"""Opt-in Linux diagnostics for one reviewed finite, precreated write view.

This observes original inotify events and directory identities. The supplied
grant digest is a reference to separately reviewed original grants, not proof
that every writer capability or process is enclosed. This slice deliberately
has no accepted completion path: native writer enclosure and original writer
quiescence have not been connected. Target return, pipe EOF, public booleans
and arbitrary empty cgroups cannot supply that missing evidence.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import select
import stat
import struct
import sys
import threading
import time
from dataclasses import dataclass

FINITE_WRITE_VIEW_PROFILE = "finite-write-view-diagnostic-v1"
FINITE_WRITE_VIEW_SCHEMA = "lunar-static-python-finite-write-view-v1"
MAX_GRANTS_BYTES = 256 * 1024
MAX_DIRECTORIES = 512
MAX_SCAN_ENTRIES = 32768
MAX_EVENTS = 8192
MAX_CAPTURE_BYTES = 4 * 1024 * 1024
MAX_READ_BYTES = 64 * 1024

IN_MODIFY = 0x00000002
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_UNMOUNT = 0x00002000
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ONLYDIR = 0x01000000
IN_ISDIR = 0x40000000
_EVENT_MASK = (IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO
               | IN_CREATE | IN_DELETE | IN_DELETE_SELF | IN_MOVE_SELF | IN_UNMOUNT
               | IN_Q_OVERFLOW | IN_IGNORED)
_HEADER = struct.Struct("=iIII")
_CACHE_NAME = re.compile(rb"\.py[co](?:$|[.\-~])")


class PycacheMonitorError(ValueError):
    """A fixed diagnostic refusal, without source contents or ambient values."""


def _fail(reason: str) -> None:
    raise PycacheMonitorError("static_python_pycache_monitor_" + reason)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_key")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class ReviewedWriteRoot:
    grant_id: str
    path: str
    directories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewedFiniteWriteView:
    """Reviewed input references only, never original-grant authentication."""

    original_grants_sha256: str
    manifest_sha256: str
    roots: tuple[ReviewedWriteRoot, ...]


def parse_reviewed_write_view(
    raw: bytes, *, expected_sha256: str, original_grants_sha256: str,
) -> ReviewedFiniteWriteView:
    """Reject unknown capabilities and require the complete finite directory list.

    The caller must bind this manifest to independently checked original grants.
    Matching the two supplied digest references does not perform that check.
    """
    if (type(raw) is not bytes or not 0 < len(raw) <= MAX_GRANTS_BYTES
            or not _digest(expected_sha256) or hashlib.sha256(raw).hexdigest() != expected_sha256
            or not _digest(original_grants_sha256)):
        _fail("grant_pin")
    try:
        facts = json.loads(raw, object_pairs_hook=_pairs)
        if (type(facts) is not dict or set(facts) != {
            "schema", "original_grants_sha256", "unknown_write_capabilities", "roots",
        } or _canonical(facts) != raw or facts["schema"] != FINITE_WRITE_VIEW_SCHEMA
                or facts["original_grants_sha256"] != original_grants_sha256
                or facts["unknown_write_capabilities"] != []
                or type(facts["roots"]) is not list or not 0 < len(facts["roots"]) <= 64):
            _fail("grant_scope")
        roots = []
        for item in facts["roots"]:
            if type(item) is not dict or set(item) != {"grant_id", "path", "directories"}:
                _fail("grant_scope")
            grant, path, directories = item["grant_id"], item["path"], item["directories"]
            if (type(grant) is not str or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}", grant) is None
                    or type(path) is not str or not path.startswith("/") or path == "/"
                    or len(path) > 4096 or "\x00" in path or os.path.normpath(path) != path
                    or type(directories) is not list or not 0 < len(directories) <= MAX_DIRECTORIES
                    or any(type(relative) is not str for relative in directories)):
                _fail("grant_scope")
            if directories != sorted(set(directories)) or "." not in directories:
                _fail("grant_scope")
            for relative in directories:
                if relative != "." and (not relative or len(relative) > 4096
                                        or any(part in {"", ".", ".."} for part in relative.split("/"))
                                        or "\x00" in relative):
                    _fail("grant_scope")
                if relative != "." and "/" in relative and relative.rpartition("/")[0] not in directories:
                    _fail("grant_scope")
            roots.append(ReviewedWriteRoot(grant, path, tuple(directories)))
        if (len({root.grant_id for root in roots}) != len(roots)
                or [root.path for root in roots] != sorted({root.path for root in roots})
                or sum(len(root.directories) for root in roots) > MAX_DIRECTORIES):
            _fail("grant_scope")
        for index, root in enumerate(roots):
            if any(other.path.startswith(root.path + "/") for other in roots[index + 1:]):
                _fail("grant_scope")
        return ReviewedFiniteWriteView(original_grants_sha256, expected_sha256, tuple(roots))
    except PycacheMonitorError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        _fail("grant_scope")


def is_python_cache_name(name: bytes) -> bool:
    """Include CPython atomic ``.pyc.<id>`` and common cache temporary names."""
    return (type(name) is bytes
            and (name == b"__pycache__" or name.startswith(b"__pycache__.")
                 or _CACHE_NAME.search(name) is not None))


@dataclass(frozen=True, slots=True)
class InotifyEvent:
    watch_descriptor: int
    mask: int
    cookie: int
    name: bytes


def parse_inotify_events(raw: bytes) -> tuple[InotifyEvent, ...]:
    """Pure bounded decoder; a short or malformed original read is a coverage failure."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_READ_BYTES:
        _fail("event_frame")
    events = []
    offset = 0
    while offset < len(raw):
        if len(raw) - offset < _HEADER.size:
            _fail("event_frame")
        descriptor, mask, cookie, length = _HEADER.unpack_from(raw, offset)
        offset += _HEADER.size
        if (length > 4096 or length % 4 or length > len(raw) - offset
                or descriptor < -1 or descriptor == 0 or not mask & _EVENT_MASK
                or mask & ~(_EVENT_MASK | IN_ISDIR)):
            _fail("event_frame")
        padded = raw[offset:offset + length]
        offset += length
        name = padded.split(b"\0", 1)[0]
        if (length and (b"\0" not in padded or padded[len(name):].strip(b"\0"))
                or len(name) > 255 or b"/" in name or name in {b".", b".."}
                or descriptor == -1 and mask != IN_Q_OVERFLOW):
            _fail("event_frame")
        events.append(InotifyEvent(descriptor, mask, cookie, name))
    return tuple(events)


