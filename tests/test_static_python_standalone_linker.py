"""Finite standalone capture wiring; inert fixtures are not a real LLD build."""

from __future__ import annotations

import json
import platform
import shutil
import struct
import subprocess
import sys
import time

import pytest

from tests.test_static_python_link_dependency_capture import base_recipe, record, sha
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import link_dependency_capture as capture
from tools.static_python_rsi_fixture import recipe, standalone_linker
from tools.static_python_rsi_fixture.command_input_graph import validate_dependency_command_graph
from tools.static_python_rsi_fixture.installation_profile import prepare_rsi_installation_profile
from tools.static_python_rsi_fixture.runtime_closure import canonical


def profile_bytes(linker=b"inert", *, crt_mode="crt1-crti-crtn",
                  archives=("libc.a", "libcompiler_rt.a"), crt=b"inert"):
    names = ["crt1.o", *archives]
    if crt_mode == "crt1-crti-crtn":
        names += ["crti.o", "crtn.o"]
    inputs = [record(standalone_linker.LINKER_PATH, linker, True),
              *(record("standalone-linker/support/" + name, crt if name == "crt1.o" else b"inert")
                for name in names)]
    return canonical({"schema": standalone_linker.PROFILE_SCHEMA, "target": "x86_64-linux-musl",
                      "linker_execution": "static-x86_64-elf", "crt_mode": crt_mode,
                      "archives": list(archives), "inputs": sorted(inputs, key=lambda row: row["path"])})


def generate(monkeypatch, base, profile):
    monkeypatch.setattr(capture, "prepare_cpython_dependency_recipe", lambda *a, **kw: base)
    return standalone_linker.prepare_cpython_standalone_link_recipe(
        object(), standalone_profile_bytes=profile, expected_standalone_profile_sha256=sha(profile),
        source_inventory_bytes=b"", expected_source_inventory_sha256="", zig_manifest_bytes=b"",
        configuration_header=b"", expected_configuration_sha256="",
    )


def validation(generated, profile):
    return {"expected_recipe_sha256": generated.sha256, "manifest_bytes": generated.manifest_bytes,
            "expected_manifest_sha256": sha(generated.manifest_bytes),
            "standalone_profile_bytes": profile, "expected_standalone_profile_sha256": sha(profile)}


@pytest.fixture
def vector(monkeypatch):
    base = base_recipe(sha(b"prep"), [record("unit.c")],
                       [record("lib/crt.o"), record("zig", executable=True)])
    profile = profile_bytes()
    return base, generate(monkeypatch, base, profile), profile


def test_opt_in_preserves_every_compilation_archive_and_old_recipe(vector):
    base, generated, profile = vector
    before, after = json.loads(base.recipe_bytes), json.loads(generated.recipe_bytes)
    wire, compiler, linker = capture.validate_dependency_capture_plan(
        generated.recipe_bytes, **validation(generated, profile))
    validate_dependency_command_graph(wire)
    assert len(compiler) == 3 and len(linker) == 2
    assert b"standalone-linker" not in base.recipe_bytes
    assert b"--dependency-file" not in base.recipe_bytes
    for old_stage, new_stage in zip(before["stages"], after["stages"], strict=True):
        for old, new in zip(old_stage["commands"], new_stage["commands"], strict=True):
            if old["argv"][:2] == ["@toolchain/zig", "cc"] and "-c" not in old["argv"]:
                assert new["argv"][0] == "@toolchain/" + standalone_linker.LINKER_PATH
                assert new["argv"][-2] == "--dependency-file"
                assert new["outputs"][:-1] == old["outputs"]
                assert "-Xlinker" not in new["argv"]
            else:
                assert new == old
    manifest = json.loads(generated.manifest_bytes)
    assert manifest["standalone_profile_sha256"] == sha(profile)
    assert manifest["base_recipe_sha256"] == base.sha256
    assert all(manifest[name] is False for name in capture._FALSE_CLAIMS)


