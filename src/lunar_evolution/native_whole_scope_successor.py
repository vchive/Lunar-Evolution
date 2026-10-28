"""Explicit v4 original coordinator ownership and strict, separate wire codec.

Records describe observations only. Only this live session launches and waits
its original Q, transfers the original B pidfd and adopts creator descriptions.
No historical record/reference constructor recreates a session.
"""
from __future__ import annotations

import array
import hashlib
import math
import os
import platform
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time

from .native_whole_scope import (
    _BINDING,
    _HEADER,
    _IDENTITY,
    _NAMESPACE,
    _POPEN,
    _PREFIX,
    _PROFILE_SIZE,
    _PUBLICATION,
    _TOKEN,
    _cgroup,
    _digest,
    _fail,
    _kernel_identity,
    _overlap,
    _text,
    fcntl,
)

PROFILE_NAME = "linux-whole-scope-successor-custody-v4"
PROFILE_PATH = "/etc/lunar-evolution/whole-scope-successor-v4.profile"
MAGIC = 0x3451574C
VERSION = 4
CONTEXT_SIZE = 925
PROPOSAL_SIZE = 949
COMMIT_SIZE = 1914
RESULT_SIZE = 2863
_PROPOSAL = struct.Struct("<4IQ")
_COMMIT = struct.Struct("<4IQ4I")
_RESULT = struct.Struct("<4IQ")
_SESSION_TOKEN = object()


def _retire_incoming(descriptors):
    """Try every received right, preserving any already active refusal."""
    active, failure = sys.exception(), None
    for fd in descriptors:
        try:
            os.close(fd)
        except BaseException as exc:  # noqa: BLE001 - exhaust owned rights before raising
            failure = failure or exc
    if active is None and failure is not None:
        raise failure


def _binding_valid(raw):
    if type(raw) is not bytes or len(raw) != _BINDING.size:
        _fail("successor_protocol_invalid")
    fields = _BINDING.unpack(raw)
    groups, count = fields[10:], fields[9]
    if (not fields[0] or any(len(value) != 65 or value[-1:] != b"\0"
            or any(char not in b"0123456789abcdef" for char in value[:64]) for value in fields[1:7])
            or not 0 < fields[7] < 2**32 - 1 or not 0 < fields[8] < 2**32 - 1
            or count > 32 or any(groups[count:])
            or tuple(sorted(set(groups[:count]))) != groups[:count]
            or any(not 0 < group < 2**32 - 1 for group in groups[:count])):
        _fail("successor_protocol_invalid")
    return fields


def context(binding, scope, target, publications, operation, sequence, count=0):
    """Encode exactly one v4 context; never alter a legacy packet's header."""
    _binding_valid(binding)
    if (type(scope) is not bytes or len(scope) != _IDENTITY.size
            or type(target) is not int or not 0 <= target < 2**31
            or type(publications) is not bytes or len(publications) != 3 * _PUBLICATION.size
            or type(operation) is not int or not 64 <= operation <= 106
            or type(sequence) is not int or not 0 <= sequence <= 10
            or type(count) is not int or not 0 <= count <= 4):
        _fail("successor_protocol_invalid")
    return (_HEADER.pack(MAGIC, VERSION, operation, sequence, count, 0) + binding
            + scope + struct.pack("<Q", target) + publications)


def validate_context(raw, operation, sequence, count=0, *, binding=None, projection=None, initial=False):
    if (type(raw) is not bytes or len(raw) != CONTEXT_SIZE
            or _HEADER.unpack_from(raw) != (MAGIC, VERSION, operation, sequence, count, 0)):
        _fail("successor_protocol_invalid")
    actual = raw[_HEADER.size:_HEADER.size + _BINDING.size]
    _binding_valid(actual)
    if ((binding is not None and actual != binding)
            or (projection is not None and raw[_HEADER.size:] != projection[_HEADER.size:])):
        _fail("successor_protocol_invalid")
    if initial:
        fields = _IDENTITY.unpack_from(raw, _HEADER.size + _BINDING.size)
        if (not fields[1] or not fields[2] or fields[3] or fields[4]
                or not stat.S_ISDIR(fields[5]) or fields[5] & 0o022 or fields[6]):
            _fail("successor_protocol_invalid")
    return raw


