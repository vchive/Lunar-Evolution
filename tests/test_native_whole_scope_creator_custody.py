"""V3 creator delivery with real Linux files and SCM_RIGHTS descriptions.

The shared original fixture projects installation ownership only. These tests
exercise the Python consumer, not R fsync, installed credentials or cgroups.
Malformed ancillary shapes use a synthetic recvmsg boundary because the kernel
does not produce those shapes from a successful ordinary sendmsg call.
"""
from __future__ import annotations

import array
import errno
import json
import os
import socket
import stat
import struct
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from test_native_whole_scope_custody import original as original  # noqa: PLC0414

from lunar_evolution import native_whole_scope as whole
from lunar_evolution import native_whole_scope_custody as custody

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux statx/xattr mechanisms")
V3 = pytest.mark.parametrize("original", [custody.CUSTODY_V3_PROFILE], indirect=True)


@contextmanager
def _created(original, *, started=True):
    owner, child, path = original
    if started:
        assert child._borrow_for_start() == child._directory
    owner._binding = owner._core(launch="1" * 64, intent="2" * 64, target="3" * 64,
                                 deadline_ns=owner._deadline)
    owner._scope = whole._IDENTITY.pack(31, 41, 51, 0, 0, stat.S_IFDIR | 0o700, 0)
    owner._target_pid = 123
    publications = b"".join(
        whole._PUBLICATION.pack(71, 81 + i, 12, 15, 16, b"e" * 64 + b"\0") for i in range(3)
    )
    registration = (whole._HEADER.pack(0x3151574C, 3, 22, 1, 0, 0) + owner._binding
                    + owner._scope + struct.pack("<Q", owner._target_pid) + publications)
    descriptors = []
    try:
        for name, raw in zip(custody._profile_shape(child.profile)[1],
                             (registration, b""), strict=True):
            fd = os.open(path / name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
            descriptors.append(fd)
            assert os.write(fd, raw) == len(raw)
        yield SimpleNamespace(publications=publications, registration=registration,
                              fds=tuple(descriptors))
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _packet(created):
    raw = bytearray(created.registration)
    struct.pack_into("<III", raw, 8, 24, 2, 2)
    return bytes(raw)


def _rights(descriptors):
    return array.array("i", descriptors).tobytes()


def _delivered_fds(ancillary):
    descriptors = []
    width = array.array("i").itemsize
    for level, kind, values in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            rights = array.array("i")
            rights.frombytes(values[:len(values) - len(values) % width])
            descriptors.extend(rights)
    return tuple(descriptors)


class _ObservedSocket:
    def __init__(self, sock):
        self.sock = sock
        self.descriptors = ()
        self.flags = None

    def recvmsg(self, *args):
        packet = self.sock.recvmsg(*args)
        self.descriptors = _delivered_fds(packet[1])
        self.flags = packet[2]
        return packet

    def fileno(self):
        return self.sock.fileno()


def _queue(owner, created, *, descriptors=None, packet=None):
    receiver, sender = owner._socket_pair()
    observed = _ObservedSocket(receiver)
    owner._controller = observed
    descriptors = created.fds if descriptors is None else descriptors
    ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, _rights(descriptors))] if descriptors else []
    packet = _packet(created) if packet is None else packet
    assert sender.sendmsg([packet], ancillary, socket.MSG_NOSIGNAL) == len(packet)
    return observed


def _closed(descriptors):
    for fd in descriptors:
        with pytest.raises(OSError) as raised:
            os.fstat(fd)
        assert raised.value.errno == errno.EBADF


def _terminal(created, *, reason=0, facts=10, observed=None):
    raw = bytearray(created.registration)
    struct.pack_into("<III", raw, 4, 3, 25 if reason == 0 else 26, 2)
    return bytes(raw) + custody._EVENT_FACTS.pack(
        reason, facts, whole.time.monotonic_ns() if observed is None else observed,
    )


