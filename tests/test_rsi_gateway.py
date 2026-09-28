import hashlib
from dataclasses import replace

import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT,
    DeterministicMockSolver,
    LocalExactVerifier,
    RSILearningError,
    RSIMemoryItem,
    RSIMemoryStore,
    RSIPracticeEpisode,
    SolverRequest,
    SolverResult,
    fixture_solver_gateway,
)

HEX = "a" * 64


class ScriptedGateway:
    """Provider-free sequence fixture for controller state-machine tests."""

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


def request() -> SolverRequest:
    return SolverRequest.build(
        episode_id="episode-1",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="mock",
        budget={"candidate_attempts": 1},
    )


def episode(status="completed", verifier=None) -> RSIPracticeEpisode:
    return RSIPracticeEpisode(
        episode_id="episode-1",
        run_id="run-1",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="mock",
        status=status,
        verifier=verifier,
        candidate_receipt_sha256=HEX if status == "completed" else None,
        execution_receipt_sha256=HEX if status == "completed" else None,
        official_evaluation_receipt_sha256=HEX if status == "completed" else None,
    )


def test_mock_solver_and_verifier_gate_memory_commit():
    req = request()
    result = DeterministicMockSolver().run(req)
    verified_episode = replace(
        episode(),
        candidate_receipt_sha256=result.candidate_receipt_sha256,
        execution_receipt_sha256=result.execution_receipt_sha256,
        official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
    )
    decision = LocalExactVerifier().verify(verified_episode, req, result)
    completed = replace(verified_episode, verifier=decision)
    assert decision.outcome == "pass"

    item = RSIMemoryItem(
        memory_id="memory-1",
        problem_family="sorting",
        trigger="duplicate-heavy input",
        strategy="stable partition",
        expected_result="stable output",
        failure_boundary="unconstrained output order",
        compatible_contracts=(HEX,),
        compatible_solvers=("mock",),
        verifier_outcome="pass",
        receipt_sha256=decision.receipt_sha256,
        episode_id="episode-1",
    )
    store = RSIMemoryStore(EMPTY_MEMORY_SNAPSHOT)
    snapshot = store.commit(
        parent_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        episode=completed,
        decision=decision,
        memory=item,
    )
    assert snapshot.items == (item,)


def test_terminal_solver_cannot_become_approved_memory():
    req = request()
    result = DeterministicMockSolver(terminal_status="unknown").run(req)
    decision = LocalExactVerifier().verify(episode(), req, result)
    assert decision.outcome == "unresolved"


@pytest.mark.parametrize("solver_id", ["native_population", "openevolve", "shinka"])
def test_provider_free_solver_fixtures_preserve_backend_provenance(solver_id: str):
    req = request()
    req = replace(req, solver_id=solver_id)
    result = fixture_solver_gateway(solver_id, provenance={"iteration": 2}).run(req)
    assert result.status == "completed"
    assert dict(result.solver_provenance) == {"backend": solver_id, "fixture": True, "iteration": 2}
    assert result.to_dict()["solver_provenance"]["backend"] == solver_id


def test_memory_commit_rejects_episode_from_a_different_frozen_parent():
    req = request()
    result = DeterministicMockSolver().run(req)
    verified_episode = replace(
        episode(),
        candidate_receipt_sha256=result.candidate_receipt_sha256,
        execution_receipt_sha256=result.execution_receipt_sha256,
        official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
    )
    decision = LocalExactVerifier().verify(verified_episode, req, result)
    completed = replace(verified_episode, verifier=decision, memory_snapshot_sha256=HEX)
    item = RSIMemoryItem(
        memory_id="memory-parent-mismatch",
        problem_family="sorting",
        trigger="duplicate-heavy input",
        strategy="stable partition",
        expected_result="stable output",
        failure_boundary="unconstrained output order",
        compatible_contracts=(HEX,),
        compatible_solvers=("mock",),
        verifier_outcome="pass",
        receipt_sha256=decision.receipt_sha256,
        episode_id="episode-1",
    )
    with pytest.raises(RSILearningError) as error:
        RSIMemoryStore(EMPTY_MEMORY_SNAPSHOT).commit(
            parent_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
            episode=completed,
            decision=decision,
            memory=item,
        )
    assert error.value.code == "rsi_memory_episode_snapshot_mismatch"


def test_solver_request_result_durable_round_trip():
    from lunar_evolution.rsi_learning import TraceEvent

    req = replace(request(), practice_charter=(("steps", ["read", "write"]),))
    assert SolverRequest.from_dict(req.to_dict()) == req
    result = replace(DeterministicMockSolver().run(req), trace_events=(TraceEvent(0, "action", "execute", HEX),))
    assert SolverResult.from_dict(result.to_dict()) == result


@pytest.mark.parametrize("field,value", [("schema_version", "2"), ("kind", "other"), ("budget", [])])
def test_solver_request_reopen_rejects_schema_drift(field, value):
    data = request().to_dict()
    data[field] = value
    with pytest.raises(RSILearningError):
        SolverRequest.from_dict(data)


@pytest.mark.parametrize("field,value", [("schema_version", "2"), ("kind", "other"), ("trace_events", [{}]), ("solver_score", float("nan")), ("solver_provenance", [])])
def test_solver_result_reopen_rejects_invalid_evidence(field, value):
    data = DeterministicMockSolver().run(request()).to_dict()
    data[field] = value
    with pytest.raises(RSILearningError):
        SolverResult.from_dict(data)


@pytest.mark.parametrize("provenance", [(("backend", "native_population"),), (("actor", "agent-loop"),), (("backend", "shinka"), ("fixture", False))])
def test_fixture_verifier_rejects_real_backend_receipts(provenance):
    req = request()
    result = replace(DeterministicMockSolver().run(req), solver_provenance=provenance)
    decision = LocalExactVerifier().verify(episode(), req, result)
    assert decision.outcome == "unresolved"
    assert decision.checks[0].name == "independent_verifier_required"
