"""Provider-free BRS policy/memory composition gates."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.rsi_brs_policy_memory import (
    BRSImmutableCandidatePublication,
    BRSPolicyMemoryComposer,
    BRSPolicyMemoryError,
)
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT,
    MemoryItem,
    MemorySnapshot,
    VerifierCheck,
    VerifierDecision,
)
from lunar_evolution.rsi_memory_governance import MemoryGovernanceStore
from lunar_evolution.rsi_native_candidate import NativeCandidateRecord, NativePublicationReceipt


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


POLICY = {
    "protocol": "lunar-rsi-brs-memory-policy-v1",
    "version": 1,
    "solver_id": "fixture",
    "memory_scope": "problem-family:fixture",
    "promotion_mode": "transfer-regression-only",
}


def request(parent=EMPTY_MEMORY_SNAPSHOT, episode="run-1-practice-0-0"):
    return SolverRequest.build(
        episode_id=episode, contract_sha256=digest("contract"), evaluator_sha256=digest("evaluator"),
        environment_sha256=digest("environment"), memory_snapshot_sha256=parent.digest(), solver_id="fixture",
    )


def evidence(req: SolverRequest):
    candidate = NativeCandidateRecord(
        candidate_id="candidate-1", request_sha256=req.digest(), contract_sha256=req.contract_sha256,
        evaluator_sha256=req.evaluator_sha256, environment_sha256=req.environment_sha256,
        memory_snapshot_sha256=req.memory_snapshot_sha256, candidate_receipt_sha256=digest("candidate"),
        candidate_source_sha256=digest("source"),
    )
    publication = NativePublicationReceipt(
        candidate_id=candidate.candidate_id, request_sha256=req.digest(), contract_sha256=req.contract_sha256,
        evaluator_sha256=req.evaluator_sha256, environment_sha256=req.environment_sha256,
        memory_snapshot_sha256=req.memory_snapshot_sha256, receipt_sha256=digest("publication"),
    )
    return candidate, publication


def candidate_memory(req: SolverRequest) -> tuple[MemorySnapshot, VerifierDecision]:
    item = MemoryItem(
        memory_id="memory-1", problem_family="fixture", trigger="when fixture fails",
        strategy="apply bounded fix", expected_result="pass", failure_boundary="fixture boundary",
        compatible_contracts=(req.contract_sha256,), compatible_solvers=(req.solver_id,), verifier_outcome="pass",
        receipt_sha256=digest("verifier"), episode_id=req.episode_id,
    )
    current = MemorySnapshot("run-1-memory-1", EMPTY_MEMORY_SNAPSHOT.digest(), (item,))
    verifier = VerifierDecision(
        req.episode_id, "pass", item.receipt_sha256, "independent fixture pass", digest("verifier-fp"),
        (VerifierCheck("clean-room", "pass", digest("check")),), contract_sha256=req.contract_sha256,
        evaluator_sha256=req.evaluator_sha256, environment_sha256=req.environment_sha256,
    )
    return current, verifier


def test_success_decision_is_publication_bound_but_not_active(tmp_path: Path):
    req = request()
    candidate, publication = evidence(req)
    immutable = BRSImmutableCandidatePublication.from_evidence(
        "run-1", req, candidate, publication, lineage_head_sha256=digest("lineage"),
    )
    current, verifier = candidate_memory(req)
    composer = BRSPolicyMemoryComposer(POLICY)
    decision = composer.compose_success("run-1", req, EMPTY_MEMORY_SNAPSHOT, current, immutable, verifier)
    assert decision.outcome == "success"
    assert decision.memory_action == "candidate_pending"
    governance = MemoryGovernanceStore(tmp_path / "governance.sqlite3")
    shadow = composer.admit_candidate_shadow(
        governance, decision, current, scope=POLICY["memory_scope"],
        compatibility={"solver": req.solver_id, "contract": req.contract_sha256},
    )
    assert shadow.state == "shadow"
    assert [entry.state for entry in governance.history(shadow.admission_id)] == [
        "observed", "verified", "candidate", "shadow",
    ]
    assert governance.list_retrievable(scope=POLICY["memory_scope"]) == ()


def test_rejection_decision_has_no_memory_or_publication_authority(tmp_path: Path):
    req = request()
    decision = BRSPolicyMemoryComposer(POLICY).compose_rejection(
        "run-1", req, EMPTY_MEMORY_SNAPSHOT, rejection_receipt_sha256=digest("rejection"), reason="all candidates rejected",
    )
    assert decision.outcome == "rejected" and decision.memory_action == "none"
    assert decision.candidate_snapshot_sha256 is None and decision.publication_sha256 is None
    with pytest.raises(BRSPolicyMemoryError, match="decision_not_promotable"):
        BRSPolicyMemoryComposer(POLICY).admit_candidate_shadow(
            MemoryGovernanceStore(tmp_path / "governance.sqlite3"), decision, EMPTY_MEMORY_SNAPSHOT,
            scope=POLICY["memory_scope"], compatibility={"solver": req.solver_id},
        )


@pytest.mark.parametrize("kind", ["request", "lineage", "verifier", "publication"])
def test_success_rejects_snapshot_lineage_and_evidence_drift(kind: str):
    req = request()
    candidate, publication = evidence(req)
    immutable = BRSImmutableCandidatePublication.from_evidence(
        "run-1", req, candidate, publication, lineage_head_sha256=digest("lineage"),
    )
    current, verifier = candidate_memory(req)
    if kind == "request":
        req = replace(req, memory_snapshot_sha256=digest("foreign-parent"))
    elif kind == "lineage":
        current = replace(current, parent_snapshot_sha256=digest("foreign-parent"))
    elif kind == "verifier":
        verifier = replace(verifier, environment_sha256=digest("foreign-environment"))
    else:
        object.__setattr__(immutable, "lineage_head_sha256", digest("changed"))
    with pytest.raises(BRSPolicyMemoryError):
        BRSPolicyMemoryComposer(POLICY).compose_success("run-1", req, EMPTY_MEMORY_SNAPSHOT, current, immutable, verifier)


def test_policy_and_candidate_drift_cannot_reuse_decision():
    req = request()
    candidate, publication = evidence(req)
    immutable = BRSImmutableCandidatePublication.from_evidence(
        "run-1", req, candidate, publication, lineage_head_sha256=digest("lineage"),
    )
    current, verifier = candidate_memory(req)
    decision = BRSPolicyMemoryComposer(POLICY).compose_success("run-1", req, EMPTY_MEMORY_SNAPSHOT, current, immutable, verifier)
    with pytest.raises(BRSPolicyMemoryError, match="decision_snapshot_mismatch"):
        BRSPolicyMemoryComposer(POLICY).admit_candidate_shadow(
            MemoryGovernanceStore("/tmp/rsi-policy-memory-test.sqlite3"), decision,
            replace(current, snapshot_id="changed"), scope=POLICY["memory_scope"], compatibility={"solver": "fixture"},
        )


def test_shadow_replay_is_idempotent_and_rejects_policy_or_admission_drift(tmp_path: Path):
    req = request()
    candidate, publication = evidence(req)
    immutable = BRSImmutableCandidatePublication.from_evidence(
        "run-1", req, candidate, publication, lineage_head_sha256=digest("lineage"),
    )
    current, verifier = candidate_memory(req)
    composer = BRSPolicyMemoryComposer(POLICY)
    decision = composer.compose_success("run-1", req, EMPTY_MEMORY_SNAPSHOT, current, immutable, verifier)
    governance = MemoryGovernanceStore(tmp_path / "governance.sqlite3")
    compatibility = {"solver": req.solver_id, "contract": req.contract_sha256}
    first = composer.admit_candidate_shadow(
        governance, decision, current, scope=POLICY["memory_scope"], compatibility=compatibility,
    )
    second = composer.admit_candidate_shadow(
        governance, decision, current, scope=POLICY["memory_scope"], compatibility=compatibility,
    )
    assert second == first
    assert len(governance.history(first.admission_id)) == 4

    with pytest.raises(BRSPolicyMemoryError, match="admission_drift"):
        composer.admit_candidate_shadow(
            governance, decision, current, scope=POLICY["memory_scope"],
            compatibility={"solver": req.solver_id, "contract": digest("foreign-contract")},
        )
    with pytest.raises(BRSPolicyMemoryError, match="admission_drift"):
        composer.admit_candidate_shadow(
            governance, decision, current, scope="problem-family:other", compatibility=compatibility,
        )

    foreign_policy = dict(POLICY, memory_scope="problem-family:other")
    with pytest.raises(BRSPolicyMemoryError, match="decision_policy_mismatch"):
        BRSPolicyMemoryComposer(foreign_policy).admit_candidate_shadow(
            governance, decision, current, scope=POLICY["memory_scope"], compatibility=compatibility,
        )


def test_success_rejects_memory_item_incompatible_with_request():
    req = request()
    candidate, publication = evidence(req)
    immutable = BRSImmutableCandidatePublication.from_evidence(
        "run-1", req, candidate, publication, lineage_head_sha256=digest("lineage"),
    )
    current, verifier = candidate_memory(req)
    item = replace(current.items[0], compatible_solvers=("foreign-solver",))
    current = replace(current, items=(item,))
    with pytest.raises(BRSPolicyMemoryError, match="candidate_compatibility_mismatch"):
        BRSPolicyMemoryComposer(POLICY).compose_success(
            "run-1", req, EMPTY_MEMORY_SNAPSHOT, current, immutable, verifier,
        )
