"""Private original-directory custody and read-only whole-scope diagnostics.

The default receiver ABI is unchanged. Explicit v2 custody preserves finite
abnormal facts while the original supervisor survives; v3 also retains the
actual creator-delivered descriptions. No profile reconstructs a live scope,
proves a lost acknowledgement, or grants cleanup from historical records.
"""
from __future__ import annotations

import errno
import json
import os
import stat
import struct
from dataclasses import dataclass, field

from .native_whole_scope import NativeWholeScopeError, fcntl

CUSTODY_PROFILE = "linux-whole-scope-private-custody-v1"
CUSTODY_V2_PROFILE = "linux-whole-scope-private-custody-v2"
CUSTODY_V3_PROFILE = "linux-whole-scope-private-custody-v3"
_DIRECTORY = ".whole-scope-custody"
_NAMES = ("scope-registration-v1.bin", "scope-terminal-v1.bin")
_V2_DIRECTORY = ".whole-scope-custody-v2"
_V2_NAMES = ("scope-registration-v2.bin", "scope-terminal-v2.bin")
_V3_DIRECTORY = ".whole-scope-custody-v3"
_V3_NAMES = ("scope-registration-v3.bin", "scope-terminal-v3.bin")
_EVENT_FACTS = struct.Struct("<IIQ")
_REASONS = ("normal", "controller_lost", "deadline", "receiver_fault", "protocol")
_TOKEN = object()
_MAX_REFERENCE = 32768


class NativeWholeScopeCustodyError(NativeWholeScopeError):
    def __init__(self, reason="unavailable"):
        super().__init__("custody_" + reason)


def _fail(reason="unavailable"):
    raise NativeWholeScopeCustodyError(reason)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _profile_shape(profile):
    if type(profile) is not str:
        _fail("profile_invalid")
    if profile == CUSTODY_PROFILE:
        return _DIRECTORY, _NAMES
    if profile == CUSTODY_V2_PROFILE:
        return _V2_DIRECTORY, _V2_NAMES
    if profile == CUSTODY_V3_PROFILE:
        return _V3_DIRECTORY, _V3_NAMES
    _fail("profile_invalid")


def _terminal_observation(registration, raw, profile):
    """Validate a record against its retained original context, never an ACK."""
    from .native_whole_scope import _BINDING, _HEADER, _MESSAGE_SIZE

    _profile_shape(profile)
    if not raw:
        return None
    expected = bytearray(registration)
    if profile == CUSTODY_PROFILE:
        struct.pack_into("<II", expected, 8, 15, 2)
        if raw != bytes(expected):
            _fail("record_changed")
        return {"reason": "normal", "facts": 0}
    if len(raw) != _MESSAGE_SIZE + _EVENT_FACTS.size:
        _fail("record_changed")
    reason, facts, observed = _EVENT_FACTS.unpack_from(raw, _MESSAGE_SIZE)
    deadline = _BINDING.unpack_from(registration, _HEADER.size)[0]
    if (reason >= len(_REASONS) or facts & ~15 or not 0 < observed < deadline
            or (reason == 0 and facts != 10) or (reason != 0 and not facts & 1)):
        _fail("record_changed")
    version, operation = ((3, 25 if reason == 0 else 26) if profile == CUSTODY_V3_PROFILE
                          else (2, 19 if reason == 0 else 20))
    struct.pack_into("<III", expected, 4, version, operation, 2)
    if raw[:_MESSAGE_SIZE] != bytes(expected):
        _fail("record_changed")
    return {"reason": _REASONS[reason], "facts": facts}


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


def _names(directory, *, profile=CUSTODY_PROFILE):
    _directory, allowed = _profile_shape(profile)
    names = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(names) == 2 or entry.name not in allowed:
                _fail("record_shape")
            names.append(entry.name)
    return tuple(sorted(names))


def _read_records(directory, *, profile=CUSTODY_PROFILE):
    """Two fixed-size files; no inode from this read grants live ownership."""
    from .native_whole_scope import _MESSAGE_SIZE, _kernel_identity, _mount_id

    parent = _directory_identity(directory)
    _directory, allowed = _profile_shape(profile)
    names = _names(directory, profile=profile)
    records = {}
    for name in names:
        bound = _MESSAGE_SIZE + (_EVENT_FACTS.size if profile in (CUSTODY_V2_PROFILE, CUSTODY_V3_PROFILE)
                                 and name == allowed[1] else 0)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=directory)
        try:
            before = os.fstat(fd)
            identity = _kernel_identity(fd)
            if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_uid or before.st_gid or before.st_nlink != 1
                    or before.st_size not in (0, bound)
                    or identity[0] != parent[0] or identity[2] != parent[2]):
                _fail("record_invalid")
            _no_acl(fd)
            raw = os.pread(fd, bound + 1, 0)
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
    if _names(directory, profile=profile) != names or _directory_identity(directory) != parent:
        _fail("record_changed")
    return records