@pytest.mark.parametrize("crt_mode", ["crt1", "crt1-crti-crtn"])
@pytest.mark.parametrize("archives", [("libc.a", "libcompiler_rt.a"),
                                     ("libc.a", "libzigc.a", "libcompiler_rt.a"),
                                     ("libc.a", "libubsan_rt.a", "libcompiler_rt.a"),
                                     ("libc.a", "libzigc.a", "libubsan_rt.a", "libcompiler_rt.a")])
def test_finite_crt_and_archive_selections_are_explicit(monkeypatch, crt_mode, archives):
    base = base_recipe(sha(b"prep"), [record("unit.c")],
                       [record("lib/crt.o"), record("zig", executable=True)])
    profile = profile_bytes(crt_mode=crt_mode, archives=archives)
    generated = generate(monkeypatch, base, profile)
    capture.validate_dependency_capture_plan(generated.recipe_bytes, **validation(generated, profile))


@pytest.mark.parametrize("mutation", ["extra_key", "target", "loader", "crt", "missing_archive",
                                     "extra_archive", "duplicate_archive", "archive_order",
                                     "missing_input", "extra_input", "support_executable",
                                     "linker_data", "empty_input", "bool_size", "unsorted"])
def test_unknown_missing_additional_or_invalid_profile_inputs_refuse(monkeypatch, vector, mutation):
    base, _, raw = vector
    profile = json.loads(raw)
    if mutation == "extra_key":
        profile["authority"] = True
    elif mutation == "target":
        profile["target"] = "host"
    elif mutation == "loader":
        profile["linker_execution"] = "ambient-dynamic-loader"
    elif mutation == "crt":
        profile["crt_mode"] = "discovered"
    elif mutation == "missing_archive":
        profile["archives"].remove("libc.a")
    elif mutation == "extra_archive":
        profile["archives"].insert(1, "libunknown.a")
    elif mutation == "duplicate_archive":
        profile["archives"].append("libc.a")
    elif mutation == "archive_order":
        profile["archives"].reverse()
    elif mutation == "missing_input":
        profile["inputs"].pop()
    elif mutation == "extra_input":
        profile["inputs"].append(record("standalone-linker/support/extra.a"))
        profile["inputs"].sort(key=lambda row: row["path"])
    elif mutation == "support_executable":
        profile["inputs"][-1]["executable"] = True
    elif mutation == "linker_data":
        profile["inputs"][0]["executable"] = False
    elif mutation == "empty_input":
        profile["inputs"][-1]["size"] = 0
    elif mutation == "bool_size":
        profile["inputs"][-1]["size"] = True
    else:
        profile["inputs"].reverse()
    with pytest.raises(standalone_linker.StandaloneLinkerError):
        generate(monkeypatch, base, canonical(profile))


@pytest.mark.parametrize("mutation", ["no_profile", "no_pin", "wrong_pin", "changed_profile",
                                     "old_schema", "wrong_profile_manifest_pin"])
def test_self_consistent_recipe_manifest_cannot_replace_independent_profile_pin(vector, mutation):
    _, generated, profile = vector
    kwargs = validation(generated, profile)
    if mutation == "no_profile":
        kwargs.pop("standalone_profile_bytes")
    elif mutation == "no_pin":
        kwargs.pop("expected_standalone_profile_sha256")
    elif mutation == "wrong_pin":
        kwargs["expected_standalone_profile_sha256"] = sha(b"different")
    elif mutation == "changed_profile":
        kwargs["standalone_profile_bytes"] = profile_bytes(linker=b"replaced")
        kwargs["expected_standalone_profile_sha256"] = sha(kwargs["standalone_profile_bytes"])
    else:
        manifest = json.loads(generated.manifest_bytes)
        if mutation == "old_schema":
            manifest["schema"] = "lunar-cpython-compiler-linker-dependency-recipe-v1"
            del manifest["standalone_profile_sha256"]
        else:
            manifest["standalone_profile_sha256"] = sha(b"replaced")
        kwargs["manifest_bytes"] = canonical(manifest)
        kwargs["expected_manifest_sha256"] = sha(kwargs["manifest_bytes"])
    with pytest.raises(capture.LinkDependencyError):
        capture.validate_dependency_capture_plan(generated.recipe_bytes, **kwargs)


