"""Bounded anonymous-pipe bridge from an isolated producer to the host broker."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import selectors
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType

from .controller_http_transport import ControllerHttpRequest, ControllerHttpTransport
from .controller_request_broker import (
    BrokerRequestResult,
    ControllerOwnedRequestBroker,
    ControllerRequestBrokerError,
)
from .http_transport import (
    MAX_REQUEST_BYTES,
    MAX_RESULT_BYTES,
    TransportResponse,
    _validate_fixed_destination_endpoint,
)
from .producer_launcher import ProducerLaunchIntent
from .producer_request_transport import (
    HostRequestEvent,
    HostRequestJournal,
    HostRequestJournalIdentity,
    HostRequestLedger,
    HostRequestSnapshot,
    ProducerRequestTransportError,
    RequestAdmission,
    read_host_request_journal,
)
from .rsi_identity import component_fingerprint

_MAX_FRAME_BYTES = MAX_REQUEST_BYTES * 4 // 3 + 4096
_MAX_RESPONSE_FRAME_BYTES = MAX_RESULT_BYTES * 4 // 3 + 4096
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_STOP_POLL_SECONDS = 0.05


class ProducerBrokerIpcError(ValueError):
    """Fixed-code failure; never includes producer body or provider response."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class ProducerBrokerConfig:
    """Host-only provider destination and credentials, never passed to the target."""

    endpoint: str
    headers: dict[str, str]

    def __post_init__(self) -> None:
        ControllerHttpRequest(self.endpoint, self.headers, b"")


class _ProducerBrokerOriginal:
    # Deliberately absent from constructor, asdict and durable recovery.
    __slots__ = ("_original_exchange_acquisition",)


class _ProducerBrokerExchangeAcquisition:
    __slots__ = ("body", "deadline_ns", "facts", "implementation", "originals", "reply", "result")

    def __init__(self) -> None:
        raise ProducerBrokerIpcError("producer_broker_exchange_private")

    def __copy__(self):
        raise ProducerBrokerIpcError("producer_broker_exchange_detached")

    def __deepcopy__(self, memo):
        raise ProducerBrokerIpcError("producer_broker_exchange_detached")


@dataclass(frozen=True, slots=True)
class ProducerBrokerObservation(_ProducerBrokerOriginal):
    snapshot: HostRequestSnapshot
    journal_path: Path
    journal_identity: HostRequestJournalIdentity
    journal_sha256: str
    journal_bytes: int
    complete: bool
    reason: str
    journal_file_identity: tuple[int, int] | None = None


def _broker_exchange_implementation_pin() -> tuple:
    helpers = (
        serve_producer_broker, _original_broker_exchange_pin, _broker_exchange_facts,
        _broker_exchange_implementation_pin, _encode, _decode, _body, _read_line,
        _write_line, _check_stop, _unique, _invalid,
        ControllerOwnedRequestBroker.execute, ControllerHttpTransport.start,
        HostRequestLedger.admit, HostRequestLedger.finish, HostRequestLedger.snapshot,
        HostRequestJournalIdentity.to_dict, ProducerBrokerObservation.__init__,
        _ProducerBrokerExchangeAcquisition.__init__, _ProducerBrokerExchangeAcquisition.__copy__,
        _ProducerBrokerExchangeAcquisition.__deepcopy__, read_host_request_journal, component_fingerprint,
    )
    if any(type(helper) is not FunctionType for helper in helpers):
        raise ProducerBrokerIpcError("producer_broker_exchange_changed")
    return (
        (ProducerBrokerObservation, _ProducerBrokerOriginal, _ProducerBrokerExchangeAcquisition,
         BrokerRequestResult, TransportResponse, HostRequestEvent, RequestAdmission,
         HostRequestSnapshot, HostRequestJournalIdentity, ControllerHttpRequest,
         ControllerOwnedRequestBroker, ControllerHttpTransport),
        (MAX_REQUEST_BYTES, MAX_RESULT_BYTES, _MAX_FRAME_BYTES, _MAX_RESPONSE_FRAME_BYTES),
        tuple((helper, helper.__code__, helper.__defaults__,
               tuple(sorted((helper.__kwdefaults__ or {}).items())),
               component_fingerprint(helper, config={})) for helper in helpers),
    )


