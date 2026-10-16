"""Three distinct inert children use real publication, memory and RSI settlement.

Only native process observations and the lowest candidate/evaluator process seams
are synthetic. No subprocess, model, external evaluator or campaign is allowed.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_child_execution_flow import _InertNativeObservation, _successful_fixture
from test_rsi_multi_episode_policy import _controller

from lunar_evolution import (
    RSILearningController,
    candidate_evaluation,
    candidate_execution_runner,
    native_trusted_output,
    native_trusted_scheduler,
)
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.evolution import CandidateArchive
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.producer_bundle_receipts import build_producer_bundle_evaluation_receipt
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT_SHA256
from lunar_evolution.rsi_producer_gateway import (
    PythonProducerRSIExecutionConfig,
    PythonProducerRSISolverGateway,
)
from lunar_evolution.rsi_producer_staging_capsule import materialize_ready
from lunar_evolution.rsi_python_scheduler_inputs import PythonRSISchedulerInputContext


class _ReceiptThresholdJudge:
    """Use the native evaluator's bound report through the existing judge API."""

    def __init__(self, workspace, ledger):
        self.workspace, self.ledger = workspace, ledger

    def rsi_fingerprint_config(self):
        return {
            "fixture": "native-evaluation-receipt-threshold-v1",
            "workspace": str(self.workspace), "ledger": str(self.ledger.database), "threshold": 1,
            "receipt_reader": component_fingerprint(build_producer_bundle_evaluation_receipt),
        }

    def quality(self, execution):
        request, result = execution.request, execution.result
        _head, state = self.ledger.controller_checkpoint("run-1")
        entry = state["producer_episode_staging"][request.episode_id]
        plan = materialize_ready(entry["ready"], allow_capsule=True,
                                 expected_workspace=self.workspace,
                                 expected_journal_id=entry["identity"]["journal_id"])["plan"]
        assert plan["request"] == request.to_dict()
        batch = self.workspace / "evolution/producer-batches" / plan["journal_id"]
        journal = parse_producer_bundle_publication_journal(batch / "journal.published.json")
        assert (journal.run_id, journal.task_id) == ("run-1", request.episode_id)
        candidate_id = dict(result.solver_provenance)["candidate_id"]
        slots = [slot for slot in journal.candidates if slot.candidate_id == candidate_id]
        assert len(slots) == 1 and slots[0].status == "admitted"
        archive = CandidateArchive(self.workspace, requested_strategy="population", read_only=True)
        records = archive.records()
        archive.validate_candidate_integrity(require_all=True, records=records)
        candidates = [candidate for candidate in records if candidate.candidate_id == candidate_id]
        assert len(candidates) == 1 and candidates[0].source_sha256 == result.candidate_source_sha256
        receipt = build_producer_bundle_evaluation_receipt(self.workspace, candidates[0])
        receipt = replace(receipt, python_handoff_sha256=journal.python_handoff_sha256, receipt_sha256=None)
        assert receipt.digest() == slots[0].evaluation_receipt_sha256 == result.official_evaluation_receipt_sha256
        assert receipt.report["validity"] == 1
        return receipt.report["combined_score"]

    def __call__(self, execution):
        return (execution.passed and self.quality(execution) >= 1,
                "native evaluation receipt threshold")


def _judged_controller(value):
    original, supplier = _controller(value, publication=True)
    controller = RSILearningController(
        value.gateway, ledger=value.ledger, producer_workspace=value.root,
        producer_sidecar=value.sidecar, producer_stager=original.producer_stager,
        producer_child_execution=True, producer_multi_episode_publication=True,
        target_judge=_ReceiptThresholdJudge(value.root, value.ledger),
    )
    return controller, supplier


class _ThreeEpisodeObservation(_InertNativeObservation):
    def rsi_fingerprint_config(self):
        return {
            "fixture": "three-episode-inert-observation-v1",
            "scores": {"run-1-target-0": 0, "run-1-practice-0-0": 9, "run-1-target-1": 9},
            "observation_dependency": component_fingerprint(_InertNativeObservation, config={}),
        }

    def source_bytes(self, intent):
        return ("# Inert source for " + intent.task_id + "; never executed.\n").encode()


