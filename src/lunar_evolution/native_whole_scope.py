"""Original ownership for the explicit, installed cgroup-v2 native profile.

This path requires an already privileged administrator and a fixed installation.
It neither installs privileges nor reconstructs a live operation from a receipt.
The native supervisor owns kernel scope observation and its guardian's waits.
"""
from __future__ import annotations

import array
import ctypes
import hashlib
import os
import platform
import secrets
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # The default native path remains portable.
    fcntl = None

PROFILE_PATH = "/etc/lunar-evolution/whole-scope-v1.profile"
PROFILE_NAME = "linux-cgroup2-original-scope-v1"
_TOKEN = object()
_IDENTITY = struct.Struct("<QQQIIII")
_NAMESPACE = struct.Struct("<QQ")
_PREFIX = struct.Struct("<6I32I2I")
_BINDING = struct.Struct("<Q65s65s65s65s65s65sIII32I")
_HEADER = struct.Struct("<6I")
_PUBLICATION = struct.Struct("<5Q65s")
_PROFILE_SIZE = 19506
_MESSAGE_SIZE = 925
_CGROUP2_MAGIC = 0x63677270
_POPEN = subprocess.Popen
_ZERO = b"\0"


class NativeWholeScopeError(ValueError):
    """Fixed, context-free refusal; a failure never grants cleanup authority."""

    def __init__(self, reason="unavailable"):
        self.code = "native_whole_scope_" + reason
        super().__init__(self.code)


def _fail(reason="unavailable"):
    raise NativeWholeScopeError(reason)


def _digest(value):
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        _fail("digest_invalid")
    return value.encode("ascii") + _ZERO


def _text(raw):
    text, separator, padding = raw.partition(_ZERO)
    if not separator or any(padding):
        _fail("profile_invalid")
    try:
        value = text.decode("utf-8")
    except UnicodeError:
        _fail("profile_invalid")
    if (not value.startswith("/") or value == "/" or "\x00" in value or len(text) > 1023
            or len(value[1:].split("/")) > 63
            or any(len(os.fsencode(part)) > 255 for part in value[1:].split("/"))
            or any(p in {"", ".", ".."} for p in value[1:].split("/"))):
        _fail("profile_invalid")
    return value


def _overlap(a, b):
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _parse_profile(raw):
    if type(raw) is not bytes or len(raw) != _PROFILE_SIZE:
        _fail("profile_invalid")
    prefix = _PREFIX.unpack_from(raw)
    magic, version, size, uid, gid, count = prefix[:6]
    groups = prefix[6:38]
    readonly_count, flags = prefix[38:]
    if (magic != 0x3150574C or version != 1 or size != _PROFILE_SIZE
            or not uid or not gid or count > 32 or not 1 <= readonly_count <= 16 or flags
            or any(groups[count:]) or tuple(sorted(set(groups[:count]))) != groups[:count]
            or any(not group for group in groups[:count])):
        _fail("profile_invalid")
    offset = _PREFIX.size
    identities = tuple(_IDENTITY.unpack_from(raw, offset + i * _IDENTITY.size) for i in range(18))
    offset += 18 * _IDENTITY.size
    for identity in identities[:readonly_count + 2]:
        if (not identity[1] or not identity[2] or identity[3] != 0
                or identity[5] & 0o022 or not stat.S_ISDIR(identity[5]) or identity[6]):
            _fail("profile_invalid")
    if any(any(x) for x in identities[readonly_count + 2:]):
        _fail("profile_invalid")
    namespaces = tuple(_NAMESPACE.unpack_from(raw, offset + i * 16) for i in range(4))
    if any(not inode for _, inode in namespaces):
        _fail("profile_invalid")
    offset += 64
    paths_raw = tuple(raw[offset + i * 1024:offset + (i + 1) * 1024] for i in range(18))
    paths = tuple(_text(part) for part in paths_raw[:readonly_count + 2])
    if any(any(x) for x in paths_raw[readonly_count + 2:]):
        _fail("profile_invalid")
    if (_overlap(paths[0], paths[1]) or any(_overlap(path, private)
            for path in paths[2:] for private in (*paths[:2], PROFILE_PATH))
            or len(set(paths)) != len(paths)):
        _fail("profile_invalid")
    offset += 18 * 1024
    hashes = []
    for i in range(2):
        value = raw[offset + i * 65:offset + (i + 1) * 65]
        try:
            text = value[:64].decode("ascii")
        except UnicodeError:
            _fail("profile_invalid")
        if _digest(text) != value:
            _fail("profile_invalid")
        hashes.append(text)
    return {"uid": uid, "gid": gid, "groups": groups[:count], "paths": paths,
            "identities": identities[:readonly_count + 2], "namespaces": namespaces,
            "bootstrap_sha256": hashes[0], "supervisor_sha256": hashes[1]}


