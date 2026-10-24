"""Independent ownership and final-observer counterexamples for inert copies."""

from __future__ import annotations

import dataclasses
import errno
import hashlib
import io
import json
import lzma
import os
import shutil
import tarfile
import time
from types import SimpleNamespace

import pytest

from tools.static_python_fixture import archive_observation as archives
from tools.static_python_fixture import toolchain_tree_observation as trees
from tools.static_python_fixture import verified_inputs
from tools.static_python_rsi_fixture import toolchain_private_copy as copying

ROOT = "zig-x86_64-linux-0.16.0"


@pytest.fixture
def copy_input(tmp_path, monkeypatch):
    parent = tmp_path.resolve()
    parent.chmod(0o700)
    table = [(ROOT, None, 0o755), (ROOT + "/lib", None, 0o755),
             (ROOT + "/lib/empty-directory", None, 0o755),
             (ROOT + "/lib/a", b"first inert data\n", 0o644),
             (ROOT + "/zig", b"never run this payload\n", 0o755)]
    stream, members = io.BytesIO(), []
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data, mode in table:
            member = tarfile.TarInfo(name)
            member.type = tarfile.DIRTYPE if data is None else tarfile.REGTYPE
            member.mode, member.size = mode, 0 if data is None else len(data)
            archive.addfile(member, None if data is None else io.BytesIO(data))
            members.append({"path": name, "kind": "directory" if data is None else "file",
                            "mode": mode, "size": member.size,
                            "sha256": None if data is None else hashlib.sha256(data).hexdigest()})
    compressed = lzma.compress(stream.getvalue(), format=lzma.FORMAT_XZ)
    digest = hashlib.sha256(compressed).hexdigest()
    monkeypatch.setitem(archives._PROFILES, "zig", dataclasses.replace(
        archives._PROFILES["zig"], size=len(compressed), sha256=digest,
    ))
    monkeypatch.setattr(verified_inputs, "_ZIG", dataclasses.replace(
        verified_inputs._ZIG, size=len(compressed), sha256=digest,
    ))
    manifest = json.dumps({
        "schema": verified_inputs.EXTRACTION_MANIFEST_SCHEMA,
        "archive": "zig", "root": ROOT, "archive_sha256": digest,
        "members": sorted(members, key=lambda member: member["path"]),
    }, sort_keys=True, separators=(",", ":")).encode()
    source = parent / "transport.xz"
    source.write_bytes(compressed)
    snapshot = archives.snapshot_archive(str(source), "zig", deadline=time.monotonic() + 30.0)
    return SimpleNamespace(snapshot=snapshot, manifest=manifest,
                           pin=hashlib.sha256(manifest).hexdigest(), destination=parent / "copy")


def _copy(fixture, **changes):
    options = {"expected_manifest_sha256": fixture.pin,
               "destination_directory": str(fixture.destination),
               "deadline": time.monotonic() + 30.0}
    options.update(changes)
    return copying._materialize_toolchain_copy(fixture.snapshot, fixture.manifest, **options)


def _descriptor_audit(monkeypatch):
    opened, duplicated, closed = os.open, os.dup, os.close
    state = SimpleNamespace(active={}, closed=[])

    def open_fd(path, flags, *args, **kwargs):
        fd = opened(path, flags, *args, **kwargs)
        state.active[fd] = flags
        return fd

    def dup_fd(fd):
        new_fd = duplicated(fd)
        state.active[new_fd] = state.active.get(fd, os.O_RDONLY)
        return new_fd

    def close_fd(fd):
        closed(fd)
        state.active.pop(fd, None)
        state.closed.append(fd)

    monkeypatch.setattr(os, "open", open_fd)
    monkeypatch.setattr(os, "dup", dup_fd)
    monkeypatch.setattr(os, "close", close_fd)
    return state


