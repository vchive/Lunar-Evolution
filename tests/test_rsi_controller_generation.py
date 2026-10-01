"""Automatic local holdout admits whole generations before the next solver dispatch."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from lunar_evolution.rsi_callbacks import DurableCallbackJournal
from lunar_evolution.rsi_controller import CurriculumDecision, RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver
from lunar_evolution.rsi_generation_campaign import GenerationCampaignRunner
from lunar_evolution.rsi_governance_coordinator import (
    GenerationGovernanceError,
    GenerationGovernancePolicy,
    GenerationRegressionRequest,
    RSIGovernanceCoordinator,
)
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, MemorySnapshot, RSILearningError
from lunar_evolution.rsi_memory_governance import MemoryGovernanceStore
from lunar_evolution.rsi_regression_campaign import DurableRegressionCampaign
from lunar_evolution.rsi_store import RSILedger
from lunar_evolution.rsi_transfer_regression import RegressionPolicy, TransferObservation
from tests.test_rsi_governance_coordinator import PINS, TASKS, digest


class Trials:
    def __init__(self, *, reject=False, interrupt=False):
        self.reject, self.interrupt = reject, interrupt
        self.calls = 0

    def rsi_fingerprint_config(self):
        return {"fixture": "generation-trials-v1", "reject": self.reject}

    def __call__(self, task, memory, repetition):
        self.calls += 1
        if self.interrupt:
            raise RuntimeError("uncertain trial")
        return TransferObservation(not (self.reject and memory.items), 0.3 + 0.2 * len(memory.items),
                                   accessed_task_ids=(task.task_id,),
                                   memory_ids_used=tuple(item.memory_id for item in memory.items))


class Gateway(DeterministicMockSolver):
    def __init__(self):
        super().__init__()
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return super().run(request)


def judge(execution):
    return execution.episode.wave >= 2, "practice twice"


def controller(tmp_path: Path, trials=None):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    coordinator = RSIGovernanceCoordinator(
        MemoryGovernanceStore(tmp_path / "governance.sqlite3"), ledger=ledger, scope="fixture",
        compatibility=PINS, policy=GenerationGovernancePolicy(RegressionPolicy(repetitions=2)),
    )
    return RSILearningController(
        Gateway(), ledger=ledger, memory_admission_gate=coordinator,
        generation_regression_tasks=TASKS, generation_regression_runner=trials or Trials(), target_judge=judge,
    )


def run(owner, budget=None):
    return owner.run_drs(run_id="learning", contract_sha256=PINS["contract"], evaluator_sha256=PINS["evaluator"],
                         environment_sha256=PINS["environment"], solver_id="fixture", max_practice_rounds=2,
                         max_target_attempts=3, budget=budget)


def test_two_generations_and_shared_budget_with_read_only_terminal_resume(tmp_path):
    owner = controller(tmp_path)
    result = run(owner)
    assert result.status == "completed" and len(result.memory_snapshot.items) == 2
    assert owner.generation_regression_runner.calls == 36
    assert owner.gateway.requests[-1].memory_snapshot_sha256 == result.memory_snapshot.digest()
    state = owner.ledger.controller_checkpoint("learning")[1]
    assert {entry["status"] for entry in state["generations"].values()} == {"active"}
    assert state["budget_state"]["consumed"]["evaluator_invocations"] == 41
    assert state["budget_state"]["consumed"]["transfer_invocations"] == 36
    owner.memory_admission_gate.validate(result.memory_snapshot)
    reopened = controller(tmp_path)
    assert reopened.resume("learning").memory_snapshot == result.memory_snapshot
    assert not reopened.gateway.requests and reopened.generation_regression_runner.calls == 0


def test_rejected_generation_keeps_parent_for_retry(tmp_path):
    owner = controller(tmp_path, Trials(reject=True))
    result = run(owner)
    assert result.status == "completed" and result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT
    assert all(request.memory_snapshot_sha256 == EMPTY_MEMORY_SNAPSHOT.digest() for request in owner.gateway.requests)
    assert {entry["status"] for entry in owner.ledger.controller_checkpoint("learning")[1]["generations"].values()} == {"rejected"}


def test_unknown_blocks_retry_and_no_trial_repeats_on_resume(tmp_path):
    owner = controller(tmp_path, Trials(interrupt=True))
    with pytest.raises(RSILearningError, match="generation_reconcile_required"):
        run(owner)
    before = owner.ledger.controller_checkpoint("learning")
    assert len(owner.gateway.requests) == 2 and owner.generation_regression_runner.calls == 1
    assert MemorySnapshot.from_dict(before[1]["memory_snapshot"]) == EMPTY_MEMORY_SNAPSHOT
    resumed = controller(tmp_path)
    with pytest.raises(RSILearningError, match="generation_reconcile_required"):
        resumed.resume("learning")
    assert resumed.generation_regression_runner.calls == 0 and not resumed.gateway.requests
    assert owner.ledger.controller_checkpoint("learning") == before


def test_unknown_explicit_child_and_outer_reconciliation_resumes_exact_generation(tmp_path):
    owner = controller(tmp_path, Trials(interrupt=True))
    with pytest.raises(RSILearningError, match="generation_reconcile_required"):
        run(owner)
    entry = next(iter(owner.ledger.controller_checkpoint("learning")[1]["generations"].values()))
    coordinator = owner.memory_admission_gate
    _head, state = coordinator.inspect(entry["generation_id"])
    request = GenerationRegressionRequest(
        entry["generation_id"], MemorySnapshot.from_dict(entry["parent_memory"]),
        MemorySnapshot.from_dict(entry["candidate_memory"]), coordinator.policy.regression,
        state["intent"]["admissions"], state["intent_sha256"], manifest=TASKS,
    )
    child = DurableRegressionCampaign(owner.ledger)
    admission = GenerationCampaignRunner.admission_id(request)
    callback_id = "trial:no_memory:0:0"
    pin, callback = child.callbacks.inspect(child.scope(admission), callback_id)
    result = TransferObservation(True, 0.3, accessed_task_ids=(TASKS[0].task_id,)).to_dict()
    evidence = {"source": "trusted-local-fixture", "binding_sha256": callback["binding_sha256"],
                "result_sha256": DurableCallbackJournal.digest(result), "receipt_sha256": digest("observed")}
    child.reconcile_trial(admission, callback_id, expected_checkpoint_sha256=pin, result=result, evidence=evidence)
    owner.generation_regression_runner.interrupt = False
    report = owner.generation_campaign_runner("learning")(request)
    outer_pin, outer = coordinator.callbacks.inspect(coordinator._namespace(request.generation_id), "holdout")
    wire = coordinator.serialize_report(report)
    outer_evidence = {"source": "trusted-local-fixture", "binding_sha256": outer["binding_sha256"],
                      "result_sha256": DurableCallbackJournal.digest(wire), "receipt_sha256": report.report_sha256}
    assert coordinator.reconcile_holdout(request.generation_id, expected_checkpoint_sha256=outer_pin,
                                        report=report, evidence=outer_evidence).status == "active"
    resumed = controller(tmp_path)
    completed = resumed.resume("learning")
    assert completed.status == "completed" and len(completed.memory_snapshot.items) == 2
    assert resumed.generation_regression_runner.calls == 18
    assert len(resumed.gateway.requests) == 3
    consumed = resumed.ledger.controller_checkpoint("learning")[1]["budget_state"]["consumed"]
    assert consumed["transfer_invocations"] == 36 and consumed["unknown_retries"] == 2


def test_shared_budget_exhaustion_does_not_admit_candidate(tmp_path):
    owner = controller(tmp_path)
    result = run(owner, {"max_evaluator_invocations": 5})
    assert result.status == "budget_exhausted" and not result.memory_snapshot.items
    assert len(owner.gateway.requests) == 2 and owner.generation_regression_runner.calls == 3
    state = owner.ledger.controller_checkpoint("learning")[1]
    assert state["budget_state"]["consumed"]["evaluator_invocations"] == 5
    assert {entry["status"] for entry in state["generations"].values()} == {"pending"}


@pytest.mark.parametrize("phase", ["candidate", "active"])
def test_publication_crash_resumes_without_duplicate_trials(tmp_path, monkeypatch, phase):
    owner = controller(tmp_path)
    original = owner.ledger.write_controller_checkpoint

    def interrupt(namespace, state, **kwargs):
        if (namespace == "learning" and state.get("generations")
                and next(iter(state["generations"].values()))["status"] == ("pending" if phase == "candidate" else "active")):
            raise RuntimeError("publication crash")
        return original(namespace, state, **kwargs)

    monkeypatch.setattr(owner.ledger, "write_controller_checkpoint", interrupt)
    with pytest.raises(RuntimeError, match="publication crash"):
        run(owner)
    calls = owner.generation_regression_runner.calls
    resumed = controller(tmp_path)
    result = resumed.resume("learning")
    assert result.status == "completed" and len(result.memory_snapshot.items) == 2
    assert calls + resumed.generation_regression_runner.calls == 36
    assert len(resumed.gateway.requests) == 3


def test_manifest_drift_on_resume_rejected_before_trial(tmp_path):
    owner = controller(tmp_path, Trials(interrupt=True))
    with pytest.raises(RSILearningError):
        run(owner)
    resumed = controller(tmp_path)
    resumed.generation_regression_tasks = tuple(reversed(TASKS))
    with pytest.raises(RSILearningError, match="fingerprint_drift"):
        resumed.resume("learning")
    assert not resumed.gateway.requests and resumed.generation_regression_runner.calls == 0


def test_brs_re_admits_generation_in_ordinal_order(tmp_path):
    owner = controller(tmp_path)
    decision = CurriculumDecision("fixture", "gap", "practice", "strategy", "pass", "boundary", ("fixture",))
    practices = [decision, decision]
    result = owner.run_brs(run_id="broad", contract_sha256=PINS["contract"], evaluator_sha256=PINS["evaluator"],
                           environment_sha256=PINS["environment"], solver_id="fixture", practices=practices)
    assert result.status == "completed" and len(result.memory_snapshot.items) == 2
    assert all(request.memory_snapshot_sha256 == EMPTY_MEMORY_SNAPSHOT.digest() for request in owner.gateway.requests)
    assert owner.generation_regression_runner.calls == 36


def test_revoked_generation_blocks_subsequent_run(tmp_path):
    owner = controller(tmp_path)
    result = run(owner)
    generation = list(owner.ledger.controller_checkpoint("learning")[1]["generations"].values())[-1]
    admission_id = next(iter(owner.memory_admission_gate.inspect(generation["generation_id"])[1]["intent"]["admissions"].values()))
    admission = owner.memory_admission_gate.governance.get(admission_id)
    owner.memory_admission_gate.governance.revoke(admission_id, expected_record_sha256=admission.record_sha256,
                                                reason="local regression failed")
    before = owner.ledger.controller_checkpoint("learning")
    replay = controller(tmp_path)
    assert replay.resume("learning").memory_snapshot == result.memory_snapshot
    assert replay.generation_regression_runner.calls == 0 and not replay.gateway.requests
    assert owner.ledger.controller_checkpoint("learning") == before
    with pytest.raises(GenerationGovernanceError, match="revoked"):
        owner.memory_admission_gate.validate(result.memory_snapshot)


@pytest.mark.parametrize("corruption", ["delete", "activate", "memory", "combined-terminal"])
def test_hash_valid_checkpoint_cannot_erase_or_bypass_pending_generation(tmp_path, corruption):
    owner = controller(tmp_path, Trials(interrupt=True))
    with pytest.raises(RSILearningError, match="generation_reconcile_required"):
        run(owner)
    pin, current = owner.ledger.controller_checkpoint("learning")
    changed = deepcopy(current)
    if corruption == "delete":
        changed["generations"].clear()
    elif corruption == "activate":
        next(iter(changed["generations"].values()))["status"] = "active"
    elif corruption == "memory":
        changed["memory_snapshot"] = next(iter(changed["generations"].values()))["candidate_memory"]
    else:
        entry = next(iter(changed["generations"].values()))
        entry["status"] = "active"
        entry["admission_checkpoint_sha256"] = owner.memory_admission_gate.inspect(entry["generation_id"])[0]
        changed.update(memory_snapshot=entry["candidate_memory"], status="completed", phase="terminal")
    with owner.ledger.controller_lock("learning"):
        owner.ledger.write_controller_checkpoint("learning", changed, expected_sha256=pin)
    resumed = controller(tmp_path)
    with pytest.raises(RSILearningError, match="generation_controller_checkpoint_corrupt"):
        resumed.resume("learning")
    assert not resumed.gateway.requests and resumed.generation_regression_runner.calls == 0


def test_controller_completed_authority_requires_actual_active_admission_heads(tmp_path, monkeypatch):
    owner = controller(tmp_path)
    coordinator = owner.memory_admission_gate

    def interrupt(*_args, **_kwargs):
        raise RuntimeError("before governance activation")

    monkeypatch.setattr(coordinator.promotion, "activate", interrupt)
    with pytest.raises(RuntimeError, match="governance activation"):
        run(owner)
    learning_pin, learning = owner.ledger.controller_checkpoint("learning")
    entry = next(iter(learning["generations"].values()))
    governance_pin, generation = coordinator.inspect(entry["generation_id"])
    assert generation["report"] is not None and generation["phase"] == "holdout"
    forged = deepcopy(generation)
    forged["phase"] = "active"
    with owner.ledger.controller_lock(coordinator._namespace(entry["generation_id"])):
        forged_pin = owner.ledger.write_controller_checkpoint(
            coordinator._namespace(entry["generation_id"]), forged, expected_sha256=governance_pin,
        )
    # Even a coherent report/phase pair cannot replace real independently recorded admissions.
    entry.update(status="active", admission_checkpoint_sha256=forged_pin)
    learning.update(status="completed", phase="terminal", memory_snapshot=entry["candidate_memory"])
    with owner.ledger.controller_lock("learning"):
        owner.ledger.write_controller_checkpoint("learning", learning, expected_sha256=learning_pin)
    reopened = controller(tmp_path)
    with pytest.raises(RSILearningError, match="generation_controller_checkpoint_corrupt"):
        reopened.resume("learning")
    assert not reopened.gateway.requests and reopened.generation_regression_runner.calls == 0
