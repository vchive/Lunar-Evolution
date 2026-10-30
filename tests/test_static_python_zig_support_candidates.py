"""Real inert processes for finite cache candidate export, never Zig execution.

The native helper is only a test tool. Its seed is plain text and is never run;
neither its cache bytes nor their successful export establish runtime custody.
"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import time
from dataclasses import replace

import pytest

from tests.test_static_python_link_dependency_capture import record, sha
from tools.static_python_rsi_fixture import recipe
from tools.static_python_rsi_fixture import zig_support as legacy
from tools.static_python_rsi_fixture import zig_support_candidates as candidates
from tools.static_python_rsi_fixture.build_dependency_consumer import BuildDependencyError
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError
from tools.static_python_rsi_fixture.installation_profile import prepare_rsi_installation_profile
from tools.static_python_rsi_fixture.runtime_closure import canonical

_HELPER = r'''
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int directory(const char *path) {
    char buf[8192];
    if (snprintf(buf, sizeof(buf), "%s", path) >= (int)sizeof(buf)) return 10;
    for (char *p = buf + 1; *p; p++) {
        if (*p != '/') continue;
        *p = 0;
        if (mkdir(buf, 0700) && errno != EEXIST) return 11;
        *p = '/';
    }
    return mkdir(buf, 0700) && errno != EEXIST ? 12 : 0;
}
static int emit(const char *path, const char *text, int executable) {
    char parent[8192];
    if (snprintf(parent, sizeof(parent), "%s", path) >= (int)sizeof(parent)) return 13;
    char *last = strrchr(parent, '/');
    if (!last) return 14;
    *last = 0;
    if (directory(parent)) return 15;
    FILE *f = fopen(path, "wb");
    if (!f) return 16;
    if (fputs(text, f) < 0 || fclose(f)) return 17;
    return chmod(path, executable ? 0700 : 0600) ? 18 : 0;
}
static int product(const char *root, const char *relative, const char *text, int executable) {
    char path[8192];
    if (snprintf(path, sizeof(path), "%s/%s", root, relative) >= (int)sizeof(path)) return 20;
    return emit(path, text, executable);
}
int main(int argc, char **argv) {
    const char *target = NULL, *source = NULL;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-o") && i + 1 < argc) target = argv[++i];
        else if (!strcmp(argv[i], "-c") && i + 1 < argc) source = argv[++i];
        else if (!strcmp(argv[i], "--dependency-file") || !strcmp(argv[i], "-Xlinker")) return 21;
    }
    if (!target || emit(target, source ? "inert object\n" : "unexecutable seed\n", !source)) return 22;
    if (source) return 0;
    const char *global = getenv("ZIG_GLOBAL_CACHE_DIR"), *local = getenv("ZIG_LOCAL_CACHE_DIR");
    const char *lib = getenv("ZIG_LIB_DIR");
    if (!global || !local || !lib || directory(global) || directory(local)) return 23;
    char modepath[8192], mode[64] = {0};
    if (snprintf(modepath, sizeof(modepath), "%s/mode", lib) >= (int)sizeof(modepath)) return 24;
    FILE *f = fopen(modepath, "rb");
    if (!f) return 25;
    size_t got = fread(mode, 1, sizeof(mode) - 1, f);
    fclose(f); mode[got] = 0;
    if (!strcmp(mode, "nonzero")) return 19;
    if (product(global, "h/cache-metadata", "ordinary cache metadata\n", 0) ||
        product(local, "h/local-metadata", "ordinary local cache metadata\n", 0)) return 26;
    if (!strcmp(mode, "empty")) return 0;
    if (product(global, "o/first/crt1.o", "first crt1 candidate\n", 0) ||
        product(global, "o/second/crt1.o", "different crt1 candidate\n", 0) ||
        product(local, "o/third/crt1.o", "local crt1 candidate\n", 0)) return 27;
    const char *names[] = {"libc.a", "libzigc.a", "libubsan_rt.a", "libcompiler_rt.a"};
    for (int i = 0; i < 4; i++) {
        char relative[128];
        if (snprintf(relative, sizeof(relative), "o/archive/%s", names[i]) >= (int)sizeof(relative)) return 28;
        if (product(global, relative, !strcmp(mode, "empty-file") && i == 3 ? "" : names[i],
                    !strcmp(mode, "executable") && i == 3)) return 29;
    }
    char path[8192];
    if (snprintf(path, sizeof(path), "%s/o/link", global) >= (int)sizeof(path)) return 30;
    if (!strcmp(mode, "symlink") && symlink("archive/libc.a", path)) return 31;
    if (!strcmp(mode, "directory-link") && symlink("archive", path)) return 32;
    if (!strcmp(mode, "fifo") && mkfifo(path, 0600)) return 33;
    return 0;
}
'''


@pytest.fixture(scope="module")
def candidate_native_helper(tmp_path_factory):
    root = tmp_path_factory.mktemp("support-candidate-native")
    source, target = root / "helper.c", root / "helper"
    source.write_text(_HELPER)
    compiler = shutil.which("cc")
    assert compiler is not None
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target)],
                   check=True, capture_output=True, timeout=30)
    return target


@pytest.fixture
def setup_candidates(tmp_path, monkeypatch, candidate_native_helper):
    plan = recipe.emit_rsi_launch_source_plan(tmp_path / "preparation")
    preparation = prepare_rsi_installation_profile(
        reviewed_build_inputs=(recipe._ROOT / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes(),
        reviewed_overlay=(recipe._ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes(),
        source_plan=plan.read_bytes(), expected_source_plan_sha256=sha(plan.read_bytes()),
        source_assets={p.name: p.read_bytes() for p in (plan.parent / "assets").iterdir()},
    )
    toolchain = tmp_path / "tools"
    (toolchain / "lib").mkdir(parents=True)
    shutil.copyfile(candidate_native_helper, toolchain / "zig")
    (toolchain / "zig").chmod(0o700)

    def prepare(mode=b"normal"):
        (toolchain / "lib/mode").write_bytes(mode)
        records = [record("lib/mode", mode), record("zig", candidate_native_helper.read_bytes(), True)]
        monkeypatch.setattr(candidates, "complete_zig_inventory", lambda _raw: records)
        kwargs = {"zig_manifest_bytes": b"inert fake inventory", "toolchain_root": toolchain,
                  "workspace": tmp_path / "candidate-attempt", "deadline": time.monotonic() + 30}
        return preparation, kwargs, records

    return prepare


def _validate(bundle, preparation, records):
    return candidates.validate_zig_support_candidate_bundle(
        bundle, expected_bundle_sha256=bundle.sha256, preparation_sha256=preparation.sha256,
        zig_inventory_sha256=sha(canonical(records)),
    )


def test_candidate_seed_keeps_the_original_three_sources_without_link_capture(setup_candidates):
    prep, kwargs, records = setup_candidates()
    build = candidates.prepare_zig_support_candidate_recipe(prep, zig_manifest_bytes=kwargs["zig_manifest_bytes"])
    wire = json.loads(build.recipe_bytes)
    assert dict(build.sources) == legacy._SOURCE
    assert wire["inputs"]["toolchain"] == records
    assert len(wire["stages"]) == 4
    link = wire["stages"][-1]["commands"]
    assert len(link) == 1
    assert link[0]["argv"] == [
        "@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "-static", "-o", "@work/support/seed",
        "@work/support/probe.o", "@work/support/main.o", "@work/support/div.o", "-lm", "-lpthread", "-lc",
    ]
    assert [row["path"] for row in link[0]["outputs"]] == ["support/seed"]
    assert b"--dependency-file" not in build.recipe_bytes
    assert b"support/seed.d" not in build.recipe_bytes


def test_real_runner_exports_all_candidates_and_preserves_ambiguous_crt_paths(setup_candidates):
    prep, kwargs, records = setup_candidates()
    bundle = candidates.run_zig_support_candidate_preparation(prep, **kwargs)
    facts = _validate(bundle, prep, records)
    rows = facts["candidates"]
    expected = {
        "candidates/global/o/first/crt1.o": b"first crt1 candidate\n",
        "candidates/global/o/second/crt1.o": b"different crt1 candidate\n",
        "candidates/local/o/third/crt1.o": b"local crt1 candidate\n",
        **{"candidates/global/o/archive/" + name: name.encode()
           for name in ("libc.a", "libzigc.a", "libubsan_rt.a", "libcompiler_rt.a")},
    }
    assert dict(bundle.files) == expected
    assert [row["path"] for row in rows] == sorted(expected)
    for row in rows:
        assert set(row) == {"path", "size", "sha256", "executable", "cache", "cache_path"}
        assert row["path"] == "candidates/" + row["cache"] + "/" + row["cache_path"]
        assert row["executable"] is False
        assert row["sha256"] == sha(expected[row["path"]])
        sealed = kwargs["workspace"] / "sealed" / row["path"]
        assert sealed.read_bytes() == expected[row["path"]]
        assert stat.S_IMODE(sealed.stat().st_mode) == 0o400
    assert facts["seed_executed"] is False
    assert facts["support_selection_accepted"] is False
    assert facts["seed_report_sha256"] == sha((kwargs["workspace"] / "attempt/report.json").read_bytes())
    assert (kwargs["workspace"] / "support-candidates.json").read_bytes() == bundle.manifest_bytes
    assert (kwargs["workspace"] / "attempt/work/support/seed").read_bytes() == b"unexecutable seed\n"
    assert not (kwargs["workspace"] / "attempt/work/support/seed.d").exists()
    for key in legacy._FALSE:
        assert facts[key] is False
    assert not any("metadata" in path for path in dict(bundle.files))
    for role in ("global", "local"):
        raw = (kwargs["workspace"] / f"cache-{role}-inventory.json").read_bytes()
        inventory = json.loads(raw)
        assert facts["cache_inventories"][role] == {
            "sha256": sha(raw), "files": len(inventory), "bytes": sum(row["size"] for row in inventory),
        }
        assert any("metadata" in row["path"] for row in inventory)


@pytest.mark.parametrize("mode", [b"symlink", b"directory-link", b"fifo", b"executable", b"empty-file"])
def test_actual_invalid_cache_entries_leave_original_report_without_bundle(setup_candidates, mode):
    prep, kwargs, _ = setup_candidates(mode)
    with pytest.raises(candidates.ZigSupportCandidateError):
        candidates.run_zig_support_candidate_preparation(prep, **kwargs)
    assert (kwargs["workspace"] / "attempt/report.json").exists()
    assert not (kwargs["workspace"] / "support-candidates.json").exists()


def test_actual_seed_failure_retains_original_failure_without_candidate_manifest(setup_candidates):
    prep, kwargs, _ = setup_candidates(b"nonzero")
    with pytest.raises(BuildExecutionError):
        candidates.run_zig_support_candidate_preparation(prep, **kwargs)
    report = json.loads((kwargs["workspace"] / "attempt/report.json").read_bytes())
    assert report["status"] != "complete"
    assert not (kwargs["workspace"] / "support-candidates.json").exists()


def test_no_candidates_is_only_an_unaccepted_cache_observation(setup_candidates):
    prep, kwargs, records = setup_candidates(b"empty")
    bundle = candidates.run_zig_support_candidate_preparation(prep, **kwargs)
    facts = _validate(bundle, prep, records)
    assert bundle.files == () and facts["candidates"] == []
    assert facts["support_selection_accepted"] is False
    assert facts["production_admission"] is False
    assert all(facts["cache_inventories"][role]["files"] > 0 for role in ("global", "local"))


@pytest.mark.parametrize("kind", ["interrupted", "deadline", "bad-interruption", "bad-clock"])
def test_controls_refuse_before_workspace_creation(setup_candidates, kind):
    prep, kwargs, _ = setup_candidates()
    extra = {}
    if kind == "interrupted":
        extra["interrupted"] = lambda: True
    elif kind == "deadline":
        kwargs["deadline"] = time.monotonic() - 1
    elif kind == "bad-interruption":
        extra["interrupted"] = lambda: 1
    else:
        extra["monotonic"] = lambda: float("nan")
    with pytest.raises(candidates.ZigSupportCandidateError):
        candidates.run_zig_support_candidate_preparation(prep, **kwargs, **extra)
    assert not kwargs["workspace"].exists()


def test_existing_workspace_is_preserved_instead_of_reused(setup_candidates):
    prep, kwargs, _ = setup_candidates()
    kwargs["workspace"].mkdir()
    marker = kwargs["workspace"] / "prior-attempt"
    marker.write_bytes(b"preserve original attempt")
    with pytest.raises(candidates.ZigSupportCandidateError):
        candidates.run_zig_support_candidate_preparation(prep, **kwargs)
    assert marker.read_bytes() == b"preserve original attempt"
    assert list(kwargs["workspace"].iterdir()) == [marker]


@pytest.mark.parametrize("limit", ["entries", "bytes"])
def test_cache_limits_are_shared_across_global_and_local_roots(tmp_path, monkeypatch, limit):
    roots = {role: tmp_path / role for role in ("global", "local")}
    for root in roots.values():
        root.mkdir()
        (root / "metadata").write_bytes(b"four")
    monkeypatch.setattr(candidates, "_MAX_CACHE_ENTRIES" if limit == "entries" else "_MAX_CACHE_BYTES",
                        1 if limit == "entries" else 7)
    with pytest.raises(candidates.ZigSupportCandidateError, match="cache_bounds"):
        candidates._cache_inventories(roots, lambda: None)


def test_cache_file_size_is_bounded_before_reading(tmp_path, monkeypatch):
    cache = tmp_path / "global"
    cache.mkdir()
    (cache / "libc.a").write_bytes(b"five!")
    monkeypatch.setattr(candidates, "_MAX_FILE_BYTES", 4)
    with pytest.raises(candidates.ZigSupportCandidateError, match="cache_bounds"):
        candidates._cache_inventories({"global": cache}, lambda: None)


def test_bundle_pin_and_exported_bytes_cannot_approve_each_other(setup_candidates):
    prep, kwargs, records = setup_candidates()
    bundle = candidates.run_zig_support_candidate_preparation(prep, **kwargs)
    with pytest.raises(candidates.ZigSupportCandidateError):
        candidates.validate_zig_support_candidate_bundle(
            bundle, expected_bundle_sha256="0" * 64, preparation_sha256=prep.sha256,
            zig_inventory_sha256=sha(canonical(records)),
        )
    files = list(bundle.files)
    files[0] = (files[0][0], files[0][1] + b"drift")
    with pytest.raises(candidates.ZigSupportCandidateError):
        _validate(replace(bundle, files=tuple(files)), prep, records)
    with pytest.raises(candidates.ZigSupportCandidateError):
        _validate(replace(bundle, files=(*bundle.files, bundle.files[0])), prep, records)


def test_original_toolchain_drift_after_the_real_runner_is_refused(setup_candidates, monkeypatch):
    prep, kwargs, _ = setup_candidates()
    original_run = candidates.run_pinned_build_v3

    def drifting_run(*args, **options):
        report = original_run(*args, **options)
        (kwargs["toolchain_root"] / "lib/mode").write_bytes(b"changed after original report")
        return report

    monkeypatch.setattr(candidates, "run_pinned_build_v3", drifting_run)
    with pytest.raises(BuildDependencyError, match="file_pin"):
        candidates.run_zig_support_candidate_preparation(prep, **kwargs)
    assert (kwargs["workspace"] / "attempt/report.json").exists()
    assert not (kwargs["workspace"] / "support-candidates.json").exists()


def test_cache_bytes_changed_before_the_export_read_cannot_be_sealed(setup_candidates, monkeypatch):
    prep, kwargs, _ = setup_candidates()
    original_read = candidates._read_pin
    changed = []

    def drifting_read(root, row, checkpoint, **options):
        if root.name == ".zig-global-cache" and row["path"] == "o/first/crt1.o" and not changed:
            (root / row["path"]).write_bytes(b"drift after inventory")
            changed.append(True)
        return original_read(root, row, checkpoint, **options)

    monkeypatch.setattr(candidates, "_read_pin", drifting_read)
    with pytest.raises(BuildDependencyError, match="file_pin"):
        candidates.run_zig_support_candidate_preparation(prep, **kwargs)
    assert changed == [True]
    assert not (kwargs["workspace"] / "support-candidates.json").exists()


def test_manifest_authority_and_cache_mapping_changes_refuse(setup_candidates):
    prep, kwargs, records = setup_candidates()
    bundle = candidates.run_zig_support_candidate_preparation(prep, **kwargs)
    for key, value in (("production_admission", True), ("seed_executed", True), ("support_selection_accepted", True),
                       ("zig_inventory_sha256", "0" * 64), ("preparation_sha256", "0" * 64)):
        facts = json.loads(bundle.manifest_bytes)
        facts[key] = value
        with pytest.raises(candidates.ZigSupportCandidateError):
            _validate(replace(bundle, manifest_bytes=canonical(facts)), prep, records)
    for cache, path in (("ambient", "o/archive/libc.a"), ("global", "../libc.a"),
                        ("global", "/absolute/libc.a"), ("global", "o//libc.a")):
        facts = json.loads(bundle.manifest_bytes)
        facts["candidates"][0].update(cache=cache, cache_path=path)
        with pytest.raises(candidates.ZigSupportCandidateError):
            _validate(replace(bundle, manifest_bytes=canonical(facts)), prep, records)
    for key, value in (("executable", 0), ("size", float(json.loads(bundle.manifest_bytes)["candidates"][0]["size"]))):
        facts = json.loads(bundle.manifest_bytes)
        facts["candidates"][0][key] = value
        with pytest.raises(candidates.ZigSupportCandidateError):
            _validate(replace(bundle, manifest_bytes=canonical(facts)), prep, records)


def test_uninitialized_observation_raises_only_the_fixed_refusal():
    bundle = object.__new__(candidates.ZigSupportCandidateBundle)
    with pytest.raises(candidates.ZigSupportCandidateError, match="^zig_support_candidate_bundle$"):
        candidates.validate_zig_support_candidate_bundle(
            bundle, expected_bundle_sha256="0" * 64, preparation_sha256="0" * 64,
            zig_inventory_sha256="0" * 64,
        )