def test_all_writers_are_closed_before_observer_with_original_deadline(copy_input, monkeypatch):
    audit = _descriptor_audit(monkeypatch)
    observer = trees.observe_extracted_toolchain_tree
    now = lambda: 1.0
    called = False

    def observe(*args, **kwargs):
        nonlocal called
        called = True
        assert kwargs["deadline"] == 123.0 and kwargs["monotonic"] is now
        assert not any(flags & os.O_ACCMODE in {os.O_WRONLY, os.O_RDWR}
                       for flags in audit.active.values())
        return observer(*args, **kwargs)

    monkeypatch.setattr(trees, "observe_extracted_toolchain_tree", observe)
    _copy(copy_input, deadline=123.0, monotonic=now)
    assert called and not audit.active


@pytest.mark.parametrize("tamper", [
    "identity", "claim_true", "claim_missing", "claim_zero", "claim_extra", "manifest",
])
def test_observer_result_cannot_change_original_root_manifest_or_false_claims(
    copy_input, monkeypatch, tamper,
):
    observer = trees.observe_extracted_toolchain_tree

    def changed(*args, **kwargs):
        result = observer(*args, **kwargs)
        if tamper == "manifest":
            return dataclasses.replace(result, manifest_json=result.manifest_json + b" ")
        record = result.to_dict()
        if tamper == "identity":
            record["tree_identity"]["inode"] += 1
        elif tamper == "claim_true":
            record["claims"]["immutable_custody_established"] = True
        elif tamper == "claim_missing":
            record["claims"].pop("immutable_custody_established")
        elif tamper == "claim_zero":
            record["claims"]["immutable_custody_established"] = 0
        else:
            record["claims"]["unexpected_authority"] = False
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        return dataclasses.replace(result, canonical_json=canonical,
                                   observation_sha256=hashlib.sha256(canonical).hexdigest())

    monkeypatch.setattr(trees, "observe_extracted_toolchain_tree", changed)
    with pytest.raises(copying.StaticPythonToolchainCopyError):
        _copy(copy_input)
    assert copy_input.destination.is_dir()


def test_replacement_after_observer_is_refused_even_with_identical_bytes(copy_input, monkeypatch):
    observer = trees.observe_extracted_toolchain_tree
    retained = copy_input.destination.with_name("retained-original")

    def replace(*args, **kwargs):
        result = observer(*args, **kwargs)
        copy_input.destination.rename(retained)
        shutil.copytree(retained, copy_input.destination)
        return result

    monkeypatch.setattr(trees, "observe_extracted_toolchain_tree", replace)
    with pytest.raises(copying.StaticPythonToolchainCopyError):
        _copy(copy_input)
    assert retained.is_dir() and copy_input.destination.is_dir()


@pytest.mark.parametrize("mutation", ["extra_file", "remove_empty_directory"])
def test_final_clock_callback_cannot_change_unobserved_nested_inventory(
    copy_input, monkeypatch, mutation,
):
    observer = trees.observe_extracted_toolchain_tree
    observed, later_callbacks = False, 0
    extra = copy_input.destination / "lib" / "unexpected"
    empty = copy_input.destination / "lib" / "empty-directory"

    def observe(*args, **kwargs):
        nonlocal observed
        result = observer(*args, **kwargs)
        observed = True
        return result

    def now():
        nonlocal later_callbacks
        if observed:
            later_callbacks += 1
            if later_callbacks == 2:
                if mutation == "extra_file":
                    extra.write_bytes(b"added after the complete observer")
                else:
                    empty.rmdir()
        return 1.0

    monkeypatch.setattr(trees, "observe_extracted_toolchain_tree", observe)
    with pytest.raises(copying.StaticPythonToolchainCopyError):
        _copy(copy_input, deadline=100.0, monotonic=now)
    assert later_callbacks >= 2
    assert extra.is_file() if mutation == "extra_file" else not empty.exists()


