"""Pure serial-successor checks for a bounded native BRS wave.

This module only advances a detached preflight projection after the owner has
observed an exact native terminal and acknowledged its lineage checkpoint.  It
does not open a ledger, inspect a workspace, launch a worker, reserve budget,
publish a candidate, or grant a handoff.  The caller must still bind the
returned selection to a *fresh* owner context and nonce.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .rsi_python_brs_child_policy import (
    BRSChildPolicyError,
    BRSNativeChildPreflight,
    BRSNativeChildSelection,
    preflight_native_brs_child,
)

_SHA = re.compile(r"^[0-9a-f]{64}$")
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
        if type(self.run_id) is not str or not self.run_id:
            _fail("run_id_invalid")
        if type(self.wave) is not int or self.wave < 0:
            _fail("wave_invalid")
        if type(self.ordinal) is not int or self.ordinal < 0:
            _fail("ordinal_invalid")
        if type(self.episode_id) is not str or not self.episode_id:
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
    if attempts > 8:
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


__all__ = [
    "BRSOrdinalCompletion",
    "BRSOrdinalSuccessor",
    "BRSOrdinalSuccessorError",
    "advance_brs_ordinal",
]
