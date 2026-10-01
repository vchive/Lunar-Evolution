"""Controller promotion uses the parent account without fresh-budget or replay bypasses."""

from __future__ import annotations

from dataclasses import replace

import pytest

from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver, RSIMemoryStore
from lunar_evolution.rsi_generation_campaign import GenerationCampaignRunner
from lunar_evolution.rsi_governance_coordinator import GenerationRegressionRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, RSILearningError
from lunar_evolution.rsi_memory_promotion import MemoryPromotionError
from lunar_evolution.rsi_store import RSILedger
from lunar_evolution.rsi_transfer_regression import RegressionPolicy, TransferObservation
from tests.test_rsi_controller_generation import controller as generation_controller
from tests.test_rsi_controller_generation import run as generation_run
from tests.test_rsi_controller_promotion import digest, manifest, shadow_admission, snapshot
from tests.test_rsi_parent_budget import parent


class Holdout:
    def __init__(self):
        self.calls = 0

    def rsi_fingerprint_config(self):
        return {"fixture": "controller-parent-promotion-v1"}

    def __call__(self, task, memory, repetition):
        self.calls += 1
        return TransferObservation(
            True, 0.9 if memory.snapshot_id == "current" else 0.3,
            accessed_task_ids=(task.task_id,), memory_ids_used=tuple(item.memory_id for item in memory.items),
        )


def setup(tmp_path, budget=None):
    ledger, _account = parent(tmp_path / "parent", budget)
    old, current = snapshot("old", "old-item"), snapshot("current", "current-item")
    governance, shadow = shadow_admission(tmp_path, old, current)
    controller = RSILearningController(DeterministicMockSolver(), ledger=ledger, memory_store=RSIMemoryStore(current))
    return controller, governance, shadow, old, current


def promote(controller, governance, admission, old, runner, **kwargs):
    return controller.promote_transfer_regression(
        governance=governance, admission_id=admission.admission_id,
        expected_record_sha256=admission.record_sha256, old_memory=old, tasks=manifest(), runner=runner,
        parent_run_id="parent", **kwargs,
    )


def test_parent_charges_completed_promotion_and_activation_replay_are_read_only(tmp_path):
    owner, governance, shadow, old, current = setup(
        tmp_path, {"max_evaluator_invocations": 19, "max_transfer_invocations": 18},
    )
    runner = Holdout()
    report, approved = promote(owner, governance, shadow, old, runner)
    assert report.promotion_eligible and approved.state == "approved"
    assert runner.calls == 18
    consumed = owner.ledger.controller_checkpoint("parent")[1]["budget_state"]["consumed"]
    assert consumed["evaluator_invocations"] == 19
    assert consumed["transfer_invocations"] == 18
    before = owner.ledger.controller_checkpoint("parent")
    replay, same = promote(owner, governance, approved, old, runner)
    assert same == approved and replay is report
    assert owner.ledger.controller_checkpoint("parent") == before

    reconstructed = RSILearningController(
        DeterministicMockSolver(), ledger=RSILedger(owner.ledger.database), memory_store=RSIMemoryStore(current),
    )
    cold_runner = Holdout()
    recovered_report, active = promote(reconstructed, governance, approved, old, cold_runner, activate=True)
    assert recovered_report is None and active.state == "active"
    assert cold_runner.calls == 0
    assert owner.ledger.controller_checkpoint("parent") == before
    promote(reconstructed, governance, active, old, cold_runner, activate=True)
    assert owner.ledger.controller_checkpoint("parent") == before
    assert cold_runner.calls == 0


def test_parent_preconsumption_limits_holdout_even_with_more_child_budget(tmp_path):
    owner, governance, shadow, old, _current = setup(
        tmp_path, {"max_evaluator_invocations": 18, "max_transfer_invocations": 100},
    )
    runner = Holdout()
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        promote(owner, governance, shadow, old, runner,
                budget={"max_evaluator_invocations": 100, "max_transfer_invocations": 100})
    assert governance.get(shadow.admission_id) == shadow
    assert runner.calls == 17
    before = owner.ledger.controller_checkpoint("parent")
    consumed = before[1]["budget_state"]["consumed"]
    assert consumed["evaluator_invocations"] == 18 and consumed["transfer_invocations"] == 17
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        promote(owner, governance, shadow, old, runner,
                budget={"max_evaluator_invocations": 100, "max_transfer_invocations": 100})
    assert owner.ledger.controller_checkpoint("parent") == before
    assert runner.calls == 17