@LINUX
@V3
def test_actual_scm_creators_reach_same_original_child_without_changing_shared_offsets(
    original, monkeypatch,
):
    owner, child, _path = original
    with _created(original) as created:
        offsets = tuple(os.lseek(fd, 0, os.SEEK_CUR) for fd in created.fds)
        flags = tuple(whole.fcntl.fcntl(fd, whole.fcntl.F_GETFL) for fd in created.fds)
        assert offsets == (whole._MESSAGE_SIZE, 0)
        observed = _queue(owner, created)
        # Consumption must use pread on the delivered descriptions. A reopened
        # path or a read/lseek can conceal that SCM_RIGHTS shares the writer OFD.
        with monkeypatch.context() as checks:
            for name in ("open", "read", "lseek", "write", "ftruncate"):
                checks.setattr(custody.os, name, lambda *_a, **_k: pytest.fail("creator OFD mutated"))
            original_fcntl = whole.fcntl.fcntl

            def read_only_fcntl(fd, command, *args):
                assert command not in (whole.fcntl.F_SETFL, whole.fcntl.F_SETFD)
                return original_fcntl(fd, command, *args)

            checks.setattr(whole.fcntl, "fcntl", read_only_fcntl)
            assert owner._receive_custody_creators(created.publications) is None
            assert owner.original_custody_owner is child
            child._check_registration()
            assert child.reference.canonical_bytes
        held = child._creators
        assert len(held) == 2 and not set(held) & owner._fds
        assert not set(held) & set(observed.descriptors)
        _closed(observed.descriptors)
        for sender, received in zip(created.fds, held, strict=True):
            assert sender != received
            assert whole._kernel_identity(sender) == whole._kernel_identity(received)
            assert not os.get_inheritable(received)
        # Moving the sender offset changes the receiver offset, which proves
        # these are shared descriptions rather than a same-inode path reopen.
        assert tuple(os.lseek(fd, 0, os.SEEK_CUR) for fd in created.fds) == offsets
        assert tuple(whole.fcntl.fcntl(fd, whole.fcntl.F_GETFL) for fd in created.fds) == flags
        assert os.lseek(created.fds[0], 7, os.SEEK_SET) == 7
        assert os.lseek(held[0], 0, os.SEEK_CUR) == 7
        child._check_registration()
        assert os.lseek(created.fds[0], 0, os.SEEK_CUR) == 7


@LINUX
@V3
def test_v3_path_records_without_creator_adoption_cannot_bind_live_registration(original):
    owner, child, _path = original
    with _created(original) as created:
        with pytest.raises(custody.NativeWholeScopeCustodyError):
            child._bind_registration(created.publications)
        with pytest.raises(custody.NativeWholeScopeCustodyError):
            _ = child.reference
        assert child._creators == ()
        assert owner.original_custody_owner is child


@LINUX
@V3
@pytest.mark.parametrize("reason,facts", [(0, 10), (1, 1), (2, 3), (3, 5), (4, 15)])
def test_v3_delivered_creator_terminal_and_retained_reference_never_recover_ack(original, reason, facts):
    owner, child, _path = original
    with _created(original) as created:
        _queue(owner, created)
        owner._receive_custody_creators(created.publications)
        reference = child.reference
        assert custody.inspect_native_whole_scope_custody(reference)["state"] == "registration_prefix_observed"
        raw = _terminal(created, reason=reason, facts=facts)
        assert os.pwrite(created.fds[1], raw, 0) == 941
        if reason == 0:
            child._check_registration(terminal=True)
        else:
            with pytest.raises(custody.NativeWholeScopeCustodyError):
                child._check_registration(terminal=True)
        report = custody.inspect_native_whole_scope_custody(reference)
        assert report["state"] == ("terminal_record_observed" if reason == 0 else "abnormal_record_observed")
        assert report["recorded_reason"] == custody._REASONS[reason]
        assert report["recorded_stop_attempted"] is bool(facts & 1)
        assert report["recorded_scope_empty"] is bool(facts & 2)
        assert report["recorded_bootstrap_exit"] is bool(facts & 4)
        assert report["recorded_guardian_exact_reaped"] is bool(facts & 8)
        assert report["cleanup_status"] == "unknown"
        assert not any(report[key] for key in (
            "durable_acknowledgement_verified", "native_success", "whole_group_cleanup_verified",
            "original_quiescence_observed", "production_admission", "publication_authority", "online_publication",
        ))
        held = child._creators
        child.close()
        _closed(held)
        assert custody.inspect_native_whole_scope_custody(reference) == report