def _records_for(directory, profile):
    # Keep the default call boundary intact for existing v1 consumers/hooks.
    if profile == CUSTODY_PROFILE:
        return _read_records(directory)
    return _read_records(directory, profile=profile)


def _read_creator_records(directory, creators, *, reserved=()):
    """Read only the delivered original descriptions, without reopening names."""
    from .native_whole_scope import _MESSAGE_SIZE, _kernel_identity, _mount_id

    parent = _directory_identity(directory)
    if (type(creators) is not tuple or len(creators) != 2
            or any(type(fd) is not int or fd <= 2 for fd in creators)
            or len(set(creators)) != 2 or _names(directory, profile=CUSTODY_V3_PROFILE) != _V3_NAMES):
        _fail("creators_invalid")
    excluded = set()
    for fd in reserved:
        info = os.fstat(fd)
        excluded.add((info.st_dev, info.st_ino))
    records, seen, original_flags = {}, set(), []
    for index, (name, fd) in enumerate(zip(_V3_NAMES, creators, strict=True)):
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        # Linux exposes its implicit O_LARGEFILE bit even on a 64-bit Python
        # whose O_LARGEFILE constant is zero. No other mutable status is allowed.
        allowed = os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_LARGEFILE", 0) | 0o100000
        if (flags & os.O_ACCMODE != os.O_RDWR or flags & ~allowed
                or fcntl.fcntl(fd, fcntl.F_GETFD) != fcntl.FD_CLOEXEC):
            _fail("creators_invalid")
        before = os.fstat(fd)
        identity = _kernel_identity(fd)
        bound = _MESSAGE_SIZE + (index * _EVENT_FACTS.size)
        if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_uid or before.st_gid or before.st_nlink != 1
                or before.st_size not in (0, bound)
                or identity[0] != parent[0] or identity[2] != parent[2]
                or identity[:2] in seen or identity[:2] in excluded):
            _fail("creators_invalid")
        seen.add(identity[:2])
        _no_acl(fd)
        raw = os.pread(fd, bound + 1, 0)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (len(raw) != before.st_size or _file_pin(os.fstat(fd)) != _file_pin(before)
                or _file_pin(named) != _file_pin(before) or _kernel_identity(fd) != identity
                or _mount_id(directory, os.fsencode(name)) != identity[2]
                or fcntl.fcntl(fd, fcntl.F_GETFL) != flags
                or fcntl.fcntl(fd, fcntl.F_GETFD) != fcntl.FD_CLOEXEC):
            _fail("record_changed")
        _no_acl(fd)
        records[name] = (raw, identity, _file_pin(before))
        original_flags.append(flags)
    # The second read may overlap a change to the first description. Recheck
    # the complete pair against its original observations before returning it.
    for (name, fd), flags in zip(zip(_V3_NAMES, creators, strict=True), original_flags, strict=True):
        _raw, identity, pin = records[name]
        if (_file_pin(os.fstat(fd)) != pin
                or _file_pin(os.stat(name, dir_fd=directory, follow_symlinks=False)) != pin
                or _kernel_identity(fd) != identity
                or _mount_id(directory, os.fsencode(name)) != identity[2]
                or fcntl.fcntl(fd, fcntl.F_GETFL) != flags
                or fcntl.fcntl(fd, fcntl.F_GETFD) != fcntl.FD_CLOEXEC):
            _fail("record_changed")
        _no_acl(fd)
    if (_names(directory, profile=CUSTODY_V3_PROFILE) != _V3_NAMES
            or _directory_identity(directory) != parent):
        _fail("record_changed")
    return records


@dataclass(frozen=True, slots=True)
class NativeWholeScopeCustodyReference:
    """Trusted caller-retained diagnostic baseline; never a scope capability.

    The installation must independently retain these private original bytes.
    Current records cannot manufacture this reference or authenticate its origin.
    V1/v2 file pins are observations after original ACK. V3 derives its pins
    from the actual creator-delivered descriptions; serialization never retains
    those live descriptions or authenticates independent reference retention.
    """

    canonical_bytes: bytes = field(repr=False)


