"""Learning and holdout share the original local durable budget."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_parent_budget import ParentRunBudget
from lunar_evolution.rsi_regression_campaign import DurableRegressionCampaign
from lunar_evolution.rsi_store import RSILedger
from tests.test_rsi_regression_campaign import Runner, campaign_args, digest


def parent(tmp_path: Path, budget=None):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(DeterministicMockSolver(), ledger=ledger)
    result = controller.run_drs(run_id="parent", contract_sha256=digest("contract"),
                                evaluator_sha256=digest("evaluator"), environment_sha256=digest("environment"),
                                solver_id="mock", max_practice_rounds=0, max_target_attempts=1, budget=budget)
    assert result.status == "completed"
    return ledger, ParentRunBudget(ledger, "parent")


def test_parent_already_consumed_evaluator_budget_limits_holdout(tmp_path: Path):
    ledger, account = parent(tmp_path, {"max_evaluator_invocations": 18, "max_transfer_invocations": 100})
    runner = Runner()
    campaign = DurableRegressionCampaign(ledger)
    with pytest.raises(RSILearningError, match="budget_exhausted"):
        campaign.run(**campaign_args(runner, parent_budget=account))
    assert runner.calls == 17
    state = ledger.controller_checkpoint("parent")[1]
    assert state["budget_state"]["consumed"]["evaluator_invocations"] == 18
    assert state["budget_state"]["consumed"]["transfer_invocations"] == 17
    assert len(state["external_budget_reservations"]) == 17


def test_two_campaigns_share_budget_and_completed_replay_does_not_charge(tmp_path: Path):
    ledger, account = parent(tmp_path, {"max_evaluator_invocations": 37, "max_transfer_invocations": 36})
    campaign, runner = DurableRegressionCampaign(ledger), Runner()
    first_args = campaign_args(runner, parent_budget=account)
    first = campaign.run(**first_args)
    second = campaign.run(**{**first_args, "admission_id": "second"})
    assert first.promotion_eligible and second.promotion_eligible and runner.calls == 36
    before = ledger.controller_checkpoint("parent")
    assert before[1]["budget_state"]["consumed"]["evaluator_invocations"] == 37
    assert campaign.run(**first_args).report_sha256 == first.report_sha256
    assert ledger.controller_checkpoint("parent") == before
    assert runner.calls == 36


def test_crash_after_parent_charge_reuses_event_without_second_charge(tmp_path: Path, monkeypatch):
    ledger, account = parent(tmp_path)
    campaign, runner = DurableRegressionCampaign(ledger), Runner()
    original = ledger.write_controller_checkpoint

    def interrupt(scope, state, **kwargs):
        if scope.startswith("rsi-regression:") and state["reservations"]:
            raise RuntimeError("after parent charge")
        return original(scope, state, **kwargs)

    monkeypatch.setattr(ledger, "write_controller_checkpoint", interrupt)
    with pytest.raises(RuntimeError, match="parent charge"):
        campaign.run(**campaign_args(runner, parent_budget=account))
    assert runner.calls == 0
    assert len(ledger.controller_checkpoint("parent")[1]["external_budget_reservations"]) == 1
    monkeypatch.setattr(ledger, "write_controller_checkpoint", original)
    assert campaign.run(**campaign_args(runner, parent_budget=account)).promotion_eligible
    assert runner.calls == 18
    state = ledger.controller_checkpoint("parent")[1]
    assert state["budget_state"]["consumed"]["evaluator_invocations"] == 19
    assert len(state["external_budget_reservations"]) == 18


def test_parent_deadline_controls_unstarted_reserved_callback(tmp_path: Path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: now[0])
    ledger, account = parent(tmp_path, {"deadline_unix": 101})
    runner, campaign = Runner(), DurableRegressionCampaign(ledger)
    original = ledger.write_controller_checkpoint

    def interrupt(scope, state, **kwargs):
        if state.get("kind") == "durable_callback":
            raise RuntimeError("before callback started")
        return original(scope, state, **kwargs)

    monkeypatch.setattr(ledger, "write_controller_checkpoint", interrupt)
    with pytest.raises(RuntimeError):
        campaign.run(**campaign_args(runner, parent_budget=account))
    now[0] = 102.0
    monkeypatch.setattr(ledger, "write_controller_checkpoint", original)
    with pytest.raises(RSILearningError, match="budget_exhausted"):
        campaign.run(**campaign_args(runner, parent_budget=account))
    assert runner.calls == 0


def test_reconcile_charges_parent_once_after_dispatch_deadline(tmp_path: Path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: now[0])
    ledger, account = parent(tmp_path, {"deadline_unix": 101, "max_unknown_retries": 1})
    campaign, runner = DurableRegressionCampaign(ledger), Runner(interrupt_at=1)
    with pytest.raises(RuntimeError):
        campaign.run(**campaign_args(runner, parent_budget=account))
    now[0] = 102.0
    callback_id = "trial:no_memory:0:0"
    checkpoint_sha, state = campaign.callbacks.inspect(campaign.scope("admission"), callback_id)
    result = {"passed": True, "score": 0.5, "cost": 0.0, "accessed_task_ids": [], "memory_ids_used": []}
    evidence = {"source": "local-fixture", "binding_sha256": state["binding_sha256"],
                "result_sha256": campaign.callbacks.digest(result), "receipt_sha256": digest("receipt")}
    for _ in range(2):
        campaign.reconcile_trial("admission", callback_id, expected_checkpoint_sha256=checkpoint_sha,
                                 result=result, evidence=evidence)
    assert ledger.controller_checkpoint("parent")[1]["budget_state"]["consumed"]["unknown_retries"] == 1
    assert runner.calls == 1


def test_synchronize_preserves_external_and_new_learning_charges(tmp_path: Path):
    ledger, account = parent(tmp_path)
    local = deepcopy(ledger.controller_checkpoint("parent")[1])
    account.reserve("holdout", "trial", {"input": "public"})
    remote = ledger.controller_checkpoint("parent")[1]
    local["budget_state"]["consumed"]["solver_invocations"] += 1
    ParentRunBudget.synchronize(local, remote)
    assert local["budget_state"]["consumed"]["solver_invocations"] == 2
    assert local["budget_state"]["consumed"]["evaluator_invocations"] == 2
    assert local["budget_state"]["consumed"]["transfer_invocations"] == 1
    before = deepcopy(local)
    ParentRunBudget.synchronize(local, remote)
    assert local == before


def test_parent_lock_excludes_another_ledger_dispatch(tmp_path: Path):
    ledger, _account = parent(tmp_path)
    other = ParentRunBudget(RSILedger(ledger.database), "parent")
    runner = Runner()
    with ledger.controller_lock("parent"), pytest.raises(RSILearningError, match="controller_busy"):
        DurableRegressionCampaign(other.ledger).run(**campaign_args(runner, parent_budget=other))
    assert runner.calls == 0


@pytest.mark.parametrize("corruption", ["missing", "binding", "unaccounted"])
def test_controller_resume_rejects_hash_valid_external_receipt_corruption(tmp_path: Path, corruption: str):
    ledger, account = parent(tmp_path)
    account.reserve("holdout", "trial", {"input": "public"})
    checkpoint_sha, state = ledger.controller_checkpoint("parent")
    changed = deepcopy(state)
    events = changed["external_budget_reservations"]
    if corruption == "missing":
        events.clear()
    elif corruption == "binding":
        events[next(iter(events))]["binding_sha256"] = digest("changed-binding")
    else:
        events[digest("uncharged-event")] = {"binding_sha256": digest("binding"), "kind": "trial"}
    with ledger.controller_lock("parent"):
        ledger.write_controller_checkpoint("parent", changed, expected_sha256=checkpoint_sha)
    original = ledger.controller_checkpoint("parent")
    controller = RSILearningController(DeterministicMockSolver(), ledger=RSILedger(ledger.database))
    with pytest.raises(RSILearningError, match="parent_budget_checkpoint_corrupt"):
        controller.resume("parent")
    assert ledger.controller_checkpoint("parent") == original


def test_cross_ledger_parent_budget_rejected_before_charge_or_runner(tmp_path: Path):
    parent_ledger, account = parent(tmp_path / "parent")
    campaign_ledger = RSILedger(tmp_path / "campaign" / "rsi.sqlite3")
    campaign, runner = DurableRegressionCampaign(campaign_ledger), Runner()
    original = parent_ledger.controller_checkpoint("parent")
    with pytest.raises(RSILearningError, match="parent_budget_ledger_mismatch"):
        campaign.run(**campaign_args(runner, parent_budget=account))
    assert runner.calls == 0
    assert campaign.inspect("admission") is None
    assert parent_ledger.controller_checkpoint("parent") == original