def _broker_exchange_facts(observation, result, body, reply, deadline_ns) -> tuple:
    if (type(observation) is not ProducerBrokerObservation
            or type(result) is not BrokerRequestResult
            or type(result.admission) is not RequestAdmission
            or type(result.event) is not HostRequestEvent
            or type(result.response) is not TransportResponse
            or type(body) is not bytes or len(body) > MAX_REQUEST_BYTES
            or type(reply) is not bytes or len(reply) > MAX_RESULT_BYTES
            or result.response.body is not reply
            or type(result.response.status) is not int or result.response.status != 200
            or result.cancellation_requested is not False
            or result.cancellation_acknowledged is not False
            or result.host_timeout_enforced is not False
            or type(deadline_ns) is not int or not 0 < deadline_ns < 2**63
            or type(observation.snapshot) is not HostRequestSnapshot
            or type(observation.journal_identity) is not HostRequestJournalIdentity
            or type(observation.journal_path) is not type(Path())
            or observation.complete is not True or observation.reason != "complete"):
        raise ProducerBrokerIpcError("producer_broker_exchange_changed")
    snapshot, identity, admission, event = (
        observation.snapshot, observation.journal_identity, result.admission, result.event,
    )
    if (type(snapshot.events) is not tuple or len(snapshot.events) != 1
            or snapshot.events[0] is not event
            or type(snapshot.admitted_count) is not int or snapshot.admitted_count != 1
            or type(snapshot.active_count) is not int or snapshot.active_count != 0
            or type(snapshot.request_timeout_seconds) is not int
            or type(snapshot.max_requests) is not int
            or type(snapshot.coverage) is not str or type(snapshot.clock_source) is not str
            or snapshot.coverage != "brokered_requests_only"
            or snapshot.clock_source != "controller_monotonic"
            or type(identity.max_requests) is not int or identity.max_requests < 1
            or type(identity.request_timeout_seconds) is not int
            or not 1 <= identity.request_timeout_seconds <= 86_400
            or snapshot.max_requests != identity.max_requests
            or snapshot.request_timeout_seconds != identity.request_timeout_seconds
            or type(identity.wall_deadline_ns) is not int
            or identity.wall_deadline_ns != deadline_ns
            or type(event.sequence) is not int or event.sequence != 1
            or type(event.request_id) is not str or event.request_id != "req-1"
            or type(event.status) is not str or event.status != "completed"
            or type(event.duration_ms) is not int or event.duration_ms < 0
            or type(admission.sequence) is not int or admission.sequence != event.sequence
            or admission.request_id is not event.request_id
            or type(admission.started_ns) is not int or type(admission.deadline_ns) is not int
            or not 0 < admission.started_ns < admission.deadline_ns <= deadline_ns
            or type(observation.journal_sha256) is not str
            or len(observation.journal_sha256) != 64
            or any(char not in "0123456789abcdef" for char in observation.journal_sha256)
            or type(observation.journal_bytes) is not int or observation.journal_bytes <= 0
            or type(observation.journal_file_identity) is not tuple
            or len(observation.journal_file_identity) != 2
            or any(type(value) is not int or value < 0 for value in observation.journal_file_identity)):
        raise ProducerBrokerIpcError("producer_broker_exchange_changed")
    if (any(type(value) is not str or _REQUEST_ID.fullmatch(value) is None for value in (
            identity.launch_id, identity.journal_id, identity.run_id, identity.parent_task_id, identity.task_id))
            or type(identity.intent_sha256) is not str or len(identity.intent_sha256) != 64
            or any(char not in "0123456789abcdef" for char in identity.intent_sha256)):
        raise ProducerBrokerIpcError("producer_broker_exchange_changed")
    return (
        tuple(identity.to_dict().items()), observation.journal_path,
        observation.journal_sha256, observation.journal_bytes, observation.journal_file_identity,
        snapshot.request_timeout_seconds, snapshot.max_requests,
        event.sequence, event.request_id, event.status, event.duration_ms,
        admission.started_ns, admission.deadline_ns, result.response.status,
    )


