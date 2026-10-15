"""One-shot detached publication transport; never a BRS publication capability.

Only the retained owner services the retained worker's request. The future owner
integration must independently validate running/started state, evidence and CAS.
No controller, filesystem, transaction, execution or recovery is performed here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn

from .python_producer_admission_handoff import (
    parse_python_producer_admission_handoff_file_pin,
)
from .rsi_learning import RSILearningError
from .rsi_python_brs_handoff import BRSSelectedChildHandoff

MAX_BRS_PUBLICATION_MESSAGE_BYTES = 8 * 1024 * 1024
_POLL_SECONDS = 0.05
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "native_plan_sha256", "expected_head_sha256", "expected_state_sha256",
    "native_execution_receipt_sha256", "output", "python_handoff_file_pin",
}
_OUTPUT_DIGEST_FIELDS = {
    "process_terminal_sha256", "output_capture_sha256", "envelope_bytes_sha256",
    "execution_receipt_sha256", "admission_plan_sha256",
}


class RSIPythonBRSPublicationMailboxError(RSILearningError):
    def __init__(self, code: str) -> None:
        super().__init__("rsi_python_brs_publication_mailbox_" + code)


def _fail(code: str) -> NoReturn:
    raise RSIPythonBRSPublicationMailboxError(code)


def _identity(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail("identity_invalid")
    return value


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail("digest_invalid")
    return value


def _shape(value: object, depth: int = 0) -> None:
    if depth > 48:
        _fail("payload_invalid")
    kind = type(value)
    if value is None or kind is str or kind is int or kind is bool:
        return
    if kind is float and math.isfinite(value):
        return
    if kind is dict:
        if any(type(key) is not str for key in value):
            _fail("payload_invalid")
        children = value.values()
    elif kind is list:
        children = value
    else:
        _fail("payload_invalid")
    for child in children:
        _shape(child, depth + 1)


def _payload(raw: object) -> dict:
    if type(raw) is not bytes:
        _fail("payload_invalid")
    if len(raw) > MAX_BRS_PUBLICATION_MESSAGE_BYTES:
        _fail("payload_too_large")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("duplicate_json_key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _value: _fail("payload_invalid"))
        _shape(value)
        if type(value) is not dict:
            _fail("payload_invalid")
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (UnicodeError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, RSIPythonBRSPublicationMailboxError):
            raise
        raise RSIPythonBRSPublicationMailboxError("payload_invalid") from exc
    if canonical != raw:
        _fail("payload_noncanonical")
    return value


def _request_payload(raw: object, run_id: str) -> dict:
    value = _payload(raw)
    if set(value) != _REQUEST_FIELDS:
        _fail("request_shape_invalid")
    for name in _REQUEST_FIELDS - {"output", "python_handoff_file_pin"}:
        _sha(value[name])
    output = value["output"]
    if type(output) is not dict or set(output) != _OUTPUT_DIGEST_FIELDS | {"request_coverage"}:
        _fail("request_shape_invalid")
    for name in _OUTPUT_DIGEST_FIELDS:
        _sha(output[name])
    if (output["request_coverage"] != "brokered_requests_only"
            or output["execution_receipt_sha256"] != value["native_execution_receipt_sha256"]):
        _fail("request_binding_invalid")
    try:
        pin = parse_python_producer_admission_handoff_file_pin(value["python_handoff_file_pin"])
    except ValueError as exc:
        raise RSIPythonBRSPublicationMailboxError("request_pin_invalid") from exc
    if pin.run_id != run_id:
        _fail("request_binding_invalid")
    return value


def _digest(domain: bytes, *parts: str | bytes) -> str:
    raw = [part.encode("utf-8") if type(part) is str else part for part in parts]
    return hashlib.sha256(domain + b"\0" + b"\0".join(raw)).hexdigest()


@dataclass(frozen=True, slots=True)
class BRSOwnerPublicationRequest:
    run_id: str
    episode_id: str
    handoff_sha256: str
    payload: bytes
    request_sha256: str

    def __post_init__(self) -> None:
        _identity(self.run_id)
        _identity(self.episode_id)
        _sha(self.handoff_sha256)
        _request_payload(self.payload, self.run_id)
        if _sha(self.request_sha256) != _digest(
            b"lunar-rsi-brs-owner-publication-request-v1", self.run_id, self.episode_id,
            self.handoff_sha256, self.payload,
        ):
            _fail("request_digest_mismatch")


@dataclass(frozen=True, slots=True)
class BRSOwnerPublicationResponse:
    run_id: str
    episode_id: str
    handoff_sha256: str
    request_sha256: str
    payload: bytes
    response_sha256: str

    def __post_init__(self) -> None:
        _identity(self.run_id)
        _identity(self.episode_id)
        _sha(self.handoff_sha256)
        _sha(self.request_sha256)
        _payload(self.payload)
        if _sha(self.response_sha256) != _digest(
            b"lunar-rsi-brs-owner-publication-response-v1", self.run_id, self.episode_id,
            self.handoff_sha256, self.request_sha256, self.payload,
        ):
            _fail("response_digest_mismatch")


def _handoff(value: object) -> BRSSelectedChildHandoff:
    if type(value) is not BRSSelectedChildHandoff:
        _fail("handoff_invalid")
    # Read only exact slots, then validate primitive types before any comparison.
    try:
        return BRSSelectedChildHandoff(**BRSSelectedChildHandoff.to_dict(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise RSIPythonBRSPublicationMailboxError("handoff_invalid") from exc


def _request(value: object) -> BRSOwnerPublicationRequest:
    if type(value) is not BRSOwnerPublicationRequest:
        _fail("request_invalid")
    try:
        return BRSOwnerPublicationRequest(value.run_id, value.episode_id, value.handoff_sha256,
                                          value.payload, value.request_sha256)
    except AttributeError as exc:
        raise RSIPythonBRSPublicationMailboxError("request_invalid") from exc


def build_brs_owner_publication_request(
    handoff: BRSSelectedChildHandoff, payload: bytes,
) -> BRSOwnerPublicationRequest:
    retained = _handoff(handoff)
    _request_payload(payload, retained.run_id)
    return BRSOwnerPublicationRequest(
        retained.run_id, retained.episode_id, retained.sha256, payload,
        _digest(b"lunar-rsi-brs-owner-publication-request-v1", retained.run_id,
                retained.episode_id, retained.sha256, payload),
    )


def build_brs_owner_publication_response(
    request: BRSOwnerPublicationRequest, payload: bytes,
) -> BRSOwnerPublicationResponse:
    retained = _request(request)
    _payload(payload)
    return BRSOwnerPublicationResponse(
        retained.run_id, retained.episode_id, retained.handoff_sha256, retained.request_sha256,
        payload, _digest(b"lunar-rsi-brs-owner-publication-response-v1", retained.run_id,
                         retained.episode_id, retained.handoff_sha256, retained.request_sha256, payload),
    )


class BRSOwnerPublicationMailbox:
    """Ephemeral transport with no refresh, retry or recovered-owner operation."""

    def __init__(
        self, handoff: BRSSelectedChildHandoff, *, worker_thread: int,
        expected_head_sha256: str | None = None, expected_state_sha256: str | None = None,
    ) -> None:
        retained = _handoff(handoff)
        if threading.get_ident() != retained.owner_thread_id:
            _fail("owner_required")
        if (type(worker_thread) is not int or worker_thread <= 0
                or worker_thread == retained.owner_thread_id):
            _fail("worker_invalid")
        if (expected_head_sha256 is None) != (expected_state_sha256 is None):
            _fail("capture_invalid")
        self._expected_head = _sha(
            retained.head_sha256 if expected_head_sha256 is None else expected_head_sha256,
        )
        self._expected_state = _sha(
            retained.state_sha256 if expected_state_sha256 is None else expected_state_sha256,
        )
        self._identity = (retained.run_id, retained.episode_id, retained.sha256)
        self._owner_thread = retained.owner_thread_id
        self._worker_thread = worker_thread
        self._condition = threading.Condition()
        self._status = "open"
        self._closed = False
        self._submitting = False
        self._servicing = False
        self._retained_request: BRSOwnerPublicationRequest | None = None
        self._response_fields: tuple | None = None
        self._accepted = False
        self._error: str | None = None

    @property
    def status(self) -> str:
        with self._condition:
            return self._status

    def _available(self) -> None:
        if self._closed:
            _fail("closed")
        if self._status != "open" or self._submitting:
            _fail("duplicate_request")

    def request(
        self, request: BRSOwnerPublicationRequest, *, check: Callable[[], None],
    ) -> BRSOwnerPublicationResponse:
        if threading.get_ident() != self._worker_thread:
            _fail("worker_required")
        detached = _request(request)
        if (detached.run_id, detached.episode_id, detached.handoff_sha256) != self._identity:
            _fail("identity_mismatch")
        payload = _request_payload(detached.payload, detached.run_id)
        if (payload["expected_head_sha256"], payload["expected_state_sha256"]) != (
            self._expected_head, self._expected_state,
        ):
            _fail("capture_mismatch")
        if not callable(check):
            _fail("check_invalid")
        with self._condition:
            self._available()
            self._submitting = True
        try:
            check()
        finally:
            with self._condition:
                self._submitting = False
        with self._condition:
            self._available()
            self._retained_request = detached
            self._status = "queued"
            self._condition.notify_all()
        try:
            while True:
                check()
                with self._condition:
                    if self._error is not None:
                        _fail(self._error)
                    if self._response_fields is not None:
                        # Return a new DTO; retained state is strict immutable primitives.
                        response = BRSOwnerPublicationResponse(*self._response_fields)
                        self._accepted = True
                        return response
                    if self._closed:
                        _fail("closed")
                    self._condition.wait(_POLL_SECONDS)
        except BaseException:
            with self._condition:
                self._status = "abandoned"
                self._response_fields = None
                self._error = self._error or "worker_abandoned"
                self._condition.notify_all()
            raise

    def service(
        self, handler: Callable[[BRSOwnerPublicationRequest], bytes], *,
        check: Callable[[], None], timeout: float = _POLL_SECONDS,
    ) -> bool:
        if threading.get_ident() != self._owner_thread:
            _fail("owner_required")
        if not callable(handler) or not callable(check):
            _fail("handler_invalid")
        if (type(timeout) is not int and type(timeout) is not float) or (
            timeout < 0 or timeout > 60 or not math.isfinite(timeout)
        ):
            _fail("timeout_invalid")
        deadline = time.monotonic() + timeout
        with self._condition:
            if self._servicing:
                _fail("service_reentrant")
            while self._status == "open" and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            if self._status != "queued" or self._closed:
                return False
            original = self._retained_request
            self._status = "inflight"
            self._servicing = True
        try:
            check()
            with self._condition:
                if self._closed or self._status != "inflight" or self._error is not None:
                    _fail("delivery_unknown")
            visible = _request(original)
            payload = handler(visible)
            # A trusted handler may inadvertently retain/mutate its argument.
            if _request(visible) != original:
                _fail("request_mutated")
            response = build_brs_owner_publication_response(original, payload)
            check()
            fields = (response.run_id, response.episode_id, response.handoff_sha256,
                      response.request_sha256, response.payload, response.response_sha256)
            with self._condition:
                if self._closed or self._status != "inflight" or self._error is not None:
                    _fail("delivery_unknown")
                self._response_fields = fields
                self._status = "delivered"
                self._servicing = False
                self._condition.notify_all()
            return True
        except BaseException:
            with self._condition:
                self._status = "abandoned"
                self._error = self._error or "handler_failed"
                self._response_fields = None
                self._servicing = False
                self._condition.notify_all()
            raise

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            if self._status == "open":
                self._status = "closed"
            elif self._status != "delivered" or not self._accepted:
                self._status = "abandoned"
                self._error = self._error or "closed"
                self._response_fields = None
            self._condition.notify_all()