def validate_registration(raw):
    validate_context(raw, 79, 1, initial=True)
    if not 0 < struct.unpack_from("<Q", raw, _HEADER.size + _BINDING.size + _IDENTITY.size)[0] < 2**31:
        _fail("successor_protocol_invalid")
    for index in range(3):
        fields = _PUBLICATION.unpack_from(raw, CONTEXT_SIZE - 3 * _PUBLICATION.size + index * _PUBLICATION.size)
        if (not fields[1] or not fields[2] or fields[5][-1:] != b"\0"
                or any(char not in b"0123456789abcdef" for char in fields[5][:64])):
            _fail("successor_protocol_invalid")
    return raw


def _wait_fields(facts, bit, code, status):
    if not facts & bit:
        return code == status == 0
    return ((code == 1 and status <= 255)
            or (code in (2, 3) and 0 < status < 65))


def validate_commit(raw, registration):
    validate_registration(registration)
    if type(raw) is not bytes or len(raw) != COMMIT_SIZE:
        _fail("successor_protocol_invalid")
    decision, reason, sequence, facts, committed, sc, ss, gc, gs = _COMMIT.unpack_from(raw, CONTEXT_SIZE)
    if decision not in (1, 2):
        _fail("successor_protocol_invalid")
    validate_context(raw[:CONTEXT_SIZE], 98 if decision == 1 else 99, 2, projection=registration)
    proposal = raw[CONTEXT_SIZE + _COMMIT.size:]
    validate_context(proposal[:CONTEXT_SIZE], 91, 7, projection=registration)
    source, trigger, source_facts, reserved, observed = _PROPOSAL.unpack_from(proposal, CONTEXT_SIZE)
    deadline = _BINDING.unpack_from(registration, _HEADER.size)[0]
    if (sequence != 1 or facts & ~63 or not 0 < observed <= committed < deadline or reserved
            or source not in (1, 2, 3) or trigger > 8 or source_facts & ~15
            or not _wait_fields(facts, 8, sc, ss) or not _wait_fields(facts, 16, gc, gs)
            or (source == 1 and (trigger != 0 or source_facts != 10))
            or (source != 1 and (not trigger or not source_facts & 1
                                or (source_facts & 2 and not source_facts & 4)))):
        _fail("successor_protocol_invalid")
    if decision == 1:
        if reason or source != 1 or facts != 58 or (sc, ss, gc, gs) != (1, 0, 1, 0):
            _fail("successor_protocol_invalid")
    elif (not 1 <= reason <= 7 or source not in (2, 3) or not facts & 1
          or (facts & 2 and not facts & 4)):
        _fail("successor_protocol_invalid")
    return {"decision": decision, "reason": reason, "facts": facts, "s_code": sc, "s_status": ss,
            "g_code": gc, "g_status": gs, "source": source, "trigger": trigger,
            "source_facts": source_facts, "observed_ns": observed, "committed_ns": committed}


def validate_result(raw, registration):
    if type(raw) is not bytes or len(raw) != RESULT_SIZE:
        _fail("successor_protocol_invalid")
    commit = raw[CONTEXT_SIZE:CONTEXT_SIZE + COMMIT_SIZE]
    result = validate_commit(commit, registration)
    validate_context(raw[:CONTEXT_SIZE], 101 if result["decision"] == 1 else 102, 4, projection=registration)
    facts, code, status, reserved, observed = _RESULT.unpack_from(raw, CONTEXT_SIZE + COMMIT_SIZE)
    deadline = _BINDING.unpack_from(registration, _HEADER.size)[0]
    if (facts != 7 or code != 1 or status or reserved
            or not result["committed_ns"] <= observed < deadline):
        _fail("successor_protocol_invalid")
    return {**result, "commit": commit, "result_observed_ns": observed}