class NativeWholeScopeCustodyOwner:
    """One live child holding the original reserved private directory."""

    def __init__(self, token, scope, *, profile=CUSTODY_PROFILE):
        if token is not _TOKEN:
            _fail("owner_invalid")
        directory, _names_for_profile = _profile_shape(profile)
        self._scope = scope
        self._profile = profile
        self._original_profile = profile
        self._closed = False
        self._directory = None
        self._chain = []
        self._identities = ()
        self._reference = None
        self._records = None
        self._creators = ()
        self._creator_delivery_started = False
        self._binding = None
        self._started = False
        self._deadline = scope.deadline_ns
        self._origin = (scope._profile_sha256, scope.journal_id, scope._publication_pins[0][0])
        self._path = os.fspath(scope.working_directory.parent / directory)

    @property
    def profile(self):
        return self._profile

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
                or scope._custody_owner is not self or self._directory is None
                or self._profile != self._original_profile):
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
        if require_unexpired and self.profile == CUSTODY_V3_PROFILE:
            scope._remaining()

    def _acquire(self):
        scope = self._scope
        directory, _names_for_profile = _profile_shape(self.profile)
        scope._check_published_grants()
        scope._remaining()
        # Only this new root-private child is created; original U grants stay
        # unchanged and never contain this directory or its files.
        os.mkdir(directory, mode=0o700, dir_fd=scope._published[0])
        self._directory = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                  | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=scope._published[0])
        created = _directory_identity(self._directory)
        self._chain, self._identities = _open_chain(self._path)
        if self._identities[-1] != created or _names(self._directory, profile=self.profile):
            _fail("directory_changed")
        # The reserved directory and original owner remain failed after any
        # exception; they cannot be retried as a fresh custody attempt.
        self._check()

    def _borrow_for_start(self):
        self._check()
        if self._started or self._reference is not None or _names(self._directory, profile=self.profile):
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
        version, operation = (3, 22) if self.profile == CUSTODY_V3_PROFILE else (1, 14)
        expected = (_HEADER.pack(0x3151574C, version, operation, 1, 0, 0) + scope._binding + scope._scope
                    + struct.pack("<Q", scope._target_pid) + publication_bytes)
        _directory, names = _profile_shape(self.profile)
        records = self._read_original_records()
        if (set(records) != set(names) or records[names[0]][0] != expected
                or records[names[1]][0] != b""):
            _fail("registration_unknown")
        self._records = records
        reference = {
            "profile": self.profile, "path": self._path,
            "directory_chain": [list(pin) for pin in self._identities],
            "registration": expected.hex(),
            "record_identities": [list(records[name][1]) for name in names],
            "registration_observed_pin": list(records[names[0]][2]),
        }
        self._check()
        self._reference = NativeWholeScopeCustodyReference(_json(reference))
        if self.profile == CUSTODY_V3_PROFILE:
            scope._remaining()

    def _read_original_records(self):
        if self.profile != CUSTODY_V3_PROFILE:
            return _records_for(self._directory, self.profile)
        if not self._creator_delivery_started:
            _fail("creators_invalid")
        scope = self._scope
        reserved = [*scope._fds, *self._chain, self._directory]
        for fd in (0, 1, 2):
            try:
                os.fstat(fd)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise
            else:
                reserved.append(fd)
        reserved.extend(sock.fileno() for sock in scope._sockets if sock.fileno() >= 0)
        if scope._published is not None:
            reserved.extend(scope._published)
        publications = getattr(scope, "_original_publications", None)
        if publications is not None:
            descriptors, _pins = publications._borrow_for_native_transfer()
            reserved.extend(descriptors)
        inputs = scope._fixed_u_input_owner
        if inputs is not None:
            if inputs._directory is not None:
                reserved.append(inputs._directory)
            reserved.extend(record["fd"] for record in inputs._records.values())
        return _read_creator_records(self._directory, self._creators, reserved=reserved)

    def _adopt_creator_descriptions(self, token, scope, descriptors, publication_bytes):
        """Retain same-OFD duplicates from the original private receiver.

        The socket receiver owns the incoming numeric FDs through this call.
        This child owns only its duplicates, so even a call-entry interruption
        leaves the receiver able to retire every incoming FD without ambiguity.
        """
        from .native_whole_scope import _TOKEN as scope_token

        owned = []
        try:
            if (token is not scope_token or scope is not self._scope
                    or self.profile != CUSTODY_V3_PROFILE or self._creator_delivery_started):
                _fail("owner_invalid")
            self._creator_delivery_started = True
            if (type(descriptors) is not tuple or len(descriptors) != 2
                    or any(type(fd) is not int or fd <= 2 for fd in descriptors)
                    or len(set(descriptors)) != 2):
                _fail("creators_invalid")
            for fd in descriptors:
                duplicate = -1
                try:
                    duplicate = os.dup(fd)
                    owned.append(duplicate)
                    duplicate = -1
                finally:
                    if duplicate >= 0:
                        os.close(duplicate)
            self._creators = tuple(owned)
            self._bind_registration(publication_bytes)
        except BaseException:
            if owned:
                self._reference = self._records = None
                self._creators = ()
            # Preserve the primary validation/interrupt error while retiring
            # every child-owned duplicate, including partial adoption.
            for fd in owned:
                try:
                    os.close(fd)
                except OSError:
                    continue
            raise

    def _check_registration(self, *, terminal=False):
        self._check()
        if self._records is None:
            _fail("registration_unknown")
        _directory, names = _profile_shape(self.profile)
        records = self._read_original_records()
        if set(records) != set(names):
            _fail("record_changed")
        for name in names:
            if records[name][1] != self._records[name][1]:
                _fail("record_changed")
        if records[names[0]] != self._records[names[0]]:
            _fail("record_changed")
        if (self.profile == CUSTODY_V3_PROFILE and not terminal
                and records[names[1]] != self._records[names[1]]):
            _fail("record_changed")
        observation = _terminal_observation(self._records[names[0]][0], records[names[1]][0], self.profile)
        if (terminal and (observation is None or observation["reason"] != "normal")
                or not terminal and observation is not None):
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
        descriptors.extend(self._creators)
        self._creators = ()
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