@LINUX
@V3
@pytest.mark.parametrize("fault", [
    "magic", "version", "operation", "sequence", "count", "reserved", "binding", "scope", "pid",
    "publication", "short", "extra", "truncated",
])
def test_v3_creator_delivery_rejects_frame_and_context_drift_and_closes_all_rights(original, fault):
    owner, child, _path = original
    with _created(original) as created:
        packet = bytearray(_packet(created))
        header_faults = {"magic": (0, 0), "version": (4, 2), "operation": (8, 23),
                         "sequence": (12, 1), "count": (16, 1), "reserved": (20, 1)}
        if fault in header_faults:
            struct.pack_into("<I", packet, *header_faults[fault])
        elif fault in {"binding", "scope", "pid", "publication"}:
            offset = {"binding": whole._HEADER.size + 8,
                      "scope": whole._HEADER.size + whole._BINDING.size,
                      "pid": whole._HEADER.size + whole._BINDING.size + whole._IDENTITY.size,
                      "publication": whole._MESSAGE_SIZE - 65}[fault]
            packet[offset] ^= 1
        elif fault == "short":
            packet.pop()
        else:
            packet.extend(b"x" * (2 if fault == "truncated" else 1))
        observed = _queue(owner, created, packet=bytes(packet))
        with pytest.raises(whole.NativeWholeScopeError):
            owner._receive_custody_creators(created.publications)
        assert len(observed.descriptors) == 2
        _closed(observed.descriptors)
        assert child._creators == ()
        assert not child._reference
        if fault == "truncated":
            assert observed.flags & socket.MSG_TRUNC
        for fd in created.fds:
            os.fstat(fd)


@LINUX
@V3
@pytest.mark.parametrize("fault", ["none", "one", "three", "aliased", "reversed"])
def test_actual_v3_rights_count_order_and_aliases_fail_closed(original, fault):
    owner, child, _path = original
    with _created(original) as created:
        fds = created.fds
        rights = {"none": (), "one": fds[:1], "three": (*fds, fds[0]),
                  "aliased": (fds[0], fds[0]), "reversed": tuple(reversed(fds))}[fault]
        observed = _queue(owner, created, descriptors=rights)
        with pytest.raises(whole.NativeWholeScopeError):
            owner._receive_custody_creators(created.publications)
        assert len(observed.descriptors) == len(rights)
        _closed(observed.descriptors)
        assert child._creators == ()
        for fd in fds:
            os.fstat(fd)


@LINUX
@V3
@pytest.mark.parametrize("fault", [
    "unknown-before-rights", "malformed-before-rights", "partial-rights-before-rights",
    "repeated-rights", "message-truncated", "control-truncated",
])
def test_malformed_ancillary_inventory_includes_later_rights_before_refusal(original, monkeypatch, fault):
    owner, child, _path = original
    with _created(original) as created:
        acquired = tuple(os.dup(fd) for fd in created.fds)
        rights = (socket.SOL_SOCKET, socket.SCM_RIGHTS, _rights(acquired))
        flags = 0
        if fault == "unknown-before-rights":
            ancillary = [(socket.SOL_SOCKET, -1, b"unknown"), rights]
        elif fault == "malformed-before-rights":
            ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, b"x"), rights]
        elif fault == "partial-rights-before-rights":
            ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, _rights(acquired[:1]) + b"x"),
                         (socket.SOL_SOCKET, socket.SCM_RIGHTS, _rights(acquired[1:]))]
        elif fault == "repeated-rights":
            ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, _rights(acquired[:1])),
                         (socket.SOL_SOCKET, socket.SCM_RIGHTS, _rights(acquired[1:]))]
        else:
            ancillary = [rights]
            flags = socket.MSG_TRUNC if fault == "message-truncated" else socket.MSG_CTRUNC
        receiver = SimpleNamespace(recvmsg=lambda *_a: (_packet(created), ancillary, flags, None))
        monkeypatch.setattr(owner, "_controller", receiver, raising=False)
        with pytest.raises(whole.NativeWholeScopeError):
            owner._receive_custody_creators(created.publications)
        _closed(acquired)
        assert child._creators == ()


