"""Strict, provider-free candidate and receipt seam for the native RSI gateway.

The native process and population publication layers produce evidence, but neither layer is
allowed to turn a producer declaration into a ``SolverResult``.  This module is the small
control-plane boundary between those layers.  It selects exactly one request-bound candidate and
maps four independently retained records (candidate, execution, evaluation and publication) to
the existing immutable ``SolverResult``.  It deliberately does not read files, start a process,
run an evaluator, or write RSI memory.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_learning import RSILearningError

_HEX = frozenset("0123456789abcdef")
_CANDIDATE_STATES = frozenset({"admitted", "rejected", "unknown"})
_EXECUTION_STATES = frozenset({"completed", "failed", "timed_out", "cancelled", "abandoned", "unknown"})
_EVALUATION_STATES = frozenset({"pass", "fail", "unresolved"})
_PUBLICATION_STATES = frozenset({"published", "rejected", "unknown"})


def _digest(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in _HEX for char in value):
        raise RSILearningError(f"rsi_native_{name}_invalid")
    return value


def _id(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or any(char in value for char in "\x00\r\n"):
        raise RSILearningError(f"rsi_native_{name}_invalid")
    return value


def _record_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()


def _wire(value: object, *, kind: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "kind", *fields}:
        raise RSILearningError("rsi_native_receipt_wire_invalid")
    if value.get("schema_version") != "1" or value.get("kind") != kind:
        raise RSILearningError("rsi_native_receipt_wire_invalid")
    try:
        encoded = canonical_json(value, maximum=128 * 1024)
    except Exception as exc:  # canonical_json intentionally exposes only fixed errors
        raise RSILearningError("rsi_native_receipt_wire_invalid") from exc
    # A canonical round-trip catches non-string keys, mutable oddities and non-JSON values while
    # retaining the strict duplicate-key behaviour of the existing RSI wire helpers.
    if encoded != canonical_json(value, maximum=128 * 1024):
        raise RSILearningError("rsi_native_receipt_wire_invalid")
    return value


def _binding_fields(value: object, *, name: str) -> tuple[str, str, str, str, str]:
    if not isinstance(value, tuple) or len(value) != 5:
        raise RSILearningError(f"rsi_native_{name}_binding_invalid")
    for item, field in zip(value, ("request_sha256", "contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256")):
        _digest(item, field)
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class NativeCandidateRecord:
    """One retained candidate admission record, already bound to the RSI request pins."""

    candidate_id: str
    request_sha256: str
    contract_sha256: str
    evaluator_sha256: str
    environment_sha256: str
    memory_snapshot_sha256: str
    candidate_receipt_sha256: str
    candidate_source_sha256: str
    state: str = "admitted"

    def __post_init__(self) -> None:
        _id(self.candidate_id, "candidate_id")
        for value, name in (
            (self.request_sha256, "request_sha256"),
            (self.contract_sha256, "contract_sha256"),
            (self.evaluator_sha256, "evaluator_sha256"),
            (self.environment_sha256, "environment_sha256"),
            (self.memory_snapshot_sha256, "memory_snapshot_sha256"),
            (self.candidate_receipt_sha256, "candidate_receipt_sha256"),
            (self.candidate_source_sha256, "candidate_source_sha256"),
        ):
            _digest(value, name)
        if type(self.state) is not str or self.state not in _CANDIDATE_STATES:
            raise RSILearningError("rsi_native_candidate_state_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1", "kind": "rsi_native_candidate",
            "candidate_id": self.candidate_id, "request_sha256": self.request_sha256,
            "contract_sha256": self.contract_sha256, "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "candidate_receipt_sha256": self.candidate_receipt_sha256,
            "candidate_source_sha256": self.candidate_source_sha256, "state": self.state,
        }

    def digest(self) -> str:
        return _record_digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> NativeCandidateRecord:
        fields = {
            "candidate_id", "request_sha256", "contract_sha256", "evaluator_sha256",
            "environment_sha256", "memory_snapshot_sha256", "candidate_receipt_sha256",
            "candidate_source_sha256", "state",
        }
        payload = _wire(value, kind="rsi_native_candidate", fields=fields)
        try:
            return cls(**{field: payload[field] for field in fields})
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            if isinstance(exc, RSILearningError):
                raise
            raise RSILearningError("rsi_native_candidate_invalid") from exc


@dataclass(frozen=True, slots=True)
class NativeExecutionReceipt:
    """Formal execution evidence for the selected candidate."""

    candidate_id: str
    request_sha256: str
    contract_sha256: str
    evaluator_sha256: str
    environment_sha256: str
    memory_snapshot_sha256: str
    receipt_sha256: str
    trace_digest: str
    status: str = "completed"

    def __post_init__(self) -> None:
        _id(self.candidate_id, "candidate_id")
        for value, name in (
            (self.request_sha256, "request_sha256"),
            (self.contract_sha256, "contract_sha256"),
            (self.evaluator_sha256, "evaluator_sha256"),
            (self.environment_sha256, "environment_sha256"),
            (self.memory_snapshot_sha256, "memory_snapshot_sha256"),
            (self.receipt_sha256, "execution_receipt_sha256"),
            (self.trace_digest, "trace_digest"),
        ):
            _digest(value, name)
        if type(self.status) is not str or self.status not in _EXECUTION_STATES:
            raise RSILearningError("rsi_native_execution_status_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1", "kind": "rsi_native_execution_receipt",
            "candidate_id": self.candidate_id, "request_sha256": self.request_sha256,
            "contract_sha256": self.contract_sha256, "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "receipt_sha256": self.receipt_sha256, "trace_digest": self.trace_digest,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: object) -> NativeExecutionReceipt:
        fields = {
            "candidate_id", "request_sha256", "contract_sha256", "evaluator_sha256",
            "environment_sha256", "memory_snapshot_sha256", "receipt_sha256", "trace_digest", "status",
        }
        payload = _wire(value, kind="rsi_native_execution_receipt", fields=fields)
        try:
            return cls(**{field: payload[field] for field in fields})
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            if isinstance(exc, RSILearningError):
                raise
            raise RSILearningError("rsi_native_execution_receipt_invalid") from exc


@dataclass(frozen=True, slots=True)
class NativeEvaluationReceipt:
    """Independent evaluator evidence; producer-declared scores cannot satisfy this DTO."""

    candidate_id: str
    request_sha256: str
    contract_sha256: str
    evaluator_sha256: str
    environment_sha256: str
    memory_snapshot_sha256: str
    receipt_sha256: str
    outcome: str = "pass"

    def __post_init__(self) -> None:
        _id(self.candidate_id, "candidate_id")
        for value, name in (
            (self.request_sha256, "request_sha256"),
            (self.contract_sha256, "contract_sha256"),
            (self.evaluator_sha256, "evaluator_sha256"),
            (self.environment_sha256, "environment_sha256"),
            (self.memory_snapshot_sha256, "memory_snapshot_sha256"),
            (self.receipt_sha256, "evaluation_receipt_sha256"),
        ):
            _digest(value, name)
        if type(self.outcome) is not str or self.outcome not in _EVALUATION_STATES:
            raise RSILearningError("rsi_native_evaluation_outcome_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1", "kind": "rsi_native_evaluation_receipt",
            "candidate_id": self.candidate_id, "request_sha256": self.request_sha256,
            "contract_sha256": self.contract_sha256, "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "receipt_sha256": self.receipt_sha256, "outcome": self.outcome,
        }

    @classmethod
    def from_dict(cls, value: object) -> NativeEvaluationReceipt:
        fields = {
            "candidate_id", "request_sha256", "contract_sha256", "evaluator_sha256",
            "environment_sha256", "memory_snapshot_sha256", "receipt_sha256", "outcome",
        }
        payload = _wire(value, kind="rsi_native_evaluation_receipt", fields=fields)
        try:
            return cls(**{field: payload[field] for field in fields})
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            if isinstance(exc, RSILearningError):
                raise
            raise RSILearningError("rsi_native_evaluation_receipt_invalid") from exc


@dataclass(frozen=True, slots=True)
class NativePublicationReceipt:
    """Durable candidate publication evidence, independent from evaluator outcome."""

    candidate_id: str
    request_sha256: str
    contract_sha256: str
    evaluator_sha256: str
    environment_sha256: str
    memory_snapshot_sha256: str
    receipt_sha256: str
    status: str = "published"

    def __post_init__(self) -> None:
        _id(self.candidate_id, "candidate_id")
        for value, name in (
            (self.request_sha256, "request_sha256"),
            (self.contract_sha256, "contract_sha256"),
            (self.evaluator_sha256, "evaluator_sha256"),
            (self.environment_sha256, "environment_sha256"),
            (self.memory_snapshot_sha256, "memory_snapshot_sha256"),
            (self.receipt_sha256, "publication_receipt_sha256"),
        ):
            _digest(value, name)
        if type(self.status) is not str or self.status not in _PUBLICATION_STATES:
            raise RSILearningError("rsi_native_publication_status_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1", "kind": "rsi_native_publication_receipt",
            "candidate_id": self.candidate_id, "request_sha256": self.request_sha256,
            "contract_sha256": self.contract_sha256, "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "receipt_sha256": self.receipt_sha256, "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: object) -> NativePublicationReceipt:
        fields = {
            "candidate_id", "request_sha256", "contract_sha256", "evaluator_sha256",
            "environment_sha256", "memory_snapshot_sha256", "receipt_sha256", "status",
        }
        payload = _wire(value, kind="rsi_native_publication_receipt", fields=fields)
        try:
            return cls(**{field: payload[field] for field in fields})
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            if isinstance(exc, RSILearningError):
                raise
            raise RSILearningError("rsi_native_publication_receipt_invalid") from exc


@dataclass(frozen=True, slots=True)
class NativeCandidateSelection:
    """The unique selected candidate and its selection evidence digest."""

    candidate: NativeCandidateRecord
    selection_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, NativeCandidateRecord) or self.candidate.state != "admitted":
            raise RSILearningError("rsi_native_candidate_not_admitted")
        _digest(self.selection_sha256, "selection_sha256")


class NativeCandidateContractError(RSILearningError):
    """A fixed-code candidate/evidence contract refusal."""


def _request_binding(request: SolverRequest) -> tuple[str, str, str, str, str]:
    return (
        request.digest(), request.contract_sha256, request.evaluator_sha256,
        request.environment_sha256, request.memory_snapshot_sha256,
    )


def _check_binding(request: SolverRequest, candidate_id: str, evidence: object) -> None:
    if not isinstance(request, SolverRequest):
        raise NativeCandidateContractError("rsi_native_request_invalid")
    if not isinstance(evidence, (NativeCandidateRecord, NativeExecutionReceipt, NativeEvaluationReceipt, NativePublicationReceipt)):
        raise NativeCandidateContractError("rsi_native_receipt_invalid")
    expected = _request_binding(request)
    actual = (
        evidence.request_sha256, evidence.contract_sha256, evidence.evaluator_sha256,
        evidence.environment_sha256, evidence.memory_snapshot_sha256,
    )
    if actual != expected:
        raise NativeCandidateContractError("rsi_native_receipt_binding_mismatch")
    if isinstance(evidence, (NativeExecutionReceipt, NativeEvaluationReceipt, NativePublicationReceipt)):
        _id(evidence.candidate_id, "candidate_id")


def select_native_candidate(
    request: SolverRequest,
    candidates: Sequence[NativeCandidateRecord],
) -> NativeCandidateSelection:
    """Select exactly one request-bound admitted candidate.

    Rejected/unknown candidates are retained as evidence but never selected.  Any candidate with
    a duplicate ID or drifted request pins fails closed; an empty admitted set and multiple
    admitted candidates have distinct fixed refusal codes for recovery diagnostics.
    """

    if not isinstance(request, SolverRequest):
        raise NativeCandidateContractError("rsi_native_request_invalid")
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise NativeCandidateContractError("rsi_native_candidates_invalid")
    seen: set[str] = set()
    admitted: list[NativeCandidateRecord] = []
    for candidate in candidates:
        if not isinstance(candidate, NativeCandidateRecord):
            raise NativeCandidateContractError("rsi_native_candidate_invalid")
        if candidate.candidate_id in seen:
            raise NativeCandidateContractError("rsi_native_candidate_duplicate")
        seen.add(candidate.candidate_id)
        _check_binding(request, candidate.candidate_id, candidate)
        if candidate.state == "admitted":
            admitted.append(candidate)
    if len(admitted) == 0:
        raise NativeCandidateContractError("rsi_native_candidate_none_admitted")
    if len(admitted) != 1:
        raise NativeCandidateContractError("rsi_native_candidate_multiple_admitted")
    candidate = admitted[0]
    selection_sha256 = _record_digest({"request_sha256": request.digest(), "candidate": candidate.to_dict()})
    return NativeCandidateSelection(candidate, selection_sha256)


def map_native_receipts_to_solver_result(
    request: SolverRequest,
    selection: NativeCandidateSelection,
    execution: NativeExecutionReceipt,
    evaluation: NativeEvaluationReceipt,
    publication: NativePublicationReceipt,
) -> SolverResult:
    """Map complete, independently bound native receipts to a successful ``SolverResult``.

    A terminal receipt, output envelope, producer score, or all-rejected publication result is
    insufficient.  Missing or non-success evidence returns a fixed refusal and never fabricates
    a failed/successful solver result.
    """

    if not isinstance(selection, NativeCandidateSelection):
        raise NativeCandidateContractError("rsi_native_selection_invalid")
    candidate = selection.candidate
    _check_binding(request, candidate.candidate_id, candidate)
    for evidence in (execution, evaluation, publication):
        _check_binding(request, candidate.candidate_id, evidence)
        if evidence.candidate_id != candidate.candidate_id:
            raise NativeCandidateContractError("rsi_native_receipt_candidate_mismatch")
    if candidate.state != "admitted":
        raise NativeCandidateContractError("rsi_native_candidate_not_admitted")
    if execution.status != "completed":
        raise NativeCandidateContractError("rsi_native_execution_incomplete")
    if evaluation.outcome != "pass":
        raise NativeCandidateContractError("rsi_native_evaluation_not_passed")
    if publication.status != "published":
        raise NativeCandidateContractError("rsi_native_publication_incomplete")
    if execution.trace_digest is None:
        raise NativeCandidateContractError("rsi_native_trace_missing")
    return SolverResult(
        episode_id=request.episode_id,
        request_sha256=request.digest(),
        status="completed",
        candidate_receipt_sha256=candidate.candidate_receipt_sha256,
        execution_receipt_sha256=execution.receipt_sha256,
        official_evaluation_receipt_sha256=evaluation.receipt_sha256,
        trace_digest=execution.trace_digest,
        solver_provenance=(
            ("candidate_id", candidate.candidate_id),
            ("publication_receipt_sha256", publication.receipt_sha256),
            ("selection_sha256", selection.selection_sha256),
        ),
        candidate_source_sha256=candidate.candidate_source_sha256,
    )


__all__ = [
    "NativeCandidateContractError", "NativeCandidateRecord", "NativeCandidateSelection",
    "NativeEvaluationReceipt", "NativeExecutionReceipt", "NativePublicationReceipt",
    "map_native_receipts_to_solver_result", "select_native_candidate",
]
