"""V4 codec/actual-rights contracts, without installed root/cgroup acceptance."""
from __future__ import annotations

import array
import copy
import errno
import os
import pickle
import signal
import socket
import stat
import struct
import subprocess
import sys
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from lunar_evolution import native_whole_scope as whole
from lunar_evolution import native_whole_scope_successor as successor
from lunar_evolution.native_bootstrap import (
    native_whole_scope_bootstrap_command,
    native_whole_scope_successor_bootstrap_command,
)

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux seqpacket/descriptor primitives")


def _profile():
    prefix = whole._PREFIX.pack(0x3450574C, 4, 19506, 65532, 65532, 2, 2, 4, *([0] * 30), 1, 1)
    identities = b"".join(whole._IDENTITY.pack(11, 101 + i, 21, 0, 0, stat.S_IFDIR | 0o755, 0)
                          for i in range(3)) + bytes(15 * 40)
    namespaces = b"".join(whole._NAMESPACE.pack(7, 100 + i) for i in range(4))
    paths = b"".join(path.encode().ljust(1024, b"\0") for path in
                     ("/srv/lunar-delegation", "/srv/lunar-execution", "/usr")) + bytes(15 * 1024)
    return prefix + identities + namespaces + paths + b"a" * 64 + b"\0" + b"b" * 64 + b"\0"


@contextmanager
def _internal_session():
    # Internal tokens only project the installed acquisition for mechanism
    # fixtures. This does not establish root-owned installation or cgroups.
    owner = whole.NativeWholeScopeOwner(whole._TOKEN)
    owner._profile = successor._parse_profile(_profile())
    owner._profile_sha256 = "e" * 64
    owner._deadline = time.monotonic_ns() + 5_000_000_000
    owner._binding = owner._core(launch="1" * 64, intent="2" * 64, target="3" * 64,
                                 deadline_ns=owner._deadline)
    owner._scope = whole._IDENTITY.pack(31, 41, 51, 0, 0, stat.S_IFDIR | 0o700, 0)
    owner._target_pid = 123
    session = successor._SuccessorSession(successor._SESSION_TOKEN, owner)
    owner._successor_session = session
    try:
        yield owner, session
    finally:
        owner.close()


def _registration(owner):
    pubs = b"".join(whole._PUBLICATION.pack(71, 81 + i, 12, 15, 16, b"f" * 64 + b"\0") for i in range(3))
    return successor.context(owner._binding, owner._scope, owner._target_pid, pubs, 79, 1)


def _change_context(raw, operation, sequence, count=0):
    return whole._HEADER.pack(successor.MAGIC, 4, operation, sequence, count, 0) + raw[24:]


def _commit(owner, registration, *, normal=True):
    now = time.monotonic_ns()
    proposal = (_change_context(registration, 91, 7)
                + struct.pack("<4IQ", 1 if normal else 2, 0 if normal else 5, 10 if normal else 5, 0, now))
    return (_change_context(registration, 98 if normal else 99, 2)
            + struct.pack("<4IQ4I", 1 if normal else 2, 0 if normal else 5, 1,
                          58 if normal else 29, now + 1, 1, 0, 1, 0)
            + proposal)


def _result(owner, registration, *, normal=True):
    commit = _commit(owner, registration, normal=normal)
    observed = struct.unpack_from("<Q", commit, 925 + 16)[0] + 1
    return (_change_context(registration, 101 if normal else 102, 4) + commit
            + struct.pack("<4IQ", 7, 1, 0, 0, observed))


def _patch(raw, offset, value, fmt="<I"):
    value_raw = bytearray(raw)
    struct.pack_into(fmt, value_raw, offset, value)
    return bytes(value_raw)


def test_v4_profile_is_separate_and_never_accepted_by_legacy_parser():
    raw = _profile()
    assert len(raw) == 19506
    assert successor._parse_profile(raw)["groups"] == (2, 4)
    with pytest.raises(whole.NativeWholeScopeError):
        whole._parse_profile(raw)
    with pytest.raises(whole.NativeWholeScopeError):
        successor._parse_profile(_patch(_patch(_patch(raw, 0, 0x3150574C), 4, 1), 156, 0))


@pytest.mark.parametrize("offset,value", [(0, 0), (4, 1), (8, 0), (12, 0), (16, 2**32 - 1),
                                          (20, 33), (24, 0), (28, 2), (32, 1), (152, 0), (156, 0)])
def test_profile_refuses_wrong_abi_or_credential_contract(offset, value):
    with pytest.raises(whole.NativeWholeScopeError):
        successor._parse_profile(_patch(_profile(), offset, value))


