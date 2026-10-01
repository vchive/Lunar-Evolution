from __future__ import annotations

from pathlib import Path

import pytest

from lunar_evolution import RSILearningController, RSILearningError, RSILedger
from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_gateway import DeterministicMockSolver

HEX = "a" * 64


class ConfiguredVerifier:
    def __init__(self, threshold: int) -> None:
        self.threshold = threshold

    def rsi_fingerprint_config(self) -> dict[str, int]:
        return {"threshold": self.threshold}

    def verify(self, episode, request, result):  # pragma: no cover - identity-only fixture
        del episode, request, result


def test_controller_run_identity_commits_component_configuration(tmp_path: Path) -> None:
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    first = RSILearningController(
        DeterministicMockSolver(), verifier=ConfiguredVerifier(1), ledger=ledger
    )
    record = first._start_run(
        run_id="fingerprint-config",
        mode="drs",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        solver_id="mock",
        budget={},
    )
    assert record is not None
    second = RSILearningController(
        DeterministicMockSolver(), verifier=ConfiguredVerifier(2), ledger=ledger
    )
    with pytest.raises(RSILearningError, match="rsi_resume_fingerprint_drift"):
        second._assert_existing_run_request(
            record,
            mode="drs",
            contract_sha256=HEX,
            evaluator_sha256=HEX,
            environment_sha256=HEX,
            solver_id="mock",
            budget={},
        )


def test_episode_budget_reserves_solver_and_verifier_stages_atomically() -> None:
    budget = RSIRunBudget.create(
        {
            "max_target_attempts": 1,
            "max_solver_invocations": 1,
            "max_evaluator_invocations": 1,
            "max_verifier_invocations": 1,
        }
    )
    RSILearningController._reserve_episode_budget(
        budget,
        episode_kind="target",
        depth=0,
        ancestry=("target-0",),
    )
    consumed = budget.to_dict()["consumed"]
    assert consumed["solver_invocations"] == 1
    assert consumed["target_attempts"] == 1
    assert consumed["evaluator_invocations"] == 1
    assert consumed["verifier_invocations"] == 1
