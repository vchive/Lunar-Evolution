"""Private BRS owner-side mailbox composition.

This module composes the already validated, provider-free pieces without exposing a
public BRS route.  The selected worker submits a detached request and waits on the
one-shot mailbox; only the original owner thread runs the private native transaction.
The response is a bounded status summary and never an admission, lineage, or
publication capability.  Public native BRS and production admission remain refused.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from .candidate_evaluation_spec import canonical_json
from .native_trusted_scheduler import _NativeTrustedPythonProducerPreparation
from .producer_bundle_publication import ProducerBundlePublicationJournal
from .producer_bundle_transaction import NativeProducerBundleTransactionResult
from .rsi_learning import RSILearningError
from .rsi_python_brs_native_dispatch import (
    _original_control,
    _run_original_brs_native_publication,
)
from .rsi_python_brs_publication_mailbox import (
    BRSOwnerPublicationMailbox,
    BRSOwnerPublicationRequest,
)


class BRSOwnerMailboxBridgeError(RSILearningError):
    """Fixed-code refusal for an invalid private owner/mailbox composition."""

    def __init__(self, code: str) -> None:
        super().__init__("rsi_python_brs_owner_bridge_" + code)


def _fail(code: str) -> None:
    raise BRSOwnerMailboxBridgeError(code)


@dataclass(frozen=True, slots=True)
class BRSOwnerMailboxBridgeResult:
    """Owner result plus the detached response bytes delivered to the worker.

    ``response_payload`` is an observation-only summary.  It intentionally omits
    drafts, paths, strategy objects, lineage owner data and any admission token.
    """

    transaction: NativeProducerBundleTransactionResult
    response_payload: bytes


def _response_payload(result: NativeProducerBundleTransactionResult) -> bytes:
    if type(result) is not NativeProducerBundleTransactionResult:
        _fail("transaction_invalid")
    journal = result.published_journal
    ids = result.admitted_candidate_ids
    if (result.publication_status != "published" or type(journal) is not ProducerBundlePublicationJournal
            or journal.state != "published" or type(ids) is not tuple or not ids
            or any(type(value) is not str or not value for value in ids)):
        _fail("success_required")
    # The worker receives only detached, bounded observation data.  It cannot use
    # this summary to claim publication authority or mutate controller state.
    return canonical_json({
        "protocol": "lunar-rsi-brs-owner-result-v1",
        "publication_status": "published",
        "admitted_candidate_ids": list(ids),
    }, maximum=8 * 1024 * 1024)


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
    delivery is surfaced as an unknown owner-side obligation by the mailbox.
    """
    if type(mailbox) is not BRSOwnerPublicationMailbox:
        _fail("mailbox_invalid")
    if type(original_preparation) is not _NativeTrustedPythonProducerPreparation:
        _fail("preparation_invalid")
    if not callable(check):
        _fail("check_invalid")
    # This validates exact owner class, original context, and monotonic control
    # before waiting for a worker request.  It performs no filesystem observation.
    _original_control(owner)
    _require_disabled_policy(owner)
    result_holder: list[NativeProducerBundleTransactionResult] = []

    def handle(request: BRSOwnerPublicationRequest) -> bytes:
        if type(request) is not BRSOwnerPublicationRequest:
            _fail("request_invalid")
        if result_holder:
            _fail("duplicate_request")
        result = _run_original_brs_native_publication(
            owner, request, original_preparation=original_preparation,
        )
        result_holder.append(result)
        return _response_payload(result)

    served = mailbox.service(handle, check=check, timeout=timeout)
    if served is not True or len(result_holder) != 1:
        _fail("mailbox_not_served")
    response = _response_payload(result_holder[0])
    return BRSOwnerMailboxBridgeResult(result_holder[0], response)
