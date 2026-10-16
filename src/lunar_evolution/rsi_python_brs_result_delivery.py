"""Exact provider-free BRS owner-result delivery and one-shot settlement.

The owner mailbox transport only moves bounded bytes.  This module gives those bytes a
narrow result contract: the response remains bound to the selected run, episode,
request, handoff, native preparation plan and one owner transaction journal.  A worker
may consume the detached delivery exactly once through a caller-owned settlement
callback.  Callback failure is classified as unknown and is never retried by this
module.

This is an online composition primitive only.  It does not create a mailbox, acquire a
controller lock, publish a candidate, reconcile an unknown outcome, or enable public
BRS.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, NoReturn

from .candidate_evaluation_spec import canonical_json
from .producer_bundle_publication import ProducerBundlePublicationJournal
from .producer_bundle_transaction import NativeProducerBundleTransactionResult
from .rsi_learning import RSILearningError
from .rsi_python_brs_handoff import BRSSelectedChildHandoff
from .rsi_python_brs_publication_mailbox import (
    BRSOwnerPublicationRequest,
    BRSOwnerPublicationResponse,
    _request_payload,
)

MAX_BRS_OWNER_RESULT_BYTES = 256 * 1024
_PROTOCOL = "lunar-rsi-brs-owner-result-v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = frozenset({"published", "all_rejected"})
_FIELDS = {
    "protocol", "run_id", "episode_id", "handoff_sha256", "request_sha256",
    "selected_request_sha256",
    "native_plan_sha256", "publication_status", "journal_sha256",
    "terminal_marker_sha256", "archive_after_sha256", "state_after_sha256",
    "admitted_candidate_ids",
}


class BRSOwnerResultDeliveryError(RSILearningError):
    """Stable refusal for malformed, stale or duplicate owner-result delivery."""

    def __init__(self, code: str) -> None:
        super().__init__("rsi_python_brs_result_delivery_" + code)


def _fail(code: str) -> NoReturn:
    raise BRSOwnerResultDeliveryError(code)


def _id(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(f"{field}_invalid")
    return value


def _sha(value: object, field: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail(f"{field}_invalid")
    return value


def _shape(value: object, depth: int = 0) -> None:
    if depth > 16:
        _fail("payload_invalid")
    kind = type(value)
    if value is None or kind in {str, int, bool}:
        return
    if kind is float:
        if not math.isfinite(value):
            _fail("payload_invalid")
        return
    if kind is dict:
        if any(type(key) is not str for key in value):
            _fail("payload_invalid")
        for child in value.values():
            _shape(child, depth + 1)
        return
    if kind is list:
        for child in value:
            _shape(child, depth + 1)
        return
    _fail("payload_invalid")


def _canonical_payload(raw: object) -> dict[str, Any]:
    if type(raw) is not bytes or len(raw) > MAX_BRS_OWNER_RESULT_BYTES:
        _fail("payload_invalid")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in items:
            if key in output:
                _fail("duplicate_json_key")
            output[key] = value
        return output

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=lambda _value: _fail("payload_invalid"))
        _shape(parsed)
        if type(parsed) is not dict or set(parsed) != _FIELDS:
            _fail("payload_shape_invalid")
        canonical = canonical_json(parsed, maximum=MAX_BRS_OWNER_RESULT_BYTES)
    except BRSOwnerResultDeliveryError:
        raise
    except RSILearningError as exc:
        raise BRSOwnerResultDeliveryError("payload_invalid") from exc
    except (UnicodeError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise BRSOwnerResultDeliveryError("payload_invalid") from exc
    if canonical != raw:
        _fail("payload_noncanonical")
    return parsed


def _journal(result: NativeProducerBundleTransactionResult) -> ProducerBundlePublicationJournal:
    if type(result) is not NativeProducerBundleTransactionResult:
        _fail("transaction_invalid")
    status = result.publication_status
    if status not in _STATUSES:
        _fail("status_invalid")
    journal = result.published_journal if status == "published" else result.terminal_journal
    if type(journal) is not ProducerBundlePublicationJournal:
        _fail("journal_missing")
    try:
        parsed = ProducerBundlePublicationJournal.from_dict(journal.to_dict())
    except Exception as exc:
        raise BRSOwnerResultDeliveryError("journal_invalid") from exc
    if parsed.state != status:
        _fail("journal_status_mismatch")
    return parsed


def build_brs_owner_result_payload(
    result: NativeProducerBundleTransactionResult,
    request: BRSOwnerPublicationRequest,
    handoff: BRSSelectedChildHandoff,
) -> bytes:
    """Build detached exact-result bytes from one owner transaction.

    The owner caller supplies the already validated mailbox request and selected handoff;
    this helper only projects immutable evidence.  It does not invoke any callback or
    inspect a workspace/ledger.
    """
    if type(request) is not BRSOwnerPublicationRequest:
        _fail("request_invalid")
    if type(handoff) is not BRSSelectedChildHandoff:
        _fail("handoff_invalid")
    try:
        request = BRSOwnerPublicationRequest(
            request.run_id, request.episode_id, request.handoff_sha256,
            request.payload, request.request_sha256,
        )
        handoff = BRSSelectedChildHandoff(**BRSSelectedChildHandoff.to_dict(handoff))
    except (AttributeError, TypeError, ValueError, RSILearningError) as exc:
        raise BRSOwnerResultDeliveryError("identity_invalid") from exc
    journal = _journal(result)
    if (request.run_id, request.episode_id, request.handoff_sha256) != (
        handoff.run_id, handoff.episode_id, handoff.sha256,
    ):
        _fail("request_handoff_mismatch")
    try:
        request_evidence = _request_payload(request.payload, request.run_id)
    except Exception as exc:
        raise BRSOwnerResultDeliveryError("request_invalid") from exc
    native_plan_sha256 = request_evidence["native_plan_sha256"]
    _sha(native_plan_sha256, "native_plan_sha256")
    if (journal.run_id != handoff.run_id or journal.task_id != handoff.episode_id
            or journal.native_execution_receipt_sha256 is None):
        _fail("journal_binding_mismatch")
    admitted = result.admitted_candidate_ids
    if type(admitted) is not tuple or any(type(item) is not str or not item for item in admitted):
        _fail("candidate_ids_invalid")
    if len(set(admitted)) != len(admitted):
        _fail("candidate_ids_duplicate")
    if result.publication_status == "published" and not admitted:
        _fail("published_candidates_missing")
    if result.publication_status == "all_rejected" and admitted:
        _fail("rejected_candidates_present")
    payload = {
        "protocol": _PROTOCOL,
        "run_id": handoff.run_id,
        "episode_id": handoff.episode_id,
        "handoff_sha256": handoff.sha256,
        "request_sha256": request.request_sha256,
        "selected_request_sha256": handoff.request_sha256,
        "native_plan_sha256": native_plan_sha256,
        "publication_status": result.publication_status,
        "journal_sha256": journal.digest(),
        "terminal_marker_sha256": journal.terminal_marker_sha256,
        "archive_after_sha256": journal.archive_after_sha256,
        "state_after_sha256": journal.state_after_sha256,
        "admitted_candidate_ids": list(admitted),
    }
    return canonical_json(payload, maximum=MAX_BRS_OWNER_RESULT_BYTES)


@dataclass(frozen=True, slots=True)
class BRSOwnerResultDelivery:
    """Detached owner result delivered to the selected worker."""

    run_id: str
    episode_id: str
    handoff_sha256: str
    request_sha256: str
    selected_request_sha256: str
    native_plan_sha256: str
    publication_status: str
    journal_sha256: str
    terminal_marker_sha256: str
    archive_after_sha256: str
    state_after_sha256: str
    admitted_candidate_ids: tuple[str, ...]
    response_sha256: str
    payload_sha256: str

    def __post_init__(self) -> None:
        _id(self.run_id, "run_id")
        _id(self.episode_id, "episode_id")
        if self.episode_id != f"{self.run_id}-practice-0-0" and "-practice-" not in self.episode_id:
            _fail("episode_identity_invalid")
        for field in (
            "handoff_sha256", "request_sha256", "selected_request_sha256", "native_plan_sha256", "journal_sha256",
            "terminal_marker_sha256", "archive_after_sha256", "state_after_sha256",
            "response_sha256", "payload_sha256",
        ):
            _sha(getattr(self, field), field)
        if self.publication_status not in _STATUSES:
            _fail("status_invalid")
        if type(self.admitted_candidate_ids) is not tuple or any(
            type(item) is not str or not item for item in self.admitted_candidate_ids
        ):
            _fail("candidate_ids_invalid")
        if len(set(self.admitted_candidate_ids)) != len(self.admitted_candidate_ids):
            _fail("candidate_ids_duplicate")
        if self.publication_status == "published" and not self.admitted_candidate_ids:
            _fail("published_candidates_missing")
        if self.publication_status == "all_rejected" and self.admitted_candidate_ids:
            _fail("rejected_candidates_present")

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id, "episode_id": self.episode_id,
            "handoff_sha256": self.handoff_sha256, "request_sha256": self.request_sha256,
            "selected_request_sha256": self.selected_request_sha256,
            "native_plan_sha256": self.native_plan_sha256,
            "publication_status": self.publication_status,
            "journal_sha256": self.journal_sha256,
            "terminal_marker_sha256": self.terminal_marker_sha256,
            "archive_after_sha256": self.archive_after_sha256,
            "state_after_sha256": self.state_after_sha256,
            "admitted_candidate_ids": list(self.admitted_candidate_ids),
            "response_sha256": self.response_sha256,
            "payload_sha256": self.payload_sha256,
        }


class BRSOwnerResultSettlement:
    """One-shot worker settlement gate for an exact detached owner result."""

    __slots__ = ("_delivery", "_state")

    def __init__(self, delivery: BRSOwnerResultDelivery) -> None:
        if type(delivery) is not BRSOwnerResultDelivery:
            _fail("delivery_invalid")
        self._delivery = delivery
        self._state = "pending"

    @property
    def delivery(self) -> BRSOwnerResultDelivery:
        return self._delivery

    @property
    def status(self) -> str:
        return self._state

    def settle(self, callback: Callable[[BRSOwnerResultDelivery], object]) -> object:
        """Consume once; callback failure becomes unknown and cannot be retried."""
        if not callable(callback):
            _fail("settlement_callback_invalid")
        if self._state != "pending":
            _fail("settlement_unavailable")
        self._state = "inflight"
        try:
            # Do not expose the retained object itself: frozen dataclasses can still
            # be mutated with object.__setattr__ by a hostile callback.
            callback_delivery = replace(self._delivery)
            value = callback(callback_delivery)
        except BaseException as exc:
            self._state = "unknown"
            raise BRSOwnerResultDeliveryError("settlement_unknown") from exc
        self._state = "settled"
        return value


def deliver_brs_owner_result(
    response: BRSOwnerPublicationResponse,
    request: BRSOwnerPublicationRequest,
    handoff: BRSSelectedChildHandoff,
    *,
    expected_native_plan_sha256: str | None = None,
    expected_journal_sha256: str | None = None,
) -> BRSOwnerResultSettlement:
    """Verify exact mailbox identity and return a one-shot settlement gate."""
    if type(response) is not BRSOwnerPublicationResponse:
        _fail("response_invalid")
    if type(request) is not BRSOwnerPublicationRequest:
        _fail("request_invalid")
    if type(handoff) is not BRSSelectedChildHandoff:
        _fail("handoff_invalid")
    try:
        request = BRSOwnerPublicationRequest(
            request.run_id, request.episode_id, request.handoff_sha256,
            request.payload, request.request_sha256,
        )
        handoff = BRSSelectedChildHandoff(**BRSSelectedChildHandoff.to_dict(handoff))
    except (AttributeError, TypeError, ValueError, RSILearningError) as exc:
        raise BRSOwnerResultDeliveryError("identity_invalid") from exc
    try:
        # Frozen DTOs can still be changed with object.__setattr__.  Rebuild the
        # transport response before observing identity or payload bytes so a forged
        # response cannot cross this boundary.
        response = BRSOwnerPublicationResponse(
            response.run_id, response.episode_id, response.handoff_sha256,
            response.request_sha256, response.payload, response.response_sha256,
        )
    except (AttributeError, TypeError, ValueError, RSILearningError) as exc:
        raise BRSOwnerResultDeliveryError("response_invalid") from exc
    if (response.run_id, response.episode_id, response.handoff_sha256, response.request_sha256) != (
        request.run_id, request.episode_id, request.handoff_sha256, request.request_sha256,
    ):
        _fail("response_binding_mismatch")
    if (request.run_id, request.episode_id, request.handoff_sha256) != (
        handoff.run_id, handoff.episode_id, handoff.sha256,
    ):
        _fail("request_handoff_mismatch")
    parsed = _canonical_payload(response.payload)
    if parsed["protocol"] != _PROTOCOL:
        _fail("protocol_invalid")
    if (parsed["run_id"], parsed["episode_id"], parsed["handoff_sha256"], parsed["request_sha256"], parsed["selected_request_sha256"]) != (
        handoff.run_id, handoff.episode_id, handoff.sha256, request.request_sha256, handoff.request_sha256,
    ):
        _fail("payload_binding_mismatch")
    if expected_native_plan_sha256 is not None:
        _sha(expected_native_plan_sha256, "expected_native_plan_sha256")
        if parsed["native_plan_sha256"] != expected_native_plan_sha256:
            _fail("preparation_mismatch")
    if expected_journal_sha256 is not None:
        _sha(expected_journal_sha256, "expected_journal_sha256")
        if parsed["journal_sha256"] != expected_journal_sha256:
            _fail("journal_mismatch")
    delivery = BRSOwnerResultDelivery(
        run_id=parsed["run_id"], episode_id=parsed["episode_id"],
        handoff_sha256=parsed["handoff_sha256"], request_sha256=parsed["request_sha256"],
        selected_request_sha256=parsed["selected_request_sha256"],
        native_plan_sha256=parsed["native_plan_sha256"], publication_status=parsed["publication_status"],
        journal_sha256=parsed["journal_sha256"], terminal_marker_sha256=parsed["terminal_marker_sha256"],
        archive_after_sha256=parsed["archive_after_sha256"], state_after_sha256=parsed["state_after_sha256"],
        admitted_candidate_ids=tuple(parsed["admitted_candidate_ids"]),
        response_sha256=response.response_sha256,
        payload_sha256=hashlib.sha256(response.payload).hexdigest(),
    )
    return BRSOwnerResultSettlement(delivery)


__all__ = [
    "MAX_BRS_OWNER_RESULT_BYTES",
    "BRSOwnerResultDelivery",
    "BRSOwnerResultDeliveryError",
    "BRSOwnerResultSettlement",
    "build_brs_owner_result_payload",
    "deliver_brs_owner_result",
]