def test_full_nested_result_retains_source_and_separate_wait_fields():
    with _internal_session() as (owner, _session):
        registration = successor.validate_registration(_registration(owner))
        for normal in (True, False):
            raw = _result(owner, registration, normal=normal)
            assert len(raw) == successor.RESULT_SIZE == 2863
            parsed = successor.validate_result(raw, registration)
            assert parsed["decision"] == (1 if normal else 2)
            assert parsed["source"] == (1 if normal else 2)
            assert (parsed["s_code"], parsed["s_status"], parsed["g_code"], parsed["g_status"]) == (1, 0, 1, 0)
            assert len(parsed["commit"]) == 1914


@pytest.mark.parametrize("offset,value", [
    (0, 0x3151574C), (4, 3), (8, 10), (12, 3), (16, 1), (20, 1),
    (925 + 8, 99), (925 + 925, 2), (925 + 925 + 4, 1),
    (925 + 925 + 8, 2), (925 + 925 + 12, 59),
    (925 + 925 + 24, 2), (925 + 925 + 28, 9),
    (925 + 965 + 925, 2), (925 + 965 + 925 + 4, 1),
    (2839, 3), (2839 + 4, 2), (2839 + 8, 1), (2839 + 12, 1),
])
def test_result_refuses_legacy_partial_wait_ack_source_or_projection_mutations(offset, value):
    with _internal_session() as (owner, _session):
        registration = _registration(owner)
        with pytest.raises(whole.NativeWholeScopeError):
            successor.validate_result(_patch(_result(owner, registration), offset, value), registration)


@pytest.mark.parametrize("where", ["source", "commit", "result"])
def test_nested_observation_must_remain_within_original_deadline(where):
    with _internal_session() as (owner, _session):
        registration = _registration(owner)
        offset = {"source": 925 + 965 + 925 + 16, "commit": 925 + 925 + 16,
                  "result": 2839 + 16}[where]
        with pytest.raises(whole.NativeWholeScopeError):
            successor.validate_result(_patch(_result(owner, registration), offset, owner._deadline, "<Q"), registration)


@pytest.mark.parametrize("clone", [copy.copy, copy.deepcopy, pickle.dumps])
def test_live_session_cannot_be_copied_or_serialized(clone):
    with _internal_session() as (_owner, session), pytest.raises(whole.NativeWholeScopeError):
        clone(session)


def test_no_public_session_or_implicit_selection_constructor():
    with pytest.raises(whole.NativeWholeScopeError):
        successor._SuccessorSession(object(), object())
    with (pytest.raises(whole.NativeWholeScopeError), whole.hold_fixed_whole_scope_installation(
            expected_profile_sha256="0" * 64, bootstrap=object(), supervisor="unused", lifecycle_profile="v4")):
        pytest.fail("unknown selector granted an installation")


def test_only_explicit_v4_factory_selection_reaches_independent_loader(monkeypatch):
    selected = []
    monkeypatch.setattr(whole.NativeWholeScopeOwner, "_acquire", lambda *_a: selected.append("legacy"))
    monkeypatch.setattr(successor, "_acquire", lambda *_a: selected.append("v4"))
    values = {"expected_profile_sha256": "0" * 64, "bootstrap": object(), "supervisor": "unused"}
    for options in ({}, {"lifecycle_profile": None}, {"lifecycle_profile": successor.PROFILE_NAME}):
        with whole.hold_fixed_whole_scope_installation(**values, **options) as owner:
            assert type(owner) is whole.NativeWholeScopeOwner
    assert selected == ["legacy", "legacy", "v4"]


@pytest.mark.parametrize("active", [True, False])
def test_incoming_cleanup_exhausts_inventory_and_preserves_primary_refusal(monkeypatch, active):
    visited = []

    def close(fd):
        visited.append(fd)
        if fd == 11:
            raise OSError("injected close failure")

    monkeypatch.setattr(successor.os, "close", close)
    if active:
        primary = ValueError("primary refusal")
        with pytest.raises(ValueError) as raised:
            try:
                raise primary
            finally:
                successor._retire_incoming((11, 12, 13))
        assert raised.value is primary
    else:
        with pytest.raises(OSError, match="injected close failure"):
            successor._retire_incoming((11, 12, 13))
    assert visited == [11, 12, 13]


