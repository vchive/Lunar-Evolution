"""Original output descriptors to privately retained, kernel-sealed prior bytes.

One command owns one data-only frame. A successful output walk does not publish
it: the original caller commits only after its whole readback and lifetime
release succeed. Sealed frames protect the staging source; the fresh ordinary
destination directory is not an immutable filesystem for a later worker.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

# These are the executor's per-file/record and custody's whole-attempt limits.
# Keep this owner independent of the modules which import it during dispatch.
MAX_OUTPUT_BYTES = 128 * 1024**2
_MAX_BYTES = 8 * 1024**3
_MAX_FRAMES = 512
_MAX_RECORDS = 32768
_MAX_LEAF_HANDLES = 4096
_CHUNK = 65536
_SEAL_NAMES = ("F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class _SealedPriorError(ValueError):
    code = "podman_sealed_prior"


class _CleanupUnknown(_SealedPriorError):
    code = "podman_sealed_prior_cleanup_unknown"


def _refuse():
    raise _SealedPriorError(_SealedPriorError.code)


def _support():
    if (not sys.platform.startswith("linux")
            or any(not callable(getattr(os, name, None)) for name in ("memfd_create", "pread", "pwrite"))
            or any(not hasattr(os, name) for name in ("MFD_CLOEXEC", "MFD_ALLOW_SEALING"))
            or any(not hasattr(fcntl, name) for name in
                   ("F_ADD_SEALS", "F_GET_SEALS", "F_GETFD", "FD_CLOEXEC", *_SEAL_NAMES))):
        _refuse()
    return sum(getattr(fcntl, name) for name in _SEAL_NAMES)


def _identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _pin(info):
    return tuple(getattr(info, name) for name in (
        "st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"))


@dataclass(frozen=True, slots=True)
class _Record:
    path: str
    size: int
    sha256: str
    executable: bool


def _record(value):
    if (type(value) is not dict or set(value) != {"path", "size", "sha256", "executable"}
            or type(value["size"]) is not int or not 0 <= value["size"] <= MAX_OUTPUT_BYTES
            or type(value["executable"]) is not bool or type(value["sha256"]) is not str
            or _DIGEST.fullmatch(value["sha256"]) is None):
        _refuse()
    path = value["path"]
    if (type(path) is not str or not 0 < len(path) <= 512
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(char in path for char in "\\\x00:\n\r")
            or any(ord(char) < 32 or ord(char) > 126 for char in path)):
        _refuse()
    return _Record(path, value["size"], value["sha256"], value["executable"])


def _records(values, checkpoint):
    if type(values) is not list or len(values) > _MAX_RECORDS:
        _refuse()
    result = {}
    for value in values:
        checkpoint()
        record = _record(value)
        if record.path in result:
            _refuse()
        result[record.path] = record
    _paths(result, checkpoint)
    checkpoint()
    return result


def _paths(records, checkpoint):
    # A punctuation sibling can sort between a file and its invalid descendant;
    # compare actual parent components rather than only neighbouring strings.
    for path in records:
        checkpoint()
        parts = path.split("/")
        for index in range(1, len(parts)):
            checkpoint()
            if "/".join(parts[:index]) in records:
                _refuse()


@dataclass(slots=True)
class _Held:
    fd: int
    identity: tuple | None = None


def _take(descriptor):
    held = _Held(descriptor)
    try:
        held.identity = _identity(os.fstat(descriptor))
        return held
    except BaseException as primary:
        _release([held], primary)
        raise


def _release(holders, primary=None):
    """Remove authority before attempting each close; never retry numeric FDs."""
    unknown = False
    control = None
    for held in holders:
        descriptor, held.fd = held.fd, -1
        if descriptor < 0:
            continue
        try:
            current = _identity(os.fstat(descriptor))
            # Acquisition was private and never published if first fstat failed.
            if held.identity is None:
                held.identity = current
            if current != held.identity:
                unknown = True
                continue
            os.close(descriptor)
        except BaseException as error:  # noqa: BLE001 - release every owner before propagating control
            unknown = True
            if primary is None and control is None and not isinstance(error, Exception):
                control = error
    if unknown:
        if primary is not None:
            primary.add_note(_CleanupUnknown.code)
        elif control is not None:
            control.add_note(_CleanupUnknown.code)
            raise control
        else:
            raise _CleanupUnknown(_CleanupUnknown.code)


@dataclass(slots=True)
class _Frame:
    held: _Held
    size: int


@dataclass(frozen=True, slots=True)
class _Entry:
    record: _Record
    frame: _Frame
    offset: int


@dataclass(frozen=True, slots=True)
class _Leaf:
    record: _Record
    held: _Held


def _write(descriptor, block, offset, checkpoint):
    consumed = 0
    while consumed < len(block):
        checkpoint()
        written = os.pwrite(descriptor, block[consumed:], offset + consumed)
        checkpoint()
        if type(written) is not int or not 0 < written <= len(block) - consumed:
            _refuse()
        consumed += written


def _leaf_info(leaf, seals, checkpoint, *, borrowed=None, sealed=True):
    """Verify an owned leaf, or an exact borrowed alias without taking ownership."""
    checkpoint()
    descriptor = leaf.held.fd if borrowed is None else borrowed
    if (type(descriptor) is not int or descriptor < 0 or leaf.held.fd < 0
            or leaf.held.identity is None):
        _refuse()
    info = os.fstat(descriptor)
    checkpoint()
    row = leaf.record
    if (not stat.S_ISREG(info.st_mode) or _identity(info) != leaf.held.identity
            or info.st_nlink != 0 or info.st_size != row.size
            or stat.S_IMODE(info.st_mode) != (0o500 if row.executable else 0o400)):
        _refuse()
    if borrowed is None and not fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC:
        _refuse()
    actual = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
    checkpoint()
    if (sealed and actual & seals != seals) or (not sealed and actual != 0):
        _refuse()
    return info


def _verify_leaf_bytes(leaf, seals, checkpoint, *, borrowed=None):
    before = _leaf_info(leaf, seals, checkpoint, borrowed=borrowed)
    descriptor = leaf.held.fd if borrowed is None else borrowed
    digest, count = hashlib.sha256(), 0
    while count < leaf.record.size:
        checkpoint()
        block = os.pread(descriptor, min(_CHUNK, leaf.record.size - count), count)
        checkpoint()
        if not block or len(block) > leaf.record.size - count:
            _refuse()
        digest.update(block)
        count += len(block)
    checkpoint()
    if (os.pread(descriptor, 1, leaf.record.size) != b""
            or digest.hexdigest() != leaf.record.sha256
            or _pin(_leaf_info(leaf, seals, checkpoint, borrowed=borrowed)) != _pin(before)):
        _refuse()
    checkpoint()


class _SealedPriorLease:
    """Private owned export handles; mount strings are not detached authority.

    This object alone does not prove that an OCI runtime bound these objects or
    that the worker's directory namespace stayed fixed while consuming them.
    """

    def __init__(self, bank, leaves, holders, pid):
        self._bank, self._leaves, self._holders, self._pid = bank, leaves, holders, pid
        self._closed = False
        self._mounts = tuple((path, f"/proc/{pid}/fd/{leaf.held.fd}")
                             for path, leaf in sorted(leaves.items()))

    def _check(self):
        self._bank._check()
        if (self._closed or self._bank._export is not self or os.getpid() != self._pid
                or self._bank._pending is not None):
            _refuse()

    def mounts(self):
        self._check()
        for leaf in self._leaves.values():
            _verify_leaf_bytes(leaf, self._bank._seals, self._bank._checkpoint)
        self._check()
        return self._mounts

    def verify_leaf(self, path, borrowed_fd):
        self._check()
        if (type(path) is not str or path not in self._leaves
                or type(borrowed_fd) is not int or borrowed_fd < 0):
            _refuse()
        leaf = self._leaves[path]
        _verify_leaf_bytes(leaf, self._bank._seals, self._bank._checkpoint)
        _verify_leaf_bytes(leaf, self._bank._seals, self._bank._checkpoint, borrowed=borrowed_fd)
        self._check()

    def _detach(self):
        # Remove authority before release; the original holders carry all FDs.
        self._closed = True
        holders, self._holders = self._holders, None
        self._leaves = None
        self._mounts = ()
        if self._bank._export is self:
            self._bank._export = None
        return holders

    def close(self, primary=None):
        if not self._closed:
            _release(self._detach(), primary)


class _SealedPriorBatch:
    def __init__(self, bank, expected):
        self._bank = bank
        self._expected = expected
        self._entries = {}
        self._frame = None
        self._size = 0
        self._active = True
        self._failed = False

    def _check(self):
        self._bank._check()
        if (not self._active or self._failed or self._bank._pending is not self):
            _refuse()

    def capture(self, source_fd, record):
        try:
            self._check()
            row = _record(record)
            if (self._expected.get(row.path) != row or row.path in self._entries
                    or type(source_fd) is not int or source_fd < 0 or self._frame is None):
                _refuse()
            checkpoint = self._bank._checkpoint
            checkpoint()
            before = os.fstat(source_fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_size != row.size or bool(before.st_mode & 0o111) is not row.executable):
                _refuse()
            self._bank._frame_info(self._frame, sealed=False, expected_size=self._size)
            digest, count = hashlib.sha256(), 0
            while count < row.size:
                checkpoint()
                block = os.pread(source_fd, min(_CHUNK, row.size - count), count)
                checkpoint()
                if not block or len(block) > row.size - count:
                    _refuse()
                digest.update(block)
                _write(self._frame.held.fd, block, self._size + count, checkpoint)
                count += len(block)
            checkpoint()
            if (os.pread(source_fd, 1, row.size) != b"" or digest.hexdigest() != row.sha256
                    or _pin(os.fstat(source_fd)) != _pin(before)):
                _refuse()
            checkpoint()
            end = self._size + row.size
            self._bank._frame_info(self._frame, sealed=False, expected_size=end)
            self._entries[row.path] = _Entry(row, self._frame, self._size)
            self._size = end
        except BaseException:
            self._failed = True
            raise

    def commit(self):
        try:
            self._check()
            if set(self._entries) != set(self._expected):
                _refuse()
            bank = self._bank
            if self._frame is not None:
                if self._size != sum(row.size for row in self._expected.values()):
                    _refuse()
                bank._frame_info(self._frame, sealed=False, expected_size=self._size)
                bank._checkpoint()
                os.fchmod(self._frame.held.fd, 0o400)
                bank._checkpoint()
                fcntl.fcntl(self._frame.held.fd, fcntl.F_ADD_SEALS, bank._seals)
                bank._checkpoint()
                self._frame.size = self._size
                bank._frame_info(self._frame, sealed=True)
                for entry in self._entries.values():
                    bank._read_entry(entry, retain=False)
            bank._checkpoint()
            # Prepare successor collections first. No checkpoint or I/O occurs
            # between these assignments and authority removal from the batch.
            entries = {**bank._entries, **self._entries}
            frames = [*bank._frames, *([self._frame] if self._frame is not None else [])]
            total_bytes = bank._bytes + self._size
            empty_batch_entries = {}
            bank._entries, bank._frames, bank._bytes = entries, frames, total_bytes
            bank._pending = None
            self._active = False
            self._frame = None
            self._entries = empty_batch_entries
        except BaseException:
            self._failed = True
            raise

    def abort(self, primary=None):
        if not self._active:
            return
        self._active = False
        self._failed = True
        if self._bank._pending is self:
            self._bank._pending = None
        frame, self._frame = self._frame, None
        self._entries = {}
        if frame is not None:
            _release([frame.held], primary)


class _SealedPriorBank:
    def __init__(self, checkpoint, *, maximum_bytes=_MAX_BYTES, maximum_frames=_MAX_FRAMES):
        if (not callable(checkpoint) or type(maximum_bytes) is not int
                or not 0 < maximum_bytes <= _MAX_BYTES or type(maximum_frames) is not int
                or not 0 < maximum_frames <= _MAX_FRAMES):
            _refuse()
        self._seals = _support()
        self._checkpoint = checkpoint
        self._maximum_bytes = maximum_bytes
        self._maximum_frames = maximum_frames
        self._entries = {}
        self._frames = []
        self._pending = None
        self._export = None
        self._exporting = False
        self._bytes = 0
        self._closed = False

    def _check(self):
        if self._closed:
            _refuse()
        self._checkpoint()

    def begin(self, records):
        self._check()
        if self._pending is not None or self._export is not None or self._exporting:
            _refuse()
        expected = _records(records, self._checkpoint)
        if (set(expected) & set(self._entries) or len(expected) + len(self._entries) > _MAX_RECORDS
                or self._bytes + sum(row.size for row in expected.values()) > self._maximum_bytes
                or len(self._frames) + bool(expected) > self._maximum_frames):
            _refuse()
        _paths({**self._entries, **expected}, self._checkpoint)
        batch = _SealedPriorBatch(self, expected)
        self._pending = batch
        try:
            if expected:
                self._checkpoint()
                held = _take(os.memfd_create("lunar-prior-frame", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING))
                batch._frame = _Frame(held, 0)
                os.fchmod(held.fd, 0o400)
                self._frame_info(batch._frame, sealed=False, expected_size=0)
            self._checkpoint()
            return batch
        except BaseException as primary:
            batch.abort(primary)
            raise

    def _frame_info(self, frame, *, sealed, expected_size=None):
        self._checkpoint()
        if frame.held.fd < 0:
            _refuse()
        info = os.fstat(frame.held.fd)
        self._checkpoint()
        if (not stat.S_ISREG(info.st_mode) or _identity(info) != frame.held.identity
                or info.st_nlink != 0 or stat.S_IMODE(info.st_mode) != 0o400
                or info.st_size != (frame.size if expected_size is None else expected_size)
                or not fcntl.fcntl(frame.held.fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC):
            _refuse()
        actual = fcntl.fcntl(frame.held.fd, fcntl.F_GET_SEALS)
        self._checkpoint()
        if (sealed and actual & self._seals != self._seals) or (not sealed and actual != 0):
            _refuse()
        return info

    def _read_entry(self, entry, *, retain, destination=None):
        before = self._frame_info(entry.frame, sealed=True)
        row, chunks = entry.record, []
        digest, count = hashlib.sha256(), 0
        if entry.offset < 0 or entry.offset + row.size > entry.frame.size:
            _refuse()
        while count < row.size:
            self._checkpoint()
            block = os.pread(entry.frame.held.fd, min(_CHUNK, row.size - count), entry.offset + count)
            self._checkpoint()
            if not block or len(block) > row.size - count:
                _refuse()
            digest.update(block)
            if retain:
                chunks.append(block)
            if destination is not None:
                _write(destination, block, count, self._checkpoint)
            count += len(block)
        after = self._frame_info(entry.frame, sealed=True)
        if digest.hexdigest() != row.sha256 or _pin(before) != _pin(after):
            _refuse()
        self._checkpoint()
        return b"".join(chunks) if retain else None

    def read_record(self, record, *, maximum=MAX_OUTPUT_BYTES):
        self._check()
        if type(maximum) is not int or not 0 <= maximum <= MAX_OUTPUT_BYTES:
            _refuse()
        row = _record(record)
        entry = self._entries.get(row.path)
        if entry is None or entry.record != row or row.size > maximum:
            _refuse()
        return self._read_entry(entry, retain=True)

    def export_worker_prior(self, records):
        """Export every committed record into a separate command-lifetime memfd.

        The source frames contain concatenated files, so only these complete
        leaf objects can become file bind sources. No ordinary copy fallback is
        supplied. The original bank budget also bounds the extra live bytes.
        """
        self._check()
        if self._pending is not None or self._export is not None or self._exporting:
            _refuse()
        requested = _records(records, self._checkpoint)
        if (requested != {path: entry.record for path, entry in self._entries.items()}
                or len(requested) + len(self._frames) > _MAX_LEAF_HANDLES
                or self._bytes + sum(row.size for row in requested.values()) > self._maximum_bytes):
            _refuse()
        # Allocate every owner slot before any descriptor or acquiring flag.
        # Filling an existing slot cannot lose a fresh FD to list growth.
        leaves = {}
        holders = [_Held(-1) for _ in requested]
        ordered = sorted(requested.items())
        self._exporting = True
        try:
            pid = os.getpid()
            for (path, row), held in zip(ordered, holders, strict=True):
                self._check()
                held.fd = os.memfd_create("lunar-prior-leaf", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
                held.identity = _identity(os.fstat(held.fd))
                os.fchmod(held.fd, 0o400)
                self._read_entry(self._entries[path], retain=False, destination=held.fd)
                self._checkpoint()
                os.fchmod(held.fd, 0o500 if row.executable else 0o400)
                leaf = _Leaf(row, held)
                _leaf_info(leaf, self._seals, self._checkpoint, sealed=False)
                self._checkpoint()
                fcntl.fcntl(held.fd, fcntl.F_ADD_SEALS, self._seals)
                self._checkpoint()
                _verify_leaf_bytes(leaf, self._seals, self._checkpoint)
                leaves[path] = leaf
            # Build every returned collection before publishing ownership. A
            # control exception or allocation failure still releases this whole
            # private pending export rather than exposing a partial lease.
            lease = _SealedPriorLease(self, leaves, holders, pid)
            self._check()
            if (self._closed or self._pending is not None or self._export is not None
                    or not self._exporting or os.getpid() != pid):
                _refuse()
            self._export = lease
            self._exporting = False
            return lease
        except BaseException as primary:
            self._exporting = False
            _release(holders, primary)
            raise

    def snapshot(self, root: Path, records):
        self._check()
        requested = _records(records, self._checkpoint)
        if (self._pending is not None or requested != {path: entry.record for path, entry in self._entries.items()}
                or not isinstance(root, Path) or not root.is_absolute() or len(root.parts) < 2
                or any(part in {"", ".", ".."} for part in root.parts[1:])):
            _refuse()
        # Every directory is new or an original held ancestor. Sorted paths let
        # us retain only the current prefix rather than one FD per input file.
        holders, stack, names = [], [], []
        primary = None
        try:
            parent = _take(os.open(root.anchor, _DIRECTORY))
            holders.append(parent)
            for component in root.parts[1:-1]:
                self._checkpoint()
                child = _take(os.open(component, _DIRECTORY, dir_fd=parent.fd))
                holders.append(child)
                _release([parent])
                parent = child
            self._checkpoint()
            os.mkdir(root.name, mode=0o700, dir_fd=parent.fd)
            base = _take(os.open(root.name, _DIRECTORY, dir_fd=parent.fd))
            holders.append(base)
            stack.append(base)
            for path in sorted(requested):
                self._checkpoint()
                parts = path.split("/")
                directories = parts[:-1]
                common = 0
                while common < min(len(names), len(directories)) and names[common] == directories[common]:
                    common += 1
                while len(names) > common:
                    self._named(stack[-2], names[-1], stack[-1])
                    _release([stack.pop()])
                    names.pop()
                for name in directories[common:]:
                    self._checkpoint()
                    os.mkdir(name, mode=0o700, dir_fd=stack[-1].fd)
                    child = _take(os.open(name, _DIRECTORY, dir_fd=stack[-1].fd))
                    holders.append(child)
                    self._named(stack[-1], name, child)
                    names.append(name)
                    stack.append(child)
                self._checkpoint()
                target = _take(os.open(parts[-1], os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                                       | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=stack[-1].fd))
                holders.append(target)
                entry = self._entries[path]
                self._read_entry(entry, retain=False, destination=target.fd)
                os.fchmod(target.fd, 0o555 if entry.record.executable else 0o444)
                self._verify_destination(target, entry.record)
                self._named(stack[-1], parts[-1], target)
                _release([target])
            while len(stack) > 1:
                self._named(stack[-2], names[-1], stack[-1])
                _release([stack.pop()])
                names.pop()
            self._named(parent, root.name, base)
            self._checkpoint()
        except BaseException as error:
            primary = error
            raise
        finally:
            _release(reversed(holders), primary)

    def _named(self, parent, name, held):
        self._checkpoint()
        if (_identity(os.fstat(held.fd)) != held.identity
                or _identity(os.stat(name, dir_fd=parent.fd, follow_symlinks=False)) != held.identity):
            _refuse()
        self._checkpoint()

    def _verify_destination(self, target, row):
        before = os.fstat(target.fd)
        if (not stat.S_ISREG(before.st_mode) or _identity(before) != target.identity
                or before.st_nlink != 1 or before.st_size != row.size
                or stat.S_IMODE(before.st_mode) != (0o555 if row.executable else 0o444)):
            _refuse()
        digest, count = hashlib.sha256(), 0
        while count < row.size:
            self._checkpoint()
            block = os.pread(target.fd, min(_CHUNK, row.size - count), count)
            self._checkpoint()
            if not block or len(block) > row.size - count:
                _refuse()
            digest.update(block)
            count += len(block)
        if digest.hexdigest() != row.sha256 or _pin(os.fstat(target.fd)) != _pin(before):
            _refuse()

    def close(self, primary=None):
        if self._closed:
            return
        # Assemble the entire release vector before removing any owner. If an
        # allocation fails, the still-open bank retains every original handle.
        pending, export = self._pending, self._export
        holders = [frame.held for frame in self._frames]
        if pending is not None and pending._frame is not None:
            holders.append(pending._frame.held)
        if export is not None:
            holders.extend(export._holders)
        empty_entries, empty_frames, empty_pending_entries = {}, [], {}
        self._closed = True
        self._pending, self._export = None, None
        self._frames, self._entries = empty_frames, empty_entries
        self._bytes = 0
        if pending is not None:
            pending._active = False
            pending._failed = True
            pending._frame = None
            pending._entries = empty_pending_entries
        if export is not None:
            export._detach()
        _release(holders, primary)
