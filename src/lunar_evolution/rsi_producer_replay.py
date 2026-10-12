"""Read-only local producer receipt inspection; it grants no runtime admission.

The caller supplies independently retained byte pins. Existing producer, request, memory and
native receipt parsers do the validation; this module only composes them and returns a diagnostic
projection. It never executes a producer/evaluator or initializes a controller/ledger.
"""

from __future__ import annotations

import hashlib
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import _benchmark_files as files
from .algorithm import MAX_CONTRACT_BYTES, AlgorithmProblemContract
from .candidate_evaluation_spec import strict_json
from .official_evaluator_evidence import OfficialEvaluationReceipt, verify_official_evaluation
from .producer_handoff import ProducerHandoffError, prepare_producer_seed_manifest
from .rsi_gateway import SolverRequest
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_candidate import (
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
    map_native_receipts_to_solver_result,
    select_native_candidate,
)
from .rsi_native_gateway import NativeRSIReceiptBundle

MAX_REPLAY_BYTES = 512 * 1024
_FIELDS = {
    "candidate", "execution", "evaluation", "publication", "provenance_sha256",
    "worker_terminal_status", "official_evaluator_receipt",
}


class RSIProducerReplayError(ValueError):
    """A fixed local diagnostic refusal with no caller text or path."""


