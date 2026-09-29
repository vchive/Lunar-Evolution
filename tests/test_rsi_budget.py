"""Focused A5 coverage for durable RSI run budgets and terminal handling."""
from copy import deepcopy

import pytest

from lunar_evolution.rsi_budget import RSIRunBudget
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
            "max_evaluator_invocations": None,
            "max_verifier_invocations": None,
            "max_transfer_invocations": None,
            "deadline_unix": None,
        },
        "consumed": {
            "solver_invocations": 1, "practice_episodes": 0, "unknown_retries": 0,
            "evaluator_invocations": 0, "verifier_invocations": 1, "transfer_invocations": 0,
        },
        "remaining": {
            "solver_invocations": 0, "practice_episodes": None, "unknown_retries": None,
            "evaluator_invocations": None, "verifier_invocations": None,
            "transfer_invocations": None,
        },
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


@pytest.mark.parametrize("stage", ["evaluator", "verifier", "transfer"])
def test_stage_budgets_are_independent_and_survive_restore(stage):
    budget = RSIRunBudget.create({
        "max_evaluator_invocations": 2,
        "max_verifier_invocations": 2,
        "max_transfer_invocations": 2,
        "max_solver_invocations": 0,
    })
    budget.reserve_stage(stage)
    restored = RSIRunBudget.load(deepcopy(budget.state))
    restored.reserve_stage(stage)
    assert restored.state["consumed"][f"{stage}_invocations"] == 2
    assert restored.state["remaining"][f"{stage}_invocations"] == 0
    for other in {"evaluator", "verifier", "transfer"} - {stage}:
        assert restored.state["consumed"][f"{other}_invocations"] == 0
        assert restored.state["remaining"][f"{other}_invocations"] == 2
    assert restored.state["consumed"]["solver_invocations"] == 0
    before = deepcopy(restored.state)
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        restored.reserve_stage(stage)
    assert restored.state == before


@pytest.mark.parametrize("stage", ["evaluator", "verifier", "transfer"])
def test_stage_zero_budget_and_expired_deadline_stop_without_charging(stage, monkeypatch):
    blocked = RSIRunBudget.create({f"max_{stage}_invocations": 0})
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        blocked.reserve_stage(stage)
    assert blocked.state["consumed"][f"{stage}_invocations"] == 0

    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 100.0)
    budget = RSIRunBudget.create({f"max_{stage}_invocations": 2, "deadline_unix": 101.0})
    budget.reserve_stage(stage)
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 101.0)
    restored = RSIRunBudget.load(deepcopy(budget.state))
    before = deepcopy(restored.state)
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        restored.reserve_stage(stage)
    assert restored.state == before
    assert restored.state["planned"]["deadline_unix"] == 101.0


@pytest.mark.parametrize("stage", ["evaluator", "verifier", "transfer"])
@pytest.mark.parametrize("field,value", [
    ("consumed", -1), ("consumed", True), ("consumed", 3),
    ("remaining", -1), ("remaining", False), ("remaining", 2),
])
def test_stage_restoration_rejects_invalid_or_inconsistent_counters(stage, field, value):
    budget = RSIRunBudget.create({f"max_{stage}_invocations": 2})
    budget.reserve_stage(stage)
    state = deepcopy(budget.state)
    state[field][f"{stage}_invocations"] = value
    with pytest.raises(RSILearningError, match="rsi_budget_checkpoint_invalid"):
        RSIRunBudget.load(state)


@pytest.mark.parametrize("stage", ["evaluator", "verifier", "transfer"])
def test_stage_limit_drift_is_rejected_on_resume(stage):
    planned = {f"max_{stage}_invocations": 2}
    budget = RSIRunBudget.create(planned)
    budget.reserve_stage(stage)
    restored = RSIRunBudget.load(deepcopy(budget.state))
    restored.assert_matches(planned)
    with pytest.raises(RSILearningError, match="rsi_resume_budget_drift"):
        restored.assert_matches({f"max_{stage}_invocations": 3})


@pytest.mark.parametrize("stage", ["evaluator", "verifier", "transfer"])
def test_unlimited_stage_keeps_real_count_and_explicit_unlimited_remaining(stage):
    budget = RSIRunBudget.create(None)
    budget.reserve_stage(stage)
    restored = RSIRunBudget.load(deepcopy(budget.state))
    assert restored.state["consumed"][f"{stage}_invocations"] == 1
    assert restored.state["remaining"][f"{stage}_invocations"] is None
    restored.state["remaining"][f"{stage}_invocations"] = 0
    with pytest.raises(RSILearningError, match="rsi_budget_checkpoint_invalid"):
        RSIRunBudget.load(restored.state)


def test_restoration_rejects_boolean_remaining_even_when_equal_to_zero():
    state = RSIRunBudget.create({"max_verifier_invocations": 0}).state
    state["remaining"]["verifier_invocations"] = False
    with pytest.raises(RSILearningError, match="rsi_budget_checkpoint_invalid"):
        RSIRunBudget.load(state)


@pytest.mark.parametrize("stage", ["evaluator", "verifier", "transfer"])
@pytest.mark.parametrize("value", [-1, True, 1.5, "2"])
def test_stage_limits_reject_non_integer_or_negative_values(stage, value):
    with pytest.raises(RSILearningError, match=f"rsi_budget_max_{stage}_invocations_invalid"):
        RSIRunBudget.create({f"max_{stage}_invocations": value})


def test_legacy_budget_checkpoint_requires_explicit_evidence_based_migration():
    budget = RSIRunBudget.create({"max_solver_invocations": 2})
    budget.reserve_launch(episode_kind="target", depth=0, ancestry=("target",))
    state = deepcopy(budget.state)
    for stage in ("evaluator", "verifier", "transfer"):
        del state["planned"][f"max_{stage}_invocations"]
        del state["consumed"][f"{stage}_invocations"]
        del state["remaining"][f"{stage}_invocations"]
    before = deepcopy(state)
    with pytest.raises(RSILearningError, match="rsi_budget_legacy_checkpoint_requires_migration"):
        RSIRunBudget.load(state)
    assert state == before


@pytest.mark.parametrize("section", ["planned", "consumed", "remaining"])
def test_partial_new_stage_checkpoint_is_invalid(section):
    state = RSIRunBudget.create(None).state
    key = "max_transfer_invocations" if section == "planned" else "transfer_invocations"
    del state[section][key]
    with pytest.raises(RSILearningError, match="rsi_budget_checkpoint_invalid"):
        RSIRunBudget.load(state)


@pytest.mark.parametrize("stage", ["solver", "practice", "Evaluator", None, ["verifier"]])
def test_unknown_stage_names_are_rejected_without_charging(stage):
    budget = RSIRunBudget.create(None)
    before = deepcopy(budget.state)
    with pytest.raises(RSILearningError, match="rsi_budget_stage_invalid"):
        budget.reserve_stage(stage)
    assert budget.state == before