def _original_broker_exchange_pin(observation: ProducerBrokerObservation) -> tuple | None:
    """Recheck the sole original delivered exchange; recovered/public DTOs have none.

    Positions 2 and 4 are the actual body/reply bytes, followed at positions 6–8
    by request ID, HTTP status and the original absolute monotonic deadline.
    This process-local pin never writes provider material to a journal or export.
    """
    try:
        if type(observation) is not ProducerBrokerObservation:
            raise ValueError
        acquired = getattr(observation, "_original_exchange_acquisition", None)
        if acquired is None:
            return None
        if type(acquired) is not _ProducerBrokerExchangeAcquisition:
            raise ValueError
        result, body, reply, originals = acquired.result, acquired.body, acquired.reply, acquired.originals
        current = (acquired, observation, body, reply, result, result.admission, result.event,
                   result.response, observation.snapshot, observation.snapshot.events,
                   observation.journal_identity, observation.journal_path)
        if (type(originals) is not tuple or len(originals) != len(current)
                or any(value is not original for value, original in zip(current, originals, strict=True))
                or _broker_exchange_implementation_pin() != acquired.implementation
                or _broker_exchange_facts(observation, result, body, reply, acquired.deadline_ns) != acquired.facts):
            raise ValueError
        return (acquired, id(acquired), body, id(body), reply, id(reply),
                result.event.request_id, result.response.status, acquired.deadline_ns,
                originals, acquired.facts, acquired.implementation)
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError, OverflowError):
        raise ProducerBrokerIpcError("producer_broker_exchange_changed") from None


def _encode(value: dict[str, object], *, limit: int) -> bytes:
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProducerBrokerIpcError("producer_broker_frame_invalid") from exc
    if len(data) > limit:
        raise ProducerBrokerIpcError("producer_broker_frame_too_large")
    return data


def _decode(raw: bytes, *, limit: int) -> dict[str, object]:
    if len(raw) > limit or not raw.endswith(b"\n"):
        raise ProducerBrokerIpcError("producer_broker_frame_invalid")
    try:
        value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_invalid)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProducerBrokerIpcError("producer_broker_frame_invalid") from exc
    if type(value) is not dict:
        raise ProducerBrokerIpcError("producer_broker_frame_invalid")
    return value


def _invalid(_: str) -> None:
    raise ValueError("non-finite JSON value")


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _body(value: object, *, maximum: int) -> bytes:
    if type(value) is not str:
        raise ProducerBrokerIpcError("producer_broker_body_invalid")
    try:
        body = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProducerBrokerIpcError("producer_broker_body_invalid") from exc
    if len(body) > maximum or base64.b64encode(body).decode("ascii") != value:
        raise ProducerBrokerIpcError("producer_broker_body_invalid")
    return body


def _check_stop(stop: threading.Event | None) -> None:
    if stop is not None and stop.is_set():
        raise ProducerBrokerIpcError("producer_broker_cancelled")


def _read_line(
    fd: int, deadline_ns: int, limit: int, *, stop: threading.Event | None = None,
) -> bytes | None:
    data = bytearray()
    os.set_blocking(fd, False)
    with selectors.DefaultSelector() as watcher:
        watcher.register(fd, selectors.EVENT_READ)
        while True:
            _check_stop(stop)
            remaining = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
            if remaining <= 0:
                raise ProducerBrokerIpcError("producer_broker_wall_timeout")
            if not watcher.select(remaining if stop is None else min(remaining, _STOP_POLL_SECONDS)):
                if stop is not None:
                    continue
                raise ProducerBrokerIpcError("producer_broker_wall_timeout")
            _check_stop(stop)
            try:
                part = os.read(fd, min(65536, limit + 1 - len(data)))
            except BlockingIOError:
                continue
            if not part:
                if not data:
                    return None
                raise ProducerBrokerIpcError("producer_broker_frame_truncated")
            data.extend(part)
            if len(data) > limit:
                raise ProducerBrokerIpcError("producer_broker_frame_too_large")
            if b"\n" in part:
                if not data.endswith(b"\n") or data.count(b"\n") != 1:
                    raise ProducerBrokerIpcError("producer_broker_frame_invalid")
                return bytes(data)


def _write_line(
    fd: int, data: bytes, deadline_ns: int, *, stop: threading.Event | None = None,
) -> None:
    os.set_blocking(fd, False)
    offset = 0
    with selectors.DefaultSelector() as watcher:
        watcher.register(fd, selectors.EVENT_WRITE)
        while offset < len(data):
            _check_stop(stop)
            remaining = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
            if remaining <= 0:
                raise ProducerBrokerIpcError("producer_broker_wall_timeout")
            if not watcher.select(remaining if stop is None else min(remaining, _STOP_POLL_SECONDS)):
                if stop is not None:
                    continue
                raise ProducerBrokerIpcError("producer_broker_wall_timeout")
            _check_stop(stop)
            try:
                offset += os.write(fd, data[offset:offset + 65536])
            except BlockingIOError:
                continue
            except BrokenPipeError as exc:
                raise ProducerBrokerIpcError("producer_broker_response_pipe_closed") from exc