def _acquire_whole_scope_custody(scope, *, profile=CUSTODY_PROFILE):
    from .native_whole_scope import NativeWholeScopeOwner

    _profile_shape(profile)
    if (type(scope) is not NativeWholeScopeOwner or scope._closed or scope._published is None
            or scope._successor_session is not None
            or scope._channels_prepared or scope._final_intent is not None or scope._custody_owner is not None):
        _fail("owner_invalid")
    owner = NativeWholeScopeCustodyOwner(_TOKEN, scope, profile=profile)
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
            or type(value["path"]) is not str):
        _fail("reference_invalid")
    directory, _names_for_profile = _profile_shape(value["profile"])
    _text(os.fsencode(value["path"]) + b"\0")
    if value["path"].split("/")[-1] != directory:
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
    version, operation = (3, 22) if value["profile"] == CUSTODY_V3_PROFILE else (1, 14)
    if (raw.hex() != value["registration"]
            or _HEADER.unpack_from(raw) != (0x3151574C, version, operation, 1, 0, 0)):
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
        "abnormal_record_observed": False, "recorded_reason": None,
        "recorded_stop_attempted": False, "recorded_scope_empty": False,
        "recorded_bootstrap_exit": False, "recorded_guardian_exact_reaped": False,
        "durable_acknowledgement_verified": False, "cleanup_status": "unknown",
        "native_success": False, "whole_group_cleanup_verified": False,
        "original_quiescence_observed": False, "production_admission": False,
        "publication_authority": False, "online_publication": False,
    }
    unknown_observations = {key: report[key] for key in (
        "state", "codes", "registration_record_observed", "terminal_record_observed",
        "abnormal_record_observed", "recorded_reason", "recorded_stop_attempted",
        "recorded_scope_empty", "recorded_bootstrap_exit", "recorded_guardian_exact_reaped",
    )}
    descriptors = []
    try:
        value, expected = _parse_reference(reference)
        profile = value["profile"]
        _directory, names = _profile_shape(profile)
        baseline = reference.canonical_bytes
        descriptors, identities = _open_chain(value["path"])
        if [list(pin) for pin in identities] != value["directory_chain"]:
            _fail("directory_changed")
        before = _records_for(descriptors[-1], profile)
        if set(before) != set(names):
            _fail("record_shape")
        if ([list(before[name][1]) for name in names] != value["record_identities"]
                or list(before[names[0]][2]) != value["registration_observed_pin"]
                or before[names[0]][0] != expected):
            _fail("record_changed")
        observation = _terminal_observation(expected, before[names[1]][0], profile)
        _check_chain(value["path"], descriptors, identities)
        if reference.canonical_bytes != baseline or _records_for(descriptors[-1], profile) != before:
            _fail("record_changed")
        observed = observation is not None
        abnormal = observed and observation["reason"] != "normal"
        facts = observation["facts"] if observed else 0
        report.update(state=("abnormal_record_observed" if abnormal else "terminal_record_observed")
                      if observed else "registration_prefix_observed", codes=[],
                      registration_record_observed=True, terminal_record_observed=observed,
                      abnormal_record_observed=abnormal,
                      recorded_reason=observation["reason"] if observed else None,
                      recorded_stop_attempted=bool(facts & 1), recorded_scope_empty=bool(facts & 2),
                      recorded_bootstrap_exit=bool(facts & 4), recorded_guardian_exact_reaped=bool(facts & 8))
    except Exception:  # noqa: BLE001 - malformed/partial private evidence always remains unknown.
        report.update(unknown_observations)
    finally:
        for fd in reversed(descriptors):
            try:
                os.close(fd)
            except OSError:
                report.update(unknown_observations)
    return report
