"""Bounded anonymous-pipe bridge from an isolated producer to the host broker."""

from __future__ import annotations

import base64
import binascii
import json
import os
import selectors
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .controller_http_transport import ControllerHttpRequest, ControllerHttpTransport
from .controller_request_broker import ControllerOwnedRequestBroker, ControllerRequestBrokerError
from .http_transport import MAX_REQUEST_BYTES, MAX_RESULT_BYTES
from .producer_launcher import ProducerLaunchIntent
from .producer_request_transport import (
    HostRequestJournal,
    HostRequestJournalIdentity,
    HostRequestLedger,
    HostRequestSnapshot,
    ProducerRequestTransportError,
    read_host_request_journal,
)

_MAX_FRAME_BYTES = MAX_REQUEST_BYTES * 4 // 3 + 4096
_MAX_RESPONSE_FRAME_BYTES = MAX_RESULT_BYTES * 4 // 3 + 4096


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


@dataclass(frozen=True, slots=True)
class ProducerBrokerObservation:
    snapshot: HostRequestSnapshot
    journal_path: Path
    journal_identity: HostRequestJournalIdentity
    journal_sha256: str
    journal_bytes: int
    complete: bool
    reason: str


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


def _read_line(fd: int, deadline_ns: int, limit: int) -> bytes | None:
    data = bytearray()
    os.set_blocking(fd, False)
    with selectors.DefaultSelector() as watcher:
        watcher.register(fd, selectors.EVENT_READ)
        while True:
            remaining = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
            if remaining <= 0 or not watcher.select(remaining):
                raise ProducerBrokerIpcError("producer_broker_wall_timeout")
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


def _write_line(fd: int, data: bytes, deadline_ns: int) -> None:
    os.set_blocking(fd, False)
    offset = 0
    with selectors.DefaultSelector() as watcher:
        watcher.register(fd, selectors.EVENT_WRITE)
        while offset < len(data):
            remaining = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
            if remaining <= 0 or not watcher.select(remaining):
                raise ProducerBrokerIpcError("producer_broker_wall_timeout")
            try:
                offset += os.write(fd, data[offset:offset + 65536])
            except BlockingIOError:
                continue
            except BrokenPipeError as exc:
                raise ProducerBrokerIpcError("producer_broker_response_pipe_closed") from exc


def serve_producer_broker(
    request_fd: int, response_fd: int, *, intent: ProducerLaunchIntent,
    journal_dir: Path, config: ProducerBrokerConfig, deadline_ns: int,
    ready: threading.Event | None = None,
) -> ProducerBrokerObservation:
    """Serve one isolated target through a controller-owned, fixed-endpoint broker.

    The caller owns both pipe descriptors and closes them after this function
    returns. The journal lives outside all target write directories.
    """
    if type(intent) is not ProducerLaunchIntent or type(config) is not ProducerBrokerConfig:
        raise ProducerBrokerIpcError("producer_broker_input_invalid")
    if type(deadline_ns) is not int or deadline_ns <= time.monotonic_ns():
        raise ProducerBrokerIpcError("producer_broker_deadline_invalid")
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
        broker = ControllerOwnedRequestBroker(ledger, ControllerHttpTransport())
        if ready is not None:
            ready.set()
        while True:
            try:
                raw = _read_line(request_fd, deadline_ns, _MAX_FRAME_BYTES)
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
                )
                response = result.response
                data = _encode({
                    "protocol": "lunar-producer-broker-ipc-v1", "request_id": request_id,
                    "status": result.event.status,
                    "http_status": response.status if response is not None else None,
                    "body_base64": base64.b64encode(response.body).decode("ascii") if response is not None else None,
                }, limit=_MAX_RESPONSE_FRAME_BYTES)
                _write_line(response_fd, data, deadline_ns)
                if result.event.status == "timed_out":
                    reason = (
                        "request_timed_out" if result.host_timeout_enforced
                        else "request_boundary_unknown"
                    )
                    break
            except (ProducerBrokerIpcError, ControllerRequestBrokerError, ProducerRequestTransportError,
                    OSError, ValueError):
                reason = "request_boundary_unknown"
                break
        snapshot = ledger.snapshot()
    recovered = read_host_request_journal(
        journal_path, expected_identity=identity, deadline=deadline_ns / 1_000_000_000,
    )
    if recovered.snapshot != snapshot or (reason == "complete" and recovered.uncertain_request_ids):
        raise ProducerBrokerIpcError("producer_broker_journal_recovery_mismatch")
    return ProducerBrokerObservation(
        snapshot, journal_path, identity, recovered.journal_sha256, recovered.journal_bytes,
        reason == "complete" and snapshot.within_broker_limits, reason,
    )


def brokered_producer_post(request_id: str, body: bytes, *, deadline_ns: int) -> tuple[int, bytes]:
    """Target-side SDK call; endpoint and credentials never enter the target."""
    read_fd = int(os.environ["LUNAR_PRODUCER_RESPONSE_FD"])
    write_fd = int(os.environ["LUNAR_PRODUCER_REQUEST_FD"])
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
            or type(response["http_status"]) is not int):
        raise ProducerBrokerIpcError("producer_broker_response_invalid")
    return response["http_status"], _body(response["body_base64"], maximum=MAX_RESULT_BYTES)


__all__ = [
    "ProducerBrokerConfig", "ProducerBrokerIpcError", "ProducerBrokerObservation",
    "brokered_producer_post", "serve_producer_broker",
]
