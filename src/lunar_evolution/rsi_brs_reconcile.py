"""Durable, controller-owned obligations for interrupted Python BRS work.

The online BRS owner/mailbox is intentionally in-memory.  This module contains
the small durable value that a controller may opt into before crossing an
owner/worker boundary.  It does not launch workers, infer process liveness, or
turn an ``unknown`` outcome into success.  A checkpoint carrying an obligation
is therefore a recovery fence: a new controller can validate the original
request and decide whether an explicit evidence-bearing reconcile is possible.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import RSILearningError

_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX_BYTES = 128 * 1024
_MAX_OBLIGATIONS = 64
_MAX_DEPTH = 16

PROTOCOL = "lunar-rsi-brs-reconcile-v1"
FIELD = "brs_reconcile_obligations"
PHASES = frozenset({
    "selected", "worker_running", "worker_result", "owner_publication",
    "result_delivery", "settlement", "reconcile_required", "settled",
})
MAILBOX_STATES = frozenset({"none", "open", "queued", "inflight", "delivered", "abandoned", "closed"})
TRANSACTION_STATES = frozenset({"not_started", "before", "prepared", "staged", "terminal", "rejected", "unknown", "settled"})
RECONCILE_OUTCOMES = frozenset({
    "already_terminal", "recoverable", "abandoned", "drifted", "manual_review",
})
PROCESS_STATES = frozenset({"running", "exited", "unknown"})
TERMINAL_STATUSES = frozenset({
    "completed", "failed", "cancelled", "timed_out", "abandoned", "unknown",
})


def _text(value: object, name: str, *, limit: int = 256) -> str:
    if type(value) is not str or not value or len(value) > limit or any(c in value for c in "\x00\r\n"):
        raise RSILearningError(f"rsi_brs_reconcile_{name}_invalid")
    return value


def _sha(value: object, name: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise RSILearningError(f"rsi_brs_reconcile_{name}_invalid")
    return value


def _json_value(value: object, *, name: str, depth: int = 0) -> object:
    if depth > _MAX_DEPTH:
        raise RSILearningError(f"rsi_brs_reconcile_{name}_depth")
    if value is None or type(value) in (str, bool, int, float):
        if type(value) is float and not math.isfinite(value):
            raise RSILearningError(f"rsi_brs_reconcile_{name}_invalid")
        return value
    if type(value) is list:
        return [_json_value(item, name=name, depth=depth + 1) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise RSILearningError(f"rsi_brs_reconcile_{name}_invalid")
        return {key: _json_value(item, name=name, depth=depth + 1) for key, item in value.items()}
    raise RSILearningError(f"rsi_brs_reconcile_{name}_invalid")


@dataclass(frozen=True, slots=True)
class BRSReconcileObligation:
    """An exact owner/worker boundary captured in a controller checkpoint."""

    run_id: str
    episode_id: str
    phase: str
    handoff_sha256: str
    request_sha256: str
    native_plan_sha256: str
    controller_checkpoint_sha256: str
    episode_record_sha256: str
    native_claim_sha256: str | None = None
    owner_result_sha256: str | None = None
    worker_profile: Mapping[str, Any] | None = None
    mailbox_state: str = "none"
    transaction_state: str = "not_started"
    terminal_status: str | None = None

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id")
        _text(self.episode_id, "episode_id")
        if self.phase not in PHASES:
            raise RSILearningError("rsi_brs_reconcile_phase_invalid")
        for value, name in (
            (self.handoff_sha256, "handoff"), (self.request_sha256, "request"),
            (self.native_plan_sha256, "native_plan"),
            (self.controller_checkpoint_sha256, "controller_checkpoint"),
            (self.episode_record_sha256, "episode_record"),
        ):
            _sha(value, name)
        for value, name in ((self.native_claim_sha256, "native_claim"), (self.owner_result_sha256, "owner_result")):
            if value is not None:
                _sha(value, name)
        if self.mailbox_state not in MAILBOX_STATES:
            raise RSILearningError("rsi_brs_reconcile_mailbox_state_invalid")
        if self.transaction_state not in TRANSACTION_STATES:
            raise RSILearningError("rsi_brs_reconcile_transaction_state_invalid")
        if self.terminal_status is not None:
            _text(self.terminal_status, "terminal_status", limit=64)
        if self.worker_profile is not None:
            if type(self.worker_profile) is not dict:
                raise RSILearningError("rsi_brs_reconcile_worker_profile_invalid")
            clean = _json_value(self.worker_profile, name="worker_profile")
            object.__setattr__(self, "worker_profile", clean)
        if self.phase == "settled" and self.transaction_state != "settled":
            raise RSILearningError("rsi_brs_reconcile_settled_transaction_invalid")
        if self.phase == "reconcile_required" and self.terminal_status is None:
            raise RSILearningError("rsi_brs_reconcile_terminal_status_missing")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL,
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "phase": self.phase,
            "handoff_sha256": self.handoff_sha256,
            "request_sha256": self.request_sha256,
            "native_plan_sha256": self.native_plan_sha256,
            "controller_checkpoint_sha256": self.controller_checkpoint_sha256,
            "episode_record_sha256": self.episode_record_sha256,
            "native_claim_sha256": self.native_claim_sha256,
            "owner_result_sha256": self.owner_result_sha256,
            "worker_profile": (
                _json_value(self.worker_profile, name="worker_profile")
                if self.worker_profile is not None else None
            ),
            "mailbox_state": self.mailbox_state,
            "transaction_state": self.transaction_state,
            "terminal_status": self.terminal_status,
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict(), maximum=_MAX_BYTES)).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BRSReconcileObligation:
        if type(value) is not dict:
            raise RSILearningError("rsi_brs_reconcile_obligation_invalid")
        expected = set(cls.__dataclass_fields__) | {"protocol"}
        if set(value) != expected or value.get("protocol") != PROTOCOL:
            raise RSILearningError("rsi_brs_reconcile_obligation_invalid")
        try:
            clean = dict(value)
            clean.pop("protocol")
            return cls(**clean)
        except (TypeError, ValueError, RSILearningError) as exc:
            if isinstance(exc, RSILearningError):
                raise
            raise RSILearningError("rsi_brs_reconcile_obligation_invalid") from exc

    def advance(self, phase: str, *, mailbox_state: str | None = None,
                transaction_state: str | None = None, terminal_status: str | None = None,
                owner_result_sha256: str | None = None,
                episode_record_sha256: str | None = None) -> BRSReconcileObligation:
        """Return one adjacent phase update; never refreshes captured identity."""
        if phase not in PHASES:
            raise RSILearningError("rsi_brs_reconcile_phase_invalid")
        if self.phase == "settled":
            raise RSILearningError("rsi_brs_reconcile_phase_terminal")
        order = {name: index for index, name in enumerate((
            "selected", "worker_running", "worker_result", "owner_publication",
            "result_delivery", "settlement", "settled",
        ))}
        if (phase != "reconcile_required" and self.phase != "reconcile_required"
                and phase != self.phase and order.get(phase, -1) != order.get(self.phase, -1) + 1):
            raise RSILearningError("rsi_brs_reconcile_phase_transition_invalid")
        if self.phase == "reconcile_required" and phase not in {"reconcile_required", "settled"}:
            raise RSILearningError("rsi_brs_reconcile_phase_transition_invalid")
        return replace(
            self, phase=phase,
            mailbox_state=self.mailbox_state if mailbox_state is None else mailbox_state,
            transaction_state=self.transaction_state if transaction_state is None else transaction_state,
            terminal_status=self.terminal_status if terminal_status is None else terminal_status,
            owner_result_sha256=self.owner_result_sha256 if owner_result_sha256 is None else owner_result_sha256,
            episode_record_sha256=self.episode_record_sha256 if episode_record_sha256 is None else episode_record_sha256,
        )


def parse_brs_reconcile_obligations(value: object) -> dict[str, BRSReconcileObligation]:
    """Parse the checkpoint field and reject unknown/duplicate identities."""
    if value is None:
        return {}
    if type(value) is not dict or len(value) > _MAX_OBLIGATIONS:
        raise RSILearningError("rsi_brs_reconcile_obligations_invalid")
    parsed: dict[str, BRSReconcileObligation] = {}
    for key, raw in value.items():
        _text(key, "episode_id")
        obligation = BRSReconcileObligation.from_dict(raw)
        if key != obligation.episode_id or key in parsed:
            raise RSILearningError("rsi_brs_reconcile_obligation_binding_invalid")
        parsed[key] = obligation
    return parsed


def validate_brs_reconcile_obligations(
    state: Mapping[str, Any], *, run_id: str, checkpoint_sha256: str | None = None,
    intents: Mapping[str, Any] | None = None,
    episode_heads: Mapping[str, Any] | None = None,
) -> dict[str, BRSReconcileObligation]:
    """Validate obligations against controller state without making progress."""
    if not isinstance(state, Mapping):
        raise RSILearningError("rsi_brs_reconcile_checkpoint_invalid")
    _text(run_id, "run_id")
    if state.get("run_id") != run_id:
        raise RSILearningError("rsi_brs_reconcile_run_binding_invalid")
    obligations = parse_brs_reconcile_obligations(state.get(FIELD))
    if checkpoint_sha256 is not None:
        _sha(checkpoint_sha256, "checkpoint")
    for episode_id, obligation in obligations.items():
        if obligation.run_id != run_id:
            raise RSILearningError("rsi_brs_reconcile_run_binding_invalid")
        if checkpoint_sha256 is not None and obligation.controller_checkpoint_sha256 != checkpoint_sha256:
            raise RSILearningError("rsi_brs_reconcile_checkpoint_binding_invalid")
        if intents is not None:
            intent = intents.get(episode_id)
            if not isinstance(intent, Mapping) or not isinstance(intent.get("request"), Mapping):
                raise RSILearningError("rsi_brs_reconcile_intent_missing")
            request_wire = canonical_json(dict(intent["request"]), maximum=_MAX_BYTES)
            request_sha256 = hashlib.sha256(request_wire).hexdigest()
            if request_sha256 != obligation.request_sha256:
                raise RSILearningError("rsi_brs_reconcile_request_binding_invalid")
        if episode_heads is not None:
            head = episode_heads.get(episode_id)
            head_sha256 = getattr(head, "record_sha256", None)
            if head_sha256 != obligation.episode_record_sha256:
                raise RSILearningError("rsi_brs_reconcile_episode_binding_invalid")
    return obligations


def put_brs_reconcile_obligation(state: dict[str, Any], obligation: BRSReconcileObligation) -> None:
    """Add one obligation to mutable controller state, preserving idempotent replay."""
    if type(state) is not dict or not isinstance(obligation, BRSReconcileObligation):
        raise RSILearningError("rsi_brs_reconcile_obligation_invalid")
    current = parse_brs_reconcile_obligations(state.get(FIELD))
    previous = current.get(obligation.episode_id)
    if previous is not None and previous.to_dict() != obligation.to_dict():
        raise RSILearningError("rsi_brs_reconcile_obligation_conflict")
    current[obligation.episode_id] = obligation
    state[FIELD] = {key: current[key].to_dict() for key in sorted(current)}


@dataclass(frozen=True, slots=True)
class BRSReconcileEvidence:
    """A bounded, controller-observed evidence envelope for one BRS obligation.

    This value is deliberately only an observation DTO.  It does not inspect a process,
    acquire ownership, read a mailbox, or write a controller checkpoint.  The four evidence
    digests are supplied by an explicit local adapter which has already performed those reads;
    ``reconcile_brs_selected`` checks their shape and exact obligation bindings before returning
    an audit decision.  Missing evidence is represented by ``None`` and never upgrades an
    unknown result to success.
    """

    obligation_sha256: str
    handoff_sha256: str
    request_sha256: str
    native_plan_sha256: str
    controller_checkpoint_sha256: str
    episode_record_sha256: str
    native_claim_sha256: str | None = None
    owner_result_sha256: str | None = None
    process_state: str = "unknown"
    process_evidence_sha256: str | None = None
    native_evidence_sha256: str | None = None
    mailbox_evidence_sha256: str | None = None
    result_evidence_sha256: str | None = None
    mailbox_state: str = "none"
    transaction_state: str = "unknown"
    terminal_status: str | None = None
    controller_observed_terminal: bool = False
    cleanup_confirmed: bool = False
    source: str = "controller-observed-v1"
    reason: str = ""

    def __post_init__(self) -> None:
        _sha(self.obligation_sha256, "obligation")
        for value, name in (
            (self.handoff_sha256, "handoff"), (self.request_sha256, "request"),
            (self.native_plan_sha256, "native_plan"),
            (self.controller_checkpoint_sha256, "controller_checkpoint"),
            (self.episode_record_sha256, "episode_record"),
        ):
            _sha(value, name)
        for value, name in (
            (self.native_claim_sha256, "native_claim"),
            (self.owner_result_sha256, "owner_result"),
            (self.process_evidence_sha256, "process_evidence"),
            (self.native_evidence_sha256, "native_evidence"),
            (self.mailbox_evidence_sha256, "mailbox_evidence"),
            (self.result_evidence_sha256, "result_evidence"),
        ):
            if value is not None:
                _sha(value, name)
        if self.process_state not in PROCESS_STATES:
            raise RSILearningError("rsi_brs_reconcile_process_state_invalid")
        if self.mailbox_state not in MAILBOX_STATES:
            raise RSILearningError("rsi_brs_reconcile_mailbox_state_invalid")
        if self.transaction_state not in TRANSACTION_STATES:
            raise RSILearningError("rsi_brs_reconcile_transaction_state_invalid")
        if self.terminal_status is not None and self.terminal_status not in TERMINAL_STATUSES:
            raise RSILearningError("rsi_brs_reconcile_terminal_status_invalid")
        if type(self.controller_observed_terminal) is not bool or type(self.cleanup_confirmed) is not bool:
            raise RSILearningError("rsi_brs_reconcile_observation_invalid")
        if self.source != "controller-observed-v1":
            raise RSILearningError("rsi_brs_reconcile_source_invalid")
        if type(self.reason) is not str or len(self.reason) > 512 or any(
            char in self.reason for char in "\x00\r\n"
        ):
            raise RSILearningError("rsi_brs_reconcile_reason_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL + ":evidence",
            "obligation_sha256": self.obligation_sha256,
            "handoff_sha256": self.handoff_sha256,
            "request_sha256": self.request_sha256,
            "native_plan_sha256": self.native_plan_sha256,
            "controller_checkpoint_sha256": self.controller_checkpoint_sha256,
            "episode_record_sha256": self.episode_record_sha256,
            "native_claim_sha256": self.native_claim_sha256,
            "owner_result_sha256": self.owner_result_sha256,
            "process_state": self.process_state,
            "process_evidence_sha256": self.process_evidence_sha256,
            "native_evidence_sha256": self.native_evidence_sha256,
            "mailbox_evidence_sha256": self.mailbox_evidence_sha256,
            "result_evidence_sha256": self.result_evidence_sha256,
            "mailbox_state": self.mailbox_state,
            "transaction_state": self.transaction_state,
            "terminal_status": self.terminal_status,
            "controller_observed_terminal": self.controller_observed_terminal,
            "cleanup_confirmed": self.cleanup_confirmed,
            "source": self.source,
            "reason": self.reason,
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict(), maximum=_MAX_BYTES)).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BRSReconcileEvidence:
        if type(value) is not dict:
            raise RSILearningError("rsi_brs_reconcile_evidence_invalid")
        expected = set(cls.__dataclass_fields__) | {"protocol"}
        if set(value) != expected or value.get("protocol") != PROTOCOL + ":evidence":
            raise RSILearningError("rsi_brs_reconcile_evidence_invalid")
        clean = dict(value)
        clean.pop("protocol")
        try:
            return cls(**clean)
        except (TypeError, ValueError, RSILearningError) as exc:
            if isinstance(exc, RSILearningError):
                raise
            raise RSILearningError("rsi_brs_reconcile_evidence_invalid") from exc


@dataclass(frozen=True, slots=True)
class BRSReconcileDecision:
    """Pure audit result returned by :func:`reconcile_brs_selected`.

    ``recommended_phase`` is advisory.  The caller must persist an adjacent obligation phase
    under its controller lock; this DTO never mutates a checkpoint or invokes the default BRS
    driver.  ``status`` is kept as a read-only alias for callers that use status terminology.
    """

    outcome: str
    recommended_phase: str
    obligation_sha256: str
    evidence_sha256: str
    reason: str

    def __post_init__(self) -> None:
        if self.outcome not in RECONCILE_OUTCOMES:
            raise RSILearningError("rsi_brs_reconcile_outcome_invalid")
        if self.recommended_phase not in PHASES:
            raise RSILearningError("rsi_brs_reconcile_phase_invalid")
        _sha(self.obligation_sha256, "obligation")
        _sha(self.evidence_sha256, "evidence")
        if type(self.reason) is not str or not self.reason or len(self.reason) > 512 or any(
            char in self.reason for char in "\x00\r\n"
        ):
            raise RSILearningError("rsi_brs_reconcile_reason_invalid")

    @property
    def status(self) -> str:
        return self.outcome

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL + ":decision",
            "outcome": self.outcome,
            "recommended_phase": self.recommended_phase,
            "obligation_sha256": self.obligation_sha256,
            "evidence_sha256": self.evidence_sha256,
            "reason": self.reason,
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict(), maximum=_MAX_BYTES)).hexdigest()


def _recommended_phase(obligation: BRSReconcileObligation, outcome: str) -> str:
    if outcome == "already_terminal":
        return "settled" if obligation.phase == "reconcile_required" else "reconcile_required"
    if outcome == "recoverable":
        return obligation.phase if obligation.phase != "selected" else "worker_running"
    if obligation.phase == "settled":
        return "settled"
    return "reconcile_required"


def _decision(
    obligation: BRSReconcileObligation, evidence: BRSReconcileEvidence, outcome: str, reason: str,
) -> BRSReconcileDecision:
    return BRSReconcileDecision(
        outcome=outcome, recommended_phase=_recommended_phase(obligation, outcome),
        obligation_sha256=obligation.digest(), evidence_sha256=evidence.digest(), reason=reason,
    )


def reconcile_brs_selected(
    obligation: BRSReconcileObligation, evidence: BRSReconcileEvidence,
) -> BRSReconcileDecision:
    """Audit one selected BRS obligation using explicit local evidence.

    This is intentionally a pure opt-in facade.  It performs no process or mailbox reads, does
    not infer success from ``unknown``, and does not write the ledger.  A caller may persist the
    returned recommended phase only after independently performing the corresponding CAS and
    controller-lock checks.
    """
    if not isinstance(obligation, BRSReconcileObligation):
        raise RSILearningError("rsi_brs_reconcile_obligation_invalid")
    if not isinstance(evidence, BRSReconcileEvidence):
        raise RSILearningError("rsi_brs_reconcile_evidence_invalid")
    if evidence.obligation_sha256 != obligation.digest():
        return _decision(obligation, evidence, "drifted", "obligation digest mismatch")
    for field in (
        "handoff_sha256", "request_sha256", "native_plan_sha256",
        "controller_checkpoint_sha256", "episode_record_sha256",
    ):
        if getattr(evidence, field) != getattr(obligation, field):
            return _decision(obligation, evidence, "drifted", f"{field} mismatch")
    for field in ("native_claim_sha256", "owner_result_sha256"):
        captured = getattr(obligation, field)
        observed = getattr(evidence, field)
        if observed != captured:
            return _decision(obligation, evidence, "drifted", f"{field} mismatch")
    if evidence.process_evidence_sha256 is None:
        return _decision(obligation, evidence, "manual_review", "process evidence missing")
    if evidence.process_state == "unknown":
        return _decision(obligation, evidence, "manual_review", "process state unknown")
    if evidence.process_state == "running":
        if evidence.terminal_status is not None or evidence.transaction_state in {"terminal", "settled"}:
            return _decision(obligation, evidence, "drifted", "running process has terminal state")
        return _decision(obligation, evidence, "recoverable", "worker process is still running")
    # An exited process is only terminal when every independent evidence leg is present.
    if evidence.terminal_status in {None, "unknown"}:
        return _decision(obligation, evidence, "manual_review", "terminal status missing or unknown")
    if any(
        value is None for value in (
            evidence.native_evidence_sha256, evidence.mailbox_evidence_sha256,
            evidence.result_evidence_sha256,
        )
    ):
        return _decision(obligation, evidence, "manual_review", "terminal evidence incomplete")
    if evidence.native_claim_sha256 is not None and evidence.native_evidence_sha256 != evidence.native_claim_sha256:
        return _decision(obligation, evidence, "drifted", "native evidence mismatch")
    if evidence.owner_result_sha256 is not None and evidence.result_evidence_sha256 != evidence.owner_result_sha256:
        return _decision(obligation, evidence, "drifted", "result evidence mismatch")
    if evidence.mailbox_state not in {"closed", "delivered"}:
        return _decision(obligation, evidence, "manual_review", "mailbox is not terminal")
    if evidence.transaction_state not in {"terminal", "settled"}:
        return _decision(obligation, evidence, "manual_review", "transaction is not terminal")
    if evidence.controller_observed_terminal is not True or evidence.cleanup_confirmed is not True:
        return _decision(obligation, evidence, "manual_review", "terminal cleanup not observed")
    return _decision(obligation, evidence, "already_terminal", "explicit terminal evidence verified")


def remove_brs_reconcile_obligation(state: dict[str, Any], episode_id: str, *, expected_digest: str | None = None) -> None:
    """Remove only an exact obligation after successful durable settlement."""
    if type(state) is not dict:
        raise RSILearningError("rsi_brs_reconcile_checkpoint_invalid")
    _text(episode_id, "episode_id")
    current = parse_brs_reconcile_obligations(state.get(FIELD))
    existing = current.get(episode_id)
    if existing is None:
        return
    if expected_digest is None:
        raise RSILearningError("rsi_brs_reconcile_obligation_digest_required")
    if existing.digest() != _sha(expected_digest, "obligation_digest"):
        raise RSILearningError("rsi_brs_reconcile_obligation_conflict")
    current.pop(episode_id)
    state[FIELD] = {key: current[key].to_dict() for key in sorted(current)}


__all__ = [
    "FIELD",
    "MAILBOX_STATES",
    "PHASES",
    "PROCESS_STATES",
    "PROTOCOL",
    "RECONCILE_OUTCOMES",
    "TERMINAL_STATUSES",
    "TRANSACTION_STATES",
    "BRSReconcileDecision",
    "BRSReconcileEvidence",
    "BRSReconcileObligation",
    "parse_brs_reconcile_obligations",
    "put_brs_reconcile_obligation",
    "reconcile_brs_selected",
    "remove_brs_reconcile_obligation",
    "validate_brs_reconcile_obligations",
]
