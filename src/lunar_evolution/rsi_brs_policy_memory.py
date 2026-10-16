"""Provider-free BRS policy/memory composition gates.

BRS owner publication and RSI memory admission are intentionally separate control-plane
transactions.  This module composes their *evidence* without giving a worker, result delivery,
or a rejection record memory authority.  A successful owner publication can produce an explicit
``candidate_pending`` decision and, after an independent verifier decision, append a governance
admission through ``observed -> ... -> shadow``.  Activation is deliberately outside this module
and remains the explicit transfer-regression promotion boundary.

The helpers only consume detached immutable DTOs; they do not launch workers, run evaluators,
mutate ``RSIMemoryStore`` or publication lineage, and do not enable public BRS.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NoReturn

from .candidate_evaluation_spec import canonical_json
from .rsi_gateway import SolverRequest
from .rsi_learning import (
    MemoryItem,
    MemorySnapshot,
    RSILearningError,
    VerifierCheck,
    VerifierDecision,
)
from .rsi_memory_governance import (
    MemoryAdmissionRecord,
    MemoryGovernanceError,
    MemoryGovernanceStore,
)
from .rsi_native_candidate import (
    NativeCandidateRecord,
    NativePublicationReceipt,
    select_native_candidate,
)

_HEX = frozenset("0123456789abcdef")
_POLICY_FIELDS = {"protocol", "version", "solver_id", "memory_scope", "promotion_mode"}
_POLICY_PROTOCOL = "lunar-rsi-brs-memory-policy-v1"


class BRSPolicyMemoryError(RSILearningError):
    """Fixed-code refusal at the owner policy/memory composition boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("rsi_brs_policy_memory_" + code)


def _fail(code: str) -> NoReturn:
    raise BRSPolicyMemoryError(code)


def _digest(value: object, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in _HEX for char in value):
        _fail(f"{field}_invalid")
    return value


