"""Focused tests for the provider-free RSI budget contract."""

from copy import deepcopy

import pytest

from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_learning import RSILearningError


def _error(code: str):
    return pytest.raises(RSILearningError, match=code)


def test_create_has_durable_counter_shape_and_canonical_digest() -> None:
    budget = RSIRunBudget.create({
        "max_depth": 2,
        "max_practice_rounds": 3,
        "max_target_attempts": 4,
        "max_practice_episodes": 3,
        "max_solver_invocations": 7,
        "max_unknown_retries": 1,
        "deadline_unix": 123.5,
    })
    assert set(budget.state) == {"planned", "consumed", "remaining"}
    assert budget.state["planned"]["max_target_attempts"] == 4
    assert budget.state["consumed"]["target_attempts"] == 0
    assert budget.state["remaining"]["solver_invocations"] == 7
    assert len(budget.digest()) == 64
    assert budget.digest() == RSIRunBudget.load(budget.to_dict()).digest()
    assert budget.canonical_bytes() == RSIRunBudget.load(budget.to_dict()).canonical_bytes()


def test_load_is_detached_and_rejects_unknown_or_inconsistent_fields() -> None:
    original = RSIRunBudget.create({"max_solver_invocations": 2}).to_dict()
    restored = RSIRunBudget.load(original)
    restored.state["consumed"]["solver_invocations"] = 1
    assert original["consumed"]["solver_invocations"] == 0
    with _error("rsi_budget_unknown_field"):
        RSIRunBudget.create({"unbounded": 1})
    broken = RSIRunBudget.create({"max_solver_invocations": 2}).to_dict()
    broken["remaining"]["solver_invocations"] = 0
    with _error("rsi_budget_checkpoint_invalid"):
        RSIRunBudget.load(broken)


@pytest.mark.parametrize("value", [-1, True, 1.5, "2"])
def test_limits_are_strict(value: object) -> None:
    with _error("rsi_budget_max_solver_invocations_invalid"):
        RSIRunBudget.create({"max_solver_invocations": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "123"])
def test_deadline_is_finite_and_not_boolean(value: object) -> None:
    with _error("rsi_budget_deadline_unix_invalid"):
        RSIRunBudget.create({"deadline_unix": value})


def test_reserve_launch_charges_target_and_practice_limits() -> None:
    budget = RSIRunBudget.create({
        "max_target_attempts": 1,
        "max_practice_rounds": 1,
        "max_practice_episodes": 1,
        "max_solver_invocations": 2,
    })
    budget.reserve_launch(episode_kind="target", depth=0, ancestry=("target-0",))
    assert budget.state["consumed"] == {
        "practice_rounds": 0,
        "target_attempts": 1,
        "practice_episodes": 0,
        "solver_invocations": 1,
        "unknown_retries": 0,
        "evaluator_invocations": 0,
        "verifier_invocations": 0,
        "transfer_invocations": 0,
    }
    budget.reserve_launch(
        episode_kind="practice", depth=1, ancestry=("target-0", "practice-0"),
    )
    assert budget.state["consumed"]["practice_rounds"] == 1
    assert budget.state["consumed"]["practice_episodes"] == 1
    assert budget.state["remaining"]["solver_invocations"] == 0
    before = deepcopy(budget.state)
    with _error("rsi_budget_exhausted"):
        budget.reserve_launch(episode_kind="target", depth=0, ancestry=("target-1",))
    assert budget.state == before


@pytest.mark.parametrize("episode_kind", ["", "solver", "Target", None, 1])
def test_invalid_episode_kind_does_not_charge(episode_kind: object) -> None:
    budget = RSIRunBudget.create()
    before = deepcopy(budget.state)
    with _error("rsi_budget_episode_kind_invalid"):
        budget.reserve_launch(episode_kind=episode_kind, depth=0, ancestry=("root",))
    assert budget.state == before


@pytest.mark.parametrize(
    "depth,ancestry",
    [
        (-1, ("root",)),
        (1, ("root",)),
        (0, ("root", "child")),
        (0, ("root", "root")),
        (0, ["root"]),
        (0, ("",)),
        (0, ("root", "bad\nline")),
    ],
)
def test_depth_and_cycle_gate_is_fail_closed(depth: object, ancestry: object) -> None:
    budget = RSIRunBudget.create()
    before = deepcopy(budget.state)
    with _error("rsi_budget_depth_cycle"):
        budget.reserve_launch(episode_kind="target", depth=depth, ancestry=ancestry)
    assert budget.state == before


def test_depth_limit_is_checked_before_any_counter_mutation() -> None:
    budget = RSIRunBudget.create({"max_depth": 0, "max_solver_invocations": 2})
    before = deepcopy(budget.state)
    with _error("rsi_budget_exhausted"):
        budget.reserve_launch(episode_kind="practice", depth=1, ancestry=("root", "child"))
    assert budget.state == before


@pytest.mark.parametrize("stage", ["evaluator", "verifier", "transfer"])
def test_stage_budget_is_independent_and_rejects_replay_after_limit(stage: str) -> None:
    budget = RSIRunBudget.create({f"max_{stage}_invocations": 1})
    budget.reserve_stage(stage)
    assert budget.state["consumed"][f"{stage}_invocations"] == 1
    before = deepcopy(budget.state)
    with _error("rsi_budget_exhausted"):
        budget.reserve_stage(stage)
    assert budget.state == before


def test_unknown_reconcile_obeys_deadline_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 100.0)
    budget = RSIRunBudget.create({"max_unknown_retries": 2, "deadline_unix": 101.0})
    budget.reserve_unknown_reconcile()
    assert budget.state["remaining"]["unknown_retries"] == 1
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 101.0)
    before = deepcopy(budget.state)
    with _error("rsi_budget_exhausted"):
        budget.reserve_unknown_reconcile()
    assert budget.state == before


def test_generic_check_and_consume_are_atomic() -> None:
    budget = RSIRunBudget.create({"max_verifier_invocations": 1})
    budget.check(counter="verifier_invocations")
    budget.consume("verifier_invocations")
    assert budget.state["remaining"]["verifier_invocations"] == 0
    before = deepcopy(budget.state)
    with _error("rsi_budget_exhausted"):
        budget.consume("verifier_invocations")
    assert budget.state == before
    with _error("rsi_budget_counter_invalid"):
        budget.check(counter="not-a-counter")


def test_resume_budget_digest_and_planned_limits_are_exact() -> None:
    budget = RSIRunBudget.create({"max_solver_invocations": 2})
    budget.assert_matches({"max_solver_invocations": 2})
    with _error("rsi_resume_budget_drift"):
        budget.assert_matches({"max_solver_invocations": 3})
    changed = budget.to_dict()
    changed["planned"]["max_solver_invocations"] = 3
    changed["remaining"]["solver_invocations"] = 3
    assert RSIRunBudget.load(changed).digest() != budget.digest()


def test_unlimited_counters_remain_explicitly_unlimited() -> None:
    budget = RSIRunBudget.create()
    budget.reserve_stage("evaluator")
    budget.reserve_unknown_reconcile()
    assert budget.state["remaining"]["evaluator_invocations"] is None
    assert budget.state["remaining"]["unknown_retries"] is None

