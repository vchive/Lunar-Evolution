"""Controller-owned, opt-in BRS reconcile phase CAS tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT,
    BRSReconcileEvidence,
    BRSReconcileObligation,
    RSILearningError,
    RSILedger,
    SolverRequest,
    reconcile_brs_selected,
)

HEX = "a" * 64


def _request() -> SolverRequest:
    return SolverRequest.build(
        episode_id="episode-1",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="fixture",
    )


def _obligation(request: SolverRequest, checkpoint: str, *, phase: str = "selected") -> BRSReconcileObligation:
    return BRSReconcileObligation(
        run_id="run",
        episode_id=request.episode_id,
        phase=phase,
        handoff_sha256=HEX,
        request_sha256=request.digest(),
        native_plan_sha256=HEX,
        controller_checkpoint_sha256=checkpoint,
        episode_record_sha256=HEX,
        native_claim_sha256=HEX,
        owner_result_sha256=HEX,
        terminal_status="failed" if phase == "reconcile_required" else None,
    )


def _evidence(obligation: BRSReconcileObligation, *, running: bool = False) -> BRSReconcileEvidence:
    if running:
        return BRSReconcileEvidence(
            obligation_sha256=obligation.digest(),
            handoff_sha256=obligation.handoff_sha256,
            request_sha256=obligation.request_sha256,
            native_plan_sha256=obligation.native_plan_sha256,
            controller_checkpoint_sha256=obligation.controller_checkpoint_sha256,
            episode_record_sha256=obligation.episode_record_sha256,
            native_claim_sha256=obligation.native_claim_sha256,
            owner_result_sha256=obligation.owner_result_sha256,
            process_state="running",
            process_evidence_sha256=HEX,
            mailbox_state="inflight",
            transaction_state="prepared",
        )
    return BRSReconcileEvidence(
        obligation_sha256=obligation.digest(),
        handoff_sha256=obligation.handoff_sha256,
        request_sha256=obligation.request_sha256,
        native_plan_sha256=obligation.native_plan_sha256,
        controller_checkpoint_sha256=obligation.controller_checkpoint_sha256,
        episode_record_sha256=obligation.episode_record_sha256,
        native_claim_sha256=obligation.native_claim_sha256,
        owner_result_sha256=obligation.owner_result_sha256,
        process_state="exited",
        process_evidence_sha256=HEX,
        native_evidence_sha256=HEX,
        mailbox_evidence_sha256=HEX,
        result_evidence_sha256=HEX,
        mailbox_state="closed",
        transaction_state="terminal",
        terminal_status="failed",
        controller_observed_terminal=True,
        cleanup_confirmed=True,
    )


def _fixture(tmp_path: Path, *, phase: str = "selected"):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    request = _request()
    payload = {
        "mode": "brs",
        "plan": {"mode": "brs"},
        "budget": {},
        "intents": {request.episode_id: {"request": request.to_dict()}},
    }
    created = ledger.create_run("run", HEX, payload)
    ledger.transition("run", state="running", expected_record_sha256=created.record_sha256)
    state = {"run_id": "run", "intents": payload["intents"], "brs_reconcile_obligations": {}}
    with ledger.controller_lock("run"):
        checkpoint = ledger.write_controller_checkpoint("run", state, expected_sha256=None)
        obligation = _obligation(request, checkpoint, phase=phase)
        checkpoint = ledger.write_brs_reconcile_obligation(
            "run", obligation, expected_checkpoint_sha256=checkpoint,
        )
    return ledger, request, checkpoint


def _current(ledger: RSILedger) -> BRSReconcileObligation:
    raw = ledger.controller_brs_reconcile_obligations("run")["episode-1"]
    return BRSReconcileObligation.from_dict(raw)


def test_running_decision_advances_selected_under_lock_and_cas(tmp_path: Path) -> None:
    ledger, _request_value, checkpoint = _fixture(tmp_path)
    obligation = _current(ledger)
    evidence = _evidence(obligation, running=True)
    decision = reconcile_brs_selected(obligation, evidence)
    assert decision.outcome == "recoverable"
    with ledger.controller_lock("run"):
        next_head = ledger.apply_brs_reconcile_decision(
            "run", "episode-1", decision,
            expected_checkpoint_sha256=checkpoint, evidence=evidence,
        )
    assert next_head != checkpoint
    advanced = _current(ledger)
    assert advanced.phase == "worker_running"
    assert advanced.mailbox_state == "inflight"
    assert advanced.transaction_state == "prepared"
    assert advanced.controller_checkpoint_sha256 == obligation.controller_checkpoint_sha256


def test_terminal_selected_decision_advances_to_reconcile_required(tmp_path: Path) -> None:
    ledger, _request_value, checkpoint = _fixture(tmp_path)
    obligation = _current(ledger)
    evidence = _evidence(obligation)
    decision = reconcile_brs_selected(obligation, evidence)
    assert decision.outcome == "already_terminal"
    with ledger.controller_lock("run"):
        next_head = ledger.apply_brs_reconcile_decision(
            "run", "episode-1", decision,
            expected_checkpoint_sha256=checkpoint, evidence=evidence,
        )
    assert next_head != checkpoint
    advanced = _current(ledger)
    assert advanced.phase == "reconcile_required"
    assert advanced.terminal_status == "failed"
    assert advanced.mailbox_state == "closed"
    assert advanced.transaction_state == "terminal"


def test_terminal_reconcile_required_decision_advances_to_settled(tmp_path: Path) -> None:
    ledger, _request_value, checkpoint = _fixture(tmp_path, phase="reconcile_required")
    obligation = _current(ledger)
    evidence = _evidence(obligation)
    decision = reconcile_brs_selected(obligation, evidence)
    assert decision.outcome == "already_terminal"
    with ledger.controller_lock("run"):
        next_head = ledger.apply_brs_reconcile_decision(
            "run", "episode-1", decision,
            expected_checkpoint_sha256=checkpoint, evidence=evidence,
        )
    assert next_head != checkpoint
    assert _current(ledger).phase == "settled"
    assert _current(ledger).transaction_state == "settled"


def test_manual_review_is_a_read_only_gate(tmp_path: Path) -> None:
    ledger, _request_value, checkpoint = _fixture(tmp_path)
    obligation = _current(ledger)
    evidence = BRSReconcileEvidence(
        obligation_sha256=obligation.digest(),
        handoff_sha256=obligation.handoff_sha256,
        request_sha256=obligation.request_sha256,
        native_plan_sha256=obligation.native_plan_sha256,
        controller_checkpoint_sha256=obligation.controller_checkpoint_sha256,
        episode_record_sha256=obligation.episode_record_sha256,
        native_claim_sha256=obligation.native_claim_sha256,
        owner_result_sha256=obligation.owner_result_sha256,
        process_state="unknown",
        process_evidence_sha256=HEX,
    )
    decision = reconcile_brs_selected(obligation, evidence)
    assert decision.outcome == "manual_review"
    before = ledger.controller_checkpoint_history("run")
    with ledger.controller_lock("run"):
        assert ledger.apply_brs_reconcile_decision(
            "run", "episode-1", decision,
            expected_checkpoint_sha256=checkpoint, evidence=evidence,
        ) == checkpoint
    assert ledger.controller_checkpoint_history("run") == before


def test_stale_checkpoint_is_rejected_without_mutation(tmp_path: Path) -> None:
    ledger, _request_value, checkpoint = _fixture(tmp_path)
    obligation = _current(ledger)
    evidence = _evidence(obligation, running=True)
    decision = reconcile_brs_selected(obligation, evidence)
    with ledger.controller_lock("run"):
        state = ledger.controller_checkpoint("run")[1]
        current = ledger.write_controller_checkpoint(
            "run", {**state, "foreign": True}, expected_sha256=checkpoint,
        )
        with pytest.raises(RSILearningError, match="checkpoint_conflict"):
            ledger.apply_brs_reconcile_decision(
                "run", "episode-1", decision,
                expected_checkpoint_sha256=checkpoint, evidence=evidence,
            )
    assert ledger.controller_checkpoint("run")[0] == current
    assert _current(ledger).phase == "selected"


def test_decision_and_evidence_binding_conflicts_are_rejected(tmp_path: Path) -> None:
    ledger, _request_value, checkpoint = _fixture(tmp_path)
    obligation = _current(ledger)
    evidence = _evidence(obligation, running=True)
    decision = reconcile_brs_selected(obligation, evidence)
    changed = _evidence(obligation)
    with ledger.controller_lock("run"), pytest.raises(
        RSILearningError, match="decision_evidence_conflict"
    ):
            ledger.apply_brs_reconcile_decision(
                "run", "episode-1", decision,
                expected_checkpoint_sha256=checkpoint, evidence=changed,
            )
