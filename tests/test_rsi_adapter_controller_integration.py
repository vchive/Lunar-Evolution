import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT,
    DeterministicCurriculum,
    RSILearningController,
    SolverRequest,
    fixture_solver_gateway,
)

HEX = "a" * 64
SOLVER_IDS = ("mock", "native_population", "openevolve", "shinka")


@pytest.mark.parametrize("status", ["completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"])
def test_provider_free_adapter_preserves_terminal_result_fields(status: str):
    request = SolverRequest.build(
        episode_id=f"adapter-{status}",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=HEX,
        solver_id="openevolve",
    )
    result = fixture_solver_gateway("openevolve", terminal_status=status, provenance={"iteration": 7}).run(request)

    assert result.status == status
    assert result.episode_id == request.episode_id
    assert result.request_sha256 == request.digest()
    assert result.trace_digest
    assert result.terminal_reason == ("fixture_completed" if status == "completed" else f"fixture_{status}")
    assert dict(result.solver_provenance) == {"backend": "openevolve", "fixture": True, "iteration": 7}
    if status == "completed":
        assert result.solver_score == 1.0
        assert result.candidate_receipt_sha256 is not None
        assert result.execution_receipt_sha256 is not None
        assert result.official_evaluation_receipt_sha256 is not None
    else:
        assert result.solver_score is None
        assert result.candidate_receipt_sha256 is None
        assert result.execution_receipt_sha256 is None
        assert result.official_evaluation_receipt_sha256 is None


class SequenceGateway:
    def __init__(self, solver_id: str, *statuses: str) -> None:
        self.delegate = fixture_solver_gateway(solver_id)
        self.statuses = list(statuses)
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        status = self.statuses.pop(0)
        if status == "completed":
            return self.delegate.run(request)
        return fixture_solver_gateway(self.delegate.solver_id, terminal_status=status).run(request)


@pytest.mark.parametrize("solver_id", SOLVER_IDS)
def test_provider_free_backends_run_through_drs_and_verifier_gated_memory(solver_id: str):
    gateway = SequenceGateway(solver_id, "completed", "completed", "completed")
    result = RSILearningController(
        gateway,
        curriculum=DeterministicCurriculum(),
        target_judge=lambda execution: (
            execution.episode.episode_kind == "target" and execution.episode.wave > 0,
            "fixture gap" if execution.episode.wave == 0 else "accepted",
        ),
    ).run_drs(
        run_id=f"integration-{solver_id}",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        solver_id=solver_id,
        max_practice_rounds=1,
        max_target_attempts=2,
    )

    assert result.status == "completed"
    assert len(gateway.requests) == 3
    assert len(result.practice_episodes) == 1
    assert result.practice_episodes[0].passed
    assert len(result.memory_snapshot.items) == 1
    assert result.memory_snapshot.items[0].receipt_sha256 == result.practice_episodes[0].verifier.receipt_sha256
    assert dict(result.practice_episodes[0].result.solver_provenance)["backend"] == solver_id
    assert result.target_attempts[1].episode.memory_snapshot_sha256 == result.memory_snapshot.digest()


@pytest.mark.parametrize("status", ["timed_out", "abandoned", "cancelled"])
@pytest.mark.parametrize("episode_kind", ["target", "practice"])
def test_uncertain_worker_terminal_state_stops_drs_without_memory(status: str, episode_kind: str):
    statuses = (status,) if episode_kind == "target" else ("completed", status)
    gateway = SequenceGateway("mock", *statuses)
    result = RSILearningController(
        gateway,
        target_judge=lambda _execution: (False, "fixture gap"),
    ).run_drs(
        run_id=f"stop-{episode_kind}-{status}",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        solver_id="mock",
        max_practice_rounds=2,
        max_target_attempts=3,
    )

    assert result.status == "failed"
    assert result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT
    assert len(gateway.requests) == len(statuses)
    assert len(result.target_attempts) == 1
    assert len(result.practice_episodes) == (1 if episode_kind == "practice" else 0)
