"""Actual complete inert copies, with unchanged false custody/build claims."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import lzma
import os
import resource
import shutil
import stat
import tarfile
import time

import pytest

from tools.static_python_fixture import archive_observation as archive
from tools.static_python_fixture import toolchain_tree_observation as tree
from tools.static_python_fixture import verified_inputs
from tools.static_python_rsi_fixture import toolchain_private_copy as copying

ROOT = "zig-x86_64-linux-0.16.0"
FILES = {
    "zig": (b"inert-driver\x00never-execute\n", 0o755),
    "lib/data": (b"fixed-data\x00bytes\n", 0o644),
    "lib/empty": (b"", 0o644),
}


def _entries():
    return [
        (ROOT, None, 0o755),
        (ROOT + "/lib", None, 0o755),
        (ROOT + "/empty-directory", None, 0o755),
        *((ROOT + "/" + path, raw, mode) for path, (raw, mode) in FILES.items()),
    ]


def _bundle(tmp_path, monkeypatch, entries=None):
    """Independently pin fixture profiles; exercise production validation intact."""
    entries = _entries() if entries is None else entries
    stream = io.BytesIO()
    members = []
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, raw, mode in entries:
            member = tarfile.TarInfo(name)
            member.mode = mode
            member.type = tarfile.DIRTYPE if raw is None else tarfile.REGTYPE
            member.size = 0 if raw is None else len(raw)
            tar.addfile(member, None if raw is None else io.BytesIO(raw))
            members.append({
                "path": name, "kind": "directory" if raw is None else "file",
                "size": member.size, "mode": mode,
                "sha256": None if raw is None else hashlib.sha256(raw).hexdigest(),
            })
    compressed = lzma.compress(stream.getvalue(), format=lzma.FORMAT_XZ)
    digest = hashlib.sha256(compressed).hexdigest()
    monkeypatch.setitem(archive._PROFILES, "zig", dataclasses.replace(
        archive._PROFILES["zig"], size=len(compressed), sha256=digest,
    ))
    monkeypatch.setattr(verified_inputs, "_ZIG", dataclasses.replace(
        verified_inputs._ZIG, size=len(compressed), sha256=digest,
    ))
    raw = json.dumps({
        "schema": verified_inputs.EXTRACTION_MANIFEST_SCHEMA,
        "archive": "zig", "root": ROOT, "archive_sha256": digest,
        "members": sorted(members, key=lambda item: item["path"]),
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    source = tmp_path / "inert.tar.xz"
    source.write_bytes(compressed)
    snapshot = archive.snapshot_archive(str(source), "zig", deadline=time.monotonic() + 30.0)
    assert snapshot.profile_pin_verified and snapshot.source_identity is not None
    return snapshot, raw, hashlib.sha256(raw).hexdigest(), source


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    parent = tmp_path.resolve()
    os.chmod(parent, 0o700)
    return _bundle(parent, monkeypatch), parent / "copy"


def _copy(inputs, **overrides):
    (snapshot, raw, pin, _source), destination = inputs
    options = {
        "expected_manifest_sha256": pin,
        "destination_directory": str(destination),
        "deadline": time.monotonic() + 90.0,
    }
    options.update(overrides)
    return copying._materialize_toolchain_copy(snapshot, raw, **options)


def _refuse(call):
    with pytest.raises(copying.StaticPythonToolchainCopyError) as caught:
        call()
    assert str(caught.value) == caught.value.reason
    assert caught.value.reason.startswith("static_python_toolchain_copy_")
    return caught.value


def test_actual_complete_copy_uses_held_bytes_and_preserves_exact_modes(inputs):
    (snapshot, raw, pin, source), destination = inputs
    source.write_bytes(b"original transport changed after snapshot acquisition")
    result = _copy(inputs)
    record = result.to_dict()
    assert result.manifest_json == raw and result.manifest_sha256 == pin
    assert record["archive_sha256"] == snapshot.archive_sha256
    assert record["file_count"] == len(FILES)
    assert record["directory_count"] == 3
    assert record["claims"] == dict.fromkeys(tree._CLAIMS, False)
    assert record["tree_identity"]["inode"] == destination.stat().st_ino
    assert record["tree_identity"]["device"] == destination.stat().st_dev
    assert stat.S_IMODE(destination.stat().st_mode) == 0o755
    assert (destination / "empty-directory").is_dir()
    for relative, (expected, mode) in FILES.items():
        path = destination / relative
        assert path.read_bytes() == expected
        assert stat.S_IMODE(path.stat().st_mode) == mode
        assert path.stat().st_nlink == 1
    # A plain copy has no write enforcement or later-consumption authority.
    (destination / "lib/data").write_bytes(b"mutable setup artifact")
    assert result.to_dict()["claims"]["immutable_custody_established"] is False


def test_copy_installs_modes_even_under_restrictive_umask(inputs):
    previous = os.umask(0o077)
    try:
        _copy(inputs)
    finally:
        os.umask(previous)
    destination = inputs[1]
    for relative, (_raw, mode) in FILES.items():
        assert stat.S_IMODE((destination / relative).stat().st_mode) == mode
    assert stat.S_IMODE((destination / "lib").stat().st_mode) == 0o755


@pytest.mark.parametrize("pin", [None, True, "", "0" * 64, "f" * 64, "a" * 64])
def test_bad_external_pin_has_no_destination_side_effect(inputs, pin):
    _refuse(lambda: _copy(inputs, expected_manifest_sha256=pin))
    assert not inputs[1].exists()


@pytest.mark.parametrize("deadline", [None, True, 0, 0.0, -1.0, float("nan"), float("inf")])
def test_invalid_deadline_has_no_destination_side_effect(inputs, deadline):
    _refuse(lambda: _copy(inputs, deadline=deadline))
    assert not inputs[1].exists()


@pytest.mark.parametrize("now", [100.0, float("nan"), float("inf"), True, "clock"])
def test_expired_or_invalid_clock_has_no_destination_side_effect(inputs, now):
    _refuse(lambda: _copy(inputs, deadline=100.0, monotonic=lambda: now))
    assert not inputs[1].exists()


def test_noncanonical_manifest_refuses_before_copy(inputs):
    (snapshot, raw, pin, source), destination = inputs
    changed = ((snapshot, raw + b" ", pin, source), destination)
    _refuse(lambda: _copy(changed))
    assert not destination.exists()


def test_snapshot_profile_or_payload_drift_refuses_before_copy(inputs):
    (snapshot, raw, pin, source), destination = inputs
    for bad in (
        dataclasses.replace(snapshot, profile_pin_verified=False),
        dataclasses.replace(snapshot, compressed_bytes=snapshot.compressed_bytes + b"x"),
        dataclasses.replace(snapshot, source_identity=None),
    ):
        _refuse(lambda bad=bad: _copy(((bad, raw, pin, source), destination)))
        assert not destination.exists()


@pytest.mark.parametrize("kind", ["file", "directory", "symlink"])
def test_existing_destination_is_never_overwritten(inputs, kind):
    destination = inputs[1]
    sentinel = destination.parent / "sentinel"
    sentinel.write_bytes(b"unchanged")
    if kind == "file":
        destination.write_bytes(b"keep")
    elif kind == "directory":
        destination.mkdir()
    else:
        destination.symlink_to(sentinel)
    before = destination.lstat()
    _refuse(lambda: _copy(inputs))
    assert destination.lstat() == before
    assert sentinel.read_bytes() == b"unchanged"


def test_nonprivate_parent_refuses_before_creating_destination(inputs):
    os.chmod(inputs[1].parent, 0o755)
    _refuse(lambda: _copy(inputs))
    assert not inputs[1].exists()


def test_symlink_ancestor_is_not_followed(inputs):
    destination = inputs[1]
    alias = destination.parent / "alias"
    alias.symlink_to(destination.parent, target_is_directory=True)
    _refuse(lambda: _copy(inputs, destination_directory=str(alias / "copy")))
    assert not destination.exists()


@pytest.mark.parametrize("case", ["missing_parent", "directory_mode", "file_mode"])
def test_complete_metadata_preflight_precedes_destination_creation(tmp_path, monkeypatch, case):
    parent = tmp_path.resolve()
    os.chmod(parent, 0o700)
    entries = _entries()
    if case == "missing_parent":
        entries = [item for item in entries if item[0] != ROOT + "/lib"]
    elif case == "directory_mode":
        entries[0] = (ROOT, None, 0o700)
    else:
        entries[-1] = (entries[-1][0], b"", 0o600)
    inputs = _bundle(parent, monkeypatch, entries), parent / "copy"
    _refuse(lambda: _copy(inputs))
    assert not inputs[1].exists()


def test_fd_resource_refusal_precedes_copy(inputs, monkeypatch):
    monkeypatch.setattr(resource, "getrlimit", lambda _kind: (3, 3))
    _refuse(lambda: _copy(inputs))
    assert not inputs[1].exists()


def test_short_writes_are_completed_without_losing_bytes(inputs, monkeypatch):
    original = os.write
    count = 0

    def short_write(fd, data):
        nonlocal count
        count += 1
        return original(fd, data[:2])

    monkeypatch.setattr(os, "write", short_write)
    _copy(inputs)
    assert count > len(FILES)
    for relative, (raw, _mode) in FILES.items():
        assert (inputs[1] / relative).read_bytes() == raw


def test_zero_write_preserves_partial_tree_and_refuses(inputs, monkeypatch):
    monkeypatch.setattr(os, "write", lambda _fd, _data: 0)
    _refuse(lambda: _copy(inputs))
    assert inputs[1].is_dir()
    assert list(inputs[1].rglob("*"))


def test_expiry_during_write_preserves_partial_tree(inputs, monkeypatch):
    original = os.write
    expired = False

    def write(fd, data):
        nonlocal expired
        result = original(fd, data)
        expired = True
        return result

    monkeypatch.setattr(os, "write", write)
    _refuse(lambda: _copy(inputs, deadline=100.0, monotonic=lambda: 101.0 if expired else 1.0))
    assert expired and inputs[1].is_dir()


def test_observer_failure_retains_complete_copy_without_success(inputs, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise tree.StaticPythonToolchainTreeObservationError("file_content_drift")

    monkeypatch.setattr(tree, "observe_extracted_toolchain_tree", refuse)
    _refuse(lambda: _copy(inputs))
    for relative, (raw, _mode) in FILES.items():
        assert (inputs[1] / relative).read_bytes() == raw


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_late_file_substitution_cannot_overwrite_foreign_bytes(inputs, monkeypatch, kind):
    sentinel = inputs[1].parent / "foreign-sentinel"
    sentinel.write_bytes(b"foreign bytes must survive")
    original = os.open
    injected = False

    def inject(path, flags, *args, **kwargs):
        nonlocal injected
        if flags & os.O_CREAT and not injected:
            injected = True
            if kind == "symlink":
                os.symlink(str(sentinel), path, dir_fd=kwargs["dir_fd"])
            else:
                os.link(str(sentinel), path, dst_dir_fd=kwargs["dir_fd"])
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", inject)
    _refuse(lambda: _copy(inputs))
    assert injected and inputs[1].is_dir()
    assert sentinel.read_bytes() == b"foreign bytes must survive"


def test_observer_cannot_adopt_replaced_identical_tree(inputs, monkeypatch):
    original = tree.observe_extracted_toolchain_tree
    destination = inputs[1]
    retained = destination.with_name("retained-original")

    def replace(*args, **kwargs):
        destination.rename(retained)
        shutil.copytree(retained, destination)
        return original(*args, **kwargs)

    monkeypatch.setattr(tree, "observe_extracted_toolchain_tree", replace)
    _refuse(lambda: _copy(inputs))
    assert destination.stat().st_ino != retained.stat().st_ino
    for relative, (raw, _mode) in FILES.items():
        assert (retained / relative).read_bytes() == raw


def test_complete_inventory_exceeds_legacy_recipe_file_limit(tmp_path, monkeypatch):
    parent = tmp_path.resolve()
    os.chmod(parent, 0o700)
    count = 16_385
    names = {f"f{i:05d}" for i in range(count)}
    entries = [(ROOT, None, 0o755), *((ROOT + "/" + name, b"", 0o644) for name in sorted(names))]
    inputs = _bundle(parent, monkeypatch, entries), parent / "complete-copy"
    assert len(inputs[0][1]) > 1024 * 1024
    result = _copy(inputs)
    assert result.to_dict()["file_count"] == count
    assert {path.name for path in inputs[1].iterdir()} == names
    assert result.to_dict()["claims"] == dict.fromkeys(tree._CLAIMS, False)
