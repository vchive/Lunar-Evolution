"""Original v4 creator custody and bounded historical observations.

Only filesystem identity primitives are shared with the old custody module.
V4 references, filenames, record grammar and live owners are independent. A
retained record never reconstructs Q/S/G/R, an ACK, a wait or cleanup authority.
"""
from __future__ import annotations

import errno
import json
import os
import stat
from dataclasses import dataclass, field

from .native_whole_scope import NativeWholeScopeError, fcntl
from .native_whole_scope_custody import (
    _check_chain,
    _directory_identity,
    _file_pin,
    _json,
    _no_acl,
    _open_chain,
)

PROFILE_NAME = "linux-whole-scope-successor-custody-v4"
_DIRECTORY = ".whole-scope-successor-v4"
_NAMES = ("scope-registration-v4.bin", "scope-terminal-v4.bin")
_TOKEN = object()
_MAX_REFERENCE = 32768
_REASONS = ("normal", "controller_lost", "deadline", "receiver_fault", "protocol",
            "supervisor_lost", "guardian_lost", "controller_cancelled")


class NativeWholeScopeSuccessorCustodyError(NativeWholeScopeError):
    def __init__(self, reason="unavailable"):
        super().__init__("successor_custody_" + reason)


def _fail(reason="unavailable"):
    raise NativeWholeScopeSuccessorCustodyError(reason)


def _names(directory):
    names = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(names) == 2 or entry.name not in _NAMES:
                _fail("record_shape")
            names.append(entry.name)
    return tuple(sorted(names))


def _read_records(directory, creators=None, *, reserved=()):
    """Read originals with pread; live custody never reopens creator names."""
    from .native_whole_scope import _kernel_identity, _mount_id
    from .native_whole_scope_successor import COMMIT_SIZE, CONTEXT_SIZE

    parent = _directory_identity(directory)
    names = _names(directory)
    if names != _NAMES:
        _fail("record_shape")
    if creators is not None and (type(creators) is not tuple or len(creators) != 2
            or any(type(fd) is not int or fd <= 2 for fd in creators) or len(set(creators)) != 2):
        _fail("creators_invalid")
    excluded = set()
    for fd in reserved:
        info = os.fstat(fd)
        excluded.add((info.st_dev, info.st_ino))
    records, seen, held, flags = {}, set(), [], []
    try:
        for index, (name, bound) in enumerate(zip(_NAMES, (CONTEXT_SIZE, COMMIT_SIZE), strict=True)):
            if creators is None:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=directory)
                held.append(fd)
                original_flags = None
            else:
                fd = creators[index]
                original_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                # O_LARGEFILE is implicit on Linux even when Python exposes 0.
                allowed = os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_LARGEFILE", 0) | 0o100000
                if (original_flags & os.O_ACCMODE != os.O_RDWR or original_flags & ~allowed
                        or fcntl.fcntl(fd, fcntl.F_GETFD) != fcntl.FD_CLOEXEC):
                    _fail("creators_invalid")
            before = os.fstat(fd)
            identity = _kernel_identity(fd)
            if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_uid or before.st_gid or before.st_nlink != 1
                    or before.st_size not in (0, bound)
                    or identity[0] != parent[0] or identity[2] != parent[2]
                    or identity[:2] in seen or identity[:2] in excluded):
                _fail("record_invalid")
            seen.add(identity[:2])
            _no_acl(fd)
            raw = os.pread(fd, bound + 1, 0)
            named = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if (len(raw) != before.st_size or _file_pin(os.fstat(fd)) != _file_pin(before)
                    or _file_pin(named) != _file_pin(before) or _kernel_identity(fd) != identity
                    or _mount_id(directory, os.fsencode(name)) != identity[2]):
                _fail("record_changed")
            _no_acl(fd)
            records[name] = (raw, identity, _file_pin(before))
            flags.append((fd, original_flags))
        for name, (fd, original_flags) in zip(_NAMES, flags, strict=True):
            _raw, identity, pin = records[name]
            if (_file_pin(os.fstat(fd)) != pin
                    or _file_pin(os.stat(name, dir_fd=directory, follow_symlinks=False)) != pin
                    or _kernel_identity(fd) != identity
                    or _mount_id(directory, os.fsencode(name)) != identity[2]
                    or (original_flags is not None and (
                        fcntl.fcntl(fd, fcntl.F_GETFL) != original_flags
                        or fcntl.fcntl(fd, fcntl.F_GETFD) != fcntl.FD_CLOEXEC))):
                _fail("record_changed")
            _no_acl(fd)
        if _names(directory) != names or _directory_identity(directory) != parent:
            _fail("record_changed")
        return records
    finally:
        for fd in reversed(held):
            os.close(fd)


