"""Controller-owned accounting for requests admitted through a producer broker.

The producer can supply only an opaque request ID. Admission and elapsed time are
measured by the controller. This ledger does not perform I/O, cancel a blocked
transport, or prove that a producer cannot bypass the broker. It is consequently
not a complete request-enforcement receipt on its own.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from .producer_request_evidence import MAX_REQUEST_EVENTS

_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_MAX_NS = 86_400 * 1_000_000_000
MAX_HOST_REQUEST_JOURNAL_BYTES = 16 * 1024 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ZERO_SHA = "0" * 64
_JOURNAL_PROTOCOL = "lunar-host-request-journal-v1"


class ProducerRequestTransportError(ValueError):
    """Fixed-code broker accounting failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ProducerRequestTransportError(code)


@dataclass(frozen=True, slots=True, eq=False)
class RequestAdmission:
    """Opaque controller-issued handle; possession does not establish I/O completion."""

    sequence: int
    request_id: str
    started_ns: int
    deadline_ns: int


@dataclass(frozen=True, slots=True)
class HostRequestEvent:
    sequence: int
    request_id: str
    status: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class HostRequestSnapshot:
    """A broker-local snapshot, never proof of complete producer egress coverage."""

    events: tuple[HostRequestEvent, ...]
    admitted_count: int
    active_count: int
    request_timeout_seconds: int
    max_requests: int
    coverage: str = "brokered_requests_only"
    clock_source: str = "controller_monotonic"

    @property
    def within_broker_limits(self) -> bool:
        return self.active_count == 0 and all(
            event.status != "timed_out" for event in self.events
        )


@dataclass(frozen=True, slots=True)
class HostRequestJournalIdentity:
    launch_id: str
    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    intent_sha256: str
    request_timeout_seconds: int
    max_requests: int
    wall_deadline_ns: int | None = None

    def __post_init__(self) -> None:
        for value in (
            self.launch_id, self.journal_id, self.run_id, self.parent_task_id, self.task_id,
        ):
            if type(value) is not str or _REQUEST_ID.fullmatch(value) is None:
                _fail("producer_request_transport_identity_invalid")
        if type(self.intent_sha256) is not str or _SHA.fullmatch(self.intent_sha256) is None:
            _fail("producer_request_transport_identity_invalid")
        if type(self.request_timeout_seconds) is not int or not 1 <= self.request_timeout_seconds <= 86_400:
            _fail("producer_request_transport_timeout_invalid")
        if type(self.max_requests) is not int or not 1 <= self.max_requests <= MAX_REQUEST_EVENTS:
            _fail("producer_request_transport_budget_invalid")
        if self.wall_deadline_ns is not None and (
            type(self.wall_deadline_ns) is not int or not 0 < self.wall_deadline_ns < 2**63
        ):
            _fail("producer_request_transport_deadline_invalid")

    def to_dict(self) -> dict[str, object]:
        value = {
            "launch_id": self.launch_id,
            "journal_id": self.journal_id,
            "run_id": self.run_id,
            "parent_task_id": self.parent_task_id,
            "task_id": self.task_id,
            "intent_sha256": self.intent_sha256,
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_requests": self.max_requests,
        }
        if self.wall_deadline_ns is not None:
            value["wall_deadline_ns"] = self.wall_deadline_ns
        return value


@dataclass(frozen=True, slots=True)
class HostRequestRecovery:
    """Read-only replay; active and timed-out requests remain uncertain."""

    snapshot: HostRequestSnapshot
    uncertain_request_ids: tuple[str, ...]


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ProducerRequestTransportError("producer_request_transport_journal_invalid") from exc


@contextmanager
def _parent_fd(path: Path):
    """Pin every ancestor without following a symbolic link."""
    parent = path.absolute().parent
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    opened: list[int] = []
    try:
        opened.append(os.open(parent.anchor, flags))
        for part in parent.parts[1:]:
            opened.append(os.open(part, flags, dir_fd=opened[-1]))
    except OSError as exc:
        for fd in reversed(opened):
            os.close(fd)
        raise ProducerRequestTransportError("producer_request_transport_journal_path_invalid") from exc
    try:
        yield opened[-1]
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _checked_file(fd: int) -> None:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.geteuid() or info.st_mode & 0o777 != 0o600):
        _fail("producer_request_transport_journal_path_invalid")


