"""Opt-in local regression gates solver dispatch using a durable request identity."""

from __future__ import annotations

import pytest

from lunar_evolution.rsi_callbacks import DurableCallbackJournal
from lunar_evolution.rsi_controller import CurriculumDecision, RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver
from lunar_evolution.rsi_generation_campaign import GenerationCampaignRunner
from lunar_evolution.rsi_governance_coordinator import (
    GenerationGovernanceError,
    GenerationGovernancePolicy,
    RSIGovernanceCoordinator,
)
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, RSILearningError
from lunar_evolution.rsi_memory_governance import MemoryGovernanceStore
from lunar_evolution.rsi_regression_campaign import DurableRegressionCampaign
from lunar_evolution.rsi_store import RSILedger
from lunar_evolution.rsi_transfer_regression import TransferObservation
from tests.test_rsi_controller_generation import Gateway
from tests.test_rsi_governance_coordinator import PINS, TASKS, FixtureRegression, digest


class Trials:
    def __init__(self, *, reject_after=None, interrupt_at=None):
        self.reject_after, self.interrupt_at = reject_after, interrupt_at
        self.calls = 0
        self.interrupt_enabled = True

    def rsi_fingerprint_config(self):
        return {"fixture": "dispatch-revalidation-v1", "reject_after": self.reject_after,
                "interrupt_at": self.interrupt_at}

    def __call__(self, task, memory, repetition):
        self.calls += 1
        if self.interrupt_enabled and self.calls == self.interrupt_at:
            raise RuntimeError("uncertain revalidation trial")
        rejected = self.reject_after is not None and self.calls > self.reject_after and memory.items
        return TransferObservation(not rejected, 0.3 + 0.2 * len(memory.items),
                                   accessed_task_ids=(task.task_id,),
                                   memory_ids_used=tuple(item.memory_id for item in memory.items))


def judge(execution):
    return execution.episode.wave >= 1, "practice once"


def controller(tmp_path, runner=None, *, enabled=True):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gate = RSIGovernanceCoordinator(MemoryGovernanceStore(tmp_path / "governance.sqlite3"), ledger=ledger,
                                     scope="fixture", compatibility=PINS, policy=GenerationGovernancePolicy())
    return RSILearningController(Gateway(), ledger=ledger, target_judge=judge, memory_admission_gate=gate,
                                 generation_regression_tasks=TASKS, generation_regression_runner=runner or Trials(),
                                 generation_revalidate_before_dispatch=enabled)


def run(owner, budget=None):
    return owner.run_drs(run_id="learning", contract_sha256=PINS["contract"], evaluator_sha256=PINS["evaluator"],
                          environment_sha256=PINS["environment"], solver_id="fixture", max_practice_rounds=1,
                          max_target_attempts=2, budget=budget)


def generation(owner):
    entry = next(iter(owner.ledger.controller_checkpoint("learning")[1]["generations"].values()))
    return entry["generation_id"], owner.memory_admission_gate.inspect(entry["generation_id"])[1]


def test_revalidation_precedes_new_intent_and_repeated_before_run_does_not_charge(tmp_path):
    owner = controller(tmp_path)
    result = run(owner)
    assert result.status == "completed" and len(result.memory_snapshot.items) == 1
    assert len(owner.gateway.requests) == 3 and owner.generation_regression_runner.calls == 36
    generation_id, state = generation(owner)
    request = owner.gateway.requests[-1]
    assert set(state["validations"]) == {"dispatch:" + request.digest()}
    assert state["validations"]["dispatch:" + request.digest()]["status"] == "completed"
    before = owner.ledger.controller_checkpoint("learning")
    owner._check_memory_admission(request, parent_run_id="learning")
    owner._check_memory_admission(request, parent_run_id="learning")
    assert owner.ledger.controller_checkpoint("learning") == before
    assert owner.generation_regression_runner.calls == 36
    assert before[1]["budget_state"]["consumed"]["transfer_invocations"] == 36
    reopened = controller(tmp_path)
    assert reopened.resume("learning").memory_snapshot == result.memory_snapshot
    assert not reopened.gateway.requests and reopened.generation_regression_runner.calls == 0
    assert owner.memory_admission_gate.inspect(generation_id)[1]["phase"] == "active"


def test_regression_failure_quarantines_memory_without_dispatching_changed_intent(tmp_path):
    owner = controller(tmp_path, Trials(reject_after=18))
    with pytest.raises(RSILearningError, match="generation_revalidation_rejected"):
        run(owner)
    assert len(owner.gateway.requests) == 2 and owner.generation_regression_runner.calls == 36
    generation_id, state = generation(owner)
    assert state["phase"] == "quarantined"
    assert "learning-target-1" not in owner.ledger.controller_checkpoint("learning")[1]["intents"]
    assert owner.snapshot.items
    with pytest.raises(GenerationGovernanceError, match="inactive"):
        owner.memory_admission_gate.validate(owner.snapshot)
    resumed = controller(tmp_path, Trials(reject_after=18))
    with pytest.raises(RSILearningError, match="generation_revalidation_rejected"):
        resumed.resume("learning")
    assert not resumed.gateway.requests and resumed.generation_regression_runner.calls == 0
    assert resumed.memory_admission_gate.inspect(generation_id)[1]["phase"] == "quarantined"