def _parse_profile(raw):
    """Independent v4 profile grammar; never translate into the v1 parser."""
    if type(raw) is not bytes or len(raw) != _PROFILE_SIZE:
        _fail("successor_profile_invalid")
    prefix = _PREFIX.unpack_from(raw)
    magic, version, size, uid, gid, count = prefix[:6]
    groups = prefix[6:38]
    readonly_count, flags = prefix[38:]
    if (magic != 0x3450574C or version != 4 or size != _PROFILE_SIZE or flags != 1
            or not 0 < uid < 2**32 - 1 or not 0 < gid < 2**32 - 1 or count > 32
            or not 1 <= readonly_count <= 16 or any(groups[count:])
            or tuple(sorted(set(groups[:count]))) != groups[:count]
            or any(not 0 < group < 2**32 - 1 for group in groups[:count])):
        _fail("successor_profile_invalid")
    offset = _PREFIX.size
    identities = tuple(_IDENTITY.unpack_from(raw, offset + i * _IDENTITY.size) for i in range(18))
    offset += 18 * _IDENTITY.size
    for identity in identities[:readonly_count + 2]:
        if (not identity[1] or not identity[2] or identity[3] or identity[6]
                or identity[5] & 0o022 or not stat.S_ISDIR(identity[5])):
            _fail("successor_profile_invalid")
    if any(any(row) for row in identities[readonly_count + 2:]):
        _fail("successor_profile_invalid")
    namespaces = tuple(_NAMESPACE.unpack_from(raw, offset + i * _NAMESPACE.size) for i in range(4))
    if any(not inode for _, inode in namespaces):
        _fail("successor_profile_invalid")
    offset += 4 * _NAMESPACE.size
    paths_raw = tuple(raw[offset + i * 1024:offset + (i + 1) * 1024] for i in range(18))
    paths = tuple(_text(part) for part in paths_raw[:readonly_count + 2])
    if any(any(row) for row in paths_raw[readonly_count + 2:]):
        _fail("successor_profile_invalid")
    for i, path in enumerate(paths):
        if (_overlap(path, PROFILE_PATH) or any(_overlap(path, other) for other in paths[:i])
                or any(identities[i][:2] == other[:2] for other in identities[:i])):
            _fail("successor_profile_invalid")
    offset += 18 * 1024
    hashes = []
    for i in range(2):
        value = raw[offset + i * 65:offset + (i + 1) * 65]
        try:
            text = value[:64].decode("ascii")
        except UnicodeError:
            _fail("successor_profile_invalid")
        if _digest(text) != value:
            _fail("successor_profile_invalid")
        hashes.append(text)
    return {"uid": uid, "gid": gid, "groups": groups[:count], "paths": paths,
            "identities": identities[:readonly_count + 2], "namespaces": namespaces,
            "bootstrap_sha256": hashes[0], "supervisor_sha256": hashes[1]}


def _acquire(owner, expected_profile_sha256, bootstrap, supervisor):
    from .native_bootstrap import NativeBootstrapArtifact

    if (sys.platform != "linux" or platform.machine() != "x86_64" or fcntl is None
            or os.getresuid() != (0, 0, 0) or os.getresgid() != (0, 0, 0)
            or type(bootstrap) is not NativeBootstrapArtifact):
        _fail("installation_unavailable")
    _digest(expected_profile_sha256)
    profile_source = owner._open_chain(PROFILE_PATH, file=True)
    if stat.S_IMODE(os.fstat(profile_source).st_mode) != 0o600:
        _fail("installation_unavailable")
    raw = owner._read_file(profile_source, _PROFILE_SIZE)
    if hashlib.sha256(raw).hexdigest() != expected_profile_sha256:
        _fail("profile_changed")
    owner._profile = _parse_profile(raw)
    owner._profile_raw, owner._profile_sha256 = raw, expected_profile_sha256
    if owner._profile["bootstrap_sha256"] != bootstrap.artifact_sha256:
        _fail("installation_unavailable")
    source = owner._open_chain(os.fspath(bootstrap.path), file=True)
    if hashlib.sha256(owner._read_file(source, 8 * 1024 * 1024)).hexdigest() != owner._profile["bootstrap_sha256"]:
        _fail("original_changed")
    image_source = owner._open_chain(os.fspath(supervisor), file=True)
    owner._image_raw = owner._read_file(image_source, 8 * 1024 * 1024)
    if (hashlib.sha256(owner._image_raw).hexdigest() != owner._profile["supervisor_sha256"]
            or not owner._image_raw.startswith(b"\x7fELF\x02\x01")):
        _fail("installation_unavailable")
    owner._profile_fd = owner._seal("lunar-whole-scope-successor-profile", raw)
    owner._image_fd = owner._seal("lunar-whole-scope-successor-image", owner._image_raw)
    roots = []
    for path, identity in zip(owner._profile["paths"], owner._profile["identities"], strict=True):
        fd = owner._open_chain(path)
        if _kernel_identity(fd) != identity:
            _fail("original_changed")
        roots.append(fd)
    owner._delegation_fd, owner._execution_fd, *owner._readonly_fds = roots
    _cgroup(owner._delegation_fd)
    owner._namespace_fds = []
    for name, identity in zip(("user", "pid", "mnt", "cgroup"), owner._profile["namespaces"], strict=True):
        fd = owner._own(os.open("/proc/self/ns/" + name, os.O_RDONLY | os.O_CLOEXEC))
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != identity:
            _fail("original_changed")
        owner._namespace_fds.append(fd)
    owner._check_installation()
    owner._successor_session = _SuccessorSession(_SESSION_TOKEN, owner)


