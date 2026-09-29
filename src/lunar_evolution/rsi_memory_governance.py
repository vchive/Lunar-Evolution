"""Fail-closed lifecycle authority for verifier-gated RSI memory.

The existing RSI snapshot format deliberately contains only approved ``MemoryItem`` values.  This
module keeps the longer-lived promotion history outside that wire format so that an old snapshot
cannot accidentally gain a new mutable state.  It does not execute a solver, verifier, or holdout;
all such work is represented by immutable, caller-supplied receipt digests.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import RSILearningError

MEMORY_GOVERNANCE_PROTOCOL = "lunar-rsi-memory-governance-v1"
MEMORY_GOVERNANCE_SCHEMA_VERSION = "1"
MAX_MEMORY_LIFECYCLE_RECEIPTS = 16
MAX_PROMOTION_EVIDENCE = 32

MemoryLifecycleState = Literal[
    "observed",
    "verified",
    "candidate",
    "shadow",
    "approved",
    "active",
    "deprecated",
    "revoked",
    "quarantined",
]

_TERMINAL_STATES = frozenset({"revoked", "quarantined"})
_TRANSITIONS: dict[str, frozenset[str]] = {
    "observed": frozenset({"verified", "revoked", "quarantined"}),
    "verified": frozenset({"candidate", "revoked", "quarantined"}),
    "candidate": frozenset({"shadow", "revoked", "quarantined"}),
    "shadow": frozenset({"approved", "revoked", "quarantined"}),
    "approved": frozenset({"active", "deprecated", "revoked", "quarantined"}),
    "active": frozenset({"deprecated", "revoked", "quarantined"}),
    "deprecated": frozenset({"revoked", "quarantined"}),
    "revoked": frozenset(),
    "quarantined": frozenset(),
}


def _fail(code: str) -> None:
    raise RSILearningError(code)


def _id(value: object, *, name: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value.encode("utf-8")) > 256
        or any(char in value for char in "\x00\r\n")
    ):
        _fail(f"rsi_memory_{name}_invalid")
    return value


def _text(value: object, *, name: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > 8192
    ):
        _fail(f"rsi_memory_{name}_invalid")
    return value


def _digest(value: object, *, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        _fail(f"rsi_memory_{name}_invalid")
    return value


def _score(value: object, *, name: str) -> int:
    if type(value) is not int or not -1_000_000_000 <= value <= 1_000_000_000:
        _fail(f"rsi_memory_{name}_invalid")
    return value


def _unique_digests(value: object, *, name: str, minimum: int = 0) -> tuple[str, ...]:
    if type(value) is not tuple or not minimum <= len(value) <= MAX_PROMOTION_EVIDENCE:
        _fail(f"rsi_memory_{name}_invalid")
    result = tuple(_digest(item, name=name) for item in value)
    if len(result) != len(set(result)):
        _fail(f"rsi_memory_{name}_invalid")
    return result


def _canonical_digest(value: Mapping[str, Any]) -> str:
    try:
        encoded = canonical_json(dict(value), maximum=128 * 1024)
    except Exception as exc:
        raise RSILearningError("rsi_memory_governance_record_invalid") from exc
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MemoryScope:
    """The task-family and conflict domain in which a memory may be retrieved."""

    scope_id: str
    problem_family: str
    conflict_key: str

    def __post_init__(self) -> None:
        _id(self.scope_id, name="scope_id")
        _text(self.problem_family, name="problem_family")
        _id(self.conflict_key, name="conflict_key")

    def to_dict(self) -> dict[str, str]:
        return {
            "scope_id": self.scope_id,
            "problem_family": self.problem_family,
            "conflict_key": self.conflict_key,
        }


@dataclass(frozen=True)
class MemoryCompatibility:
    """Exact pins that make a memory meaningfully comparable and retrievable."""

    contract_sha256: str
    evaluator_sha256: str
    environment_sha256: str
    solver_id: str
    solver_fingerprint: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.contract_sha256, "contract_sha256"),
            (self.evaluator_sha256, "evaluator_sha256"),
            (self.environment_sha256, "environment_sha256"),
            (self.solver_fingerprint, "solver_fingerprint"),
        ):
            _digest(value, name=name)
        _id(self.solver_id, name="solver_id")

    def to_dict(self) -> dict[str, str]:
        return {
            "contract_sha256": self.contract_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
            "solver_id": self.solver_id,
            "solver_fingerprint": self.solver_fingerprint,
        }

    def digest(self) -> str:
        return _canonical_digest(self.to_dict())


@dataclass(frozen=True)
class MemoryAuthority:
    """The immutable source identity which every promotion record retains."""

    memory_id: str
    content_sha256: str
    source_episode_id: str
    source_episode_sha256: str
    source_receipt_sha256: str
    parent_snapshot_sha256: str
    scope: MemoryScope
    compatibility: MemoryCompatibility

    def __post_init__(self) -> None:
        _id(self.memory_id, name="id")
        _id(self.source_episode_id, name="source_episode_id")
        for value, name in (
            (self.content_sha256, "content_sha256"),
            (self.source_episode_sha256, "source_episode_sha256"),
            (self.source_receipt_sha256, "source_receipt_sha256"),
            (self.parent_snapshot_sha256, "parent_snapshot_sha256"),
        ):
            _digest(value, name=name)
        if not isinstance(self.scope, MemoryScope) or not isinstance(
            self.compatibility, MemoryCompatibility
        ):
            _fail("rsi_memory_authority_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content_sha256": self.content_sha256,
            "source_episode_id": self.source_episode_id,
            "source_episode_sha256": self.source_episode_sha256,
            "source_receipt_sha256": self.source_receipt_sha256,
            "parent_snapshot_sha256": self.parent_snapshot_sha256,
            "scope": self.scope.to_dict(),
            "compatibility": self.compatibility.to_dict(),
        }


@dataclass(frozen=True)
class LifecycleReceipt:
    """A retained receipt for one state transition, never a generated success claim."""

    state: MemoryLifecycleState
    receipt_sha256: str
    actor_fingerprint: str
    reason_code: str

    def __post_init__(self) -> None:
        if self.state not in _TRANSITIONS:
            _fail("rsi_memory_lifecycle_state_invalid")
        _digest(self.receipt_sha256, name="lifecycle_receipt_sha256")
        _digest(self.actor_fingerprint, name="actor_fingerprint")
        _id(self.reason_code, name="reason_code")

    def to_dict(self) -> dict[str, str]:
        return {
            "state": self.state,
            "receipt_sha256": self.receipt_sha256,
            "actor_fingerprint": self.actor_fingerprint,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class PromotionGate:
    """Retained champion/challenger and holdout evidence for a proposed activation."""

    compatibility_fingerprint: str
    parent_snapshot_sha256: str
    baseline_practice_receipt_sha256: str
    challenger_practice_receipt_sha256: str
    baseline_holdout_receipt_sha256: str
    challenger_holdout_receipt_sha256: str
    baseline_practice_score: int
    challenger_practice_score: int
    baseline_holdout_score: int
    challenger_holdout_score: int
    practice_pass_receipts: tuple[str, ...]
    holdout_pass_receipts: tuple[str, ...]
    holdout_failure_receipts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, name in (
            (self.compatibility_fingerprint, "compatibility_fingerprint"),
            (self.parent_snapshot_sha256, "parent_snapshot_sha256"),
            (self.baseline_practice_receipt_sha256, "baseline_practice_receipt_sha256"),
            (self.challenger_practice_receipt_sha256, "challenger_practice_receipt_sha256"),
            (self.baseline_holdout_receipt_sha256, "baseline_holdout_receipt_sha256"),
            (self.challenger_holdout_receipt_sha256, "challenger_holdout_receipt_sha256"),
        ):
            _digest(value, name=name)
        for value, name in (
            (self.baseline_practice_score, "baseline_practice_score"),
            (self.challenger_practice_score, "challenger_practice_score"),
            (self.baseline_holdout_score, "baseline_holdout_score"),
            (self.challenger_holdout_score, "challenger_holdout_score"),
        ):
            _score(value, name=name)
        practice = _unique_digests(
            self.practice_pass_receipts, name="practice_pass_receipts", minimum=1
        )
        holdout = _unique_digests(
            self.holdout_pass_receipts, name="holdout_pass_receipts", minimum=1
        )
        failures = _unique_digests(self.holdout_failure_receipts, name="holdout_failure_receipts")
        if (
            set(practice) & set(holdout)
            or set(practice) & set(failures)
            or set(holdout) & set(failures)
        ):
            _fail("rsi_memory_gate_evidence_overlap")
        if self.challenger_practice_receipt_sha256 not in practice:
            _fail("rsi_memory_gate_practice_receipt_unbound")
        if self.challenger_holdout_receipt_sha256 not in holdout:
            _fail("rsi_memory_gate_holdout_receipt_unbound")

    @property
    def has_regression(self) -> bool:
        return (
            self.challenger_practice_score < self.baseline_practice_score
            or self.challenger_holdout_score < self.baseline_holdout_score
            or bool(self.holdout_failure_receipts)
        )

    @property
    def ready_for_activation(self) -> bool:
        return not self.has_regression and len(self.practice_pass_receipts) >= 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatibility_fingerprint": self.compatibility_fingerprint,
            "parent_snapshot_sha256": self.parent_snapshot_sha256,
            "baseline_practice_receipt_sha256": self.baseline_practice_receipt_sha256,
            "challenger_practice_receipt_sha256": self.challenger_practice_receipt_sha256,
            "baseline_holdout_receipt_sha256": self.baseline_holdout_receipt_sha256,
            "challenger_holdout_receipt_sha256": self.challenger_holdout_receipt_sha256,
            "baseline_practice_score": self.baseline_practice_score,
            "challenger_practice_score": self.challenger_practice_score,
            "baseline_holdout_score": self.baseline_holdout_score,
            "challenger_holdout_score": self.challenger_holdout_score,
            "practice_pass_receipts": list(self.practice_pass_receipts),
            "holdout_pass_receipts": list(self.holdout_pass_receipts),
            "holdout_failure_receipts": list(self.holdout_failure_receipts),
        }


@dataclass(frozen=True)
class MemoryPromotionRecord:
    """An immutable lifecycle record; ``approved`` remains pending until activation evidence exists."""

    authority: MemoryAuthority
    state: MemoryLifecycleState
    receipts: tuple[LifecycleReceipt, ...]
    previous_record_sha256: str | None = None
    verifier_receipt_sha256: str | None = None
    verifier_fingerprint: str | None = None
    gate: PromotionGate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.authority, MemoryAuthority) or self.state not in _TRANSITIONS:
            _fail("rsi_memory_promotion_record_invalid")
        if (
            type(self.receipts) is not tuple
            or not self.receipts
            or len(self.receipts) > MAX_MEMORY_LIFECYCLE_RECEIPTS
        ):
            _fail("rsi_memory_lifecycle_receipts_invalid")
        if any(not isinstance(receipt, LifecycleReceipt) for receipt in self.receipts):
            _fail("rsi_memory_lifecycle_receipts_invalid")
        if self.receipts[-1].state != self.state:
            _fail("rsi_memory_lifecycle_receipts_invalid")
        if self.receipts[0].state != "observed" or len(
            {receipt.state for receipt in self.receipts}
        ) != len(self.receipts):
            _fail("rsi_memory_lifecycle_receipts_invalid")
        for before, after in zip(self.receipts, self.receipts[1:]):
            if after.state not in _TRANSITIONS[before.state]:
                _fail("rsi_memory_lifecycle_transition_invalid")
        if self.previous_record_sha256 is not None:
            _digest(self.previous_record_sha256, name="previous_record_sha256")
        if self.state == "observed" and self.previous_record_sha256 is not None:
            _fail("rsi_memory_observed_parent_invalid")
        if self.state != "observed" and self.previous_record_sha256 is None:
            _fail("rsi_memory_transition_parent_missing")
        requires_verifier = self.state in {
            "verified",
            "candidate",
            "shadow",
            "approved",
            "active",
            "deprecated",
        }
        has_verifier = (
            self.verifier_receipt_sha256 is not None or self.verifier_fingerprint is not None
        )
        if requires_verifier or has_verifier:
            _digest(self.verifier_receipt_sha256, name="verifier_receipt_sha256")
            _digest(self.verifier_fingerprint, name="verifier_fingerprint")
        if (self.verifier_receipt_sha256 is None) != (self.verifier_fingerprint is None):
            _fail("rsi_memory_verifier_evidence_invalid")
        if self.state in {"approved", "active", "deprecated"}:
            if not isinstance(self.gate, PromotionGate):
                _fail("rsi_memory_gate_missing")
        elif self.gate is not None and self.state not in {"revoked", "quarantined"}:
            _fail("rsi_memory_gate_invalid")

    def _payload(self) -> dict[str, Any]:
        return {
            "protocol": MEMORY_GOVERNANCE_PROTOCOL,
            "schema_version": MEMORY_GOVERNANCE_SCHEMA_VERSION,
            "kind": "rsi_memory_promotion_record",
            "authority": self.authority.to_dict(),
            "state": self.state,
            "receipts": [receipt.to_dict() for receipt in self.receipts],
            "previous_record_sha256": self.previous_record_sha256,
            "verifier_receipt_sha256": self.verifier_receipt_sha256,
            "verifier_fingerprint": self.verifier_fingerprint,
            "gate": self.gate.to_dict() if self.gate is not None else None,
        }

    def digest(self) -> str:
        return _canonical_digest(self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "record_sha256": self.digest()}


class MemoryGovernanceAuthority:
    """In-process lifecycle authority with stale-record and active-conflict gates.

    A durable controller should persist each returned ``MemoryPromotionRecord`` in its own ledger.
    This authority intentionally stores no candidate content and has no authority to execute the
    evidence named by a digest.
    """

    def __init__(self) -> None:
        self._heads: dict[str, MemoryPromotionRecord] = {}

    @staticmethod
    def _receipt(
        state: MemoryLifecycleState,
        receipt_sha256: str,
        actor_fingerprint: str,
        reason_code: str,
    ) -> LifecycleReceipt:
        return LifecycleReceipt(state, receipt_sha256, actor_fingerprint, reason_code)

    def observe(
        self,
        authority: MemoryAuthority,
        *,
        observation_receipt_sha256: str,
        actor_fingerprint: str,
        reason_code: str = "episode_observed",
    ) -> MemoryPromotionRecord:
        if not isinstance(authority, MemoryAuthority):
            _fail("rsi_memory_authority_invalid")
        if authority.memory_id in self._heads:
            _fail("rsi_memory_duplicate_observation")
        if observation_receipt_sha256 != authority.source_receipt_sha256:
            _fail("rsi_memory_observation_receipt_mismatch")
        record = MemoryPromotionRecord(
            authority,
            "observed",
            (
                self._receipt(
                    "observed", observation_receipt_sha256, actor_fingerprint, reason_code
                ),
            ),
        )
        self._heads[authority.memory_id] = record
        return record

    def _head(self, record: MemoryPromotionRecord, *, required: str) -> MemoryPromotionRecord:
        if not isinstance(record, MemoryPromotionRecord):
            _fail("rsi_memory_promotion_record_invalid")
        current = self._heads.get(record.authority.memory_id)
        if current is None:
            _fail("rsi_memory_record_unknown")
        if current.digest() != record.digest():
            _fail("rsi_memory_stale_record")
        if record.state != required:
            _fail("rsi_memory_lifecycle_state_invalid")
        return current

    def _advance(
        self,
        record: MemoryPromotionRecord,
        state: MemoryLifecycleState,
        *,
        receipt_sha256: str,
        actor_fingerprint: str,
        reason_code: str,
        verifier_receipt_sha256: str | None = None,
        verifier_fingerprint: str | None = None,
        gate: PromotionGate | None = None,
    ) -> MemoryPromotionRecord:
        if state not in _TRANSITIONS[record.state]:
            _fail("rsi_memory_lifecycle_transition_invalid")
        next_verifier_receipt = (
            record.verifier_receipt_sha256
            if verifier_receipt_sha256 is None
            else verifier_receipt_sha256
        )
        next_verifier_fingerprint = (
            record.verifier_fingerprint if verifier_fingerprint is None else verifier_fingerprint
        )
        next_gate = record.gate if gate is None else gate
        advanced = MemoryPromotionRecord(
            authority=record.authority,
            state=state,
            receipts=record.receipts
            + (self._receipt(state, receipt_sha256, actor_fingerprint, reason_code),),
            previous_record_sha256=record.digest(),
            verifier_receipt_sha256=next_verifier_receipt,
            verifier_fingerprint=next_verifier_fingerprint,
            gate=next_gate,
        )
        self._heads[record.authority.memory_id] = advanced
        return advanced

    def verify(
        self,
        record: MemoryPromotionRecord,
        *,
        verifier_receipt_sha256: str,
        verifier_fingerprint: str,
        compatibility_fingerprint: str,
        transition_receipt_sha256: str,
        actor_fingerprint: str,
    ) -> MemoryPromotionRecord:
        current = self._head(record, required="observed")
        if compatibility_fingerprint != current.authority.compatibility.digest():
            _fail("rsi_memory_verifier_compatibility_mismatch")
        return self._advance(
            current,
            "verified",
            receipt_sha256=transition_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
            reason_code="independent_verifier_passed",
            verifier_receipt_sha256=verifier_receipt_sha256,
            verifier_fingerprint=verifier_fingerprint,
        )

    def nominate_candidate(
        self,
        record: MemoryPromotionRecord,
        *,
        transition_receipt_sha256: str,
        actor_fingerprint: str,
    ) -> MemoryPromotionRecord:
        current = self._head(record, required="verified")
        return self._advance(
            current,
            "candidate",
            receipt_sha256=transition_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
            reason_code="candidate_nominated",
            verifier_receipt_sha256=current.verifier_receipt_sha256,
            verifier_fingerprint=current.verifier_fingerprint,
        )

    def start_shadow(
        self,
        record: MemoryPromotionRecord,
        *,
        transition_receipt_sha256: str,
        actor_fingerprint: str,
    ) -> MemoryPromotionRecord:
        current = self._head(record, required="candidate")
        return self._advance(
            current,
            "shadow",
            receipt_sha256=transition_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
            reason_code="shadow_evaluation_started",
            verifier_receipt_sha256=current.verifier_receipt_sha256,
            verifier_fingerprint=current.verifier_fingerprint,
        )

    @staticmethod
    def _validate_gate(record: MemoryPromotionRecord, gate: PromotionGate) -> None:
        if not isinstance(gate, PromotionGate):
            _fail("rsi_memory_gate_invalid")
        if gate.compatibility_fingerprint != record.authority.compatibility.digest():
            _fail("rsi_memory_gate_compatibility_mismatch")
        if gate.parent_snapshot_sha256 != record.authority.parent_snapshot_sha256:
            _fail("rsi_memory_gate_parent_snapshot_mismatch")
        if record.authority.source_receipt_sha256 not in gate.practice_pass_receipts:
            _fail("rsi_memory_gate_source_receipt_unbound")
        if gate.has_regression:
            _fail("rsi_memory_gate_regression")

    def approve(
        self,
        record: MemoryPromotionRecord,
        gate: PromotionGate,
        *,
        transition_receipt_sha256: str,
        actor_fingerprint: str,
    ) -> MemoryPromotionRecord:
        current = self._head(record, required="shadow")
        self._validate_gate(current, gate)
        return self._advance(
            current,
            "approved",
            receipt_sha256=transition_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
            reason_code="holdout_gate_approved_pending_activation",
            verifier_receipt_sha256=current.verifier_receipt_sha256,
            verifier_fingerprint=current.verifier_fingerprint,
            gate=gate,
        )

    def activate(
        self,
        record: MemoryPromotionRecord,
        *,
        transition_receipt_sha256: str,
        actor_fingerprint: str,
    ) -> MemoryPromotionRecord:
        current = self._head(record, required="approved")
        if current.gate is None or not current.gate.ready_for_activation:
            _fail("rsi_memory_activation_evidence_insufficient")
        for other in self._heads.values():
            if other.authority.memory_id == current.authority.memory_id or other.state != "active":
                continue
            if (
                other.authority.scope.conflict_key == current.authority.scope.conflict_key
                and other.authority.compatibility.digest()
                == current.authority.compatibility.digest()
            ):
                _fail("rsi_memory_active_conflict")
        return self._advance(
            current,
            "active",
            receipt_sha256=transition_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
            reason_code="holdout_gate_activated",
            verifier_receipt_sha256=current.verifier_receipt_sha256,
            verifier_fingerprint=current.verifier_fingerprint,
            gate=current.gate,
        )

    def deprecate(
        self,
        record: MemoryPromotionRecord,
        *,
        transition_receipt_sha256: str,
        actor_fingerprint: str,
        reason_code: str = "champion_replaced",
    ) -> MemoryPromotionRecord:
        if record.state not in {"approved", "active"}:
            _fail("rsi_memory_lifecycle_state_invalid")
        current = self._head(record, required=record.state)
        return self._advance(
            current,
            "deprecated",
            receipt_sha256=transition_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
            reason_code=reason_code,
            verifier_receipt_sha256=current.verifier_receipt_sha256,
            verifier_fingerprint=current.verifier_fingerprint,
            gate=current.gate,
        )

    def revoke(
        self,
        record: MemoryPromotionRecord,
        *,
        transition_receipt_sha256: str,
        actor_fingerprint: str,
        reason_code: str = "evidence_revoked",
    ) -> MemoryPromotionRecord:
        if record.state in _TERMINAL_STATES:
            _fail("rsi_memory_lifecycle_state_invalid")
        current = self._head(record, required=record.state)
        return self._advance(
            current,
            "revoked",
            receipt_sha256=transition_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
            reason_code=reason_code,
        )

    def quarantine(
        self,
        record: MemoryPromotionRecord,
        *,
        transition_receipt_sha256: str,
        actor_fingerprint: str,
        reason_code: str = "evidence_ambiguous",
    ) -> MemoryPromotionRecord:
        if record.state in _TERMINAL_STATES:
            _fail("rsi_memory_lifecycle_state_invalid")
        current = self._head(record, required=record.state)
        return self._advance(
            current,
            "quarantined",
            receipt_sha256=transition_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
            reason_code=reason_code,
        )

    def get(self, memory_id: str) -> MemoryPromotionRecord | None:
        return self._heads.get(_id(memory_id, name="id"))

    def retrieve(
        self,
        *,
        scope: MemoryScope,
        compatibility: MemoryCompatibility,
    ) -> tuple[MemoryPromotionRecord, ...]:
        if not isinstance(scope, MemoryScope) or not isinstance(compatibility, MemoryCompatibility):
            _fail("rsi_memory_retrieval_scope_invalid")
        result = [
            record
            for record in self._heads.values()
            if record.state == "active"
            and record.authority.scope == scope
            and record.authority.compatibility == compatibility
        ]
        return tuple(sorted(result, key=lambda record: record.authority.memory_id))


__all__ = [
    "MAX_MEMORY_LIFECYCLE_RECEIPTS",
    "MAX_PROMOTION_EVIDENCE",
    "MEMORY_GOVERNANCE_PROTOCOL",
    "MEMORY_GOVERNANCE_SCHEMA_VERSION",
    "LifecycleReceipt",
    "MemoryAuthority",
    "MemoryCompatibility",
    "MemoryGovernanceAuthority",
    "MemoryLifecycleState",
    "MemoryPromotionRecord",
    "MemoryScope",
    "PromotionGate",
]