@LINUX
@V3
@pytest.mark.parametrize("fault", ["token", "scope", "not-started", "closed"])
def test_creator_adoption_requires_same_live_started_original_and_preserves_borrowed_fds(original, fault):
    owner, child, _path = original
    with _created(original, started=fault != "not-started") as created:
        descriptors = created.fds
        if fault == "closed":
            child.close()
        with pytest.raises(whole.NativeWholeScopeError):
            child._adopt_creator_descriptions(
                object() if fault == "token" else whole._TOKEN,
                object() if fault == "scope" else owner,
                descriptors, created.publications,
            )
        # Internal adoption borrows receiver-owned numeric FDs; it owns only
        # its same-OFD duplicates. This direct caller remains responsible here.
        for fd in descriptors:
            os.fstat(fd)
        assert child._creators == ()


@LINUX
@V3
def test_creator_adoption_is_one_shot_and_close_retires_each_description_once(original, monkeypatch):
    owner, child, _path = original
    with _created(original) as created:
        _queue(owner, created)
        owner._receive_custody_creators(created.publications)
        first = child._creators
        second = _queue(owner, created)
        original_close = os.close
        retired = []

        def retire(fd):
            assert fd not in retired
            retired.append(fd)
            return original_close(fd)

        with monkeypatch.context() as checks:
            checks.setattr(custody.os, "close", retire)
            with pytest.raises(whole.NativeWholeScopeError):
                owner._receive_custody_creators(created.publications)
            _closed(second.descriptors)
            child.close()
            child.close()
        _closed(first)
        assert all(retired.count(fd) == 1 for fd in (*first, *second.descriptors))
        assert child._creators == ()


@LINUX
@V3
def test_failed_creator_adoption_cannot_be_retried_after_correcting_bytes(original):
    owner, child, _path = original
    with _created(original) as created:
        os.pwrite(created.fds[0], b"x", 0)
        first = _queue(owner, created)
        with pytest.raises(whole.NativeWholeScopeError):
            owner._receive_custody_creators(created.publications)
        _closed(first.descriptors)
        assert child._creator_delivery_started
        assert child._creators == ()
        os.pwrite(created.fds[0], created.registration, 0)
        second = _queue(owner, created)
        with pytest.raises(whole.NativeWholeScopeError):
            owner._receive_custody_creators(created.publications)
        _closed(second.descriptors)
        assert not child._reference


@LINUX
@V3
@pytest.mark.parametrize("interrupt_after", [1, 2])
def test_partial_creator_adoption_interrupt_retires_all_actual_received_descriptions(
    original, monkeypatch, interrupt_after,
):
    owner, child, _path = original
    with _created(original) as created:
        observed = _queue(owner, created)
        original_pread = os.pread
        original_dup = os.dup
        calls, retained = [], []

        class ConsumerInterrupted(BaseException):
            pass

        def interrupt_read(fd, count, offset):
            calls.append(fd)
            if len(calls) == interrupt_after:
                raise ConsumerInterrupted
            return original_pread(fd, count, offset)

        def duplicate(fd):
            result = original_dup(fd)
            retained.append(result)
            return result

        monkeypatch.setattr(custody.os, "dup", duplicate)
        monkeypatch.setattr(custody.os, "pread", interrupt_read)
        with pytest.raises(ConsumerInterrupted):
            owner._receive_custody_creators(created.publications)
        assert len(calls) == interrupt_after
        assert len(observed.descriptors) == 2
        assert len(retained) == 2
        _closed(observed.descriptors)
        _closed(retained)
        assert child._creators == ()
        assert not child._reference