class _SuccessorSession:
    """One original C/Q relationship, reachable only from installed selection."""

    def __init__(self, token, owner):
        if token is not _SESSION_TOKEN:
            _fail("owner_invalid")
        self.owner = owner
        self.registration = None
        self._q = None
        self._q_pidfd = None
        self._q_waited = False
        self._b = None
        self._b_pidfd = None
        self._b_waited = False
        self._result = None
        self._publication_bytes = None

    def __copy__(self):
        _fail("owner_invalid")

    def __deepcopy__(self, memo):
        _fail("owner_invalid")

    def __reduce_ex__(self, protocol):
        _fail("owner_invalid")

    def check(self):
        from .native_whole_scope import NativeWholeScopeOwner

        owner = self.owner
        if (type(owner) is not NativeWholeScopeOwner or owner._successor_session is not self
                or owner._closed or owner._profile is None
                or (self._q is not None and owner._supervisor is not self._q)):
            _fail("owner_invalid")
        return owner

    def _packet(self, operation, sequence, *, count=0, bound=True, publications=None):
        owner = self.check()
        return context(owner._binding, owner._scope if bound else b"\0" * _IDENTITY.size,
                       owner._target_pid if bound else 0,
                       publications if publications is not None else b"\0" * (3 * _PUBLICATION.size),
                       operation, sequence, count)

    def _send(self, sock, packet, rights=()):
        owner = self.check()
        if (type(rights) is not tuple or len(rights) > 4 or len(set(rights)) != len(rights)
                or any(type(fd) is not int or fd < 0 for fd in rights)
                or not CONTEXT_SIZE <= len(packet) <= RESULT_SIZE
                or _HEADER.unpack_from(packet)[4] != len(rights)):
            _fail("successor_protocol_invalid")
        ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", rights))] if rights else []
        while True:
            owner._remaining()
            try:
                if sock.sendmsg([packet], ancillary, socket.MSG_NOSIGNAL) != len(packet):
                    _fail("successor_protocol_invalid")
                owner._remaining()
                return
            except BlockingIOError:
                owner._wait(sock, select.POLLOUT)

    def _receive(self, sock, size, count=0):
        owner = self.check()
        if (type(size) is not int or size not in (CONTEXT_SIZE, RESULT_SIZE)
                or type(count) is not int or not 0 <= count <= 4):
            _fail("successor_protocol_invalid")
        acquired = []
        while True:
            owner._remaining()
            try:
                raw, ancillary, flags, _ = sock.recvmsg(RESULT_SIZE + 1,
                    socket.CMSG_SPACE(4 * array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC)
                break
            except BlockingIOError:
                owner._wait(sock, select.POLLIN)
        try:
            # Inventory every delivered numeric right before rejecting any
            # malformed/unknown ancillary entry, frame, count or truncation.
            invalid = False
            for level, kind, values in ancillary:
                if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                    invalid = True
                    continue
                width = array.array("i").itemsize
                rights = array.array("i")
                rights.frombytes(values[:len(values) // width * width])
                acquired.extend(rights)
                invalid |= bool(len(values) % width)
            if (invalid or len(raw) != size or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC)
                    or len(acquired) != count or len(ancillary) != bool(count)
                    or _HEADER.unpack_from(raw)[:2] != (MAGIC, VERSION)
                    or _HEADER.unpack_from(raw)[4:] != (count, 0)
                    or raw[_HEADER.size:_HEADER.size + _BINDING.size] != owner._binding):
                _fail("successor_protocol_invalid")
            owner._remaining()
            result = tuple(acquired)
            acquired = []
            return raw, result
        finally:
            _retire_incoming(acquired)

    def publish(self, deadline_ns):
        import secrets

        owner = self.check()
        if owner._published is not None or owner._preparation_key is not None or owner._channels_prepared:
            _fail("grants_unavailable")
        owner._check_installation()
        owner._deadline, owner._preparation_key = deadline_ns, secrets.token_hex(32)
        owner._binding = owner._core(launch=owner._preparation_key, intent=owner._preparation_key,
                                    target="0" * 64, deadline_ns=deadline_ns)
        parent, child = owner._socket_pair()
        command = [f"/proc/self/fd/{owner._image_fd}", "--publish-successor-v4", "--profile-fd", str(owner._profile_fd),
                   "--execution-root-fd", str(owner._execution_fd), "--controller-fd", str(child.fileno()),
                   "--image-fd", str(owner._image_fd), "--deadline-monotonic-ns", str(deadline_ns)]
        owner._remaining()
        owner._publisher = subprocess.Popen(command, executable=command[0], close_fds=True,
            pass_fds=(owner._profile_fd, owner._execution_fd, child.fileno(), owner._image_fd),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd="/", env={"PATH": os.defpath, "LANG": "C"})
        child.close()
        self._send(parent, self._packet(105, 0, bound=False))
        raw, fds = self._receive(parent, CONTEXT_SIZE, 3)
        pending = list(fds)
        try:
            validate_context(raw, 106, 1, 3, binding=owner._binding, initial=True)
            offset = _HEADER.size + _BINDING.size
            if (any(raw[offset + _IDENTITY.size:])
                    or len({_kernel_identity(fd)[:2] for fd in fds}) != 3
                    or _IDENTITY.pack(*_kernel_identity(fds[0])) != raw[offset:offset + _IDENTITY.size]):
                _fail("grants_unavailable")
            owner._publisher.wait(timeout=owner._remaining())
            owner._remaining()
            if owner._publisher.returncode != 0:
                _fail("grants_unavailable")
            while pending:
                owner._own(pending.pop(0))
            owner._published = fds
            owner._publication_pins = tuple((_kernel_identity(fd), os.getxattr(fd, "system.posix_acl_access")
                                             if i == 0 else None) for i, fd in enumerate(fds))
            owner._binding = None
            return owner.working_directory, owner.output_directory
        finally:
            _retire_incoming(pending)

    def start(self, *, process, launch, intent, controller_lifeline_fd, deadline_ns, bootstrap=None):
        from .native_whole_scope_successor_custody import NativeWholeScopeSuccessorCustodyOwner
        from .producer_bootstrap import TrustedBootstrapLaunch
        from .producer_launcher import ProducerLaunchIntent

        owner = self.check()
        if (self._q is not None or self._b is not None or owner._supervisor is not None or not owner._channels_prepared
                or type(process) is not _POPEN or process.returncode is not None
                or type(launch) is not TrustedBootstrapLaunch or type(intent) is not ProducerLaunchIntent
                or signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL or threading.active_count() != 1
                or os.listdir("/proc/self/task") != [str(os.getpid())]
                or type(owner._custody_owner) is not NativeWholeScopeSuccessorCustodyOwner):
            _fail("original_wait_unavailable")
        owner._check_installation()
        if deadline_ns != owner._deadline or launch.intent_sha256 != owner._final_intent:
            _fail("owner_invalid")
        owner._binding = owner._core(launch=launch.launch_sha256, intent=launch.intent_sha256,
                                     target=intent.executable_sha256, deadline_ns=deadline_ns)
        directory = owner._custody_owner._borrow_for_start()
        line = os.fstat(controller_lifeline_fd)
        if (not stat.S_ISFIFO(line.st_mode)
                or fcntl.fcntl(controller_lifeline_fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY):
            _fail("successor_protocol_invalid")
        owner._remaining()
        owner._bootstrap = process
        # B remains an unreaped original child throughout this capture/transfer.
        bootstrap_pidfd = owner._own(os.pidfd_open(process.pid, 0))
        try:
            self._b = process
            # Keep a private same-OFD duplicate of the original right sent to
            # Q; neither a PID lookup nor Popen's cached status can replace it.
            self._b_pidfd = owner._own(os.dup(bootstrap_pidfd))
            inherited = (owner._profile_fd, owner._delegation_fd, owner._controller_child.fileno(),
                         owner._enrollment_child.fileno(), owner._lifecycle_child.fileno(),
                         controller_lifeline_fd, owner._image_fd, directory)
            names = ("--profile-fd", "--delegation-fd", "--controller-fd", "--enrollment-fd",
                     "--lifecycle-fd", "--controller-lifeline-fd", "--image-fd", "--custody-dir-fd")
            command = [f"/proc/self/fd/{owner._image_fd}", "--successor-coordinator-v4"]
            for name, fd in zip(names, inherited, strict=True):
                command.extend((name, str(fd)))
            command.extend(("--deadline-monotonic-ns", str(deadline_ns)))
            owner._remaining()
            self._q = subprocess.Popen(command, executable=command[0], pass_fds=inherited,
                close_fds=True, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, cwd="/", env={"PATH": os.defpath, "LANG": "C"})
            owner._supervisor = self._q
            self._q_pidfd = owner._own(os.pidfd_open(self._q.pid, 0))
            for sock in (owner._controller_child, owner._enrollment_child, owner._lifecycle_child,
                         owner._enrollment, owner._lifecycle):
                sock.close()
            self._send(owner._controller, self._packet(64, 0, count=1, bound=False), (bootstrap_pidfd,))
        finally:
            owner._drop(bootstrap_pidfd)

    def wait_enrolled(self):
        owner = self.check()
        if owner._scope is not None or self._q is None:
            _fail("owner_invalid")
        raw, _ = self._receive(owner._controller, CONTEXT_SIZE)
        validate_context(raw, 74, 1, binding=owner._binding, initial=True)
        offset = _HEADER.size + _BINDING.size
        target = struct.unpack_from("<Q", raw, offset + _IDENTITY.size)[0]
        if not 0 < target < 2**31 or any(raw[-3 * _PUBLICATION.size:]):
            _fail("successor_protocol_invalid")
        owner._scope, owner._target_pid = raw[offset:offset + _IDENTITY.size], target

    def bind_registration(self, publications, context=None):
        from .native_original_publication import NativeOriginalPublications

        owner = self.check()
        if type(publications) is not NativeOriginalPublications or owner._registered or self.registration is not None:
            _fail("owner_invalid")
        if owner._scope is None:
            self.wait_enrolled()
        owner._check_installation()
        descriptors, pins = publications._borrow_for_native_transfer()
        raw = b"".join(_PUBLICATION.pack(device, inode, size, mtime, ctime, _digest(digest))
                       for digest, size, device, inode, mtime, ctime in pins)
        self._publication_bytes = raw
        self.registration = validate_registration(self._packet(79, 1, publications=raw))
        owner._original_publications = publications
        self._send(owner._controller, self._packet(75, 1, count=3, publications=raw), descriptors)
        packet, rights = self._receive(owner._controller, CONTEXT_SIZE, 2)
        try:
            validate_context(packet, 81, 2, 2, projection=self.registration)
            owner._custody_owner._adopt_creator_descriptions(_TOKEN, owner, rights, raw)
        finally:
            _retire_incoming(rights)
        owner._remaining()
        owner._check_installation()
        publications._borrow_for_native_transfer()
        owner._custody_owner._check_registration()
        self._send(owner._controller, self._packet(82, 2, publications=raw))
        packet, _ = self._receive(owner._controller, CONTEXT_SIZE)
        validate_context(packet, 83, 2, projection=self.registration)
        owner._remaining()
        owner._check_installation()
        publications._borrow_for_native_transfer()
        owner._custody_owner._check_registration()
        owner._registered = True

    def release(self):
        owner = self.check()
        if not owner._registered or owner._released:
            _fail("owner_invalid")
        owner._check_installation()
        owner._original_publications._borrow_for_native_transfer()
        owner._custody_owner._check_registration()
        self._send(owner._controller, self._packet(86, 3, publications=self._publication_bytes))
        owner._released = True

    def _wait_original_q(self):
        owner = self.check()
        if (self._q is None or type(self._q) is not _POPEN or self._q_waited
                or self._q.returncode is not None or self._q_pidfd is None):
            _fail("original_wait_unavailable")
        # Popen.wait may turn ECHILD into a synthetic zero after an unrelated
        # reaper. Consume this original pidfd's wait explicitly and refuse that
        # case, while excluding a concurrent Popen waiter on this actual object.
        if not self._q._waitpid_lock.acquire(blocking=False):
            _fail("original_wait_unavailable")
        try:
            if self._q.returncode is not None:
                _fail("original_wait_unavailable")
            while True:
                owner._remaining()
                try:
                    info = os.waitid(os.P_PIDFD, self._q_pidfd, os.WEXITED | os.WNOHANG)
                except ChildProcessError:
                    _fail("original_wait_unavailable")
                if info is not None:
                    if (info.si_pid != self._q.pid or info.si_code not in (1, 2, 3)
                            or not _wait_fields(8, 8, info.si_code, info.si_status)):
                        _fail("original_wait_unavailable")
                    code = info.si_status if info.si_code == 1 else -info.si_status
                    self._q.returncode = code
                    self._q_waited = True
                    owner._remaining()
                    return code
                poller = select.poll()
                poller.register(self._q_pidfd, select.POLLIN)
                poller.poll(max(1, min(10, int(owner._remaining() * 1000))))
        finally:
            self._q._waitpid_lock.release()

    def wait_original_bootstrap(self, *, timeout):
        """Consume only original B's wait, within one caller polling slice.

        A slice timeout leaves B unreaped for the original runner's next
        cancellation/deadline check. It never creates a new attempt allowance.
        """
        owner = self.check()
        process = self._b
        if (type(process) is not _POPEN or owner._bootstrap is not process or self._b_waited
                or process.returncode is not None or self._b_pidfd is None
                or self._b_pidfd not in owner._fds
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0):
            _fail("original_wait_unavailable")
        slice_deadline = time.monotonic() + timeout
        if not process._waitpid_lock.acquire(blocking=False):
            _fail("original_wait_unavailable")
        try:
            if process.returncode is not None:
                _fail("original_wait_unavailable")
            while True:
                owner._remaining()
                try:
                    info = os.waitid(os.P_PIDFD, self._b_pidfd, os.WEXITED | os.WNOHANG)
                except ChildProcessError:
                    _fail("original_wait_unavailable")
                if info is not None:
                    if (info.si_pid != process.pid or info.si_code not in (1, 2, 3)
                            or not _wait_fields(8, 8, info.si_code, info.si_status)):
                        _fail("original_wait_unavailable")
                    code = info.si_status if info.si_code == 1 else -info.si_status
                    process.returncode = code
                    self._b_waited = True
                    owner._remaining()
                    return code
                slice_remaining = slice_deadline - time.monotonic()
                if slice_remaining <= 0:
                    raise subprocess.TimeoutExpired("native-whole-scope-original-bootstrap", timeout)
                poller = select.poll()
                poller.register(self._b_pidfd, select.POLLIN)
                poller.poll(max(1, min(10, int(min(owner._remaining(), slice_remaining) * 1000))))
        finally:
            process._waitpid_lock.release()

    def cleanup(self):
        owner = self.check()
        if self._q is None:
            return False
        owner._controller.close()
        if not self._q_waited:
            try:
                self._wait_original_q()
            except (OSError, ValueError, subprocess.TimeoutExpired):
                return False
        # Consuming Q's actual abnormal wait does not prove scope completion.
        return False

    def finish(self):
        owner = self.check()
        if owner._finished:
            return
        if (not owner._released or self._q is None or not self._b_waited
                or owner._bootstrap is not self._b or self._b is None
                or owner._bootstrap.returncode != 0 or self.registration is None):
            _fail("completion_unknown")
        raw, _ = self._receive(owner._controller, RESULT_SIZE)
        result = validate_result(raw, self.registration)
        qcode = self._wait_original_q()
        self._result = result
        owner._check_installation()
        owner._original_publications._borrow_for_native_transfer()
        owner._custody_owner._check_registration(terminal=True, commit=result["commit"])
        if result["decision"] != 1 or qcode != 0:
            _fail("completion_unknown")
        owner._remaining()
        owner._finished = True
