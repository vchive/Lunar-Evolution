"""Private original-directory custody and read-only whole-scope diagnostics.

The receiver's existing binary ABI is unchanged. A record can preserve a normal
terminal or an abnormal durable prefix, but cannot reconstruct a live scope,
prove a lost acknowledgement, or provide positive cleanup authority.
"""
from __future__ import annotations

import errno
import json
import os
import stat
import struct
from dataclasses import dataclass, field

from .native_whole_scope import NativeWholeScopeError

CUSTODY_PROFILE = "linux-whole-scope-private-custody-v1"
_DIRECTORY = ".whole-scope-custody"
_NAMES = ("scope-registration-v1.bin", "scope-terminal-v1.bin")
_TOKEN = object()
_MAX_REFERENCE = 32768


class NativeWholeScopeCustodyError(NativeWholeScopeError):
    def __init__(self, reason="unavailable"):
        super().__init__("custody_" + reason)


def _fail(reason="unavailable"):
    raise NativeWholeScopeCustodyError(reason)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _no_acl(fd):
    for name in ("system.posix_acl_access", "system.posix_acl_default"):
        try:
            os.getxattr(fd, name)
        except OSError as exc:
            if exc.errno == errno.ENODATA:
                continue
            raise
        _fail("directory_changed")


def _file_pin(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory_identity(fd):
    from .native_whole_scope import _kernel_identity

    identity = _kernel_identity(fd)
    if (identity[3] or identity[4] or not stat.S_ISDIR(identity[5])
            or stat.S_IMODE(identity[5]) != 0o700):
        _fail("directory_invalid")
    _no_acl(fd)
    return identity


def _open_chain(path):
    """Hold every no-follow ancestor; this never discovers an original binding."""
    from .native_whole_scope import _kernel_identity, _mount_id, _text

    _text(os.fsencode(path) + b"\0")
    descriptors, identities = [], []
    try:
        descriptors.append(os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC))
        for name in (None, *path[1:].split("/")):
            if name is not None:
                descriptors.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                           | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=descriptors[-1]))
            identity = _kernel_identity(descriptors[-1])
            if identity[3] or identity[5] & 0o022 or not stat.S_ISDIR(identity[5]):
                _fail("directory_invalid")
            if name is not None:
                named = os.stat(name, dir_fd=descriptors[-2], follow_symlinks=False)
                if ((named.st_dev, named.st_ino, _mount_id(descriptors[-2], os.fsencode(name)),
                     named.st_uid, named.st_gid, named.st_mode, 0) != identity):
                    _fail("directory_changed")
            identities.append(identity)
        _directory_identity(descriptors[-1])
        return descriptors, tuple(identities)
    except BaseException:
        for fd in reversed(descriptors):
            try:
                os.close(fd)
            except OSError:
                continue
        raise


def _check_chain(path, descriptors, identities):
    from .native_whole_scope import _kernel_identity, _mount_id

    for index, (fd, identity) in enumerate(zip(descriptors, identities, strict=True)):
        if _kernel_identity(fd) != identity:
            _fail("directory_changed")
        if index:
            name = path[1:].split("/")[index - 1]
            named = os.stat(name, dir_fd=descriptors[index - 1], follow_symlinks=False)
            if ((named.st_dev, named.st_ino, _mount_id(descriptors[index - 1], os.fsencode(name)),
                 named.st_uid, named.st_gid, named.st_mode, 0) != identity):
                _fail("directory_changed")
    _directory_identity(descriptors[-1])


def _names(directory):
    names = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(names) == 2 or entry.name not in _NAMES:
                _fail("record_shape")
            names.append(entry.name)
    return tuple(sorted(names))