@dataclass(frozen=True, slots=True)
class DirectoryIdentity:
    grant_id: str
    relative_path: str
    path: str
    device: int
    inode: int
    mode: int
    nlink: int


@dataclass(frozen=True, slots=True)
class CapturedPycacheEvent:
    grant_id: str | None
    relative_directory: str | None
    event: InotifyEvent


@dataclass(frozen=True, slots=True)
class PycacheMonitorDiagnostic:
    original_grants_sha256: str
    manifest_sha256: str
    directories: tuple[DirectoryIdentity, ...]
    events: tuple[CapturedPycacheEvent, ...]
    failures: tuple[str, ...]
    capture_running: bool
    initial_scan_completed: bool
    terminal_scan_completed: bool
    all_watches_installed_before_initial_scan: bool
    original_grants_authenticated: bool = False
    writer_enclosure_verified: bool = False
    original_quiescence_observed: bool = False
    coverage_complete: bool = False
    strict_view_accepted: bool = False
    production_admission: bool = False


def _identity(descriptor: int, root: ReviewedWriteRoot, relative: str) -> DirectoryIdentity:
    value = os.fstat(descriptor)
    if not stat.S_ISDIR(value.st_mode):
        _fail("directory_type")
    path = root.path if relative == "." else root.path + "/" + relative
    return DirectoryIdentity(root.grant_id, relative, path, value.st_dev, value.st_ino,
                             value.st_mode, value.st_nlink)


def _remaining_ns(deadline: int) -> int:
    remaining = deadline - time.monotonic_ns()
    if remaining <= 0:
        _fail("deadline")
    return remaining


def _open_directory(path: str, deadline: int) -> int:
    """Open every original path component without following symlinks."""
    _remaining_ns(deadline)
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.split("/")[1:]:
            _remaining_ns(deadline)
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        _remaining_ns(deadline)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


