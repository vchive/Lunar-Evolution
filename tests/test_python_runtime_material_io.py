"""Portable guarded IO checks over inert declared blobs, never Python execution."""

from __future__ import annotations

import errno
import hashlib
import os
from collections.abc import Sequence

import pytest
from test_producer_python_runtime import _build, _path, _tree

from lunar_evolution import _python_runtime_material_io as io
from lunar_evolution import producer_python_runtime_tree as runtime
from lunar_evolution._python_runtime_material_format import PythonRuntimeMaterialError


def _fixture(tmp_path, *, large=False, zero=False):
    fixture = _tree(tmp_path)
    (fixture.roots["deps"] / "site/empty/nested").mkdir(parents=True)
    if large:
        _path(fixture, "project_source").write_bytes(bytes(range(256)) * 1025)
    if zero:
        _path(fixture, "project_resource").write_bytes(b"")
    original = _build(fixture)
    fixture.closed = runtime.build_python_runtime_tree_manifest(
        declared_manifest=original, expected_manifest_sha256=original.manifest_sha256,
        expected_target=original.target,
    )
    return fixture


def _expected(fixture):
    return b"".join((fixture.roots[file.root_label] / file.relative_path).read_bytes()
                    for file in sorted(fixture.closed.declared_manifest.files,
                                       key=lambda item: (item.root_label, item.relative_path)))