def _read_records(directory):
    """At most two 925-byte files; no inode from this read grants live ownership."""
    from .native_whole_scope import _MESSAGE_SIZE, _kernel_identity, _mount_id

    parent = _directory_identity(directory)
    names = _names(directory)
    records = {}
    for name in names:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=directory)
        try:
            before = os.fstat(fd)
            identity = _kernel_identity(fd)
            if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_uid or before.st_gid or before.st_nlink != 1
                    or before.st_size not in (0, _MESSAGE_SIZE)
                    or identity[0] != parent[0] or identity[2] != parent[2]):
                _fail("record_invalid")
            _no_acl(fd)
            raw = os.pread(fd, _MESSAGE_SIZE + 1, 0)
            named = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if (len(raw) != before.st_size or _file_pin(os.fstat(fd)) != _file_pin(before)
                    or _file_pin(named) != _file_pin(before)
                    or _kernel_identity(fd) != identity
                    or _mount_id(directory, os.fsencode(name)) != identity[2]):
                _fail("record_changed")
            _no_acl(fd)
            records[name] = (raw, identity, _file_pin(before))
        finally:
            os.close(fd)
    if _names(directory) != names or _directory_identity(directory) != parent:
        _fail("record_changed")
    return records


@dataclass(frozen=True, slots=True)
class NativeWholeScopeCustodyReference:
    """Trusted caller-retained diagnostic baseline; never a scope capability.

    The installation must independently retain these private original bytes.
    Current records cannot manufacture this reference or authenticate its origin.
    File pins are observations after original ACK, not R's creator descriptions.
    """

    canonical_bytes: bytes = field(repr=False)


class NativeWholeScopeCustodyOwner:
    """One live child holding the original reserved private directory."""

    def __init__(self, token, scope):
        if token is not _TOKEN:
            _fail("owner_invalid")
        self._scope = scope
        self._closed = False
        self._directory = None
        self._chain = []
        self._identities = ()
        self._reference = None
        self._records = None
        self._binding = None
        self._started = False
        self._deadline = scope.deadline_ns
        self._origin = (scope._profile_sha256, scope.journal_id, scope._publication_pins[0][0])
        self._path = os.fspath(scope.working_directory.parent / _DIRECTORY)

    def __copy__(self):
        _fail("owner_invalid")

    def __deepcopy__(self, memo):
        _fail("owner_invalid")

    def __reduce_ex__(self, protocol):
        _fail("owner_invalid")

    def _check(self, *, require_unexpired=True):
        from .native_whole_scope import NativeWholeScopeOwner

        scope = self._scope
        if (self._closed or type(scope) is not NativeWholeScopeOwner
                or scope._custody_owner is not self or self._directory is None):
            _fail("owner_invalid")
        scope._check_published_grants()
        if require_unexpired:
            scope._remaining()
        if (scope.deadline_ns > self._deadline or self._origin != (
                scope._profile_sha256, scope.journal_id, scope._publication_pins[0][0])):
            _fail("original_changed")
        _check_chain(self._path, self._chain, self._identities)
        if self._binding is not None and self._binding != (scope._binding, scope._scope, scope._target_pid):
            _fail("original_changed")

    def _acquire(self):
        scope = self._scope
        scope._check_published_grants()
        scope._remaining()
        # Only this new root-private child is created; original U grants stay
        # unchanged and never contain this directory or its files.
        os.mkdir(_DIRECTORY, mode=0o700, dir_fd=scope._published[0])
        self._directory = os.open(_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                  | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=scope._published[0])
        created = _directory_identity(self._directory)
        self._chain, self._identities = _open_chain(self._path)
        if self._identities[-1] != created or _names(self._directory):
            _fail("directory_changed")
        # The reserved directory and original owner remain failed after any
        # exception; they cannot be retried as a fresh custody attempt.
        self._check()

    def _borrow_for_start(self):
        self._check()
        if self._started or self._reference is not None or _names(self._directory):
            _fail("owner_invalid")
        self._started = True
        return self._directory

    def _bind_registration(self, publication_bytes):
        from .native_whole_scope import _HEADER

        self._check()
        if not self._started or self._reference is not None:
            _fail("owner_invalid")
        scope = self._scope
        self._binding = (scope._binding, scope._scope, scope._target_pid)
        expected = (_HEADER.pack(0x3151574C, 1, 14, 1, 0, 0) + scope._binding + scope._scope
                    + struct.pack("<Q", scope._target_pid) + publication_bytes)
        records = _read_records(self._directory)
        if (set(records) != set(_NAMES) or records[_NAMES[0]][0] != expected
                or records[_NAMES[1]][0] != b""):
            _fail("registration_unknown")
        self._records = records
        reference = {
            "profile": CUSTODY_PROFILE, "path": self._path,
            "directory_chain": [list(pin) for pin in self._identities],
            "registration": expected.hex(),
            "record_identities": [list(records[name][1]) for name in _NAMES],
            "registration_observed_pin": list(records[_NAMES[0]][2]),
        }
        self._check()
        self._reference = NativeWholeScopeCustodyReference(_json(reference))

    def _check_registration(self, *, terminal=False):
        self._check()
        if self._records is None:
            _fail("registration_unknown")
        records = _read_records(self._directory)
        if set(records) != set(_NAMES):
            _fail("record_changed")
        for name in _NAMES:
            if records[name][1] != self._records[name][1]:
                _fail("record_changed")
        if records[_NAMES[0]] != self._records[_NAMES[0]]:
            _fail("record_changed")
        expected = bytearray(self._records[_NAMES[0]][0])
        struct.pack_into("<II", expected, 8, 15, 2)
        if records[_NAMES[1]][0] != (bytes(expected) if terminal else b""):
            _fail("terminal_unknown" if terminal else "record_changed")
        self._check()

    @property
    def reference(self):
        self._check(require_unexpired=False)
        if self._reference is None:
            _fail("registration_unknown")
        return self._reference

    def close(self):
        if self._closed:
            return
        self._closed = True
        descriptors, self._chain = self._chain, []
        if self._directory is not None:
            descriptors.append(self._directory)
            self._directory = None
        first = None
        for fd in reversed(descriptors):
            try:
                os.close(fd)
            except OSError as exc:
                first = first or exc
        if first is not None:
            raise first