@pytest.mark.parametrize("mutation", ["extra_option", "no_depfile", "response", "search", "joined_depfile",
                                     "additional_archive", "missing_crt", "oversized_depfile"])
def test_only_reviewed_direct_link_command_and_capture_pass(vector, mutation):
    _, generated, _profile = vector
    wire = json.loads(generated.recipe_bytes)
    command = wire["stages"][1]["commands"][1]
    if mutation == "extra_option":
        command["argv"].insert(-2, "--trace")
    elif mutation == "no_depfile":
        del command["argv"][-2:]
    elif mutation == "response":
        command["argv"].insert(-2, "@toolchain/standalone-linker/support/response")
    elif mutation == "search":
        command["argv"].insert(-2, "-L/usr/lib")
    elif mutation == "joined_depfile":
        command["argv"][-2:] = ["--dependency-file=" + command["argv"][-1]]
    elif mutation == "additional_archive":
        command["argv"].insert(command["argv"].index("--end-group"), "@toolchain/lib/crt.o")
    elif mutation == "missing_crt":
        command["argv"].remove("@toolchain/standalone-linker/support/crti.o")
    else:
        command["outputs"][1]["max_size"] += 1
    with pytest.raises(ValueError):
        # Exercise the actual finite grammar, without a stale manifest pin
        # making the refusal happen before the command under test is checked.
        if mutation == "oversized_depfile":
            validate_dependency_command_graph(wire)
        else:
            standalone_linker._standalone_link(command)


def test_resigned_recipe_inventory_cannot_replace_independent_profile(vector):
    _, generated, profile = vector
    wire = json.loads(generated.recipe_bytes)
    row = next(row for row in wire["inputs"]["toolchain"]
               if row["path"] == "standalone-linker/support/libc.a")
    row.update(size=len(b"replacement"), sha256=sha(b"replacement"))
    raw = canonical(wire)
    manifest = json.loads(generated.manifest_bytes)
    manifest["recipe_sha256"] = sha(raw)
    manifest_raw = canonical(manifest)
    with pytest.raises(capture.LinkDependencyError):
        capture.validate_dependency_capture_plan(
            raw, **{**validation(generated, profile), "expected_recipe_sha256": sha(raw),
                    "manifest_bytes": manifest_raw, "expected_manifest_sha256": sha(manifest_raw)})


def linker_comparison_vector(generated, profile):
    manifest = json.loads(generated.manifest_bytes)
    artifacts = {}
    for link in manifest["links"]:
        paths = [ref.replace("@work/", "/attempt/work/").replace("@toolchain/", "/attempt/toolchain/")
                 for ref in link["explicit_inputs"]]
        artifacts[link["depfile"]] = (link["target"].replace("@work/", "/attempt/work/")
                                     + ": " + " ".join(paths) + "\n").encode()
    wire = json.loads(generated.recipe_bytes)
    outputs = [record(out["path"], artifacts.get(out["path"], b"output"), out["executable"])
               for stage in wire["stages"] for command in stage["commands"] for out in command["outputs"]]
    inventory = canonical(sorted(outputs, key=lambda row: row["path"]))
    return {**validation(generated, profile), "output_inventory_bytes": inventory,
            "expected_output_inventory_sha256": sha(inventory), "dependency_artifacts": artifacts,
            "source_root": "/attempt/source", "toolchain_root": "/attempt/toolchain", "work_root": "/attempt/work"}