class FinitePycacheMonitor:
    """Owned original descriptors and a bounded event reader; diagnostics only.

    Construct with ``arm_before_target`` and do not start the target until it
    returns. Every listed existing directory is watched before the initial scan.
    Newly created/moved directories invalidate coverage; watches never expand.
    ``finish`` stops this reader and preserves incomplete evidence. It cannot
    assert that original writers have stopped, even if all event queues are empty.
    """

    def __init__(self) -> None:
        _fail("use_arm_before_target")

    @classmethod
    def arm_before_target(
        cls, *, reviewed_grants_bytes: bytes, expected_grants_sha256: str,
        original_grants_sha256: str, deadline_monotonic_ns: int,
        diagnostic_profile: str | None = None,
    ) -> FinitePycacheMonitor:
        if type(diagnostic_profile) is not str or diagnostic_profile != FINITE_WRITE_VIEW_PROFILE:
            _fail("profile_disabled")
        view = parse_reviewed_write_view(
            reviewed_grants_bytes, expected_sha256=expected_grants_sha256,
            original_grants_sha256=original_grants_sha256,
        )
        if sys.platform != "linux":
            _fail("linux_inotify_unavailable")
        if (type(deadline_monotonic_ns) is not int
                or not time.monotonic_ns() < deadline_monotonic_ns < 2**64):
            _fail("deadline")
        instance = object.__new__(cls)
        instance._view = view
        instance._deadline = deadline_monotonic_ns
        instance._fd = -1
        instance._directories = []
        instance._watches = {}
        instance._events = []
        instance._failures = []
        instance._read_bytes = 0
        instance._data_lock = threading.Lock()
        instance._io_lock = threading.Lock()
        instance._stop = threading.Event()
        instance._started = threading.Event()
        instance._thread = None
        instance._initial_scan_completed = False
        instance._terminal_scan_completed = False
        instance._closed = False
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            init = libc.inotify_init1
            init.argtypes, init.restype = [ctypes.c_int], ctypes.c_int
            add = libc.inotify_add_watch
            add.argtypes, add.restype = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32], ctypes.c_int
            instance._fd = init(os.O_NONBLOCK | os.O_CLOEXEC)
            if instance._fd < 0:
                _fail("inotify_init")
            for root in view.roots:
                for relative in root.directories:
                    _remaining_ns(deadline_monotonic_ns)
                    path = root.path if relative == "." else root.path + "/" + relative
                    descriptor = _open_directory(path, deadline_monotonic_ns)
                    try:
                        identity = _identity(descriptor, root, relative)
                    except BaseException:
                        os.close(descriptor)
                        raise
                    instance._directories.append((descriptor, root, identity))
                    watch = add(instance._fd, f"/proc/self/fd/{descriptor}".encode("ascii"),
                                _EVENT_MASK | IN_ONLYDIR)
                    if watch <= 0 or watch in instance._watches:
                        _fail("watch_incomplete")
                    instance._watches[watch] = identity
                    _remaining_ns(deadline_monotonic_ns)
            instance._thread = threading.Thread(target=instance._reader, name="lunar-pycache-diagnostic", daemon=True)
            try:
                instance._thread.start()
            except (RuntimeError, OSError):
                instance._thread = None
                _fail("reader_start")
            remaining = _remaining_ns(deadline_monotonic_ns)
            if not instance._started.wait(min(1, remaining / 10**9)):
                _remaining_ns(deadline_monotonic_ns)
                _fail("reader_start")
            instance._initial_scan_completed = instance._scan()
            instance.drain()
            _remaining_ns(deadline_monotonic_ns)
            if instance._failures:
                _fail("initial_view_incomplete")
            return instance
        except (OSError, AttributeError):
            instance._release()
            _fail("directory_or_inotify_unavailable")
        except BaseException:
            instance._release()
            raise

    def _record_failure(self, reason: str) -> None:
        with self._data_lock:
            if reason not in self._failures:
                self._failures.append(reason)

    def _deadline_live(self) -> bool:
        if time.monotonic_ns() >= self._deadline:
            self._record_failure("capture_deadline_reached")
            self._stop.set()
            return False
        return True

    def _scan(self) -> bool:
        count = 0
        completed = True
        for descriptor, root, original in self._directories:
            if not self._deadline_live():
                return False
            try:
                current = _identity(descriptor, root, original.relative_path)
                path_stat = os.stat(original.path, follow_symlinks=False)
                if (current != original or not stat.S_ISDIR(path_stat.st_mode)
                        or (path_stat.st_dev, path_stat.st_ino, path_stat.st_mode, path_stat.st_nlink)
                        != (original.device, original.inode, original.mode, original.nlink)
                        or os.readlink(f"/proc/self/fd/{descriptor}") != original.path):
                    self._record_failure("directory_identity_changed")
                with os.scandir(descriptor) as entries:
                    for entry in entries:
                        if not self._deadline_live():
                            return False
                        count += 1
                        if count > MAX_SCAN_ENTRIES:
                            self._record_failure("scan_limit")
                            return False
                        name = os.fsencode(entry.name)
                        if is_python_cache_name(name):
                            self._record_failure("python_cache_observed")
                        value = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(value.st_mode):
                            self._record_failure("symlink_write_view_unknown")
                        elif stat.S_ISDIR(value.st_mode):
                            relative = entry.name if original.relative_path == "." else original.relative_path + "/" + entry.name
                            if relative not in root.directories:
                                self._record_failure("unwatched_directory")
                        elif not stat.S_ISREG(value.st_mode):
                            self._record_failure("special_write_view_unknown")
                        elif value.st_nlink != 1:
                            self._record_failure("hardlink_write_view_unknown")
            except OSError:
                self._record_failure("directory_scan_unavailable")
                completed = False
        return self._deadline_live() and completed

    def _consume(self, raw: bytes) -> None:
        self._read_bytes += len(raw)
        if self._read_bytes > MAX_CAPTURE_BYTES:
            self._record_failure("capture_byte_limit")
            self._stop.set()
            return
        try:
            events = parse_inotify_events(raw)
        except PycacheMonitorError:
            self._record_failure("event_frame_invalid")
            self._stop.set()
            return
        for event in events:
            identity = self._watches.get(event.watch_descriptor)
            if event.mask & IN_Q_OVERFLOW:
                self._record_failure("kernel_queue_overflow")
            elif identity is None:
                self._record_failure("unknown_watch")
            if event.mask & (IN_DELETE_SELF | IN_MOVE_SELF | IN_IGNORED | IN_UNMOUNT):
                self._record_failure("watch_coverage_lost")
            if event.mask & IN_ISDIR and event.mask & (IN_CREATE | IN_MOVED_TO | IN_MOVED_FROM | IN_DELETE):
                self._record_failure("directory_topology_changed")
            if event.mask & IN_ATTRIB and not event.name:
                self._record_failure("directory_attributes_changed")
            if is_python_cache_name(event.name):
                self._record_failure("python_cache_observed")
            with self._data_lock:
                if len(self._events) >= MAX_EVENTS:
                    if "event_limit" not in self._failures:
                        self._failures.append("event_limit")
                    self._stop.set()
                    return
                self._events.append(CapturedPycacheEvent(
                    identity.grant_id if identity else None,
                    identity.relative_path if identity else None, event,
                ))

    def drain(self) -> PycacheMonitorDiagnostic:
        """Read the current kernel queue; empty does not establish quiescence."""
        if self._closed:
            _fail("closed")
        with self._io_lock:
            # Finite per-call work even if another process floods the queue.
            for _ in range(MAX_CAPTURE_BYTES // MAX_READ_BYTES + 1):
                if not self._deadline_live():
                    break
                try:
                    raw = os.read(self._fd, MAX_READ_BYTES)
                except BlockingIOError:
                    break
                except OSError as error:
                    if error.errno == errno.EINTR:
                        continue
                    self._record_failure("event_read_unavailable")
                    self._stop.set()
                    break
                if not raw:
                    self._record_failure("event_reader_eof")
                    self._stop.set()
                    break
                self._consume(raw)
                self._deadline_live()
                if self._stop.is_set():
                    break
            else:
                self._record_failure("drain_limit")
                self._stop.set()
        return self.snapshot()

    def _reader(self) -> None:
        self._started.set()
        try:
            poller = select.poll()
            poller.register(self._fd, select.POLLIN | select.POLLERR | select.POLLHUP | select.POLLNVAL)
            while not self._stop.is_set():
                if not self._deadline_live():
                    break
                remaining = max(0, self._deadline - time.monotonic_ns())
                for _descriptor, mask in poller.poll(min(50, remaining // 10**6)):
                    if not self._deadline_live():
                        break
                    if mask & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                        self._record_failure("event_poll_unavailable")
                        self._stop.set()
                    if mask & select.POLLIN:
                        self.drain()
        except (OSError, RuntimeError, ValueError, OverflowError):
            self._record_failure("event_reader_failed")
        finally:
            self._stop.set()

    def snapshot(self) -> PycacheMonitorDiagnostic:
        with self._data_lock:
            return PycacheMonitorDiagnostic(
                self._view.original_grants_sha256, self._view.manifest_sha256,
                tuple(identity for _descriptor, _root, identity in self._directories),
                tuple(self._events), tuple(self._failures),
                not self._closed and not self._stop.is_set(), self._initial_scan_completed,
                self._terminal_scan_completed, len(self._watches) == len(self._directories),
            )

    def _release(self) -> None:
        self._stop.set()
        if self._thread is not None:
            # Resource cleanup only. This grace never renews the original
            # capture deadline or supplies validation/quiescence evidence.
            self._thread.join(timeout=1)
            if self._thread.is_alive():
                self._record_failure("reader_join_incomplete")
        # Serialize closing against an original drain already in progress.
        with self._io_lock:
            if self._fd >= 0:
                os.close(self._fd)
                self._fd = -1
            for descriptor, _root, _identity in self._directories:
                os.close(descriptor)
        self._closed = True

    def finish(self) -> PycacheMonitorDiagnostic:
        """Release only this capture; original writer quiescence is unavailable.

        No quiescence boolean, target exit status, EOF or caller DTO is accepted.
        There is intentionally no way to clear missing evidence in this slice.
        """
        if self._closed:
            return self.snapshot()
        self._record_failure("original_quiescence_unavailable")
        self.drain()
        self._terminal_scan_completed = self._scan()
        self.drain()
        self._release()
        return self.snapshot()
