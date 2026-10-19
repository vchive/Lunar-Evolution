"""Governed finalization budget joins real local campaign journals."""
from __future__ import annotations

import sys
import types
from copy import deepcopy
from pathlib import Path

_tests_package = types.ModuleType("tests")
_tests_package.__path__ = [str(Path(__file__).parent)]
sys.modules.setdefault("tests", _tests_package)

import pytest
from test_rsi_controller_generation import PINS, Trials, controller

from lunar_evolution.rsi_brs_serial_budget import validate_reserved_brs_finalization_budget
from lunar_evolution.rsi_controller import CurriculumDecision
from lunar_evolution.rsi_learning import RSILearningError


def _run(tmp_path: Path, *, reject: bool = False):
    owner = controller(tmp_path, Trials(reject=reject))
    decision = CurriculumDecision(
        "fixture", "gap", "practice", "strategy", "pass", "boundary", ("fixture",),
    )
    result = owner.run_brs(
        run_id="broad", contract_sha256=PINS["contract"],
        evaluator_sha256=PINS["evaluator"], environment_sha256=PINS["environment"],
        solver_id="fixture", practices=[decision, decision],
    )
    history = owner.ledger.controller_checkpoint_history("broad")
    scheduling = next(
        state for _head, state in history
        if state["phase"] == "evaluated" and len(state["executions"]) == 2
    )
    return owner, result, scheduling, history


@pytest.mark.parametrize("reject", [False, True])
def test_real_governed_campaign_receipts_match_final_counters(tmp_path, reject):
    owner, result, scheduling, history = _run(tmp_path, reject=reject)
    assert result.status == "completed"
    validate_reserved_brs_finalization_budget(owner, scheduling, history)
    final = history[-1][1]
    consumed = final["budget_state"]["consumed"]
    assert consumed["practice_rounds"] == 2
    assert consumed["practice_episodes"] == 2
    assert consumed["solver_invocations"] == 2
    assert consumed["verifier_invocations"] == 2
    assert consumed["transfer_invocations"] == 36
    assert consumed["evaluator_invocations"] == 38


@pytest.mark.parametrize("fault", ["receipt", "counter", "deadline"])
def test_governed_finalization_rejects_unbound_budget_history(tmp_path, fault):
    owner, _result, scheduling, _history = _run(tmp_path)
    latest_head, latest = owner.ledger.controller_checkpoint("broad")
    changed = deepcopy(latest)
    if fault == "receipt":
        changed["external_budget_reservations"]["a" * 64] = {
            "binding_sha256": "b" * 64, "kind": "trial",
        }
    elif fault == "counter":
        changed["budget_state"]["consumed"]["transfer_invocations"] -= 1
    else:
        changed["budget_state"]["planned"]["deadline_unix"] = 1.0
    with owner.ledger.controller_lock("broad"):
        owner.ledger.write_controller_checkpoint("broad", changed, expected_sha256=latest_head)
        corrupted = owner.ledger.controller_checkpoint_history("broad")
        with pytest.raises(RSILearningError, match="rsi_brs_reserved_finalization_budget_"):
            validate_reserved_brs_finalization_budget(owner, scheduling, corrupted)