def _checked_parent(fd: int) -> None:
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o777 != 0o700):
        _fail("producer_request_transport_journal_path_invalid")


def _record_line(value: dict[str, object]) -> tuple[bytes, str]:
    digest = hashlib.sha256(_canonical(value)).hexdigest()
    line = _canonical({**value, "record_sha256": digest}) + b"\n"
    if len(line) > 2048:
        _fail("producer_request_transport_journal_invalid")
    return line, digest


class HostRequestJournal:
    """New, controller-owned, fsynced append-only journal for broker events.

    A failed write poisons the handle; replay must then decide whether a partial
    record exists. The path is never reopened for appending after a crash.
    """

    def __init__(self, fd: int, parent_fd: int, identity: HostRequestJournalIdentity,
                 initial_size: int, head: str) -> None:
        self._fd = fd
        self._parent_fd = parent_fd
        self.identity = identity
        self._size = initial_size
        self._head = head
        self._ordinal = 0
        self._poisoned = False
        self._claimed = False
        self._lock = threading.Lock()

    @classmethod
    def create(cls, path: str | Path, identity: HostRequestJournalIdentity) -> HostRequestJournal:
        if type(identity) is not HostRequestJournalIdentity:
            _fail("producer_request_transport_identity_invalid")
        target = Path(path).expanduser().absolute()
        if not _REQUEST_ID.fullmatch(target.name):
            _fail("producer_request_transport_journal_path_invalid")
        with _parent_fd(target) as parent:
            _checked_parent(parent)
            try:
                parent_copy = os.dup(parent)
            except OSError as exc:
                raise ProducerRequestTransportError("producer_request_transport_journal_path_invalid") from exc
            try:
                fd = os.open(
                    target.name,
                    os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=parent,
                )
            except OSError as exc:
                os.close(parent_copy)
                raise ProducerRequestTransportError("producer_request_transport_journal_path_invalid") from exc
            try:
                _checked_file(fd)
                header, head = _record_line({
                    "protocol": _JOURNAL_PROTOCOL,
                    "ordinal": 0,
                    "kind": "header",
                    "previous_sha256": _ZERO_SHA,
                    "identity": identity.to_dict(),
                })
                _write_all(fd, header)
                os.fsync(fd)
                os.fsync(parent)
            except Exception as exc:
                os.close(fd)
                os.close(parent_copy)
                if isinstance(exc, ProducerRequestTransportError):
                    raise
                raise ProducerRequestTransportError("producer_request_transport_journal_write_failed") from exc
        return cls(fd, parent_copy, identity, len(header), head)

    def close(self) -> None:
        with self._lock:
            if self._fd >= 0:
                os.close(self._fd)
                self._fd = -1
                os.close(self._parent_fd)
                self._parent_fd = -1

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def _append(self, kind: str, fields: dict[str, object]) -> None:
        with self._lock:
            self._append_locked(kind, fields)

    def _append_locked(self, kind: str, fields: dict[str, object]) -> None:
        if self._poisoned or self._fd < 0:
            _fail("producer_request_transport_journal_unavailable")
        record = {
            "protocol": _JOURNAL_PROTOCOL,
            "ordinal": self._ordinal + 1,
            "kind": kind,
            "previous_sha256": self._head,
            **fields,
        }
        line, head = _record_line(record)
        if self._size + len(line) > MAX_HOST_REQUEST_JOURNAL_BYTES:
            _fail("producer_request_transport_journal_too_large")
        try:
            _checked_parent(self._parent_fd)
            _checked_file(self._fd)
            _write_all(self._fd, line)
            os.fsync(self._fd)
        except ProducerRequestTransportError:
            self._poisoned = True
            raise
        except OSError as exc:
            self._poisoned = True
            raise ProducerRequestTransportError("producer_request_transport_journal_write_failed") from exc
        self._ordinal += 1
        self._size += len(line)
        self._head = head

    def record_admission(self, admission: RequestAdmission) -> None:
        self._append("admitted", {
            "sequence": admission.sequence,
            "request_id": admission.request_id,
            "started_ns": admission.started_ns,
            "deadline_ns": admission.deadline_ns,
        })

    def record_terminal(self, event: HostRequestEvent, ended_ns: int) -> None:
        self._append("terminal", {
            "sequence": event.sequence,
            "request_id": event.request_id,
            "status": event.status,
            "duration_ms": event.duration_ms,
            "ended_ns": ended_ns,
        })