@dataclass(frozen=True, slots=True)
class NativeWholeScopeSuccessorCustodyReference:
    """Separately retained original baseline, without live capabilities.

    Serialization retains neither the creator OFDs nor authentication of the
    independent retention. Current valid files cannot establish this baseline.
    """

    canonical_bytes: bytes = field(repr=False)


class NativeWholeScopeSuccessorCustodyOwner:
    """One v4-only child of an explicitly selected original acquisition."""

    def __init__(self, token, scope):
        if token is not _TOKEN:
            _fail("owner_invalid")
        self._scope = scope
        self._closed = False
        self._directory = None
        self._chain = []
        self._identities = ()
        self._records = self._reference = self._binding = None
        self._creators = ()
        self._creator_delivery_started = self._started = False
        self._deadline = scope.deadline_ns
        self._origin = (scope._profile_sha256, scope.journal_id, scope._publication_pins[0][0])
        self._path = os.fspath(scope.working_directory.parent / _DIRECTORY)
        self._session = scope._successor_session

    @property
    def profile(self):
        return PROFILE_NAME

    def __copy__(self):
        _fail("owner_invalid")

    def __deepcopy__(self, memo):
        _fail("owner_invalid")

    def __reduce_ex__(self, protocol):
        _fail("owner_invalid")

    def _check(self, *, require_unexpired=True):
        from .native_whole_scope import NativeWholeScopeOwner
        from .native_whole_scope_successor import _SuccessorSession

        scope = self._scope
        if (self._closed or type(scope) is not NativeWholeScopeOwner or scope._custody_owner is not self
                or self._directory is None or getattr(scope, "_successor_session", None) is not self._session
                or type(self._session) is not _SuccessorSession or self._session.owner is not scope):
            _fail("owner_invalid")
        self._session.check()
        scope._check_published_grants()
        if require_unexpired:
            scope._remaining()
        if (scope.deadline_ns > self._deadline or self._origin != (
                scope._profile_sha256, scope.journal_id, scope._publication_pins[0][0])):
            _fail("original_changed")
        _check_chain(self._path, self._chain, self._identities)
        if self._binding is not None and self._binding != (scope._binding, scope._scope, scope._target_pid):
            _fail("original_changed")
        if self._records is not None and self._session.registration != self._records[_NAMES[0]][0]:
            _fail("original_changed")
        if require_unexpired:
            scope._remaining()

    def _acquire(self):
        scope = self._scope
        scope._check_published_grants()
        scope._remaining()
        os.mkdir(_DIRECTORY, mode=0o700, dir_fd=scope._published[0])
        self._directory = os.open(_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                  | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=scope._published[0])
        created = _directory_identity(self._directory)
        self._chain, self._identities = _open_chain(self._path)
        if self._identities[-1] != created or _names(self._directory):
            _fail("directory_changed")
        self._check()

    def _borrow_for_start(self):
        self._check()
        if self._started or self._reference is not None or _names(self._directory):
            _fail("owner_invalid")
        self._started = True
        return self._directory

    def _read_original_records(self):
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
        return _read_records(self._directory, self._creators, reserved=reserved)

    def _adopt_creator_descriptions(self, token, scope, descriptors, publication_bytes):
        from .native_whole_scope import _TOKEN as scope_token
        from .native_whole_scope_successor import context, validate_registration

        owned = []
        try:
            if (token is not scope_token or scope is not self._scope or not self._started
                    or self._reference is not None or self._creator_delivery_started):
                _fail("owner_invalid")
            self._check()
            # This attempt remains consumed even if a later dup or validation
            # fails. The receiver continues to own all incoming numeric FDs.
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
            self._binding = (scope._binding, scope._scope, scope._target_pid)
            expected = context(*self._binding, publication_bytes, 79, 1)
            validate_registration(expected)
            if self._session.registration != expected:
                _fail("registration_unknown")
            records = self._read_original_records()
            if records[_NAMES[0]][0] != expected or records[_NAMES[1]][0] != b"":
                _fail("registration_unknown")
            self._records = records
            reference = {"profile": PROFILE_NAME, "path": self._path,
                         "directory_chain": [list(pin) for pin in self._identities],
                         "registration": expected.hex(),
                         "record_identities": [list(records[name][1]) for name in _NAMES],
                         "registration_observed_pin": list(records[_NAMES[0]][2]),
                         "empty_terminal_observed_pin": list(records[_NAMES[1]][2])}
            self._check()
            self._reference = NativeWholeScopeSuccessorCustodyReference(_json(reference))
            _parse_reference(self._reference)
            scope._remaining()
        except BaseException:
            self._reference = self._records = None
            self._creators = ()
            for fd in owned:
                try:
                    os.close(fd)
                except OSError:
                    continue
            raise

    def _check_registration(self, *, terminal=False, commit=None):
        from .native_whole_scope_successor import validate_commit

        self._check()
        if self._records is None:
            _fail("registration_unknown")
        records = self._read_original_records()
        if (records[_NAMES[0]] != self._records[_NAMES[0]]
                or records[_NAMES[1]][1] != self._records[_NAMES[1]][1]
                or self._session.registration != self._records[_NAMES[0]][0]):
            _fail("record_changed")
        if not terminal:
            if commit is not None or records[_NAMES[1]] != self._records[_NAMES[1]]:
                _fail("record_changed")
        elif type(commit) is not bytes or commit != records[_NAMES[1]][0] or validate_commit(commit, self._records[_NAMES[0]][0])["decision"] != 1:
            _fail("terminal_unknown")
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