@LINUX
@pytest.mark.parametrize("outcome", ["normal", "abnormal", "signal", "externally-reaped", "cached-status"])
def test_original_b_wait_consumes_real_pidfd_and_refuses_cached_or_lost_wait(outcome):
    if not hasattr(os, "pidfd_open") or not hasattr(os, "P_PIDFD"):
        pytest.skip("actual pidfd wait unavailable")
    code = 78 if outcome == "abnormal" else 0
    script = ("import os,signal; os.kill(os.getpid(),signal.SIGTERM)"
              if outcome == "signal" else f"raise SystemExit({code})")
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               env={"PATH": os.defpath, "LANG": "C"})
    try:
        with _internal_session() as (owner, session):
            owner._bootstrap = session._b = process
            original = owner._own(os.pidfd_open(process.pid, 0))
            session._b_pidfd = owner._own(os.dup(original))
            owner._drop(original)
            if outcome == "externally-reaped":
                waited, status = os.waitpid(process.pid, 0)
                assert waited == process.pid and os.waitstatus_to_exitcode(status) == 0
            elif outcome == "cached-status":
                assert process.wait(timeout=5) == 0
            if outcome in {"externally-reaped", "cached-status"}:
                with pytest.raises(whole.NativeWholeScopeError, match="original_wait_unavailable"):
                    owner.wait_original_bootstrap(timeout=1)
                assert session._b_waited is False
                if outcome == "externally-reaped":
                    assert process.returncode is None
                    # Cleanup bookkeeping cannot turn the rejected lost wait
                    # into the live session's original consuming observation.
                    process.returncode = 0
            else:
                expected = -signal.SIGTERM if outcome == "signal" else code
                assert owner.wait_original_bootstrap(timeout=4) == expected
                assert session._b_waited and process.returncode == expected
                with pytest.raises(ChildProcessError):
                    os.waitid(os.P_PIDFD, session._b_pidfd, os.WEXITED | os.WNOHANG)
                with pytest.raises(whole.NativeWholeScopeError, match="original_wait_unavailable"):
                    owner.wait_original_bootstrap(timeout=1)
    finally:
        if process.returncode is None:
            process.kill()
            process.wait(timeout=5)


@LINUX
def test_original_b_slice_timeout_keeps_original_deadline_and_wait_unconsumed():
    if not hasattr(os, "pidfd_open") or not hasattr(os, "P_PIDFD"):
        pytest.skip("actual pidfd wait unavailable")
    process = subprocess.Popen([sys.executable, "-B", "-c", "import sys; sys.stdin.buffer.read(1)"],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               env={"PATH": os.defpath, "LANG": "C"})
    try:
        with _internal_session() as (owner, session):
            owner._bootstrap = session._b = process
            session._b_pidfd = owner._own(os.pidfd_open(process.pid, 0))
            original_deadline = owner.deadline_ns
            with pytest.raises(subprocess.TimeoutExpired):
                owner.wait_original_bootstrap(timeout=0.001)
            assert owner.deadline_ns == original_deadline
            assert not session._b_waited and process.returncode is None
            assert process.stdin is not None
            process.stdin.close()
            assert owner.wait_original_bootstrap(timeout=4) == 0
            assert owner.deadline_ns == original_deadline
    finally:
        if process.stdin is not None:
            process.stdin.close()
        if process.returncode is None:
            process.kill()
            process.wait(timeout=5)


def test_full_result_cannot_substitute_for_original_b_wait(monkeypatch):
    with _internal_session() as (owner, session):
        owner._released = True
        owner._bootstrap = session._b = SimpleNamespace(returncode=0)
        owner._supervisor = session._q = SimpleNamespace(returncode=0)
        session.registration = _registration(owner)
        monkeypatch.setattr(session, "_receive", lambda *_a: pytest.fail("unconsumed B wait reached result receive"))
        try:
            with pytest.raises(whole.NativeWholeScopeError, match="completion_unknown"):
                session.finish()
        finally:
            owner._supervisor = session._q = None


def test_explicit_bootstrap_mode_preserves_original_argv_bytes():
    values = {"control_fd": 11, "gate_fd": 12, "frame_fd": 13, "controller_lifeline_fd": 14,
              "scope_enrollment_fd": 15, "scope_lifecycle_fd": 16, "profile_fd": 17,
              "deadline_monotonic_ns": 1234567}
    legacy = native_whole_scope_bootstrap_command("/sealed/bootstrap", **values)
    selected = native_whole_scope_successor_bootstrap_command("/sealed/bootstrap", **values)
    assert legacy[1] == "--whole-scope-v1"
    assert selected[1] == "--whole-scope-successor-v4"
    assert len(selected) == 18 and selected[:1] + selected[2:] == legacy[:1] + legacy[2:]


