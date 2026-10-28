"""Owner/packet failure boundaries, without installed root-profile acceptance.

The synthetic profile and private-token fixtures exercise internal contracts.
Only the Linux-marked memfd/socket tests use actual kernel primitives; none
establish cgroup emptiness, credential separation, or production authority.
"""
from __future__ import annotations

import array
import copy
import hashlib
import os
import pickle
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, suppress
from types import SimpleNamespace

import pytest

from lunar_evolution import native_whole_scope as whole

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux descriptor primitives")


def _profile_bytes():
    groups = (2, 4) + (0,) * 30
    prefix = struct.pack("<6I32I2I", 0x3150574C, 1, 19506, 65532, 65532, 2, *groups, 1, 0)
    identities = b"".join(struct.pack("<QQQIIII", 11, 101 + i, 21, 0, 0, stat.S_IFDIR | 0o755, 0)
                          for i in range(3)) + bytes(15 * 40)
    namespaces = b"".join(struct.pack("<QQ", 7, 100 + i) for i in range(4))
    paths = b"".join(path.encode().ljust(1024, b"\0") for path in
                     ("/srv/lunar-delegation", "/srv/lunar-execution", "/usr")) + bytes(15 * 1024)
    return prefix + identities + namespaces + paths + b"a" * 64 + b"\0" + b"b" * 64 + b"\0"


@contextmanager
def _internal_owner():
    # This token fixture is explicitly not an installed privileged acquisition.
    owner = whole.NativeWholeScopeOwner(whole._TOKEN)
    try:
        yield owner
    finally:
        owner.close()


def _bound(owner):
    owner._profile = whole._parse_profile(_profile_bytes())
    owner._profile_sha256 = hashlib.sha256(_profile_bytes()).hexdigest()
    owner._deadline = time.monotonic_ns() + 5_000_000_000
    owner._binding = owner._core(launch="1" * 64, intent="2" * 64, target="3" * 64,
                                 deadline_ns=owner._deadline)
    owner._scope = struct.pack("<QQQIIII", 31, 41, 51, 0, 0, stat.S_IFDIR | 0o700, 0)
    owner._target_pid = 123


def _packet(owner, *, operation=4, sequence=1, count=0, initial=False):
    scope = owner._scope
    pid = owner._target_pid
    if initial:
        scope = struct.pack("<QQQIIII", 61, 71, 81, 0, 0, stat.S_IFDIR | 0o700, 0)
        pid = 234
    return (struct.pack("<6I", 0x3151574C, 1, operation, sequence, count, 0)
            + owner._binding + scope + struct.pack("<Q", pid) + bytes(3 * 105))


def _patch_u32(raw, offset, value):
    result = bytearray(raw)
    struct.pack_into("<I", result, offset, value)
    return bytes(result)


def test_packed_profile_and_message_sizes_match_explicit_abi():
    assert len(_profile_bytes()) == whole._PROFILE_SIZE == 19506
    assert (whole._PREFIX.size, whole._IDENTITY.size, whole._NAMESPACE.size,
            whole._BINDING.size, whole._HEADER.size, whole._PUBLICATION.size) == (160, 40, 16, 538, 24, 105)
    with _internal_owner() as owner:
        _bound(owner)
        assert len(_packet(owner)) == whole._MESSAGE_SIZE == 925


def test_internal_profile_parses_exact_fixed_credential_and_original_pins():
    profile = whole._parse_profile(_profile_bytes())
    assert (profile["uid"], profile["gid"], profile["groups"]) == (65532, 65532, (2, 4))
    assert profile["paths"] == ("/srv/lunar-delegation", "/srv/lunar-execution", "/usr")
    assert profile["namespaces"] == ((7, 100), (7, 101), (7, 102), (7, 103))
    assert (profile["bootstrap_sha256"], profile["supervisor_sha256"]) == ("a" * 64, "b" * 64)