def _write_all(fd: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short journal write")
        view = view[written:]


def _strict_pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in items:
        if key in value:
            _fail("producer_request_transport_journal_invalid")
        value[key] = item
    return value


def _journal_record(line: bytes, ordinal: int, head: str) -> dict[str, object]:
    try:
        value = json.loads(
            line.decode("ascii"), object_pairs_hook=_strict_pairs,
            parse_constant=lambda _: _fail("producer_request_transport_journal_invalid"),
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProducerRequestTransportError("producer_request_transport_journal_invalid") from exc
    if type(value) is not dict:
        _fail("producer_request_transport_journal_invalid")
    digest = value.get("record_sha256")
    if type(digest) is not str or _SHA.fullmatch(digest) is None:
        _fail("producer_request_transport_journal_invalid")
    payload = dict(value)
    del payload["record_sha256"]
    expected_line, expected_digest = _record_line(payload)
    if line != expected_line or digest != expected_digest:
        _fail("producer_request_transport_journal_invalid")
    if (value.get("protocol") != _JOURNAL_PROTOCOL
            or type(value.get("ordinal")) is not int or value["ordinal"] != ordinal
            or value.get("previous_sha256") != head):
        _fail("producer_request_transport_journal_invalid")
    return value


def read_host_request_journal(
    path: str | Path, *, expected_identity: HostRequestJournalIdentity,
) -> HostRequestRecovery:
    """Read a closed journal without changing it or resuming uncertain requests."""
    if type(expected_identity) is not HostRequestJournalIdentity:
        _fail("producer_request_transport_identity_invalid")
    target = Path(path).expanduser().absolute()
    if not _REQUEST_ID.fullmatch(target.name):
        _fail("producer_request_transport_journal_path_invalid")
    with _parent_fd(target) as parent:
        _checked_parent(parent)
        try:
            fd = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        except OSError as exc:
            raise ProducerRequestTransportError("producer_request_transport_journal_path_invalid") from exc
        try:
            _checked_file(fd)
            size = os.fstat(fd).st_size
            if size <= 0 or size > MAX_HOST_REQUEST_JOURNAL_BYTES:
                _fail("producer_request_transport_journal_too_large")
            chunks: list[bytes] = []
            remaining = size
            while remaining:
                chunk = os.read(fd, min(remaining, 64 * 1024))
                if not chunk:
                    _fail("producer_request_transport_journal_invalid")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.fstat(fd).st_size != size:
                _fail("producer_request_transport_journal_invalid")
        except OSError as exc:
            raise ProducerRequestTransportError("producer_request_transport_journal_read_failed") from exc
        finally:
            os.close(fd)
    data = b"".join(chunks)
    if not data.endswith(b"\n"):
        _fail("producer_request_transport_journal_invalid")
    lines = data.splitlines(keepends=True)
    if len(lines) > 1 + 2 * expected_identity.max_requests:
        _fail("producer_request_transport_journal_invalid")
    head = _ZERO_SHA
    active: dict[int, tuple[str, int, int]] = {}
    used_ids: set[str] = set()
    events: dict[int, HostRequestEvent] = {}
    admitted = 0
    last_timestamp = -1
    for ordinal, line in enumerate(lines):
        record = _journal_record(line, ordinal, head)
        head = record["record_sha256"]
        kind = record.get("kind")
        if ordinal == 0:
            fields = {"protocol", "ordinal", "kind", "previous_sha256", "identity", "record_sha256"}
            identity = record.get("identity")
            expected = expected_identity.to_dict()
            if (kind != "header" or set(record) != fields or type(identity) is not dict
                    or set(identity) != set(expected)
                    or any(type(identity[key]) is not type(value) or identity[key] != value
                           for key, value in expected.items())):
                _fail("producer_request_transport_journal_binding_mismatch")
            continue
        if kind == "admitted":
            fields = {"protocol", "ordinal", "kind", "previous_sha256", "record_sha256",
                      "sequence", "request_id", "started_ns", "deadline_ns"}
            sequence = record.get("sequence")
            request_id = record.get("request_id")
            started = record.get("started_ns")
            deadline = record.get("deadline_ns")
            if (set(record) != fields or type(sequence) is not int or sequence != admitted + 1
                    or sequence > expected_identity.max_requests
                    or type(request_id) is not str or _REQUEST_ID.fullmatch(request_id) is None
                    or request_id in used_ids or type(started) is not int
                    or not last_timestamp <= started <= (2**63 - 1) - _MAX_NS
                    or type(deadline) is not int
                    or deadline != min(
                        started + expected_identity.request_timeout_seconds * 1_000_000_000,
                        expected_identity.wall_deadline_ns or 2**63 - 1,
                    ) or deadline <= started):
                _fail("producer_request_transport_journal_invalid")
            admitted += 1
            used_ids.add(request_id)
            active[sequence] = (request_id, started, deadline)
            last_timestamp = started
        elif kind == "terminal":
            fields = {"protocol", "ordinal", "kind", "previous_sha256", "record_sha256",
                      "sequence", "request_id", "status", "duration_ms", "ended_ns"}
            sequence = record.get("sequence")
            ended = record.get("ended_ns")
            if (set(record) != fields or type(sequence) is not int or sequence not in active
                    or type(ended) is not int or not last_timestamp <= ended <= 2**63 - 1):
                _fail("producer_request_transport_journal_invalid")
            request_id, started, deadline = active.pop(sequence)
            status = record.get("status")
            duration_ms = record.get("duration_ms")
            if (record.get("request_id") != request_id
                    or type(status) is not str or status not in _TERMINAL | {"timed_out"}
                    or (status == "timed_out") != (ended >= deadline)
                    or type(duration_ms) is not int
                    or duration_ms != (ended - started + 999_999) // 1_000_000):
                _fail("producer_request_transport_journal_invalid")
            events[sequence] = HostRequestEvent(sequence, request_id, status, duration_ms)
            last_timestamp = ended
        else:
            _fail("producer_request_transport_journal_invalid")
    uncertain = {sequence: request_id for sequence, (request_id, _, _) in active.items()}
    uncertain.update(
        (sequence, event.request_id)
        for sequence, event in events.items() if event.status == "timed_out"
    )
    return HostRequestRecovery(
        snapshot=HostRequestSnapshot(
            events=tuple(events[key] for key in sorted(events)),
            admitted_count=admitted,
            active_count=len(active),
            request_timeout_seconds=expected_identity.request_timeout_seconds,
            max_requests=expected_identity.max_requests,
        ),
        uncertain_request_ids=tuple(uncertain[key] for key in sorted(uncertain)),
    )


class HostRequestLedger:
    """Count and time requests at a controller-owned broker entry point.

    The caller must run all permitted provider traffic through this entry point,
    apply ``deadline_ns`` to its actual I/O, and cancel that I/O on timeout.
    This class alone cannot enforce those transport or egress requirements.
    """

    def __init__(
        self,
        *,
        request_timeout_seconds: int,
        max_requests: int,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        journal: HostRequestJournal | None = None,
    ) -> None:
        if type(request_timeout_seconds) is not int or not 1 <= request_timeout_seconds <= 86_400:
            _fail("producer_request_transport_timeout_invalid")
        if type(max_requests) is not int or not 1 <= max_requests <= MAX_REQUEST_EVENTS:
            _fail("producer_request_transport_budget_invalid")
        if journal is not None and (
            type(journal) is not HostRequestJournal
            or journal.identity.request_timeout_seconds != request_timeout_seconds
            or journal.identity.max_requests != max_requests
        ):
            _fail("producer_request_transport_journal_binding_mismatch")
        if journal is not None:
            with journal._lock:
                if journal._claimed or journal._poisoned or journal._fd < 0:
                    _fail("producer_request_transport_journal_unavailable")
                journal._claimed = True
        self.request_timeout_seconds = request_timeout_seconds
        self.max_requests = max_requests
        self._lock = threading.Lock()
        self._clock = monotonic_ns
        self._last_ns: int | None = None
        self._journal = journal
        self._wall_deadline_ns = journal.identity.wall_deadline_ns if journal else None
        self._used_ids: set[str] = set()
        self._active: dict[RequestAdmission, None] = {}
        self._events: dict[int, HostRequestEvent] = {}
        self._admitted = 0

    def _now(self) -> int:
        try:
            value = self._clock()
        except Exception as exc:
            raise ProducerRequestTransportError("producer_request_transport_clock_invalid") from exc
        if (type(value) is not int or not 0 <= value <= 2**63 - 1
                or (self._last_ns is not None and value < self._last_ns)):
            _fail("producer_request_transport_clock_invalid")
        self._last_ns = value
        return value

    def admit(self, request_id: str) -> RequestAdmission:
        """Reserve capacity before the caller starts any provider I/O."""
        with self._lock:
            return self._admit_locked(request_id)

    def _admit_locked(self, request_id: str) -> RequestAdmission:
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            _fail("producer_request_transport_request_id_invalid")
        if request_id in self._used_ids:
            _fail("producer_request_transport_request_id_duplicate")
        if self._admitted >= self.max_requests:
            _fail("producer_request_transport_budget_exceeded")
        started = self._now()
        if self._wall_deadline_ns is not None and started >= self._wall_deadline_ns:
            _fail("producer_request_transport_wall_timeout")
        if started > (2**63 - 1) - _MAX_NS:
            _fail("producer_request_transport_clock_invalid")
        admission = RequestAdmission(
            sequence=self._admitted + 1,
            request_id=request_id,
            started_ns=started,
            deadline_ns=min(started + self.request_timeout_seconds * 1_000_000_000,
                            self._wall_deadline_ns or 2**63 - 1),
        )
        if self._journal is not None:
            self._journal.record_admission(admission)
        self._admitted += 1
        self._used_ids.add(request_id)
        self._active[admission] = None
        return admission

    def finish(self, admission: RequestAdmission, *, status: str) -> HostRequestEvent:
        """Record controller-observed completion, overriding late results as timed out."""
        with self._lock:
            return self._finish_locked(admission, status=status)

    def _finish_locked(self, admission: RequestAdmission, *, status: str) -> HostRequestEvent:
        if type(admission) is not RequestAdmission or admission not in self._active:
            _fail("producer_request_transport_admission_invalid")
        if type(status) is not str or status not in _TERMINAL:
            _fail("producer_request_transport_status_invalid")
        now = self._now()
        if now < admission.started_ns:
            _fail("producer_request_transport_clock_invalid")
        event = self._terminal_event(admission, now, status)
        if self._journal is not None:
            self._journal.record_terminal(event, now)
        del self._active[admission]
        self._events[event.sequence] = event
        return event

    def expire(self, *, admission: RequestAdmission | None = None) -> tuple[HostRequestEvent, ...]:
        """Mark overdue admissions; caller must independently cancel their I/O."""
        with self._lock:
            return self._expire_locked(admission=admission)

    def _expire_locked(self, *, admission: RequestAdmission | None) -> tuple[HostRequestEvent, ...]:
        now = self._now()
        expired: list[HostRequestEvent] = []
        candidates = (admission,) if admission is not None else tuple(self._active)
        for candidate in candidates:
            if candidate not in self._active:
                _fail("producer_request_transport_admission_invalid")
            if now >= candidate.deadline_ns:
                event = self._terminal_event(candidate, now, "timed_out")
                if self._journal is not None:
                    self._journal.record_terminal(event, now)
                del self._active[candidate]
                self._events[event.sequence] = event
                expired.append(event)
        return tuple(expired)

    @staticmethod
    def _terminal_event(admission: RequestAdmission, now: int, status: str) -> HostRequestEvent:
        elapsed_ns = now - admission.started_ns
        elapsed_ms = (elapsed_ns + 999_999) // 1_000_000
        return HostRequestEvent(
            sequence=admission.sequence,
            request_id=admission.request_id,
            status="timed_out" if now >= admission.deadline_ns else status,
            duration_ms=elapsed_ms,
        )

    def snapshot(self) -> HostRequestSnapshot:
        with self._lock:
            return HostRequestSnapshot(
                events=tuple(self._events[key] for key in sorted(self._events)),
                admitted_count=self._admitted,
                active_count=len(self._active),
                request_timeout_seconds=self.request_timeout_seconds,
                max_requests=self.max_requests,
            )


__all__ = [
    "MAX_HOST_REQUEST_JOURNAL_BYTES",
    "HostRequestEvent",
    "HostRequestJournal",
    "HostRequestJournalIdentity",
    "HostRequestLedger",
    "HostRequestRecovery",
    "HostRequestSnapshot",
    "ProducerRequestTransportError",
    "RequestAdmission",
    "read_host_request_journal",
]
