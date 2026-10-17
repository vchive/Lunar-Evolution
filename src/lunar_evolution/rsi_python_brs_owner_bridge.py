"""Private BRS owner-side mailbox composition.

This module composes the already validated, provider-free pieces without exposing a
public BRS route.  The selected worker submits a detached request and waits on the
one-shot mailbox; only the original owner thread runs the private native transaction.
The response contains the existing exact result envelope, without granting admission,
lineage or publication authority. Public native BRS and production admission remain refused.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass

from .native_trusted_scheduler import _NativeTrustedPythonProducerPreparation
from .producer_bundle_transaction import NativeProducerBundleTransactionResult
from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
from .rsi_learning import RSILearningError
from .rsi_python_brs_handoff import BRSSelectedChildHandoff
from .rsi_python_brs_native_dispatch import (
    _original_control,
    _run_original_brs_native_publication,
)
from .rsi_python_brs_publication_mailbox import (
    BRSOwnerPublicationMailbox,
    BRSOwnerPublicationRequest,
    BRSOwnerPublicationResponse,
)
from .rsi_python_brs_result_delivery import build_brs_owner_result_payload


class BRSOwnerMailboxBridgeError(RSILearningError):
    """Fixed-code refusal for an invalid private owner/mailbox composition."""

    def __init__(self, code: str) -> None:
        super().__init__("rsi_python_brs_owner_bridge_" + code)


def _fail(code: str) -> None:
    raise BRSOwnerMailboxBridgeError(code)


@dataclass(frozen=True, slots=True)
class BRSOwnerMailboxBridgeResult:
    """Owner result plus the detached response bytes delivered to the worker.

    ``response_payload`` contains the exact detached result bytes delivered. It omits
    drafts, paths, strategy objects, lineage owner data and any admission token.
    """

    transaction: NativeProducerBundleTransactionResult
    response_payload: bytes


def _response_payload(
    result: NativeProducerBundleTransactionResult,
    request: BRSOwnerPublicationRequest,
    handoff: BRSSelectedChildHandoff,
) -> bytes:
    return build_brs_owner_result_payload(result, request, handoff)


def _require_disabled_policy(owner: object) -> None:
    """Keep this opt-in seam behind the non-authorizing BRS policy pins."""
    try:
        policy_bytes = owner._policy_bytes
        if type(policy_bytes) is not bytes:
            raise ValueError("policy bytes")
        policy = json.loads(policy_bytes)
        if (type(policy) is not dict or policy.get("online_publication") is not False
                or policy.get("production_admission") is not False):
            raise ValueError("publication policy enabled")
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BRSOwnerMailboxBridgeError("policy_invalid") from exc


def _require_original_mailbox(owner: _BRSLineageCheckpointOwner, mailbox: BRSOwnerPublicationMailbox) -> None:
    """Bind this transport to the original selected capture before any durable write."""
    handoff = owner._handoff
    identity = mailbox._identity
    if (type(identity) is not tuple or len(identity) != 3
            or any(type(value) is not str for value in identity)
            or identity != (owner._run_id, owner._request.episode_id, handoff.sha256)
            or type(mailbox._owner_thread) is not int or mailbox._owner_thread != owner._thread
            or type(mailbox._worker_thread) is not int or mailbox._worker_thread <= 0
            or mailbox._worker_thread == owner._thread
            or type(mailbox._expected_head) is not str or mailbox._expected_head != handoff.head_sha256
            or type(mailbox._expected_state) is not str or mailbox._expected_state != handoff.state_sha256):
        _fail("mailbox_binding_invalid")
    with mailbox._condition:
        if (type(mailbox._status) is not str or mailbox._status not in {"open", "queued"}
                or mailbox._closed is not False or mailbox._servicing is not False):
            _fail("mailbox_unavailable")


def run_brs_owner_publication_mailbox(
    owner: object,
    mailbox: BRSOwnerPublicationMailbox,
    original_preparation: _NativeTrustedPythonProducerPreparation,
    *,
    check: Callable[[], None],
    timeout: float = 0.05,
) -> BRSOwnerMailboxBridgeResult:
    """Serve one selected-worker request on the original owner thread.

    The helper is deliberately private and opt-in.  It does not create a mailbox,
    refresh captured pins, retry an ambiguous transaction, settle the worker result,
    advance a sibling ordinal, or enable public native BRS.  A failed response
    delivery is surfaced as an unknown owner-side obligation by the mailbox. The
    exact selected recovery fence is durable before mailbox service, and remains
    after empty/failed service or publication success. Consumption needs explicit
    independent terminal evidence; a joined thread supplies no process evidence.
    """
    if type(mailbox) is not BRSOwnerPublicationMailbox:
        _fail("mailbox_invalid")
    if type(original_preparation) is not _NativeTrustedPythonProducerPreparation:
        _fail("preparation_invalid")
    if not callable(check):
        _fail("check_invalid")
    if (type(timeout) is not int and type(timeout) is not float) or (
        timeout < 0 or timeout > 60 or not math.isfinite(timeout)
    ):
        _fail("timeout_invalid")
    # This validates exact owner class, original context, and monotonic control
    # before waiting for a worker request.  It performs no filesystem observation.
    _original_control(owner)
    _require_disabled_policy(owner)
    _require_original_mailbox(owner, mailbox)
    _BRSLineageCheckpointOwner.retain_reconcile_obligation(owner)
    try:
        status, accepted, request_fields, _response_fields = BRSOwnerPublicationMailbox._observation_snapshot(mailbox)
        _BRSLineageCheckpointOwner.retain_mailbox_observation(
            owner, "owner_capture", mailbox_state=status, worker_receipt_observed=accepted,
            request=None if request_fields is None else BRSOwnerPublicationRequest(*request_fields),
        )
        handoff_bytes = owner._handoff_bytes
        result_holder: list[tuple[NativeProducerBundleTransactionResult, bytes]] = []
        generated_fields_holder: list[tuple] = []

        def observe() -> None:
            check()
            _original_control(owner)
            # Mailbox check callbacks run outside its condition. Recheck the original
            # source/policy and running claim before both dispatch and byte delivery.
            _BRSLineageCheckpointOwner._success_fixed(owner)

        def handle(request: BRSOwnerPublicationRequest) -> bytes:
            if type(request) is not BRSOwnerPublicationRequest:
                _fail("request_invalid")
            if result_holder:
                _fail("duplicate_request")
            request_fields = (request.run_id, request.episode_id, request.handoff_sha256,
                              request.payload, request.request_sha256)
            status, accepted, captured_request, _response_fields = BRSOwnerPublicationMailbox._observation_snapshot(mailbox)
            if captured_request != request_fields:
                _fail("request_snapshot_drift")
            _BRSLineageCheckpointOwner.retain_mailbox_observation(
                owner, "request_observed", mailbox_state=status, worker_receipt_observed=accepted,
                request=BRSOwnerPublicationRequest(*request_fields),
            )
            result = _run_original_brs_native_publication(
                owner, request, original_preparation=original_preparation,
            )
            # Native execution receives its own request DTO. Build against the
            # immutable entry capture, never that DTO or a mutable latest handoff.
            payload = _response_payload(
                result, BRSOwnerPublicationRequest(*request_fields),
                BRSSelectedChildHandoff(**json.loads(handoff_bytes)),
            )
            result_holder.append((result, payload))
            return payload

        def generated(request: BRSOwnerPublicationRequest, response: BRSOwnerPublicationResponse) -> None:
            status, accepted, request_fields, response_fields = BRSOwnerPublicationMailbox._observation_snapshot(mailbox)
            if response_fields is not None or request_fields != (
                request.run_id, request.episode_id, request.handoff_sha256, request.payload, request.request_sha256,
            ):
                _fail("response_snapshot_drift")
            _BRSLineageCheckpointOwner.retain_mailbox_observation(
                owner, "response_generated", mailbox_state=status, worker_receipt_observed=accepted,
                request=request, response=response,
            )
            generated_fields_holder.append((
                response.run_id, response.episode_id, response.handoff_sha256,
                response.request_sha256, response.payload, response.response_sha256,
            ))

        served = BRSOwnerPublicationMailbox.service(
            mailbox, handle, check=observe, timeout=timeout, _response_observer=generated,
        )
        if served is not True or len(result_holder) != 1:
            _fail("mailbox_not_served")
        status, accepted, request_fields, response_fields = BRSOwnerPublicationMailbox._observation_snapshot(mailbox)
        if request_fields is None or len(generated_fields_holder) != 1:
            _fail("transport_snapshot_invalid")
        generated_fields = generated_fields_holder[0]
        if ((response_fields is None and status != "abandoned")
                or (response_fields is not None and response_fields != generated_fields)):
            _fail("transport_snapshot_invalid")
        _BRSLineageCheckpointOwner.retain_mailbox_observation(
            owner, "transport_observed", mailbox_state=status, worker_receipt_observed=accepted,
            request=BRSOwnerPublicationRequest(*request_fields), response=BRSOwnerPublicationResponse(*generated_fields),
        )
        transaction, response = result_holder[0]
        return BRSOwnerMailboxBridgeResult(transaction, response)
    except BaseException:
        owner._poisoned = True
        raise
