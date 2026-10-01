"""Outer holdout reconciliation consumes the same parent unknown-recovery budget."""

from __future__ import annotations

from pathlib import Path

import pytest

from lunar_evolution.rsi_callbacks import DurableCallbackJournal
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver
from lunar_evolution.rsi_governance_coordinator import (
    GenerationGovernanceError,
    GenerationGovernancePolicy,
    RSIGovernanceCoordinator,
)
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_memory_governance import MemoryGovernanceStore
from lunar_evolution.rsi_parent_budget import ParentRunBudget
from lunar_evolution.rsi_store import RSILedger
from tests.test_rsi_governance_coordinator import PINS, FixtureRegression, activate, digest


def fixture(tmp_path: Path, *, unknown_limit=1, deadline=None):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    owner = RSILearningController(DeterministicMockSolver(), ledger=ledger)
    result = owner.run_drs(
        run_id="parent", contract_sha256=PINS["contract"], evaluator_sha256=PINS["evaluator"],
        environment_sha256=PINS["environment"], solver_id="mock", max_practice_rounds=0,
        max_target_attempts=1, budget={"max_unknown_retries": unknown_limit, "deadline_unix": deadline},
    )
    assert result.status == "completed"
    coordinator = RSIGovernanceCoordinator(
        MemoryGovernanceStore(tmp_path / "governance.sqlite3"), ledger=ledger, scope="fixture",
        compatibility=PINS, policy=GenerationGovernancePolicy(),
    )
    account = ParentRunBudget(ledger, "parent")

    class ParentFixture(FixtureRegression):
        def rsi_fingerprint_config(self):
            return {**super().rsi_fingerprint_config(), "parent": account.identity()}

    return coordinator, ParentFixture(fail=True), account


def arguments(coordinator, runner, validation_id=None):
    callback_id = "holdout" if validation_id is None else "revalidation:" + validation_id
    head, callback = coordinator.callbacks.inspect(coordinator._namespace("generation-1"), callback_id)
    report = runner.report(runner.request)
    result = coordinator.serialize_report(report)
    evidence = {"source": "trusted-local-fixture", "binding_sha256": callback["binding_sha256"],
                "result_sha256": DurableCallbackJournal.digest(result), "receipt_sha256": digest("observed")}
    return {"expected_checkpoint_sha256": head, "report": report, "evidence": evidence,
            "validation_id": validation_id}


def test_zero_unknown_budget_refuses_outer_reconcile_before_callback_or_promotion(tmp_path):
    coordinator, runner, account = fixture(tmp_path, unknown_limit=0)
    _snapshot, initial = activate(coordinator, runner=runner)
    assert initial.status == "unknown"
    before = coordinator.ledger.controller_checkpoint("parent")
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        coordinator.reconcile_holdout("generation-1", **arguments(coordinator, runner))
    assert coordinator.ledger.controller_checkpoint("parent") == before
    assert coordinator.inspect("generation-1")[1]["phase"] == "unknown"
    assert coordinator.callbacks.inspect(coordinator._namespace("generation-1"), "holdout")[1]["status"] == "started"
    assert runner.calls == 1
    account.validate_history()


def test_outer_reconcile_charges_once_and_terminal_exact_replay_is_read_only(tmp_path):
    coordinator, runner, account = fixture(tmp_path)
    snapshot, _initial = activate(coordinator, runner=runner)
    args = arguments(coordinator, runner)
    result = coordinator.reconcile_holdout("generation-1", **args)
    assert result.status == "active"
    coordinator.validate(snapshot)
    before = coordinator.ledger.controller_checkpoint("parent")
    assert before[1]["budget_state"]["consumed"]["unknown_retries"] == 1
    assert len(before[1]["external_budget_reservations"]) == 1
    coordinator.reconcile_holdout("generation-1", **args)
    assert coordinator.ledger.controller_checkpoint("parent") == before
    assert runner.calls == 1
    account.validate_history()


def test_crash_after_parent_charge_resumes_without_second_charge(tmp_path, monkeypatch):
    coordinator, runner, _account = fixture(tmp_path)
    activate(coordinator, runner=runner)
    args = arguments(coordinator, runner)
    reconcile = coordinator.callbacks.reconcile

    def interrupt(*args, **kwargs):
        raise RuntimeError("before outer reconciliation publication")

    monkeypatch.setattr(coordinator.callbacks, "reconcile", interrupt)
    with pytest.raises(RuntimeError, match="outer reconciliation"):
        coordinator.reconcile_holdout("generation-1", **args)
    before = coordinator.ledger.controller_checkpoint("parent")
    assert before[1]["budget_state"]["consumed"]["unknown_retries"] == 1
    assert coordinator.callbacks.inspect(coordinator._namespace("generation-1"), "holdout")[1]["status"] == "started"
    monkeypatch.setattr(coordinator.callbacks, "reconcile", reconcile)
    assert coordinator.reconcile_holdout("generation-1", **args).status == "active"
    assert coordinator.ledger.controller_checkpoint("parent") == before
    assert runner.calls == 1