@LINUX
@V3
@pytest.mark.parametrize("duplicate_failure", [1, 2])
def test_partial_creator_duplicate_failure_has_unambiguous_receiver_and_child_cleanup(
    original, monkeypatch, duplicate_failure,
):
    owner, child, _path = original
    with _created(original) as created:
        observed = _queue(owner, created)
        original_dup = os.dup
        calls, retained = [], []

        def duplicate(fd):
            calls.append(fd)
            if len(calls) == duplicate_failure:
                raise OSError(errno.EMFILE, "fixture duplicate failure")
            result = original_dup(fd)
            retained.append(result)
            return result

        monkeypatch.setattr(custody.os, "dup", duplicate)
        with pytest.raises(OSError) as raised:
            owner._receive_custody_creators(created.publications)
        assert raised.value.errno == errno.EMFILE
        assert len(calls) == duplicate_failure
        assert len(retained) == duplicate_failure - 1
        assert len(observed.descriptors) == 2
        _closed((*observed.descriptors, *retained))
        assert child._creators == ()
        assert not child._reference


@LINUX
@V3
def test_interruption_at_adoption_call_entry_leaves_incoming_rights_owned_by_receiver(original, monkeypatch):
    owner, child, _path = original
    with _created(original) as created:
        observed = _queue(owner, created)

        class ConsumerInterrupted(BaseException):
            pass

        def interrupt_before_adoption(*_args):
            raise ConsumerInterrupted

        monkeypatch.setattr(custody.NativeWholeScopeCustodyOwner, "_adopt_creator_descriptions",
                            interrupt_before_adoption)
        with pytest.raises(ConsumerInterrupted):
            owner._receive_custody_creators(created.publications)
        assert len(observed.descriptors) == 2
        _closed(observed.descriptors)
        assert child._creators == ()


@LINUX
@V3
def test_original_deadline_expiring_after_receive_retires_rights_before_adoption(original, monkeypatch):
    owner, child, _path = original
    with _created(original) as created:
        observed = _queue(owner, created)
        original_recvmsg = observed.recvmsg

        def expire_after_delivery(*args):
            packet = original_recvmsg(*args)
            monkeypatch.setattr(whole.time, "monotonic_ns", lambda: owner.deadline_ns + 1)
            return packet

        observed.recvmsg = expire_after_delivery
        with pytest.raises(whole.NativeWholeScopeError, match="deadline_exceeded"):
            owner._receive_custody_creators(created.publications)
        assert len(observed.descriptors) == 2
        _closed(observed.descriptors)
        assert child._creators == ()
        assert not child._reference