def test_failure_on_first_writer_fstat_still_closes_all_acquired_descriptors(copy_input, monkeypatch):
    audit = _descriptor_audit(monkeypatch)
    opened, fstat = os.open, os.fstat
    pending, failed = None, False

    def open_writer(path, flags, *args, **kwargs):
        nonlocal pending
        fd = opened(path, flags, *args, **kwargs)
        if flags & os.O_ACCMODE == os.O_WRONLY:
            pending = fd
        return fd

    def fail_first(fd):
        nonlocal failed
        if fd == pending and not failed:
            failed = True
            raise OSError(errno.EIO, "injected first fstat failure")
        return fstat(fd)

    monkeypatch.setattr(os, "open", open_writer)
    monkeypatch.setattr(os, "fstat", fail_first)
    with pytest.raises(copying.StaticPythonToolchainCopyError):
        _copy(copy_input)
    assert failed and not audit.active and copy_input.destination.is_dir()


def test_known_foreign_writer_fd_reuse_is_not_closed(copy_input, monkeypatch):
    foreign_path = copy_input.destination.with_name("foreign-owner")
    foreign_path.write_bytes(b"foreign data")
    foreign = os.open(foreign_path, os.O_RDONLY)
    foreign_identity = os.fstat(foreign)
    write, close, dup2 = os.write, os.close, os.dup2
    reused = None

    def rebind(fd, data):
        nonlocal reused
        written = write(fd, data)
        if reused is None:
            dup2(foreign, fd)
            reused = fd
        return written

    monkeypatch.setattr(os, "write", rebind)
    try:
        with pytest.raises(copying.StaticPythonToolchainCopyError) as caught:
            _copy(copy_input)
        assert reused is not None
        assert os.fstat(reused).st_ino == foreign_identity.st_ino
        assert "static_python_toolchain_copy_cleanup_unknown" in caught.value.__notes__
    finally:
        close(foreign)
        if reused is not None:
            close(reused)


def test_interrupt_plus_unknown_close_preserves_primary_and_releases_remaining_roles(
    copy_input, monkeypatch,
):
    audit = _descriptor_audit(monkeypatch)
    opened, closed = os.open, os.close
    writer, injected = None, False
    primary = KeyboardInterrupt("injected writer interruption")

    def open_writer(path, flags, *args, **kwargs):
        nonlocal writer
        fd = opened(path, flags, *args, **kwargs)
        if flags & os.O_ACCMODE == os.O_WRONLY:
            writer = fd
        return fd

    def interrupt(_fd, _data):
        raise primary

    def unknown(fd):
        nonlocal injected
        closed(fd)
        if fd == writer and not injected:
            injected = True
            raise OSError(errno.EIO, "close completed but result unknown")

    monkeypatch.setattr(os, "open", open_writer)
    monkeypatch.setattr(os, "write", interrupt)
    monkeypatch.setattr(os, "close", unknown)
    with pytest.raises(KeyboardInterrupt) as caught:
        _copy(copy_input)
    assert caught.value is primary and injected and not audit.active
    assert "static_python_toolchain_copy_cleanup_unknown" in caught.value.__notes__


@pytest.mark.parametrize("failure", ["timeout", "interrupt"])
def test_archive_checkpoint_preserves_original_timeout_or_interrupt_before_mutation(
    copy_input, monkeypatch, failure,
):
    decompress = archives._decompress
    decoding = False
    primary = KeyboardInterrupt("injected archive checkpoint interruption")

    def arm(*args, **kwargs):
        nonlocal decoding
        decoding = True
        return decompress(*args, **kwargs)

    def now():
        if decoding:
            if failure == "interrupt":
                raise primary
            return 101.0
        return 1.0

    monkeypatch.setattr(archives, "_decompress", arm)
    if failure == "interrupt":
        with pytest.raises(KeyboardInterrupt) as caught:
            _copy(copy_input, deadline=100.0, monotonic=now)
        assert caught.value is primary
    else:
        with pytest.raises(copying.StaticPythonToolchainCopyError) as caught:
            _copy(copy_input, deadline=100.0, monotonic=now)
        assert caught.value.reason == "static_python_toolchain_copy_wall_timeout"
    assert decoding and not copy_input.destination.exists()
