"""Actual disposable source staging; no release, source or runtime execution."""

from __future__ import annotations

import dataclasses
import errno
import hashlib
import io
import json
import lzma
import math
import os
import socket
import stat
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path

import pytest

from tools.static_python_fixture import archive_observation as archive
from tools.static_python_fixture import source_patches as preparation
from tools.static_python_fixture import source_projection as projection
from tools.static_python_fixture import source_staging as staging

ROOT = "Python-3.13.12"
FIXTURE = Path(__file__).parent / "fixtures/static_python_source"
PREFIX = "static_python_source_staging_"


@pytest.fixture
def sources():
    return {path: (FIXTURE / (path + ".source")).read_bytes()
            for path in preparation.SOURCE_PATHS}


@pytest.fixture
def tmp_path(tmp_path):
    # Darwin's /var is a symlink; the contract requires canonical real ancestors.
    return tmp_path.resolve()


def _dir(path, mode=0o755):
    member = tarfile.TarInfo(path)
    member.type = tarfile.DIRTYPE
    member.mode = mode
    return member, None


def _file(path, raw, mode=0o644):
    member = tarfile.TarInfo(path)
    member.size = len(raw)
    member.mode = mode
    return member, raw


def _entries(sources):
    return ([_dir(ROOT)]
            + [_file(ROOT + "/" + path, raw) for path, raw in sources.items()]
            + [_dir(ROOT + "/explicit-empty", 0o777),
               _file(ROOT + "/extra/unchanged.bin", b"unchanged\x00data", 0o777),
               _file(ROOT + "/extra/empty", b"")])


