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
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import FunctionType

from .native_trusted_scheduler import _NativeTrustedPythonProducerPreparation
from .producer_bundle_transaction import NativeProducerBundleTransactionResult
from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
from .rsi_learning import RSILearningError
from .rsi_python_brs_handoff import BRSSelectedChildHandoff
from .rsi_python_brs_native_dispatch import (
    _original_control,
    _rejection_committed,
    _run_original_brs_native_publication,
)
from .rsi_python_brs_publication_mailbox import (
    BRSOwnerPublicationMailbox,
    BRSOwnerPublicationRequest,
    BRSOwnerPublicationResponse,
)
from .rsi_python_brs_result_delivery import build_brs_owner_result_payload

_OWNER_STAMP_MODULE_NAMES: tuple[str, ...] | None = None


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
    worker_receipt_observed: bool = True

    def __post_init__(self) -> None:
        if type(self.worker_receipt_observed) is not bool:
            _fail("receipt_invalid")

    def __getattribute__(self, name: str):
        """Keep an unacknowledged transaction out of settlement callers.

        The owner may retain the detached response bytes as recovery evidence when
        a worker abandons the mailbox after generation.  That observation does not
        constitute a worker receipt, however, so exposing the transaction would let
        a caller accidentally continue into settlement or ordinal advancement.
        The explicit receipt bit remains readable for recovery/audit code; only the
        authority-bearing transaction field is fail-closed.
        """
        if name == "transaction":
            receipt = object.__getattribute__(self, "worker_receipt_observed")
            if receipt is not True:
                _fail("worker_receipt_unknown")
        return object.__getattribute__(self, name)


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


def _clear_owner_observation_caches(owner: object) -> None:
    """Forget transaction-scoped observations after a caller callback returns.

    The callback is outside the trusted observation boundary and may replace a
    fingerprinted dependency.  Clear both bounded transaction caches before the
    canonical owner gate runs so that replacement cannot be hidden by a value
    captured before the callback.
    """
    from . import rsi_brs_publication_lineage as lineage

    policy_cache = getattr(lineage._POLICY_OBSERVATION_LOCAL, "cache", None)
    if type(policy_cache) is dict:
        policy_cache.clear()
    controller = getattr(owner, "_controller", None)
    local = getattr(controller, "_python_admission_brs_local", None)
    scope = getattr(local, "full_gate_scope", None)
    if (type(scope) is tuple and len(scope) == 3 and type(scope[2]) is dict):
        scope[2].clear()


def _owner_dependency_stamp() -> tuple[tuple[str, tuple[tuple[str, int, int], ...]], ...]:
    """Return a cheap replacement stamp for live Lunar function dependencies.

    Full policy fingerprints are intentionally expensive.  A mailbox callback is
    outside that trusted boundary, so we only invalidate the transaction caches
    when it actually replaces a module or class function (the mutation shape the
    policy gate protects).  The subsequent canonical owner gate still computes
    the complete fingerprint after invalidation.
    """
    global _OWNER_STAMP_MODULE_NAMES
    if _OWNER_STAMP_MODULE_NAMES is None:
        _OWNER_STAMP_MODULE_NAMES = tuple(sorted(
            name for name in sys.modules if name.startswith("lunar_evolution")
        ))
    modules: list[tuple[str, tuple[tuple[str, int, int], ...]]] = []
    for module_name in _OWNER_STAMP_MODULE_NAMES:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        entries: list[tuple[str, int, int]] = []
        for name, value in vars(module).items():
            if isinstance(value, FunctionType):
                entries.append((name, id(value), id(value.__code__)))
            elif isinstance(value, type):
                for method_name, method in vars(value).items():
                    if isinstance(method, FunctionType):
                        entries.append((value.__qualname__ + "." + method_name,
                                        id(method), id(method.__code__)))
        if entries:
            modules.append((module_name, tuple(sorted(entries))))
    return tuple(modules)