@LINUX
@V3
@pytest.mark.parametrize("fault", [
    "append", "nonblocking", "read-only", "no-cloexec", "mode", "hardlink", "replacement",
    "symlink", "registration-bytes", "registration-size", "terminal-partial", "extra-name", "reserved",
    "access-acl", "empty-terminal-pin", "terminal-write-truncate",
])
def test_v3_live_creator_flags_names_metadata_and_reserved_roles_cannot_drift(original, fault):
    owner, child, path = original
    with _created(original) as created:
        if fault == "terminal-write-truncate":
            # Establish a distinct original mtime without a timing/sleep race.
            os.utime(created.fds[1], ns=(1_000_000_000,) * 2)
        _queue(owner, created)
        owner._receive_custody_creators(created.publications)
        held = child._creators
        record = path / custody._V3_NAMES[0]
        if fault in {"append", "nonblocking"}:
            flags = whole.fcntl.fcntl(created.fds[0], whole.fcntl.F_GETFL)
            whole.fcntl.fcntl(created.fds[0], whole.fcntl.F_SETFL,
                              flags | (os.O_APPEND if fault == "append" else os.O_NONBLOCK))
        elif fault == "read-only":
            replacement = os.open(record, os.O_RDONLY | os.O_CLOEXEC)
            os.close(held[0])
            child._creators = (replacement, held[1])
        elif fault == "no-cloexec":
            os.set_inheritable(held[0], True)
        elif fault == "mode":
            record.chmod(0o640)
        elif fault == "hardlink":
            os.link(record, path.parent / "record-alias")
        elif fault in {"replacement", "symlink"}:
            retained = path.parent / "retained-registration"
            record.rename(retained)
            if fault == "symlink":
                record.symlink_to(retained)
            else:
                record.write_bytes(created.registration)
                record.chmod(0o600)
        elif fault == "registration-bytes":
            os.pwrite(created.fds[0], b"x", 24)
        elif fault == "registration-size":
            os.ftruncate(created.fds[0], whole._MESSAGE_SIZE - 1)
        elif fault == "terminal-partial":
            os.pwrite(created.fds[1], b"partial", 0)
        elif fault == "extra-name":
            (path / "unexpected").write_bytes(b"x")
        elif fault == "access-acl":
            # An explicit named-user ACL with zero mask leaves mode 0600,
            # isolating the ACL refusal from the ordinary mode check.
            acl = struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in (
                (1, 6, 2**32 - 1), (2, 0, 65534), (4, 0, 2**32 - 1),
                (16, 0, 2**32 - 1), (32, 0, 2**32 - 1),
            ))
            os.setxattr(created.fds[0], "system.posix_acl_access", acl, os.XATTR_CREATE)
            assert stat.S_IMODE(os.fstat(created.fds[0]).st_mode) == 0o600
        elif fault == "empty-terminal-pin":
            info = os.fstat(created.fds[1])
            terminal = path / custody._V3_NAMES[1]
            os.utime(terminal, ns=(info.st_mtime_ns + 1_000_000_000,) * 2)
            assert os.fstat(created.fds[1]).st_size == 0
        elif fault == "terminal-write-truncate":
            before = os.fstat(created.fds[1])
            identity = whole._kernel_identity(created.fds[1])
            assert os.write(created.fds[1], b"transient terminal bytes") == 24
            os.ftruncate(created.fds[1], 0)
            after = os.fstat(created.fds[1])
            assert whole._kernel_identity(created.fds[1]) == identity
            assert before.st_size == after.st_size == 0
            assert os.pread(created.fds[1], 1, 0) == b""
            assert custody._file_pin(after) != custody._file_pin(before)
        else:
            owner._own(os.dup(created.fds[0]))
        with pytest.raises((whole.NativeWholeScopeError, OSError)):
            child._check_registration()


@LINUX
@V3
def test_actual_stdin_alias_refuses_creator_adoption_and_retires_both_ownership_regions(
    original, monkeypatch,
):
    owner, child, _path = original
    with _created(original) as created:
        observed = _queue(owner, created)
        original_stdin = os.dup(0)
        original_inheritable = os.get_inheritable(0)
        original_identity = whole._kernel_identity(original_stdin)
        original_dup = os.dup
        retained = []

        def duplicate(fd):
            result = original_dup(fd)
            retained.append(result)
            return result

        try:
            # No input is read, and stdout/stderr are never replaced. Restore
            # the original open description and inheritance even on refusal.
            os.dup2(created.fds[0], 0, inheritable=False)
            assert whole._kernel_identity(0) == whole._kernel_identity(created.fds[0])
            with monkeypatch.context() as checks:
                checks.setattr(custody.os, "dup", duplicate)
                with pytest.raises(custody.NativeWholeScopeCustodyError):
                    owner._receive_custody_creators(created.publications)
            assert len(observed.descriptors) == len(retained) == 2
            _closed((*observed.descriptors, *retained))
            assert child._creators == ()
            assert child._reference is child._records is None
            assert not owner._registered
        finally:
            os.dup2(original_stdin, 0, inheritable=original_inheritable)
            os.close(original_stdin)
        assert whole._kernel_identity(0) == original_identity
        assert os.get_inheritable(0) is original_inheritable


