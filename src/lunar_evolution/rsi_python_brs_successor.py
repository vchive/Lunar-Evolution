"""Pure serial-successor checks for a bounded native BRS wave.

This module only advances a detached preflight projection after the owner has
observed an exact native terminal and acknowledged its lineage checkpoint.  It
does not open a ledger, inspect a workspace, launch a worker, reserve budget,
publish a candidate, or grant a handoff.  The caller must still bind the
returned selection to a *fresh* owner context and nonce.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .rsi_gateway import SolverRequest
from .rsi_python_brs_child_policy import (
    MAX_BRS_CHILD_ATTEMPTS,
    BRSChildPolicyError,
    BRSNativeChildPreflight,
    BRSNativeChildSelection,
    preflight_native_brs_child,
)
from .rsi_python_brs_handoff import (
    BRSChildHandoffContext,
    BRSChildHandoffError,
    BRSSelectedChildHandoff,
    validate_brs_child_handoff,
)
from .rsi_store import NativeEpisodeClaim, RSILedger

_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_OUTCOMES = frozenset({"completed", "rejected"})


class BRSOrdinalSuccessorError(BRSChildPolicyError):
    """Stable refusal for incomplete or mismatched serial-successor evidence."""

    def __init__(self, code: str) -> None:
        super().__init__("successor_" + code)


def _fail(code: str) -> None:
    raise BRSOrdinalSuccessorError(code)


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail(f"{field}_invalid")
    return value


@dataclass(frozen=True, slots=True)
class BRSOrdinalCompletion:
    """Owner-observed terminal evidence for exactly one selected ordinal.

    ``owner_lineage_ack_sha256`` is deliberately separate from
    ``native_terminal_sha256``: a worker result or a ready ACK alone cannot
    authorize a successor.  ``verified_head_sha256`` is the captured owner
    head against which a later fresh handoff must be bound.
    """

    run_id: str
    wave: int
    ordinal: int
    episode_id: str
    request_sha256: str
    outcome: Literal["completed", "rejected"]
    result_sha256: str
    native_terminal_sha256: str
    owner_lineage_ack_sha256: str
    verified_head_sha256: str

    def __post_init__(self) -> None:
        if type(self.run_id) is not str or _ID.fullmatch(self.run_id) is None:
            _fail("run_id_invalid")
        if type(self.wave) is not int or self.wave < 0:
            _fail("wave_invalid")
        if type(self.ordinal) is not int or self.ordinal < 0:
            _fail("ordinal_invalid")
        if type(self.episode_id) is not str or _ID.fullmatch(self.episode_id) is None:
            _fail("episode_id_invalid")
        if self.episode_id != f"{self.run_id}-practice-{self.wave}-{self.ordinal}":
            _fail("episode_identity_invalid")
        if self.outcome not in _OUTCOMES:
            _fail("outcome_invalid")
        for field in (
            "request_sha256", "result_sha256", "native_terminal_sha256",
            "owner_lineage_ack_sha256", "verified_head_sha256",
        ):
            _digest(getattr(self, field), field)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "wave": self.wave,
            "ordinal": self.ordinal,
            "episode_id": self.episode_id,
            "request_sha256": self.request_sha256,
            "outcome": self.outcome,
            "result_sha256": self.result_sha256,
            "native_terminal_sha256": self.native_terminal_sha256,
            "owner_lineage_ack_sha256": self.owner_lineage_ack_sha256,
            "verified_head_sha256": self.verified_head_sha256,
        }


@dataclass(frozen=True, slots=True)
class BRSOrdinalSuccessor:
    """Detached post-terminal projection and optional next selection."""

    preflight: BRSNativeChildPreflight
    completion: BRSOrdinalCompletion
    next_selection: BRSNativeChildSelection | None

    def __post_init__(self) -> None:
        if type(self.preflight) is not BRSNativeChildPreflight:
            _fail("preflight_invalid")
        if type(self.completion) is not BRSOrdinalCompletion:
            _fail("completion_invalid")
        if self.next_selection is not None and type(self.next_selection) is not BRSNativeChildSelection:
            _fail("selection_invalid")


@dataclass(frozen=True, slots=True)
class BRSOrdinalSuccessorDispatch:
    """Result of one owner-controlled terminal-to-successor dispatch boundary.

    ``dispatch_result`` is an opaque provider-free fixture observation.  It is
    deliberately not interpreted as a solver result, publication receipt or
    ownership token.  A failed dispatch leaves the durable claim in ``started``
    state and must be reconciled by a separate recovery path.
    """

    status: Literal["dispatched", "wave_complete"]
    successor: BRSOrdinalSuccessor
    handoff: BRSSelectedChildHandoff | None
    claim: NativeEpisodeClaim | None
    dispatch_result: object | None = None

    def __post_init__(self) -> None:
        if self.status not in {"dispatched", "wave_complete"}:
            _fail("dispatch_status_invalid")
        if type(self.successor) is not BRSOrdinalSuccessor:
            _fail("dispatch_successor_invalid")
        if self.status == "wave_complete":
            if self.successor.next_selection is not None or self.handoff is not None or self.claim is not None:
                _fail("dispatch_completion_shape_invalid")
        else:
            if (self.successor.next_selection is None
                    or type(self.handoff) is not BRSSelectedChildHandoff
                    or type(self.claim) is not NativeEpisodeClaim):
                _fail("dispatch_started_shape_invalid")


def advance_brs_ordinal(
    preflight: BRSNativeChildPreflight,
    completion: BRSOrdinalCompletion,
) -> BRSOrdinalSuccessor:
    """Advance one exact ordinal without copying sibling execution state.

    The completion must match the first pending intent.  The returned preflight
    appends only that episode, increments the two per-episode counters, and
    preserves the original M0/root snapshot, plan, and reservation.  It does
    not carry forward a nonce, claim, journal, receipt, result, or owner context.
    """
    if type(preflight) is not BRSNativeChildPreflight:
        _fail("preflight_invalid")
    if type(completion) is not BRSOrdinalCompletion:
        _fail("completion_invalid")
    try:
        # Rebuild strict primitives before comparisons.  This also rejects
        # object.__setattr__ injections into frozen DTOs.
        current = preflight_native_brs_child(preflight.to_dict())
        observed = BRSOrdinalCompletion(**completion.to_dict())
    except (BRSChildPolicyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, BRSOrdinalSuccessorError):
            raise
        raise BRSOrdinalSuccessorError("shape_invalid") from exc

    selection = current.select_next_pending()
    if selection is None:
        _fail("wave_complete")
    if (
        observed.run_id != selection.run_id
        or observed.wave != selection.wave
        or observed.ordinal != selection.ordinal
        or observed.episode_id != selection.episode_id
        or observed.request_sha256 != selection.request_sha256
    ):
        _fail("completion_mismatch")

    executions = [*current.executions, selection.episode_id]
    consumed = dict(current.consumed_budget)
    for counter in ("practice_episodes", "solver_invocations"):
        used = consumed[counter]
        limit = dict(current.planned_budget)[counter]
        if limit is not None and used >= limit:
            _fail("budget_exhausted")
        consumed[counter] = used + 1
    attempts = current.attempts + 1
    if attempts > MAX_BRS_CHILD_ATTEMPTS:
        _fail("attempts_exhausted")
    next_wire = current.to_dict()
    next_wire["executions"] = executions
    next_wire["budget"] = {
        "planned": dict(current.planned_budget),
        "consumed": consumed,
    }
    next_wire["caps"] = {
        "attempts": attempts,
        "candidates": current.candidates,
        "checkpoint_bytes": current.checkpoint_bytes,
        "aggregate_bytes": current.aggregate_bytes,
    }
    successor = preflight_native_brs_child(next_wire)
    return BRSOrdinalSuccessor(successor, observed, successor.select_next_pending())


def claim_brs_successor(
    ledger: RSILedger,
    selection: BRSNativeChildSelection,
    request: SolverRequest,
    *,
    plan_sha256: str,
    controller_run_id: str,
    expected_controller_checkpoint_sha256: str,
) -> NativeEpisodeClaim:
    """Create one fresh, owner-CAS-bound claim for a serial successor.

    ``advance_brs_ordinal`` intentionally returns a descriptive selection only.  This
    narrow bridge is the next online boundary: it revalidates the selected identity,
    checks the request digest, and delegates the atomic create-only operation to the
    existing ledger.  The caller must already hold the controller lock; the guarded
    ledger operation rejects a stale head, duplicate claim, unclaimed result, or any
    other attempt to replay the prior ordinal.  A claim is launch state only and never
    grants publication or lineage authority.
    """
    if type(ledger) is not RSILedger:
        _fail("ledger_invalid")
    if type(selection) is not BRSNativeChildSelection:
        _fail("selection_invalid")
    if type(request) is not SolverRequest:
        _fail("request_invalid")
    try:
        # Rebuild strict detached values before calculating the request digest.  This
        # also rejects object.__setattr__ mutations on an otherwise frozen selection.
        selected = BRSNativeChildSelection(
            run_id=selection.run_id,
            wave=selection.wave,
            ordinal=selection.ordinal,
            episode_id=selection.episode_id,
            request_sha256=selection.request_sha256,
            root_snapshot_sha256=selection.root_snapshot_sha256,
            planned_budget=selection.planned_budget,
            consumed_budget=selection.consumed_budget,
            authority=selection.authority,
        )
        expected = SolverRequest.from_dict(request.to_dict())
    except (BRSChildPolicyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise BRSOrdinalSuccessorError("claim_shape_invalid") from exc
    if selected.authority is not False:
        _fail("claim_authority_invalid")
    try:
        request_sha256 = expected.digest()
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise BRSOrdinalSuccessorError("claim_request_invalid") from exc
    if (
        expected.episode_id != selected.episode_id
        or request_sha256 != selected.request_sha256
    ):
        _fail("claim_binding_mismatch")
    try:
        return ledger.claim_native_episode(
            expected,
            plan_sha256=plan_sha256,
            controller_run_id=controller_run_id,
            expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
        )
    except Exception as exc:
        # Do not leak a ledger object or turn a stale/duplicate claim into a retryable
        # successor.  The original exception remains available as ``__cause__`` for
        # local diagnostics while callers receive one stable refusal class.
        raise BRSOrdinalSuccessorError("claim_refused") from exc


def dispatch_brs_successor(
    preflight: BRSNativeChildPreflight,
    completion: BRSOrdinalCompletion,
    current: BRSChildHandoffContext,
    request: SolverRequest,
    ledger: RSILedger,
    *,
    plan_sha256: str,
    controller_run_id: str,
    expected_controller_checkpoint_sha256: str,
    dispatch: Callable[[BRSSelectedChildHandoff, SolverRequest, NativeEpisodeClaim], object],
    consumed_nonces: tuple[str, ...] = (),
    lease_nonce: str | None = None,
) -> BRSOrdinalSuccessorDispatch:
    """Complete the narrow owner-side terminal -> fresh handoff -> claim boundary.

    The preceding ordinal is advanced only from an exact terminal completion.  A
    pending successor is then bound to the *new* verified owner head, receives a
    fresh detached nonce, and is validated before the guarded ledger claim.  The
    injected ``dispatch`` callback is called only after the claim transaction
    returns; it is a local launch seam and receives no publication authority.  A
    callback error therefore leaves the durable started claim in place and is
    surfaced without retry or claim deletion.

    The caller must hold the original controller lock while this function runs.
    This helper does not inspect a workspace, spawn a process, reserve a second
    wave budget, settle a result, or enable public/native BRS.
    """
    if type(current) is not BRSChildHandoffContext:
        _fail("handoff_context_invalid")
    if not callable(dispatch):
        _fail("dispatch_callback_invalid")
    if type(expected_controller_checkpoint_sha256) is not str:
        _fail("checkpoint_invalid")
    try:
        # Reconstruct caller DTOs before comparing fields. Frozen dataclasses can
        # still be modified with object.__setattr__ by a hostile worker.
        observed = BRSOrdinalCompletion(**completion.to_dict())
        context = BRSChildHandoffContext(**current.to_dict())
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise BRSOrdinalSuccessorError("handoff_context_invalid") from exc
    if context.head_sha256 != observed.verified_head_sha256:
        _fail("verified_head_mismatch")
    if context.head_sha256 != expected_controller_checkpoint_sha256:
        _fail("checkpoint_mismatch")
    successor = advance_brs_ordinal(preflight, observed)
    selection = successor.next_selection
    if selection is None:
        return BRSOrdinalSuccessorDispatch("wave_complete", successor, None, None)
    if type(consumed_nonces) is not tuple:
        _fail("nonce_state_invalid")
    try:
        handoff = BRSSelectedChildHandoff.from_selection(
            selection, context, lease_nonce=lease_nonce,
        )
        validate_brs_child_handoff(
            handoff, successor.preflight, context, consumed_nonces=consumed_nonces,
        )
    except BRSChildHandoffError as exc:
        # Preserve the handoff gate's stable suffix without exposing arbitrary
        # callback/object details through this boundary.
        prefix = "rsi_python_brs_child_policy_handoff_"
        text = str(exc)
        if text.startswith(prefix):
            code = text[len(prefix):]
            raise BRSOrdinalSuccessorError("handoff_" + code) from exc
        raise BRSOrdinalSuccessorError("handoff_refused") from exc
    claim = claim_brs_successor(
        ledger, selection, request, plan_sha256=plan_sha256,
        controller_run_id=controller_run_id,
        expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
    )
    if claim.status != "started":
        _fail("claim_status_invalid")
    try:
        dispatch_result = dispatch(handoff, request, claim)
    except BaseException as exc:
        raise BRSOrdinalSuccessorError("dispatch_failed") from exc
    return BRSOrdinalSuccessorDispatch(
        "dispatched", successor, handoff, claim, dispatch_result,
    )


__all__ = [
    "BRSOrdinalCompletion",
    "BRSOrdinalSuccessor",
    "BRSOrdinalSuccessorDispatch",
    "BRSOrdinalSuccessorError",
    "advance_brs_ordinal",
    "claim_brs_successor",
    "dispatch_brs_successor",
]
