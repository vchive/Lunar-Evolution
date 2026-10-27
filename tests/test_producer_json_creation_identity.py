"""Creation identity is anchored in the original atomic JSON write descriptor."""

from __future__ import annotations

import errno
import json
import os
import stat

import pytest

from lunar_evolution import producer_process
from lunar_evolution.producer_process import ProducerProcessError


def _track_creation_fds(monkeypatch):
    original_open = os.open
    original_fstat = os.fstat
    opened = []

    def track_open(path, flags, *args, **kwargs):
        fd = original_open(path, flags, *args, **kwargs)
        if (os.fspath(path).startswith(".producer-receipt-")
                and flags & os.O_ACCMODE == os.O_WRONLY):
            opened.append((fd, original_fstat(fd).st_ino))
        return fd

    monkeypatch.setattr(producer_process.os, "open", track_open)
    return opened, original_fstat


def _assert_creation_fds_closed(opened, original_fstat):
    assert len(opened) == 1
    with pytest.raises(OSError) as closed:
        original_fstat(opened[0][0])
    assert closed.value.errno == errno.EBADF


def test_default_atomic_json_keeps_none_and_close_before_publication(tmp_path, monkeypatch):
    target = tmp_path / "record.json"
    opened, original_fstat = _track_creation_fds(monkeypatch)
    original_replace = os.replace
    published = []

    def check_replace(*args, **kwargs):
        _assert_creation_fds_closed(opened, original_fstat)
        published.append(True)
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(producer_process.os, "replace", check_replace)
    assert producer_process._atomic_json(target, {"value": 1}) is None
    assert published == [True]
    assert target.read_bytes() == b'{"value":1}'
    _assert_creation_fds_closed(opened, original_fstat)
    assert not list(tmp_path.glob(".producer-receipt-*"))


def test_default_exclusive_atomic_json_keeps_create_only_replay(tmp_path):
    target = tmp_path / "record.json"
    assert producer_process._atomic_json(target, {"value": 1}, exclusive=True) is None
    with pytest.raises(ProducerProcessError, match="producer_process_attestation_replayed"):
        producer_process._atomic_json(target, {"value": 2}, exclusive=True)
    assert json.loads(target.read_bytes()) == {"value": 1}
    assert not list(tmp_path.glob(".producer-receipt-*"))


@pytest.mark.parametrize("exclusive", [False, True])
def test_capture_identity_uses_original_creation_fd_and_closes_it(tmp_path, monkeypatch, exclusive):
    target = tmp_path / "record.json"
    opened, original_fstat = _track_creation_fds(monkeypatch)
    original_fsync = os.fsync
    held_at_directory_sync = []

    def check_fsync(fd):
        result = original_fsync(fd)
        if stat.S_ISDIR(original_fstat(fd).st_mode):
            assert len(opened) == 1
            held_at_directory_sync.append(original_fstat(opened[0][0]).st_ino)
        return result

    monkeypatch.setattr(producer_process.os, "fsync", check_fsync)
    pin = producer_process._atomic_json(
        target, {"value": 1}, exclusive=exclusive, capture_identity=True,
    )
    assert type(pin) is tuple and len(pin) == 6
    assert pin == tuple(producer_process._file_identity(target).values())
    assert held_at_directory_sync == [opened[0][1]]
    assert pin[3] == opened[0][1]
    _assert_creation_fds_closed(opened, original_fstat)
    assert not list(tmp_path.glob(".producer-receipt-*"))


@pytest.mark.parametrize("exclusive", [False, True])
def test_same_bytes_replacement_before_atomic_return_never_becomes_creation_pin(
    tmp_path, monkeypatch, exclusive,
):
    target = tmp_path / "record.json"
    opened, original_fstat = _track_creation_fds(monkeypatch)
    original_fsync = os.fsync
    replaced = []

    def replace_at_directory_sync(fd):
        result = original_fsync(fd)
        if stat.S_ISDIR(original_fstat(fd).st_mode) and not replaced:
            original = target.stat()
            data = target.read_bytes()
            replacement = tmp_path / "replacement.json"
            replacement.write_bytes(data)
            replacement.chmod(stat.S_IMODE(original.st_mode))
            replacement.replace(target)
            replaced.append((original.st_ino, target.stat().st_ino))
            assert target.read_bytes() == data
        return result

    monkeypatch.setattr(producer_process.os, "fsync", replace_at_directory_sync)
    with pytest.raises(ProducerProcessError, match="producer_process_receipt_write_unknown"):
        producer_process._atomic_json(
            target, {"value": 1}, exclusive=exclusive, capture_identity=True,
        )
    assert len(replaced) == 1 and replaced[0][0] != replaced[0][1]
    _assert_creation_fds_closed(opened, original_fstat)
    assert not list(tmp_path.glob(".producer-receipt-*"))


@pytest.mark.parametrize("capture_identity", [False, True])
@pytest.mark.parametrize("failure", ["write", "file-fsync", "directory-fsync"])
def test_atomic_json_failure_closes_creation_fd_and_clears_temporary(
    tmp_path, monkeypatch, capture_identity, failure,
):
    target = tmp_path / "record.json"
    opened, original_fstat = _track_creation_fds(monkeypatch)
    original_write = os.write
    original_fsync = os.fsync

    def fail_write(fd, data):
        if failure == "write" and any(fd == item[0] for item in opened):
            raise OSError("injected creation write failure")
        return original_write(fd, data)

    def fail_fsync(fd):
        directory = stat.S_ISDIR(original_fstat(fd).st_mode)
        if ((failure == "file-fsync" and not directory)
                or (failure == "directory-fsync" and directory)):
            raise OSError("injected publication sync failure")
        return original_fsync(fd)

    monkeypatch.setattr(producer_process.os, "write", fail_write)
    monkeypatch.setattr(producer_process.os, "fsync", fail_fsync)
    with pytest.raises(ProducerProcessError, match="producer_process_receipt_write_unknown"):
        producer_process._atomic_json(target, {"value": 1}, capture_identity=capture_identity)
    _assert_creation_fds_closed(opened, original_fstat)
    assert target.exists() is (failure == "directory-fsync")
    assert not list(tmp_path.glob(".producer-receipt-*"))


@pytest.mark.parametrize("failure_call", [1, 2])
def test_creation_pin_stat_failure_closes_original_fd_and_clears_temporary(
    tmp_path, monkeypatch, failure_call,
):
    target = tmp_path / "record.json"
    opened, original_fstat = _track_creation_fds(monkeypatch)

    calls = []

    def fail_creation_fstat(fd):
        if any(fd == item[0] for item in opened):
            calls.append(fd)
            if len(calls) == failure_call:
                raise OSError("injected original descriptor stat failure")
        return original_fstat(fd)

    monkeypatch.setattr(producer_process.os, "fstat", fail_creation_fstat)
    with pytest.raises(ProducerProcessError, match="producer_process_receipt_write_unknown"):
        producer_process._atomic_json(target, {"value": 1}, capture_identity=True)
    _assert_creation_fds_closed(opened, original_fstat)
    assert target.exists() is (failure_call == 2)
    assert not list(tmp_path.glob(".producer-receipt-*"))