@LINUX
@V3
@pytest.mark.parametrize("expiry_boundary", ["last-chain-check", "reference-json"])
def test_original_deadline_crossing_final_adoption_boundary_clears_reference_and_all_fds(
    original, monkeypatch, expiry_boundary,
):
    owner, child, _path = original
    with _created(original) as created:
        observed = _queue(owner, created)
        deadline = owner.deadline_ns
        original_clock = whole.time.monotonic_ns
        original_chain = custody._check_chain
        original_json = custody._json
        original_dup = os.dup
        clock = {"expired": False}
        chains, json_calls, retained = [], [], []

        def monotonic_ns():
            return deadline + 1 if clock["expired"] else original_clock()

        def check_chain(*args):
            original_chain(*args)
            chains.append(args[0])
            if expiry_boundary == "last-chain-check" and len(chains) == 2:
                clock["expired"] = True

        def reference_json(value):
            raw = original_json(value)
            json_calls.append(value)
            if expiry_boundary == "reference-json":
                clock["expired"] = True
            return raw

        def duplicate(fd):
            result = original_dup(fd)
            retained.append(result)
            return result

        monkeypatch.setattr(whole.time, "monotonic_ns", monotonic_ns)
        monkeypatch.setattr(custody, "_check_chain", check_chain)
        monkeypatch.setattr(custody, "_json", reference_json)
        monkeypatch.setattr(custody.os, "dup", duplicate)
        with pytest.raises(whole.NativeWholeScopeError, match="deadline_exceeded"):
            owner._receive_custody_creators(created.publications)
        assert clock["expired"] and len(chains) == 2
        if expiry_boundary == "reference-json":
            assert len(json_calls) == 1
            assert json_calls[0]["profile"] == custody.CUSTODY_V3_PROFILE
        assert len(observed.descriptors) == len(retained) == 2
        _closed((*observed.descriptors, *retained))
        assert child._reference is child._records is None
        assert child._creators == ()
        assert not owner._registered
        assert owner.deadline_ns == child._deadline == deadline
        assert whole._BINDING.unpack_from(created.registration, whole._HEADER.size)[0] == deadline
        for fd in created.fds:
            os.fstat(fd)


@LINUX
@V3
@pytest.mark.parametrize("fault", ["bytes", "status-flags", "descriptor-flags"])
def test_live_creator_pin_rechecks_detect_mutation_during_pread(original, monkeypatch, fault):
    owner, child, _path = original
    with _created(original) as created:
        _queue(owner, created)
        owner._receive_custody_creators(created.publications)
        original_pread = os.pread
        calls = []

        def mutate_after_read(fd, count, offset):
            raw = original_pread(fd, count, offset)
            calls.append(fd)
            if len(calls) == 1:
                if fault == "bytes":
                    os.pwrite(created.fds[0], b"x", 24)
                elif fault == "status-flags":
                    flags = whole.fcntl.fcntl(fd, whole.fcntl.F_GETFL)
                    whole.fcntl.fcntl(fd, whole.fcntl.F_SETFL, flags | os.O_NONBLOCK)
                else:
                    os.set_inheritable(fd, True)
            return raw

        monkeypatch.setattr(custody.os, "pread", mutate_after_read)
        with pytest.raises(custody.NativeWholeScopeCustodyError):
            child._check_registration()