def _bundle(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for member, raw in entries:
            tar.addfile(member, None if raw is None else io.BytesIO(raw))
    compressed = lzma.compress(stream.getvalue(), format=lzma.FORMAT_XZ)
    # Independently pin the harness's known complete entry vector; never adopt
    # an expected pin from the observer or stager return value.
    manifest = {
        "schema": "lunar-static-python-extraction-manifest-v1", "archive": "cpython",
        "root": ROOT, "archive_sha256": hashlib.sha256(compressed).hexdigest(),
        "members": sorted([{
            "path": member.name.rstrip("/") if member.isdir() else member.name,
            "kind": "directory" if member.isdir() else "file", "size": member.size,
            "mode": member.mode, "sha256": None if raw is None else hashlib.sha256(raw).hexdigest(),
        } for member, raw in entries], key=lambda item: item["path"]),
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode()
    return archive.snapshot_inert_archive_bytes(compressed, "cpython"), hashlib.sha256(raw).hexdigest()


def _stage(bundle, destination, **kwargs):
    snapshot, pin = bundle
    options = {"expected_manifest_sha256": pin, "require_profile": False,
               "deadline": time.monotonic() + 30.0}
    options.update(kwargs)
    return staging.stage_archive_sources(snapshot, str(destination), **options)


def _refused(call):
    with pytest.raises(staging.StaticPythonSourceStagingError) as error:
        call()
    assert error.value.reason.startswith(PREFIX)
    assert str(error.value) == error.value.reason
    return error.value


def _forbid(*args, **kwargs):
    pytest.fail("unexpected operation before staging admission")


def _no_filesystem(monkeypatch):
    for name in ("open", "stat", "mkdir", "write", "fsync"):
        monkeypatch.setattr(os, name, _forbid)


def test_complete_bytes_postimages_and_original_stat_inventory(sources, tmp_path):
    entries = _entries(sources)
    bundle = _bundle(entries)
    destination = tmp_path / "stage"
    expected, _ = preparation.prepare_static_python_sources(sources)
    expected_projection = projection.prepare_archive_sources(
        bundle[0], expected_manifest_sha256=bundle[1], require_profile=False,
        deadline=time.monotonic() + 30.0,
    )
    result = _stage(bundle, destination)
    manifest = result.to_manifest()
    assert manifest["schema"] == "lunar-static-python-source-staging-v1"
    assert manifest["root_directory"] == str(destination / ROOT)
    assert manifest["archive_sha256"] == bundle[0].archive_sha256
    assert manifest["snapshot_sha256"] == bundle[0].snapshot_sha256
    assert manifest["manifest_sha256"] == bundle[1]
    assert manifest["projection_sha256"] == expected_projection.projection_sha256
    assert manifest["metadata_validation"] == "skipped-inert-profile"
    assert manifest["profile_pin_verified"] is False
    assert manifest["signature_verification"] == "not-performed"
    assert manifest["extraction_performed"] is True
    assert manifest["fixed_patches_staged"] is True
    for key in ("release_verified", "source_execution_performed", "build_performed",
                "frozen_headers_generated", "runtime_execution_performed",
                "runtime_load_protection", "production_admission", "general_code_origin_protection"):
        assert manifest[key] is False
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode()
    assert result.canonical_json == canonical
    assert result.staging_sha256 == hashlib.sha256(canonical).hexdigest()

    original = {member.name: (member, raw) for member, raw in entries}
    expected_paths = set(original)
    for path in list(expected_paths):
        parts = path.split("/")
        expected_paths.update("/".join(parts[:count]) for count in range(1, len(parts)))
    inventory = manifest["entries"]
    assert [item["path"] for item in inventory] == sorted(expected_paths)
    assert len({item["path"] for item in inventory}) == len(inventory)
    for item in inventory:
        path = destination / item["path"]
        info = path.stat(follow_symlinks=False)
        assert item["device"] == info.st_dev
        assert item["inode"] == info.st_ino
        assert item["nlink"] == info.st_nlink
        assert item["mtime_ns"] == info.st_mtime_ns
        assert item["ctime_ns"] == info.st_ctime_ns
        assert item["implicit"] is (item["path"] not in original)
        if item["kind"] == "directory":
            assert stat.S_ISDIR(info.st_mode)
            assert item["mode"] == stat.S_IMODE(info.st_mode) == 0o700
            assert item["source_sha256"] is None
            assert item["staged_sha256"] is None
        else:
            member, source = original[item["path"]]
            relative = item["path"].removeprefix(ROOT + "/")
            wanted = expected.get(relative, source)
            assert path.read_bytes() == wanted
            assert stat.S_ISREG(info.st_mode)
            assert item["size"] == info.st_size == len(wanted)
            assert item["mode"] == stat.S_IMODE(info.st_mode) == 0o600
            assert item["nlink"] == 1
            assert item["source_sha256"] == hashlib.sha256(source).hexdigest()
            assert item["staged_sha256"] == hashlib.sha256(wanted).hexdigest()
            assert member.mode != 0o600  # Archived permissions never become execution grants.
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700


def test_result_is_frozen_and_manifest_views_are_detached(sources, tmp_path):
    result = _stage(_bundle(_entries(sources)), tmp_path / "stage")
    original = result.canonical_json
    mutable = result.to_manifest()
    mutable["entries"][0]["path"] = "changed"
    mutable["entries"].clear()
    mutable["production_admission"] = True
    assert result.canonical_json == original
    assert result.to_manifest() == json.loads(original)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.canonical_json = b"changed"


def test_one_decode_and_no_archive_reopen_extract_or_process(sources, tmp_path, monkeypatch):
    bundle = _bundle(_entries(sources))
    original = archive._decompress
    decoded = []

    def decode(snapshot, checkpoint=None):
        decoded.append(snapshot)
        return original(snapshot, checkpoint)

    monkeypatch.setattr(archive, "_decompress", decode)
    for owner, name in ((tarfile, "open"), (tarfile.TarFile, "extract"),
                        (tarfile.TarFile, "extractall"), (subprocess, "Popen"),
                        (subprocess, "run"), (socket, "socket"), (urllib.request, "urlopen")):
        monkeypatch.setattr(owner, name, _forbid)
    _stage(bundle, tmp_path / "stage")
    assert decoded == [bundle[0]]


@pytest.mark.parametrize("bad", [None, "", "A" * 64, "0" * 64, "f" * 64, "a" * 63, 1])
def test_bad_pin_refuses_before_filesystem(sources, tmp_path, monkeypatch, bad):
    bundle = _bundle(_entries(sources))
    _no_filesystem(monkeypatch)
    _refused(lambda: _stage(bundle, tmp_path / "stage", expected_manifest_sha256=bad))


@pytest.mark.parametrize("bad", [None, True, 1, 0.0, -1.0, math.nan, math.inf])
def test_bad_deadline_refuses_before_filesystem(sources, tmp_path, monkeypatch, bad):
    bundle = _bundle(_entries(sources))
    _no_filesystem(monkeypatch)
    _refused(lambda: _stage(bundle, tmp_path / "stage", deadline=bad))


@pytest.mark.parametrize("bad", [0, 1, None, "false"])
def test_bad_profile_flag_refuses_before_filesystem(sources, tmp_path, monkeypatch, bad):
    bundle = _bundle(_entries(sources))
    _no_filesystem(monkeypatch)
    _refused(lambda: _stage(bundle, tmp_path / "stage", require_profile=bad))


@pytest.mark.parametrize("bad", [None, {}, b"archive", "archive.xz"])
def test_snapshot_does_not_accept_path_or_mapping_fallback(tmp_path, monkeypatch, bad):
    _no_filesystem(monkeypatch)
    _refused(lambda: staging.stage_archive_sources(
        bad, str(tmp_path / "stage"), expected_manifest_sha256="a" * 64,
        deadline=1.0, monotonic=lambda: 0.0,
    ))


@pytest.mark.parametrize("kind", ["relative", "empty", "dot", "dotdot", "double-slash", "trailing", "bytes", "path"])
def test_destination_requires_exact_absolute_canonical_string(sources, tmp_path, monkeypatch, kind):
    bundle = _bundle(_entries(sources))
    path = str(tmp_path / "stage")
    values = {"relative": "stage", "empty": "", "dot": str(tmp_path) + "/./stage",
              "dotdot": str(tmp_path) + "/../stage", "double-slash": str(tmp_path) + "//stage",
              "trailing": path + "/", "bytes": path.encode(), "path": Path(path)}
    _no_filesystem(monkeypatch)
    _refused(lambda: staging.stage_archive_sources(
        bundle[0], values[kind], expected_manifest_sha256=bundle[1], require_profile=False,
        deadline=1.0, monotonic=lambda: 0.0,
    ))


def test_callback_bearing_scalars_and_snapshot_bytes_are_not_observed(sources, tmp_path, monkeypatch):
    bundle = _bundle(_entries(sources))

    class Text(str):
        __hash__ = str.__hash__
        __eq__ = _forbid
        encode = _forbid

    class Bytes(bytes):
        __len__ = _forbid

    _no_filesystem(monkeypatch)
    _refused(lambda: staging.stage_archive_sources(
        bundle[0], Text(str(tmp_path / "stage")), expected_manifest_sha256=bundle[1],
        require_profile=False, deadline=1.0, monotonic=lambda: 0.0,
    ))
    _refused(lambda: _stage(bundle, tmp_path / "stage", expected_manifest_sha256=Text(bundle[1])))
    altered = dataclasses.replace(bundle[0], compressed_bytes=Bytes(bundle[0].compressed_bytes))
    _refused(lambda: _stage((altered, bundle[1]), tmp_path / "stage"))


@pytest.mark.parametrize("kind", ["wrong-pin", "missing-source", "preimage", "late-link", "late-hardlink",
                                  "late-traversal", "duplicate", "file-parent", "mode"])
def test_complete_archive_and_source_validation_precede_destination(sources, tmp_path, monkeypatch, kind):
    entries = _entries(sources)
    if kind == "missing-source":
        entries.pop(1)
    elif kind == "preimage":
        path, raw = next(iter(sources.items()))
        entries[1] = _file(ROOT + "/" + path, b"!" + raw[1:])
    elif kind in {"late-link", "late-hardlink"}:
        member = tarfile.TarInfo(ROOT + "/late-link")
        member.type = tarfile.SYMTYPE if kind == "late-link" else tarfile.LNKTYPE
        member.linkname = ROOT + "/Python/import.c"
        entries.append((member, None))
    elif kind == "late-traversal":
        entries.append(_file(ROOT + "/../escape", b"bad"))
    elif kind == "duplicate":
        entries.append(entries[-1])
    elif kind == "file-parent":
        entries.append(_file(ROOT + "/extra", b"file parent"))
    elif kind == "mode":
        entries.append(_file(ROOT + "/setuid", b"bad", 0o4755))
    bundle = _bundle(entries)
    if kind == "wrong-pin":
        bundle = (bundle[0], "b" * 64)
    _no_filesystem(monkeypatch)
    _refused(lambda: _stage(bundle, tmp_path / "stage"))


def test_profile_failure_does_not_fall_back_or_touch_destination(sources, tmp_path, monkeypatch):
    bundle = _bundle(_entries(sources))
    _no_filesystem(monkeypatch)
    _refused(lambda: _stage(bundle, tmp_path / "stage", require_profile=True))


@pytest.mark.parametrize("budget", ["MAX_COMPRESSED_ARCHIVE_BYTES", "MAX_TAR_STREAM_BYTES",
                                    "MAX_TAR_MEMBERS", "MAX_FILE_BYTES", "MAX_TOTAL_FILE_BYTES"])
def test_archive_budgets_refuse_before_any_destination_operation(sources, tmp_path, monkeypatch, budget):
    bundle = _bundle(_entries(sources))
    monkeypatch.setattr(archive, budget, 1)
    _no_filesystem(monkeypatch)
    _refused(lambda: _stage(bundle, tmp_path / "stage"))


@pytest.mark.parametrize("tail", ["extra-xz-stream", "nonzero-tar-tail"])
def test_complete_trailing_archive_material_is_refused(sources, tmp_path, monkeypatch, tail):
    snapshot, pin = _bundle(_entries(sources))
    if tail == "extra-xz-stream":
        compressed = snapshot.compressed_bytes + lzma.compress(b"tail")
    else:
        compressed = lzma.compress(lzma.decompress(snapshot.compressed_bytes) + b"nonzero")
    altered = archive.snapshot_inert_archive_bytes(compressed, "cpython")
    _no_filesystem(monkeypatch)
    _refused(lambda: _stage((altered, pin), tmp_path / "stage"))


@pytest.mark.parametrize("kind", ["empty-directory", "file", "symlink"])
def test_any_existing_destination_refuses_without_adoption(sources, tmp_path, kind):
    bundle = _bundle(_entries(sources))
    destination = tmp_path / "stage"
    if kind == "empty-directory":
        destination.mkdir()
    elif kind == "file":
        destination.write_bytes(b"keep")
    else:
        target = tmp_path / "other"
        target.mkdir()
        destination.symlink_to(target, target_is_directory=True)
    before = destination.lstat()
    _refused(lambda: _stage(bundle, destination))
    after = destination.lstat()
    assert (after.st_dev, after.st_ino, after.st_mode) == (before.st_dev, before.st_ino, before.st_mode)
    if kind == "file":
        assert destination.read_bytes() == b"keep"
    elif kind == "empty-directory":
        assert list(destination.iterdir()) == []
    else:
        assert list(target.iterdir()) == []


def test_success_cannot_be_adopted_on_a_second_call(sources, tmp_path):
    bundle = _bundle(_entries(sources))
    destination = tmp_path / "stage"
    first = _stage(bundle, destination)
    original = first.canonical_json
    _refused(lambda: _stage(bundle, destination))
    assert first.canonical_json == original
    assert (destination / ROOT / "extra/unchanged.bin").read_bytes() == b"unchanged\x00data"


@pytest.mark.parametrize("kind", ["missing", "symlink", "file"])
def test_destination_ancestors_must_already_exist_as_original_directories(sources, tmp_path, kind):
    parent = tmp_path / "parent"
    if kind == "symlink":
        actual = tmp_path / "actual"
        actual.mkdir()
        parent.symlink_to(actual, target_is_directory=True)
    elif kind == "file":
        parent.write_bytes(b"keep")
    _refused(lambda: _stage(_bundle(_entries(sources)), parent / "stage"))
    if kind == "symlink":
        assert list(actual.iterdir()) == []
    elif kind == "missing":
        assert not parent.exists()
    else:
        assert parent.read_bytes() == b"keep"


@pytest.mark.parametrize("kind", ["parent", "destination", "archive-root"])
def test_original_directory_substitution_is_not_adopted(sources, tmp_path, monkeypatch, kind):
    bundle = _bundle(_entries(sources))
    parent = tmp_path / "parent"
    parent.mkdir()
    destination = parent / "stage"
    original = os.open
    fired = False

    def replace(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal fired
        result = original(path, flags, mode, dir_fd=dir_fd)
        wanted = "stage" if kind in {"parent", "destination"} else ROOT
        if not fired and flags & os.O_DIRECTORY and os.fspath(path) == wanted:
            fired = True
            if kind == "parent":
                parent.rename(tmp_path / "retained-parent")
                os.mkdir(parent, 0o700)
            else:
                os.rename(path, str(path) + "-retained", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
                os.mkdir(path, 0o700, dir_fd=dir_fd)
        return result

    monkeypatch.setattr(os, "open", replace)
    _refused(lambda: _stage(bundle, destination))
    assert fired
    if kind == "parent":
        assert (tmp_path / "retained-parent/stage").is_dir()
        assert list(parent.iterdir()) == []
    elif kind == "destination":
        assert (parent / "stage-retained").is_dir()
        assert list(destination.iterdir()) == []
    else:
        assert (destination / (ROOT + "-retained")).is_dir()
        assert list((destination / ROOT).iterdir()) == []


def test_short_writes_are_completed_without_reset_or_truncation(sources, tmp_path, monkeypatch):
    bundle = _bundle(_entries(sources))
    original = os.write
    calls = []

    def short(fd, data):
        calls.append(len(data))
        return original(fd, data[:7])

    monkeypatch.setattr(os, "write", short)
    destination = tmp_path / "stage"
    _stage(bundle, destination)
    expected, _ = preparation.prepare_static_python_sources(sources)
    assert len(calls) > 10
    for path, raw in expected.items():
        assert (destination / ROOT / path).read_bytes() == raw


@pytest.mark.parametrize("kind", ["zero", "error", "partial-error"])
def test_failed_write_keeps_partial_tree_and_cannot_be_repaired(sources, tmp_path, monkeypatch, kind):
    bundle = _bundle(_entries(sources))
    destination = tmp_path / "stage"
    original = os.write
    calls = 0

    def fail(fd, data):
        nonlocal calls
        calls += 1
        if kind == "zero":
            return 0
        if kind == "partial-error" and calls == 1:
            return original(fd, data[:3])
        raise OSError(errno.EIO, "untrusted injected detail")

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", fail)
        error = _refused(lambda: _stage(bundle, destination))
    assert "untrusted" not in str(error)
    assert destination.is_dir()
    retained = [path for path in destination.rglob("*") if path.is_file()]
    assert retained
    assert any(path.stat().st_size == (3 if kind == "partial-error" else 0) for path in retained)
    identities = [(path, path.stat().st_ino, path.read_bytes()) for path in retained]
    _refused(lambda: _stage(bundle, destination))
    assert [(path, path.stat().st_ino, path.read_bytes()) for path in retained] == identities


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_fsync_failure_keeps_created_evidence(sources, tmp_path, monkeypatch, kind):
    bundle = _bundle(_entries(sources))
    original = os.fsync
    fired = False

    def fail(fd):
        nonlocal fired
        info = os.fstat(fd)
        matches = stat.S_ISREG(info.st_mode) if kind == "file" else stat.S_ISDIR(info.st_mode)
        if matches and not fired:
            fired = True
            raise OSError(errno.EIO, "injected fsync failure")
        return original(fd)

    destination = tmp_path / "stage"
    monkeypatch.setattr(os, "fsync", fail)
    _refused(lambda: _stage(bundle, destination))
    assert fired
    assert destination.is_dir()


@pytest.mark.parametrize("kind", ["error", "early-eof", "corrupt-bytes"])
def test_original_file_readback_errors_or_drift_never_return_success(sources, tmp_path, monkeypatch, kind):
    bundle = _bundle(_entries(sources))
    read = os.read
    pread = os.pread
    fired = False

    def alter(fd, count, offset=None):
        nonlocal fired
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
        if regular and not fired:
            fired = True
            if kind == "error":
                raise OSError(errno.EIO, "injected readback failure")
            if kind == "early-eof":
                return b""
            raw = read(fd, count) if offset is None else pread(fd, count, offset)
            return b"!" + raw[1:] if raw else b"!"
        return read(fd, count) if offset is None else pread(fd, count, offset)

    monkeypatch.setattr(os, "read", lambda fd, count: alter(fd, count))
    monkeypatch.setattr(os, "pread", lambda fd, count, offset: alter(fd, count, offset))
    destination = tmp_path / "stage"
    _refused(lambda: _stage(bundle, destination))
    assert fired
    assert destination.is_dir()


@pytest.mark.parametrize("kind", ["replacement", "symlink", "hardlink", "chmod", "content"])
def test_file_identity_and_content_are_checked_after_write(sources, tmp_path, monkeypatch, kind):
    bundle = _bundle(_entries(sources))
    original_open = os.open
    original_write = os.write
    original_fsync = os.fsync
    opened = {}
    fired = False

    def capture(path, flags, mode=0o777, *, dir_fd=None):
        fd = original_open(path, flags, mode, dir_fd=dir_fd)
        if flags & os.O_CREAT:
            opened[fd] = (path, dir_fd)
        return fd

    def mutate(fd):
        nonlocal fired
        result = original_fsync(fd)
        if fd in opened and not fired and os.fstat(fd).st_size:
            fired = True
            name, parent = opened[fd]
            if kind == "replacement":
                content = os.pread(fd, os.fstat(fd).st_size, 0)
                os.unlink(name, dir_fd=parent)
                foreign = original_open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
                try:
                    original_write(foreign, content)
                    original_fsync(foreign)
                finally:
                    os.close(foreign)
            elif kind == "symlink":
                os.unlink(name, dir_fd=parent)
                os.symlink("unrelated", name, dir_fd=parent)
            elif kind == "hardlink":
                os.link(name, str(name) + ".extra-link", src_dir_fd=parent, dst_dir_fd=parent)
            elif kind == "chmod":
                os.fchmod(fd, 0o644)
            else:
                os.pwrite(fd, b"!", 0)
        return result

    monkeypatch.setattr(os, "open", capture)
    monkeypatch.setattr(os, "fsync", mutate)
    destination = tmp_path / "stage"
    _refused(lambda: _stage(bundle, destination))
    assert fired
    assert destination.is_dir()


def test_timestamp_drift_during_original_readback_is_refused(sources, tmp_path, monkeypatch):
    bundle = _bundle(_entries(sources))
    original = os.read
    fired = False

    def touch(fd, count):
        nonlocal fired
        raw = original(fd, count)
        if not fired and stat.S_ISREG(os.fstat(fd).st_mode):
            fired = True
            info = os.fstat(fd)
            os.utime(fd, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
        return raw

    monkeypatch.setattr(os, "read", touch)
    destination = tmp_path / "stage"
    _refused(lambda: _stage(bundle, destination))
    assert fired
    assert destination.is_dir()


def test_extra_entry_at_final_inventory_is_refused_and_retained(sources, tmp_path, monkeypatch):
    bundle = _bundle(_entries(sources))
    original = os.listdir
    opened = os.open
    fired = False

    def inject(path):
        nonlocal fired
        if type(path) is int and not fired:
            fired = True
            fd = opened("unexpected-entry", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=path)
            os.close(fd)
        return original(path)

    monkeypatch.setattr(os, "listdir", inject)
    destination = tmp_path / "stage"
    _refused(lambda: _stage(bundle, destination))
    assert fired
    assert list(destination.rglob("unexpected-entry"))


@pytest.mark.parametrize("phase", ["decode", "write", "file-fsync", "directory-fsync", "final-scan", "result"])
def test_one_original_deadline_covers_parse_write_and_final_inventory(sources, tmp_path, monkeypatch, phase):
    bundle = _bundle(_entries(sources))
    expired = False
    destination = tmp_path / "stage"

    def clock():
        return 2.0 if expired else 0.0

    owner, name = ((archive, "_decompress") if phase == "decode" else
                   (staging, "StaticPythonSourceStaging") if phase == "result" else
                   (os, "write" if phase == "write" else "listdir" if phase == "final-scan" else "fsync"))
    original = getattr(owner, name)

    def expire(*args, **kwargs):
        nonlocal expired
        result = original(*args, **kwargs)
        should_expire = True
        if phase in {"file-fsync", "directory-fsync"}:
            info = os.fstat(args[0])
            should_expire = stat.S_ISREG(info.st_mode) if phase == "file-fsync" else stat.S_ISDIR(info.st_mode)
        if should_expire:
            expired = True
        return result

    monkeypatch.setattr(owner, name, expire)
    _refused(lambda: _stage(bundle, destination, deadline=1.0, monotonic=clock))
    assert expired
    assert destination.exists() is (phase != "decode")


@pytest.mark.parametrize("clock_value", [1.0, math.nan, math.inf, True, "bad"])
def test_expired_or_invalid_clock_refuses_before_filesystem(sources, tmp_path, monkeypatch, clock_value):
    bundle = _bundle(_entries(sources))
    _no_filesystem(monkeypatch)
    _refused(lambda: _stage(bundle, tmp_path / "stage", deadline=1.0, monotonic=lambda: clock_value))


@pytest.mark.parametrize("failure", [False, True])
def test_all_opened_descriptors_close_on_success_and_write_failure(sources, tmp_path, monkeypatch, failure):
    bundle = _bundle(_entries(sources))
    opened = os.open
    closed = os.close
    duplicated = os.dup
    active = set()

    def capture(*args, **kwargs):
        fd = opened(*args, **kwargs)
        assert fd not in active
        active.add(fd)
        return fd

    def release(fd):
        result = closed(fd)
        active.remove(fd)
        return result

    def duplicate(fd):
        copy = duplicated(fd)
        assert copy not in active
        active.add(copy)
        return copy

    monkeypatch.setattr(os, "open", capture)
    monkeypatch.setattr(os, "close", release)
    monkeypatch.setattr(os, "dup", duplicate)
    if failure:
        monkeypatch.setattr(os, "write", lambda *args: 0)
        _refused(lambda: _stage(bundle, tmp_path / "stage"))
    else:
        _stage(bundle, tmp_path / "stage")
    assert active == set()


@pytest.mark.parametrize(("primary_write_error", "caller_exception"),
                         [(True, False), (False, False), (False, True)],
                         ids=["primary-write-refusal", "successful-file-close", "successful-file-close-in-except"])
def test_regular_file_close_uncertainty_preserves_primary_or_refuses_success(
    sources, tmp_path, monkeypatch, primary_write_error, caller_exception,
):
    bundle = _bundle(_entries(sources))
    original_open, original_dup, original_close = os.open, os.dup, os.close
    active = set()
    fired = False
    write_failed = False

    def capture(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        assert fd not in active
        active.add(fd)
        return fd

    def duplicate(fd):
        copy = original_dup(fd)
        assert copy not in active
        active.add(copy)
        return copy

    def write(fd, raw):
        nonlocal write_failed
        assert stat.S_ISREG(os.fstat(fd).st_mode)
        write_failed = True
        return 0

    def close(fd):
        nonlocal fired
        before = os.fstat(fd)
        original_close(fd)
        active.remove(fd)
        eligible = write_failed if primary_write_error else before.st_size > 0
        if not fired and stat.S_ISREG(before.st_mode) and eligible:
            fired = True
            raise OSError(errno.EIO, "untrusted close detail")

    monkeypatch.setattr(os, "open", capture)
    monkeypatch.setattr(os, "dup", duplicate)
    monkeypatch.setattr(os, "close", close)
    if primary_write_error:
        monkeypatch.setattr(os, "write", write)
    destination = tmp_path / "stage"
    if caller_exception:
        try:
            raise RuntimeError("previous caller failure")
        except RuntimeError:
            error = _refused(lambda: _stage(bundle, destination))
    else:
        error = _refused(lambda: _stage(bundle, destination))
    assert fired
    assert write_failed is primary_write_error
    expected = "write_progress_invalid" if primary_write_error else "descriptor_close_failed"
    assert error.reason == PREFIX + expected
    assert "untrusted" not in str(error)
    assert active == set()
    assert destination.is_dir()


@pytest.mark.parametrize("caller_exception", [False, True], ids=["normal-caller", "inside-caller-except"])
def test_final_retained_fd_close_failure_never_becomes_success(sources, tmp_path, monkeypatch, caller_exception):
    bundle = _bundle(_entries(sources))
    destination = tmp_path / "stage"
    original_open, original_dup, original_close = os.open, os.dup, os.close
    active = set()
    host_calls = 0
    fired = False

    def capture(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        assert fd not in active
        active.add(fd)
        return fd

    def duplicate(fd):
        copy = original_dup(fd)
        assert copy not in active
        active.add(copy)
        return copy

    def close(fd):
        nonlocal fired
        before = os.fstat(fd)
        original_close(fd)
        active.remove(fd)
        if host_calls == 2 and not fired:
            assert stat.S_ISDIR(before.st_mode)
            fired = True
            raise OSError(errno.EIO, "untrusted final retained FD close detail")

    def host_clock():
        nonlocal host_calls
        host_calls += 1
        return 0.0

    monkeypatch.setattr(os, "open", capture)
    monkeypatch.setattr(os, "dup", duplicate)
    monkeypatch.setattr(os, "close", close)
    monkeypatch.setattr(time, "perf_counter", host_clock)
    if caller_exception:
        try:
            raise RuntimeError("previous caller failure")
        except RuntimeError:
            error = _refused(lambda: _stage(bundle, destination, deadline=10.0, monotonic=lambda: 0.0))
    else:
        error = _refused(lambda: _stage(bundle, destination, deadline=10.0, monotonic=lambda: 0.0))
    assert error.reason == PREFIX + "descriptor_close_failed"
    assert fired
    assert active == set()
    assert destination.is_dir()


@pytest.mark.parametrize("kind", ["file", "extra-entry", "directory"])
def test_final_caller_clock_mutation_cannot_escape_complete_final_gate(sources, tmp_path, monkeypatch, kind):
    bundle = _bundle(_entries(sources))
    destination = tmp_path / "stage"
    dumps = json.dumps
    perf_counter = time.perf_counter
    serialized = False
    mutated = False
    final_gate_started = False
    final_caller_calls = 0

    def serialize(value, *args, **kwargs):
        nonlocal serialized
        raw = dumps(value, *args, **kwargs)
        if type(value) is dict and value.get("schema") == staging.SOURCE_STAGING_SCHEMA:
            serialized = True
        return raw

    def clock():
        nonlocal mutated, final_caller_calls
        # Once the bounded non-callback final gate starts, another caller clock
        # would reopen the same mutation boundary that this gate must close.
        if final_gate_started:
            final_caller_calls += 1
            assert final_caller_calls == 1
        if serialized and final_gate_started and not mutated:
            mutated = True
            root = destination / ROOT
            if kind == "file":
                target = root / "extra/unchanged.bin"
                raw = target.read_bytes()
                target.write_bytes(b"!" + raw[1:])
            elif kind == "extra-entry":
                (root / "extra/injected-after-serialization").write_bytes(b"keep")
            else:
                root.rename(destination / (ROOT + "-retained"))
                root.mkdir(mode=0o700)
        return 0.0

    def host_clock():
        nonlocal final_gate_started
        final_gate_started = True
        return perf_counter()

    monkeypatch.setattr(json, "dumps", serialize)
    monkeypatch.setattr(time, "perf_counter", host_clock)
    error = _refused(lambda: _stage(bundle, destination, deadline=30.0, monotonic=clock))
    assert serialized and mutated
    assert final_caller_calls == 1
    assert error.reason == PREFIX + ("file_drift" if kind == "file" else "directory_drift")
    assert destination.is_dir()
    if kind == "file":
        assert (destination / ROOT / "extra/unchanged.bin").read_bytes().startswith(b"!")
    elif kind == "extra-entry":
        assert (destination / ROOT / "extra/injected-after-serialization").read_bytes() == b"keep"
    else:
        assert (destination / (ROOT + "-retained")).is_dir()
        assert list((destination / ROOT).iterdir()) == []


def test_noncallback_final_elapsed_is_charged_to_original_remaining_budget(sources, tmp_path, monkeypatch):
    bundle = _bundle(_entries(sources))
    destination = tmp_path / "stage"
    host_calls = 0
    caller_calls = 0
    final_gate_started = False
    final_caller_calls = 0

    def caller_clock():
        nonlocal caller_calls, final_caller_calls
        if final_gate_started:
            final_caller_calls += 1
            assert final_caller_calls == 1
        caller_calls += 1
        return 0.9  # Only 0.1 of the original deadline remains throughout.

    def host_clock():
        nonlocal host_calls, final_gate_started
        final_gate_started = True
        host_calls += 1
        return 0.0 if host_calls == 1 else 0.125

    monkeypatch.setattr(time, "perf_counter", host_clock)
    error = _refused(lambda: _stage(bundle, destination, deadline=1.0, monotonic=caller_clock))
    assert error.reason == PREFIX + "wall_timeout"
    assert host_calls == 2
    assert caller_calls > 0
    assert destination.is_dir()
    # No repair or deletion follows a late timeout of a completely written tree.
    expected, _ = preparation.prepare_static_python_sources(sources)
    for path, raw in expected.items():
        assert (destination / ROOT / path).read_bytes() == raw


def test_final_caller_clock_work_itself_consumes_original_remaining_budget(sources, tmp_path, monkeypatch):
    bundle = _bundle(_entries(sources))
    destination = tmp_path / "stage"
    fake_host_time = 0.0
    final_gate_started = False
    final_caller_calls = 0
    host_calls = 0

    def caller_clock():
        nonlocal fake_host_time, final_caller_calls
        if final_gate_started:
            final_caller_calls += 1
            assert final_caller_calls == 1
            # The final callback returns a valid original-clock observation, but
            # consumes more host time than its original remaining 0.1 budget.
            fake_host_time += 0.125
        return 0.9

    def host_clock():
        nonlocal final_gate_started, host_calls
        final_gate_started = True
        host_calls += 1
        return fake_host_time

    monkeypatch.setattr(time, "perf_counter", host_clock)
    error = _refused(lambda: _stage(bundle, destination, deadline=1.0, monotonic=caller_clock))
    assert error.reason == PREFIX + "wall_timeout"
    assert final_caller_calls == 1
    assert host_calls == 2
    assert destination.is_dir()


def test_final_owned_descriptor_cleanup_consumes_original_budget_without_leak(sources, tmp_path, monkeypatch):
    bundle = _bundle(_entries(sources))
    destination = tmp_path / "stage"
    original_open, original_dup, original_close = os.open, os.dup, os.close
    active = set()
    fake_host_time = 0.0
    host_calls = 0
    cleanup_charged = False

    def capture(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        assert fd not in active
        active.add(fd)
        return fd

    def duplicate(fd):
        copy = original_dup(fd)
        assert copy not in active
        active.add(copy)
        return copy

    def close(fd):
        nonlocal fake_host_time, cleanup_charged
        original_close(fd)
        active.remove(fd)
        if host_calls == 2 and not cleanup_charged:
            # Both final validation observations have passed. Only the final
            # retained-handle cleanup performs this remaining host work.
            cleanup_charged = True
            fake_host_time += 0.125

    def host_clock():
        nonlocal host_calls
        host_calls += 1
        return fake_host_time

    monkeypatch.setattr(os, "open", capture)
    monkeypatch.setattr(os, "dup", duplicate)
    monkeypatch.setattr(os, "close", close)
    monkeypatch.setattr(time, "perf_counter", host_clock)
    error = _refused(lambda: _stage(bundle, destination, deadline=1.0, monotonic=lambda: 0.9))
    assert error.reason == PREFIX + "wall_timeout"
    assert host_calls == 3
    assert cleanup_charged
    assert active == set()
    assert destination.is_dir()
