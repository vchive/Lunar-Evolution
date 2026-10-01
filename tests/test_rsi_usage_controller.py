from __future__ import annotations

import importlib
from pathlib import Path

from lunar_evolution import (
    DeterministicCurriculum,
    DeterministicMockSolver,
    RSILearningController,
    RSIUsageLedger,
)

HEX = "a" * 64


def pins() -> dict[str, str]:
    return {
        "contract_sha256": HEX,
        "evaluator_sha256": HEX,
        "environment_sha256": HEX,
        "solver_id": "mock",
    }


def test_controller_sidecar_records_monotonic_solver_wall_time_and_unknown_usage(
    tmp_path: Path, monkeypatch,
) -> None:
    controller_module = importlib.import_module("lunar_evolution.rsi_controller")
    ticks = iter((100_000_000, 112_345_678))
    monkeypatch.setattr(controller_module.time, "monotonic_ns", lambda: next(ticks))
    usage = RSIUsageLedger(tmp_path / "usage.json")

    result = RSILearningController(
        DeterministicMockSolver(), usage_ledger=usage,
    ).run_drs(run_id="usage-run", **pins(), max_practice_rounds=0, max_target_attempts=1)

    assert result.status == "completed"
    records = usage.records()
    assert len(records) == 1
    receipt = records[0]
    assert receipt.event_id.startswith("rsi-solver-")
    assert receipt.run_id == "usage-run"
    assert receipt.episode_id == result.target_attempts[0].episode.episode_id
    assert receipt.adapter_stage == "solver"
    assert receipt.wall_time_ms == 12
    assert receipt.input_tokens is None
    assert receipt.output_tokens is None
    assert receipt.cpu_time_ms is None


def test_controller_sidecar_replay_is_event_idempotent(tmp_path: Path) -> None:
    from lunar_evolution import RSILedger

    state = RSILedger(tmp_path / "rsi.sqlite3")
    usage = RSIUsageLedger(tmp_path / "usage.json")
    first = RSILearningController(
        DeterministicMockSolver(), ledger=state, usage_ledger=usage,
    ).run_drs(run_id="usage-replay", **pins(), max_practice_rounds=0, max_target_attempts=1)
    replay = RSILearningController(
        DeterministicMockSolver(), ledger=state, usage_ledger=usage,
    ).resume("usage-replay")

    assert replay.status == first.status == "completed"
    assert len(usage.records()) == 1
    assert replay.target_attempts == first.target_attempts


def test_controller_replay_missing_sidecar_records_unknown_marker(tmp_path: Path) -> None:
    from lunar_evolution import RSILedger

    state = RSILedger(tmp_path / "rsi.sqlite3")
    usage_path = tmp_path / "usage.json"
    first_usage = RSIUsageLedger(usage_path)
    RSILearningController(
        DeterministicMockSolver(), ledger=state, usage_ledger=first_usage,
    ).run_drs(run_id="usage-gap", **pins(), max_practice_rounds=0, max_target_attempts=1)
    usage_path.unlink()

    replay_usage = RSIUsageLedger(usage_path)
    replay = RSILearningController(
        DeterministicMockSolver(), ledger=state, usage_ledger=replay_usage,
    ).resume("usage-gap")

    assert replay.status == "completed"
    assert len(replay_usage.records()) == 1
    assert replay_usage.records()[0].wall_time_ms is None
    assert replay_usage.summary(run_id="usage-gap").usage_complete is False


def test_controller_sidecar_is_safe_for_concurrent_brs_appends(tmp_path: Path) -> None:
    usage = RSIUsageLedger(tmp_path / "usage.json")
    controller = RSILearningController(
        DeterministicMockSolver(), usage_ledger=usage,
    )
    target = controller._target_episode("usage-brs", "usage-brs-target", pins(), 0)
    curriculum = DeterministicCurriculum()
    practices = [
        curriculum.choose(target=target, diagnosis=f"gap-{index}", wave=0, ordinal=index)
        for index in range(4)
    ]

    result = controller.run_brs(
        run_id="usage-brs", practices=practices, **pins(), max_workers=4,
    )

    assert result.status == "completed"
    assert len(usage.records()) == 4
    assert {item.episode_id for item in usage.records()} == {
        execution.episode.episode_id for execution in result.practice_episodes
    }