def test_original_comparator_consumes_exact_standalone_linker_input_set(vector):
    _, generated, profile = vector
    result = capture.compare_linker_dependencies(
        generated.recipe_bytes, **linker_comparison_vector(generated, profile)).to_dict()
    assert len(result["links"]) == 2
    assert all(result[key] is False for key in capture._FALSE_CLAIMS)


@pytest.mark.parametrize("mutation", ["missing", "extra_pinned", "external", "unlisted", "future"])
def test_missing_additional_external_or_future_reported_inputs_refuse(vector, mutation):
    _, generated, profile = vector
    kwargs = linker_comparison_vector(generated, profile)
    depfile = next(iter(kwargs["dependency_artifacts"]))
    raw = kwargs["dependency_artifacts"][depfile]
    if mutation == "missing":
        raw = raw.replace(b" /attempt/toolchain/standalone-linker/support/libc.a", b"")
    else:
        extra = {"extra_pinned": "/attempt/toolchain/lib/crt.o", "external": "/usr/lib/private.a",
                 "unlisted": "/attempt/toolchain/standalone-linker/support/unknown.a",
                 "future": "/attempt/work/bin/lunar-openevolve"}[mutation]
        raw = raw.rstrip(b"\n") + b" " + extra.encode() + b"\n"
    kwargs["dependency_artifacts"][depfile] = raw
    rows = json.loads(kwargs["output_inventory_bytes"])
    for row in rows:
        if row["path"] == depfile:
            row.update(size=len(raw), sha256=sha(raw))
    kwargs["output_inventory_bytes"] = canonical(rows)
    kwargs["expected_output_inventory_sha256"] = sha(kwargs["output_inventory_bytes"])
    with pytest.raises(capture.LinkDependencyError):
        capture.compare_linker_dependencies(generated.recipe_bytes, **kwargs)


