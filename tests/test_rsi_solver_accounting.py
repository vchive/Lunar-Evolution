"""Durable solver reservations fail closed around checkpoint persistence."""

import copy

import pytest

from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_stage_accounting import (
    DurableSolverAccounting,
    digest,
    validate_solver_history,
)

HEX = "a" * 64


def _accounting(*, persist):
    state = {"invocations": []}
    budget = RSIRunBudget.create({"max_solver_invocations": 2}).state
    return DurableSolverAccounting(state, budget, persist), state, budget


def test_solver_reservation_persistence_failure_rolls_back_and_poison_accounting():
    writes = []
    fail = False

    def persist():
        writes.append((copy.deepcopy(state), copy.deepcopy(budget)))
        if fail:
            raise OSError("checkpoint unavailable")

    accounting, state, budget = _accounting(persist=persist)
    fail = True
    with pytest.raises(OSError, match="checkpoint unavailable"):
        accounting.reserve({"episode_id": "first"})

    assert state == {"invocations": []}
    assert budget["consumed"]["solver_invocations"] == 0
    assert budget["remaining"]["solver_invocations"] == 2
    with pytest.raises(RSILearningError, match="rsi_solver_accounting_poisoned"):
        accounting.reserve({"episode_id": "second"})


def test_solver_completion_persistence_failure_keeps_pending_and_poison_accounting():
    fail = False

    def persist():
        if fail:
            raise OSError("checkpoint unavailable")

    accounting, state, budget = _accounting(persist=persist)
    row = accounting.reserve({"episode_id": "pending"})
    assert row["result_sha256"] is None
    fail = True

    with pytest.raises(OSError, match="checkpoint unavailable"):
        accounting.complete(row, HEX)

    assert row["result_sha256"] is None
    assert state["invocations"] == [row]
    assert budget["consumed"]["solver_invocations"] == 1
    with pytest.raises(RSILearningError, match="rsi_solver_accounting_poisoned"):
        accounting.complete(row, HEX)
    with pytest.raises(RSILearningError, match="rsi_solver_accounting_poisoned"):
        accounting.reserve({"episode_id": "after-failure"})


def test_completed_solver_invocation_is_idempotent_for_same_evidence():
    writes = 0

    def persist():
        nonlocal writes
        writes += 1

    accounting, state, budget = _accounting(persist=persist)
    row = accounting.reserve({"episode_id": "completed"})
    accounting.complete(row, HEX)
    accounting.complete(row, HEX)

    assert len(state["invocations"]) == 1
    assert state["invocations"][0] is row
    assert row["result_sha256"] == HEX
    assert budget["consumed"]["solver_invocations"] == 1
    assert writes == 2


@pytest.mark.parametrize("mutation", ["erased", "identity", "evidence"])
def test_solver_history_rejects_erased_or_changed_rows(mutation):
    identity = {"episode_id": "history", "ordinal": 0}
    old = {
        "invocations": [{
            "identity": identity,
            "intent_sha256": digest(identity),
            "result_sha256": HEX,
        }],
    }
    current = copy.deepcopy(old)
    if mutation == "erased":
        current["invocations"] = []
    elif mutation == "identity":
        current["invocations"][0]["identity"]["ordinal"] = 1
        current["invocations"][0]["intent_sha256"] = digest(
            current["invocations"][0]["identity"],
        )
    else:
        current["invocations"][0]["result_sha256"] = "b" * 64

    with pytest.raises(RSILearningError, match="rsi_solver_checkpoint_invalid"):
        validate_solver_history(old, current)