@pytest.mark.parametrize("offset,value", [
    (0, 0), (4, 2), (8, 0), (12, 0), (16, 0), (20, 33),
    (24, 0), (28, 2), (32, 9), (152, 0), (152, 17), (156, 1),
    (160 + 24, 1), (160 + 32, stat.S_IFDIR | 0o777), (160 + 36, 1),
    (160 + 3 * 40, 1),
])
def test_profile_rejects_noncanonical_or_privileged_identity_fields(offset, value):
    with pytest.raises(whole.NativeWholeScopeError, match="profile_invalid"):
        whole._parse_profile(_patch_u32(_profile_bytes(), offset, value))


@pytest.mark.parametrize("raw", [b"", bytes(19505), bytes(19507), bytearray(_profile_bytes())])
def test_profile_requires_exact_immutable_bytes(raw):
    with pytest.raises(whole.NativeWholeScopeError, match="profile_invalid"):
        whole._parse_profile(raw)


@pytest.mark.parametrize("path", ["relative", "/", "/a//b", "/a/../b", "/a/./b", "/a/", "/a\0b"])
def test_profile_refuses_noncanonical_original_names(path):
    raw = bytearray(_profile_bytes())
    raw[944:1968] = path.encode().ljust(1024, b"\0")
    with pytest.raises(whole.NativeWholeScopeError, match="profile_invalid"):
        whole._parse_profile(bytes(raw))


@pytest.mark.parametrize("path", ["/srv/lunar-execution", "/srv/lunar-delegation/subdir", "/etc"])
def test_readonly_root_cannot_cover_private_execution_or_fixed_profile(path):
    raw = bytearray(_profile_bytes())
    raw[944 + 2048:944 + 3072] = path.encode().ljust(1024, b"\0")
    with pytest.raises(whole.NativeWholeScopeError, match="profile_invalid"):
        whole._parse_profile(bytes(raw))


@pytest.mark.parametrize("clone", [copy.copy, copy.deepcopy, pickle.dumps])
def test_live_owner_cannot_be_copied_or_serialized(clone):
    with _internal_owner() as owner, pytest.raises(whole.NativeWholeScopeError, match="owner_invalid"):
        clone(owner)


def test_caller_cannot_construct_owner_from_a_token_or_descriptor_record():
    with pytest.raises(whole.NativeWholeScopeError):
        whole.NativeWholeScopeOwner(object())


def test_unsupported_acquisition_refuses_before_opening_any_installation(monkeypatch):
    monkeypatch.setattr(whole.sys, "platform", "darwin")
    monkeypatch.setattr(whole.os, "open", lambda *_a, **_k: pytest.fail("installation must not be opened"))
    with (
        pytest.raises(whole.NativeWholeScopeError, match="installation_unavailable"),
        whole.hold_fixed_whole_scope_installation(
            expected_profile_sha256="0" * 64, bootstrap=object(), supervisor="/not-used"),
    ):
        pytest.fail("unsupported acquisition yielded authority")


