"""Curriculum feedback is reconstructed from retained controller evidence."""
from dataclasses import replace

import pytest
from test_rsi_curriculum import execution

from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_curriculum import CurriculumCandidate, DeterministicDiversityCurriculum
from lunar_evolution.rsi_gateway import DeterministicMockSolver
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger

PINS = {"contract_sha256": "a" * 64, "evaluator_sha256": "b" * 64,
        "environment_sha256": "c" * 64, "solver_id": "mock"}


def policy():
    return DeterministicDiversityCurriculum([
        CurriculumCandidate(name, name, "gap", "practice " + name, "verified coverage", name, ("mock",))
        for name in ("first", "second")
    ])


def judge(execution):
    return execution.episode.wave >= 2, "gap"


class Gateway:
    def __init__(self, *, interrupt=None):
        self.requests = []
        self.interrupt = interrupt

    def fingerprint(self):
        return "d" * 64

    def run(self, request):
        self.requests.append(request)
        if request.episode_id == self.interrupt:
            raise RuntimeError("interrupted")
        return DeterministicMockSolver().run(request)


def test_controller_uses_verified_history_for_next_practice_and_replays_it(tmp_path):
    initial = policy()
    ledger = RSILedger(tmp_path / "rsi.db")
    gateway = Gateway(interrupt="learn-target-1")
    controller = RSILearningController(gateway, curriculum=initial, ledger=ledger, target_judge=judge)
    with pytest.raises(RuntimeError, match="interrupted"):
        controller.run_drs(run_id="learn", **PINS, max_target_attempts=3, max_practice_rounds=2)
    assert not initial.history
    request = gateway.requests[-1]
    resumed_gateway = Gateway()
    resumed = RSILearningController(resumed_gateway, curriculum=policy(), ledger=ledger, target_judge=judge)
    assert resumed.resume(run_id="learn").status == "unknown"
    head = ledger.get(request.episode_id)
    result = resumed.reconcile_episode(run_id="learn", episode_id=request.episode_id,
                                       result=DeterministicMockSolver().run(request),
                                       expected_record_sha256=head.record_sha256)
    assert result.status == "completed"
    families = [dict(item.request.practice_charter)["practice_family"] for item in result.practice_episodes]
    assert families == ["first", "second"]
    checkpoint = ledger.controller_checkpoint("learn")[1]
    assert checkpoint["curriculum_history_sha256"] != initial.history_fingerprint()
    calls = len(resumed_gateway.requests)
    assert resumed.resume(run_id="learn") == result
    assert len(resumed_gateway.requests) == calls
    assert ledger.controller_checkpoint("learn")[1]["curriculum_history_sha256"] == checkpoint["curriculum_history_sha256"]


def test_changed_initial_history_cannot_adopt_same_run(tmp_path):
    initial = policy()
    ledger = RSILedger(tmp_path / "rsi.db")
    RSILearningController(Gateway(), curriculum=initial, ledger=ledger).run_drs(run_id="history", **PINS)
    chosen = initial.candidates[0].decision()
    changed = initial.observe(decision=chosen, execution=execution(chosen))
    with pytest.raises(RSILearningError, match="curriculum_history_fingerprint_drift"):
        RSILearningController(Gateway(), curriculum=changed, ledger=ledger).resume(run_id="history")


def test_changed_catalog_is_rejected_before_gateway(tmp_path):
    initial = policy()
    ledger = RSILedger(tmp_path / "rsi.db")
    RSILearningController(Gateway(), curriculum=initial, ledger=ledger).run_drs(run_id="catalog", **PINS)
    changed = DeterministicDiversityCurriculum([replace(initial.candidates[0], strategy="different")])
    gateway = Gateway()
    with pytest.raises(RSILearningError, match="curriculum_fingerprint_drift"):
        RSILearningController(gateway, curriculum=changed, ledger=ledger).resume(run_id="catalog")
    assert not gateway.requests


@pytest.mark.parametrize("status", ["timed_out", "abandoned"])
def test_unknown_reconciles_to_terminal_failure_without_replay(tmp_path, status):
    ledger = RSILedger(tmp_path / "rsi.db")
    gateway = Gateway(interrupt="terminal-target-0")
    instance = RSILearningController(gateway, ledger=ledger)
    with pytest.raises(RuntimeError, match="interrupted"):
        instance.run_drs(run_id="terminal", **PINS)
    assert instance.resume(run_id="terminal").status == "unknown"
    request = gateway.requests[0]
    outcome = instance.reconcile_episode(run_id="terminal", episode_id=request.episode_id,
                                          result=DeterministicMockSolver(terminal_status=status).run(request),
                                          expected_record_sha256=ledger.get(request.episode_id).record_sha256)
    assert outcome.status == "failed"
    assert len(gateway.requests) == 1
