from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native_candidate import (
    NativeCandidateContractError,
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
    map_native_receipts_to_solver_result,
    select_native_candidate,
)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def request() -> SolverRequest:
    return SolverRequest.build(
        episode_id="native-candidate-episode",
        contract_sha256=digest("contract"),
        evaluator_sha256=digest("evaluator"),
        environment_sha256=digest("environment"),
        memory_snapshot_sha256=digest("memory"),
        solver_id="native_population",
        budget={"candidate_attempts": 1},
    )


def candidate(solver_request: SolverRequest, *, state: str = "admitted", suffix: str = "one") -> NativeCandidateRecord:
    return NativeCandidateRecord(
        candidate_id=f"candidate-{suffix}",
        request_sha256=solver_request.digest(),
        contract_sha256=solver_request.contract_sha256,
        evaluator_sha256=solver_request.evaluator_sha256,
        environment_sha256=solver_request.environment_sha256,
        memory_snapshot_sha256=solver_request.memory_snapshot_sha256,
        candidate_receipt_sha256=digest(f"candidate-receipt-{suffix}"),
        candidate_source_sha256=digest(f"candidate-source-{suffix}"),
        state=state,
    )


def receipts(solver_request: SolverRequest, selected: NativeCandidateRecord):
    common = {
        "candidate_id": selected.candidate_id,
        "request_sha256": solver_request.digest(),
        "contract_sha256": solver_request.contract_sha256,
        "evaluator_sha256": solver_request.evaluator_sha256,
        "environment_sha256": solver_request.environment_sha256,
        "memory_snapshot_sha256": solver_request.memory_snapshot_sha256,
    }
    return (
        NativeExecutionReceipt(**common, receipt_sha256=digest("execution"), trace_digest=digest("trace")),
        NativeEvaluationReceipt(**common, receipt_sha256=digest("evaluation")),
        NativePublicationReceipt(**common, receipt_sha256=digest("publication")),
    )


def test_selector_requires_one_request_bound_admitted_candidate() -> None:
    solver_request = request()
    selection = select_native_candidate(solver_request, [candidate(solver_request), candidate(solver_request, state="rejected", suffix="rejected")])
    assert selection.candidate.candidate_id == "candidate-one"
    assert len(selection.selection_sha256) == 64


@pytest.mark.parametrize(
    ("records", "code"),
    [
        ([], "rsi_native_candidate_none_admitted"),
        (["unknown"], "rsi_native_candidate_none_admitted"),
        (["two", "three"], "rsi_native_candidate_multiple_admitted"),
    ],
)
def test_selector_refuses_ambiguous_or_missing_admission(records: list[str], code: str) -> None:
    solver_request = request()
    values = []
    for item in records:
        if item == "unknown":
            values.append(candidate(solver_request, state="unknown"))
        else:
            values.append(candidate(solver_request, suffix=item))
    with pytest.raises(NativeCandidateContractError, match=code):
        select_native_candidate(solver_request, values)


def test_selector_refuses_duplicate_and_drifted_candidates() -> None:
    solver_request = request()
    first = candidate(solver_request)
    with pytest.raises(NativeCandidateContractError, match="candidate_duplicate"):
        select_native_candidate(solver_request, [first, first])
    drifted = replace(candidate(solver_request), memory_snapshot_sha256=digest("other-memory"))
    with pytest.raises(NativeCandidateContractError, match="receipt_binding_mismatch"):
        select_native_candidate(solver_request, [drifted])


def test_complete_bound_receipts_map_to_solver_result() -> None:
    solver_request = request()
    selected = select_native_candidate(solver_request, [candidate(solver_request)])
    execution, evaluation, publication = receipts(solver_request, selected.candidate)
    result = map_native_receipts_to_solver_result(solver_request, selected, execution, evaluation, publication)
    assert result.status == "completed"
    assert result.episode_id == solver_request.episode_id
    assert result.request_sha256 == solver_request.digest()
    assert result.candidate_receipt_sha256 == selected.candidate.candidate_receipt_sha256
    assert result.execution_receipt_sha256 == execution.receipt_sha256
    assert result.official_evaluation_receipt_sha256 == evaluation.receipt_sha256
    assert result.trace_digest == execution.trace_digest
    assert dict(result.solver_provenance)["publication_receipt_sha256"] == publication.receipt_sha256


@pytest.mark.parametrize(
    ("which", "code"),
    [
        ("execution", "rsi_native_execution_incomplete"),
        ("evaluation", "rsi_native_evaluation_not_passed"),
        ("publication", "rsi_native_publication_incomplete"),
    ],
)
def test_receipt_mapping_refuses_incomplete_evidence(which: str, code: str) -> None:
    solver_request = request()
    selected = select_native_candidate(solver_request, [candidate(solver_request)])
    execution, evaluation, publication = receipts(solver_request, selected.candidate)
    if which == "execution":
        execution = replace(execution, status="unknown")
    elif which == "evaluation":
        evaluation = replace(evaluation, outcome="unresolved")
    else:
        publication = replace(publication, status="unknown")
    with pytest.raises(NativeCandidateContractError, match=code):
        map_native_receipts_to_solver_result(solver_request, selected, execution, evaluation, publication)


def test_receipt_mapping_refuses_candidate_or_receipt_drift() -> None:
    solver_request = request()
    selected = select_native_candidate(solver_request, [candidate(solver_request)])
    execution, evaluation, publication = receipts(solver_request, selected.candidate)
    drifted = replace(evaluation, memory_snapshot_sha256=digest("drifted-memory"))
    with pytest.raises(NativeCandidateContractError, match="receipt_binding_mismatch"):
        map_native_receipts_to_solver_result(solver_request, selected, execution, drifted, publication)


def test_wire_dto_round_trips_and_rejects_extra_fields() -> None:
    solver_request = request()
    value = candidate(solver_request)
    assert NativeCandidateRecord.from_dict(value.to_dict()) == value
    malformed = {**value.to_dict(), "unexpected": True}
    with pytest.raises(RSILearningError, match="wire_invalid"):
        NativeCandidateRecord.from_dict(malformed)