@pytest.mark.parametrize("ready", [True, False])
def test_registration_requires_both_actual_creator_adoption_and_final_ready(monkeypatch, tmp_path, ready):
    from lunar_evolution import native_original_publication

    originals, incoming, operations, events = [], [], [], []
    try:
        for index in range(3):
            path = tmp_path / str(index)
            path.write_bytes(b"original publication fixture")
            originals.append(os.open(path, os.O_RDONLY))
        incoming = [os.dup(originals[0]), os.dup(originals[1])]
        with _internal_session() as (owner, session):
            registration = _registration(owner)
            pins = tuple(("f" * 64, 12, 71, 81 + i, 15, 16) for i in range(3))

            class OriginalPublications:
                def _borrow_for_native_transfer(self):
                    return tuple(originals), pins

            def adopt(_token, scope, rights, raw):
                assert scope is owner and rights == tuple(incoming)
                assert raw == registration[-315:]
                for fd in rights:
                    os.fstat(fd)
                events.append("adopted")

            owner._custody_owner = SimpleNamespace(
                _adopt_creator_descriptions=adopt,
                _check_registration=lambda: events.append("checked"), close=lambda: None)
            owner._controller = object()
            monkeypatch.setattr(owner, "_check_installation", lambda: None)
            monkeypatch.setattr(native_original_publication, "NativeOriginalPublications", OriginalPublications)
            packets = iter([
                (_change_context(registration, 81, 2, 2), tuple(incoming)),
                (_change_context(registration, 83 if ready else 82, 2), ()),
            ])
            monkeypatch.setattr(session, "_receive", lambda *_args: next(packets))

            def sent(_sock, packet, rights=()):
                operations.append(whole._HEADER.unpack_from(packet)[2])
                if operations[-1] == 82:
                    assert "adopted" in events and "checked" in events
                    assert owner._registered is False
                if operations[-1] == 75:
                    assert rights == tuple(originals)

            monkeypatch.setattr(session, "_send", sent)
            if ready:
                session.bind_registration(OriginalPublications())
            else:
                with pytest.raises(whole.NativeWholeScopeError):
                    session.bind_registration(OriginalPublications())
            assert owner._registered is ready
            assert operations == [75, 82]
            for fd in incoming:
                with pytest.raises(OSError):
                    os.fstat(fd)
            incoming = []
    finally:
        for fd in (*incoming, *originals):
            os.close(fd)


class _ObservedSocket:
    def __init__(self, sock):
        self.sock, self.received = sock, ()

    def recvmsg(self, *args):
        result = self.sock.recvmsg(*args)
        descriptors = []
        for level, kind, raw in result[1]:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values = array.array("i")
                values.frombytes(raw)
                descriptors.extend(values)
        self.received = tuple(descriptors)
        return result


@LINUX
@pytest.mark.parametrize("mutation", ["header", "short", "extra_right", "oversize"])
def test_actual_received_rights_are_retired_on_every_frame_refusal(tmp_path, mutation):
    path = tmp_path / "original"
    path.write_bytes(b"real Linux descriptor fixture")
    original = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        with _internal_session() as (owner, session):
            receiver, sender = owner._socket_pair()
            observed = _ObservedSocket(receiver)
            packet = successor.context(owner._binding, owner._scope, owner._target_pid,
                                       b"\0" * 315, 81, 2, 1)
            expected = 1
            if mutation == "header":
                packet = _patch(packet, 0, 0)
            elif mutation == "short":
                packet = packet[:-1]
            elif mutation == "extra_right":
                expected = 0
            else:
                packet += b"x" * 3000
            sender.sendmsg([packet], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [original]))])
            with pytest.raises(whole.NativeWholeScopeError):
                session._receive(observed, 925, expected)
            assert observed.received
            for fd in observed.received:
                with pytest.raises(OSError) as raised:
                    os.fstat(fd)
                assert raised.value.errno == errno.EBADF
            assert os.pread(original, 4, 0) == b"real"
    finally:
        os.close(original)


@LINUX
def test_unknown_ancillary_before_actual_rights_does_not_skip_cleanup(tmp_path):
    path = tmp_path / "original"
    path.write_bytes(b"fixture")
    original = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    delivered = os.dup(original)
    try:
        with _internal_session() as (owner, session):
            packet = successor.context(owner._binding, owner._scope, owner._target_pid,
                                       b"\0" * 315, 81, 2, 1)

            class MalformedBoundary:
                def recvmsg(self, *_args):
                    return packet, [(123, 456, b"unsupported"),
                                    (socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [delivered]).tobytes())], 0, None

            with pytest.raises(whole.NativeWholeScopeError):
                session._receive(MalformedBoundary(), 925, 1)
            with pytest.raises(OSError) as raised:
                os.fstat(delivered)
            assert raised.value.errno == errno.EBADF
            delivered = -1
    finally:
        if delivered >= 0:
            os.close(delivered)
        os.close(original)