def _pin(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise RSIProducerReplayError("rsi_producer_replay_pin_invalid")
    return value


def _identity(path: Path) -> tuple[int, ...]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RSIProducerReplayError("rsi_producer_replay_file_invalid")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read(path: object, pin: str, maximum: int = MAX_REPLAY_BYTES) -> tuple[Path, bytes, tuple[int, ...]]:
    selected = files.absolute_path(path)
    if selected.name == ".env" or selected.name.startswith(".env."):
        raise RSIProducerReplayError("rsi_producer_replay_file_invalid")
    before = _identity(selected)
    raw = files.read_regular_file(selected, maximum)
    if hashlib.sha256(raw).hexdigest() != _pin(pin):
        raise RSIProducerReplayError("rsi_producer_replay_digest_drift")
    if _identity(selected) != before:
        raise RSIProducerReplayError("rsi_producer_replay_file_drift")
    return selected, raw, before


def inspect_producer_replay(
    *, producer_root: str | Path, contract_path: str | Path, request_path: str | Path,
    memory_path: str | Path, receipts_path: str | Path, producer_id: str,
    producer_fingerprint: str, contract_sha256: str, request_sha256: str,
    memory_sha256: str, receipts_sha256: str, envelope_sha256: str,
) -> dict[str, Any]:
    """Map pinned local receipt fixtures with existing APIs, without publishing their result.

    A producer envelope alone never supplies execution/evaluation/publication authority.
    ``completed`` describes only this detached local comparison, not an admitted runtime.
    """
    pins = tuple(_pin(value) for value in (
        producer_fingerprint, contract_sha256, request_sha256, memory_sha256, receipts_sha256,
        envelope_sha256,
    ))
    if producer_id not in {"openevolve", "shinka"}:
        raise RSIProducerReplayError("rsi_producer_replay_solver_invalid")
    report: dict[str, Any] = {
        "status": "unknown", "reason": "rsi_producer_replay_evidence_missing",
        "read_only": True, "evidence_scope": "retained_local_comparison",
        "production_admission": False, "solver_id": producer_id, "result": None,
        "producer_fingerprint": pins[0], "contract_sha256": pins[1],
        "request_sha256": pins[2], "memory_sha256": pins[3],
        "envelope_sha256": pins[5], "receipts_sha256": pins[4],
    }
    observed: list[tuple[Path, bytes, tuple[int, ...]]] = []
    try:
        observed = [
            _read(contract_path, pins[1], MAX_CONTRACT_BYTES),
            _read(request_path, pins[2]), _read(memory_path, pins[3]),
        ]
        contract = AlgorithmProblemContract.from_dict(strict_json(observed[0][1], MAX_CONTRACT_BYTES))
        request = SolverRequest.from_dict(strict_json(observed[1][1], MAX_REPLAY_BYTES))
        memory = MemorySnapshot.from_dict(strict_json(observed[2][1], MAX_REPLAY_BYTES))
        if (request.solver_id != producer_id or request.contract_sha256 != contract.digest()
                or request.memory_snapshot_sha256 != memory.digest()):
            raise RSIProducerReplayError("rsi_producer_replay_request_drift")
        observed.append(_read(files.absolute_path(producer_root) / "producer-result.json", pins[5]))
        manifest = prepare_producer_seed_manifest(
            producer_root, contract, evaluator_fingerprint=request.evaluator_sha256,
            producer_fingerprint=pins[0], producer_id=producer_id,
        )
        source_nodes = [(manifest.source_root / seed.source_path, _identity(manifest.source_root / seed.source_path))
                        for seed in manifest.seeds]
        observed.append(_read(receipts_path, pins[4]))
        value = strict_json(observed[-1][1], MAX_REPLAY_BYTES)
        required = {"candidate", "execution", "evaluation", "publication", "official_evaluator_receipt"}
        if type(value) is not dict or not required <= set(value) or set(value) - _FIELDS:
            raise RSIProducerReplayError("rsi_producer_replay_receipts_invalid")
        worker_status = value.get("worker_terminal_status", "unknown")
        if worker_status not in {"completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"}:
            raise RSIProducerReplayError("rsi_producer_replay_terminal_invalid")
        if any(value[name] is None for name in required) or worker_status != "completed":
            return report
        bundle = NativeRSIReceiptBundle(
            NativeCandidateRecord.from_dict(value["candidate"]),
            NativeExecutionReceipt.from_dict(value["execution"]),
            NativeEvaluationReceipt.from_dict(value["evaluation"]),
            NativePublicationReceipt.from_dict(value["publication"]),
            provenance_sha256=value.get("provenance_sha256"),
            worker_terminal_status=worker_status,
            official_evaluator_receipt=OfficialEvaluationReceipt.from_dict(value["official_evaluator_receipt"]),
        )
        if bundle.candidate.candidate_source_sha256 not in {seed.source_sha256 for seed in manifest.seeds}:
            raise RSIProducerReplayError("rsi_producer_replay_source_drift")
        verify_official_evaluation(
            bundle.official_evaluator_receipt, request_sha256=request.digest(),
            contract_sha256=request.contract_sha256, evaluator_sha256=request.evaluator_sha256,
            candidate_source_sha256=bundle.candidate.candidate_source_sha256,
            execution_receipt_sha256=bundle.execution.receipt_sha256,
            publication_receipt_sha256=bundle.publication.receipt_sha256,
        )
        if bundle.official_evaluator_receipt.raw_verdict_sha256 != bundle.evaluation.receipt_sha256:
            raise RSIProducerReplayError("rsi_producer_replay_evaluator_drift")
        result = map_native_receipts_to_solver_result(
            request, select_native_candidate(request, [bundle.candidate]),
            bundle.execution, bundle.evaluation, bundle.publication,
        )
        if prepare_producer_seed_manifest(
            producer_root, contract, evaluator_fingerprint=request.evaluator_sha256,
            producer_fingerprint=pins[0], producer_id=producer_id,
        ).to_dict() != manifest.to_dict():
            raise RSIProducerReplayError("rsi_producer_replay_source_drift")
        if (any(_identity(path) != node for path, node in source_nodes)
                or any(_identity(path) != node for path, _, node in observed)):
            raise RSIProducerReplayError("rsi_producer_replay_file_drift")
        result = replace(result, solver_provenance=tuple(sorted({
            **dict(result.solver_provenance), "backend": producer_id,
            "evidence_scope": "retained_local_comparison", "production_admission": False,
        }.items())))
        return {**report, "status": "completed", "reason": "rsi_producer_replay_matching",
                "request_sha256": request.digest(), "receipts_sha256": pins[4], "result": result.to_dict()}
    except FileNotFoundError:
        return report
    except files.BenchmarkFileError as exc:
        return {**report, "status": "unknown" if exc.reason == "missing" else "drifted",
                "reason": "rsi_producer_replay_evidence_missing" if exc.reason == "missing" else "rsi_producer_replay_file_invalid"}
    except ProducerHandoffError as exc:
        return {**report, "status": "drifted", "reason": exc.code}
    except (RSIProducerReplayError, RSILearningError, ValueError, TypeError, OSError):
        return {**report, "status": "drifted", "reason": "rsi_producer_replay_evidence_drift"}


__all__ = ["RSIProducerReplayError", "inspect_producer_replay"]
