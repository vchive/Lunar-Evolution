"""Original output FDs and actual Linux seals protect retained staging bytes.

No Podman, compiler, target or solver runs. A sealed staging source does not
protect the ordinary destination bind throughout a later worker's execution.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import mmap
import os
import sys
from contextlib import contextmanager

import pytest

from tools.static_python_rsi_fixture import podman_sealed_prior as sealed

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="requires actual Linux memfd seals")
REFUSALS = (ValueError, OSError)
SEAL_NAMES = ("F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")


def row(path, raw, *, executable=False):
    return {"path": path, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "executable": executable}


def write(root, path, raw, *, executable=False):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    target.chmod(0o700 if executable else 0o600)
    return target


@contextmanager
def output_fd(root, record):
    descriptor = os.open(root / record["path"], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def capture(bank, root, records):
    batch = bank.begin(records)
    try:
        for record in records:
            with output_fd(root, record) as descriptor:
                batch.capture(descriptor, record)
        batch.commit()
    except BaseException as error:
        batch.abort(error)
        raise
    return batch


def tracked_frames(monkeypatch):
    original = os.memfd_create
    descriptors = []

    def create(*args, **kwargs):
        descriptor = original(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(sealed.os, "memfd_create", create)
    return descriptors


def assert_closed(descriptors):
    for descriptor in descriptors:
        with pytest.raises(OSError) as caught:
            os.fstat(descriptor)
        assert caught.value.errno == errno.EBADF


@LINUX
def test_original_outputs_share_one_sealed_frame_and_keep_borrowed_offsets(tmp_path, monkeypatch):
    root = tmp_path / "outputs"
    values = {"bin/tool": (b"inert generated helper", True),
              "objects/unit.o": (b"original object bytes", False), "empty": (b"", False)}
    records = [row(path, raw, executable=executable)
               for path, (raw, executable) in sorted(values.items())]
    for path, (raw, executable) in values.items():
        write(root, path, raw, executable=executable)
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        batch = bank.begin(records)
        for record in reversed(records):
            with output_fd(root, record) as descriptor:
                position = min(record["size"], 3)
                os.lseek(descriptor, position, os.SEEK_SET)
                before = os.fstat(descriptor)
                batch.capture(descriptor, record)
                assert os.lseek(descriptor, 0, os.SEEK_CUR) == position
                assert os.fstat(descriptor).st_ino == before.st_ino
        with pytest.raises(REFUSALS):
            bank.read_record(records[0])
        batch.commit()
        assert len(frames) == 1
        required = sum(getattr(fcntl, name) for name in SEAL_NAMES)
        assert fcntl.fcntl(frames[0], fcntl.F_GET_SEALS) & required == required
        assert not os.get_inheritable(frames[0])
        assert not os.fstat(frames[0]).st_mode & 0o111
        for record in records:
            assert bank.read_record(record) == values[record["path"]][0]
        destination = tmp_path / "prior"
        bank.snapshot(destination, records)
        for path, (raw, executable) in values.items():
            target = destination / path
            assert target.read_bytes() == raw
            assert bool(target.stat().st_mode & 0o111) is executable
            assert not target.stat().st_mode & 0o222
    finally:
        bank.close()
    assert_closed(frames)


@LINUX
@pytest.mark.parametrize("operation", ["write", "pwrite", "shrink", "grow", "mapping", "add-seal"])
def test_actual_kernel_seals_reject_every_later_write_route(tmp_path, monkeypatch, operation):
    record = row("object.o", b"original retained bytes")
    write(tmp_path, record["path"], b"original retained bytes")
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        capture(bank, tmp_path, [record])
        descriptor = frames[0]
        size = os.fstat(descriptor).st_size
        with pytest.raises((OSError, ValueError)):
            if operation == "write":
                os.write(descriptor, b"x")
            elif operation == "pwrite":
                os.pwrite(descriptor, b"x", 0)
            elif operation == "shrink":
                os.ftruncate(descriptor, max(0, size - 1))
            elif operation == "grow":
                os.ftruncate(descriptor, size + 1)
            elif operation == "mapping":
                with mmap.mmap(descriptor, size, access=mmap.ACCESS_WRITE):
                    pytest.fail("sealed frame admitted a shared writable mapping")
            else:
                fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, fcntl.F_SEAL_WRITE)
        assert bank.read_record(record) == b"original retained bytes"
    finally:
        bank.close()
    assert_closed(frames)


@LINUX
def test_later_source_overwrite_and_name_replacement_cannot_change_staging_bytes(tmp_path):
    root = tmp_path / "outputs"
    original = b"stable original output"
    record = row("objects/unit.o", original)
    target = write(root, record["path"], original)
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        capture(bank, root, [record])
        target.write_bytes(b"changed live output")
        target.unlink()
        write(root, record["path"], original + b" replacement")
        destination = tmp_path / "prior"
        bank.snapshot(destination, [record])
        assert (destination / record["path"]).read_bytes() == original
        assert bank.read_record(record) == original
    finally:
        bank.close()


@LINUX
def test_pending_batch_is_unavailable_until_commit_and_abort_exposes_no_prefix(tmp_path):
    records = [row("a.o", b"first"), row("b.o", b"second")]
    for record, raw in zip(records, (b"first", b"second"), strict=True):
        write(tmp_path, record["path"], raw)
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        batch = bank.begin(records)
        with output_fd(tmp_path, records[0]) as descriptor:
            batch.capture(descriptor, records[0])
        with pytest.raises(REFUSALS):
            bank.read_record(records[0])
        destination = tmp_path / "unpublished"
        with pytest.raises(REFUSALS):
            bank.snapshot(destination, records)
        assert not destination.exists()
        with pytest.raises(REFUSALS):
            batch.commit()
        batch.abort()
        for record in records:
            with pytest.raises(REFUSALS):
                bank.read_record(record)
        assert not destination.exists()
        capture(bank, tmp_path, records)
        assert bank.read_record(records[1]) == b"second"
    finally:
        bank.close()


@LINUX
@pytest.mark.parametrize("change", ["bytes", "size", "execute-bit", "missing-capture"])
def test_late_group_failure_never_publishes_an_earlier_valid_member(tmp_path, monkeypatch, change):
    records = [row("a.o", b"first"), row("b.o", b"second")]
    write(tmp_path, "a.o", b"first")
    target = write(tmp_path, "b.o", b"second")
    if change == "bytes":
        target.write_bytes(b"xxxxxx")
    elif change == "size":
        target.write_bytes(b"second plus extra")
    elif change == "execute-bit":
        target.chmod(0o700)
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        batch = bank.begin(records)
        with pytest.raises(REFUSALS) as caught:
            for record in records[:1] if change == "missing-capture" else records:
                with output_fd(tmp_path, record) as descriptor:
                    batch.capture(descriptor, record)
            batch.commit()
        batch.abort(caught.value)
        for record in records:
            with pytest.raises(REFUSALS):
                bank.read_record(record)
        assert_closed(frames)
    finally:
        bank.close()


@LINUX
def test_multiple_command_frames_publish_only_once_and_preserve_prior_records(tmp_path):
    first = row("first.o", b"first")
    second = row("second.o", b"second")
    write(tmp_path, first["path"], b"first")
    write(tmp_path, second["path"], b"second")
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        first_batch = capture(bank, tmp_path, [first])
        with pytest.raises(REFUSALS):
            first_batch.commit()
        with pytest.raises(REFUSALS):
            bank.begin([first])
        capture(bank, tmp_path, [second])
        destination = tmp_path / "complete-prior"
        bank.snapshot(destination, [first, second])
        assert (destination / "first.o").read_bytes() == b"first"
        assert (destination / "second.o").read_bytes() == b"second"
    finally:
        bank.close()


@LINUX
@pytest.mark.parametrize("change", ["missing", "extra", "bytes-pin", "size", "mode", "path", "duplicate"])
def test_snapshot_requires_the_exact_original_published_record_set(tmp_path, change):
    record = row("object.o", b"retained")
    write(tmp_path, record["path"], b"retained")
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        capture(bank, tmp_path, [record])
        requested = [dict(record)]
        if change == "missing":
            requested = []
        elif change == "extra":
            requested.append(row("foreign.o", b"foreign"))
        elif change == "duplicate":
            requested.append(dict(record))
        else:
            field, value = {"bytes-pin": ("sha256", "0" * 64), "size": ("size", record["size"] + 1),
                            "mode": ("executable", True), "path": ("path", "other.o")}[change]
            requested[0][field] = value
        destination = tmp_path / "refused-prior"
        with pytest.raises(REFUSALS):
            bank.snapshot(destination, requested)
        assert not destination.exists()
        assert bank.read_record(record) == b"retained"
    finally:
        bank.close()


@LINUX
def test_snapshot_is_create_only_and_never_reuses_a_previous_destination(tmp_path):
    record = row("object.o", b"retained")
    write(tmp_path, record["path"], b"retained")
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        capture(bank, tmp_path, [record])
        destination = tmp_path / "prior"
        destination.mkdir()
        sentinel = write(destination, "existing", b"keep original partial")
        with pytest.raises(REFUSALS):
            bank.snapshot(destination, [record])
        assert sentinel.read_bytes() == b"keep original partial"
        assert not (destination / record["path"]).exists()
    finally:
        bank.close()


@LINUX
def test_failed_snapshot_retains_the_original_partial_destination_without_replacing_the_bank(
        tmp_path, monkeypatch):
    record = row("object.o", b"original retained bytes")
    write(tmp_path, record["path"], b"original retained bytes")
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        capture(bank, tmp_path, [record])
        real_write, real_pwrite = os.write, os.pwrite
        injected = OSError(errno.ENOSPC, "original destination full")

        def partial_write(descriptor, block):
            real_write(descriptor, block[:3])
            raise injected

        def partial_pwrite(descriptor, block, offset):
            real_pwrite(descriptor, block[:3], offset)
            raise injected

        monkeypatch.setattr(sealed.os, "write", partial_write)
        monkeypatch.setattr(sealed.os, "pwrite", partial_pwrite)
        destination = tmp_path / "partial-prior"
        with pytest.raises(OSError) as caught:
            bank.snapshot(destination, [record])
        assert caught.value is injected
        assert (destination / record["path"]).read_bytes() == b"ori"
        assert bank.read_record(record) == b"original retained bytes"
        with pytest.raises(REFUSALS):
            bank.snapshot(destination, [record])
        assert (destination / record["path"]).read_bytes() == b"ori"
    finally:
        bank.close()


@LINUX
@pytest.mark.parametrize("change", ["bool-size", "nonbool-mode", "extra-field", "dotdot",
                                    "duplicate", "path-overlap", "negative-size"])
def test_invalid_group_records_refuse_before_frame_allocation(tmp_path, monkeypatch, change):
    record = row("object.o", b"retained")
    records = [dict(record)]
    if change == "duplicate":
        records.append(dict(record))
    elif change == "path-overlap":
        records.extend([row("object.o-middle", b"interleaved"),
                        row("object.o/nested", b"foreign")])
    else:
        field, value = {"bool-size": ("size", True), "nonbool-mode": ("executable", 1),
                        "extra-field": ("accepted", True), "dotdot": ("path", "../foreign"),
                        "negative-size": ("size", -1)}[change]
        records[0][field] = value
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        with pytest.raises(REFUSALS):
            bank.begin(records)
        assert frames == []
    finally:
        bank.close()


@LINUX
def test_nonadjacent_parent_conflict_with_an_earlier_command_refuses_before_allocation(
        tmp_path, monkeypatch):
    first = row("a", b"retained")
    write(tmp_path, first["path"], b"retained")
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        capture(bank, tmp_path, [first])
        with pytest.raises(REFUSALS):
            bank.begin([row("a-b", b"middle"), row("a/c", b"conflicting")])
        assert len(frames) == 1
        assert bank.read_record(first) == b"retained"
    finally:
        bank.close()


@LINUX
def test_read_record_cannot_raise_its_caller_bound_or_relabel_an_original_pin(tmp_path):
    record = row("object.o", b"retained")
    write(tmp_path, record["path"], b"retained")
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        capture(bank, tmp_path, [record])
        with pytest.raises(REFUSALS):
            bank.read_record(record, maximum=record["size"] - 1)
        for changed in ({**record, "executable": True}, {**record, "path": "foreign.o"}):
            with pytest.raises(REFUSALS):
                bank.read_record(changed)
        assert bank.read_record(record, maximum=record["size"]) == b"retained"
    finally:
        bank.close()


@LINUX
@pytest.mark.parametrize("limit", ["bytes", "frames"])
def test_attempt_resource_bounds_refuse_before_new_frame_allocation(tmp_path, monkeypatch, limit):
    first, second = row("a.o", b"first"), row("b.o", b"second")
    write(tmp_path, first["path"], b"first")
    write(tmp_path, second["path"], b"second")
    options = {"maximum_bytes": first["size"]} if limit == "bytes" else {"maximum_frames": 1}
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None, **options)
    try:
        capture(bank, tmp_path, [first])
        assert len(frames) == 1
        with pytest.raises(REFUSALS):
            bank.begin([second])
        assert len(frames) == 1
        assert bank.read_record(first) == b"first"
    finally:
        bank.close()
    assert_closed(frames)


@LINUX
def test_only_one_pending_batch_can_use_an_attempt_owner(tmp_path):
    first, second = row("a.o", b"first"), row("b.o", b"second")
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        pending = bank.begin([first])
        with pytest.raises(REFUSALS):
            bank.begin([second])
        pending.abort()
        successor = bank.begin([second])
        successor.abort()
    finally:
        bank.close()


@LINUX
def test_empty_group_needs_no_frame_but_only_the_empty_record_set_can_be_staged(tmp_path, monkeypatch):
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None)
    try:
        bank.begin([]).commit()
        destination = tmp_path / "empty-prior"
        bank.snapshot(destination, [])
        assert destination.is_dir() and list(destination.iterdir()) == []
        assert frames == []
    finally:
        bank.close()


@LINUX
@pytest.mark.parametrize("stage", ["capture", "commit", "snapshot", "read-record"])
@pytest.mark.parametrize("fault", [RuntimeError("original deadline"), KeyboardInterrupt("original cancellation")])
def test_original_control_exception_propagates_without_replacement_or_budget_reset(
        tmp_path, monkeypatch, stage, fault):
    record = row("object.o", b"original retained bytes")
    write(tmp_path, record["path"], b"original retained bytes")
    active = [False]

    def checkpoint():
        if active[0]:
            raise fault

    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(checkpoint)
    pending = None
    try:
        if stage in {"capture", "commit"}:
            pending = bank.begin([record])
            with output_fd(tmp_path, record) as descriptor:
                if stage == "commit":
                    pending.capture(descriptor, record)
                active[0] = True
                with pytest.raises(type(fault)) as caught:
                    pending.capture(descriptor, record) if stage == "capture" else pending.commit()
                assert os.fstat(descriptor).st_size == record["size"]
        else:
            capture(bank, tmp_path, [record])
            active[0] = True
            with pytest.raises(type(fault)) as caught:
                if stage == "snapshot":
                    bank.snapshot(tmp_path / "prior", [record])
                else:
                    bank.read_record(record)
        assert caught.value is fault
        if pending is not None:
            pending.abort(fault)
    finally:
        bank.close(fault)
    assert_closed(frames)


@LINUX
@pytest.mark.parametrize("operation", ["memfd", "sealing", "sealed-readback"])
def test_resource_or_seal_failure_never_publishes_and_closes_pending_frame(
        tmp_path, monkeypatch, operation):
    record = row("object.o", b"retained bytes")
    write(tmp_path, record["path"], b"retained bytes")
    frames = tracked_frames(monkeypatch)
    injected = OSError(errno.EMFILE if operation == "memfd" else errno.EIO, "inert failure")
    real_create, real_fcntl, real_pread = sealed.os.memfd_create, fcntl.fcntl, os.pread
    armed = [False]

    def create(*args, **kwargs):
        if armed[0] and operation == "memfd":
            raise injected
        return real_create(*args, **kwargs)

    def control(descriptor, command, *args):
        if armed[0] and operation == "sealing" and command == fcntl.F_ADD_SEALS:
            raise injected
        return real_fcntl(descriptor, command, *args)

    def read(descriptor, maximum, offset):
        if (armed[0] and operation == "sealed-readback" and descriptor in frames
                and real_fcntl(descriptor, fcntl.F_GET_SEALS) & fcntl.F_SEAL_WRITE):
            raise injected
        return real_pread(descriptor, maximum, offset)

    monkeypatch.setattr(sealed.os, "memfd_create", create)
    monkeypatch.setattr(sealed.fcntl, "fcntl", control)
    monkeypatch.setattr(sealed.os, "pread", read)
    bank = sealed._SealedPriorBank(lambda: None)
    armed[0] = True
    try:
        with pytest.raises(OSError) as caught:
            capture(bank, tmp_path, [record])
        assert caught.value is injected
        with pytest.raises(REFUSALS):
            bank.read_record(record)
        assert_closed(frames)
    finally:
        bank.close()


@LINUX
@pytest.mark.parametrize("replacement", ["ordinary", "same-bytes-sealed"])
def test_foreign_numeric_fd_reuse_is_refused_without_closing_the_foreign_object(
        tmp_path, monkeypatch, replacement):
    record = row("object.o", b"retained")
    write(tmp_path, record["path"], b"retained")
    real_create = os.memfd_create
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None)
    foreign = original = -1
    try:
        capture(bank, tmp_path, [record])
        original = frames[0]
        raw = os.pread(original, os.fstat(original).st_size, 0)
        if replacement == "ordinary":
            foreign = os.open(tmp_path / "foreign", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        else:
            foreign = real_create("inert-foreign", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        os.write(foreign, raw)
        if replacement == "same-bytes-sealed":
            fcntl.fcntl(foreign, fcntl.F_ADD_SEALS, sum(getattr(fcntl, name) for name in SEAL_NAMES))
        os.dup2(foreign, original, inheritable=False)
        with pytest.raises(REFUSALS):
            bank.read_record(record)
        with pytest.raises(ValueError) as caught:
            bank.close()
        assert getattr(caught.value, "code", None) == "podman_sealed_prior_cleanup_unknown"
        assert os.fstat(original).st_ino == os.fstat(foreign).st_ino
        assert os.pread(original, len(raw), 0) == raw
        bank.close()
    finally:
        for descriptor in (original, foreign):
            if descriptor >= 0:
                os.close(descriptor)


@LINUX
@pytest.mark.parametrize("primary", [False, True])
def test_uncertain_close_preserves_primary_and_attempts_each_original_frame_once(
        tmp_path, monkeypatch, primary):
    records = [row("a.o", b"first"), row("b.o", b"second")]
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None)
    for record, raw in zip(records, (b"first", b"second"), strict=True):
        write(tmp_path, record["path"], raw)
        capture(bank, tmp_path, [record])
    real_close, attempts = os.close, []

    def close(descriptor):
        if descriptor in frames:
            attempts.append(descriptor)
        real_close(descriptor)
        if descriptor == frames[-1]:
            raise OSError(errno.EIO, "original close result unavailable")

    monkeypatch.setattr(sealed.os, "close", close)
    fault = KeyboardInterrupt("original cancellation") if primary else None
    if primary:
        bank.close(fault)
        assert "podman_sealed_prior_cleanup_unknown" in fault.__notes__
    else:
        with pytest.raises(ValueError) as caught:
            bank.close()
        assert getattr(caught.value, "code", None) == "podman_sealed_prior_cleanup_unknown"
    assert sorted(attempts) == sorted(frames)
    assert_closed(frames)
    bank.close()
    assert len(attempts) == len(frames)


@LINUX
@pytest.mark.parametrize("control", [KeyboardInterrupt("original close cancellation"), SystemExit(77)])
def test_cleanup_without_primary_preserves_first_control_and_releases_every_owner(
        tmp_path, monkeypatch, control):
    records = [row("a.o", b"first"), row("b.o", b"second")]
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None)
    for record, raw in zip(records, (b"first", b"second"), strict=True):
        write(tmp_path, record["path"], raw)
        capture(bank, tmp_path, [record])
    real_close, attempts = os.close, []

    def close(descriptor):
        real_close(descriptor)
        if descriptor in frames:
            attempts.append(descriptor)
            if descriptor == frames[0]:
                raise control
            raise GeneratorExit("later control must not replace the first")

    monkeypatch.setattr(sealed.os, "close", close)
    with pytest.raises(type(control)) as caught:
        bank.close()
    assert caught.value is control
    assert "podman_sealed_prior_cleanup_unknown" in control.__notes__
    assert sorted(attempts) == sorted(frames)
    assert_closed(frames)
    bank.close()
    assert len(attempts) == len(frames)


@LINUX
def test_cleanup_control_does_not_replace_an_existing_primary(tmp_path, monkeypatch):
    records = [row("a.o", b"first"), row("b.o", b"second")]
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None)
    for record, raw in zip(records, (b"first", b"second"), strict=True):
        write(tmp_path, record["path"], raw)
        capture(bank, tmp_path, [record])
    real_close, attempts = os.close, []
    control = KeyboardInterrupt("cleanup cancellation")
    primary = RuntimeError("original attempt failure")

    def close(descriptor):
        real_close(descriptor)
        if descriptor in frames:
            attempts.append(descriptor)
            if descriptor == frames[0]:
                raise control

    monkeypatch.setattr(sealed.os, "close", close)
    with pytest.raises(RuntimeError) as caught:
        try:
            raise primary
        finally:
            bank.close(primary)
    assert caught.value is primary
    assert "podman_sealed_prior_cleanup_unknown" in primary.__notes__
    assert sorted(attempts) == sorted(frames)
    assert_closed(frames)
    bank.close()
    assert len(attempts) == len(frames)


@LINUX
def test_closed_bank_cannot_be_recreated_from_matching_detached_records(tmp_path, monkeypatch):
    record = row("object.o", b"retained")
    write(tmp_path, record["path"], b"retained")
    frames = tracked_frames(monkeypatch)
    bank = sealed._SealedPriorBank(lambda: None)
    capture(bank, tmp_path, [record])
    bank.close()
    assert_closed(frames)
    for call in (lambda: bank.begin([record]), lambda: bank.read_record(dict(record)),
                 lambda: bank.snapshot(tmp_path / "prior", [dict(record)])):
        with pytest.raises(REFUSALS):
            call()
    assert len(frames) == 1


@pytest.mark.parametrize("missing", ["host", "memfd", "pread", "seals"])
def test_unsupported_platform_or_api_refuses_before_frame_or_source_acquisition(monkeypatch, missing):
    def forbidden(*_args, **_kwargs):
        pytest.fail("unsupported mechanism acquired an original output or memfd")

    monkeypatch.setattr(sealed.sys, "platform", "darwin" if missing == "host" else "linux")
    monkeypatch.setattr(sealed.os, "memfd_create", forbidden, raising=False)
    monkeypatch.setattr(sealed.os, "open", forbidden)
    if missing == "memfd":
        monkeypatch.setattr(sealed.os, "memfd_create", None)
    elif missing == "pread":
        monkeypatch.setattr(sealed.os, "pread", None)
    elif missing == "seals":
        monkeypatch.delattr(sealed.fcntl, "F_SEAL_WRITE", raising=False)
    with pytest.raises(REFUSALS):
        bank = sealed._SealedPriorBank(lambda: None)
        try:
            bank.begin([row("object.o", b"retained")])
        finally:
            bank.close()