def _acquire_whole_scope_custody(scope):
    from .native_whole_scope import NativeWholeScopeOwner

    if (type(scope) is not NativeWholeScopeOwner or scope._closed or scope._published is None
            or scope._channels_prepared or scope._final_intent is not None or scope._custody_owner is not None):
        _fail("owner_invalid")
    owner = NativeWholeScopeCustodyOwner(_TOKEN, scope)
    scope._custody_owner = owner
    owner._acquire()
    return owner


def _parse_reference(reference):
    from .native_whole_scope import _BINDING, _HEADER, _IDENTITY, _MESSAGE_SIZE, _PUBLICATION, _text

    if (type(reference) is not NativeWholeScopeCustodyReference or type(reference.canonical_bytes) is not bytes
            or not 0 < len(reference.canonical_bytes) <= _MAX_REFERENCE):
        _fail("reference_invalid")
    value = json.loads(reference.canonical_bytes)
    if (type(value) is not dict or set(value) != {
            "profile", "path", "directory_chain", "registration", "record_identities",
            "registration_observed_pin"} or _json(value) != reference.canonical_bytes
            or value["profile"] != CUSTODY_PROFILE or type(value["path"]) is not str):
        _fail("reference_invalid")
    _text(os.fsencode(value["path"]) + b"\0")
    if value["path"].split("/")[-1] != _DIRECTORY:
        _fail("reference_invalid")
    chains = value["directory_chain"]
    identities = value["record_identities"]
    pin = value["registration_observed_pin"]
    if (type(chains) is not list or len(chains) != len(value["path"][1:].split("/")) + 1
            or type(identities) is not list or len(identities) != 2
            or type(pin) is not list or len(pin) != 9
            or any(type(row) is not list or len(row) != 7 for row in (*chains, *identities))
            or any(type(item) is not int or not 0 <= item < 2**64
                   for row in (*chains, *identities, pin) for item in row)):
        _fail("reference_invalid")
    if type(value["registration"]) is not str or len(value["registration"]) != 2 * _MESSAGE_SIZE:
        _fail("reference_invalid")
    raw = bytes.fromhex(value["registration"])
    if raw.hex() != value["registration"] or _HEADER.unpack_from(raw) != (0x3151574C, 1, 14, 1, 0, 0):
        _fail("reference_invalid")
    binding = _BINDING.unpack_from(raw, _HEADER.size)
    groups = binding[10:]
    if (not 0 < binding[0] < 2**64 or any(len(digest) != 65 or digest[64:] != b"\0"
            or any(c not in b"0123456789abcdef" for c in digest[:64]) for digest in binding[1:7])
            or not 0 < binding[7] < 2**32 - 1 or not 0 < binding[8] < 2**32 - 1
            or not 0 <= binding[9] <= 32 or any(groups[binding[9]:])
            or tuple(sorted(set(groups[:binding[9]]))) != groups[:binding[9]]
            or any(not 0 < group < 2**32 - 1 for group in groups[:binding[9]])):
        _fail("reference_invalid")
    offset = _HEADER.size + _BINDING.size
    scope = _IDENTITY.unpack_from(raw, offset)
    if (not scope[1] or not scope[2] or scope[3] or not stat.S_ISDIR(scope[5])
            or scope[6] or not 0 < struct.unpack_from("<Q", raw, offset + _IDENTITY.size)[0] < 2**31):
        _fail("reference_invalid")
    for index in range(3):
        publication = _PUBLICATION.unpack_from(raw, _MESSAGE_SIZE - 3 * _PUBLICATION.size
                                                + index * _PUBLICATION.size)
        if (not publication[1] or not publication[2] or publication[5][-1:] != b"\0"
                or any(c not in b"0123456789abcdef" for c in publication[5][:64])):
            _fail("reference_invalid")
    return value, raw


