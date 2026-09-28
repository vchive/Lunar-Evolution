"""Provider-free RSI solver and verifier boundaries.

The production adapters can implement :class:`SolverGateway` later.  The local fixture in this
module is intentionally deterministic so the controller and memory admission rules can be tested
without a model, a remote evaluator, or an OpenEvolve installation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import (
    MemoryItem,
    MemorySnapshot,
    PracticeEpisode,
    RSILearningError,
    TraceEvent,
    VerifierCheck,
    VerifierDecision,
)

MAX_SOLVER_SETTINGS = 32
MAX_SOLVER_BUDGET = 32


def _digest(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise RSILearningError(f"rsi_{name}_invalid")
    return value


def _id(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value or "\n" in value or "\r" in value:
        raise RSILearningError(f"rsi_{name}_invalid")
    return value


def _record_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()


def _bounded_map(value: object, name: str) -> tuple[tuple[str, Any], ...]:
    if not isinstance(value, Mapping) or len(value) > MAX_SOLVER_SETTINGS:
        raise RSILearningError(f"rsi_{name}_invalid")
    result: list[tuple[str, Any]] = []
    for key, item in value.items():
        if type(key) is not str or not key or "\x00" in key:
            raise RSILearningError(f"rsi_{name}_invalid")
        result.append((key, item))
    return tuple(sorted(result))


@dataclass(frozen=True)
class SolverRequest:
    """Immutable launch identity handed to a solver adapter."""

    episode_id: str
    contract_sha256: str
    evaluator_sha256: str
    environment_sha256: str
    memory_snapshot_sha256: str
    solver_id: str
    solver_settings: tuple[tuple[str, Any], ...] = ()
    budget: tuple[tuple[str, Any], ...] = ()
    practice_charter: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        _id(self.episode_id, "episode_id")
        _id(self.solver_id, "solver_id")
        for value, name in (
            (self.contract_sha256, "contract_sha256"),
            (self.evaluator_sha256, "evaluator_sha256"),
            (self.environment_sha256, "environment_sha256"),
            (self.memory_snapshot_sha256, "memory_snapshot_sha256"),
        ):
            _digest(value, name)
        for value, name in (
            (self.solver_settings, "solver_settings"),
            (self.budget, "budget"),
            (self.practice_charter, "practice_charter"),
        ):
            if type(value) is not tuple or len(value) > MAX_SOLVER_BUDGET:
                raise RSILearningError(f"rsi_{name}_invalid")

    @classmethod
    def build(
        cls,
        *,
        episode_id: str,
        contract_sha256: str,
        evaluator_sha256: str,
        environment_sha256: str,
        memory_snapshot_sha256: str,
        solver_id: str,
        solver_settings: Mapping[str, Any] | None = None,
        budget: Mapping[str, Any] | None = None,
        practice_charter: Mapping[str, Any] | None = None,
    ) -> SolverRequest:
        return cls(
            episode_id,
            contract_sha256,
            evaluator_sha256,
            environment_sha256,
            memory_snapshot_sha256,
            solver_id,
            _bounded_map(solver_settings or {}, "solver_settings"),
            _bounded_map(budget or {}, "budget"),
            _bounded_map(practice_charter or {}, "practice_charter"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "kind": "rsi_solver_request",
            "episode_id": self.episode_id,
            "contract_sha256": self.contract_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "solver_id": self.solver_id,
            "solver_settings": dict(self.solver_settings),
            "budget": dict(self.budget),
            "practice_charter": dict(self.practice_charter),
        }

    def digest(self) -> str:
        return _record_digest(self.to_dict())


SolverTerminalStatus = str


@dataclass(frozen=True)
class SolverResult:
    episode_id: str
    request_sha256: str
    status: SolverTerminalStatus
    candidate_receipt_sha256: str | None
    execution_receipt_sha256: str | None
    official_evaluation_receipt_sha256: str | None
    trace_digest: str
    solver_score: float | None = None
    terminal_reason: str = ""
    solver_provenance: tuple[tuple[str, Any], ...] = ()
    candidate_source_sha256: str | None = None
    dependency_sha256: str | None = None
    trace_events: tuple[TraceEvent, ...] = ()
    actor_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _id(self.episode_id, "episode_id")
        _digest(self.request_sha256, "request_sha256")
        if self.status not in {"completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"}:
            raise RSILearningError("rsi_solver_status_invalid")
        for value, name in (
            (self.candidate_receipt_sha256, "candidate_receipt_sha256"),
            (self.execution_receipt_sha256, "execution_receipt_sha256"),
            (self.official_evaluation_receipt_sha256, "official_evaluation_receipt_sha256"),
        ):
            if value is not None:
                _digest(value, name)
        _digest(self.trace_digest, "trace_digest")
        for value, name in (
            (self.candidate_source_sha256, "candidate_source_sha256"),
            (self.dependency_sha256, "dependency_sha256"),
            (self.actor_fingerprint, "actor_fingerprint"),
        ):
            if value is not None:
                _digest(value, name)
        if type(self.trace_events) is not tuple or len(self.trace_events) > 64 or any(
            not isinstance(event, TraceEvent) for event in self.trace_events
        ):
            raise RSILearningError("rsi_trace_events_invalid")
        if type(self.terminal_reason) is not str or len(self.terminal_reason.encode()) > 8192:
            raise RSILearningError("rsi_terminal_reason_invalid")
        if type(self.solver_provenance) is not tuple or len(self.solver_provenance) > MAX_SOLVER_SETTINGS:
            raise RSILearningError("rsi_solver_provenance_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "kind": "rsi_solver_result",
            "episode_id": self.episode_id,
            "request_sha256": self.request_sha256,
            "status": self.status,
            "candidate_receipt_sha256": self.candidate_receipt_sha256,
            "execution_receipt_sha256": self.execution_receipt_sha256,
            "official_evaluation_receipt_sha256": self.official_evaluation_receipt_sha256,
            "trace_digest": self.trace_digest,
            "solver_score": self.solver_score,
            "terminal_reason": self.terminal_reason,
            "solver_provenance": dict(self.solver_provenance),
            "candidate_source_sha256": self.candidate_source_sha256,
            "dependency_sha256": self.dependency_sha256,
            "trace_events": [event.to_dict() for event in self.trace_events],
            "actor_fingerprint": self.actor_fingerprint,
        }


class SolverGateway(Protocol):
    def run(self, request: SolverRequest) -> SolverResult:
        """Run one immutable request and persist its result before returning."""


class DeterministicMockSolver:
    """A deterministic fixture that simulates a successful or terminal worker."""

    def __init__(self, *, terminal_status: str = "completed") -> None:
        if terminal_status not in {"completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"}:
            raise ValueError("invalid terminal status")
        self.terminal_status = terminal_status

    def run(self, request: SolverRequest) -> SolverResult:
        request_digest = request.digest()
        seed = lambda label: hashlib.sha256(f"{label}:{request_digest}".encode()).hexdigest()
        completed = self.terminal_status == "completed"
        return SolverResult(
            request.episode_id,
            request_digest,
            self.terminal_status,
            seed("candidate") if completed else None,
            seed("execution") if completed else None,
            seed("evaluation") if completed else None,
            seed("trace"),
            1.0 if completed else None,
            "mock_completed" if completed else f"mock_{self.terminal_status}",
            candidate_source_sha256=seed("candidate-source") if completed else None,
            dependency_sha256=seed("dependencies") if completed else None,
        )


class LocalExactVerifier:
    """Verifier fixture: only a completed result with all receipts can pass."""

    def verify(self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult) -> VerifierDecision:
        checks: list[VerifierCheck] = []
        evidence = {
            "candidate_receipt_sha256": result.candidate_receipt_sha256,
            "execution_receipt_sha256": result.execution_receipt_sha256,
            "official_evaluation_receipt_sha256": result.official_evaluation_receipt_sha256,
            "trace_digest": result.trace_digest,
        }
        evidence_sha256 = _record_digest(evidence)
        if result.episode_id != episode.episode_id or result.request_sha256 != request.digest():
            outcome = "unresolved"
            diagnosis = "request identity mismatch"
            checks.append(VerifierCheck("request_identity", "fail", _record_digest({"check": "identity", "episode": episode.episode_id})))
        elif result.status != "completed":
            outcome = "unresolved"
            diagnosis = f"solver terminal status: {result.status}"
            checks.append(VerifierCheck("terminal_status", "unresolved", _record_digest({"check": "terminal", "status": result.status})))
        elif any(value is None for value in (
            result.candidate_receipt_sha256,
            result.execution_receipt_sha256,
            result.official_evaluation_receipt_sha256,
        )):
            outcome = "unresolved"
            diagnosis = "required receipt missing"
            checks.append(VerifierCheck("receipts", "unresolved", _record_digest({"check": "receipts", "episode": episode.episode_id})))
        else:
            outcome = "pass"
            diagnosis = "deterministic exact checks passed"
            checks.extend(
                (
                    VerifierCheck("candidate_receipt", "pass", result.candidate_receipt_sha256),
                    VerifierCheck("execution_receipt", "pass", result.execution_receipt_sha256),
                    VerifierCheck("official_evaluator", "pass", result.official_evaluation_receipt_sha256),
                )
            )
        receipt = _record_digest({"episode": episode.episode_id, "result": result.to_dict(), "outcome": outcome})
        fingerprint = _record_digest({"verifier": "local-exact-v1"})
        return VerifierDecision(
            episode.episode_id,
            outcome,
            receipt,
            diagnosis,
            fingerprint,
            tuple(checks),
            contract_sha256=episode.contract_sha256,
            evaluator_sha256=episode.evaluator_sha256,
            environment_sha256=episode.environment_sha256,
            official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
            evidence_sha256=evidence_sha256,
            candidate_receipt_sha256=result.candidate_receipt_sha256,
            execution_receipt_sha256=result.execution_receipt_sha256,
        )


class RSIMemoryStore:
    """Small compare-and-swap store used by local tests and future durable implementations."""

    def __init__(self, snapshot: MemorySnapshot) -> None:
        self._snapshot = snapshot

    @property
    def snapshot(self) -> MemorySnapshot:
        return self._snapshot

    def commit(
        self,
        *,
        parent_snapshot_sha256: str,
        episode: PracticeEpisode,
        decision: VerifierDecision,
        memory: MemoryItem,
        expected_episode_snapshot_sha256: str | None = None,
        source_snapshot_sha256: str | None = None,
    ) -> MemorySnapshot:
        if parent_snapshot_sha256 != self._snapshot.digest():
            raise RSILearningError("rsi_memory_parent_conflict")
        expected_episode_snapshot = expected_episode_snapshot_sha256 or parent_snapshot_sha256
        _digest(expected_episode_snapshot, "expected_episode_snapshot_sha256")
        if source_snapshot_sha256 is not None:
            _digest(source_snapshot_sha256, "source_snapshot_sha256")
            if episode.memory_snapshot_sha256 != source_snapshot_sha256:
                raise RSILearningError("rsi_memory_source_snapshot_mismatch")
        if episode.memory_snapshot_sha256 != expected_episode_snapshot:
            raise RSILearningError("rsi_memory_episode_snapshot_mismatch")
        if (
            episode.status != "completed"
            or episode.verifier != decision
            or decision.episode_id != episode.episode_id
            or decision.outcome != "pass"
            or not decision.independent_of_actor
            or any(check.outcome != "pass" for check in decision.checks)
        ):
            raise RSILearningError("rsi_memory_commit_not_approved")
        if any(
            value is None
            for value in (
                episode.candidate_receipt_sha256,
                episode.execution_receipt_sha256,
                episode.official_evaluation_receipt_sha256,
            )
        ):
            raise RSILearningError("rsi_memory_commit_evidence_missing")
        if (
            decision.contract_sha256 != episode.contract_sha256
            or decision.evaluator_sha256 != episode.evaluator_sha256
            or decision.environment_sha256 != episode.environment_sha256
            or decision.official_evaluation_receipt_sha256
            != episode.official_evaluation_receipt_sha256
        ):
            raise RSILearningError("rsi_memory_commit_pin_mismatch")
        if (
            memory.episode_id != episode.episode_id
            or memory.receipt_sha256 != decision.receipt_sha256
            or memory.status != "approved"
            or memory.verifier_outcome != "pass"
            or episode.solver_id not in memory.compatible_solvers
            or (
                memory.compatible_contracts
                and episode.contract_sha256 not in memory.compatible_contracts
            )
        ):
            raise RSILearningError("rsi_memory_commit_evidence_mismatch")
        self._snapshot = MemorySnapshot(
            f"snapshot-{memory.memory_id}", self._snapshot.digest(), self._snapshot.items + (memory,)
        )
        return self._snapshot


__all__ = [
    "DeterministicMockSolver",
    "LocalExactVerifier",
    "RSIMemoryStore",
    "SolverGateway",
    "SolverRequest",
    "SolverResult",
]