def run_brs_owner_publication_mailbox(
    owner: object,
    mailbox: BRSOwnerPublicationMailbox,
    original_preparation: _NativeTrustedPythonProducerPreparation,
    *,
    check: Callable[[], None],
    timeout: float = 0.05,
    _terminal_lifecycle: object = None,
) -> BRSOwnerMailboxBridgeResult:
    """Serve one owner mailbox under one bounded policy observation scope.

    Mailbox observation performs several owner identity checks while a worker
    receipt is being delivered.  Those checks are still complete and fail closed,
    but they share the immutable policy graph for this one owner transaction.  The
    scope is thread-local and is discarded when this call returns; later resume or
    mailbox calls therefore perform a fresh policy observation.
    """
    from contextlib import nullcontext

    from .rsi_brs_publication_lineage import _policy_observation_scope

    # The owner callback and the terminal admission service both re-observe the
    # selected owner gate while the one-shot mailbox transaction is in flight.
    # Keep one strict observation cache for this bounded transaction so those
    # callbacks do not repeatedly walk the immutable runtime manifest.  The
    # cache key includes the live checkpoint head/payload, and the scope is
    # discarded before any later child, resume, or mailbox transaction.
    controller = getattr(owner, "_controller", None)
    full_gate = getattr(controller, "_python_admission_brs_full_gate_scope", None)
    wave = getattr(owner, "_wave", None)
    handoff = getattr(owner, "_handoff", None)
    gate_scope = (full_gate(wave, handoff) if callable(full_gate) else nullcontext())
    with gate_scope, _policy_observation_scope():
        result = _run_brs_owner_publication_mailbox(
            owner, mailbox, original_preparation, check=check, timeout=timeout,
            _terminal_lifecycle=_terminal_lifecycle,
        )
    # The transaction-scoped caches above intentionally cover the worker wait
    # and native publication path only.  A response can be delivered while a
    # dependency is replaced before the bridge returns, so the final owner
    # check must run after both scopes have been cleared and rebuild the live
    # policy/full-gate observations.
    # The callback is intentionally not repeated here.  ``service`` and the
    # post-receipt path already ran it; repeating it would change the callback's
    # observable contract and can run a worker-facing budget check twice.
    # ``check`` is caller supplied and may intentionally be a lightweight
    # fixture callback.  Re-run the canonical owner gate here so a dependency
    # changed after publication cannot be hidden by that callback or by the
    # transaction-scoped full-gate cache.
    if owner._rejection_ready_state == "committed":
        _rejection_committed(owner)
    elif owner._reserved_prefix is not None and owner._phase == "terminal":
        _BRSLineageCheckpointOwner._check_owner(owner)
    else:
        _BRSLineageCheckpointOwner._success_fixed(owner)
    return result


def _run_brs_owner_publication_mailbox(
    owner: object,
    mailbox: BRSOwnerPublicationMailbox,
    original_preparation: _NativeTrustedPythonProducerPreparation,
    *,
    check: Callable[[], None],
    timeout: float = 0.05,
    _terminal_lifecycle: object = None,
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
            dependency_stamp = _owner_dependency_stamp()
            check()
            if dependency_stamp != _owner_dependency_stamp():
                _clear_owner_observation_caches(owner)
            _original_control(owner)
            # Mailbox check callbacks run outside its condition. Recheck the original
            # source/policy and running claim before both dispatch and byte delivery.
            if owner._rejection_ready_state == "committed":
                _rejection_committed(owner)
            elif owner._reserved_prefix is not None and owner._phase == "terminal":
                from .rsi_python_brs_terminal_lifecycle import BRSOwnerTerminalLifecycle

                if (type(_terminal_lifecycle) is not BRSOwnerTerminalLifecycle
                        or _terminal_lifecycle._owner is not owner
                        or _terminal_lifecycle._mailbox is not mailbox):
                    _fail("published_lifecycle_required")
                BRSOwnerTerminalLifecycle._assert_published_admission(_terminal_lifecycle)
                _BRSLineageCheckpointOwner._check_owner(owner)
            else:
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
            if result.publication_status == "all_rejected":
                from .rsi_python_brs_terminal_lifecycle import BRSOwnerTerminalLifecycle

                if (type(_terminal_lifecycle) is not BRSOwnerTerminalLifecycle
                        or _terminal_lifecycle._owner is not owner
                        or _terminal_lifecycle._mailbox is not mailbox):
                    _fail("rejection_lifecycle_required")
                BRSOwnerTerminalLifecycle._service_rejection_admission(_terminal_lifecycle, timeout=timeout)
                _rejection_committed(owner)
            elif result.publication_status == "published" and owner._reserved_prefix is not None:
                from .rsi_python_brs_terminal_lifecycle import BRSOwnerTerminalLifecycle

                if (type(_terminal_lifecycle) is not BRSOwnerTerminalLifecycle
                        or _terminal_lifecycle._owner is not owner
                        or _terminal_lifecycle._mailbox is not mailbox):
                    _fail("published_lifecycle_required")
                BRSOwnerTerminalLifecycle._service_published_admission(_terminal_lifecycle, timeout=timeout)
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
        # ``service`` publishes the response before the worker has necessarily
        # consumed it.  Persisting ``transport_observed`` during that window
        # would record a delivered response with an unknown worker receipt and
        # make a later settled read reject the original transport.  Wait for the
        # mailbox's one-shot receipt bit under a bounded deadline; the worker
        # only changes this bit after validating the detached response, so this
        # does not grant any publication or settlement authority.
        deadline = time.monotonic() + timeout
        while True:
            status, accepted, request_fields, response_fields = BRSOwnerPublicationMailbox._observation_snapshot(mailbox)
            # A worker may reject the delivered DTO after the owner has
            # published it.  ``abandoned`` is then a terminal transport
            # observation with an intentionally false receipt bit; waiting for
            # ``accepted`` would poll the fixture evidence again and can turn a
            # valid unknown receipt into a spurious timeout/queue failure.
            if accepted or status == "abandoned":
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _fail("worker_receipt_unknown")
            time.sleep(min(0.001, remaining))
        # Re-run the full owner/source check only after the worker has yielded
        # the receipt.  The check may scan immutable staging evidence; running
        # it on every poll would starve the worker that is needed to flip the
        # receipt bit on CPython.
        dependency_stamp = _owner_dependency_stamp()
        check()
        if dependency_stamp != _owner_dependency_stamp():
            _clear_owner_observation_caches(owner)
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
        return BRSOwnerMailboxBridgeResult(transaction, response, accepted)
    except BaseException:
        owner._poisoned = True
        raise