@pytest.mark.parametrize("uids,gids", [
    ((1, 0, 0), (0, 0, 0)), ((0, 1, 0), (0, 0, 0)), ((0, 0, 1), (0, 0, 0)),
    ((0, 0, 0), (1, 0, 0)), ((0, 0, 0), (0, 1, 0)), ((0, 0, 0), (0, 0, 1)),
])
def test_every_original_root_credential_slot_is_required_before_acquisition(monkeypatch, uids, gids):
    monkeypatch.setattr(whole.sys, "platform", "linux")
    monkeypatch.setattr(whole.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(whole.os, "getresuid", lambda: uids, raising=False)
    monkeypatch.setattr(whole.os, "getresgid", lambda: gids, raising=False)
    monkeypatch.setattr(whole.os, "open", lambda *_a, **_k: pytest.fail("unprivileged installation acquisition"))
    with (
        pytest.raises(whole.NativeWholeScopeError, match="installation_unavailable"),
        whole.hold_fixed_whole_scope_installation(
            expected_profile_sha256="0" * 64, bootstrap=object(), supervisor="/not-used"),
    ):
        pytest.fail("partial root identity yielded authority")


def _virtual_named_root(tmp_path, monkeypatch):
    """Real opened names/inodes under a synthetic root; no root-policy proof."""
    root = tmp_path / "synthetic-root"
    root.mkdir(mode=0o755)
    (root / "safe").mkdir(mode=0o755)
    (root / "safe" / "source").write_bytes(b"original-installed-fixture")
    original_open, original_fstat, original_stat = os.open, os.fstat, os.stat
    opened = []

    def fixture_stat(info):
        # Only root ownership is synthetic; inode/mount/name/mode stay real.
        return SimpleNamespace(**{name: (0 if name == "st_uid" else getattr(info, name)) for name in
            ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")})

    def fixture_open(path, flags, *args, **kwargs):
        descriptor = original_open(root if path == "/" else path, flags, *args, **kwargs)
        opened.append((path, flags, descriptor))
        return descriptor

    monkeypatch.setattr(whole.os, "open", fixture_open)
    monkeypatch.setattr(whole.os, "fstat", lambda fd: fixture_stat(original_fstat(fd)))
    monkeypatch.setattr(whole.os, "stat", lambda *a, **k: fixture_stat(original_stat(*a, **k)))
    monkeypatch.setattr(whole, "_mount_id", lambda _fd, _name=b"": 31)
    monkeypatch.setattr(whole.os, "getresuid", lambda: (0, 0, 0), raising=False)
    monkeypatch.setattr(whole.os, "getresgid", lambda: (0, 0, 0), raising=False)
    return root, opened


def test_internal_named_chain_holds_original_components_without_following_names(tmp_path, monkeypatch):
    _root, opened = _virtual_named_root(tmp_path, monkeypatch)
    with _internal_owner() as owner:
        descriptor = owner._open_chain("/safe/source", file=True)
        assert os.pread(descriptor, 100, 0) == b"original-installed-fixture"
        assert len(owner._named) == len(owner._fds) == 3
        assert [entry[2] for entry in owner._named] == ["", "safe", "source"]
        assert all(flags & os.O_NOFOLLOW for path, flags, _fd in opened if path != "/")
        assert all(flags & os.O_CLOEXEC for _path, flags, _fd in opened)
        # Type inspection must not first block on a mistakenly installed FIFO.
        assert opened[-1][1] & os.O_NONBLOCK
    for _path, _flags, descriptor in opened:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.parametrize("changed", ["source", "ancestor"])
def test_same_bytes_replacement_name_never_matches_held_original_chain(tmp_path, monkeypatch, changed):
    root, _opened = _virtual_named_root(tmp_path, monkeypatch)
    with _internal_owner() as owner:
        owner._open_chain("/safe/source", file=True)
        owner._profile = {}  # Only the earlier original-name gate is reached.
        if changed == "source":
            (root / "safe" / "source").rename(root / "safe" / "old")
            (root / "safe" / "source").write_bytes(b"original-installed-fixture")
        else:
            (root / "safe").rename(root / "old-safe")
            (root / "safe").mkdir(mode=0o755)
            (root / "safe" / "source").write_bytes(b"original-installed-fixture")
        with pytest.raises(whole.NativeWholeScopeError, match="original_changed"):
            owner._check_installation()


def test_internal_named_chain_refuses_symlink_without_opening_its_target(tmp_path, monkeypatch):
    root, _opened = _virtual_named_root(tmp_path, monkeypatch)
    (root / "safe" / "source").unlink()
    (root / "safe" / "source").symlink_to("/dev/null")
    with _internal_owner() as owner, pytest.raises(OSError):
        owner._open_chain("/safe/source", file=True)


@pytest.mark.parametrize("path", ["/" + "/".join("a" for _ in range(64)), "/" + "a" * 256])
def test_original_paths_fit_native_component_and_name_bounds(path):
    with pytest.raises(whole.NativeWholeScopeError, match="profile_invalid"):
        whole._text(path.encode() + b"\0")


@LINUX
def test_actual_multiple_os_threads_refuse_original_start_even_if_python_registry_reports_one(monkeypatch):
    from lunar_evolution.producer_bootstrap import TrustedBootstrapLaunch
    from lunar_evolution.producer_launcher import ProducerLaunchIntent

    ready, stop = threading.Event(), threading.Event()

    def inert_thread():
        ready.set()
        stop.wait(timeout=5)

    thread = threading.Thread(target=inert_thread)
    thread.start()
    try:
        assert ready.wait(timeout=2)
        assert len(os.listdir("/proc/self/task")) > 1
        # No process/target is spawned. Only exact-type preflight inputs exist.
        process = object.__new__(subprocess.Popen)
        process._child_created = False
        process.returncode = None
        launch = object.__new__(TrustedBootstrapLaunch)
        intent = object.__new__(ProducerLaunchIntent)
        monkeypatch.setattr(whole.threading, "active_count", lambda: 1)
        monkeypatch.setattr(whole.signal, "getsignal", lambda _signal: whole.signal.SIG_DFL)
        with _internal_owner() as owner:
            owner._channels_prepared = True
            monkeypatch.setattr(owner, "_check_installation", lambda: pytest.fail("multiple tasks reached installation gate"))
            with pytest.raises(whole.NativeWholeScopeError, match="original_wait_unavailable"):
                owner.start_original(process=process, launch=launch, intent=intent,
                    controller_lifeline_fd=-1, deadline_ns=1)
            assert owner._supervisor is None
    finally:
        stop.set()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_readonly_grant_requests_recheck_actual_held_fd_identity_before_each_export(tmp_path, monkeypatch):
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    with _internal_owner() as owner:
        descriptor = owner._own(os.open(readonly, os.O_RDONLY | os.O_DIRECTORY))
        info = os.fstat(descriptor)
        original = (info.st_dev, info.st_ino, 31, info.st_uid, info.st_gid, info.st_mode, 0)
        owner._profile = {"paths": ("/private-delegation", "/private-execution", str(readonly)),
                          "identities": ((), (), original)}
        owner._readonly_fds = [descriptor]
        observations = []
        monkeypatch.setattr(owner, "_check_installation", lambda: observations.append("installation"))

        def fresh_identity(fd):
            observations.append(fd)
            current = os.fstat(fd)
            return (current.st_dev, current.st_ino, 31, current.st_uid, current.st_gid, current.st_mode, 0)

        monkeypatch.setattr(whole, "_kernel_identity", fresh_identity)
        first = owner.original_readonly_grant_requests()
        second = owner.original_readonly_grant_requests()
        assert first == second
        assert observations == ["installation", descriptor, "installation", descriptor]
        assert len(first) == 1
        assert first[0].role == "readonly-directory"
        assert first[0].expected_identity.device == info.st_dev
        assert first[0].expected_identity.inode == info.st_ino
        os.fchmod(descriptor, 0o700 if stat.S_IMODE(info.st_mode) != 0o700 else 0o500)
        with pytest.raises(whole.NativeWholeScopeError, match="original_changed"):
            owner.original_readonly_grant_requests()


def test_acquisition_exception_closes_owned_fds_and_preserves_primary(monkeypatch):
    descriptor = os.open(os.devnull, os.O_RDONLY)
    primary = RuntimeError("fixture-acquisition-failed")

    def fail_acquisition(owner, *_a):
        owner._own(descriptor)
        raise primary

    monkeypatch.setattr(whole.NativeWholeScopeOwner, "_acquire", fail_acquisition)
    with (
        pytest.raises(RuntimeError) as caught,
        whole.hold_fixed_whole_scope_installation(
            expected_profile_sha256="0" * 64, bootstrap=object(), supervisor="/not-used"),
    ):
        pytest.fail("failed acquisition yielded authority")
    assert caught.value is primary
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_own_failure_closes_the_incoming_original_fd():
    class RefusingSet(set):
        def add(self, _value):
            raise MemoryError("fixture-ownership-allocation")

    descriptor = os.open(os.devnull, os.O_RDONLY)
    with _internal_owner() as owner:
        owner._fds = RefusingSet()
        with pytest.raises(MemoryError):
            owner._own(descriptor)
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_read_original_regular_file_uses_pread_without_changing_stream_offset(tmp_path):
    source = tmp_path / "original"
    source.write_bytes(b"original-installed-bytes")
    descriptor = os.open(source, os.O_RDONLY)
    with _internal_owner() as owner:
        owner._own(descriptor)
        os.lseek(descriptor, 7, os.SEEK_SET)
        assert owner._read_file(descriptor, 100) == b"original-installed-bytes"
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 7


def test_original_file_with_extra_hardlink_is_not_installation(tmp_path):
    source = tmp_path / "original"
    source.write_bytes(b"immutable")
    os.link(source, tmp_path / "alias")
    with _internal_owner() as owner:
        descriptor = owner._own(os.open(source, os.O_RDONLY))
        with pytest.raises(whole.NativeWholeScopeError, match="installation_unavailable"):
            owner._read_file(descriptor, 100)


@LINUX
def test_actual_memfds_are_sealed_private_and_closed_with_owner():
    import fcntl

    with _internal_owner() as owner:
        profile = owner._seal("lunar-whole-scope-profile", _profile_bytes())
        image = owner._seal("lunar-whole-scope-supervisor", b"inert-fixture-image")
        assert os.pread(profile, 20000, 0) == _profile_bytes()
        assert stat.S_IMODE(os.fstat(profile).st_mode) == 0o600
        assert stat.S_IMODE(os.fstat(image).st_mode) == 0o700
        required = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_WRITE | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW
        assert fcntl.fcntl(profile, fcntl.F_GET_SEALS) & required == required
        for descriptor in (profile, image):
            with pytest.raises(OSError):
                os.write(descriptor, b"mutation")
            with pytest.raises(OSError):
                os.ftruncate(descriptor, 0)
    for descriptor in (profile, image):
        with pytest.raises(OSError):
            os.fstat(descriptor)


@LINUX
def test_actual_seqpacket_send_preserves_exact_packet_and_original_rights():
    with _internal_owner() as owner:
        _bound(owner)
        parent, child = owner._socket_pair()
        descriptor = owner._own(os.open(os.devnull, os.O_RDONLY))
        owner._send(parent, 5, 1, fds=(descriptor,))
        raw, ancillary, flags, _address = child.recvmsg(926, socket.CMSG_SPACE(16), socket.MSG_CMSG_CLOEXEC)
        assert raw == _packet(owner, operation=5, count=1)
        assert not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC)
        assert len(ancillary) == 1
        assert ancillary[0][:2] == (socket.SOL_SOCKET, socket.SCM_RIGHTS)
        received = array.array("i")
        received.frombytes(ancillary[0][2])
        assert len(received) == 1
        try:
            assert not os.get_inheritable(received[0])
            assert os.fstat(received[0]) == os.fstat(descriptor)
        finally:
            os.close(received[0])


@LINUX
def test_actual_seqpacket_receive_adopts_original_rights_and_closes_them():
    with _internal_owner() as owner:
        _bound(owner)
        parent, child = owner._socket_pair()
        descriptor = owner._own(os.open(os.devnull, os.O_RDONLY))
        child.sendmsg([_packet(owner, count=1)],
                      [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [descriptor]))])
        scope, pid, received = owner._receive(parent, 4, 1, count=1)
        assert (scope, pid) == (owner._scope, owner._target_pid)
        assert len(received) == 1 and received[0] in owner._fds
        assert not os.get_inheritable(received[0])
        assert os.fstat(received[0]) == os.fstat(descriptor)
    with pytest.raises(OSError):
        os.fstat(received[0])