def _target_pipe(name: str) -> int:
    """Resolve one controller-created anonymous pipe from the target environment.

    The environment is only a descriptor handoff; accepting a regular file,
    socket, or arbitrary inherited descriptor would create a second egress or
    persistence channel outside the broker protocol.  The native launcher uses
    ``os.pipe`` for both directions, so fail closed on every other descriptor.
    """
    value = os.environ.get(name)
    if type(value) is not str or not value or not value.isdecimal():
        raise ProducerBrokerIpcError("producer_broker_pipe_invalid")
    try:
        fd = int(value, 10)
        info = os.fstat(fd)
    except (OSError, ValueError, OverflowError) as exc:
        raise ProducerBrokerIpcError("producer_broker_pipe_invalid") from exc
    if fd < 0 or not stat.S_ISFIFO(info.st_mode):
        raise ProducerBrokerIpcError("producer_broker_pipe_invalid")
    return fd


def serve_producer_broker(
    request_fd: int, response_fd: int, *, intent: ProducerLaunchIntent,
    journal_dir: Path, config: ProducerBrokerConfig, deadline_ns: int,
    ready: threading.Event | None = None,
    stop: threading.Event | None = None,
    retain_original_exchange: bool = False,
) -> ProducerBrokerObservation:
    """Serve one isolated target through a controller-owned, fixed-endpoint broker.

    The caller owns both pipe descriptors and closes them after this function
    returns. The journal lives outside all target write directories.
    """
    if type(intent) is not ProducerLaunchIntent or type(config) is not ProducerBrokerConfig:
        raise ProducerBrokerIpcError("producer_broker_input_invalid")
    if type(retain_original_exchange) is not bool:
        raise ProducerBrokerIpcError("producer_broker_input_invalid")
    implementation = _broker_exchange_implementation_pin() if retain_original_exchange else None
    original_exchange = None
    delivered_count = 0
    try:
        _validate_fixed_destination_endpoint(config.endpoint)
    except ValueError as exc:
        raise ProducerBrokerIpcError("producer_broker_endpoint_invalid") from exc
    if type(deadline_ns) is not int or deadline_ns <= time.monotonic_ns():
        raise ProducerBrokerIpcError("producer_broker_deadline_invalid")
    if stop is not None and not isinstance(stop, threading.Event):
        raise ProducerBrokerIpcError("producer_broker_stop_invalid")
    journal_dir.mkdir(mode=0o700)
    journal_path = journal_dir / "requests"
    identity = HostRequestJournalIdentity(
        launch_id=intent.launch_id, journal_id=intent.journal_id, run_id=intent.run_id,
        parent_task_id=intent.parent_task_id, task_id=intent.task_id,
        intent_sha256=str(intent.intent_sha256),
        request_timeout_seconds=intent.request_timeout_seconds,
        max_requests=intent.max_requests, wall_deadline_ns=deadline_ns,
    )
    reason = "complete"
    with HostRequestJournal.create(journal_path, identity) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=intent.request_timeout_seconds,
            max_requests=intent.max_requests, journal=journal,
        )
        broker = ControllerOwnedRequestBroker(ledger, ControllerHttpTransport(fixed_destination=True))
        if ready is not None:
            ready.set()
        while True:
            try:
                raw = _read_line(request_fd, deadline_ns, _MAX_FRAME_BYTES, stop=stop)
                if raw is None:
                    break
                frame = _decode(raw, limit=_MAX_FRAME_BYTES)
                if set(frame) != {"protocol", "request_id", "body_base64"} or frame["protocol"] != "lunar-producer-broker-ipc-v1":
                    raise ProducerBrokerIpcError("producer_broker_frame_invalid")
                body = _body(frame["body_base64"], maximum=MAX_REQUEST_BYTES)
                request_id = frame["request_id"]
                if type(request_id) is not str:
                    raise ProducerBrokerIpcError("producer_broker_frame_invalid")
                result = broker.execute(
                    request_id, ControllerHttpRequest(config.endpoint, config.headers, body),
                    cancelled=stop.is_set if stop is not None else None,
                )
                if result.cancellation_requested and not result.host_timeout_enforced:
                    reason = "cancelled"
                    break
                _check_stop(stop)
                response = result.response
                data = _encode({
                    "protocol": "lunar-producer-broker-ipc-v1", "request_id": request_id,
                    "status": result.event.status,
                    "http_status": response.status if response is not None else None,
                    "body_base64": base64.b64encode(response.body).decode("ascii") if response is not None else None,
                }, limit=_MAX_RESPONSE_FRAME_BYTES)
                _write_line(response_fd, data, deadline_ns, stop=stop)
                if retain_original_exchange:
                    # These are the exact decoded body and response consumed by
                    # this execute call. A partial/failed pipe write retains none.
                    delivered_count += 1
                    original_exchange = ((body, result.response.body, result)
                                         if delivered_count == 1 and type(result.response) is TransportResponse
                                         else None)
                if result.event.status == "timed_out":
                    reason = (
                        "request_timed_out" if result.host_timeout_enforced
                        else "request_boundary_unknown"
                    )
                    break
            except (ProducerBrokerIpcError, ControllerRequestBrokerError) as exc:
                reason = (
                    "cancelled" if exc.code in {"producer_broker_cancelled", "producer_request_broker_cancelled"}
                    else "request_boundary_unknown"
                )
                break
            except (ProducerRequestTransportError, OSError, ValueError):
                reason = "request_boundary_unknown"
                break
        snapshot = ledger.snapshot()
    recovered = read_host_request_journal(
        journal_path, expected_identity=identity, deadline=deadline_ns / 1_000_000_000,
    )
    if recovered.snapshot != snapshot or (reason == "complete" and recovered.uncertain_request_ids):
        raise ProducerBrokerIpcError("producer_broker_journal_recovery_mismatch")
    observation = ProducerBrokerObservation(
        snapshot=snapshot,
        journal_path=journal_path,
        journal_identity=identity,
        journal_sha256=recovered.journal_sha256,
        journal_bytes=recovered.journal_bytes,
        complete=(reason == "complete" and snapshot.within_broker_limits),
        reason=reason,
        journal_file_identity=recovered.journal_file_identity,
    )
    if (retain_original_exchange and observation.complete and original_exchange is not None
            and delivered_count == 1 and snapshot.admitted_count == 1):
        body, reply, result = original_exchange
        if (result.event.request_id == "req-1" and result.event.status == "completed"
                and type(result.response.status) is int and result.response.status == 200):
            if (time.monotonic_ns() >= deadline_ns
                    or _broker_exchange_implementation_pin() != implementation):
                raise ProducerBrokerIpcError("producer_broker_exchange_changed")
            acquired = object.__new__(_ProducerBrokerExchangeAcquisition)
            acquired.body, acquired.reply, acquired.result = body, reply, result
            acquired.deadline_ns, acquired.implementation = deadline_ns, implementation
            acquired.facts = _broker_exchange_facts(observation, result, body, reply, deadline_ns)
            acquired.originals = (
                acquired, observation, body, reply, result, result.admission, result.event,
                result.response, observation.snapshot, observation.snapshot.events,
                observation.journal_identity, observation.journal_path,
            )
            object.__setattr__(observation, "_original_exchange_acquisition", acquired)
            _original_broker_exchange_pin(observation)
    return observation


