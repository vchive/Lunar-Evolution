"""A retained adapter result repairs the controller handoff without executing again."""

from __future__ import annotations

import pytest

from lunar_evolution.rsi_controller import CurriculumDecision, RSILearningController
from lunar_evolution.rsi_durable_adapter import DurableSolverGateway
from lunar_evolution.rsi_gateway import DeterministicMockSolver
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64


class LocalGateway:
    def __init__(self, *, crash=False):
        self.crash = crash
        self.requests = []

    def rsi_fingerprint_config(self):
        return {"fixture": "durable-controller", "crash": self.crash}

    def run(self, request):
        self.requests.append(request)
        if self.crash:
            raise RuntimeError("local worker interrupted before result")
        return DeterministicMockSolver().run(request)


def run(controller, run_id):
    return controller.run_drs(
        run_id=run_id, contract_sha256=HEX, evaluator_sha256=HEX,
        environment_sha256=HEX, solver_id="mock", max_practice_rounds=0,
        max_target_attempts=1,
    )


def controller_at(path, gateway, scope_id):
    ledger = RSILedger(path)
    durable = DurableSolverGateway(gateway, ledger, scope_id=scope_id)
    return RSILearningController(durable, ledger=ledger), durable


def test_durable_completion_repairs_interrupted_controller_handoff(tmp_path, monkeypatch):
    path = tmp_path / "rsi.sqlite3"
    gateway = LocalGateway()
    controller, _durable = controller_at(path, gateway, "handoff")
    original_save = controller.ledger.save_episode_result

    with monkeypatch.context() as patch:
        def interrupted_save(*_args):
            raise RuntimeError("controller result handoff interrupted")

        patch.setattr(controller.ledger, "save_episode_result", interrupted_save)
        with pytest.raises(RuntimeError, match="handoff interrupted"):
            run(controller, "handoff")

    assert len(gateway.requests) == 1
    request = gateway.requests[0]
    assert controller.ledger.episode_result(request.episode_id) is None
    budget_before = controller.ledger.controller_checkpoint("handoff")[1]["budget_state"]
    with pytest.raises(RSILearningError, match="recovery_required|reconcile_required"):
        controller.resume("handoff")

    # A new wrapper reopens the exact completed adapter record; no worker call is made.
    restarted, recovered_gateway = controller_at(path, gateway, "handoff")
    result = recovered_gateway.restore_result(request)
    assert result.status == "completed"
    assert restarted.ledger.episode_result(request.episode_id) == (request, result)
    original_save(request, result)  # The normal controller write remains exactly idempotent.
    recovered = restarted.resume("handoff")
    assert recovered.status == "completed"
    assert len(recovered.target_attempts) == 1
    assert recovered.target_attempts[0].passed
    assert not recovered.memory_snapshot.items
    assert len(gateway.requests) == 1
    budget_after = restarted.ledger.controller_checkpoint("handoff")[1]["budget_state"]
    assert budget_after["consumed"] == budget_before["consumed"]
    history = restarted.ledger.controller_checkpoint_history("handoff")
    episode_history = restarted.ledger.history(request.episode_id)
    assert restarted.resume("handoff").status == "completed"
    assert restarted.ledger.controller_checkpoint_history("handoff") == history
    assert restarted.ledger.history(request.episode_id) == episode_history
    assert len(gateway.requests) == 1


def test_started_adapter_without_result_cannot_repair_or_resume(tmp_path):
    gateway = LocalGateway(crash=True)
    controller, durable = controller_at(tmp_path / "rsi.sqlite3", gateway, "started")
    with pytest.raises(RuntimeError, match="worker interrupted"):
        run(controller, "started")
    request = gateway.requests[0]
    budget = controller.ledger.controller_checkpoint("started")[1]["budget_state"]
    with pytest.raises(RSILearningError, match="recovery_required|reconcile_required"):
        durable.restore_result(request)
    with pytest.raises(RSILearningError, match="recovery_required|reconcile_required"):
        durable.run(request)
    with pytest.raises(RSILearningError, match="recovery_required|reconcile_required"):
        controller.resume("started")
    assert len(gateway.requests) == 1
    assert controller.ledger.episode_result(request.episode_id) is None
    assert controller.ledger.controller_checkpoint("started")[1]["budget_state"] == budget


def test_brs_parallel_completions_restore_frozen_wave_without_new_calls(tmp_path, monkeypatch):
    path = tmp_path / "rsi.sqlite3"
    gateway = LocalGateway()
    controller, durable = controller_at(path, gateway, "broad")
    practices = tuple(CurriculumDecision(
        f"family-{index}", "local gap", "boundary", "fixed practice", "pass",
        "local fixture only", ("mock",),
    ) for index in range(3))
    with monkeypatch.context() as patch:
        def interrupted_save(*_args):
            raise RuntimeError("parallel controller handoff interrupted")

        patch.setattr(controller.ledger, "save_episode_result", interrupted_save)
        with pytest.raises(RuntimeError, match="parallel controller handoff"):
            controller.run_brs(
                run_id="broad", contract_sha256=HEX, evaluator_sha256=HEX,
                environment_sha256=HEX, solver_id="mock", practices=practices, max_workers=3,
            )

    assert len(gateway.requests) == 3
    parents = {request.memory_snapshot_sha256 for request in gateway.requests}
    assert len(parents) == 1
    assert not controller.snapshot.items
    budget = controller.ledger.controller_checkpoint("broad")[1]["budget_state"]
    # Partial restoration must leave the entire frozen wave blocked.
    durable.restore_result(gateway.requests[0])
    with pytest.raises(RSILearningError, match="recovery_required|reconcile_required"):
        controller.resume("broad")
    assert not controller.snapshot.items
    restarted, restored = controller_at(path, gateway, "broad")
    for request in gateway.requests:
        restored.restore_result(request)
    result = restarted.resume("broad")
    assert result.status == "completed"
    assert len(result.practice_episodes) == len(result.memory_snapshot.items) == 3
    assert [item.episode.ordinal for item in result.practice_episodes] == [0, 1, 2]
    assert {item.request.memory_snapshot_sha256 for item in result.practice_episodes} == parents
    assert restarted.ledger.controller_checkpoint("broad")[1]["budget_state"]["consumed"] == budget["consumed"]
    assert len(gateway.requests) == 3
