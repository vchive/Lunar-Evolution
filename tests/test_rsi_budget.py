"""Focused A5 coverage for durable RSI run budgets and terminal handling."""
import pytest

from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64
PINS = {
    "contract_sha256": HEX,
    "evaluator_sha256": HEX,
    "environment_sha256": HEX,
    "solver_id": "mock",
}


class Gateway:
    def __init__(self, statuses: tuple[str, ...] = ()) -> None:
        self.statuses = list(statuses)
        self.requests = []

    def fingerprint(self) -> str:
        return "b" * 64

    def run(self, request):
        self.requests.append(request)
        status = self.statuses.pop(0) if self.statuses else "completed"
        return DeterministicMockSolver(terminal_status=status).run(request)


def controller(tmp_path, gateway: Gateway) -> RSILearningController:
    return RSILearningController(gateway, ledger=RSILedger(tmp_path / "rsi.sqlite3"))


def test_solver_budget_is_persisted_and_stops_new_episodes(tmp_path):
    gateway = Gateway(("failed", "completed"))
    result = controller(tmp_path, gateway).run_drs(
        run_id="bounded", **PINS, budget={"max_solver_invocations": 1},
    )
    assert result.status == "budget_exhausted"
    assert [request.episode_id for request in gateway.requests] == ["bounded-target-0"]
    checkpoint = controller(tmp_path, Gateway()).ledger.controller_checkpoint("bounded")[1]
    assert checkpoint["budget_state"] == {
        "planned": {
            "max_depth": None,
            "max_solver_invocations": 1,
            "max_practice_episodes": None,
            "max_unknown_retries": None,
            "deadline_unix": None,
        },
        "consumed": {"solver_invocations": 1, "practice_episodes": 0, "unknown_retries": 0},
        "remaining": {"solver_invocations": 0, "practice_episodes": None, "unknown_retries": None},
    }
    resumed_gateway = Gateway()
    assert controller(tmp_path, resumed_gateway).resume(run_id="bounded").status == "budget_exhausted"
    assert resumed_gateway.requests == []


def test_depth_limit_stops_practice_child_before_gateway_launch(tmp_path):
    gateway = Gateway(("failed", "completed"))
    result = controller(tmp_path, gateway).run_drs(
        run_id="depth", **PINS, budget={"max_depth": 0},
    )
    assert result.status == "budget_exhausted"
    assert [request.episode_id for request in gateway.requests] == ["depth-target-0"]
    checkpoint = controller(tmp_path, Gateway()).ledger.controller_checkpoint("depth")[1]
    assert checkpoint["episodes"]["depth-target-0"]["depth"] == 0
    assert checkpoint["episodes"]["depth-practice-0-0"]["depth"] == 1


def test_resume_rejects_budget_checkpoint_that_expands_remaining_work(tmp_path):
    first = controller(tmp_path, Gateway(("failed",)))
    first.run_drs(run_id="tampered", **PINS, budget={"max_solver_invocations": 1})
    version, checkpoint = first.ledger.controller_checkpoint("tampered")
    checkpoint["budget_state"]["consumed"]["solver_invocations"] = 0
    checkpoint["budget_state"]["remaining"]["solver_invocations"] = 1
    with first.ledger.controller_lock("tampered"):
        first.ledger.write_controller_checkpoint("tampered", checkpoint, expected_sha256=version)
    with pytest.raises(RSILearningError, match="rsi_budget_checkpoint_invalid"):
        controller(tmp_path, Gateway()).resume(run_id="tampered")


def test_resume_requires_budget_counts_to_exactly_match_reserved_episodes(tmp_path):
    first = controller(tmp_path, Gateway(("failed",)))
    first.run_drs(run_id="overcounted", **PINS, budget={"max_solver_invocations": 3},
                  max_practice_rounds=0, max_target_attempts=1)
    version, checkpoint = first.ledger.controller_checkpoint("overcounted")
    checkpoint["budget_state"]["consumed"]["solver_invocations"] = 3
    checkpoint["budget_state"]["remaining"]["solver_invocations"] = 0
    with first.ledger.controller_lock("overcounted"):
        first.ledger.write_controller_checkpoint("overcounted", checkpoint, expected_sha256=version)
    with pytest.raises(RSILearningError, match="rsi_budget_checkpoint_invalid"):
        controller(tmp_path, Gateway()).resume(run_id="overcounted")


def test_unknown_reconciliation_has_a_durable_retry_budget(tmp_path):
    gateway = Gateway(("unknown",))
    first = controller(tmp_path, gateway)
    assert first.run_drs(run_id="unknown", **PINS, budget={"max_unknown_retries": 0}).status == "unknown"
    request = gateway.requests[0]
    head = first.ledger.get(request.episode_id)
    result = first.reconcile_episode(
        run_id="unknown", episode_id=request.episode_id,
        result=DeterministicMockSolver().run(request), expected_record_sha256=head.record_sha256,
    )
    assert result.status == "budget_exhausted"
    checkpoint = first.ledger.controller_checkpoint("unknown")[1]
    assert checkpoint["budget_state"]["consumed"]["unknown_retries"] == 0


def test_reconciliation_budget_is_bound_to_original_record_and_evidence(tmp_path):
    gateway = Gateway(("unknown",))
    first = controller(tmp_path, gateway)
    assert first.run_drs(run_id="reconciled", **PINS, budget={"max_unknown_retries": 1},
                         max_practice_rounds=0, max_target_attempts=1).status == "unknown"
    request = gateway.requests[0]
    head = first.ledger.get(request.episode_id)
    assert first.reconcile_episode(
        run_id="reconciled", episode_id=request.episode_id,
        result=DeterministicMockSolver(terminal_status="failed").run(request),
        expected_record_sha256=head.record_sha256,
    ).status == "failed"
    version, checkpoint = first.ledger.controller_checkpoint("reconciled")
    entry = checkpoint["episodes"][request.episode_id]
    assert entry["reconciliation"]["expected_record_sha256"] == head.record_sha256
    checkpoint["budget_state"]["consumed"]["unknown_retries"] = 0
    checkpoint["budget_state"]["remaining"]["unknown_retries"] = 1
    with first.ledger.controller_lock("reconciled"):
        first.ledger.write_controller_checkpoint("reconciled", checkpoint, expected_sha256=version)
    with pytest.raises(RSILearningError, match="rsi_budget_checkpoint_invalid"):
        controller(tmp_path, Gateway()).resume(run_id="reconciled")
