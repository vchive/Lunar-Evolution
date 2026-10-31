"""Kernel-backed export ownership; these tests do not mount or accept a runtime."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import mmap
import os
import stat
import sys
from contextlib import contextmanager

import pytest

from tools.static_python_rsi_fixture import podman_sealed_prior as sealed

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="requires actual Linux memfd seals")
SEALS = ("F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")


def record(path, raw, executable=False):
    return {"path": path, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "executable": executable}


@contextmanager
def committed(tmp_path, values=None, *, maximum_bytes=8 * 1024**3):
    values = values if values is not None else {"data.o": (b"original object", False)}
    bank = sealed._SealedPriorBank(lambda: None, maximum_bytes=maximum_bytes)
    rows = [record(path, raw, executable) for path, (raw, executable) in values.items()]
    batch = bank.begin(rows)
    try:
        for row in rows:
            target = tmp_path / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(values[row["path"]][0])
            target.chmod(0o700 if row["executable"] else 0o600)
            fd = os.open(target, os.O_RDONLY | os.O_CLOEXEC)
            try:
                batch.capture(fd, row)
            finally:
                os.close(fd)
        batch.commit()
        yield bank, rows
    finally:
        batch.abort()
        bank.close()


def descriptor(source):
    assert source.startswith(f"/proc/{os.getpid()}/fd/")
    return int(source.rsplit("/", 1)[1])


def assert_closed(fds):
    for fd in fds:
        with pytest.raises(OSError) as caught:
            os.fstat(fd)
        assert caught.value.errno == errno.EBADF


def test_export_has_exact_independent_sealed_file_ranges_and_preserves_borrowed_offsets(tmp_path):
    values = {"bin/inert": (b"executable fixture bytes", True),
              "nested/data.o": (b"object fixture bytes", False), "empty": (b"", False)}
    with committed(tmp_path, values) as (bank, rows):
        lease = bank.export_worker_prior(rows)
        mounts = lease.mounts()
        assert type(mounts) is tuple and all(type(pair) is tuple for pair in mounts)
        assert {path for path, _source in mounts} == set(values)
        owned = []
        for path, source in mounts:
            raw, executable = values[path]
            original = descriptor(source)
            owned.append(original)
            info = os.fstat(original)
            assert stat.S_ISREG(info.st_mode) and info.st_nlink == 0
            assert info.st_size == len(raw) and stat.S_IMODE(info.st_mode) == (0o500 if executable else 0o400)
            assert not os.get_inheritable(original)
            required = sum(getattr(fcntl, name) for name in SEALS)
            assert fcntl.fcntl(original, fcntl.F_GET_SEALS) & required == required
            borrowed = os.open(source, os.O_RDONLY | os.O_CLOEXEC)
            try:
                assert os.pread(borrowed, len(raw) + 1, 0) == raw
                os.lseek(borrowed, min(3, len(raw)), os.SEEK_SET)
                position = os.lseek(borrowed, 0, os.SEEK_CUR)
                lease.verify_leaf(path, borrowed)
                assert os.lseek(borrowed, 0, os.SEEK_CUR) == position
            finally:
                os.close(borrowed)
            (tmp_path / path).write_bytes(b"changed mutable work mirror")
            assert os.pread(original, len(raw) + 1, 0) == raw
        assert len(set(owned)) == len(values)
        lease.close()
        assert_closed(owned)
        assert all(bank.read_record(row) == values[row["path"]][0] for row in rows)


@pytest.mark.parametrize("executable", [False, True])
@pytest.mark.parametrize("operation", ["pwrite", "shrink", "grow", "mapping", "add-seal"])
def test_exported_inode_rejects_mutation_through_original_and_alias_handles(tmp_path, executable, operation):
    raw = b"sealed leaf bytes"
    with committed(tmp_path, {"leaf": (raw, executable)}) as (bank, rows):
        lease = bank.export_worker_prior(rows)
        _path, source = lease.mounts()[0]
        # Retain the original writable-open description across chmod/sealing;
        # a new O_RDWR proc open could be refused by mode before reaching seals.
        alias = os.dup(descriptor(source))
        try:
            with pytest.raises((OSError, ValueError)):
                if operation == "pwrite":
                    os.pwrite(alias, b"x", 0)
                elif operation == "shrink":
                    os.ftruncate(alias, 1)
                elif operation == "grow":
                    os.ftruncate(alias, len(raw) + 1)
                elif operation == "mapping":
                    with mmap.mmap(alias, len(raw), access=mmap.ACCESS_WRITE):
                        pytest.fail("sealed leaf admitted writable shared mapping")
                else:
                    fcntl.fcntl(alias, fcntl.F_ADD_SEALS, 0)
            lease.verify_leaf("leaf", alias)
            assert os.pread(alias, len(raw) + 1, 0) == raw
        finally:
            os.close(alias)


def test_empty_export_is_owned_exclusive_and_released_by_bank_close(tmp_path):
    with committed(tmp_path, {}) as (bank, rows):
        lease = bank.export_worker_prior(rows)
        assert lease.mounts() == ()
        with pytest.raises(ValueError):
            bank.export_worker_prior(rows)
        with pytest.raises(ValueError):
            bank.begin([])
        bank.close()
        lease.close()
        with pytest.raises(ValueError):
            lease.mounts()
        with pytest.raises(ValueError):
            bank.export_worker_prior(rows)


@pytest.mark.parametrize("drift", ["missing", "extra", "duplicate", "hash", "mode", "size"])
def test_export_refuses_detached_inventory_drift_before_acquiring_leaf(tmp_path, monkeypatch, drift):
    with committed(tmp_path) as (bank, rows):
        requested = [dict(row) for row in rows]
        if drift == "missing":
            requested.clear()
        elif drift == "extra":
            requested.append(record("other", b""))
        elif drift == "duplicate":
            requested.append(dict(requested[0]))
        elif drift == "hash":
            requested[0]["sha256"] = "f" * 64
        elif drift == "mode":
            requested[0]["executable"] = True
        else:
            requested[0]["size"] += 1
        monkeypatch.setattr(sealed.os, "memfd_create",
                            lambda *_a, **_k: pytest.fail("invalid inventory allocated a leaf"))
        with pytest.raises(ValueError):
            bank.export_worker_prior(requested)


def test_pending_group_cannot_be_exported_and_closed_lease_cannot_be_reused(tmp_path):
    with committed(tmp_path) as (bank, rows):
        pending = bank.begin([])
        with pytest.raises(ValueError):
            bank.export_worker_prior(rows)
        pending.abort()
        lease = bank.export_worker_prior(rows)
        mount = lease.mounts()[0]
        fd = os.open(mount[1], os.O_RDONLY | os.O_CLOEXEC)
        try:
            lease.close()
            for call in (lease.mounts, lambda: lease.verify_leaf(mount[0], fd)):
                with pytest.raises(ValueError):
                    call()
            successor = bank.export_worker_prior(rows)
            successor.verify_leaf(mount[0], descriptor(successor.mounts()[0][1]))
            successor.close()
        finally:
            os.close(fd)


@pytest.mark.parametrize("replacement", ["ordinary", "sealed-clone"])
def test_matching_bytes_from_a_different_inode_do_not_supply_export_ownership(tmp_path, replacement):
    raw = b"identical contents"
    with committed(tmp_path, {"data.o": (raw, False)}) as (bank, rows):
        lease = bank.export_worker_prior(rows)
        if replacement == "ordinary":
            fd = os.open(tmp_path / "data.o", os.O_RDONLY | os.O_CLOEXEC)
        else:
            fd = os.memfd_create("unrelated-clone", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            os.write(fd, raw)
            os.fchmod(fd, 0o400)
            fcntl.fcntl(fd, fcntl.F_ADD_SEALS, sum(getattr(fcntl, name) for name in SEALS))
        try:
            with pytest.raises((ValueError, OSError)):
                lease.verify_leaf("data.o", fd)
        finally:
            os.close(fd)


def test_combined_bank_and_export_byte_budget_refuses_before_allocation(tmp_path, monkeypatch):
    with committed(tmp_path, {"data.o": (b"123456", False)}, maximum_bytes=10) as (bank, rows):
        monkeypatch.setattr(sealed.os, "memfd_create",
                            lambda *_a, **_k: pytest.fail("over-budget export allocated a leaf"))
        with pytest.raises(ValueError):
            bank.export_worker_prior(rows)
        assert bank.read_record(rows[0]) == b"123456"


@pytest.mark.parametrize("files,frames", [(4097, 1), (4095, 2)])
def test_file_and_combined_descriptor_limits_precede_all_leaf_allocation(tmp_path, monkeypatch, files, frames):
    bank = sealed._SealedPriorBank(lambda: None)
    source = tmp_path / "empty"
    source.write_bytes(b"")
    fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC)
    rows = [record(f"leaf-{index}", b"") for index in range(files)]
    try:
        for group in (rows[index::frames] for index in range(frames)):
            batch = bank.begin(group)
            try:
                for row in group:
                    batch.capture(fd, row)
                batch.commit()
            finally:
                batch.abort()
        monkeypatch.setattr(sealed.os, "memfd_create",
                            lambda *_a, **_k: pytest.fail("over-budget export allocated a leaf"))
        with pytest.raises(ValueError):
            bank.export_worker_prior(rows)
    finally:
        os.close(fd)
        bank.close()


@pytest.mark.parametrize("failure", ["create", "write", "seal"])
@pytest.mark.parametrize("cleanup_unknown", [False, True])
def test_partial_export_failure_closes_every_leaf_and_leaves_bank_available(
        tmp_path, monkeypatch, failure, cleanup_unknown):
    values = {"a": (b"first", False), "b": (b"second", False)}
    with committed(tmp_path, values) as (bank, rows):
        created = []
        fault = KeyboardInterrupt("original export cancellation")
        real_create, real_write, real_fcntl, real_close = os.memfd_create, os.pwrite, fcntl.fcntl, os.close

        def create(*args, **kwargs):
            if len(created) == 1 and failure == "create":
                raise fault
            fd = real_create(*args, **kwargs)
            created.append(fd)
            return fd

        def write(fd, *args):
            if len(created) == 2 and fd == created[-1] and failure == "write":
                raise fault
            return real_write(fd, *args)

        def control(fd, operation, *args):
            if len(created) == 2 and fd == created[-1] and operation == fcntl.F_ADD_SEALS and failure == "seal":
                raise fault
            return real_fcntl(fd, operation, *args)

        def close(fd):
            real_close(fd)
            if cleanup_unknown and fd in created:
                raise OSError(errno.EIO, "close result unknown")

        with monkeypatch.context() as patch:
            patch.setattr(sealed.os, "memfd_create", create)
            patch.setattr(sealed.os, "pwrite", write)
            patch.setattr(sealed.fcntl, "fcntl", control)
            patch.setattr(sealed.os, "close", close)
            with pytest.raises(KeyboardInterrupt) as caught:
                bank.export_worker_prior(rows)
            assert caught.value is fault
            if cleanup_unknown:
                assert "podman_sealed_prior_cleanup_unknown" in fault.__notes__
        assert_closed(created)
        assert all(bank.read_record(row) == values[row["path"]][0] for row in rows)
        lease = bank.export_worker_prior(rows)
        assert len(lease.mounts()) == 2
        lease.close()


def test_bank_close_does_not_close_a_foreign_reused_leaf_descriptor(tmp_path):
    with committed(tmp_path) as (bank, rows):
        lease = bank.export_worker_prior(rows)
        leaf = descriptor(lease.mounts()[0][1])
        foreign = os.open(tmp_path / "data.o", os.O_RDONLY | os.O_CLOEXEC)
        os.dup2(foreign, leaf, inheritable=False)
        try:
            with pytest.raises(ValueError) as caught:
                bank.close()
            assert caught.value.code == "podman_sealed_prior_cleanup_unknown"
            assert os.fstat(leaf).st_ino == os.fstat(foreign).st_ino
            bank.close()
            assert os.fstat(leaf).st_ino == os.fstat(foreign).st_ino
        finally:
            os.close(leaf)
            os.close(foreign)


@pytest.mark.parametrize("path,borrowed", [("data.o", None), ("data.o", True),
                                          ("data.o", -1), ("unknown", 0)])
def test_lease_refuses_invalid_borrowed_handle_or_unbound_name(tmp_path, path, borrowed):
    with committed(tmp_path) as (bank, rows):
        lease = bank.export_worker_prior(rows)
        with pytest.raises(ValueError):
            lease.verify_leaf(path, borrowed)


@pytest.mark.parametrize("drift", ["pid", "mode"])
def test_lease_refuses_original_process_or_leaf_mode_drift(tmp_path, monkeypatch, drift):
    with committed(tmp_path) as (bank, rows):
        lease = bank.export_worker_prior(rows)
        fd = descriptor(lease.mounts()[0][1])
        if drift == "pid":
            original = os.getpid()
            monkeypatch.setattr(sealed.os, "getpid", lambda: original + 1)
        else:
            os.fchmod(fd, 0o600)
        with pytest.raises(ValueError):
            lease.mounts()


@pytest.mark.parametrize("moment", ["before-allocation", "after-allocation"])
def test_original_checkpoint_failure_is_preserved_without_partial_lease(tmp_path, monkeypatch, moment):
    with committed(tmp_path) as (bank, rows):
        original_create = os.memfd_create
        created = []
        fault = TimeoutError("original attempt allowance exhausted")

        def create(*args, **kwargs):
            fd = original_create(*args, **kwargs)
            created.append(fd)
            return fd

        def checkpoint():
            if moment == "before-allocation" or created:
                raise fault

        with monkeypatch.context() as patch:
            patch.setattr(sealed.os, "memfd_create", create)
            patch.setattr(bank, "_checkpoint", checkpoint)
            with pytest.raises(TimeoutError) as caught:
                bank.export_worker_prior(rows)
            assert caught.value is fault
        assert len(created) == (0 if moment == "before-allocation" else 1)
        assert_closed(created)
        lease = bank.export_worker_prior(rows)
        assert len(lease.mounts()) == 1


@pytest.mark.parametrize("primary_present", [False, True])
def test_bank_close_releases_frames_and_all_leaves_despite_one_unknown_close(
        tmp_path, monkeypatch, primary_present):
    created = []
    original_create, original_close = os.memfd_create, os.close

    def create(*args, **kwargs):
        fd = original_create(*args, **kwargs)
        created.append(fd)
        return fd

    monkeypatch.setattr(sealed.os, "memfd_create", create)
    values = {"a": (b"one", False), "b": (b"two", False)}
    with committed(tmp_path, values) as (bank, rows):
        lease = bank.export_worker_prior(rows)
        assert len(created) == 3
        attempts = []

        def close(fd):
            original_close(fd)
            if fd in created:
                attempts.append(fd)
                if fd == created[0]:
                    raise OSError(errno.EIO, "original frame close result unknown")

        monkeypatch.setattr(sealed.os, "close", close)
        primary = RuntimeError("original attempt failure")
        if primary_present:
            with pytest.raises(RuntimeError) as caught:
                try:
                    raise primary
                finally:
                    bank.close(primary)
            assert caught.value is primary
            assert "podman_sealed_prior_cleanup_unknown" in primary.__notes__
        else:
            with pytest.raises(ValueError) as caught:
                bank.close()
            assert caught.value.code == "podman_sealed_prior_cleanup_unknown"
        assert sorted(attempts) == sorted(created)
        assert_closed(created)
        lease.close()
        bank.close()
        assert len(attempts) == 3
