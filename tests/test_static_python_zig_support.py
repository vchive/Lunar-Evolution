"""Actual inert processes for support generation and the original consumer.

The test executable is not Zig and its artifacts are not a runtime. No real
CPython, solver, cache acceptance or immutable-generation authority is claimed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import replace

import pytest

from tests.test_static_python_link_dependency_capture import base_recipe, instrument, record, sha
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import recipe
from tools.static_python_rsi_fixture import zig_support as support
from tools.static_python_rsi_fixture.command_input_graph import validate_dependency_command_graph
from tools.static_python_rsi_fixture.installation_profile import prepare_rsi_installation_profile
from tools.static_python_rsi_fixture.link_dependency_capture import (
    LinkDependencyError,
    compare_linker_dependencies,
    validate_dependency_capture_plan,
)
from tools.static_python_rsi_fixture.runtime_closure import canonical

_HELPER = r'''
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
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
int main(int argc, char **argv) {
    if (argc >= 4 && !strcmp(argv[1], "ar")) return emit(argv[3], "inert-archive\n", 0);
    const char *target = NULL, *dep = NULL, *source = NULL, *libdir = getenv("ZIG_LIB_DIR");
    int explicit = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-o") && i + 1 < argc) target = argv[++i];
        else if (!strcmp(argv[i], "-c") && i + 1 < argc) source = argv[++i];
        else if (!strcmp(argv[i], "-MF") && i + 1 < argc) dep = argv[++i];
        else if (!strcmp(argv[i], "--dependency-file") && i + 2 < argc) dep = argv[i + 2];
        else if (!strcmp(argv[i], "-nostdlib")) explicit = 1;
    }
    if (!target || !libdir || emit(target, source ? "inert-object\n" : "unexecutable-seed\n", !source)) return 23;
    if (source && !dep) return 0;
    if (!dep) return 24;
    FILE *f = fopen(dep, "wb"); if (!f) return 25;
    escaped(f, target); fputs(":", f);
    if (source) { fputc(' ', f); escaped(f, source); }
    else {
        for (int i = 1; i < argc; i++) {
            size_t n = strlen(argv[i]);
            if (strcmp(argv[i], target) && n > 2 &&
                (!strcmp(argv[i] + n - 2, ".o") || !strcmp(argv[i] + n - 2, ".a"))) {
                fputc(' ', f); escaped(f, argv[i]);
            }
        }
        if (!explicit) {
            const char *cache = getenv("ZIG_GLOBAL_CACHE_DIR");
            if (!cache || mkdir(cache, 0700)) return 26;
            char parent[8192], path[8192], modepath[8192], mode[64] = {0};
            if (snprintf(parent, sizeof(parent), "%s/o", cache) >= (int)sizeof(parent) || mkdir(parent, 0700)) return 27;
            if (snprintf(modepath, sizeof(modepath), "%s/mode", libdir) >= (int)sizeof(modepath)) return 28;
            FILE *m = fopen(modepath, "rb"); if (!m) return 29;
            size_t got = fread(mode, 1, sizeof(mode) - 1, m); fclose(m); mode[got] = 0;
            if (!strcmp(mode, "nonzero")) return 19;
            const char *names[] = {"crt1.o", "crti.o", "crtn.o", "libc.a", "libcompiler_rt.a"};
            for (int i = 0; i < 5; i++) {
                if (!strcmp(mode, "missing") && i == 4) continue;
                if (snprintf(path, sizeof(path), "%s/%s", parent, names[i]) >= (int)sizeof(path)) return 30;
                if (!strcmp(mode, "symlink") && i == 4) {
                    if (symlink("libc.a", path)) return 31;
                } else if (emit(path, names[i], 0)) return 32;
                fputc(' ', f); escaped(f, path);
            }
            if (!strcmp(mode, "external")) fputs(" /ambient/private.a", f);
        }
    }
    fputc('\n', f); return fclose(f) ? 33 : 0;
}
'''


@pytest.fixture(scope="module")
def inert_support_tool(tmp_path_factory):
    root = tmp_path_factory.mktemp("support-inert-tool")
    source, target = root / "helper.c", root / "helper"
    source.write_text(_HELPER)
    compiler = shutil.which("cc")
    assert compiler is not None
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target)],
                   check=True, capture_output=True, timeout=30)
    return target


@pytest.fixture
def setup_support(tmp_path, monkeypatch, inert_support_tool):
    plan = recipe.emit_rsi_launch_source_plan(tmp_path / "preparation")
    preparation = prepare_rsi_installation_profile(
        reviewed_build_inputs=(recipe._ROOT / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes(),
        reviewed_overlay=(recipe._ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes(),
        source_plan=plan.read_bytes(), expected_source_plan_sha256=sha(plan.read_bytes()),
        source_assets={p.name: p.read_bytes() for p in (plan.parent / "assets").iterdir()},
    )
    toolchain = tmp_path / "tools"
    (toolchain / "lib").mkdir(parents=True)
    shutil.copyfile(inert_support_tool, toolchain / "zig")
    (toolchain / "zig").chmod(0o700)

    def prepare(mode=b"normal"):
        (toolchain / "lib/mode").write_bytes(mode)
        records = [record("lib/mode", mode), record("zig", inert_support_tool.read_bytes(), True)]
        monkeypatch.setattr(support, "complete_zig_inventory", lambda _raw: records)
        kwargs = {"zig_manifest_bytes": b"inert fake inventory", "toolchain_root": toolchain,
                  "workspace": tmp_path / "support-attempt", "deadline": time.monotonic() + 30}
        return preparation, kwargs, records
    return prepare


def test_actual_original_runner_generates_cache_and_seals_only_linker_consumed_support(setup_support):
    prep, kwargs, _ = setup_support()
    bundle = support.run_zig_support_preparation(prep, **kwargs)
    facts = json.loads(bundle.manifest_bytes)
    assert facts["seed_executed"] is False
    assert facts["seed_report_sha256"] == sha((kwargs["workspace"] / "attempt/report.json").read_bytes())
    assert {path for path, raw in bundle.files} == {"lunar-support/" + name for name in support._SUPPORT_NAMES}
    for path, raw in bundle.files:
        assert (kwargs["workspace"] / "sealed" / path).read_bytes() == raw
    for key in support._FALSE:
        assert facts[key] is False
    assert (kwargs["workspace"] / "support-observation.json").read_bytes() == bundle.manifest_bytes


@pytest.mark.parametrize("mode,reason", [(b"missing", "support_set"), (b"external", "seed_dependency"),
                                        (b"symlink", "cache_entry")])
def test_actual_bad_seed_cache_or_dependencies_never_return_a_bundle(setup_support, mode, reason):
    prep, kwargs, _ = setup_support(mode)
    with pytest.raises(support.ZigSupportError, match=reason):
        support.run_zig_support_preparation(prep, **kwargs)
    assert (kwargs["workspace"] / "attempt/report.json").exists()
    assert not (kwargs["workspace"] / "support-observation.json").exists()


def test_control_refuses_before_workspace_mutation(setup_support):
    prep, kwargs, _ = setup_support()
    with pytest.raises(support.ZigSupportError, match="interrupted"):
        support.run_zig_support_preparation(prep, **kwargs, interrupted=lambda: True)
    assert not kwargs["workspace"].exists()


def _final(prep, kwargs, records, monkeypatch, tmp_path):
    bundle = support.run_zig_support_preparation(prep, **kwargs)
    source = tmp_path / "final-source"
    source.mkdir()
    (source / "unit.c").write_bytes(b"inert")
    generated = instrument(monkeypatch, base_recipe(prep.sha256, [record("unit.c", b"inert")], records))
    monkeypatch.setattr(support, "prepare_cpython_link_dependency_recipe", lambda *a, **k: generated)
    result = support.prepare_cpython_explicit_support_recipe(
        prep, support_bundle=bundle, source_inventory_bytes=b"unused synthetic", expected_source_inventory_sha256="",
        zig_manifest_bytes=b"unused synthetic", configuration_header=b"synthetic; no pyconfig claim",
        expected_configuration_sha256="",
    )
    for path, raw in result.toolchain_additions:
        target = kwargs["toolchain_root"] / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return bundle, result, source


def test_real_original_consumer_uses_explicit_support_and_both_exact_link_comparisons(
    setup_support, monkeypatch, tmp_path,
):
    prep, kwargs, records = setup_support()
    bundle, build, source = _final(prep, kwargs, records, monkeypatch, tmp_path)
    wire, _, _ = validate_dependency_capture_plan(
        build.recipe_bytes, expected_recipe_sha256=build.sha256, manifest_bytes=build.manifest_bytes,
        expected_manifest_sha256=sha(build.manifest_bytes),
    )
    validate_dependency_command_graph(wire)
    assert b'"-nostdlib"' in build.recipe_bytes
    assert not any(flag in build.recipe_bytes for flag in (b'"-lc"', b'"-lm"', b'"-lpthread"'))
    assert json.loads(build.manifest_bytes)["support_bundle_sha256"] == bundle.sha256
    final = consumer.run_dependency_checked_build(
        prep, recipe_bytes=build.recipe_bytes, expected_recipe_sha256=build.sha256,
        manifest_bytes=build.manifest_bytes, expected_manifest_sha256=sha(build.manifest_bytes),
        source_root=source, toolchain_root=kwargs["toolchain_root"], workspace=tmp_path / "final-attempt",
        deadline=kwargs["deadline"],
    )
    assert final.execution_report.status == "complete"
    comparisons = json.loads((tmp_path / "final-attempt/linker-dependency-comparison.json").read_bytes())["links"]
    assert len(comparisons) == 2
    for link in comparisons:
        assert {name for name in link["dependencies"] if name.startswith("@toolchain/")} == {
            "@toolchain/" + path for path, _ in bundle.files}
    assert final.production_admission is False and final.implicit_link_inputs_verified is False
    # Even a declared/pinned extra toolchain input must not be accepted by the
    # explicit-support successor. Refreshing an output digest cannot grant it.
    manifest = json.loads(build.manifest_bytes)
    final_root = tmp_path / "final-attempt"
    inventory = json.loads((final_root / "dependency-output-inventory.json").read_bytes())
    artifacts = {row["depfile"]: (final_root / "work" / row["depfile"]).read_bytes()
                 for row in manifest["links"]}
    first = manifest["links"][0]["depfile"]
    artifacts[first] = artifacts[first].rstrip(b"\n") + b" " + str(
        final_root / "toolchain/lib/mode").encode() + b"\n"
    for item in inventory:
        if item["path"] == first:
            item.update(size=len(artifacts[first]), sha256=sha(artifacts[first]))
    raw = canonical(inventory)
    with pytest.raises(LinkDependencyError, match="explicit_support_input_set"):
        compare_linker_dependencies(
            build.recipe_bytes, expected_recipe_sha256=build.sha256,
            manifest_bytes=build.manifest_bytes, expected_manifest_sha256=sha(build.manifest_bytes),
            output_inventory_bytes=raw, expected_output_inventory_sha256=sha(raw),
            dependency_artifacts=artifacts, source_root=str(final_root / "source"),
            toolchain_root=str(final_root / "toolchain"), work_root=str(final_root / "work"),
        )


@pytest.mark.parametrize("kind", ["bytes", "duplicate", "authority", "toolchain", "hash", "cache-path", "scalar"])
def test_changed_bundle_never_reaches_final_recipe_dispatch(setup_support, monkeypatch, tmp_path, kind):
    prep, kwargs, records = setup_support()
    bundle, _, _ = _final(prep, kwargs, records, monkeypatch, tmp_path)
    facts, files = json.loads(bundle.manifest_bytes), list(bundle.files)
    if kind == "bytes":
        files[0] = (files[0][0], b"different")
    elif kind == "duplicate":
        files[-1] = files[0]
    elif kind == "authority":
        facts["production_admission"] = True
    elif kind == "toolchain":
        facts["zig_inventory_sha256"] = "0" * 64
    elif kind == "hash":
        facts["seed_report_sha256"] = "not-a-hash"
    elif kind == "cache-path":
        facts["support"][0]["generated_cache_path"] = "../crt1.o"
    else:
        facts["support"][0]["executable"] = 0
    changed = replace(bundle, manifest_bytes=canonical(facts), files=tuple(files))
    with pytest.raises(support.ZigSupportError, match="bundle"):
        support._bundle(changed, prep.sha256, records)


@pytest.mark.parametrize("kind", ["missing-slots", "empty-file-pair", "short-file-pair", "long-file-pair",
                                 "list-file-pair", "wrong-top-level"])
def test_malformed_bundle_shapes_raise_only_the_fixed_refusal(kind):
    if kind == "missing-slots":
        bundle = object.__new__(support.ZigSupportBundle)
    else:
        pairs = tuple(("lunar-support/" + name, name.encode()) for name in sorted(support._SUPPORT_NAMES))
        facts = {
            "schema": support._BUNDLE_SCHEMA, "target": "x86_64-linux-musl",
            "preparation_sha256": sha(b"prep"), "seed_recipe_sha256": "0" * 64,
            "seed_report_sha256": "0" * 64, "seed_depfile_sha256": "0" * 64,
            "zig_inventory_sha256": sha(canonical([])), "cache_inventory_sha256": "0" * 64,
            "support": [{**record(path, raw), "generated_cache_path": "o/" + path.split("/")[-1]}
                        for path, raw in pairs], "seed_executed": False, **support._FALSE,
        }
        bad = {"empty-file-pair": (), "short-file-pair": ("path",),
               "long-file-pair": ("path", b"data", None), "list-file-pair": ["path", b"data"]}
        if kind == "wrong-top-level":
            facts = [facts]
        else:
            pairs = (bad[kind], *pairs[1:])
        bundle = support.ZigSupportBundle(canonical(facts), pairs)
    with pytest.raises(support.ZigSupportError, match="^zig_support_bundle$"):
        support._bundle(bundle, sha(b"prep"), [])
