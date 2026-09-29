from __future__ import annotations

import hashlib

import pytest

from lunar_evolution.rsi_gateway import DeterministicMockSolver, SolverRequest, SolverResult
from lunar_evolution.rsi_learning import RSILearningError, TraceEvent

HEX = "a" * 64


def _request() -> SolverRequest:
    return SolverRequest.build(
        episode_id="wire-episode",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=HEX,
        solver_id="fixture",
        solver_settings={"iterations": 2, "seed": 9},
        budget={"candidate_attempts": 3},
        practice_charter={"goal": "wire roundtrip"},
    )


def test_solver_request_wire_roundtrip_preserves_digest_and_all_fields() -> None:
    request = _request()
    loaded = SolverRequest.from_dict(request.to_dict())
    assert loaded == request
    assert loaded.to_dict() == request.to_dict()
    assert loaded.digest() == request.digest()


@pytest.mark.parametrize("mutation", [
    lambda payload: payload.update(extra=1),
    lambda payload: payload.pop("budget"),
    lambda payload: payload.update(kind="wrong"),
    lambda payload: payload.update(schema_version=2),
    lambda payload: payload.update(solver_settings=[]),
])
def test_solver_request_wire_rejects_schema_and_shape_drift(mutation) -> None:
    payload = _request().to_dict()
    mutation(payload)
    with pytest.raises(RSILearningError, match="rsi_wire_record|rsi_solver_request|rsi_solver_settings"):
        SolverRequest.from_dict(payload)


def test_solver_result_wire_roundtrip_preserves_trace_and_provenance() -> None:
    request = _request()
    digest = lambda label: hashlib.sha256(f"{label}:{request.digest()}".encode()).hexdigest()
    result = SolverResult(
        episode_id=request.episode_id,
        request_sha256=request.digest(),
        status="completed",
        candidate_receipt_sha256=digest("candidate"),
        execution_receipt_sha256=digest("execution"),
        official_evaluation_receipt_sha256=digest("evaluation"),
        trace_digest=digest("trace"),
        solver_score=0.75,
        terminal_reason="wire_complete",
        solver_provenance=(("backend", "fixture"), ("iteration", 2)),
        candidate_source_sha256=digest("source"),
        dependency_sha256=digest("deps"),
        trace_events=(TraceEvent(0, "tool", "write", digest("payload"), digest("observation")),),
        actor_fingerprint=digest("actor"),
    )
    loaded = SolverResult.from_dict(result.to_dict())
    assert loaded == result
    assert loaded.to_dict() == result.to_dict()
    assert loaded.trace_events == result.trace_events
    assert loaded.solver_provenance == result.solver_provenance


@pytest.mark.parametrize("mutation", [
    lambda payload: payload.update(extra=1),
    lambda payload: payload.pop("trace_events"),
    lambda payload: payload.update(trace_events=[{"sequence": 0}]),
    lambda payload: payload.update(solver_provenance=[]),
    lambda payload: payload.update(solver_score=float("nan")),
])
def test_solver_result_wire_rejects_tampering(mutation) -> None:
    result = DeterministicMockSolver().run(_request())
    payload = result.to_dict()
    mutation(payload)
    with pytest.raises((RSILearningError, ValueError), match="rsi_"):
        SolverResult.from_dict(payload)