def test_approved_parent_identity_cannot_be_removed_or_changed(tmp_path):
    owner, governance, shadow, old, _current = setup(tmp_path)
    runner = Holdout()
    _report, approved = promote(owner, governance, shadow, old, runner)
    before = owner.ledger.controller_checkpoint("parent")
    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        owner.promote_transfer_regression(
            governance=governance, admission_id=approved.admission_id,
            expected_record_sha256=approved.record_sha256, old_memory=old, tasks=manifest(), runner=runner,
            activate=True,
        )
    changed = tuple(replace(task, target_id=task.target_id + "-changed") for task in manifest())
    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        owner.promote_transfer_regression(
            governance=governance, admission_id=approved.admission_id,
            expected_record_sha256=approved.record_sha256, old_memory=old, tasks=changed, runner=runner,
            parent_run_id="parent", activate=True,
        )
    assert governance.get(shadow.admission_id) == approved
    assert owner.ledger.controller_checkpoint("parent") == before
    assert runner.calls == 18


def test_parent_identity_wrong_run_does_not_dispatch_or_charge(tmp_path):
    owner, governance, shadow, old, _current = setup(tmp_path)
    runner = Holdout()
    before = owner.ledger.controller_checkpoint("parent")
    with pytest.raises(RSILearningError, match="parent_budget_missing"):
        owner.promote_transfer_regression(
            governance=governance, admission_id=shadow.admission_id,
            expected_record_sha256=shadow.record_sha256, old_memory=old, tasks=manifest(), runner=runner,
            parent_run_id="missing-parent",
        )
    assert governance.get(shadow.admission_id) == shadow
    assert owner.ledger.controller_checkpoint("parent") == before
    assert runner.calls == 0


def test_parent_requires_a_durable_controller_ledger(tmp_path):
    old, current = snapshot("old", "old-item"), snapshot("current", "current-item")
    governance, shadow = shadow_admission(tmp_path, old, current)
    owner = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    runner = Holdout()
    with pytest.raises(RSILearningError, match="parent_budget_requires_ledger"):
        promote(owner, governance, shadow, old, runner)
    assert governance.get(shadow.admission_id) == shadow
    assert runner.calls == 0


def test_initial_generation_and_named_initial_validation_have_distinct_scopes():
    request = GenerationRegressionRequest(
        "generation", EMPTY_MEMORY_SNAPSHOT, snapshot("candidate", "candidate-item"),
        RegressionPolicy(), {}, digest("generation-intent"),
    )
    named_initial = replace(request, validation_id="initial")
    assert GenerationCampaignRunner.admission_id(request) != GenerationCampaignRunner.admission_id(named_initial)
    assert GenerationCampaignRunner.admission_id(request) == GenerationCampaignRunner.admission_id(request)


@pytest.mark.parametrize("replacement", ["gateway", "runner", "manifest"])
def test_created_generation_helper_observes_live_controller_replacement(tmp_path, replacement: str):
    owner = generation_controller(tmp_path)
    generation_run(owner)
    helper = owner.generation_campaign_runner("learning")
    frozen_runner = owner.generation_regression_runner
    calls = frozen_runner.calls
    before = owner.ledger.controller_checkpoint("learning")
    if replacement == "gateway":
        owner.gateway = DeterministicMockSolver()
    elif replacement == "runner":
        owner.generation_regression_runner = Holdout()
    else:
        owner.generation_regression_tasks = tuple(reversed(owner.generation_regression_tasks))
    request = GenerationRegressionRequest(
        "unused-generation", EMPTY_MEMORY_SNAPSHOT, snapshot("candidate", "candidate-item"),
        owner.memory_admission_gate.policy.regression, {}, digest("unused-intent"),
    )
    with pytest.raises(RSILearningError, match="generation_campaign_fingerprint_drift"):
        helper(request)
    assert frozen_runner.calls == calls
    assert owner.ledger.controller_checkpoint("learning") == before
    assert helper.campaign.inspect(GenerationCampaignRunner.admission_id(request)) is None
