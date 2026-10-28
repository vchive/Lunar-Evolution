"""Live creator descriptors retained by one original native operation.

This owner is deliberately separate from a publication's serializable identity
pin. Only the actual publisher may supply a newly created descriptor. Comparing
a current pathname never reacquires a missing creator descriptor.
"""
from __future__ import annotations

import hashlib
import os
import stat
import sys
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # pragma: no cover - the explicit native profile is Linux only.
    fcntl = None


class NativeOriginalPublicationError(ValueError):
    """A fixed refusal without original bytes or installation paths."""

    code = "native_original_publication_unavailable"


_TOKEN = object()
_ROLES = frozenset({"deadline", "registration", "handoff"})
_MAXIMUM = 64 * 1024


def _fail() -> None:
    raise NativeOriginalPublicationError(NativeOriginalPublicationError.code)


def _identity(info: os.stat_result) -> tuple[int, ...]:
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid()
            or not 0 < info.st_size <= _MAXIMUM):
        _fail()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_uid, info.st_gid, info.st_mode)


class _NativeOriginalPublicationSlot:
    __slots__ = ("_owner", "_role")

    def __init__(self, token: object, owner: NativeOriginalPublications, role: str) -> None:
        if token is not _TOKEN or role not in _ROLES:
            _fail()
        self._owner, self._role = owner, role

    def __copy__(self):
        _fail()

    def __deepcopy__(self, memo):
        _fail()

    def __reduce_ex__(self, protocol):
        _fail()

    def _capture_created(self, *, descriptor: int, parent: int, name: str, raw: bytes) -> None:
        self._owner._capture(_TOKEN, self, descriptor, parent, name, raw)


class NativeOriginalPublications:
    """Non-transferable FD ownership; no constructor accepts saved pins or FDs."""

    __slots__ = ("_closed", "_entries", "_slots")

    def __init__(self, token: object) -> None:
        if token is not _TOKEN:
            _fail()
        self._closed = False
        self._entries: dict[str, tuple] = {}
        self._slots = {role: _NativeOriginalPublicationSlot(_TOKEN, self, role) for role in _ROLES}

    def __copy__(self):
        _fail()

    def __deepcopy__(self, memo):
        _fail()

    def __reduce_ex__(self, protocol):
        _fail()

    def _slot(self, role: str) -> _NativeOriginalPublicationSlot:
        if self._closed or role not in _ROLES or role in self._entries:
            _fail()
        return self._slots[role]

    def _capture(self, token, slot, descriptor, parent, name, raw) -> None:
        if (token is not _TOKEN or self._closed
                or type(slot) is not _NativeOriginalPublicationSlot
                or self._slots.get(slot._role) is not slot or slot._role in self._entries
                or type(descriptor) is not int or descriptor <= 2
                or type(parent) is not int or parent <= 2
                or type(name) is not str or name in {"", ".", ".."} or "/" in name
                or type(raw) is not bytes or not 0 < len(raw) <= _MAXIMUM
                or fcntl is None):
            _fail()
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        if flags & os.O_ACCMODE != os.O_RDWR or flags & getattr(os, "O_PATH", 0):
            _fail()
        original = _identity(os.fstat(descriptor))
        if (_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != original
                or os.pread(descriptor, _MAXIMUM + 1, 0) != raw
                or _identity(os.fstat(descriptor)) != original):
            _fail()
        owned = owned_parent = -1
        try:
            # dup retains the actual creator's open file description. There is
            # intentionally no open(name), /proc/self/fd or pin reconstruction.
            owned = os.dup(descriptor)
            owned_parent = os.dup(parent)
            os.set_inheritable(owned, False)
            os.set_inheritable(owned_parent, False)
            parent_info = os.fstat(owned_parent)
            if not stat.S_ISDIR(parent_info.st_mode):
                _fail()
            parent_pin = (parent_info.st_dev, parent_info.st_ino, parent_info.st_uid,
                          parent_info.st_gid, parent_info.st_mode)
            entry = (owned, owned_parent, name, raw, original, parent_pin)
            self._check_entry(entry)
            self._entries[slot._role] = entry
            owned = owned_parent = -1
        finally:
            original_exception = sys.exception()
            active = None
            for fd in (owned_parent, owned):
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError as exc:
                        if active is None:
                            active = exc
            if active is not None and original_exception is None:
                raise active

    @staticmethod
    def _check_entry(entry) -> None:
        descriptor, parent, name, raw, original, parent_pin = entry
        current_parent = os.fstat(parent)
        if (current_parent.st_dev, current_parent.st_ino, current_parent.st_uid,
                current_parent.st_gid, current_parent.st_mode) != parent_pin:
            _fail()
        if (_identity(os.fstat(descriptor)) != original
                or _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != original
                or os.pread(descriptor, _MAXIMUM + 1, 0) != raw
                or _identity(os.fstat(descriptor)) != original):
            _fail()

    def _borrow_for_native_transfer(self) -> tuple[tuple[int, ...], tuple[tuple, ...]]:
        """Borrow exact originals while this same operation keeps their ownership."""
        if self._closed or set(self._entries) != _ROLES:
            _fail()
        descriptors, pins = [], []
        for role in ("registration", "handoff", "deadline"):
            entry = self._entries[role]
            self._check_entry(entry)
            descriptor, _, _, raw, identity, _ = entry
            descriptors.append(descriptor)
            pins.append((hashlib.sha256(raw).hexdigest(), identity[2],
                         identity[0], identity[1], identity[3], identity[4]))
        if len(set(descriptors)) != 3:
            _fail()
        return tuple(descriptors), tuple(pins)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        entries, self._entries = self._entries, {}
        failure = None
        for descriptor, parent, _, _, identity, parent_pin in entries.values():
            for fd, expected in ((descriptor, identity[:2]), (parent, parent_pin[:2])):
                try:
                    # Retire the number before close; an uncertain close never
                    # authorizes a retry against a possibly reused FD number.
                    current = os.fstat(fd)
                    if (current.st_dev, current.st_ino) != expected:
                        _fail()
                    os.close(fd)
                except BaseException as exc:  # noqa: BLE001 - retire every owned role once
                    if failure is None:
                        failure = exc
        if failure is not None:
            raise failure


def _validate_publication_slot(value: object, *, expected_role: str) -> _NativeOriginalPublicationSlot:
    if (type(value) is not _NativeOriginalPublicationSlot or value._owner._closed
            or expected_role not in _ROLES or value._role != expected_role
            or value._owner._slots.get(value._role) is not value
            or value._role in value._owner._entries):
        _fail()
    return value


@contextmanager
def hold_native_original_publications():
    """Retain only newly published originals until this operation's terminal path."""
    owner = NativeOriginalPublications(_TOKEN)
    try:
        yield owner
    except BaseException as primary:
        try:
            owner.close()
        except BaseException:  # noqa: BLE001 - preserve the operation's first failure
            # Ownership is retired even when close reports uncertainty. Preserve
            # the operation's first failure and never retry a retired FD number.
            primary.add_note("native_original_publication_cleanup_unknown")
        raise
    finally:
        if not owner._closed:
            owner.close()
