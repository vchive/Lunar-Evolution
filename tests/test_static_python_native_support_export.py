"""Inert native exports and independent wire vectors; no Zig or seed runs.

The production C helper is compiled as an ordinary test executable. Its Zig
substitute writes finite cache data, and the generated seed is plain text.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import stat
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.test_static_python_concrete_recipe import (
    concrete_inputs,  # noqa: F401 - shared pytest fixture
)
from tools.static_python_rsi_fixture import execution_backend as execution
from tools.static_python_rsi_fixture import native_support_export as export
from tools.static_python_rsi_fixture.command_input_graph import validate_dependency_command_graph
from tools.static_python_rsi_fixture.runtime_closure import canonical
from tools.static_python_rsi_fixture.zig_support import _SOURCE

_MAGIC = b"LZSUP01\n"
_CANDIDATE_NAMES = frozenset({"crt1.o", "crti.o", "crtn.o", "libc.a", "libzigc.a",
                              "libubsan_rt.a", "libcompiler_rt.a"})


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _file(cache, path, raw, *, mode=stat.S_IFREG | 0o600):
    return {"cache": cache, "kind": 2, "path": path, "mode": mode, "raw": raw}


def _directory(cache, path):
    return {"cache": cache, "kind": 1, "path": path, "mode": stat.S_IFDIR | 0o700, "raw": b""}


def _entries():
    return [
        _directory(0, "h"), _file(0, "h/metadata", b"original cache metadata\n"),
        _directory(0, "o"), _directory(0, "o/first"),
        _file(0, "o/first/crt1.o", b"first crt candidate\n"),
        _directory(0, "o/second"), _file(0, "o/second/crt1.o", b"different crt candidate\n"),
        _directory(1, "o"), _directory(1, "o/local"),
        _file(1, "o/local/libc.a", b"local libc candidate\n"),
    ]


def _wire(entries=None, *, roots=((1, stat.S_IFDIR | 0o700), (1, stat.S_IFDIR | 0o700)),
          entry_count=None, candidate_count=None, magic=_MAGIC):
    entries = _entries() if entries is None else entries
    candidates = [row for row in entries if row["kind"] == 2
                  and row["path"].rsplit("/", 1)[-1] in _CANDIDATE_NAMES]
    raw = bytearray(magic)
    raw.extend(struct.pack(">II", len(entries) if entry_count is None else entry_count,
                           len(candidates) if candidate_count is None else candidate_count))
    for present, mode in roots:
        raw.extend(struct.pack(">BI", present, mode))
    for row in entries:
        path = row["path"].encode("ascii")
        data = row.get("raw", b"")
        size = row.get("size", len(data))
        digest = row.get("digest", hashlib.sha256(data).digest() if row["kind"] == 2 else bytes(32))
        raw.extend(struct.pack(">BBHIQ", row["cache"], row["kind"], len(path), row["mode"], size))
        raw.extend(digest)
        raw.extend(path)
        if row["kind"] == 2 and row["path"].rsplit("/", 1)[-1] in _CANDIDATE_NAMES:
            raw.extend(data)
    return bytes(raw)


def test_independent_wire_retains_every_cache_record_and_all_ambiguous_candidates():
    parsed = export.parse_native_support_export(_wire())
    assert parsed.candidates == (
        ("candidates/global/o/first/crt1.o", b"first crt candidate\n"),
        ("candidates/global/o/second/crt1.o", b"different crt candidate\n"),
        ("candidates/local/o/local/libc.a", b"local libc candidate\n"),
    )
    assert parsed.inventories == {
        "global": [
            {"path": "h/metadata", "size": 24, "sha256": _sha(b"original cache metadata\n"), "executable": False},
            {"path": "o/first/crt1.o", "size": 20, "sha256": _sha(b"first crt candidate\n"), "executable": False},
            {"path": "o/second/crt1.o", "size": 24, "sha256": _sha(b"different crt candidate\n"), "executable": False},
        ],
        "local": [{"path": "o/local/libc.a", "size": 21, "sha256": _sha(b"local libc candidate\n"),
                   "executable": False}],
    }
    assert len(parsed.entries) == 10
    assert parsed.entries[0] == {"cache": "global", "kind": "directory", "path": "h",
                                 "mode": stat.S_IFDIR | 0o700, "size": 0, "sha256": "0" * 64}
    assert parsed.entries[1]["sha256"] == _sha(b"original cache metadata\n")


@pytest.mark.parametrize("name", sorted(_CANDIDATE_NAMES))
def test_each_finite_support_basename_is_exported_without_selecting_a_role(name):
    parsed = export.parse_native_support_export(_wire([_file(0, name, b"candidate\n")]))
    assert parsed.candidates == (("candidates/global/" + name, b"candidate\n"),)


def test_unknown_archive_is_retained_only_as_cache_inventory_metadata():
    parsed = export.parse_native_support_export(_wire([_file(0, "libunknown.a", b"unselected\n")]))
    assert parsed.candidates == ()
    assert parsed.inventories["global"] == [{"path": "libunknown.a", "size": 11,
                                             "sha256": _sha(b"unselected\n"), "executable": False}]


@pytest.mark.parametrize("raw", [None, bytearray(_MAGIC), memoryview(_MAGIC), "LZSUP01\n"])
def test_wire_requires_original_bytes_instead_of_another_buffer_type(raw):
    with pytest.raises(export.NativeSupportExportError):
        export.parse_native_support_export(raw)


@pytest.mark.parametrize("change", ["magic", "truncated-header", "truncated-entry", "truncated-payload",
                                     "trailing", "entry-bound", "candidate-bound", "count-mismatch",
                                     "missing-root", "root-mode", "root-kind"])
def test_wire_header_roots_counts_and_exact_eof_are_strict(change):
    raw = _wire()
    if change == "magic":
        raw = b"NOTMAGIC" + raw[8:]
    elif change == "truncated-header":
        raw = raw[:25]
    elif change == "truncated-entry":
        raw = raw[:40]
    elif change == "truncated-payload":
        raw = raw[:-1]
    elif change == "trailing":
        raw += b"unconsumed"
    elif change == "entry-bound":
        raw = _wire(entry_count=32769)
    elif change == "candidate-bound":
        raw = _wire(candidate_count=32769)
    elif change == "count-mismatch":
        raw = _wire(candidate_count=2)
    elif change == "missing-root":
        raw = _wire(roots=((0, 0), (1, stat.S_IFDIR | 0o700)))
    elif change == "root-mode":
        raw = _wire(roots=((1, stat.S_IFDIR | 0o755), (1, stat.S_IFDIR | 0o700)))
    else:
        raw = _wire(roots=((1, stat.S_IFREG | 0o700), (1, stat.S_IFDIR | 0o700)))
    with pytest.raises(export.NativeSupportExportError):
        export.parse_native_support_export(raw)


@pytest.mark.parametrize("change", ["cache", "kind", "directory-digest", "directory-size", "directory-mode",
                                     "file-mode", "candidate-executable", "candidate-empty", "candidate-digest",
                                     "file-bound", "duplicate", "reordered"])
def test_wire_records_reject_nonfinite_types_modes_hashes_and_order(change):
    entries = _entries()
    if change == "cache":
        entries[0]["cache"] = 2
    elif change == "kind":
        entries[0]["kind"] = 3
    elif change == "directory-digest":
        entries[0]["digest"] = b"x" * 32
    elif change == "directory-size":
        entries[0]["size"] = 1
    elif change == "directory-mode":
        entries[0]["mode"] = stat.S_IFREG | 0o700
    elif change == "file-mode":
        entries[1]["mode"] = stat.S_IFLNK | 0o600
    elif change == "candidate-executable":
        entries[4]["mode"] |= 0o100
    elif change == "candidate-empty":
        entries[4]["raw"] = b""
    elif change == "candidate-digest":
        entries[4]["digest"] = b"x" * 32
    elif change == "file-bound":
        entries[4]["size"] = 128 * 1024 * 1024 + 1
    elif change == "duplicate":
        entries.insert(5, copy.deepcopy(entries[4]))
    else:
        entries[3], entries[4] = entries[4], entries[3]
    with pytest.raises(export.NativeSupportExportError):
        export.parse_native_support_export(_wire(entries))


def test_declared_metadata_sizes_share_one_total_cache_budget():
    entries = [_file(0, "metadata" + str(index), b"", mode=stat.S_IFREG | 0o600) for index in range(5)]
    for row in entries:
        row["size"] = 128 * 1024 * 1024
    with pytest.raises(export.NativeSupportExportError, match="bounds"):
        export.parse_native_support_export(_wire(entries))


@pytest.mark.parametrize("path", ["../escape", "/absolute", "o//crt1.o", "o/./crt1.o", "o/../crt1.o",
                                   "o/back\\slash", "o/colon:name", "o/control\x01", "x" * 481])
def test_wire_paths_cannot_escape_or_alias_the_original_cache(path):
    entries = _entries()
    entries[4]["path"] = path
    with pytest.raises(export.NativeSupportExportError):
        export.parse_native_support_export(_wire(entries))


@pytest.mark.parametrize("parent", ["missing", "file"])
def test_wire_children_require_an_actual_preceding_directory_record(parent):
    entries = [_file(0, "o/crt1.o", b"candidate\n")]
    if parent == "file":
        entries.insert(0, _file(0, "o", b"not a directory\n"))
    with pytest.raises(export.NativeSupportExportError, match="parent"):
        export.parse_native_support_export(_wire(entries))


def test_native_recipe_keeps_source_fixed_compiles_and_one_same_command_export(concrete_inputs, monkeypatch):  # noqa: F811
    prep, _ = concrete_inputs
    tools = [{"path": "zig", "size": 5, "sha256": _sha(b"inert"), "executable": True}]
    monkeypatch.setattr(export, "complete_zig_inventory", lambda _: tools)
    build = export.prepare_native_support_export_recipe(prep, zig_manifest_bytes=b"inert synthetic inventory")
    wire = json.loads(build.recipe_bytes)
    assert dict(build.sources) == {**_SOURCE, export.HELPER_SOURCE_PATH: export._helper_source()}
    assert wire["inputs"]["toolchain"] == tools
    stages = {stage["stage"]: stage["commands"] for stage in wire["stages"]}
    assert len(stages["configure"]) == len(stages["freeze"]) == len(stages["link"]) == 1
    assert len(stages["compile"]) == 2
    assert stages["configure"][0]["argv"] == [
        "@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "-std=c11", "-O2", "-g0", "-static",
        "@source/native/native_support_export.c", "-o", "@work/bin/lunar-native-support-export",
    ]
    link = stages["link"][0]
    assert link["argv"] == [
        "@work/bin/lunar-native-support-export", "@toolchain/zig",
        "/tmp/zig-global/native-support", "/tmp/zig-local/native-support",
        "@work/support/seed", "@work/support/native-cache-export.bin",
        "@work/support/probe.o", "@work/support/main.o", "@work/support/div.o",
    ]
    assert [row["path"] for row in link["outputs"]] == ["support/seed", "support/native-cache-export.bin"]
    assert b"--dependency-file" not in build.recipe_bytes and b"seed.d" not in build.recipe_bytes
    assert not any(command["argv"][0] == "@work/support/seed"
                   for stage in wire["stages"] for command in stage["commands"])
    manifest = json.loads(build.manifest_bytes)
    assert manifest["helper_source_sha256"] == export.HELPER_SOURCE_SHA256
    assert manifest["custody_backend"] == "podman-snapshots-v1"
    for name in ("seed_executed", "production_admission", "support_selection_accepted", "installation_accepted"):
        assert manifest[name] is False
    export.validate_native_support_export_graph(wire)
    with pytest.raises(ValueError):
        validate_dependency_command_graph(wire)


@pytest.mark.parametrize("change", [
    "helper-source-pin", "helper-source-size", "seed-source-pin", "helper-flag", "object-flag",
    "cache-path", "cache-alias", "link-object-order", "output-bound", "environment-value", "environment-extra",
])
def test_re_signed_native_graph_cannot_replace_source_commands_outputs_or_environment(
    concrete_inputs, monkeypatch, change,  # noqa: F811
):
    prep, _ = concrete_inputs
    tools = [{"path": "zig", "size": 5, "sha256": _sha(b"inert"), "executable": True}]
    monkeypatch.setattr(export, "complete_zig_inventory", lambda _: tools)
    build = export.prepare_native_support_export_recipe(prep, zig_manifest_bytes=b"inert synthetic inventory")
    wire = json.loads(build.recipe_bytes)
    helper = next(row for row in wire["inputs"]["source"] if row["path"] == export.HELPER_SOURCE_PATH)
    if change == "helper-source-pin":
        helper["sha256"] = _sha(b"another source, independently re-signed")
    elif change == "helper-source-size":
        helper["size"] += 1
    elif change == "seed-source-pin":
        wire["inputs"]["source"][-1]["sha256"] = _sha(b"replaced original support source")
    elif change == "helper-flag":
        wire["stages"][0]["commands"][0]["argv"].insert(6, "-DUNREVIEWED=1")
    elif change == "object-flag":
        wire["stages"][1]["commands"][0]["argv"].insert(6, "-DUNREVIEWED=1")
    elif change == "cache-path":
        wire["stages"][3]["commands"][0]["argv"][2] = "/tmp/other-global"
    elif change == "cache-alias":
        wire["stages"][3]["commands"][0]["argv"][3] = wire["stages"][3]["commands"][0]["argv"][2]
    elif change == "link-object-order":
        argv = wire["stages"][3]["commands"][0]["argv"]
        argv[-1], argv[-2] = argv[-2], argv[-1]
    elif change == "output-bound":
        wire["stages"][3]["commands"][0]["outputs"][1]["max_size"] -= 1
    elif change == "environment-value":
        wire["environment"]["TZ"] = "Other"
    else:
        wire["environment"]["CFLAGS"] = ""
    # Supply a fresh exact recipe digest so a stale outer pin cannot explain
    # the refusal of this independently changed finite command profile.
    raw = canonical(wire)
    parsed = execution._recipe(raw, _sha(raw), version3=True)
    with pytest.raises(export.NativeSupportExportError):
        export.validate_native_support_export_graph(parsed)


@pytest.mark.parametrize("profile,backend", [
    ("native-support-export-v2", "podman-snapshots-v1"),
    (1, "podman-snapshots-v1"),
    ("native-support-export-v1", None),
    ("native-support-export-v1", "podman"),
])
def test_runner_refuses_unknown_or_wrong_backend_native_profiles_before_preflight_or_workspace(
    concrete_inputs, tmp_path, monkeypatch, profile, backend,  # noqa: F811
):
    from tools.static_python_rsi_fixture import podman_custody as custody

    prep, _ = concrete_inputs
    records = [{"path": "zig", "size": 5, "sha256": _sha(b"inert"), "executable": True}]
    monkeypatch.setattr(export, "complete_zig_inventory", lambda _: records)
    build = export.prepare_native_support_export_recipe(prep, zig_manifest_bytes=b"inert synthetic inventory")
    roots = {name: tmp_path / name for name in ("source", "toolchain")}
    for root in roots.values():
        root.mkdir()
    called = []
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: called.append(True))
    workspace = tmp_path / "attempt"
    with pytest.raises(execution.BuildExecutionError):
        execution.run_pinned_build_v3(
            prep, recipe_bytes=build.recipe_bytes, expected_recipe_sha256=build.sha256,
            source_root=roots["source"], toolchain_root=roots["toolchain"], workspace=workspace,
            deadline=time.monotonic() + 30, custody_backend=backend, command_profile=profile,
        )
    assert called == [] and not workspace.exists()


def test_native_run_dispatches_only_the_fixed_snapshot_backend(concrete_inputs, tmp_path, monkeypatch):  # noqa: F811
    prep, _ = concrete_inputs
    tools = tmp_path / "tools"
    tools.mkdir()
    records = [{"path": "zig", "size": 5, "sha256": _sha(b"inert"), "executable": True}]
    monkeypatch.setattr(export, "complete_zig_inventory", lambda _: records)
    called = []

    class DispatchBoundary(BaseException):
        pass

    def actual_dispatch(preparation, **options):
        assert preparation is prep
        assert options["custody_backend"] == "podman-snapshots-v1"
        assert options["command_profile"] == "native-support-export-v1"
        assert options["source_root"].joinpath(export.HELPER_SOURCE_PATH).read_bytes() == export._helper_source()
        called.append(options)
        raise DispatchBoundary

    monkeypatch.setattr(export, "run_pinned_build_v3", actual_dispatch)
    with pytest.raises(DispatchBoundary):
        export.run_native_support_export(
            prep, zig_manifest_bytes=b"inert synthetic inventory", toolchain_root=tools,
            workspace=tmp_path / "attempt", deadline=time.monotonic() + 30,
        )
    assert len(called) == 1
    assert not (tmp_path / "attempt/support-candidates.json").exists()


_INERT_ZIG = r'''
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int directory(const char *path) {
    char copy[8192];
    if (snprintf(copy, sizeof(copy), "%s", path) >= (int)sizeof(copy)) return 10;
    for (char *p = copy + 1; *p; p++) {
        if (*p != '/') continue;
        *p = 0;
        if (mkdir(copy, 0700) && errno != EEXIST) return 11;
        *p = '/';
    }
    return mkdir(copy, 0700) && errno != EEXIST ? 12 : 0;
}
static int emit(const char *root, const char *relative, const char *text, mode_t mode) {
    char path[8192], parent[8192];
    if (snprintf(path, sizeof(path), "%s/%s", root, relative) >= (int)sizeof(path)) return 13;
    if (snprintf(parent, sizeof(parent), "%s", path) >= (int)sizeof(parent)) return 14;
    char *last = strrchr(parent, '/');
    if (!last) return 15;
    *last = 0;
    if (directory(parent)) return 16;
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL, mode);
    if (fd < 0) return 17;
    size_t size = strlen(text);
    if (write(fd, text, size) != (ssize_t)size || close(fd)) return 18;
    return chmod(path, mode) ? 19 : 0;
}
int main(int argc, char **argv) {
    char path[8192], mode[64] = {0};
    if (snprintf(path, sizeof(path), "%s.mode", argv[0]) >= (int)sizeof(path)) return 20;
    FILE *f = fopen(path, "rb");
    if (!f) return 21;
    size_t got = fread(mode, 1, sizeof(mode) - 1, f);
    if (fclose(f)) return 22;
    mode[got] = 0;
    const char *seed = NULL;
    int objects = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-o") && i + 1 < argc) seed = argv[++i];
        else if (!strcmp(argv[i], "--dependency-file") || !strcmp(argv[i], "-Xlinker")) return 23;
        else if (strstr(argv[i], ".o")) objects++;
    }
    const char *global = getenv("ZIG_GLOBAL_CACHE_DIR"), *local = getenv("ZIG_LOCAL_CACHE_DIR");
    if (!seed || objects != 3 || !global || !local) return 24;
    if (emit(global, "h/metadata", "metadata still present during the same command\n", 0600)) return 25;
    f = fopen(seed, "wb");
    if (!f || fputs("plain text seed: never execute\n", f) < 0 || fclose(f) || chmod(seed, 0700)) return 28;
    if (!strcmp(mode, "nonzero")) {
        fputs("original inert Zig link failure\n", stderr);
        return 37;
    }
    if (emit(global, "o/first/crt1.o", "first crt\n", 0600) ||
        emit(global, "o/second/crt1.o", "second crt\n", 0600) ||
        emit(local, "o/local/crt1.o", "local crt\n", 0600) ||
        emit(global, "o/archive/libc.a", "libc\n", 0600)) return 29;
    if (snprintf(path, sizeof(path), "%s/o/untrusted", global) >= (int)sizeof(path)) return 30;
    if (!strcmp(mode, "symlink") && symlink("archive/libc.a", path)) return 31;
    if (!strcmp(mode, "directory-link") && symlink("archive", path)) return 32;
    if (!strcmp(mode, "fifo") && mkfifo(path, 0600)) return 33;
    if (!strcmp(mode, "bad-path") && emit(global, "o/colon:name", "bad\n", 0600)) return 34;
    if (!strcmp(mode, "space-path") && emit(global, "o/space name", "bad\n", 0600)) return 41;
    if (!strcmp(mode, "executable") && emit(global, "o/archive/libcompiler_rt.a", "executable\n", 0700)) return 35;
    if (!strcmp(mode, "empty") && emit(global, "o/archive/libcompiler_rt.a", "", 0600)) return 36;
    if (!strcmp(mode, "oversized")) {
        if (emit(global, "o/archive/libcompiler_rt.a", "", 0600)) return 38;
        if (snprintf(path, sizeof(path), "%s/o/archive/libcompiler_rt.a", global) >= (int)sizeof(path)) return 39;
        if (truncate(path, (off_t)128 * 1024 * 1024 + 1)) return 40;
    }
    return 0;
}
'''


@pytest.fixture(scope="module")
def native_export_programs(tmp_path_factory):
    if sys.platform != "linux":
        pytest.skip("the production native export mechanism targets Linux")
    compiler = shutil.which("cc")
    assert compiler is not None
    root = tmp_path_factory.mktemp("native-support-export-programs")
    inert_source = root / "inert_zig.c"
    inert_source.write_text(_INERT_ZIG)
    production = Path(export.__file__).parent / "assets/native_support_export.c"
    assert production.is_file()
    programs = {}
    for name, source in (("exporter", production), ("zig", inert_source)):
        target = root / name
        subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target)],
                       check=True, capture_output=True, timeout=30)
        programs[name] = target
    return programs


@pytest.fixture
def native_export_case(tmp_path, native_export_programs):
    tool = tmp_path / "tools/zig"
    tool.parent.mkdir()
    shutil.copyfile(native_export_programs["zig"], tool)
    tool.chmod(0o700)
    objects = []
    for name in ("probe.o", "main.o", "div.o"):
        path = tmp_path / name
        path.write_bytes(b"inert declared object\n")
        objects.append(path)
    work = tmp_path / "work"
    work.mkdir()

    def run(mode="normal", *, global_cache=None, local_cache=None, bundle=None):
        Path(str(tool) + ".mode").write_text(mode)
        global_cache = tmp_path / "global-cache" if global_cache is None else global_cache
        local_cache = tmp_path / "local-cache" if local_cache is None else local_cache
        seed = work / "seed"
        bundle = work / "native-support.bin" if bundle is None else bundle
        argv = [str(native_export_programs["exporter"]), str(tool), str(global_cache), str(local_cache),
                str(seed), str(bundle), *(str(path) for path in objects)]
        result = subprocess.run(argv, cwd=work, env={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"}, check=False,
                                capture_output=True, timeout=30)
        return result, global_cache, local_cache, seed, bundle

    return run


def test_native_helper_uses_fresh_children_under_existing_container_cache_parents(native_export_case, tmp_path):
    roots = [tmp_path / name for name in ("zig-global", "zig-local")]
    for root in roots:
        root.mkdir(mode=0o700)
        (root / "scaffold-metadata").write_bytes(b"original parent remains outside fresh cache\n")
    result, global_cache, local_cache, _, bundle = native_export_case(
        global_cache=roots[0] / "native-support", local_cache=roots[1] / "native-support",
    )
    assert result.returncode == 0, result.stderr
    assert len(export.parse_native_support_export(bundle.read_bytes()).candidates) == 4
    assert all(root.joinpath("scaffold-metadata").read_bytes() == b"original parent remains outside fresh cache\n"
               for root in roots)
    assert all(stat.S_IMODE(root.stat().st_mode) == 0o700 for root in (global_cache, local_cache))


def test_real_native_helper_exports_same_link_command_cache_and_never_executes_seed(native_export_case):
    result, global_cache, local_cache, seed, bundle = native_export_case()
    assert result.returncode == 0, result.stderr
    parsed = export.parse_native_support_export(bundle.read_bytes())
    assert parsed.candidates == (
        ("candidates/global/o/archive/libc.a", b"libc\n"),
        ("candidates/global/o/first/crt1.o", b"first crt\n"),
        ("candidates/global/o/second/crt1.o", b"second crt\n"),
        ("candidates/local/o/local/crt1.o", b"local crt\n"),
    )
    assert seed.read_bytes() == b"plain text seed: never execute\n"
    assert not seed.with_suffix(".d").exists()
    assert global_cache.joinpath("h/metadata").read_bytes() == b"metadata still present during the same command\n"
    assert local_cache.joinpath("o/local/crt1.o").read_bytes() == b"local crt\n"
    assert any(row["path"] == "h/metadata" for row in parsed.inventories["global"])


def test_real_native_helper_never_replays_into_a_completed_export(native_export_case):
    first, global_cache, _, seed, bundle = native_export_case()
    assert first.returncode == 0, first.stderr
    original = bundle.read_bytes()
    second, _, _, _, _ = native_export_case()
    assert second.returncode != 0
    assert bundle.read_bytes() == original
    assert seed.read_bytes() == b"plain text seed: never execute\n"
    assert global_cache.joinpath("o/first/crt1.o").read_bytes() == b"first crt\n"


@pytest.mark.parametrize("mode", [
    "symlink", "directory-link", "fifo", "bad-path", "space-path", "executable", "empty", "oversized",
])
def test_real_native_helper_refuses_invalid_cache_entries_and_preserves_originals(native_export_case, mode):
    result, global_cache, _, seed, bundle = native_export_case(mode)
    assert result.returncode != 0
    assert seed.read_bytes() == b"plain text seed: never execute\n"
    assert global_cache.joinpath("h/metadata").is_file()
    if bundle.exists():
        with pytest.raises(export.NativeSupportExportError):
            export.parse_native_support_export(bundle.read_bytes())


def test_actual_failed_link_keeps_original_stderr_seed_and_cache_without_export(native_export_case):
    result, global_cache, _, seed, bundle = native_export_case("nonzero")
    assert result.returncode != 0
    assert b"original inert Zig link failure" in result.stderr
    assert seed.read_bytes() == b"plain text seed: never execute\n"
    assert global_cache.joinpath("h/metadata").is_file()
    assert bundle.read_bytes() == b""


def test_native_helper_does_not_reuse_a_prior_cache_or_overwrite_its_contents(native_export_case, tmp_path):
    prior = tmp_path / "prior-cache"
    prior.mkdir()
    marker = prior / "preserve"
    marker.write_bytes(b"original cache\n")
    result, _, _, seed, bundle = native_export_case(global_cache=prior)
    assert result.returncode != 0
    assert marker.read_bytes() == b"original cache\n"
    assert seed.read_bytes() == bundle.read_bytes() == b""


@pytest.mark.parametrize("name", ["tools/zig", "probe.o"])
def test_native_helper_follows_no_executable_or_declared_object_alias(native_export_case, tmp_path, name):
    target = tmp_path / name
    original = target.with_name(target.name + ".original")
    target.rename(original)
    target.symlink_to(original)
    result, _, _, seed, bundle = native_export_case()
    assert result.returncode != 0
    assert original.is_file()
    assert not seed.exists() and not bundle.exists()


@pytest.mark.parametrize("kind", ["cache-parent", "bundle-parent", "existing-bundle"])
def test_native_helper_follows_no_cache_or_destination_alias(native_export_case, tmp_path, kind):
    actual = tmp_path / "original"
    actual.mkdir()
    marker = actual / "preserve"
    marker.write_bytes(b"preserve original\n")
    options = {}
    if kind == "cache-parent":
        alias = tmp_path / "cache-alias"
        alias.symlink_to(actual, target_is_directory=True)
        options["global_cache"] = alias / "new-cache"
    elif kind == "bundle-parent":
        alias = tmp_path / "bundle-alias"
        alias.symlink_to(actual, target_is_directory=True)
        options["bundle"] = alias / "new-bundle"
    else:
        target = tmp_path / "work/native-support.bin"
        target.symlink_to(marker)
    result, _, _, _, _ = native_export_case(**options)
    assert result.returncode != 0
    assert marker.read_bytes() == b"preserve original\n"
    assert not (actual / "new-cache").exists()
    assert not (actual / "new-bundle").exists()
