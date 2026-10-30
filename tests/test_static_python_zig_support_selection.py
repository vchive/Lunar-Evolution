"""Inert native selection/capture tests; no real Zig or generated ELF executes."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import replace

import pytest

from tests.test_static_python_link_dependency_capture import record, sha
from tests.test_static_python_standalone_linker import elf_header
from tests.test_static_python_zig_support_candidates import _HELPER
from tools.static_python_rsi_fixture import recipe
from tools.static_python_rsi_fixture import zig_support_candidates as candidates
from tools.static_python_rsi_fixture import zig_support_selection as selected
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError
from tools.static_python_rsi_fixture.installation_profile import prepare_rsi_installation_profile
from tools.static_python_rsi_fixture.runtime_closure import canonical
from tools.static_python_rsi_fixture.zig_lld_linker import PROFILE_SCHEMA

_CAPTURE = r'''
static void escaped(FILE *f, const char *path) {
    for (; *path; path++) {
        if (*path == '$') fputc('$', f);
        else if (strchr(" \\:#", *path)) fputc('\\', f);
        fputc(*path, f);
    }
}
int main(int argc, char **argv) {
    if (argc < 2 || strcmp(argv[1], "ld.lld")) return generation_main(argc, argv);
    const char *target = NULL, *dep = NULL, *lib = getenv("ZIG_LIB_DIR");
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "-o") && i + 1 < argc) target = argv[++i];
        else if (!strcmp(argv[i], "--dependency-file") && i + 1 < argc) dep = argv[++i];
    }
    if (!target || !dep || !lib) return 40;
    char path[8192], mode[64] = {0};
    if (snprintf(path, sizeof(path), "%s/mode", lib) >= (int)sizeof(path)) return 41;
    FILE *m = fopen(path, "rb"); if (!m) return 42;
    size_t got = fread(mode, 1, sizeof(mode) - 1, m); fclose(m); mode[got] = 0;
    if (!strcmp(mode, "nonzero-link")) return 43;
    const unsigned char elf[] = {ELF_BYTES};
    FILE *f = fopen(target, "wb"); if (!f) return 44;
    if (!strcmp(mode, "bad-elf")) { if (fputs("unexecutable", f) < 0) return 45; }
    else if (fwrite(elf, 1, sizeof(elf), f) != sizeof(elf)) return 46;
    if (fclose(f) || chmod(target, 0700)) return 47;
    f = fopen(dep, "wb"); if (!f) return 48;
    escaped(f, !strcmp(mode, "wrong-target") ? "/wrong/target" : target);
    fputs(":", f);
    for (int i = 2; i < argc; i++) {
        size_t n = strlen(argv[i]);
        if (strcmp(argv[i], target) && n > 2 &&
            (!strcmp(argv[i] + n - 2, ".o") || !strcmp(argv[i] + n - 2, ".a"))) {
            if (!strcmp(mode, "missing-input") && strstr(argv[i], "/crt1.o")) continue;
            fputc(' ', f); escaped(f, argv[i]);
        }
    }
    if (!strcmp(mode, "extra-input")) fputs(" /ambient/undeclared.a", f);
    fputc('\n', f); return fclose(f) ? 49 : 0;
}
'''


@pytest.fixture(scope="module")
def capture_native_helper(tmp_path_factory):
    root = tmp_path_factory.mktemp("support-selection-native")
    source, target = root / "helper.c", root / "helper"
    source.write_text(_HELPER.replace("int main(int argc, char **argv)",
                                     "static int generation_main(int argc, char **argv)")
                      + _CAPTURE.replace("ELF_BYTES", ",".join(str(b) for b in elf_header(1))))
    compiler = shutil.which("cc")
    assert compiler is not None
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target)],
                   check=True, capture_output=True, timeout=30)
    return target


@pytest.fixture
def selection_case(tmp_path, monkeypatch, capture_native_helper):
    plan = recipe.emit_rsi_launch_source_plan(tmp_path / "preparation")
    prep = prepare_rsi_installation_profile(
        reviewed_build_inputs=(recipe._ROOT / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes(),
        reviewed_overlay=(recipe._ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes(),
        source_plan=plan.read_bytes(), expected_source_plan_sha256=sha(plan.read_bytes()),
        source_assets={p.name: p.read_bytes() for p in (plan.parent / "assets").iterdir()},
    )
    toolchain = tmp_path / "tools with space"
    (toolchain / "lib").mkdir(parents=True)
    shutil.copyfile(capture_native_helper, toolchain / "zig")
    (toolchain / "zig").chmod(0o700)

    def prepare(mode=b"normal"):
        (toolchain / "lib/mode").write_bytes(mode)
        tools = [record("lib/mode", mode), record("zig", capture_native_helper.read_bytes(), True)]
        monkeypatch.setattr(candidates, "complete_zig_inventory", lambda _raw: tools)
        monkeypatch.setattr(selected, "complete_zig_inventory", lambda _raw: tools)
        deadline = time.monotonic() + 30
        bundle = candidates.run_zig_support_candidate_preparation(
            prep, zig_manifest_bytes=b"inert inventory", toolchain_root=toolchain,
            workspace=tmp_path / "generation", deadline=deadline,
        )
        mapping = (("zig-lld/support/crt1.o", "candidates/global/o/second/crt1.o"),
                   ("zig-lld/support/libc.a", "candidates/global/o/archive/libc.a"),
                   ("zig-lld/support/libcompiler_rt.a", "candidates/global/o/archive/libcompiler_rt.a"))
        files = dict(bundle.files)
        profile = canonical({"schema": PROFILE_SCHEMA, "target": "x86_64-linux-musl",
                             "linker_execution": "static-x86_64-elf", "crt_mode": "crt1",
                             "archives": ["libc.a", "libcompiler_rt.a"],
                             "inputs": sorted([tools[1], *(record(p, files[c]) for p, c in mapping)],
                                              key=lambda row: row["path"])})
        arguments = {"bundle": bundle, "expected_bundle_sha256": bundle.sha256,
                     "zig_manifest_bytes": b"inert inventory", "zig_lld_profile_bytes": profile,
                     "expected_zig_lld_profile_sha256": sha(profile), "selections": mapping}
        selection = selected.prepare_zig_lld_support_selection(prep, **arguments)
        controls = {"selection": selection, "expected_selection_sha256": selection.sha256,
                    "zig_manifest_bytes": b"inert inventory", "zig_lld_profile_bytes": profile,
                    "expected_zig_lld_profile_sha256": sha(profile),
                    "toolchain_root": toolchain, "deadline": deadline}
        return prep, arguments, controls

    return prepare


def test_explicit_selection_preserves_full_candidate_identity_and_stages_once(selection_case):
    prep, arguments, controls = selection_case()
    selection = controls["selection"]
    assert dict(selection.files)["zig-lld/support/crt1.o"] == b"different crt1 candidate\n"
    facts = json.loads(selection.manifest_bytes)
    assert next(r for r in facts["support"] if r["path"].endswith("crt1.o"))["candidate_path"] == (
        "candidates/global/o/second/crt1.o")
    assert facts["candidate_bundle_sha256"] == arguments["bundle"].sha256
    assert facts["seed_executed"] is False and facts["production_admission"] is False
    selected.stage_zig_lld_support_selection(prep, **controls)
    for path, raw in selection.files:
        assert (controls["toolchain_root"] / path).read_bytes() == raw
    with pytest.raises(FileExistsError):
        selected.stage_zig_lld_support_selection(prep, **controls)


@pytest.mark.parametrize("kind", ["missing", "duplicate-role", "duplicate-source", "different-crt", "wrong-name",
                                 "profile-pin", "bundle-pin", "zig-pin"])
def test_independent_mapping_and_pins_refuse_without_staging(selection_case, kind):
    prep, args, controls = selection_case()
    mapping = args["selections"]
    if kind == "missing":
        args["selections"] = mapping[:-1]
    elif kind == "duplicate-role":
        args["selections"] = (*mapping[:-1], mapping[0])
    elif kind == "duplicate-source":
        args["selections"] = (*mapping[:-1], (mapping[-1][0], mapping[0][1]))
    elif kind == "different-crt":
        args["selections"] = ((mapping[0][0], "candidates/global/o/first/crt1.o"), *mapping[1:])
    elif kind == "wrong-name":
        args["selections"] = ((mapping[0][0], mapping[1][1]), *mapping[1:])
    elif kind == "profile-pin":
        args["expected_zig_lld_profile_sha256"] = "0" * 64
    elif kind == "bundle-pin":
        args["expected_bundle_sha256"] = "0" * 64
    else:
        profile = json.loads(args["zig_lld_profile_bytes"])
        next(row for row in profile["inputs"] if row["path"] == "zig")["sha256"] = "0" * 64
        args["zig_lld_profile_bytes"] = canonical(profile)
        args["expected_zig_lld_profile_sha256"] = sha(args["zig_lld_profile_bytes"])
    with pytest.raises((selected.ZigSupportSelectionError, candidates.ZigSupportCandidateError, ValueError)):
        selected.prepare_zig_lld_support_selection(prep, **args)
    assert not (controls["toolchain_root"] / "zig-lld").exists()


@pytest.mark.parametrize("kind", ["bytes", "authority", "selection-pin", "interrupted"])
def test_staging_drift_and_control_refuse_before_creating_namespace(selection_case, kind):
    prep, _, controls = selection_case()
    selection = controls["selection"]
    if kind == "bytes":
        controls["selection"] = replace(selection, files=((selection.files[0][0], b"drift"), *selection.files[1:]))
    elif kind == "authority":
        facts = json.loads(selection.manifest_bytes)
        facts["production_admission"] = True
        controls["selection"] = replace(selection, manifest_bytes=canonical(facts))
        controls["expected_selection_sha256"] = controls["selection"].sha256
    elif kind == "selection-pin":
        controls["expected_selection_sha256"] = "0" * 64
    else:
        controls["interrupted"] = lambda: True
    with pytest.raises(selected.ZigSupportSelectionError):
        selected.stage_zig_lld_support_selection(prep, **controls)
    assert not (controls["toolchain_root"] / "zig-lld").exists()


@pytest.mark.parametrize("mode", [b"normal", b"wrong-target", b"missing-input", b"extra-input", b"bad-elf", b"nonzero-link"])
def test_actual_inert_direct_capture_checks_original_report_elf_and_exact_dependencies(
    selection_case, tmp_path, monkeypatch, mode,
):
    prep, _, controls = selection_case(mode)
    selected.stage_zig_lld_support_selection(prep, **controls)
    original_gate = selected._static_executable
    gates = []

    def inert_tool_gate(root, row, check):
        gates.append(row["path"])
        if row["path"] == "zig":
            # The test helper is a host binary, not an approved static Zig.
            selected._read_pin(root, row, check)
        else:
            original_gate(root, row, check)

    monkeypatch.setattr(selected, "_static_executable", inert_tool_gate)
    workspace = tmp_path / "capture with space"
    if mode != b"normal":
        with pytest.raises((selected.ZigSupportSelectionError, BuildExecutionError)):
            selected.run_selected_zig_lld_seed_capture(prep, **controls, workspace=workspace)
        assert (workspace / "attempt/report.json").exists()
        assert not (workspace / "selected-seed-capture.json").exists()
        return
    raw = selected.run_selected_zig_lld_seed_capture(prep, **controls, workspace=workspace)
    facts = json.loads(raw)
    assert gates == ["zig", "support/seed"]
    assert facts["seed_executed"] is False and facts["production_admission"] is False
    assert facts["selection_sha256"] == controls["selection"].sha256
    assert len(facts["actual_link_dependencies"]) == 6
    assert facts["report_sha256"] == sha((workspace / "attempt/report.json").read_bytes())
    assert (workspace / "selected-seed-capture.json").read_bytes() == raw
    assert (workspace / "attempt/work/support/seed").read_bytes() == elf_header(1)