def recover_producer_broker_observation(
    journal_path: str | Path,
    *,
    identity: HostRequestJournalIdentity,
    deadline_ns: int,
    expected_journal_sha256: str | None = None,
    expected_journal_bytes: int | None = None,
    expected_journal_file_identity: tuple[int, int] | None = None,
) -> ProducerBrokerObservation:
    """Rebuild one broker observation from a durable journal after interruption.

    Recovery is deliberately read-only: it never opens the journal for append, retries a
    request, or upgrades an active/timed-out request to a successful terminal.  A complete
    observation is returned only when every admitted request has a host-observed terminal.
    The optional digest and byte count let a retained execution receipt bind the replay to the
    exact journal that was captured before the process stopped.
    """
    if not isinstance(identity, HostRequestJournalIdentity) or type(deadline_ns) is not int:
        raise ProducerBrokerIpcError("producer_broker_recovery_input_invalid")
    if expected_journal_sha256 is not None and (
        type(expected_journal_sha256) is not str or len(expected_journal_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_journal_sha256)
    ):
        raise ProducerBrokerIpcError("producer_broker_recovery_digest_invalid")
    if expected_journal_bytes is not None and (
        type(expected_journal_bytes) is not int or expected_journal_bytes < 1
    ):
        raise ProducerBrokerIpcError("producer_broker_recovery_size_invalid")
    if expected_journal_file_identity is not None and (
        type(expected_journal_file_identity) is not tuple
        or len(expected_journal_file_identity) != 2
        or any(type(item) is not int or item < 0 for item in expected_journal_file_identity)
    ):
        raise ProducerBrokerIpcError("producer_broker_recovery_file_identity_invalid")
    if deadline_ns <= time.monotonic_ns():
        raise ProducerBrokerIpcError("producer_broker_recovery_input_invalid")
    path = Path(journal_path).expanduser().absolute()
    try:
        recovered = read_host_request_journal(
            path,
            expected_identity=identity,
            deadline=deadline_ns / 1_000_000_000,
            expected_file_identity=expected_journal_file_identity,
        )
    except ProducerRequestTransportError as exc:
        raise ProducerBrokerIpcError("producer_broker_recovery_journal_invalid") from exc
    if expected_journal_sha256 is not None and recovered.journal_sha256 != expected_journal_sha256:
        raise ProducerBrokerIpcError("producer_broker_recovery_journal_mismatch")
    if expected_journal_bytes is not None and recovered.journal_bytes != expected_journal_bytes:
        raise ProducerBrokerIpcError("producer_broker_recovery_journal_mismatch")
    complete = not recovered.uncertain_request_ids and recovered.snapshot.within_broker_limits
    return ProducerBrokerObservation(
        snapshot=recovered.snapshot,
        journal_path=path,
        journal_identity=identity,
        journal_sha256=recovered.journal_sha256,
        journal_bytes=recovered.journal_bytes,
        complete=complete,
        journal_file_identity=recovered.journal_file_identity,
        reason="recovered" if complete else "recovery_required",
    )