def test_precharged_outer_recovery_cannot_change_evidence_binding(tmp_path, monkeypatch):
    coordinator, runner, _account = fixture(tmp_path)
    activate(coordinator, runner=runner)
    args = arguments(coordinator, runner)
    reconcile = coordinator.callbacks.reconcile

    def interrupt(*args, **kwargs):
        raise RuntimeError("before callback publication")

    monkeypatch.setattr(coordinator.callbacks, "reconcile", interrupt)
    with pytest.raises(RuntimeError):
        coordinator.reconcile_holdout("generation-1", **args)
    monkeypatch.setattr(coordinator.callbacks, "reconcile", reconcile)
    before = coordinator.ledger.controller_checkpoint("parent")
    changed = {**args, "evidence": {**args["evidence"], "source": "changed-source"}}
    with pytest.raises(RSILearningError, match="reservation_drift"):
        coordinator.reconcile_holdout("generation-1", **changed)
    assert coordinator.ledger.controller_checkpoint("parent") == before
    assert coordinator.inspect("generation-1")[1]["phase"] == "unknown"


def test_invalid_outer_evidence_does_not_consume_parent_recovery_budget(tmp_path):
    coordinator, runner, _account = fixture(tmp_path)
    activate(coordinator, runner=runner)
    args = arguments(coordinator, runner)
    args["evidence"]["binding_sha256"] = digest("wrong")
    before = coordinator.ledger.controller_checkpoint("parent")
    with pytest.raises(RSILearningError, match="evidence_invalid"):
        coordinator.reconcile_holdout("generation-1", **args)
    assert coordinator.ledger.controller_checkpoint("parent") == before


def test_recording_observed_report_after_deadline_does_not_refresh_dispatch(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: now[0])
    coordinator, runner, account = fixture(tmp_path, deadline=101.0)
    activate(coordinator, runner=runner)
    args = arguments(coordinator, runner)
    now[0] = 102.0
    assert coordinator.reconcile_holdout("generation-1", **args).status == "active"
    state = coordinator.ledger.controller_checkpoint("parent")[1]
    assert state["budget_state"]["planned"]["deadline_unix"] == 101.0
    assert state["budget_state"]["consumed"]["unknown_retries"] == 1
    with pytest.raises(RSILearningError, match="budget_exhausted"):
        account.check_dispatch()


def test_revalidation_outer_reconcile_uses_its_bound_parent_account(tmp_path):
    coordinator, runner, _account = fixture(tmp_path)
    snapshot, _initial = activate(coordinator)
    coordinator.revalidate_generation("generation-1", "scheduled", runner)
    state = coordinator.inspect("generation-1")[1]
    assert state["intent"]["runner_parent"] is None
    assert state["validations"]["scheduled"]["runner_parent"]["run_id"] == "parent"
    assert coordinator.reconcile_holdout("generation-1", **arguments(coordinator, runner, "scheduled")).status == "active"
    coordinator.validate(snapshot)
    assert coordinator.ledger.controller_checkpoint("parent")[1]["budget_state"]["consumed"]["unknown_retries"] == 1


def test_cross_ledger_standard_parent_pin_refused_before_generation_or_runner(tmp_path):
    coordinator, runner, _account = fixture(tmp_path / "parent")
    other = RSIGovernanceCoordinator(
        MemoryGovernanceStore(tmp_path / "other" / "governance.sqlite3"),
        ledger=RSILedger(tmp_path / "other" / "rsi.sqlite3"), scope="fixture",
        compatibility=PINS, policy=GenerationGovernancePolicy(),
    )
    with pytest.raises(GenerationGovernanceError, match="parent_budget_identity_drift"):
        activate(other, runner=runner)
    assert runner.calls == 0
    assert other.inspect("generation-1") is None
    assert coordinator.ledger.controller_checkpoint("parent")[1]["budget_state"]["consumed"]["unknown_retries"] == 0


def test_wrong_outer_expected_checkpoint_does_not_charge_parent(tmp_path):
    coordinator, runner, _account = fixture(tmp_path)
    activate(coordinator, runner=runner)
    args = arguments(coordinator, runner)
    args["expected_checkpoint_sha256"] = digest("wrong-checkpoint")
    before = coordinator.ledger.controller_checkpoint("parent")
    with pytest.raises(RSILearningError, match="checkpoint_conflict"):
        coordinator.reconcile_holdout("generation-1", **args)
    assert coordinator.ledger.controller_checkpoint("parent") == before


def test_conflicting_completed_reconciliation_cannot_charge_parent(tmp_path):
    coordinator, runner, _account = fixture(tmp_path, unknown_limit=2)
    activate(coordinator, runner=runner)
    args = arguments(coordinator, runner)
    coordinator.reconcile_holdout("generation-1", **args)
    before = coordinator.ledger.controller_checkpoint("parent")
    args["evidence"]["source"] = "different-source"
    with pytest.raises(RSILearningError, match="reconcile_conflict"):
        coordinator.reconcile_holdout("generation-1", **args)
    assert coordinator.ledger.controller_checkpoint("parent") == before
    assert before[1]["budget_state"]["consumed"]["unknown_retries"] == 1


def test_parent_lock_contention_refuses_reconcile_without_generation_writes(tmp_path):
    coordinator, runner, _account = fixture(tmp_path)
    activate(coordinator, runner=runner)
    args = arguments(coordinator, runner)
    other = RSILedger(coordinator.ledger.database)
    before = coordinator.inspect("generation-1")
    with other.controller_lock("parent"), pytest.raises(RSILearningError, match="controller_busy"):
        coordinator.reconcile_holdout("generation-1", **args)
    assert coordinator.inspect("generation-1") == before
    assert runner.calls == 1