def _acquire_successor_custody(scope):
    from .native_whole_scope import NativeWholeScopeOwner
    from .native_whole_scope_successor import _SuccessorSession

    if (type(scope) is not NativeWholeScopeOwner or scope._closed or scope._published is None
            or scope._channels_prepared or scope._final_intent is not None or scope._custody_owner is not None
            or type(getattr(scope, "_successor_session", None)) is not _SuccessorSession
            or scope._successor_session.owner is not scope):
        _fail("owner_invalid")
    scope._successor_session.check()
    owner = NativeWholeScopeSuccessorCustodyOwner(_TOKEN, scope)
    scope._custody_owner = owner
    owner._acquire()
    return owner


def _parse_reference(reference):
    from .native_whole_scope import _text
    from .native_whole_scope_successor import CONTEXT_SIZE, validate_registration

    if (type(reference) is not NativeWholeScopeSuccessorCustodyReference
            or type(reference.canonical_bytes) is not bytes
            or not 0 < len(reference.canonical_bytes) <= _MAX_REFERENCE):
        _fail("reference_invalid")
    value = json.loads(reference.canonical_bytes)
    if (type(value) is not dict or set(value) != {
            "profile", "path", "directory_chain", "registration", "record_identities",
            "registration_observed_pin", "empty_terminal_observed_pin"}
            or _json(value) != reference.canonical_bytes or value["profile"] != PROFILE_NAME
            or type(value["path"]) is not str):
        _fail("reference_invalid")
    _text(os.fsencode(value["path"]) + b"\0")
    if value["path"].split("/")[-1] != _DIRECTORY:
        _fail("reference_invalid")
    chains, identities = value["directory_chain"], value["record_identities"]
    pins = (value["registration_observed_pin"], value["empty_terminal_observed_pin"])
    if (type(chains) is not list or len(chains) != len(value["path"][1:].split("/")) + 1
            or type(identities) is not list or len(identities) != 2
            or any(type(row) is not list or len(row) != 7 for row in (*chains, *identities))
            or any(type(pin) is not list or len(pin) != 9 for pin in pins)
            or any(type(item) is not int or not 0 <= item < 2**64
                   for row in (*chains, *identities, *pins) for item in row)
            or pins[1][6] != 0):
        _fail("reference_invalid")
    if type(value["registration"]) is not str or len(value["registration"]) != 2 * CONTEXT_SIZE:
        _fail("reference_invalid")
    raw = bytes.fromhex(value["registration"])
    if raw.hex() != value["registration"]:
        _fail("reference_invalid")
    validate_registration(raw)
    return value, raw