def inspect_native_whole_scope_custody(reference):
    """Bounded read-only prefix inspection, including after the original expiry.

    Bounds cover names, bytes and work, not hard real-time filesystem latency.
    No new native execution, signal, scope acquisition, retry or allowance occurs.
    Missing records, partial bytes, drift and lost ACKs remain cleanup unknown.
    """
    report = {
        "state": "unknown", "codes": ["native_whole_scope_custody_unknown"],
        "registration_record_observed": False, "terminal_record_observed": False,
        "durable_acknowledgement_verified": False, "cleanup_status": "unknown",
        "native_success": False, "whole_group_cleanup_verified": False,
        "original_quiescence_observed": False, "production_admission": False,
        "publication_authority": False, "online_publication": False,
    }
    descriptors = []
    try:
        value, expected = _parse_reference(reference)
        baseline = reference.canonical_bytes
        descriptors, identities = _open_chain(value["path"])
        if [list(pin) for pin in identities] != value["directory_chain"]:
            _fail("directory_changed")
        before = _read_records(descriptors[-1])
        if set(before) != set(_NAMES):
            _fail("record_shape")
        if ([list(before[name][1]) for name in _NAMES] != value["record_identities"]
                or list(before[_NAMES[0]][2]) != value["registration_observed_pin"]
                or before[_NAMES[0]][0] != expected):
            _fail("record_changed")
        terminal = bytearray(expected)
        struct.pack_into("<II", terminal, 8, 15, 2)
        if before[_NAMES[1]][0] not in (b"", bytes(terminal)):
            _fail("record_changed")
        _check_chain(value["path"], descriptors, identities)
        if reference.canonical_bytes != baseline or _read_records(descriptors[-1]) != before:
            _fail("record_changed")
        observed = bool(before[_NAMES[1]][0])
        report.update(state="terminal_record_observed" if observed else "registration_prefix_observed",
                      codes=[], registration_record_observed=True, terminal_record_observed=observed)
    except Exception:  # noqa: BLE001 - malformed/partial private evidence always remains unknown.
        report.update(state="unknown", codes=["native_whole_scope_custody_unknown"],
                      registration_record_observed=False, terminal_record_observed=False)
    finally:
        for fd in reversed(descriptors):
            try:
                os.close(fd)
            except OSError:
                report.update(state="unknown", codes=["native_whole_scope_custody_unknown"],
                              registration_record_observed=False, terminal_record_observed=False)
    return report