def _stat_pin(info, *, directory=False):
    base = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
    return base if directory else (*base, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _mount_id(fd, name=b""):
    # statx AT_EMPTY_PATH observes this held object, not a reconstructed path.
    libc = ctypes.CDLL(None, use_errno=True)
    result = ctypes.create_string_buffer(256)
    statx = getattr(libc, "statx", None)
    if statx is None or statx(fd, ctypes.c_char_p(name), 0x100 if name else 0x1100, 0x17FF, result):
        _fail("kernel_unsupported")
    raw = result.raw
    if not struct.unpack_from("<I", raw)[0] & 0x1000:
        _fail("kernel_unsupported")
    return struct.unpack_from("<Q", raw, 144)[0]


def _kernel_identity(fd):
    info = os.fstat(fd)
    return (info.st_dev, info.st_ino, _mount_id(fd), info.st_uid, info.st_gid, info.st_mode, 0)


def _cgroup(fd):
    buffer = ctypes.create_string_buffer(256)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.fstatfs(fd, buffer) or struct.unpack_from("<q", buffer.raw)[0] != _CGROUP2_MAGIC:
        _fail("delegation_unavailable")


def _seals(fd):
    required = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
    if fcntl.fcntl(fd, fcntl.F_GET_SEALS) & required != required:
        _fail("original_changed")


class NativeWholeScopeOwner:
    """One live installed acquisition; no public FD/DTO-based constructor."""

    def __init__(self, token):
        if token is not _TOKEN:
            _fail()
        self._fds = set()
        self._sockets = []
        self._named = []
        self._closed = False
        self._profile = None
        self._profile_raw = b""
        self._image_raw = b""
        self._binding = None
        self._deadline = None
        self._supervisor = None
        self._publisher = None
        self._bootstrap = None
        self._scope = None
        self._target_pid = None
        self._registered = self._released = self._finished = False
        self._channels_prepared = False
        self._published = None
        self._publication_pins = None
        self._preparation_key = None
        self._final_intent = None
        self._fixed_u_input_owner = None
        self._custody_owner = None

    def __copy__(self):
        _fail("owner_invalid")

    def __deepcopy__(self, memo):
        _fail("owner_invalid")

    def __reduce_ex__(self, protocol):
        _fail("owner_invalid")

    def _own(self, fd):
        try:
            self._fds.add(fd)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def _drop(self, fd):
        self._fds.remove(fd)
        os.close(fd)

    def _remaining(self):
        now = time.monotonic_ns()
        if self._deadline is None or now >= self._deadline:
            _fail("deadline_exceeded")
        return (self._deadline - now) / 1e9

    def _open_chain(self, path, *, file=False):
        _text(os.fsencode(path) + _ZERO)
        fd = self._own(os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC))
        info = os.fstat(fd)
        if info.st_uid or info.st_mode & 0o022:
            _fail("installation_unavailable")
        self._named.append((fd, None, "", (*_stat_pin(info, directory=True), _mount_id(fd)), True))
        parts = path[1:].split("/")
        for i, name in enumerate(parts):
            directory = not file or i < len(parts) - 1
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if directory:
                flags |= os.O_DIRECTORY
            child = self._own(os.open(name, flags, dir_fd=fd))
            info = os.fstat(child)
            if (info.st_uid or info.st_mode & 0o022 or
                    (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode))):
                _fail("installation_unavailable")
            pin = (*_stat_pin(info, directory=directory), _mount_id(child))
            if (*_stat_pin(os.stat(name, dir_fd=fd, follow_symlinks=False), directory=directory),
                    _mount_id(fd, os.fsencode(name))) != pin:
                _fail("original_changed")
            self._named.append((child, fd, name, pin, directory))
            fd = child
        return fd

    def _read_file(self, fd, maximum):
        pin = _stat_pin(os.fstat(fd))
        size = pin[6]
        if pin[5] != 1 or not 0 < size <= maximum:
            _fail("installation_unavailable")
        raw = os.pread(fd, maximum + 1, 0)
        if len(raw) != size or _stat_pin(os.fstat(fd)) != pin:
            _fail("original_changed")
        return raw

    def _seal(self, name, raw):
        fd = self._own(os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING))
        os.fchmod(fd, 0o600 if name.endswith("profile") else 0o700)
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                _fail("installation_unavailable")
            view = view[count:]
        required = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, required)
        _seals(fd)
        return fd

    def _acquire(self, expected_profile_sha256, bootstrap, supervisor):
        from .native_bootstrap import NativeBootstrapArtifact

        if (sys.platform != "linux" or platform.machine() != "x86_64" or fcntl is None
                or os.getresuid() != (0, 0, 0) or os.getresgid() != (0, 0, 0)):
            _fail("installation_unavailable")
        _digest(expected_profile_sha256)
        if type(bootstrap) is not NativeBootstrapArtifact:
            _fail("installation_unavailable")
        profile_source = self._open_chain(PROFILE_PATH, file=True)
        if stat.S_IMODE(os.fstat(profile_source).st_mode) != 0o600:
            _fail("installation_unavailable")
        raw = self._read_file(profile_source, _PROFILE_SIZE)
        if hashlib.sha256(raw).hexdigest() != expected_profile_sha256:
            _fail("profile_changed")
        self._profile = _parse_profile(raw)
        self._profile_raw = raw
        self._profile_sha256 = expected_profile_sha256
        if self._profile["bootstrap_sha256"] != bootstrap.artifact_sha256:
            _fail("installation_unavailable")
        source = self._open_chain(os.fspath(bootstrap.path), file=True)
        if hashlib.sha256(self._read_file(source, 8 * 1024 * 1024)).hexdigest() != self._profile["bootstrap_sha256"]:
            _fail("original_changed")
        image_source = self._open_chain(os.fspath(supervisor), file=True)
        self._image_raw = self._read_file(image_source, 8 * 1024 * 1024)
        if (hashlib.sha256(self._image_raw).hexdigest() != self._profile["supervisor_sha256"]
                or not self._image_raw.startswith(b"\x7fELF\x02\x01")):
            _fail("installation_unavailable")
        self._profile_fd = self._seal("lunar-whole-scope-profile", raw)
        self._image_fd = self._seal("lunar-whole-scope-supervisor", self._image_raw)
        roots = []
        for path, identity in zip(self._profile["paths"], self._profile["identities"], strict=True):
            fd = self._open_chain(path)
            if _kernel_identity(fd) != identity:
                _fail("original_changed")
            roots.append(fd)
        self._delegation_fd, self._execution_fd, *self._readonly_fds = roots
        _cgroup(self._delegation_fd)
        self._namespace_fds = []
        for name, identity in zip(("user", "pid", "mnt", "cgroup"), self._profile["namespaces"], strict=True):
            fd = self._own(os.open("/proc/self/ns/" + name, os.O_RDONLY | os.O_CLOEXEC))
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) != identity:
                _fail("original_changed")
            self._namespace_fds.append(fd)
        self._check_installation()

    def _check_installation(self):
        if self._closed or self._profile is None:
            _fail("owner_invalid")
        if os.getresuid() != (0, 0, 0) or os.getresgid() != (0, 0, 0):
            _fail("installation_unavailable")
        for fd, parent, name, pin, directory in self._named:
            if ((*_stat_pin(os.fstat(fd), directory=directory), _mount_id(fd)) != pin or (parent is not None
                    and (*_stat_pin(os.stat(name, dir_fd=parent, follow_symlinks=False), directory=directory),
                         _mount_id(parent, os.fsencode(name))) != pin)):
                _fail("original_changed")
        for fd, raw in ((self._profile_fd, self._profile_raw), (self._image_fd, self._image_raw)):
            _seals(fd)
            info = os.fstat(fd)
            if (os.pread(fd, len(raw) + 1, 0) != raw or info.st_uid or info.st_gid
                    or stat.S_IMODE(info.st_mode) != (0o600 if fd == self._profile_fd else 0o700)):
                _fail("original_changed")
        for name, fd, identity in zip(("user", "pid", "mnt", "cgroup"), self._namespace_fds,
                                      self._profile["namespaces"], strict=True):
            held, current = os.fstat(fd), os.stat("/proc/self/ns/" + name)
            if (held.st_dev, held.st_ino) != identity or (current.st_dev, current.st_ino) != identity:
                _fail("original_changed")
        _cgroup(self._delegation_fd)

    def _core(self, *, launch, intent, target, deadline_ns):
        if type(deadline_ns) is not int or not 0 < deadline_ns < 2**64:
            _fail("deadline_exceeded")
        groups = self._profile["groups"]
        return _BINDING.pack(deadline_ns, _digest(launch), _digest(intent), _digest(target),
                             _digest(self._profile["bootstrap_sha256"]),
                             _digest(self._profile["supervisor_sha256"]), _digest(self._profile_sha256),
                             self._profile["uid"], self._profile["gid"], len(groups),
                             *groups, *(0 for _ in range(32 - len(groups))))

    def _socket_pair(self):
        first, second = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            self._sockets.append(first)
            self._sockets.append(second)
            for value in (first, second):
                value.setblocking(False)
                value.set_inheritable(False)
        except BaseException:
            first.close()
            second.close()
            raise
        return first, second

    def _wait(self, sock, mask):
        waiter = select.poll()
        waiter.register(sock.fileno(), mask)
        self._remaining()
        events = waiter.poll(max(1, min(10, int(self._remaining() * 1000))))
        self._remaining()
        if any(flags & (select.POLLERR | select.POLLNVAL) for _, flags in events):
            _fail("protocol_invalid")

    def _send(self, sock, operation, sequence, *, fds=(), publications=None, bound=True):
        self._remaining()
        scope = self._scope if bound else None
        packet = (_HEADER.pack(0x3151574C, 1, operation, sequence, len(fds), 0) + self._binding
                  + (scope or _ZERO * _IDENTITY.size) + struct.pack("<Q", self._target_pid if bound else 0)
                  + (publications or _ZERO * (3 * _PUBLICATION.size)))
        if len(packet) != _MESSAGE_SIZE or len(fds) > 4 or len(set(fds)) != len(fds):
            _fail("protocol_invalid")
        ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))] if fds else []
        while True:
            try:
                if sock.sendmsg([packet], ancillary, socket.MSG_NOSIGNAL) != len(packet):
                    _fail("protocol_invalid")
                self._remaining()
                return
            except BlockingIOError:
                self._wait(sock, select.POLLOUT)

    def _receive(self, sock, operation, sequence, *, count=0, initial=False):
        while True:
            self._remaining()
            try:
                raw, ancillary, flags, _ = sock.recvmsg(_MESSAGE_SIZE + 1, socket.CMSG_SPACE(4 * array.array("i").itemsize),
                                                        socket.MSG_CMSG_CLOEXEC)
                break
            except BlockingIOError:
                self._wait(sock, select.POLLIN)
        acquired = []
        try:
            for level, kind, values in ancillary:
                if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS or len(values) % array.array("i").itemsize:
                    _fail("protocol_invalid")
                rights = array.array("i")
                rights.frombytes(values)
                acquired.extend(rights)
            if (len(raw) != _MESSAGE_SIZE or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC)
                    or len(acquired) != count or len(ancillary) != bool(count)
                    or _HEADER.unpack_from(raw) != (0x3151574C, 1, operation, sequence, count, 0)
                    or raw[24:24 + _BINDING.size] != self._binding
                    or any(raw[-3 * _PUBLICATION.size:])):
                _fail("protocol_invalid")
            offset = 24 + _BINDING.size
            scope, pid = raw[offset:offset + 40], struct.unpack_from("<Q", raw, offset + 40)[0]
            if initial:
                fields = _IDENTITY.unpack(scope)
                if not fields[1] or not fields[2] or fields[3] or not stat.S_ISDIR(fields[5]) or fields[6]:
                    _fail("protocol_invalid")
            elif scope != self._scope or pid != self._target_pid:
                _fail("protocol_invalid")
            self._remaining()
            owned = tuple(acquired)
            while acquired:
                fd = acquired.pop(0)
                self._own(fd)
            return scope, pid, owned
        finally:
            failure = None
            active = sys.exception()
            for fd in acquired:
                try:
                    os.close(fd)
                except OSError as exc:
                    failure = failure or exc
            if active is None and failure is not None:
                raise failure

    def _receive_custody_creators(self, publication_bytes):
        """Receive v3 only; inventory all delivered rights before refusing."""
        from .native_whole_scope_custody import CUSTODY_V3_PROFILE, NativeWholeScopeCustodyOwner

        child = self._custody_owner
        if (type(child) is not NativeWholeScopeCustodyOwner or child._scope is not self
                or child.profile != CUSTODY_V3_PROFILE):
            _fail("owner_invalid")
        while True:
            self._remaining()
            try:
                raw, ancillary, flags, _ = self._controller.recvmsg(
                    _MESSAGE_SIZE + 1, socket.CMSG_SPACE(4 * array.array("i").itemsize),
                    socket.MSG_CMSG_CLOEXEC,
                )
                break
            except BlockingIOError:
                self._wait(self._controller, select.POLLIN)
        acquired = []
        try:
            invalid, rights_headers = False, 0
            width = array.array("i").itemsize
            for level, kind, values in ancillary:
                if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                    invalid = True
                    continue
                rights_headers += 1
                usable = len(values) - len(values) % width
                rights = array.array("i")
                rights.frombytes(values[:usable])
                acquired.extend(rights)
                if usable != len(values):
                    invalid = True
            expected = (_HEADER.pack(0x3151574C, 3, 24, 2, 2, 0) + self._binding + self._scope
                        + struct.pack("<Q", self._target_pid) + publication_bytes)
            if (invalid or rights_headers != 1 or len(ancillary) != 1 or len(acquired) != 2
                    or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or raw != expected):
                _fail("protocol_invalid")
            self._remaining()
            descriptors = tuple(acquired)
            # The receiver retains these numeric FDs until finally. The child
            # retains same-OFD dup copies, with no ambiguous handoff window.
            NativeWholeScopeCustodyOwner._adopt_creator_descriptions(
                child, _TOKEN, self, descriptors, publication_bytes,
            )
        finally:
            active = sys.exception()
            failure = None
            for fd in acquired:
                try:
                    os.close(fd)
                except OSError as exc:
                    failure = failure or exc
            if active is None and failure is not None:
                raise failure

    @property
    def journal_id(self):
        if self._preparation_key is None:
            _fail("grants_unavailable")
        return "lunar-" + self._preparation_key

    @property
    def deadline_ns(self):
        if self._deadline is None:
            _fail("deadline_exceeded")
        return self._deadline

    @property
    def working_directory(self):
        return Path(self._profile["paths"][1]) / self.journal_id / "work"

    @property
    def output_directory(self):
        return Path(self._profile["paths"][1]) / self.journal_id / "output"

    def acquire_fixed_u_input_owner(self):
        """Opt into distinct-user inputs once, before input/intent freeze.

        This consumes this exact installed acquisition, not numeric credentials,
        a detached profile description or a recovered attempt.
        """
        from .native_fixed_u_inputs import _acquire_fixed_u_input_owner

        return _acquire_fixed_u_input_owner(self)

    def acquire_custody_owner(self, *, profile="linux-whole-scope-private-custody-v1"):
        """Reserve private R storage beneath this original attempt, once.

        This explicit selection grants only diagnostic persistence; it adds no
        native deadline, cleanup authority or candidate filesystem grant.
        """
        from .native_whole_scope_custody import _acquire_whole_scope_custody

        return _acquire_whole_scope_custody(self, profile=profile)

    @property
    def original_custody_owner(self):
        if self._custody_owner is not None:
            self._custody_owner._check(require_unexpired=False)
        return self._custody_owner

    @property
    def original_fixed_u_input_owner(self):
        from .native_fixed_u_inputs import checked_fixed_u_input_owner

        if self._fixed_u_input_owner is None:
            return None
        owner = checked_fixed_u_input_owner(self._fixed_u_input_owner, require_unexpired=False)
        if owner._scope is not self:
            _fail("owner_invalid")
        return owner

    def _check_published_grants(self):
        self._check_installation()
        if self._published is None or self._publication_pins is None:
            _fail("grants_unavailable")
        for index, (fd, (identity, acl)) in enumerate(zip(self._published, self._publication_pins, strict=True)):
            if _kernel_identity(fd) != identity or (acl is not None and os.getxattr(fd, "system.posix_acl_access") != acl):
                _fail("original_changed")
            parent, name = ((self._execution_fd, self.journal_id) if index == 0
                            else (self._published[0], "work" if index == 1 else "output"))
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (named.st_dev, named.st_ino, named.st_mode, named.st_uid, named.st_gid) != (
                    identity[0], identity[1], identity[5], identity[3], identity[4]):
                _fail("original_changed")

    def publish_original_grants(self, *, deadline_ns):
        """Create fixed native leaves before any intent/input identity freeze."""
        if self._published is not None or self._preparation_key is not None or self._channels_prepared:
            _fail("grants_unavailable")
        self._check_installation()
        self._deadline = deadline_ns
        self._preparation_key = secrets.token_hex(32)
        self._binding = self._core(launch=self._preparation_key, intent=self._preparation_key,
                                   target="0" * 64, deadline_ns=deadline_ns)
        parent, child = self._socket_pair()
        command = [f"/proc/self/fd/{self._image_fd}", "--publish-v1", "--profile-fd", str(self._profile_fd),
                   "--execution-root-fd", str(self._execution_fd), "--controller-fd", str(child.fileno()),
                   "--image-fd", str(self._image_fd), "--deadline-monotonic-ns", str(deadline_ns)]
        self._remaining()
        self._publisher = subprocess.Popen(command, executable=command[0], close_fds=True,
            pass_fds=(self._profile_fd, self._execution_fd, child.fileno(), self._image_fd),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd="/", env={"PATH": os.defpath, "LANG": "C"})
        child.close()
        self._send(parent, 17, 0, bound=False)
        scope, pid, fds = self._receive(parent, 18, 1, count=3, initial=True)
        if pid or len({_kernel_identity(fd)[:2] for fd in fds}) != 3:
            _fail("grants_unavailable")
        self._publisher.wait(timeout=self._remaining())
        self._remaining()
        if self._publisher.returncode != 0 or _IDENTITY.pack(*_kernel_identity(fds[0])) != scope:
            _fail("grants_unavailable")
        self._published = fds
        self._publication_pins = tuple((_kernel_identity(fd), os.getxattr(fd, "system.posix_acl_access")
                                      if i == 0 else None) for i, fd in enumerate(fds))
        self._binding = None
        return self.working_directory, self.output_directory

    def check_before_launch(self, intent, artifact, deadline_ns, *, working=None, output=None):
        from .native_bootstrap import NativeBootstrapArtifact
        from .producer_launcher import ProducerLaunchIntent

        self._check_installation()
        if (type(artifact) is not NativeBootstrapArtifact or type(intent) is not ProducerLaunchIntent
                or self._published is None or artifact.artifact_sha256 != self._profile["bootstrap_sha256"]
                or intent.journal_id != self.journal_id or intent.working_directory != "work"
                or intent.output_directory != "output"
                or type(deadline_ns) is not int or deadline_ns > self._deadline):
            _fail("grants_unavailable")
        digest = intent.intent_sha256 or intent.digest()
        if self._final_intent is not None and digest != self._final_intent:
            _fail("owner_invalid")
        self._final_intent = digest
        self._deadline = deadline_ns
        self._remaining()
        self._check_published_grants()
        if self._fixed_u_input_owner is not None:
            self.original_fixed_u_input_owner.check()
        if ((working is not None and Path(working) != self.working_directory)
                or (output is not None and Path(output) != self.output_directory)):
            _fail("grants_unavailable")

    def original_readonly_grant_requests(self):
        """Export only identities freshly checked against the installed held roots."""
        from .producer_grant_anchors import ProducerGrantIdentity, ProducerGrantRequest

        self._check_installation()
        requests = []
        for path, identity, fd in zip(self._profile["paths"][2:], self._profile["identities"][2:],
                                       self._readonly_fds, strict=True):
            if _kernel_identity(fd) != identity:
                _fail("original_changed")
            requests.append(ProducerGrantRequest(path, "readonly-directory",
                ProducerGrantIdentity(identity[0], identity[1], "directory")))
        return tuple(requests)

    def prepare_channels(self):
        if self._closed or self._channels_prepared or self._published is None:
            _fail("owner_invalid")
        self._channels_prepared = True
        self._controller, self._controller_child = self._socket_pair()
        self._enrollment, self._enrollment_child = self._socket_pair()
        self._lifecycle, self._lifecycle_child = self._socket_pair()

    @property
    def profile_fd(self):
        return self._profile_fd

    @property
    def enrollment_fd(self):
        return self._enrollment.fileno()

    @property
    def lifecycle_fd(self):
        return self._lifecycle.fileno()

    @property
    def bootstrap_pass_fds(self):
        return (self.profile_fd, self.enrollment_fd, self.lifecycle_fd)

    def start_original(self, *, process, launch, intent, controller_lifeline_fd, deadline_ns, bootstrap=None):
        from .producer_bootstrap import TrustedBootstrapLaunch
        from .producer_launcher import ProducerLaunchIntent

        if (self._supervisor is not None or not self._channels_prepared or type(process) is not _POPEN
                or type(launch) is not TrustedBootstrapLaunch or type(intent) is not ProducerLaunchIntent
                or process.returncode is not None or signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL
                or threading.active_count() != 1
                or os.listdir("/proc/self/task") != [str(os.getpid())]):
            _fail("original_wait_unavailable")
        self._check_installation()
        if deadline_ns != self._deadline or launch.intent_sha256 != self._final_intent:
            _fail("owner_invalid")
        self._binding = self._core(launch=launch.launch_sha256, intent=launch.intent_sha256,
                                   target=intent.executable_sha256, deadline_ns=deadline_ns)
        self._remaining()
        custody_fd = -1 if self._custody_owner is None else self._custody_owner._borrow_for_start()
        line = os.fstat(controller_lifeline_fd)
        if (not stat.S_ISFIFO(line.st_mode)
                or fcntl.fcntl(controller_lifeline_fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY):
            _fail("protocol_invalid")
        # No intervening poll/wait: the single-threaded default-SIGCHLD owner
        # keeps its exclusive unreaped B relationship through pidfd delivery.
        self._bootstrap = process
        bootstrap_pidfd = self._own(os.pidfd_open(process.pid, 0))
        selected_custody = None if self._custody_owner is None else self._custody_owner.profile
        mode = {"linux-whole-scope-private-custody-v2": "--supervisor-custody-v2",
                "linux-whole-scope-private-custody-v3": "--supervisor-custody-v3"}.get(
                    selected_custody, "--supervisor-v1")
        command = [f"/proc/self/fd/{self._image_fd}", mode, "--profile-fd", str(self._profile_fd),
            "--delegation-fd", str(self._delegation_fd), "--bootstrap-pidfd", str(bootstrap_pidfd),
            "--controller-fd", str(self._controller_child.fileno()), "--enrollment-fd", str(self._enrollment_child.fileno()),
            "--lifecycle-fd", str(self._lifecycle_child.fileno()), "--controller-lifeline-fd", str(controller_lifeline_fd),
            "--image-fd", str(self._image_fd), "--custody-dir-fd", str(custody_fd),
            "--deadline-monotonic-ns", str(deadline_ns)]
        inherited = (self._profile_fd, self._delegation_fd, bootstrap_pidfd, self._controller_child.fileno(),
                     self._enrollment_child.fileno(), self._lifecycle_child.fileno(), controller_lifeline_fd, self._image_fd)
        if custody_fd >= 0:
            inherited += (custody_fd,)
        self._supervisor = subprocess.Popen(command, executable=command[0], pass_fds=inherited,
            close_fds=True, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, cwd="/", env={"PATH": os.defpath, "LANG": "C"})
        for sock in (self._controller_child, self._enrollment_child, self._lifecycle_child, self._enrollment, self._lifecycle):
            sock.close()
        self._drop(bootstrap_pidfd)
        self._send(self._controller, 1, 0, bound=False)

    def wait_enrolled(self):
        if self._scope is not None or self._supervisor is None:
            _fail("owner_invalid")
        self._scope, self._target_pid, _ = self._receive(self._controller, 4, 1, initial=True)
        if not self._target_pid:
            _fail("protocol_invalid")

    def bind_original_registration(self, publications, context=None):
        from .native_original_publication import NativeOriginalPublications

        if type(publications) is not NativeOriginalPublications or self._registered:
            _fail("owner_invalid")
        if self._scope is None:
            self.wait_enrolled()
        self._check_installation()
        descriptors, pins = publications._borrow_for_native_transfer()
        raw = b"".join(_PUBLICATION.pack(device, inode, size, mtime, ctime, _digest(digest))
                       for digest, size, device, inode, mtime, ctime in pins)
        self._send(self._controller, 5, 1, fds=descriptors, publications=raw)
        if (self._custody_owner is not None
                and self._custody_owner.profile == "linux-whole-scope-private-custody-v3"):
            self._original_publications = publications
            self._receive_custody_creators(raw)
        else:
            self._receive(self._controller, 6, 2)
            self._original_publications = publications
            if self._custody_owner is not None:
                self._custody_owner._bind_registration(raw)
        self._registered = True
        if (self._custody_owner is not None
                and self._custody_owner.profile == "linux-whole-scope-private-custody-v3"):
            try:
                self._remaining()
            except BaseException:
                self._registered = False
                raise

    def release_original(self):
        if not self._registered or self._released:
            _fail("owner_invalid")
        self._check_installation()
        self._original_publications._borrow_for_native_transfer()
        if self._custody_owner is not None:
            self._custody_owner._check_registration()
        # This operation grants only S's half of the two-owner release gate.
        # B still requires the unchanged original host token and EOF.
        self._released = True
        self._send(self._controller, 7, 3)

    def finish(self):
        if self._finished:
            return
        if not self._released or self._supervisor is None or self._bootstrap.returncode is None:
            _fail("completion_unknown")
        self._receive(self._controller, 10, 4)
        self._supervisor.wait(timeout=self._remaining())
        self._remaining()
        self._check_installation()
        if self._supervisor.returncode != 0:
            _fail("completion_unknown")
        if self._custody_owner is not None:
            self._custody_owner._check_registration(terminal=True)
        self._finished = True

    def cleanup(self):
        """Close the private C channel; only the original S/G stop path acts."""
        if self._supervisor is None:
            return False
        self._controller.close()
        try:
            self._supervisor.wait(timeout=max(0, self._remaining()))
        except (NativeWholeScopeError, subprocess.TimeoutExpired, OSError):
            return False
        # Abnormal exit/reap is diagnostic, never positive scope completion.
        return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        failure = None
        if self._fixed_u_input_owner is not None:
            try:
                self._fixed_u_input_owner.close()
            except OSError as exc:
                failure = failure or exc
        if self._custody_owner is not None:
            try:
                self._custody_owner.close()
            except OSError as exc:
                failure = failure or exc
        for sock in self._sockets:
            try:
                sock.close()
            except OSError as exc:
                failure = failure or exc
        # Channel closure initiates each native owner's original finite path.
        # It does not establish emptiness or allow an additional wait budget.
        for process in (self._publisher, self._supervisor):
            if process is not None and process.returncode is None:
                try:
                    process.wait(timeout=self._remaining())
                    self._remaining()
                except (OSError, subprocess.TimeoutExpired, NativeWholeScopeError):
                    failure = failure or NativeWholeScopeError("retirement_unknown")
                except BaseException as exc:  # noqa: BLE001 - retire every original FD before re-raising.
                    failure = failure or exc
        descriptors, self._fds = self._fds, set()
        for fd in descriptors:
            try:
                os.close(fd)
            except OSError as exc:
                failure = failure or exc
        if failure is not None:
            raise failure


@contextmanager
def hold_fixed_whole_scope_installation(*, expected_profile_sha256, bootstrap, supervisor):
    """Acquire a fixed root-owned installation; never provision or fall back."""
    owner = NativeWholeScopeOwner(_TOKEN)
    try:
        owner._acquire(expected_profile_sha256, bootstrap, supervisor)
        yield owner
    finally:
        active = sys.exception()
        try:
            owner.close()
        except (OSError, NativeWholeScopeError):
            if active is None:
                raise
