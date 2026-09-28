"""Provider-free solver gateway fixtures for RSI integration tests.

The real OpenEvolve, ShinkaEvolve and native population processes remain optional external
backends.  These adapters exercise the same immutable gateway boundary locally and preserve
backend identity as provenance without treating a solver score as verifier authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_learning import RSILearningError

SUPPORTED_FIXTURE_SOLVERS = frozenset({"mock", "native_population", "openevolve", "shinka"})


def _digest(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RSILearningError(f"rsi_{name}_invalid")
    return value


def _record_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()


@dataclass(frozen=True)
class ProviderFreeSolverGateway:
    """Deterministic stand-in for one registered solver backend."""

    solver_id: str
    terminal_status: str = "completed"
    provenance: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.solver_id not in SUPPORTED_FIXTURE_SOLVERS:
            raise RSILearningError("rsi_fixture_solver_invalid")
        if self.terminal_status not in {"completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"}:
            raise RSILearningError("rsi_fixture_solver_status_invalid")
        if type(self.provenance) is not tuple or len(self.provenance) > 32:
            raise RSILearningError("rsi_fixture_solver_provenance_invalid")

    def fingerprint(self) -> str:
        return _record_digest({"protocol": "rsi-provider-free-v1", "solver_id": self.solver_id,
                               "terminal_status": self.terminal_status, "provenance": dict(self.provenance)})

    def run(self, request: SolverRequest) -> SolverResult:
        if request.solver_id != self.solver_id:
            raise RSILearningError("rsi_fixture_solver_request_mismatch")
        request_sha256 = request.digest()
        seed = lambda label: hashlib.sha256(f"{self.solver_id}:{label}:{request_sha256}".encode()).hexdigest()
        completed = self.terminal_status == "completed"
        provenance = dict(self.provenance)
        provenance.setdefault("backend", self.solver_id)
        provenance.setdefault("fixture", True)
        provenance.setdefault("iteration", 0)
        return SolverResult(
            episode_id=request.episode_id,
            request_sha256=request_sha256,
            status=self.terminal_status,
            candidate_receipt_sha256=seed("candidate") if completed else None,
            execution_receipt_sha256=seed("execution") if completed else None,
            official_evaluation_receipt_sha256=seed("evaluation") if completed else None,
            trace_digest=seed("trace"),
            solver_score=1.0 if completed else None,
            terminal_reason="fixture_completed" if completed else f"fixture_{self.terminal_status}",
            solver_provenance=tuple(sorted(provenance.items())),
        )


def fixture_solver_gateway(
    solver_id: str,
    *,
    terminal_status: str = "completed",
    provenance: Mapping[str, Any] | None = None,
) -> ProviderFreeSolverGateway:
    """Construct a local gateway using the same IDs as supported production backends."""

    return ProviderFreeSolverGateway(
        solver_id,
        terminal_status,
        tuple(sorted((provenance or {}).items())),
    )


__all__ = ["SUPPORTED_FIXTURE_SOLVERS", "ProviderFreeSolverGateway", "fixture_solver_gateway"]