@pytest.fixture(autouse=True)
def _no_subprocess(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("multi-episode acceptance must never launch a subprocess")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


def _fixture(tmp_path, monkeypatch):
    value, _old_controller, _old_supplier, _old_observation = _successful_fixture(tmp_path, monkeypatch)
    observation = _ThreeEpisodeObservation()
    value.native = replace(value.native, python_handoff_after_execution=observation)
    value.context = PythonRSISchedulerInputContext(value.native, value.sidecar, value.proof)
    value.config = PythonProducerRSIExecutionConfig(value.request.solver_id, value.ledger, value.context)
    value.gateway = PythonProducerRSISolverGateway(value.config)
    controller, supplier = _judged_controller(value)
    observation.controller = controller
    monkeypatch.setattr(native_trusted_scheduler, "run_native_trusted_attempt", observation.attempt)
    monkeypatch.setattr(native_trusted_scheduler, "persist_native_trusted_execution_receipt", observation.persist_receipt)
    monkeypatch.setattr(native_trusted_scheduler, "recover_native_trusted_execution_receipt", observation.recover_receipt)
    monkeypatch.setattr(native_trusted_output, "recover_native_trusted_attempt", observation.terminal)
    monkeypatch.setattr(native_trusted_output, "recover_native_trusted_execution_receipt", observation.recover_receipt)

    def process(command, *, cwd, process_observer=None, process_released=None,
                process_exit_observed=None, continuation_guard=None, **_kwargs):
        if continuation_guard is not None:
            continuation_guard()
        if process_observer is not None:
            process_observer(4242, 4242)
        _head, state = value.ledger.controller_checkpoint(value.binding.run_id)
        episode_id = state["current_episode_id"]
        score = {"run-1-target-0": 0, "run-1-practice-0-0": 9, "run-1-target-1": 9}[episode_id]
        root = Path(cwd)
        if "evaluator.py" in command:
            assert json.loads((root / "output/result.json").read_bytes()) == {"value": score}
            stdout = canonical_json({
                "schema_version": "1", "evaluator_id": "bundle-population-fixture",
                "validity": 1, "quality": float(score), "combined_score": float(score),
                "detailed_scores": {}, "error_info": [],
            })
        else:
            (root / "output").mkdir(exist_ok=True)
            (root / "output/result.json").write_bytes(canonical_json({"value": score}))
            stdout = b""
        if process_exit_observed is not None:
            process_exit_observed(0)
        if process_released is not None:
            process_released(4242, 4242)
        if continuation_guard is not None:
            continuation_guard()
        return stdout, b"", "succeeded", 0, None

    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", process)
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", process)
    return value, controller, supplier, observation


def test_three_children_publish_promote_memory_and_resume_without_dispatch(tmp_path, monkeypatch):
    value, controller, supplier, observation = _fixture(tmp_path, monkeypatch)
    root_gateway, root_sidecar = controller.gateway, controller.producer_sidecar
    result = controller.run_drs(
        run_id=value.binding.run_id, contract_sha256=value.request.contract_sha256,
        evaluator_sha256=value.request.evaluator_sha256,
        environment_sha256=value.request.environment_sha256,
        solver_id=value.request.solver_id, max_practice_rounds=1, max_target_attempts=2,
        budget=dict(value.request.budget),
    )
    assert result.status == "completed"
    assert all(item.result.solver_score is None for item in result.target_attempts)
    assert [controller.target_judge.quality(item) for item in result.target_attempts] == [0.0, 9.0]
    assert len(result.practice_episodes) == 1 and result.practice_episodes[0].passed
    assert result.memory_snapshot.digest() != EMPTY_MEMORY_SNAPSHOT_SHA256
    executions = [result.target_attempts[0], result.practice_episodes[0], result.target_attempts[1]]
    assert [controller.target_judge.quality(item) for item in executions] == [0.0, 9.0, 9.0]
    assert [item.request.memory_snapshot_sha256 for item in executions] == [
        EMPTY_MEMORY_SNAPSHOT_SHA256, EMPTY_MEMORY_SNAPSHOT_SHA256, result.memory_snapshot.digest(),
    ]
    assert [item.episode.episode_id for item in executions] == [
        "run-1-target-0", "run-1-practice-0-0", "run-1-target-1",
    ]
    assert controller.gateway is root_gateway and controller.producer_sidecar is root_sidecar
    assert controller._producer_publication_dispatch is None
    assert controller._python_admission_flow_local.active is None
    assert len(observation.attempts) == len(observation.handoffs) == len(supplier.observations) == 3
    assert len({intent.journal_id for intent in observation.attempts}) == 3
    assert len({intent.launch_id for intent in observation.attempts}) == 3
    with sqlite3.connect(value.ledger.database) as connection:
        claims = connection.execute("SELECT episode_id FROM rsi_native_episode_claims").fetchall()
    assert set(claims) == {(item.episode.episode_id,) for item in executions}
    head, state = value.ledger.controller_checkpoint(value.binding.run_id)
    for item in executions:
        entry = state["producer_episode_staging"][item.request.episode_id]
        native_plan = materialize_ready(entry["ready"], allow_capsule=True,
                                        expected_workspace=value.root,
                                        expected_journal_id=entry["identity"]["journal_id"])["plan"]
        claim = value.ledger.inspect_native_episode_claim(item.request, plan_sha256=native_plan["plan_sha256"])
        assert claim.status == "completed"
    assert state["budget_state"]["consumed"]["solver_invocations"] == 3
    assert state["budget_state"]["consumed"]["target_attempts"] == 2
    assert state["budget_state"]["consumed"]["practice_episodes"] == 1
    assert len(canonical_json(state)) <= 112 * 1024
    native_state = json.loads((value.root / "evolution/state.json").read_bytes())
    events = native_state["producer_admissions"]["events"]
    assert len(events) == 3 and all(event["after_iteration"] == 0 for event in events)
    candidates = [candidate for event in events for candidate in event["candidate_ids"]]
    assert len(candidates) == len(set(candidates)) == 3
    histories = value.ledger.controller_checkpoint_history(value.binding.run_id)
    assert all(len(canonical_json(snapshot)) <= 112 * 1024 for _digest, snapshot in histories)
    assert all(set(entry["ready"]) == {"protocol", "workspace", "journal_id",
                                      "workspace_identity", "file_pin"}
               for entry in state["producer_episode_staging"].values())
    inventory = _inventory(value.root)
    restarted, _supplier = _judged_controller(value)
    replayed = restarted.resume(value.binding.run_id)
    assert replayed == result
    assert value.ledger.controller_checkpoint(value.binding.run_id) == (head, state)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == histories
    assert _inventory(value.root) == inventory
    assert len(observation.attempts) == len(observation.handoffs) == len(supplier.observations) == 3