def _id(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or any(char in value for char in "\x00\r\n"):
        _fail(f"{field}_invalid")
    try:
        if len(value.encode("utf-8")) > 512:
            _fail(f"{field}_too_large")
    except UnicodeEncodeError as exc:
        raise BRSPolicyMemoryError(f"{field}_invalid") from exc
    return value


def _policy(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _POLICY_FIELDS:
        _fail("policy_shape_invalid")
    try:
        # Round-trip through canonical JSON prevents mutable/foreign values from crossing the
        # policy boundary and makes the digest an immutable policy identity.
        raw = canonical_json(dict(value), maximum=32 * 1024)
        parsed = __import__("json").loads(raw)
    except Exception as exc:
        raise BRSPolicyMemoryError("policy_invalid") from exc
    if not isinstance(parsed, dict) or parsed.get("protocol") != _POLICY_PROTOCOL:
        _fail("policy_protocol_invalid")
    if parsed.get("version") != 1 or type(parsed.get("solver_id")) is not str:
        _fail("policy_invalid")
    if type(parsed.get("memory_scope")) is not str or not parsed["memory_scope"].strip():
        _fail("policy_invalid")
    if parsed.get("promotion_mode") != "transfer-regression-only":
        _fail("policy_promotion_mode_invalid")
    return parsed


def _digest_payload(value: object) -> str:
    try:
        return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()
    except Exception as exc:
        raise BRSPolicyMemoryError("digest_invalid") from exc


def _detached_candidate(value: NativeCandidateRecord) -> NativeCandidateRecord:
    if type(value) is not NativeCandidateRecord:
        _fail("candidate_invalid")
    try:
        return NativeCandidateRecord.from_dict(NativeCandidateRecord.to_dict(value))
    except (TypeError, ValueError, AttributeError, RSILearningError) as exc:
        raise BRSPolicyMemoryError("candidate_invalid") from exc


def _detached_publication(value: NativePublicationReceipt) -> NativePublicationReceipt:
    if type(value) is not NativePublicationReceipt:
        _fail("publication_invalid")
    try:
        return NativePublicationReceipt.from_dict(NativePublicationReceipt.to_dict(value))
    except (TypeError, ValueError, AttributeError, RSILearningError) as exc:
        raise BRSPolicyMemoryError("publication_invalid") from exc


def _detached_request(value: SolverRequest) -> SolverRequest:
    if type(value) is not SolverRequest:
        _fail("request_invalid")
    try:
        return SolverRequest.from_dict(value.to_dict())
    except (TypeError, ValueError, AttributeError, RSILearningError) as exc:
        raise BRSPolicyMemoryError("request_invalid") from exc


def _detached_snapshot(value: MemorySnapshot, field: str) -> MemorySnapshot:
    if type(value) is not MemorySnapshot:
        _fail(f"{field}_invalid")
    try:
        return MemorySnapshot.from_dict(value.to_dict())
    except (TypeError, ValueError, AttributeError, RSILearningError) as exc:
        raise BRSPolicyMemoryError(f"{field}_invalid") from exc


def _detached_verifier(value: VerifierDecision) -> VerifierDecision:
    if type(value) is not VerifierDecision:
        _fail("verifier_invalid")
    try:
        payload = value.to_dict()
        payload["checks"] = tuple(VerifierCheck(**check) for check in payload["checks"])
        return VerifierDecision(**payload)
    except (TypeError, ValueError, AttributeError, RSILearningError) as exc:
        raise BRSPolicyMemoryError("verifier_invalid") from exc


def _detached_decision(value: BRSPolicyMemoryDecision) -> BRSPolicyMemoryDecision:
    """Rebuild a decision before it is used as an admission capability.

    The DTO is frozen, but callers can still hand us a forged object (or mutate one through
    reflection).  Reconstructing it from its canonical wire form rechecks the decision digest
    and the success/rejection authority split at the only method that can append governance
    history.
    """
    if type(value) is not BRSPolicyMemoryDecision:
        _fail("decision_invalid")
    try:
        payload = value.to_dict()
        payload.pop("protocol", None)
        return BRSPolicyMemoryDecision(**payload)
    except (TypeError, ValueError, AttributeError, RSILearningError) as exc:
        raise BRSPolicyMemoryError("decision_invalid") from exc


def _check_snapshot_lineage(parent: MemorySnapshot, current: MemorySnapshot, *, episode_id: str) -> MemoryItem:
    """Require a single immutable new item atop an exact parent snapshot."""
    if current.parent_snapshot_sha256 != parent.digest() or current.digest() == parent.digest():
        _fail("snapshot_lineage_mismatch")
    old = {item.memory_id: item for item in parent.items}
    new = [item for item in current.items if item.memory_id not in old]
    if len(new) != 1:
        _fail("candidate_cardinality_invalid")
    for item in current.items:
        if item.memory_id in old and item.to_dict() != old[item.memory_id].to_dict():
            _fail("snapshot_lineage_mismatch")
    candidate = new[0]
    if candidate.episode_id != episode_id or candidate.verifier_outcome != "pass" or candidate.status != "approved":
        _fail("candidate_item_invalid")
    return candidate


@dataclass(frozen=True, slots=True)
class BRSImmutableCandidatePublication:
    """Owner-created publication evidence, independent from memory policy."""

    run_id: str
    episode_id: str
    candidate_id: str
    request_sha256: str
    memory_snapshot_sha256: str
    candidate_receipt_sha256: str
    publication_receipt_sha256: str
    lineage_head_sha256: str
    selection_sha256: str
    publication_sha256: str

    def __post_init__(self) -> None:
        for value, field in ((self.run_id, "run_id"), (self.episode_id, "episode_id"),
                             (self.candidate_id, "candidate_id")):
            _id(value, field)
        for value, field in (
            (self.request_sha256, "request_sha256"),
            (self.memory_snapshot_sha256, "memory_snapshot_sha256"),
            (self.candidate_receipt_sha256, "candidate_receipt_sha256"),
            (self.publication_receipt_sha256, "publication_receipt_sha256"),
            (self.lineage_head_sha256, "lineage_head_sha256"),
            (self.selection_sha256, "selection_sha256"),
            (self.publication_sha256, "publication_sha256"),
        ):
            _digest(value, field)
        expected = _digest_payload({
            "protocol": "lunar-rsi-brs-candidate-publication-v1",
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "candidate_id": self.candidate_id,
            "request_sha256": self.request_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "candidate_receipt_sha256": self.candidate_receipt_sha256,
            "publication_receipt_sha256": self.publication_receipt_sha256,
            "lineage_head_sha256": self.lineage_head_sha256,
            "selection_sha256": self.selection_sha256,
        })
        if self.publication_sha256 != expected:
            _fail("publication_digest_mismatch")

    @classmethod
    def from_evidence(
        cls,
        run_id: str,
        request: SolverRequest,
        candidate: NativeCandidateRecord,
        publication: NativePublicationReceipt,
        *,
        lineage_head_sha256: str,
    ) -> BRSImmutableCandidatePublication:
        run_id = _id(run_id, "run_id")
        request = _detached_request(request)
        candidate = _detached_candidate(candidate)
        publication = _detached_publication(publication)
        _digest(lineage_head_sha256, "lineage_head_sha256")
        if candidate.state != "admitted" or publication.status != "published":
            _fail("publication_not_immutable")
        try:
            selected = select_native_candidate(request, (candidate,))
        except RSILearningError as exc:
            raise BRSPolicyMemoryError("publication_request_mismatch") from exc
        if (publication.candidate_id != candidate.candidate_id
                or publication.request_sha256 != request.digest()
                or publication.contract_sha256 != request.contract_sha256
                or publication.evaluator_sha256 != request.evaluator_sha256
                or publication.environment_sha256 != request.environment_sha256
                or publication.memory_snapshot_sha256 != request.memory_snapshot_sha256
                or publication.receipt_sha256 == "0" * 64):
            _fail("publication_binding_mismatch")
        payload = {
            "protocol": "lunar-rsi-brs-candidate-publication-v1",
            "run_id": run_id,
            "episode_id": request.episode_id,
            "candidate_id": candidate.candidate_id,
            "request_sha256": request.digest(),
            "memory_snapshot_sha256": request.memory_snapshot_sha256,
            "candidate_receipt_sha256": candidate.candidate_receipt_sha256,
            "publication_receipt_sha256": publication.receipt_sha256,
            "lineage_head_sha256": lineage_head_sha256,
            "selection_sha256": selected.selection_sha256,
        }
        # Selection identity is included in the canonical immutable publication digest, but the
        # public DTO intentionally retains only the bounded fields needed by policy consumers.
        publication_sha256 = _digest_payload(payload)
        return cls(
            run_id, request.episode_id, candidate.candidate_id, request.digest(),
            request.memory_snapshot_sha256, candidate.candidate_receipt_sha256,
            publication.receipt_sha256, lineage_head_sha256, selected.selection_sha256, publication_sha256,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol": "lunar-rsi-brs-candidate-publication-v1",
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "candidate_id": self.candidate_id,
            "request_sha256": self.request_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "candidate_receipt_sha256": self.candidate_receipt_sha256,
            "publication_receipt_sha256": self.publication_receipt_sha256,
            "lineage_head_sha256": self.lineage_head_sha256,
            "selection_sha256": self.selection_sha256,
            "publication_sha256": self.publication_sha256,
        }


@dataclass(frozen=True, slots=True)
class BRSPolicyMemoryDecision:
    """A policy outcome with no publication or memory authority attached."""

    outcome: Literal["success", "rejected"]
    memory_action: Literal["candidate_pending", "none"]
    run_id: str
    episode_id: str
    request_sha256: str
    parent_snapshot_sha256: str
    candidate_snapshot_sha256: str | None
    publication_sha256: str | None
    verifier_receipt_sha256: str | None
    rejection_receipt_sha256: str | None
    policy_sha256: str
    reason: str
    decision_sha256: str

    def __post_init__(self) -> None:
        if self.outcome not in {"success", "rejected"}:
            _fail("decision_outcome_invalid")
        expected_action = "candidate_pending" if self.outcome == "success" else "none"
        if self.memory_action != expected_action:
            _fail("decision_action_invalid")
        _id(self.run_id, "run_id")
        _id(self.episode_id, "episode_id")
        for value, field in ((self.request_sha256, "request_sha256"),
                             (self.parent_snapshot_sha256, "parent_snapshot_sha256"),
                             (self.policy_sha256, "policy_sha256"),):
            _digest(value, field)
        if self.candidate_snapshot_sha256 is not None:
            _digest(self.candidate_snapshot_sha256, "candidate_snapshot_sha256")
        if self.publication_sha256 is not None:
            _digest(self.publication_sha256, "publication_sha256")
        if self.verifier_receipt_sha256 is not None:
            _digest(self.verifier_receipt_sha256, "verifier_receipt_sha256")
        if self.rejection_receipt_sha256 is not None:
            _digest(self.rejection_receipt_sha256, "rejection_receipt_sha256")
        if self.outcome == "rejected" and self.rejection_receipt_sha256 is None:
            _fail("rejection_receipt_missing")
        if self.outcome == "success" and self.rejection_receipt_sha256 is not None:
            _fail("success_rejection_binding")
        _id(self.reason, "reason")
        expected = _digest_payload({
            "protocol": "lunar-rsi-brs-policy-memory-decision-v1",
            "outcome": self.outcome, "memory_action": self.memory_action,
            "run_id": self.run_id, "episode_id": self.episode_id,
            "request_sha256": self.request_sha256,
            "parent_snapshot_sha256": self.parent_snapshot_sha256,
            "candidate_snapshot_sha256": self.candidate_snapshot_sha256,
            "publication_sha256": self.publication_sha256,
            "verifier_receipt_sha256": self.verifier_receipt_sha256,
            "rejection_receipt_sha256": self.rejection_receipt_sha256,
            "policy_sha256": self.policy_sha256, "reason": self.reason,
        })
        if self.decision_sha256 != expected:
            _fail("decision_digest_mismatch")
        if self.outcome == "rejected" and any(
            value is not None for value in (self.candidate_snapshot_sha256, self.publication_sha256,
                                            self.verifier_receipt_sha256)
        ):
            _fail("rejection_memory_binding")

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol": "lunar-rsi-brs-policy-memory-decision-v1",
            "outcome": self.outcome, "memory_action": self.memory_action,
            "run_id": self.run_id, "episode_id": self.episode_id,
            "request_sha256": self.request_sha256,
            "parent_snapshot_sha256": self.parent_snapshot_sha256,
            "candidate_snapshot_sha256": self.candidate_snapshot_sha256,
            "publication_sha256": self.publication_sha256,
            "verifier_receipt_sha256": self.verifier_receipt_sha256,
            "rejection_receipt_sha256": self.rejection_receipt_sha256,
            "policy_sha256": self.policy_sha256, "reason": self.reason,
            "decision_sha256": self.decision_sha256,
        }


class BRSPolicyMemoryComposer:
    """Compose owner publication and policy evidence without activation authority."""

    def __init__(self, policy: Mapping[str, object]) -> None:
        self.policy = _policy(policy)
        self.policy_sha256 = _digest_payload(self.policy)

    def compose_success(
        self,
        run_id: str,
        request: SolverRequest,
        parent_memory: MemorySnapshot,
        candidate_memory: MemorySnapshot,
        publication: BRSImmutableCandidatePublication,
        verifier: VerifierDecision,
    ) -> BRSPolicyMemoryDecision:
        run_id = _id(run_id, "run_id")
        request = _detached_request(request)
        parent = _detached_snapshot(parent_memory, "parent_memory")
        current = _detached_snapshot(candidate_memory, "candidate_memory")
        verifier = _detached_verifier(verifier)
        if type(publication) is not BRSImmutableCandidatePublication:
            _fail("publication_invalid")
        try:
            publication = BRSImmutableCandidatePublication(
                publication.run_id, publication.episode_id, publication.candidate_id,
                publication.request_sha256, publication.memory_snapshot_sha256,
                publication.candidate_receipt_sha256, publication.publication_receipt_sha256,
                publication.lineage_head_sha256, publication.selection_sha256,
                publication.publication_sha256,
            )
        except (TypeError, ValueError, RSILearningError) as exc:
            raise BRSPolicyMemoryError("publication_invalid") from exc
        if (publication.run_id != run_id or publication.episode_id != request.episode_id
                or publication.request_sha256 != request.digest()
                or publication.memory_snapshot_sha256 != parent.digest()):
            _fail("publication_snapshot_mismatch")
        if request.memory_snapshot_sha256 != parent.digest():
            _fail("request_snapshot_mismatch")
        item = _check_snapshot_lineage(parent, current, episode_id=request.episode_id)
        if (request.contract_sha256 not in item.compatible_contracts
                or request.solver_id not in item.compatible_solvers):
            _fail("candidate_compatibility_mismatch")
        if (verifier.episode_id != request.episode_id or verifier.outcome != "pass"
                or not verifier.independent_of_actor
                or verifier.receipt_sha256 != item.receipt_sha256
                or verifier.contract_sha256 != request.contract_sha256
                or verifier.evaluator_sha256 != request.evaluator_sha256
                or verifier.environment_sha256 != request.environment_sha256):
            _fail("verifier_binding_mismatch")
        payload = {
            "protocol": "lunar-rsi-brs-policy-memory-decision-v1", "outcome": "success",
            "memory_action": "candidate_pending", "run_id": run_id,
            "episode_id": request.episode_id, "request_sha256": request.digest(),
            "parent_snapshot_sha256": parent.digest(), "candidate_snapshot_sha256": current.digest(),
            "publication_sha256": publication.publication_sha256,
            "verifier_receipt_sha256": verifier.receipt_sha256,
            "rejection_receipt_sha256": None,
            "policy_sha256": self.policy_sha256, "reason": "owner_publication_and_verifier_pass",
        }
        body = dict(payload)
        body.pop("protocol")
        return BRSPolicyMemoryDecision(**body, decision_sha256=_digest_payload(payload))

    def compose_rejection(
        self,
        run_id: str,
        request: SolverRequest,
        parent_memory: MemorySnapshot,
        *,
        rejection_receipt_sha256: str,
        reason: str,
    ) -> BRSPolicyMemoryDecision:
        run_id = _id(run_id, "run_id")
        request = _detached_request(request)
        parent = _detached_snapshot(parent_memory, "parent_memory")
        if request.memory_snapshot_sha256 != parent.digest():
            _fail("request_snapshot_mismatch")
        _digest(rejection_receipt_sha256, "rejection_receipt_sha256")
        _id(reason, "rejection_reason")
        payload = {
            "protocol": "lunar-rsi-brs-policy-memory-decision-v1", "outcome": "rejected",
            "memory_action": "none", "run_id": run_id, "episode_id": request.episode_id,
            "request_sha256": request.digest(), "parent_snapshot_sha256": parent.digest(),
            "candidate_snapshot_sha256": None, "publication_sha256": None,
            "verifier_receipt_sha256": None, "rejection_receipt_sha256": rejection_receipt_sha256,
            "policy_sha256": self.policy_sha256, "reason": reason,
        }
        # Rejection receipt is retained as policy evidence only; no publication or memory field
        # is emitted, so a rejected result cannot become a promotion token or mutate a head.
        body = dict(payload)
        body.pop("protocol")
        return BRSPolicyMemoryDecision(**body, decision_sha256=_digest_payload(payload))

    def admit_candidate_shadow(
        self,
        governance: MemoryGovernanceStore,
        decision: BRSPolicyMemoryDecision,
        candidate_memory: MemorySnapshot,
        *,
        scope: str,
        compatibility: Mapping[str, object],
    ) -> MemoryAdmissionRecord:
        """Append only through ``shadow``; transfer promotion remains a separate explicit API."""
        if not isinstance(governance, MemoryGovernanceStore):
            _fail("governance_invalid")
        decision = _detached_decision(decision)
        if decision.outcome != "success":
            _fail("decision_not_promotable")
        current = _detached_snapshot(candidate_memory, "candidate_memory")
        if decision.policy_sha256 != self.policy_sha256:
            _fail("decision_policy_mismatch")
        if decision.candidate_snapshot_sha256 != current.digest():
            _fail("decision_snapshot_mismatch")
        if decision.parent_snapshot_sha256 != current.parent_snapshot_sha256:
            _fail("decision_parent_snapshot_mismatch")
        if decision.publication_sha256 is None or decision.verifier_receipt_sha256 is None:
            _fail("decision_evidence_missing")
        new = [item for item in current.items if item.episode_id == decision.episode_id]
        if len(new) != 1:
            _fail("candidate_cardinality_invalid")
        item = new[0]
        admission_id = "brs-memory:" + _digest_payload({
            "run_id": decision.run_id, "episode_id": decision.episode_id,
            "snapshot": current.digest(), "item": item.memory_id,
        })
        try:
            record = governance.get(admission_id)
            if record is None:
                record = governance.create(MemoryAdmissionRecord(
                    admission_id=admission_id, memory_snapshot_sha256=current.digest(),
                    memory_item_sha256=_digest_payload(item.to_dict()), source_episode_id=item.episode_id,
                    verifier_receipt_sha256=decision.verifier_receipt_sha256,
                    parent_snapshot_sha256=current.parent_snapshot_sha256, scope=_id(scope, "scope"),
                    compatibility=dict(compatibility), reason="brs-policy-memory:" + decision.decision_sha256,
                ))
            else:
                if (record.memory_snapshot_sha256 != current.digest()
                        or record.memory_item_sha256 != _digest_payload(item.to_dict())
                        or record.source_episode_id != item.episode_id
                        or record.verifier_receipt_sha256 != decision.verifier_receipt_sha256
                        or record.parent_snapshot_sha256 != current.parent_snapshot_sha256
                        or record.scope != scope
                        or dict(record.compatibility) != dict(compatibility)
                        or record.reason != "brs-policy-memory:" + decision.decision_sha256):
                    _fail("admission_drift")
            edges = {"observed": "verified", "verified": "candidate", "candidate": "shadow"}
            while record.state in edges:
                record = governance.transition(
                    admission_id, edges[record.state], expected_record_sha256=record.record_sha256,
                    verifier_receipt_sha256=decision.verifier_receipt_sha256,
                    compatibility=dict(compatibility),
                )
            if record.state != "shadow":
                _fail("admission_state_invalid")
            return record
        except MemoryGovernanceError as exc:
            raise BRSPolicyMemoryError("admission_refused") from exc


__all__ = [
    "BRSImmutableCandidatePublication", "BRSPolicyMemoryComposer", "BRSPolicyMemoryDecision",
    "BRSPolicyMemoryError",
]