def test_unknown_revalidation_has_stable_required_error_and_never_retries_on_resume(tmp_path):
    owner = controller(tmp_path, Trials(interrupt_at=19))
    with pytest.raises(RSILearningError, match="generation_revalidation_reconcile_required"):
        run(owner)
    before = owner.ledger.controller_checkpoint("learning")
    assert len(owner.gateway.requests) == 2 and owner.generation_regression_runner.calls == 19
    assert "learning-target-1" not in before[1]["intents"]
    _generation_id, state = generation(owner)
    assert state["phase"] == "revalidating"
    resumed = controller(tmp_path, Trials(interrupt_at=19))
    with pytest.raises(RSILearningError, match="generation_revalidation_reconcile_required"):
        resumed.resume("learning")
    assert not resumed.gateway.requests and resumed.generation_regression_runner.calls == 0
    assert owner.ledger.controller_checkpoint("learning") == before


def test_explicit_child_and_outer_reconciliation_allows_exact_original_dispatch(tmp_path):
    owner = controller(tmp_path, Trials(interrupt_at=19))
    with pytest.raises(RSILearningError, match="generation_revalidation_reconcile_required"):
        run(owner)
    generation_id, state = generation(owner)
    validation_id = state["pending_validation"]
    gate = owner.memory_admission_gate
    request = gate._request(state, validation_id)
    child = DurableRegressionCampaign(owner.ledger)
    admission_id = GenerationCampaignRunner.admission_id(request)
    trial_id = "trial:no_memory:0:0"
    pin, callback = child.callbacks.inspect(child.scope(admission_id), trial_id)
    result = TransferObservation(True, 0.3, accessed_task_ids=(TASKS[0].task_id,)).to_dict()
    evidence = {"source": "trusted-local-fixture", "binding_sha256": callback["binding_sha256"],
                "result_sha256": DurableCallbackJournal.digest(result), "receipt_sha256": digest("observed")}
    child.reconcile_trial(admission_id, trial_id, expected_checkpoint_sha256=pin, result=result, evidence=evidence)
    owner.generation_regression_runner.interrupt_enabled = False
    report = owner.generation_campaign_runner("learning")(request)
    outer_pin, outer = gate.callbacks.inspect(gate._namespace(generation_id), "revalidation:" + validation_id)
    wire = gate.serialize_report(report)
    evidence = {"source": "trusted-local-fixture", "binding_sha256": outer["binding_sha256"],
                "result_sha256": DurableCallbackJournal.digest(wire), "receipt_sha256": report.report_sha256}
    gate.reconcile_holdout(generation_id, validation_id=validation_id, expected_checkpoint_sha256=outer_pin,
                            report=report, evidence=evidence)
    resumed = controller(tmp_path, Trials(interrupt_at=19))
    completed = resumed.resume("learning")
    assert completed.status == "completed" and completed.memory_snapshot == owner.snapshot
    assert len(resumed.gateway.requests) == 1 and resumed.gateway.requests[0].episode_id == "learning-target-1"
    assert resumed.generation_regression_runner.calls == 0
    consumed = resumed.ledger.controller_checkpoint("learning")[1]["budget_state"]["consumed"]
    assert consumed["transfer_invocations"] == 36 and consumed["unknown_retries"] == 2


def test_shared_budget_stop_during_revalidation_prevents_next_solver(tmp_path):
    owner = controller(tmp_path)
    result = run(owner, {"max_evaluator_invocations": 21})
    assert result.status == "budget_exhausted"
    assert len(owner.gateway.requests) == 2 and owner.generation_regression_runner.calls == 19
    assert "learning-target-1" not in owner.ledger.controller_checkpoint("learning")[1]["intents"]
    assert owner.ledger.controller_checkpoint("learning")[1]["budget_state"]["consumed"]["evaluator_invocations"] == 21


