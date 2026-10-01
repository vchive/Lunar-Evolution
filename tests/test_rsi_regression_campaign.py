"""Local holdout crash boundaries; no solver/provider/evaluator service is contacted."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.rsi_callbacks import DurableCallbackJournal
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver, RSIMemoryStore
from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot, RSILearningError
from lunar_evolution.rsi_memory_governance import MemoryAdmissionRecord, MemoryGovernanceStore
from lunar_evolution.rsi_memory_promotion import MemoryPromotionError
from lunar_evolution.rsi_regression_campaign import DurableRegressionCampaign
from lunar_evolution.rsi_store import RSILedger
from lunar_evolution.rsi_transfer_regression import (
    RegressionPolicy,
    TransferObservation,
    TransferTask,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def snapshot(name: str) -> MemorySnapshot:
    return MemorySnapshot(name, None, (MemoryItem(
        memory_id=name, episode_id="episode", receipt_sha256=digest("verifier"),
        strategy="local", trigger="public", expected_result="pass", failure_boundary="fixture",
        problem_family="fixture", compatible_contracts=(digest("contract"),),
        compatible_solvers=("fixture",), verifier_outcome="pass",
    ),))


def manifest() -> tuple[TransferTask, ...]:
    return (
        TransferTask("seen", "a", "seen", "seen", digest("seen")),
        TransferTask("unseen-a", "a", "unseen", "a", digest("a")),
        TransferTask("unseen-b", "b", "unseen", "b", digest("b")),
    )


class Runner:
    def __init__(self, *, interrupt_at: int | None = None, score: float = 0.9) -> None:
        self.calls = 0
        self.interrupt_at = interrupt_at
        self.score = score

    def rsi_fingerprint_config(self):
        return {"score": self.score, "fixture": "public-local"}

    def __call__(self, task, memory, repetition):
        del repetition
        self.calls += 1
        if self.calls == self.interrupt_at:
            raise RuntimeError("local interruption")
        return TransferObservation(
            True, self.score if memory.snapshot_id == "current" else 0.5,
            accessed_task_ids=(task.task_id,), memory_ids_used=tuple(item.memory_id for item in memory.items),
        )


def campaign_args(runner: Runner, **extra):
    return {
        "admission_id": "admission", "initial_record_sha256": digest("shadow"),
        "tasks": manifest(), "old_memory": snapshot("old"), "current_memory": snapshot("current"),
        "policy": RegressionPolicy(), "runner": runner, "controller_pins": {"solver": digest("solver")},
        "check_components": lambda: None, **extra,
    }


def test_completed_trials_and_terminal_report_replay_without_calls_or_charges(tmp_path: Path):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    campaign = DurableRegressionCampaign(ledger)
    runner = Runner()
    args = campaign_args(runner)
    report = campaign.run(**args)
    checkpoint = campaign.inspect("admission")
    assert checkpoint[1]["budget_state"]["consumed"]["transfer_invocations"] == 18
    assert checkpoint[1]["budget_state"]["consumed"]["evaluator_invocations"] == 18
    resumed_runner = Runner(interrupt_at=1)
    resumed = DurableRegressionCampaign(RSILedger(ledger.database))
    replay = resumed.run(**campaign_args(resumed_runner))
    assert replay.report_sha256 == report.report_sha256
    assert resumed_runner.calls == 0
    assert resumed.inspect("admission") == checkpoint


def test_crash_after_completed_trial_reuses_observation(tmp_path: Path, monkeypatch):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    campaign = DurableRegressionCampaign(ledger)
    original = campaign.callbacks.invoke

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("crash after completed callback")

    monkeypatch.setattr(campaign.callbacks, "invoke", interrupted)
    first = Runner()
    with pytest.raises(RuntimeError, match="completed callback"):
        campaign.run(**campaign_args(first))
    assert first.calls == 1
    resumed_runner = Runner()
    result = DurableRegressionCampaign(RSILedger(ledger.database)).run(**campaign_args(resumed_runner))
    assert result.promotion_eligible
    assert resumed_runner.calls == 17
    assert campaign.inspect("admission")[1]["budget_state"]["consumed"]["transfer_invocations"] == 18


def test_unknown_trial_requires_bound_reconcile_without_repeat_or_refund(tmp_path: Path):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    campaign = DurableRegressionCampaign(ledger)
    runner = Runner(interrupt_at=1)
    with pytest.raises(RuntimeError, match="interruption"):
        campaign.run(**campaign_args(runner))
    runner.interrupt_at = None
    with pytest.raises(RSILearningError, match="reconcile_required"):
        campaign.run(**campaign_args(runner))
    assert runner.calls == 1
    scope = campaign.scope("admission")
    callback_id = "trial:no_memory:0:0"
    checkpoint_sha, state = campaign.callbacks.inspect(scope, callback_id)
    observation = TransferObservation(True, 0.5, accessed_task_ids=("seen",)).to_dict()
    evidence = {
        "source": "trusted-local-fixture", "binding_sha256": state["binding_sha256"],
        "result_sha256": DurableCallbackJournal.digest(observation), "receipt_sha256": digest("receipt"),
    }
    with pytest.raises(RSILearningError, match="evidence_invalid"):
        campaign.reconcile_trial("admission", callback_id, expected_checkpoint_sha256=checkpoint_sha,
                                 result=observation, evidence={**evidence, "binding_sha256": digest("wrong")})
    campaign.reconcile_trial("admission", callback_id, expected_checkpoint_sha256=checkpoint_sha,
                             result=observation, evidence=evidence)
    campaign.reconcile_trial("admission", callback_id, expected_checkpoint_sha256=checkpoint_sha,
                             result=observation, evidence=evidence)
    assert campaign.inspect("admission")[1]["budget_state"]["consumed"]["unknown_retries"] == 1
    result = campaign.run(**campaign_args(runner))
    assert result.promotion_eligible and runner.calls == 18
    assert campaign.inspect("admission")[1]["budget_state"]["consumed"]["transfer_invocations"] == 18


def test_zero_reconciliation_budget_cannot_register_an_unknown_result(tmp_path: Path):
    campaign = DurableRegressionCampaign(RSILedger(tmp_path / "rsi.sqlite3"))
    runner = Runner(interrupt_at=1)
    with pytest.raises(RuntimeError):
        campaign.run(**campaign_args(runner, budget={"max_unknown_retries": 0}))
    callback_id = "trial:no_memory:0:0"
    checkpoint_sha, state = campaign.callbacks.inspect(campaign.scope("admission"), callback_id)
    result = TransferObservation(True, 0.5).to_dict()
    evidence = {"source": "local-fixture", "binding_sha256": state["binding_sha256"],
                "result_sha256": campaign.callbacks.digest(result), "receipt_sha256": digest("receipt")}
    before = campaign.inspect("admission")
    with pytest.raises(RSILearningError, match="budget_exhausted"):
        campaign.reconcile_trial("admission", callback_id, expected_checkpoint_sha256=checkpoint_sha,
                                 result=result, evidence=evidence)
    assert campaign.inspect("admission") == before
    assert campaign.callbacks.inspect(campaign.scope("admission"), callback_id)[1]["status"] == "started"


def test_crash_between_reservation_and_started_retains_single_charge(tmp_path: Path, monkeypatch):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    campaign = DurableRegressionCampaign(ledger)
    original = ledger.write_controller_checkpoint

    def interrupted(scope, state, **kwargs):
        if state.get("kind") == "durable_callback":
            raise RuntimeError("crash before started write")
        return original(scope, state, **kwargs)

    monkeypatch.setattr(ledger, "write_controller_checkpoint", interrupted)
    runner = Runner()
    with pytest.raises(RuntimeError, match="started write"):
        campaign.run(**campaign_args(runner))
    assert runner.calls == 0
    assert campaign.inspect("admission")[1]["reservations"] == ["trial:no_memory:0:0"]
    resumed = DurableRegressionCampaign(RSILedger(ledger.database))
    resumed.run(**campaign_args(runner))
    assert runner.calls == 18
    assert resumed.inspect("admission")[1]["budget_state"]["consumed"]["evaluator_invocations"] == 18


@pytest.mark.parametrize("changed", ["runner", "manifest", "policy", "budget", "controller"])
def test_intent_drift_stops_before_new_calls(tmp_path: Path, changed: str):
    campaign = DurableRegressionCampaign(RSILedger(tmp_path / "rsi.sqlite3"))
    runner = Runner(interrupt_at=1)
    args = campaign_args(runner)
    with pytest.raises(RuntimeError):
        campaign.run(**args)
    runner.interrupt_at = None
    if changed == "runner":
        runner.score = 0.8
    elif changed == "manifest":
        args["tasks"] = (replace(manifest()[0], input_sha256=digest("new-input")), *manifest()[1:])
    elif changed == "policy":
        args["policy"] = RegressionPolicy(min_unseen_pass_rate=0.5)
    elif changed == "budget":
        args["budget"] = {"max_transfer_invocations": 100}
    else:
        args["controller_pins"] = {"solver": digest("changed")}
    with pytest.raises(RSILearningError, match="intent_drift"):
        campaign.run(**args)
    assert runner.calls == 1


def test_count_exhaustion_is_atomic_persistent_and_cannot_be_refreshed(tmp_path: Path):
    campaign = DurableRegressionCampaign(RSILedger(tmp_path / "rsi.sqlite3"))
    runner = Runner()
    args = campaign_args(runner, budget={"max_transfer_invocations": 1, "max_evaluator_invocations": 10})
    with pytest.raises(RSILearningError, match="budget_exhausted"):
        campaign.run(**args)
    state = campaign.inspect("admission")[1]
    assert state["phase"] == "budget_exhausted"
    assert state["budget_state"]["consumed"]["transfer_invocations"] == 1
    assert state["budget_state"]["consumed"]["evaluator_invocations"] == 1
    with pytest.raises(RSILearningError, match="budget_exhausted"):
        campaign.run(**args)
    assert runner.calls == 1
    with pytest.raises(RSILearningError, match="intent_drift"):
        campaign.run(**{**args, "budget": {"max_transfer_invocations": 100}})


def test_terminal_replay_after_deadline_and_late_callback_rejection(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 100.0)
    campaign = DurableRegressionCampaign(RSILedger(tmp_path / "rsi.sqlite3"))
    runner = Runner()
    args = campaign_args(runner, budget={"deadline_unix": 101})
    report = campaign.run(**args)
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 200.0)
    assert campaign.run(**args).report_sha256 == report.report_sha256
    assert runner.calls == 18
    other = DurableRegressionCampaign(RSILedger(tmp_path / "other.sqlite3"))
    with pytest.raises(RSILearningError, match="budget_exhausted"):
        other.run(**args)
    assert other.inspect("admission")[1]["phase"] == "budget_exhausted"
    assert runner.calls == 18


def test_concurrent_campaign_cannot_start_runner(tmp_path: Path):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    campaign = DurableRegressionCampaign(ledger)
    runner = Runner()
    with ledger.controller_lock(campaign.scope("admission")), pytest.raises(RSILearningError, match="controller_busy"):
        DurableRegressionCampaign(RSILedger(ledger.database)).run(**campaign_args(runner))
    assert runner.calls == 0


def test_excessive_trial_count_rejected_before_journal_or_callback(tmp_path: Path):
    campaign = DurableRegressionCampaign(RSILedger(tmp_path / "rsi.sqlite3"))
    runner = Runner()
    with pytest.raises(RSILearningError, match="trial_limit"):
        campaign.run(**campaign_args(runner, policy=RegressionPolicy(repetitions=10**12),
                                     budget={"max_transfer_invocations": 1}))
    assert runner.calls == 0 and campaign.inspect("admission") is None


def test_hash_valid_counter_rewrite_is_rejected(tmp_path: Path):
    from copy import deepcopy

    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    campaign = DurableRegressionCampaign(ledger)
    runner = Runner(interrupt_at=1)
    with pytest.raises(RuntimeError):
        campaign.run(**campaign_args(runner))
    checkpoint_sha, state = campaign.inspect("admission")
    changed = deepcopy(state)
    changed["budget_state"]["consumed"]["transfer_invocations"] = 0
    with ledger.controller_lock(campaign.scope("admission")):
        ledger.write_controller_checkpoint(campaign.scope("admission"), changed, expected_sha256=checkpoint_sha)
    with pytest.raises(RSILearningError, match="checkpoint_corrupt"):
        campaign.run(**campaign_args(runner))
    assert runner.calls == 1


def test_nested_controller_pins_are_frozen_and_live_mutation_is_quarantined(tmp_path: Path):
    pins = {"external": {"mode": "frozen"}}

    class MutatingRunner(Runner):
        def __call__(self, task, memory, repetition):
            result = super().__call__(task, memory, repetition)
            pins["external"]["mode"] = "changed"
            return result

    runner = MutatingRunner()
    campaign = DurableRegressionCampaign(RSILedger(tmp_path / "rsi.sqlite3"))
    with pytest.raises(RSILearningError, match="controller_drift"):
        campaign.run(**campaign_args(runner, controller_pins=pins))
    state = campaign.inspect("admission")[1]
    assert state["intent"]["controller_pins"]["external"]["mode"] == "frozen"
    assert campaign.callbacks.inspect(campaign.scope("admission"), "trial:no_memory:0:0")[1]["status"] == "started"


def test_malformed_memory_intent_reports_fixed_corruption_error(tmp_path: Path):
    from copy import deepcopy

    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    campaign = DurableRegressionCampaign(ledger)
    runner = Runner(interrupt_at=1)
    with pytest.raises(RuntimeError):
        campaign.run(**campaign_args(runner))
    checkpoint_sha, state = campaign.inspect("admission")
    changed = deepcopy(state)
    changed["intent"]["memories"] = []
    changed["intent_sha256"] = campaign.callbacks.digest(changed["intent"])
    with ledger.controller_lock(campaign.scope("admission")):
        ledger.write_controller_checkpoint(campaign.scope("admission"), changed, expected_sha256=checkpoint_sha)
    with pytest.raises(RSILearningError, match="checkpoint_corrupt"):
        campaign.inspect("admission")


def test_controller_reuses_campaign_after_crash_before_governance_append(tmp_path: Path, monkeypatch):
    old, current = snapshot("old"), snapshot("current")
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current), ledger=ledger)
    governance = MemoryGovernanceStore(tmp_path / "governance.sqlite3")
    record = governance.create(MemoryAdmissionRecord(
        admission_id="admission", memory_snapshot_sha256=current.digest(), memory_item_sha256=digest("item"),
        source_episode_id="episode", verifier_receipt_sha256=digest("verifier"),
        parent_snapshot_sha256=old.digest(), scope="fixture", compatibility={},
    ))
    for state in ("verified", "candidate", "shadow"):
        record = governance.transition(record.admission_id, state, expected_record_sha256=record.record_sha256)
    runner = Runner()
    args = {"governance": governance, "admission_id": record.admission_id,
            "expected_record_sha256": record.record_sha256, "old_memory": old,
            "tasks": manifest(), "runner": runner}
    original = governance.transition

    def interrupt(*args, **kwargs):
        raise RuntimeError("crash before approval")

    monkeypatch.setattr(governance, "transition", interrupt)
    with pytest.raises(RuntimeError, match="approval"):
        controller.promote_transfer_regression(**args)
    assert runner.calls == 18
    monkeypatch.setattr(governance, "transition", original)
    resumed = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current),
                                    ledger=RSILedger(ledger.database))
    report, approved = resumed.promote_transfer_regression(**args)
    assert report.promotion_eligible and approved.state == "approved"
    assert runner.calls == 18
    changed_tasks = (replace(manifest()[0], input_sha256=digest("other")), *manifest()[1:])
    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        resumed.promote_transfer_regression(**{**args, "expected_record_sha256": approved.record_sha256,
                                               "tasks": changed_tasks, "activate": True})
    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        resumed.promote_transfer_regression(**{**args, "expected_record_sha256": approved.record_sha256,
                                               "policy": RegressionPolicy(min_unseen_pass_rate=0.5), "activate": True})