@LINUX
@pytest.mark.parametrize("mutation", ["short", "long", "version", "operation", "sequence", "count", "reserved",
                                      "binding", "scope", "pid", "publications", "rights-count", "rights-truncated"])
def test_actual_seqpacket_refuses_malformed_packet_and_closes_received_rights(monkeypatch, mutation):
    with _internal_owner() as owner:
        _bound(owner)
        parent, child = owner._socket_pair()
        descriptor = owner._own(os.open(os.devnull, os.O_RDONLY))
        raw = _packet(owner, count=1)
        if mutation == "short":
            raw = raw[:-1]
        elif mutation == "long":
            raw += bytes(100)
        elif mutation in {"version", "operation", "sequence", "count", "reserved"}:
            raw = _patch_u32(raw, {"version": 4, "operation": 8, "sequence": 12, "count": 16, "reserved": 20}[mutation], 99)
        elif mutation in {"binding", "scope", "pid", "publications"}:
            changed = bytearray(raw)
            changed[{"binding": 24, "scope": 562, "pid": 602, "publications": 610}[mutation]] ^= 1
            raw = bytes(changed)
        rights = [descriptor] * (5 if mutation == "rights-truncated" else 1)
        child.sendmsg([raw], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", rights))])
        closed = []
        original_close = os.close

        def record_close(fd):
            closed.append(fd)
            original_close(fd)

        monkeypatch.setattr(whole.os, "close", record_close)
        with pytest.raises(whole.NativeWholeScopeError, match="protocol_invalid"):
            owner._receive(parent, 4, 1, count=0 if mutation == "rights-count" else 1)
        assert closed
        for descriptor_received in closed:
            with pytest.raises(OSError):
                os.fstat(descriptor_received)


@LINUX
def test_receive_uses_original_packet_boundary_instead_of_joining_two_short_packets():
    with _internal_owner() as owner:
        _bound(owner)
        parent, child = owner._socket_pair()
        packet = _packet(owner)
        child.send(packet[:400])
        child.send(packet[400:])
        with pytest.raises(whole.NativeWholeScopeError, match="protocol_invalid"):
            owner._receive(parent, 4, 1)
        assert parent.recv(926) == packet[400:]


@LINUX
def test_receive_refuses_expired_original_deadline_before_consuming_queued_packet():
    with _internal_owner() as owner:
        _bound(owner)
        parent, child = owner._socket_pair()
        packet = _packet(owner)
        child.send(packet)
        owner._deadline = time.monotonic_ns() - 1
        with pytest.raises(whole.NativeWholeScopeError, match="deadline_exceeded"):
            owner._receive(parent, 4, 1)
        assert parent.recv(926) == packet


@LINUX
def test_receive_deadline_expiry_after_packet_consumption_closes_original_rights(monkeypatch):
    with _internal_owner() as owner:
        _bound(owner)
        parent, child = owner._socket_pair()
        descriptor = owner._own(os.open(os.devnull, os.O_RDONLY))
        child.sendmsg([_packet(owner, count=1)],
                      [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [descriptor]))])
        owner._deadline = 150
        samples = iter((100, 200))
        monkeypatch.setattr(whole.time, "monotonic_ns", lambda: next(samples))
        closed = []
        original_close = os.close

        def record_close(fd):
            closed.append(fd)
            original_close(fd)

        monkeypatch.setattr(whole.os, "close", record_close)
        with pytest.raises(whole.NativeWholeScopeError, match="deadline_exceeded"):
            owner._receive(parent, 4, 1, count=1)
        assert len(closed) == 1
        with pytest.raises(OSError):
            os.fstat(closed[0])