@LINUX
@V3
@pytest.mark.parametrize("fault", ["registration-flags", "same-bytes-pin", "replaced-name"])
def test_terminal_read_cannot_hide_prior_registration_drift_at_pair_adoption_boundary(
    original, monkeypatch, fault,
):
    owner, child, path = original
    with _created(original) as created:
        if fault == "same-bytes-pin":
            # A real same-byte write must change the original observed mtime;
            # start from a fixed old value instead of depending on clock ticks.
            os.utime(created.fds[0], ns=(1_000_000_000,) * 2)
        observed = _queue(owner, created)
        original_pread, original_dup = os.pread, os.dup
        retained, reads, mutations = [], [], []

        def duplicate(fd):
            result = original_dup(fd)
            retained.append(result)
            return result

        def mutate_registration_during_terminal_read(fd, count, offset):
            raw = original_pread(fd, count, offset)
            reads.append(fd)
            if len(reads) == 2:
                assert len(retained) == 2 and fd == retained[1]
                assert reads[0] == retained[0] and raw == b""
                registration_fd = created.fds[0]
                before = custody._file_pin(os.fstat(registration_fd))
                if fault == "registration-flags":
                    flags = whole.fcntl.fcntl(registration_fd, whole.fcntl.F_GETFL)
                    whole.fcntl.fcntl(registration_fd, whole.fcntl.F_SETFL, flags | os.O_APPEND)
                    assert whole.fcntl.fcntl(retained[0], whole.fcntl.F_GETFL) == flags | os.O_APPEND
                elif fault == "same-bytes-pin":
                    assert os.pwrite(registration_fd, created.registration, 0) == whole._MESSAGE_SIZE
                    assert original_pread(registration_fd, whole._MESSAGE_SIZE + 1, 0) == created.registration
                    assert custody._file_pin(os.fstat(registration_fd)) != before
                else:
                    name = path / custody._V3_NAMES[0]
                    name.rename(path.parent / "retained-pair-registration")
                    replacement = os.open(
                        name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                        0o600,
                    )
                    try:
                        assert os.write(replacement, created.registration) == whole._MESSAGE_SIZE
                        assert os.fstat(replacement).st_ino != os.fstat(registration_fd).st_ino
                    finally:
                        os.close(replacement)
                mutations.append(fault)
            return raw

        with monkeypatch.context() as checks:
            checks.setattr(custody.os, "dup", duplicate)
            checks.setattr(custody.os, "pread", mutate_registration_during_terminal_read)
            with pytest.raises(custody.NativeWholeScopeCustodyError, match="record_changed"):
                owner._receive_custody_creators(created.publications)
        assert mutations == [fault]
        assert reads == retained and len(retained) == len(observed.descriptors) == 2
        _closed((*observed.descriptors, *retained))
        assert child._creator_delivery_started
        assert child._creators == ()
        assert child._reference is child._records is None
        assert not owner._registered
        for fd in created.fds:
            os.fstat(fd)


@LINUX
@V3
def test_expired_v3_live_owner_keeps_only_original_diagnostic_reference(original, monkeypatch):
    owner, child, _path = original
    with _created(original) as created:
        _queue(owner, created)
        owner._receive_custody_creators(created.publications)
        reference = child.reference
        monkeypatch.setattr(whole.time, "monotonic_ns", lambda: owner.deadline_ns + 1)
        assert child.reference is reference
        with pytest.raises(whole.NativeWholeScopeError, match="deadline_exceeded"):
            child._check_registration()
        report = custody.inspect_native_whole_scope_custody(reference)
        assert report["state"] == "registration_prefix_observed"
        assert report["cleanup_status"] == "unknown"
        assert not report["durable_acknowledgement_verified"]
        assert not report["whole_group_cleanup_verified"]


@LINUX
@pytest.mark.parametrize("original", [custody.CUSTODY_PROFILE, custody.CUSTODY_V2_PROFILE], indirect=True)
def test_v1_and_v2_children_refuse_v3_delivery_without_consuming_borrowed_descriptions(original):
    owner, child, _path = original
    with _created(original) as created:
        descriptors = created.fds
        with pytest.raises(whole.NativeWholeScopeError):
            child._adopt_creator_descriptions(whole._TOKEN, owner, descriptors, created.publications)
        for fd in descriptors:
            os.fstat(fd)
        with pytest.raises(whole.NativeWholeScopeError):
            owner._receive_custody_creators(created.publications)
        with pytest.raises(custody.NativeWholeScopeCustodyError):
            child._bind_registration(created.publications)
        assert child._creators == ()


@LINUX
@V3
@pytest.mark.parametrize("profile", [custody.CUSTODY_PROFILE, custody.CUSTODY_V2_PROFILE])
def test_legacy_reference_profiles_refuse_v3_registration_bytes(original, profile):
    owner, child, _path = original
    with _created(original) as created:
        _queue(owner, created)
        owner._receive_custody_creators(created.publications)
        value = json.loads(child.reference.canonical_bytes)
        value["profile"] = profile
        value["path"] = value["path"].rsplit("/", 1)[0] + "/" + custody._profile_shape(profile)[0]
        with pytest.raises(custody.NativeWholeScopeCustodyError):
            custody._parse_reference(custody.NativeWholeScopeCustodyReference(custody._json(value)))
        for reason in (0, 1):
            with pytest.raises(custody.NativeWholeScopeCustodyError):
                custody._terminal_observation(
                    created.registration, _terminal(created, reason=reason, facts=10 if not reason else 1),
                    profile,
                )
