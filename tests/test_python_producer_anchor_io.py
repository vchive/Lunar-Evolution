import errno
import os
from pathlib import Path

import pytest
from test_python_producer_admission_anchor import _anchor

import lunar_evolution.python_producer_admission_anchor as anchor_io


def _path(tmp_path):
    return tmp_path / anchor_io.PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME


def _invoke(operation, path, anchor):
    if operation == "read":
        return anchor_io.read_python_producer_admission_attempt_anchor(
            path, expected_anchor_sha256=anchor.anchor_sha256,
        )
    return anchor_io.persist_python_producer_admission_attempt_anchor(path, anchor=anchor)


def _is_anchor_path(path):
    return Path(os.fspath(path)).name == anchor_io.PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME


@pytest.mark.parametrize("operation", ["read", "replay"])
@pytest.mark.parametrize("phase", ["already-fifo", "raced-before-open"])
def test_fifo_is_rejected_without_a_blocking_open(tmp_path, monkeypatch, operation, phase):
    path = _path(tmp_path)
    anchor = _anchor()
    if phase == "already-fifo":
        os.mkfifo(path, 0o600)
    else:
        anchor_io.persist_python_producer_admission_attempt_anchor(path, anchor=anchor)
    real_open = os.open
    observed_flags = []

    def checked_open(file, flags, mode=0o777, *, dir_fd=None):
        if _is_anchor_path(file):
            # Fail before the real open when the guard is missing; this test must
            # never wait for a writer on the FIFO it created.
            assert flags & os.O_NONBLOCK
            observed_flags.append(flags)
            if phase == "raced-before-open":
                path.unlink()
                os.mkfifo(path, 0o600)
        return real_open(file, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(anchor_io.os, "open", checked_open)
    with pytest.raises(anchor_io.PythonProducerAdmissionAnchorError, match="file_identity_invalid"):
        _invoke(operation, path, anchor)
    assert bool(observed_flags) is (phase == "raced-before-open")


@pytest.mark.parametrize("operation", ["read", "replay"])
@pytest.mark.parametrize("drift", ["hardlink", "mode"])
def test_existing_anchor_rejects_hardlink_or_mode_drift(tmp_path, operation, drift):
    anchor = _anchor()
    path = _path(tmp_path)
    anchor_io.persist_python_producer_admission_attempt_anchor(path, anchor=anchor)
    if drift == "hardlink":
        os.link(path, tmp_path / "second-anchor-link.json")
    else:
        path.chmod(0o644)

    with pytest.raises(
        anchor_io.PythonProducerAdmissionAnchorError,
        match="file_identity_(invalid|drift)",
    ):
        _invoke(operation, path, anchor)


def test_partial_writes_are_completed_before_admitting_anchor(tmp_path, monkeypatch):
    anchor = _anchor()
    path = _path(tmp_path)
    real_write = os.write
    writes = []

    def partial_write(descriptor, data):
        count = real_write(descriptor, data[:17])
        writes.append(count)
        return count

    monkeypatch.setattr(anchor_io.os, "write", partial_write)
    assert anchor_io.persist_python_producer_admission_attempt_anchor(path, anchor=anchor) == anchor
    assert len(writes) > 1
    assert sum(writes) == len(anchor.to_json())
    assert path.read_bytes() == anchor.to_json()
    assert path.stat().st_mode & 0o777 == 0o600
    assert anchor_io.read_python_producer_admission_attempt_anchor(path) == anchor


def test_zero_progress_write_preserves_partial_file_and_rejects_retry(tmp_path, monkeypatch):
    anchor = _anchor()
    path = _path(tmp_path)
    real_write = os.write
    writes = 0

    def stalled_write(descriptor, data):
        nonlocal writes
        writes += 1
        if writes == 1:
            return real_write(descriptor, data[:29])
        return 0

    monkeypatch.setattr(anchor_io.os, "write", stalled_write)
    with pytest.raises(anchor_io.PythonProducerAdmissionAnchorError, match="write_unknown"):
        anchor_io.persist_python_producer_admission_attempt_anchor(path, anchor=anchor)

    partial = path.read_bytes()
    identity = (path.stat().st_dev, path.stat().st_ino)
    assert partial == anchor.to_json()[:29]
    monkeypatch.setattr(anchor_io.os, "write", real_write)
    with pytest.raises(anchor_io.PythonProducerAdmissionAnchorError, match="already_exists"):
        anchor_io.persist_python_producer_admission_attempt_anchor(path, anchor=anchor)
    assert path.read_bytes() == partial
    assert (path.stat().st_dev, path.stat().st_ino) == identity


@pytest.mark.parametrize("operation", ["read", "replay"])
@pytest.mark.parametrize("mutation", ["touch", "same_bytes"])
def test_eof_revalidation_rejects_in_place_full_stat_drift(
    tmp_path, monkeypatch, operation, mutation,
):
    anchor = _anchor()
    path = _path(tmp_path)
    anchor_io.persist_python_producer_admission_attempt_anchor(path, anchor=anchor)
    # Give same-byte writes a deterministic mtime change, even on filesystems
    # whose clock cannot distinguish two operations in quick succession.
    os.utime(path, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    before = path.stat()
    real_read = os.read
    mutated = False

    def changing_read(descriptor, count):
        nonlocal mutated
        chunk = real_read(descriptor, count)
        info = os.fstat(descriptor)
        if not chunk and not mutated and (info.st_dev, info.st_ino) == (
            before.st_dev, before.st_ino,
        ):
            mutated = True
            if mutation == "touch":
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
            else:
                with path.open("r+b") as stream:
                    stream.write(anchor.to_json())
                    stream.flush()
        return chunk

    monkeypatch.setattr(anchor_io.os, "read", changing_read)
    with pytest.raises(anchor_io.PythonProducerAdmissionAnchorError, match="file_identity_drift"):
        _invoke(operation, path, anchor)
    assert mutated
    after = path.stat()
    assert (after.st_dev, after.st_ino, after.st_size) == (
        before.st_dev, before.st_ino, before.st_size,
    )
    assert (after.st_mtime_ns, after.st_ctime_ns) != (before.st_mtime_ns, before.st_ctime_ns)
    assert path.read_bytes() == anchor.to_json()


@pytest.mark.parametrize("operation", ["read", "replay"])
@pytest.mark.parametrize("phase", ["before_open", "after_open"])
def test_open_revalidation_rejects_same_bytes_on_replaced_inode(
    tmp_path, monkeypatch, operation, phase,
):
    anchor = _anchor()
    path = _path(tmp_path)
    retired = tmp_path / "retired-anchor.json"
    anchor_io.persist_python_producer_admission_attempt_anchor(path, anchor=anchor)
    original_inode = path.stat().st_ino
    real_open = os.open
    replaced = False

    def replace_path():
        nonlocal replaced
        replaced = True
        path.rename(retired)
        path.write_bytes(anchor.to_json())
        path.chmod(0o600)

    def replacing_open(file, flags, mode=0o777, *, dir_fd=None):
        targeted = _is_anchor_path(file) and not replaced
        if targeted and phase == "before_open":
            replace_path()
        descriptor = real_open(file, flags, mode, dir_fd=dir_fd)
        if targeted and phase == "after_open":
            replace_path()
        return descriptor

    monkeypatch.setattr(anchor_io.os, "open", replacing_open)
    with pytest.raises(anchor_io.PythonProducerAdmissionAnchorError, match="file_identity_drift"):
        _invoke(operation, path, anchor)
    assert replaced
    assert retired.stat().st_ino == original_inode
    assert path.stat().st_ino != original_inode
    assert path.read_bytes() == retired.read_bytes() == anchor.to_json()


def test_first_write_cannot_adopt_same_bytes_from_another_inode(tmp_path, monkeypatch):
    anchor = _anchor()
    path = _path(tmp_path)
    retired = tmp_path / "retired-first-write.json"
    real_write = os.write
    replaced = False

    def replacing_write(descriptor, data):
        nonlocal replaced
        count = real_write(descriptor, data)
        if not replaced:
            replaced = True
            path.rename(retired)
            path.write_bytes(anchor.to_json())
            path.chmod(0o600)
        return count

    monkeypatch.setattr(anchor_io.os, "write", replacing_write)
    with pytest.raises(anchor_io.PythonProducerAdmissionAnchorError, match="file_identity_drift"):
        anchor_io.persist_python_producer_admission_attempt_anchor(path, anchor=anchor)
    assert replaced
    assert retired.stat().st_ino != path.stat().st_ino
    assert path.read_bytes() == retired.read_bytes() == anchor.to_json()


def test_create_race_cannot_adopt_byte_identical_competitor(tmp_path, monkeypatch):
    anchor = _anchor()
    path = _path(tmp_path)
    real_open = os.open
    raced = False

    def competing_open(file, flags, mode=0o777, *, dir_fd=None):
        nonlocal raced
        if _is_anchor_path(file) and flags & os.O_CREAT and not raced:
            raced = True
            path.write_bytes(anchor.to_json())
            path.chmod(0o600)
            raise FileExistsError(errno.EEXIST, "competing creator", os.fspath(file))
        return real_open(file, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(anchor_io.os, "open", competing_open)
    with pytest.raises(anchor_io.PythonProducerAdmissionAnchorError, match="already_exists"):
        anchor_io.persist_python_producer_admission_attempt_anchor(path, anchor=anchor)
    assert raced
    assert path.read_bytes() == anchor.to_json()