def inspect_native_whole_scope_successor_custody(reference):
    """Observe a retained v4 original read-only, also after original expiry.

    Bounds limit names, work and bytes, not syscall latency. No process lookup,
    signal, owner acquisition, ACK recovery, retry or new allowance occurs.
    """
    from .native_whole_scope_successor import validate_commit

    report = {"state": "unknown", "codes": ["native_whole_scope_successor_custody_unknown"],
              "registration_record_observed": False, "terminal_record_observed": False,
              "abnormal_record_observed": False, "recorded_reason": None,
              "recorded_source": None, "recorded_trigger": None,
              "recorded_stop_attempted": False, "recorded_scope_empty": False,
              "recorded_bootstrap_exit": False, "recorded_supervisor_wait": False,
              "recorded_guardian_wait": False, "recorded_target_exit": False,
              "durable_acknowledgement_verified": False, "cleanup_status": "unknown",
              "native_success": False, "whole_group_cleanup_verified": False,
              "original_quiescence_observed": False, "production_admission": False,
              "publication_authority": False, "online_publication": False}
    observed_keys = {key: report[key] for key in report if key.startswith("recorded_") or key in {
        "state", "codes", "registration_record_observed", "terminal_record_observed", "abnormal_record_observed"}}
    descriptors = []
    try:
        value, registration = _parse_reference(reference)
        baseline = reference.canonical_bytes
        descriptors, identities = _open_chain(value["path"])
        if [list(pin) for pin in identities] != value["directory_chain"]:
            _fail("directory_changed")
        before = _read_records(descriptors[-1])
        if ([list(before[name][1]) for name in _NAMES] != value["record_identities"]
                or list(before[_NAMES[0]][2]) != value["registration_observed_pin"]
                or before[_NAMES[0]][0] != registration):
            _fail("record_changed")
        terminal = before[_NAMES[1]][0]
        observation = validate_commit(terminal, registration) if terminal else None
        if not terminal and list(before[_NAMES[1]][2]) != value["empty_terminal_observed_pin"]:
            _fail("record_changed")
        _check_chain(value["path"], descriptors, identities)
        after = _read_records(descriptors[-1])
        _check_chain(value["path"], descriptors, identities)
        if reference.canonical_bytes != baseline or after != before:
            _fail("record_changed")
        observed = observation is not None
        abnormal = observed and observation["decision"] != 1
        facts = observation["facts"] if observed else 0
        report.update(state=("abnormal_record_observed" if abnormal else "terminal_record_observed")
                      if observed else "registration_prefix_observed", codes=[],
                      registration_record_observed=True, terminal_record_observed=observed,
                      abnormal_record_observed=bool(abnormal),
                      recorded_reason=_REASONS[observation["reason"]] if observed else None,
                      recorded_source=observation["source"] if observed else None,
                      recorded_trigger=observation["trigger"] if observed else None,
                      recorded_stop_attempted=bool(facts & 1), recorded_scope_empty=bool(facts & 2),
                      recorded_bootstrap_exit=bool(facts & 4), recorded_supervisor_wait=bool(facts & 8),
                      recorded_guardian_wait=bool(facts & 16), recorded_target_exit=bool(facts & 32))
    except Exception:  # noqa: BLE001 - missing/changed original evidence remains unknown
        report.update(observed_keys)
    finally:
        for fd in reversed(descriptors):
            try:
                os.close(fd)
            except OSError:
                report.update(observed_keys)
    return report
