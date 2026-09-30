"""Focused durable replay tests for the optional failure-driven curriculum ledger."""

from __future__ import annotations

from pathlib import Path

import pytest

from lunar_evolution import (
    DeterministicMockSolver,
    FailureDrivenCurriculum,
    FailureObservation,
    LocalExactVerifier,
    RSILearningController,
    RSILedger,
)

HEX = "a" * 64
PINS = {
    "contract_sha256": HEX,
    "evaluator_sha256": HEX,
    "environment_sha256": HEX,
    "solver_id": "mock",
}


class Gateway:
    def __init__(self) -> None:
        self.requests = []

    def rsi_fingerprint_config(self):
        return {"fixture": "failure-driven-resume-gateway-v1"}

    def run(self, request):
        self.requests.append(request)
        return DeterministicMockSolver().run(request)


class JudgeAfterPractice:
    def rsi_fingerprint_config(self):
        return {"fixture": "failure-driven-resume-judge-v1"}

    def __call__(self, execution):
        return execution.episode.wave >= 1, "stable_sort"


def curriculum() -> FailureDrivenCurriculum:
    return FailureDrivenCurriculum(
        seed="resume-seed", budget=4,
        failures=(FailureObservation(
            failure_code="wrong_order", capability="stable_sort",
            observable="duplicate order changed", failure_boundary="duplicates only",
            practice_task="practice-sort", transfer_task="holdout-sort",
            prerequisites=("comparison",), hard_negative_task="negative-sort",
        ),),
    )


def controller(ledger: RSILedger, gateway: Gateway, policy: FailureDrivenCurriculum):
    return RSILearningController(
        gateway, ledger=ledger, curriculum=policy,
        verifier=LocalExactVerifier(), target_judge=JudgeAfterPractice(),
    )


class CrashAfterCurriculumCallback(RuntimeError):
    pass


def test_failure_driven_ledger_is_checkpointed_and_replayed_once(tmp_path: Path):
    run_id = "failure-driven-resume"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = Gateway()
    learner = controller(ledger, gateway, curriculum())
    original_save = learner._save_flow

    def crash_after_callback(record, state):
        callback = learner.callback_checkpoint(run_id, f"curriculum:{run_id}-practice-0-0")
        # The inner save in the callback call persists the selection while its journal is still
        # started.  Crash only after the journal has completed and before decisions is published.
        if (
            callback is not None and callback[1]["status"] == "completed"
            and f"{run_id}-practice-0-0" in state["decisions"]
            and state.get("curriculum_state", {}).get("ledger")
        ):
            raise CrashAfterCurriculumCallback("decision_checkpoint_lost")
        return original_save(record, state)

    learner._save_flow = crash_after_callback
    with pytest.raises(CrashAfterCurriculumCallback, match="decision_checkpoint_lost"):
        learner.run_drs(run_id=run_id, **PINS, max_practice_rounds=1, max_target_attempts=2)

    checkpoint = ledger.controller_checkpoint(run_id)
    assert checkpoint is not None
    state = checkpoint[1]
    assert state["curriculum_state"]["protocol"] == "rsi-failure-driven-curriculum-v1"
    assert len([item for item in state["curriculum_state"]["ledger"] if item["kind"] == "selection"]) == 1
    assert f"{run_id}-practice-0-0" not in state["decisions"]

    reopened = RSILedger(ledger.database)
    restarted_policy = curriculum()
    restarted_gateway = gateway
    restarted = controller(reopened, restarted_gateway, restarted_policy)
    recovered = restarted.resume(run_id)

    assert recovered.status == "completed"
    assert [request.episode_id for request in gateway.requests] == [
        f"{run_id}-target-0", f"{run_id}-practice-0-0", f"{run_id}-target-1",
    ]
    assert len(restarted.curriculum.selections) == 1
    assert restarted.curriculum.remaining_budget == 3
    assert reopened.get_run(run_id).payload["budget_state"]["consumed"]["solver_invocations"] == 3
    assert len([item for item in reopened.controller_checkpoint(run_id)[1]["curriculum_state"]["ledger"]
                if item["kind"] == "selection"]) == 1
    terminal = controller(RSILedger(ledger.database), gateway, curriculum())
    assert terminal.resume(run_id).status == "completed"
    assert terminal.curriculum.ledger_digest() == restarted.curriculum.ledger_digest()
    assert terminal.curriculum.remaining_budget == 3
    assert len(gateway.requests) == 3


def test_initial_checkpoint_crash_restores_initial_failure_observations(tmp_path: Path, monkeypatch):
    run_id = "curriculum-initial-checkpoint"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = Gateway()
    learner = controller(ledger, gateway, curriculum())
    write_checkpoint = ledger.write_controller_checkpoint

    def crash_before_initial_checkpoint(requested_run_id, state, **kwargs):
        if requested_run_id == run_id:
            raise CrashAfterCurriculumCallback("initial_checkpoint_lost")
        return write_checkpoint(requested_run_id, state, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "write_controller_checkpoint", crash_before_initial_checkpoint)
        with pytest.raises(CrashAfterCurriculumCallback, match="initial_checkpoint_lost"):
            learner.run_drs(run_id=run_id, **PINS, max_practice_rounds=1, max_target_attempts=2)

    assert ledger.controller_checkpoint(run_id) is None
    assert gateway.requests == []
    # Failure observations belong to persisted run state, so a restart needs only the same
    # immutable policy identity; it does not have to seed the observations again.
    restarted = controller(
        RSILedger(ledger.database), gateway,
        FailureDrivenCurriculum(seed="resume-seed", budget=4),
    )
    assert restarted.resume(run_id).status == "completed"
    assert restarted.curriculum.selections[0].practice_task == "practice-sort"
    assert restarted.curriculum.remaining_budget == 3


def test_deterministic_curriculum_keeps_legacy_checkpoint_shape(tmp_path: Path):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    learner = RSILearningController(
        Gateway(), ledger=ledger, verifier=LocalExactVerifier(), target_judge=JudgeAfterPractice(),
    )
    result = learner.run_drs(run_id="deterministic-shape", **PINS, max_practice_rounds=0)
    assert result.status == "failed"
    state = ledger.controller_checkpoint("deterministic-shape")[1]
    assert "curriculum_state" not in state