def _track(monkeypatch):
    opened, closed = [], []
    real_open, real_close = os.open, os.close

    def opening(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def closing(fd):
        closed.append(fd)
        return real_close(fd)

    monkeypatch.setattr(io.os, "open", opening)
    monkeypatch.setattr(io.os, "close", closing)
    return opened, closed


def _all_closed(opened):
    assert opened
    for fd in set(opened):
        with pytest.raises(OSError) as result:
            os.fstat(fd)
        assert result.value.errno == errno.EBADF


@pytest.mark.parametrize("large,zero", [(False, False), (True, False), (False, True)])
def test_canonical_stream_verifies_original_empty_membership_and_leaves_destination_owned(tmp_path, monkeypatch, large, zero):
    fixture = _fixture(tmp_path, large=large, zero=zero)
    expected = _expected(fixture)
    destination = os.open(tmp_path / "payload", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    opened, _closed = _track(monkeypatch)
    reads, writes, checkpoints = [], [], []
    real_read, real_write = os.read, os.write

    def reading(fd, size):
        reads.append(size)
        return real_read(fd, size)

    def writing(fd, chunk):
        writes.append(len(chunk))
        # Exercise actual positive partial writes, rather than accepting a
        # fabricated return count without writing bytes.
        return real_write(fd, chunk[:max(1, min(701, len(chunk)))])

    monkeypatch.setattr(io.os, "read", reading)
    monkeypatch.setattr(io.os, "write", writing)
    try:
        io.verify_source(fixture.closed, checkpoint=lambda: checkpoints.append(True))
        digest = io.copy_payload(fixture.closed, destination, checkpoint=lambda: checkpoints.append(True))
        assert digest == hashlib.sha256(expected).hexdigest()
        assert os.pread(destination, len(expected) + 1, 0) == expected
        assert os.fstat(destination).st_size == len(expected)
        assert max(reads) <= 65536 and max(writes) <= 65536
        assert 1 in reads  # EOF/growth sentinel, including the zero-size case.
        assert len(checkpoints) > len(reads) * 2
        _all_closed(opened)
    finally:
        os.close(destination)


@pytest.mark.parametrize("operation", ["verify", "copy"])
@pytest.mark.parametrize("drift", ["bytes", "mode", "hardlink", "file-symlink", "empty-member", "empty-directory"])
def test_original_source_drift_is_refused_without_copying_new_admission(tmp_path, operation, drift):
    fixture = _fixture(tmp_path)
    file = _path(fixture, "project_source")
    empty = fixture.roots["deps"] / "site/empty/nested"
    if drift == "bytes":
        file.write_bytes(b"changed")
    elif drift == "mode":
        file.chmod(0o400)
    elif drift == "hardlink":
        os.link(file, tmp_path / "alias")
    elif drift == "file-symlink":
        file.unlink()
        file.symlink_to(tmp_path / "decoy")
    elif drift == "empty-member":
        (empty / "unlisted").write_bytes(b"inert")
    else:
        empty.rmdir()
    destination = os.open(tmp_path / "payload", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with pytest.raises(PythonRuntimeMaterialError, match="source_drift"):
            if operation == "verify":
                io.verify_source(fixture.closed, checkpoint=lambda: None)
            else:
                io.copy_payload(fixture.closed, destination, checkpoint=lambda: None)
        os.fstat(destination)
    finally:
        os.close(destination)


@pytest.mark.parametrize("operation", ["verify", "copy"])
@pytest.mark.parametrize("mutation", ["same-bytes", "empty-membership"])
def test_final_closure_detects_earlier_root_drift_during_later_read(tmp_path, monkeypatch, operation, mutation):
    fixture = _fixture(tmp_path)
    files = sorted(fixture.closed.declared_manifest.files, key=lambda item: (item.root_label, item.relative_path))
    earlier = fixture.roots[files[0].root_label] / files[0].relative_path
    later = files[-1]
    real_read, changed = os.read, False

    def reading(fd, size):
        nonlocal changed
        chunk = real_read(fd, size)
        info = os.fstat(fd)
        if chunk and not changed and (info.st_dev, info.st_ino) == (later.device, later.inode):
            changed = True
            # Same bytes still change the pinned identity times. This happens
            # after the earlier root's byte/metadata observations completed.
            if mutation == "same-bytes":
                earlier.write_bytes(earlier.read_bytes())
            else:
                (fixture.roots["deps"] / "site/empty/nested/unlisted").write_bytes(b"inert")
        return chunk

    monkeypatch.setattr(io.os, "read", reading)
    destination = os.open(tmp_path / "payload", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with pytest.raises(PythonRuntimeMaterialError, match="source_drift"):
            if operation == "verify":
                io.verify_source(fixture.closed, checkpoint=lambda: None)
            else:
                io.copy_payload(fixture.closed, destination, checkpoint=lambda: None)
        assert changed
    finally:
        os.close(destination)


def test_held_parent_does_not_follow_root_name_replacement_during_read(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    file = fixture.closed.declared_manifest.files[0]
    original_root = fixture.roots[file.root_label]
    real_read, changed = os.read, False

    def reading(fd, size):
        nonlocal changed
        chunk = real_read(fd, size)
        info = os.fstat(fd)
        if not changed and (info.st_dev, info.st_ino) == (file.device, file.inode):
            changed = True
            original_root.rename(original_root.with_name(original_root.name + "-held"))
            original_root.mkdir()
        return chunk

    monkeypatch.setattr(io.os, "read", reading)
    with pytest.raises(PythonRuntimeMaterialError, match="source_drift"):
        io.verify_source(fixture.closed, checkpoint=lambda: None)
    assert changed


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit, lambda: PythonRuntimeMaterialError("deadline_expired")])
@pytest.mark.parametrize("boundary", ["after-open", "after-read"])
def test_interrupt_and_expiry_release_every_owned_fd_without_more_checkpoint_work(tmp_path, monkeypatch, exception, boundary):
    fixture = _fixture(tmp_path)
    opened, _closed = _track(monkeypatch)
    real_read, ready, raised = os.read, False, False

    def reading(fd, size):
        nonlocal ready
        value = real_read(fd, size)
        ready = True
        return value

    monkeypatch.setattr(io.os, "read", reading)

    def checkpoint():
        nonlocal raised
        if raised:
            pytest.fail("cleanup renewed the expired/interrupted checkpoint")
        if (boundary == "after-open" and opened) or (boundary == "after-read" and ready):
            raised = True
            raise exception()

    with pytest.raises((KeyboardInterrupt, SystemExit, PythonRuntimeMaterialError)):
        io.verify_source(fixture.closed, checkpoint=checkpoint)
    assert raised
    _all_closed(opened)


@pytest.mark.parametrize("write_result", [0, -1, True, 65537])
def test_zero_or_invalid_write_refuses_and_preserves_caller_destination(tmp_path, monkeypatch, write_result):
    fixture = _fixture(tmp_path)
    destination = os.open(tmp_path / "payload", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    opened, _closed = _track(monkeypatch)
    monkeypatch.setattr(io.os, "write", lambda *_args: write_result)
    try:
        with pytest.raises(PythonRuntimeMaterialError, match="source_write_failed"):
            io.copy_payload(fixture.closed, destination, checkpoint=lambda: None)
        os.fstat(destination)
        _all_closed(opened)
    finally:
        os.close(destination)


@pytest.mark.parametrize("zero", [False, True])
def test_growth_sentinel_bounds_the_read_and_never_writes_unadmitted_extra_bytes(tmp_path, monkeypatch, zero):
    fixture = _fixture(tmp_path, zero=zero)
    wanted = fixture.closed.declared_manifest.files[0]
    real_read, reads = os.read, []

    def reading(fd, size):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == (wanted.device, wanted.inode):
            reads.append(size)
            return b"x" * size  # Simulate a file that keeps growing.
        return real_read(fd, size)

    monkeypatch.setattr(io.os, "read", reading)
    destination = os.open(tmp_path / "payload", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with pytest.raises(PythonRuntimeMaterialError, match="source_drift"):
            io.copy_payload(fixture.closed, destination, checkpoint=lambda: None)
        assert reads == [min(65536, wanted.size + 1)]
        assert os.fstat(destination).st_size == 0
    finally:
        os.close(destination)


class _ForbiddenSequence(Sequence):
    def __len__(self):
        raise AssertionError("untrusted length callback")

    def __getitem__(self, index):
        pytest.fail("untrusted indexing callback")


@pytest.mark.parametrize("mutation", ["directories", "children", "roots", "files", "path", "path-utf8", "path-newline", "size", "digest"])
def test_invalid_shape_refuses_before_trusted_checkpoint_or_filesystem(tmp_path, monkeypatch, mutation):
    fixture = _fixture(tmp_path)
    original = fixture.closed.declared_manifest
    subject, name, value = {
        "directories": (fixture.closed, "directories", _ForbiddenSequence()),
        "children": (fixture.closed.directories[0], "children", _ForbiddenSequence()),
        "roots": (original, "roots", _ForbiddenSequence()),
        "files": (original, "files", _ForbiddenSequence()),
        "path": (original.files[0], "relative_path", "../escape"),
        "path-utf8": (original.files[0], "relative_path", "bad-\ud800"),
        "path-newline": (original.files[0], "relative_path", "bad\nname"),
        "size": (original.files[0], "size", True),
        "digest": (original.files[0], "sha256", "x" * 64),
    }[mutation]
    object.__setattr__(subject, name, value)

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid cheap shape reached checkpoint/filesystem")

    monkeypatch.setattr(io.os, "stat", forbidden)
    monkeypatch.setattr(io.os, "open", forbidden)
    with pytest.raises(PythonRuntimeMaterialError, match="source_shape_invalid"):
        io.verify_source(fixture.closed, checkpoint=forbidden)


@pytest.mark.parametrize("destination", [True, -1, 2**63, object()])
def test_invalid_destination_is_rejected_before_checkpoint(tmp_path, destination):
    fixture = _fixture(tmp_path)

    def forbidden():
        pytest.fail("invalid destination reached checkpoint")

    with pytest.raises(PythonRuntimeMaterialError, match="source_shape_invalid"):
        io.copy_payload(fixture.closed, destination, checkpoint=forbidden)


def test_io_failure_cleanup_attempts_every_fd_and_retains_only_fixed_note(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    opened, closed = _track(monkeypatch)
    real_close, failed_close, read_failed = os.close, False, False

    def reading(*_args):
        nonlocal read_failed
        read_failed = True
        raise OSError(errno.EIO, "sensitive injected source path")

    def closing(fd):
        nonlocal failed_close
        real_close(fd)
        if read_failed and not failed_close:
            failed_close = True
            raise OSError(errno.EIO, "sensitive injected close path")

    monkeypatch.setattr(io.os, "read", reading)
    monkeypatch.setattr(io.os, "close", closing)
    with pytest.raises(PythonRuntimeMaterialError, match="source_io_failed") as result:
        io.verify_source(fixture.closed, checkpoint=lambda: None)
    assert result.value.__notes__ == ["python_runtime_material_cleanup_unknown"]
    assert "sensitive" not in str(result.value)
    assert closed and failed_close
    _all_closed(opened)


def test_known_private_fd_substitution_is_not_closed_and_primary_is_preserved(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    foreign_path = tmp_path / "foreign"
    foreign_path.write_bytes(b"owned by caller")
    real_read, real_open, real_close = os.read, os.open, os.close
    substituted = []

    def reading(fd, size):
        real_close(fd)
        foreign = real_open(foreign_path, os.O_RDONLY)
        assert foreign == fd
        substituted.append(foreign)
        raise KeyboardInterrupt

    monkeypatch.setattr(io.os, "read", reading)
    try:
        with pytest.raises(KeyboardInterrupt) as result:
            io.verify_source(fixture.closed, checkpoint=lambda: None)
        assert result.value.__notes__ == ["python_runtime_material_cleanup_unknown"]
        assert len(substituted) == 1
        assert real_read(substituted[0], 100) == b"owned by caller"
    finally:
        for fd in substituted:
            real_close(fd)


@pytest.mark.parametrize("boundary", ["open", "stat", "fstat", "scandir", "scandir-next", "read", "write", "hash-update"])
def test_expiry_after_each_fs_stream_step_refuses_before_more_accepted_work(tmp_path, monkeypatch, boundary):
    fixture = _fixture(tmp_path)
    destination = os.open(tmp_path / "payload", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    opened, _closed = _track(monkeypatch)
    expired = False

    def checkpoint():
        if expired:
            raise PythonRuntimeMaterialError("deadline_expired")

    def mark():
        nonlocal expired
        expired = True

    if boundary == "scandir-next":
        real_scandir = os.scandir

        class Iterator:
            def __init__(self, fd):
                self.original = real_scandir(fd)

            def __next__(self):
                entry = next(self.original)
                mark()
                return entry

            def close(self):
                self.original.close()

        monkeypatch.setattr(io.os, "scandir", Iterator)
    elif boundary == "hash-update":
        real_sha = hashlib.sha256

        class Digest:
            def __init__(self):
                self.original = real_sha()

            def update(self, chunk):
                self.original.update(chunk)
                mark()

            def hexdigest(self):
                return self.original.hexdigest()

        monkeypatch.setattr(io.hashlib, "sha256", Digest)
    else:
        original_operation = getattr(os, boundary)

        def operation(*args, **kwargs):
            value = original_operation(*args, **kwargs)
            mark()
            return value

        monkeypatch.setattr(io.os, boundary, operation)
    try:
        with pytest.raises(PythonRuntimeMaterialError, match="deadline_expired"):
            if boundary == "write":
                io.copy_payload(fixture.closed, destination, checkpoint=checkpoint)
            else:
                io.verify_source(fixture.closed, checkpoint=checkpoint)
        assert expired
        if opened:
            _all_closed(opened)
        os.fstat(destination)
    finally:
        os.close(destination)