@pytest.mark.parametrize("deadline", [None, True, 0, -1, 2**64])
def test_core_cannot_extend_or_encode_an_invalid_deadline(deadline):
    with _internal_owner() as owner:
        _bound(owner)
        with pytest.raises(whole.NativeWholeScopeError, match="deadline_exceeded"):
            owner._core(launch="1" * 64, intent="2" * 64, target="3" * 64, deadline_ns=deadline)


def test_wait_keeps_original_deadline_and_finite_poll_slice(monkeypatch):
    polls = []

    class Poll:
        def register(self, fd, mask):
            assert (fd, mask) == (7, 1)

        def poll(self, timeout):
            polls.append(timeout)
            return []

    monkeypatch.setattr(whole.select, "poll", Poll)
    monkeypatch.setattr(whole.time, "monotonic_ns", lambda: 100)
    with _internal_owner() as owner:
        owner._deadline = 20_000_100
        owner._wait(SimpleNamespace(fileno=lambda: 7), 1)
        assert polls == [10]
        assert owner.deadline_ns == 20_000_100


def test_release_is_one_shot_even_when_first_original_send_fails(monkeypatch):
    sent = []
    with _internal_owner() as owner:
        owner._registered = True
        owner._controller = object()
        owner._original_publications = SimpleNamespace(_borrow_for_native_transfer=lambda: ())
        monkeypatch.setattr(owner, "_check_installation", lambda: None)

        def fail_send(*args, **kwargs):
            sent.append((args, kwargs))
            raise OSError("fixture-original-channel-failed")

        monkeypatch.setattr(owner, "_send", fail_send)
        with pytest.raises(OSError):
            owner.release_original()
        with pytest.raises(whole.NativeWholeScopeError, match="owner_invalid"):
            owner.release_original()
        assert len(sent) == 1
        assert owner._finished is False