def test_completed_revalidation_replays_after_intent_publication_crash(tmp_path, monkeypatch):
    owner = controller(tmp_path)
    publish = owner.ledger.write_controller_checkpoint

    def interrupt(scope, state, **kwargs):
        result = publish(scope, state, **kwargs)
        if scope == "learning" and "learning-target-1" in state.get("intents", {}):
            raise KeyboardInterrupt("after target intent publication")
        return result

    monkeypatch.setattr(owner.ledger, "write_controller_checkpoint", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run(owner)
    assert owner.generation_regression_runner.calls == 36 and len(owner.gateway.requests) == 2
    monkeypatch.setattr(owner.ledger, "write_controller_checkpoint", publish)
    resumed = controller(tmp_path)
    assert resumed.resume("learning").status == "completed"
    assert len(resumed.gateway.requests) == 1 and resumed.generation_regression_runner.calls == 0


def test_nonempty_brs_prevalidates_in_owner_thread_and_workers_replay_read_only(tmp_path):
    owner = controller(tmp_path)
    run(owner)
    before_calls = owner.generation_regression_runner.calls
    before_requests = len(owner.gateway.requests)
    decision = CurriculumDecision("fixture", "gap", "practice", "strategy", "pass", "boundary", ("fixture",))
    result = owner.run_brs(run_id="broad", contract_sha256=PINS["contract"], evaluator_sha256=PINS["evaluator"],
                            environment_sha256=PINS["environment"], solver_id="fixture",
                            practices=[decision, decision], max_workers=2)
    assert result.status == "completed" and len(result.memory_snapshot.items) == 3
    assert owner.generation_regression_runner.calls - before_calls == 72
    assert len(owner.gateway.requests) - before_requests == 2
    assert owner.ledger.controller_checkpoint("broad")[1]["budget_state"]["consumed"]["transfer_invocations"] == 72


@pytest.mark.parametrize("flag", [None, 1, "true"])
def test_flag_requires_boolean_and_generation_configuration(flag):
    with pytest.raises(RSILearningError, match="generation_controller_config_invalid"):
        RSILearningController(DeterministicMockSolver(), generation_revalidate_before_dispatch=flag)


def test_flag_requires_same_ledger_coordinator_and_frozen_tasks():
    with pytest.raises(RSILearningError, match="generation_controller_config_invalid"):
        RSILearningController(DeterministicMockSolver(), generation_revalidate_before_dispatch=True)


def test_flag_drift_is_rejected_before_resume_dispatch(tmp_path):
    owner = controller(tmp_path, Trials(interrupt_at=19))
    with pytest.raises(RSILearningError):
        run(owner)
    resumed = controller(tmp_path, Trials(interrupt_at=19), enabled=False)
    with pytest.raises(RSILearningError, match="fingerprint_drift"):
        resumed.resume("learning")
    assert not resumed.gateway.requests and resumed.generation_regression_runner.calls == 0


def test_default_preserves_existing_admission_only_behavior_and_empty_skip(tmp_path):
    owner = controller(tmp_path, enabled=False)
    result = run(owner)
    assert result.status == "completed" and owner.generation_regression_runner.calls == 18
    assert generation(owner)[1]["validations"] == {}
    assert owner.gateway.requests[0].memory_snapshot_sha256 == EMPTY_MEMORY_SNAPSHOT.digest()


def test_live_flag_disabling_cannot_bypass_before_run_identity(tmp_path):
    owner = controller(tmp_path)
    run(owner)
    request = owner.gateway.requests[-1]
    owner.generation_revalidate_before_dispatch = False
    before = owner.ledger.controller_checkpoint("learning")
    with pytest.raises(RSILearningError, match="fingerprint_drift"):
        owner._check_memory_admission(request, parent_run_id="learning")
    assert owner.ledger.controller_checkpoint("learning") == before
    assert owner.generation_regression_runner.calls == 36


def test_readonly_helper_projection_matches_instance_without_new_charges(tmp_path):
    owner = controller(tmp_path)
    run(owner)
    before = owner.ledger.controller_checkpoint("learning")
    config = owner._generation_campaign_config_readonly("learning")
    assert component_fingerprint(GenerationCampaignRunner, config=config) == component_fingerprint(
        owner.generation_campaign_runner("learning"),
    )
    assert owner.ledger.controller_checkpoint("learning") == before


def test_foreign_completed_dispatch_validation_cannot_bypass_bound_controller_helper(tmp_path, monkeypatch):
    owner = controller(tmp_path)
    check = owner._check_memory_admission
    foreign = FixtureRegression()

    def inject(request, *, parent_run_id=None):
        if owner.snapshot.items and not foreign.calls:
            gate = owner.memory_admission_gate
            generation_id = gate._snapshot_generation(owner.snapshot)
            gate.revalidate_generation(generation_id, "dispatch:" + request.digest(), foreign)
        return check(request, parent_run_id=parent_run_id)

    monkeypatch.setattr(owner, "_check_memory_admission", inject)
    with pytest.raises(RSILearningError, match="generation_controller_admission_drift"):
        run(owner)
    assert foreign.calls == 1
    assert owner.generation_regression_runner.calls == 18
    assert len(owner.gateway.requests) == 2
    assert "learning-target-1" not in owner.ledger.controller_checkpoint("learning")[1]["intents"]