def elf_header(segment):
    """Structural gate vector only; not a runnable or accepted binary."""
    raw = bytearray(120)
    raw[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<H", raw, 18, 62)
    struct.pack_into("<Q", raw, 32, 64)
    struct.pack_into("<HH", raw, 54, 56, 1)
    struct.pack_into("<I", raw, 64, segment)
    return bytes(raw)


@pytest.mark.parametrize("linker", [b"not-elf", elf_header(2), elf_header(3)])
def test_dynamic_or_non_elf_linker_refuses_before_original_runner(tmp_path, monkeypatch, linker):
    profile = profile_bytes(linker)
    base = base_recipe(sha(b"prep"), [record("unit.c")],
                       [record("lib/crt.o"), record("zig", executable=True)])
    generated = generate(monkeypatch, base, profile)
    tools = tmp_path / "tools"
    path = tools / standalone_linker.LINKER_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(linker)
    path.chmod(0o700)
    monkeypatch.setattr(consumer, "run_pinned_build_v3", lambda *a, **kw: pytest.fail("no dispatch permitted"))
    with pytest.raises(consumer.BuildDependencyError, match="execution_failed") as error:
        consumer.run_dependency_checked_build(
            object(), recipe_bytes=generated.recipe_bytes, **validation(generated, profile),
            source_root=tmp_path / "source", toolchain_root=tools,
            workspace=tmp_path / "attempt", deadline=time.monotonic() + 10,
        )
    assert error.value.execution_report is None and not (tmp_path / "attempt").exists()


def test_static_gate_is_followed_by_original_pin_recheck(tmp_path, monkeypatch):
    from tools.static_python_rsi_fixture import podman_custody

    linker = elf_header(1)
    profile = profile_bytes(linker)
    path = tmp_path / standalone_linker.LINKER_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(linker)
    path.chmod(0o700)
    original = podman_custody._static_executable

    def drift(root, row, checkpoint):
        original(root, row, checkpoint)
        path.write_bytes(linker + b"changed")

    monkeypatch.setattr(podman_custody, "_static_executable", drift)
    with pytest.raises(consumer.BuildDependencyError, match="file_pin"):
        standalone_linker.verify_standalone_linker_input(
            profile, expected_profile_sha256=sha(profile), toolchain_root=tmp_path, checkpoint=lambda: None)


_HELPER = r'''
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
static int emit(const char *path, const char *text, int executable) {
    FILE *f = fopen(path, "wb"); if (!f) return 20;
    if (fputs(text, f) < 0 || fclose(f)) return 21;
    return chmod(path, executable ? 0700 : 0600) ? 22 : 0;
}
static void escaped(FILE *f, const char *path) {
    for (; *path; path++) {
        if (*path == '$') fputc('$', f);
        else if (strchr(" \\:#", *path)) fputc('\\', f);
        fputc(*path, f);
    }
}
static int starts(const char *path, const char *text) {
    char value[32] = {0}; FILE *f = fopen(path, "rb"); if (!f) return 0;
    size_t n = fread(value, 1, sizeof(value) - 1, f); fclose(f);
    return n >= strlen(text) && !strncmp(value, text, strlen(text));
}
int main(int argc, char **argv) {
    if (argc >= 4 && !strcmp(argv[1], "ar")) return emit(argv[3], "inert-archive\n", 0);
    const char *target = NULL, *dep = NULL, *source = NULL, *crt = NULL;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-o") && i + 1 < argc) target = argv[++i];
        else if (!strcmp(argv[i], "-c") && i + 1 < argc) source = argv[++i];
        else if ((!strcmp(argv[i], "-MF") || !strcmp(argv[i], "--dependency-file")) && i + 1 < argc)
            dep = argv[++i];
        else if (strstr(argv[i], "/support/crt1.o")) crt = argv[i];
    }
    if (!target || !dep) return 23;
    if (crt && starts(crt, "nonzero")) return 19;
    if (emit(target, source ? "inert-object\n" : "inert-image\n", !source)) return 24;
    FILE *f = fopen(dep, "wb"); if (!f) return 25;
    escaped(f, target); fputs(":", f);
    if (source) { fputc(' ', f); escaped(f, source); }
    else {
        for (int i = 1; i < argc; i++) {
            size_t n = strlen(argv[i]);
            if (crt && starts(crt, "missing") && !strcmp(argv[i], crt)) continue;
            if (strcmp(argv[i], target) && n > 2 &&
                (!strcmp(argv[i] + n - 2, ".o") || !strcmp(argv[i] + n - 2, ".a"))) {
                fputc(' ', f); escaped(f, argv[i]);
            }
        }
        if (crt && starts(crt, "external")) fputs(" /ambient/private.a", f);
    }
    fputc('\n', f); return fclose(f) ? 26 : 0;
}
'''


@pytest.fixture(scope="module")
def inert_static_tool(tmp_path_factory):
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "AMD64"}:
        pytest.skip("actual standalone helper requires native Linux x86_64 static ELF execution")
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("actual standalone helper requires a local static C compiler")
    root = tmp_path_factory.mktemp("standalone-inert-static-helper")
    probe, source, target = root / "probe.c", root / "helper.c", root / "helper"
    probe.write_text("int main(void) { return 0; }\n")
    result = subprocess.run([compiler, "-static", str(probe), "-o", str(root / "probe")],
                            capture_output=True, timeout=30, check=False)
    if result.returncode:
        pytest.skip("local C compiler cannot link the static native fixture")
    source.write_text(_HELPER)
    subprocess.run([compiler, "-static", "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target)],
                   capture_output=True, timeout=30, check=True)
    return target


@pytest.fixture
def actual_build(tmp_path, monkeypatch, inert_static_tool):
    path = recipe.emit_rsi_launch_source_plan(tmp_path / "preparation")
    prep = prepare_rsi_installation_profile(
        reviewed_build_inputs=(recipe._ROOT / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes(),
        reviewed_overlay=(recipe._ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes(),
        source_plan=path.read_bytes(), expected_source_plan_sha256=sha(path.read_bytes()),
        source_assets={p.name: p.read_bytes() for p in (path.parent / "assets").iterdir()},
    )

    def prepare(crt=b"inert"):
        source, tools = tmp_path / "source", tmp_path / "tools"
        source.mkdir()
        (source / "unit.c").write_bytes(b"inert")
        (tools / "lib").mkdir(parents=True)
        (tools / "lib/crt.o").write_bytes(b"inert")
        shutil.copyfile(inert_static_tool, tools / "zig")
        (tools / "zig").chmod(0o700)
        binary = inert_static_tool.read_bytes()
        profile = profile_bytes(binary, crt=crt)
        for row in json.loads(profile)["inputs"]:
            destination = tools / row["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(binary if row["executable"] else crt if destination.name == "crt1.o" else b"inert")
            destination.chmod(0o700 if row["executable"] else 0o600)
        base = base_recipe(prep.sha256, [record("unit.c")],
                           [record("lib/crt.o"), record("zig", binary, True)])
        generated = generate(monkeypatch, base, profile)
        return prep, {"recipe_bytes": generated.recipe_bytes, **validation(generated, profile),
                      "source_root": source, "toolchain_root": tools,
                      "workspace": tmp_path / "attempt with space", "deadline": time.monotonic() + 20}

    return prepare


def test_actual_static_inert_process_uses_original_runner_report_and_consumer(actual_build, monkeypatch):
    prep, kwargs = actual_build()
    original, calls = consumer.run_pinned_build_v3, []

    def run(*args, **options):
        calls.append(options)
        return original(*args, **options)

    monkeypatch.setattr(consumer, "run_pinned_build_v3", run)
    result = consumer.run_dependency_checked_build(prep, **kwargs)
    assert len(calls) == 1 and calls[0]["deadline"] == kwargs["deadline"]
    assert result.execution_report.completed_stages == ("configure", "freeze", "compile", "link")
    root = kwargs["workspace"]
    evidence = (root / "dependency-report.json").read_bytes()
    assert sha(evidence) == result.evidence_sha256
    assert json.loads(evidence)["execution_report_sha256"] == sha((root / "report.json").read_bytes())
    comparisons = json.loads((root / "linker-dependency-comparison.json").read_bytes())
    assert len(comparisons["links"]) == 2
    assert all(comparisons[name] is False for name in capture._FALSE_CLAIMS)


@pytest.mark.parametrize("crt", [b"missing", b"external", b"nonzero"])
def test_actual_bad_link_report_or_nonzero_retains_attempt_without_success(actual_build, crt):
    prep, kwargs = actual_build(crt)
    with pytest.raises(consumer.BuildDependencyError) as error:
        consumer.run_dependency_checked_build(prep, **kwargs)
    assert error.value.execution_report is not None
    assert (kwargs["workspace"] / "report.json").exists()
    assert not (kwargs["workspace"] / "dependency-report.json").exists()


@pytest.mark.parametrize("kind", ["output", "report", "linker", "support"])
def test_actual_readback_drift_refuses_current_resigned_bytes(actual_build, monkeypatch, kind):
    prep, kwargs = actual_build()
    original = consumer.run_pinned_build_v3

    def drift(*args, **options):
        report = original(*args, **options)
        if kind == "output":
            target = options["workspace"] / "work/bin/lunar-openevolve"
        elif kind == "report":
            target = options["workspace"] / "report.json"
        elif kind == "linker":
            target = options["toolchain_root"] / standalone_linker.LINKER_PATH
        else:
            target = options["toolchain_root"] / "standalone-linker/support/libc.a"
        target.write_bytes(b"replacement")
        return report

    monkeypatch.setattr(consumer, "run_pinned_build_v3", drift)
    with pytest.raises(consumer.BuildDependencyError) as error:
        consumer.run_dependency_checked_build(prep, **kwargs)
    assert error.value.execution_report.status == "complete"
    assert not (kwargs["workspace"] / "dependency-report.json").exists()
