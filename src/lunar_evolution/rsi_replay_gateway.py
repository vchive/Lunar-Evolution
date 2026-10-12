"""Read-only producer replay gateway for the local RSI controller.

This adapter consumes a previously retained producer export and maps the existing
receipt comparison into the ordinary :class:`SolverGateway` result wire.  It never
starts a producer, evaluator, controller, or ledger by itself.  The adapter is
deliberately marked as replay-only; its provenance keeps ``production_admission``
false and callers must treat it as local evidence rather than a production worker.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .candidate_evaluation_spec import canonical_json, strict_json
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_learning import RSILearningError
from .rsi_producer_replay import inspect_producer_replay


def _pin(value: object, code: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RSILearningError(code)
    return value


def _path(value: object, code: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise RSILearningError(code)
    path = Path(value).expanduser()
    if path.name == ".env" or path.name.startswith(".env."):
        raise RSILearningError(code)
    return path.absolute()


@dataclass(frozen=True, slots=True)
class RetainedProducerReplaySource:
    """All inputs required to replay one pinned local producer export.

    The paths are retained as lexical identities and are rechecked by
    :func:`inspect_producer_replay` before each read.  The independent pins are
    part of the gateway fingerprint, so controller resume cannot silently switch
    to another export.
    """

    producer_root: Path
    contract_path: Path
    request_path: Path
    memory_path: Path
    receipts_path: Path
    producer_id: str
    producer_fingerprint: str
    contract_sha256: str
    request_sha256: str
    memory_sha256: str
    receipts_sha256: str
    envelope_sha256: str
    materials_sha256: str

    def __post_init__(self) -> None:
        for field in ("producer_root", "contract_path", "request_path", "memory_path", "receipts_path"):
            object.__setattr__(self, field, _path(getattr(self, field), "rsi_replay_source_path_invalid"))
        if self.producer_id not in {"openevolve", "shinka"}:
            raise RSILearningError("rsi_replay_solver_invalid")
        for field in (
            "producer_fingerprint", "contract_sha256", "request_sha256", "memory_sha256",
            "receipts_sha256", "envelope_sha256",
            "materials_sha256",
        ):
            _pin(getattr(self, field), "rsi_replay_source_pin_invalid")

    def fingerprint(self) -> dict[str, Any]:
        """Return a path-free stable identity suitable for resume fingerprints."""

        return {
            "protocol": "lunar-rsi-retained-producer-replay-v1",
            "producer_id": self.producer_id,
            "producer_fingerprint": self.producer_fingerprint,
            "contract_sha256": self.contract_sha256,
            "request_sha256": self.request_sha256,
            "memory_sha256": self.memory_sha256,
            "receipts_sha256": self.receipts_sha256,
            "envelope_sha256": self.envelope_sha256,
            "materials_sha256": self.materials_sha256,
        }


class RetainedProducerReplayGateway:
    """Map a retained replay into ``SolverResult`` without launching anything.

    ``unknown`` evidence is represented as a durable unknown result with a stable
    trace digest.  Drift is a hard refusal, while a completed report is reparsed
    through the canonical ``SolverResult`` loader and checked against the request.
    ``validate_replay`` is used by controller resume to repeat the same read-only
    comparison before returning a cached execution.
    """

    requires_replay_validation = True
    replay_only = True

    def __init__(self, source: RetainedProducerReplaySource) -> None:
        if type(source) is not RetainedProducerReplaySource:
            raise RSILearningError("rsi_replay_source_invalid")
        self.source = source

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        return self.source.fingerprint()

    def _inspect(self, request: SolverRequest) -> dict[str, Any]:
        if type(request) is not SolverRequest or request.solver_id != self.source.producer_id:
            raise RSILearningError("rsi_replay_request_mismatch")
        # Check the complete original request before incomplete producer/receipt
        # evidence can map to unknown. Missing receipts must not authorize a new
        # episode, budget, evaluator, memory or solver-settings request.
        from .rsi_producer_replay import _read

        try:
            _, request_raw, _ = _read(self.source.request_path, self.source.request_sha256)
            original = SolverRequest.from_dict(strict_json(request_raw, maximum=512 * 1024))
        except (OSError, TypeError, ValueError, KeyError, RecursionError, OverflowError):
            raise RSILearningError("rsi_replay_request_unverified") from None
        if original != request:
            raise RSILearningError("rsi_replay_request_mismatch")
        try:
            return inspect_producer_replay(
                producer_root=self.source.producer_root,
                contract_path=self.source.contract_path,
                request_path=self.source.request_path,
                memory_path=self.source.memory_path,
                receipts_path=self.source.receipts_path,
                producer_id=self.source.producer_id,
                producer_fingerprint=self.source.producer_fingerprint,
                contract_sha256=self.source.contract_sha256,
                request_sha256=self.source.request_sha256,
                memory_sha256=self.source.memory_sha256,
                receipts_sha256=self.source.receipts_sha256,
                envelope_sha256=self.source.envelope_sha256,
                materials_sha256=self.source.materials_sha256,
            )
        except (OSError, TypeError, ValueError, KeyError, RecursionError, OverflowError) as exc:
            if isinstance(exc, RSILearningError):
                raise
            raise RSILearningError("rsi_replay_inspection_failed") from None

    @staticmethod
    def _unknown(request: SolverRequest, reason: str) -> SolverResult:
        trace = hashlib.sha256(canonical_json({
            "protocol": "lunar-rsi-retained-producer-replay-v1",
            "request_sha256": request.digest(),
            "reason": reason,
        }, maximum=4096)).hexdigest()
        return SolverResult(
            episode_id=request.episode_id,
            request_sha256=request.digest(),
            status="unknown",
            candidate_receipt_sha256=None,
            execution_receipt_sha256=None,
            official_evaluation_receipt_sha256=None,
            trace_digest=trace,
            terminal_reason=reason,
            solver_provenance=(
                ("backend", request.solver_id),
                ("evidence_scope", "retained_local_comparison"),
                ("production_admission", False),
                ("replay_only", True),
            ),
        )

    def run(self, request: SolverRequest) -> SolverResult:
        report = self._inspect(request)
        status = report.get("status")
        if status == "completed":
            raw = report.get("result")
            try:
                result = SolverResult.from_dict(raw)
            except (RSILearningError, TypeError, ValueError):
                raise RSILearningError("rsi_replay_result_invalid") from None
            if result.request_sha256 != request.digest() or result.episode_id != request.episode_id:
                raise RSILearningError("rsi_replay_result_identity_mismatch")
            return result
        if status == "unknown":
            return self._unknown(request, str(report.get("reason", "rsi_replay_evidence_missing")))
        if status == "drifted":
            raise RSILearningError("rsi_replay_evidence_drift")
        raise RSILearningError("rsi_replay_report_invalid")

    def validate_replay(self, request: SolverRequest, result: SolverResult) -> SolverResult:
        """Re-read the source and require the exact cached result to round-trip."""

        observed = self.run(request)
        if observed != result:
            raise RSILearningError("rsi_replay_result_drift")
        return observed


__all__ = ["RetainedProducerReplayGateway", "RetainedProducerReplaySource"]
