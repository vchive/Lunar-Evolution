"""Provider-free DRS context selection and unknown fail-closed regression."""

from __future__ import annotations

import hashlib

import pytest

from lunar_evolution import EMPTY_MEMORY_SNAPSHOT, RSILearningController, RSILearningError
from lunar_evolution.rsi_gateway import SolverRequest, SolverResult

HEX = "a" * 64


class ContextRecordingGateway:
    def __init__(self, *statuses: str) -> None:
        self.statuses = list(statuses)
        self.calls: list[tuple[SolverRequest, str]] = []

    def rsi_fingerprint_config(self):
        return {"fixture": "multi-episode-context-v1", "statuses": list(self.statuses)}

    def run(self, request: SolverRequest, memory=None) -> SolverResult:
        self.calls.append((request, request.memory_snapshot_sha256))
        status = self.statuses.pop(0)
        digest = lambda label: hashlib.sha256(f"{label}:{request.digest()}".encode()).hexdigest()
        complete = status == "completed"
        return SolverResult(
            request.episode_id, request.digest(), status,
            digest("candidate") if complete else None,
            digest("execution") if complete else None,
            digest("evaluation") if complete else None,
            digest("trace"), 1.0 if complete else None, f"fixture_{status}",
        )


def _run(gateway, run_id: str, *, practice: int = 1, targets: int = 2):
    return RSILearningController(
        gateway, target_judge=lambda execution: (execution.episode.wave > 0, "practice required"),
    ).run_drs(
        run_id=run_id, contract_sha256=HEX, evaluator_sha256=HEX,
        environment_sha256=HEX, solver_id="fixture", max_practice_rounds=practice,
        max_target_attempts=targets,
    )


def test_target_practice_retry_selects_each_episode_context_independently():
    gateway = ContextRecordingGateway("completed", "completed", "completed")
    result = _run(gateway, "multi-context")

    assert result.status == "completed"
    assert [request.episode_id for request, _ in gateway.calls] == [
        "multi-context-target-0", "multi-context-practice-0-0", "multi-context-target-1",
    ]
    assert len({request.digest() for request, _ in gateway.calls}) == 3
    assert gateway.calls[0][1] == EMPTY_MEMORY_SNAPSHOT.digest()
    assert gateway.calls[1][1] == EMPTY_MEMORY_SNAPSHOT.digest()
    assert gateway.calls[2][1] == result.memory_snapshot.digest()
    assert gateway.calls[2][1] != gateway.calls[0][1]
    assert result.target_attempts[1].request.memory_snapshot_sha256 == gateway.calls[2][1]


@pytest.mark.parametrize("status", ["unknown", "timed_out", "cancelled", "abandoned"])
def test_uncertain_target_does_not_select_practice_or_retry_context(status: str):
    gateway = ContextRecordingGateway(status, "completed", "completed")
    result = _run(gateway, f"uncertain-{status}", practice=2, targets=3)

    assert result.status == ("unknown" if status == "unknown" else "failed")
    assert len(gateway.calls) == 1
    assert result.practice_episodes == ()
    assert result.target_attempts[0].result.status == status
    assert result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT


def test_invalid_context_status_is_rejected_before_any_retry():
    gateway = ContextRecordingGateway("bogus")
    with pytest.raises((RSILearningError, ValueError)):
        _run(gateway, "invalid-context")
    assert len(gateway.calls) == 1