@LINUX
def test_early_completion_and_channel_closure_do_not_grant_quiescence(monkeypatch):
    with _internal_owner() as owner:
        _bound(owner)
        parent, _child = owner._socket_pair()
        owner._controller = parent
        owner._supervisor = SimpleNamespace(returncode=0, wait=lambda **_kwargs: 0)
        owner._bootstrap = SimpleNamespace(returncode=None)
        with pytest.raises(whole.NativeWholeScopeError, match="completion_unknown"):
            owner.finish()
        assert owner.cleanup() is False
        assert owner._finished is False


def test_successful_helper_exit_without_exact_original_complete_packet_is_unknown(monkeypatch):
    with _internal_owner() as owner:
        _bound(owner)
        owner._released = True
        owner._bootstrap = SimpleNamespace(returncode=0)
        owner._supervisor = SimpleNamespace(returncode=0, wait=lambda **_kwargs: 0)
        owner._controller = object()
        monkeypatch.setattr(owner, "_receive", lambda *_a, **_k: whole._fail("protocol_invalid"))
        with pytest.raises(whole.NativeWholeScopeError, match="protocol_invalid"):
            owner.finish()
        assert owner._finished is False


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("fixture", 0), RuntimeError("fixture"), KeyboardInterrupt()])
def test_retirement_wait_failure_never_leaks_owned_fds(failure):
    owner = whole.NativeWholeScopeOwner(whole._TOKEN)
    descriptor = owner._own(os.open(os.devnull, os.O_RDONLY))
    owner._deadline = time.monotonic_ns() + 5_000_000_000

    def fail_wait(**_kwargs):
        raise failure

    owner._supervisor = SimpleNamespace(returncode=None, wait=fail_wait)
    expected_error = whole.NativeWholeScopeError if isinstance(failure, subprocess.TimeoutExpired) else type(failure)
    try:
        with pytest.raises(expected_error):
            owner.close()
        with pytest.raises(OSError):
            os.fstat(descriptor)
    finally:
        # Explicit teardown also protects a diagnostic run of a broken owner.
        with suppress(OSError):
            os.close(descriptor)