def brokered_producer_post(request_id: str, body: bytes, *, deadline_ns: int) -> tuple[int, bytes]:
    """Target-side SDK call; endpoint and credentials never enter the target."""
    if type(request_id) is not str or _REQUEST_ID.fullmatch(request_id) is None:
        raise ProducerBrokerIpcError("producer_broker_request_id_invalid")
    if type(body) is not bytes:
        raise ProducerBrokerIpcError("producer_broker_body_invalid")
    if type(deadline_ns) is not int or deadline_ns <= time.monotonic_ns():
        raise ProducerBrokerIpcError("producer_broker_deadline_invalid")
    read_fd = _target_pipe("LUNAR_PRODUCER_RESPONSE_FD")
    write_fd = _target_pipe("LUNAR_PRODUCER_REQUEST_FD")
    if read_fd == write_fd:
        raise ProducerBrokerIpcError("producer_broker_pipe_invalid")
    frame = _encode({
        "protocol": "lunar-producer-broker-ipc-v1", "request_id": request_id,
        "body_base64": base64.b64encode(body).decode("ascii"),
    }, limit=_MAX_FRAME_BYTES)
    _write_line(write_fd, frame, deadline_ns)
    raw = _read_line(read_fd, deadline_ns, _MAX_RESPONSE_FRAME_BYTES)
    if raw is None:
        raise ProducerBrokerIpcError("producer_broker_response_missing")
    response = _decode(raw, limit=_MAX_RESPONSE_FRAME_BYTES)
    if (set(response) != {"protocol", "request_id", "status", "http_status", "body_base64"}
            or response["protocol"] != "lunar-producer-broker-ipc-v1"
            or response["request_id"] != request_id or response["status"] != "completed"
            or type(response["http_status"]) is not int
            or not 100 <= response["http_status"] <= 599):
        raise ProducerBrokerIpcError("producer_broker_response_invalid")
    return response["http_status"], _body(response["body_base64"], maximum=MAX_RESULT_BYTES)


__all__ = [
    "ProducerBrokerConfig", "ProducerBrokerIpcError", "ProducerBrokerObservation",
    "brokered_producer_post", "recover_producer_broker_observation", "serve_producer_broker",
]
