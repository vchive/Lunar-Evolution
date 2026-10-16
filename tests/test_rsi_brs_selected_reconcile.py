"""Pure provider-free selected BRS reconcile facade tests."""

from __future__ import annotations

import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT,
    BRSReconcileEvidence,
    BRSReconcileObligation,
    RSILearningError,
    SolverRequest,
    reconcile_brs_selected,
)

HEX = "a" * 64
OTHER = "b" * 64


def _obligation(*, phase: str = "selected") -> BRSReconcileObligation:
    request = SolverRequest.build(
        episode_id="episode-1", contract_sha256=HEX, evaluator_sha256=HEX,
        environment_sha256=HEX, memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="fixture",
    )
    return BRSReconcileObligation(
        run_id="run-1", episode_id=request.episode_id, phase=phase,
        handoff_sha256=HEX, request_sha256=request.digest(), native_plan_sha256=HEX,
        controller_checkpoint_sha256=HEX, episode_record_sha256=HEX,
        native_claim_sha256=HEX, owner_result_sha256=HEX,
        terminal_status="completed" if phase == "reconcile_required" else None,
    )


def _evidence(obligation: BRSReconcileObligation, **kwargs) -> BRSReconcileEvidence:
    values = {
        "obligation_sha256": obligation.digest(), "handoff_sha256": obligation.handoff_sha256,
        "request_sha256": obligation.request_sha256, "native_plan_sha256": obligation.native_plan_sha256,
        "controller_checkpoint_sha256": obligation.controller_checkpoint_sha256,
        "episode_record_sha256": obligation.episode_record_sha256,
        "native_claim_sha256": obligation.native_claim_sha256,
        "owner_result_sha256": obligation.owner_result_sha256,
        "process_state": "exited", "process_evidence_sha256": HEX,
        "native_evidence_sha256": HEX, "mailbox_evidence_sha256": HEX, "result_evidence_sha256": HEX,
        "mailbox_state": "closed", "transaction_state": "terminal", "terminal_status": "completed",
        "controller_observed_terminal": True, "cleanup_confirmed": True,
    }
    values.update(kwargs)
    return BRSReconcileEvidence(**values)


def test_terminal_evidence_is_a_pure_already_terminal_decision() -> None:
    obligation = _obligation()
    evidence = _evidence(obligation)
    result = reconcile_brs_selected(obligation, evidence)
    assert result.outcome == result.status == "already_terminal"
    assert result.recommended_phase == "reconcile_required"
    assert obligation.phase == "selected"


def test_reconcile_required_can_recommend_settled_but_does_not_write() -> None:
    obligation = _obligation(phase="reconcile_required")
    result = reconcile_brs_selected(obligation, _evidence(obligation))
    assert result.outcome == "already_terminal"
    assert result.recommended_phase == "settled"
    assert obligation.phase == "reconcile_required"


def test_running_process_is_recoverable() -> None:
    obligation = _obligation()
    result = reconcile_brs_selected(
        obligation, _evidence(obligation, process_state="running", terminal_status=None,
                              native_evidence_sha256=None, mailbox_evidence_sha256=None,
                              result_evidence_sha256=None, mailbox_state="open",
                              transaction_state="prepared", controller_observed_terminal=False,
                              cleanup_confirmed=False),
    )
    assert result.outcome == "recoverable"
    assert result.recommended_phase == "worker_running"


def test_unknown_or_missing_evidence_requires_manual_review() -> None:
    obligation = _obligation()
    unknown = reconcile_brs_selected(obligation, _evidence(obligation, process_state="unknown"))
    missing = reconcile_brs_selected(obligation, _evidence(obligation, process_evidence_sha256=None))
    assert unknown.outcome == missing.outcome == "manual_review"


@pytest.mark.parametrize("field", ["obligation_sha256", "request_sha256", "native_claim_sha256"])
def test_identity_drift_is_fail_closed(field: str) -> None:
    obligation = _obligation()
    evidence = _evidence(obligation, **{field: OTHER})
    assert reconcile_brs_selected(obligation, evidence).outcome == "drifted"


def test_terminal_evidence_requires_all_independent_legs() -> None:
    obligation = _obligation()
    result = reconcile_brs_selected(obligation, _evidence(obligation, result_evidence_sha256=None))
    assert result.outcome == "manual_review"


def test_explicit_abandoned_terminal_is_not_reported_as_success() -> None:
    obligation = _obligation()
    result = reconcile_brs_selected(obligation, _evidence(obligation, terminal_status="abandoned"))
    assert result.outcome == "abandoned"
    assert result.recommended_phase == "reconcile_required"


def test_evidence_wire_is_strict_and_round_trips() -> None:
    obligation = _obligation()
    evidence = _evidence(obligation)
    assert BRSReconcileEvidence.from_dict(evidence.to_dict()) == evidence
    with pytest.raises(RSILearningError, match="evidence_invalid"):
        BRSReconcileEvidence.from_dict({**evidence.to_dict(), "extra": True})


def test_decision_does_not_mutate_obligation() -> None:
    obligation = _obligation()
    before = obligation.to_dict()
    reconcile_brs_selected(obligation, _evidence(obligation))
    assert obligation.to_dict() == before
