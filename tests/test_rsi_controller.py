import hashlib
from pathlib import Path

import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT,
    DeterministicCurriculum,
    FrozenMemoryTransferRunner,
    RSILearningController,
    RSILearningError,
    RSILedger,
    SolverRequest,
    SolverResult,
    fixture_solver_gateway,
)

HEX = "a" * 64


class ScriptedGateway:
    def __init__(self, *statuses: str) -> None:
        self.statuses = list(statuses)
        self.requests: list[SolverRequest] = []

    def run(self, request: SolverRequest) -> SolverResult:
        self.requests.append(request)
        status = self.statuses.pop(0)
        digest = lambda label: hashlib.sha256(f"{label}:{request.digest()}".encode()).hexdigest()
        completed = status == "completed"
        return SolverResult(
            request.episode_id,
            request.digest(),
            status,
            digest("candidate") if completed else None,
            digest("execution") if completed else None,
            digest("evaluation") if completed else None,
            digest("trace"),
            1.0 if completed else None,
            f"scripted_{status}",
        )


def judge_after_first(execution):
    return (execution.episode.wave > 0, "needs practice")


def test_drs_commits_verified_practice_before_retrying_target():
    gateway = ScriptedGateway("completed", "completed", "completed")
    result = RSILearningController(gateway, target_judge=judge_after_first).run_drs(
        run_id="drs-1",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        solver_id="mock",
        max_practice_rounds=1,
        max_target_attempts=2,
    )

    assert result.status == "completed"
    assert len(result.target_attempts) == 2
    assert len(result.practice_episodes) == 1
    assert len(result.memory_snapshot.items) == 1
    assert result.target_attempts[1].episode.memory_snapshot_sha256 == result.memory_snapshot.digest()


def test_drs_target_unknown_stops_without_practice_or_retry():
    gateway = ScriptedGateway("unknown", "completed")
    result = RSILearningController(gateway, target_judge=judge_after_first).run_drs(
        run_id="drs-unknown-target",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        solver_id="mock",
        max_practice_rounds=2,
        max_target_attempts=3,
    )

    assert result.status == "unknown"
    assert len(result.target_attempts) == 1
    assert result.practice_episodes == ()
    assert len(gateway.requests) == 1


def test_drs_unknown_practice_stops_without_retry_or_memory():
    gateway = ScriptedGateway("completed", "unknown", "completed")
    result = RSILearningController(gateway, target_judge=lambda _execution: (False, "gap")).run_drs(
        run_id="drs-unknown-practice",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        solver_id="mock",
        max_practice_rounds=2,
        max_target_attempts=3,
    )

    assert result.status == "unknown"
    assert len(result.target_attempts) == 1
    assert len(result.practice_episodes) == 1
    assert result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT
    assert len(gateway.requests) == 2


def test_brs_commits_completed_children_in_ordinal_order():
    gateway = ScriptedGateway("completed", "completed")
    controller = RSILearningController(gateway)
    curriculum = DeterministicCurriculum()
    target = controller._target_episode(
        "brs-1", "brs-1-target", {
            "contract_sha256": HEX, "evaluator_sha256": HEX,
            "environment_sha256": HEX, "solver_id": "mock",
        }, 0,
    )
    decisions = [curriculum.choose(target=target, diagnosis=f"gap-{i}", wave=0, ordinal=i) for i in range(2)]
    result = controller.run_brs(
        run_id="brs-1", contract_sha256=HEX, evaluator_sha256=HEX,
        environment_sha256=HEX, solver_id="mock", practices=decisions,
    )

    assert result.status == "completed"
    assert [episode.episode.ordinal for episode in result.practice_episodes] == [0, 1]
    assert [item.trigger for item in result.memory_snapshot.items] == ["gap-0", "gap-1"]


@pytest.mark.parametrize("status", ["unknown", "timed_out", "abandoned", "cancelled"])
def test_brs_uncertain_child_blocks_wave_memory_merge_until_reconciliation(status: str):
    class OrdinalGateway:
        def run(self, request):
            ordinal = int(request.episode_id.rsplit("-", 1)[1])
            terminal_status = "completed" if ordinal == 0 else status
            return fixture_solver_gateway("mock", terminal_status=terminal_status).run(request)

    controller = RSILearningController(OrdinalGateway())
    target = controller._target_episode(
        "brs-unknown", "brs-unknown-target", {
            "contract_sha256": HEX, "evaluator_sha256": HEX,
            "environment_sha256": HEX, "solver_id": "mock",
        }, 0,
    )
    curriculum = DeterministicCurriculum()
    decisions = [curriculum.choose(target=target, diagnosis=f"gap-{i}", wave=0, ordinal=i) for i in range(2)]

    result = controller.run_brs(
        run_id=f"brs-{status}", contract_sha256=HEX, evaluator_sha256=HEX,
        environment_sha256=HEX, solver_id="mock", practices=decisions,
    )

    assert result.status == ("unknown" if status == "unknown" else "failed")
    assert result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT
    assert [execution.result.status for execution in result.practice_episodes] == ["completed", status]


def test_frozen_transfer_rejects_memory_write_and_preserves_snapshot():
    runner = FrozenMemoryTransferRunner(ScriptedGateway("unknown"))
    with pytest.raises(RSILearningError, match="rsi_transfer_memory_write_disabled"):
        runner.reject_memory_write()
    receipt, execution = runner.run(
        run_id="transfer-1", target_id="transfer-target", contract_sha256=HEX,
        evaluator_sha256=HEX, environment_sha256=HEX, solver_id="mock",
        snapshot=EMPTY_MEMORY_SNAPSHOT,
    )
    assert receipt.status == "unknown"
    assert execution.episode.memory_snapshot_sha256 == EMPTY_MEMORY_SNAPSHOT.digest()
    assert receipt.to_dict()["curriculum_enabled"] is False
    assert receipt.to_dict()["memory_write_enabled"] is False


def test_controller_binds_episode_lifecycle_to_append_only_ledger(tmp_path: Path):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    result = RSILearningController(
        ScriptedGateway("completed"),
        ledger=ledger,
        target_judge=lambda _execution: (True, "accepted"),
    ).run_drs(
        run_id="ledger-bound",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        solver_id="mock",
        max_target_attempts=1,
    )

    assert result.status == "completed"
    episode_id = result.target_attempts[0].episode.episode_id
    assert [record.state for record in ledger.history(episode_id)] == [
        "running", "completed", "completed",
    ]
    assert ledger.get(episode_id).payload["verifier"]["outcome"] == "pass"
