from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import SolverRequest, SolverResult
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_replay_gateway import (
    RetainedProducerReplayGateway,
    RetainedProducerReplaySource,
)

HEX = "a" * 64


def _request(status_solver: str = "openevolve") -> SolverRequest:
    return SolverRequest.build(
        episode_id="replay-episode",
        contract_sha256=HEX,
        evaluator_sha256="b" * 64,
        environment_sha256="c" * 64,
        memory_snapshot_sha256="d" * 64,
        solver_id=status_solver,
    )


def _source(tmp_path: Path, solver: str = "openevolve") -> RetainedProducerReplaySource:
    return RetainedProducerReplaySource(
        producer_root=tmp_path / "producer",
        contract_path=tmp_path / "contract.json",
        request_path=tmp_path / "request.json",
        memory_path=tmp_path / "memory.json",
        receipts_path=tmp_path / "receipts.json",
        producer_id=solver,
        producer_fingerprint="e" * 64,
        contract_sha256=HEX,
        request_sha256="f" * 64,
        memory_sha256="1" * 64,
        receipts_sha256="2" * 64,
        envelope_sha256="3" * 64,
    )


def _result(request: SolverRequest, *, status: str = "completed") -> SolverResult:
    seed = lambda label: hashlib.sha256(f"{label}:{request.digest()}".encode()).hexdigest()
    return SolverResult(
        episode_id=request.episode_id,
        request_sha256=request.digest(),
        status=status,
        candidate_receipt_sha256=seed("candidate") if status == "completed" else None,
        execution_receipt_sha256=seed("execution") if status == "completed" else None,
        official_evaluation_receipt_sha256=seed("evaluation") if status == "completed" else None,
        trace_digest=seed("trace"),
        solver_score=1.0 if status == "completed" else None,
        terminal_reason="retained_replay" if status == "completed" else "retained_unknown",
        solver_provenance=(
            ("backend", request.solver_id),
            ("evidence_scope", "retained_local_comparison"),
            ("production_admission", False),
        ),
    )


def test_source_fingerprint_is_path_free_and_pins_are_checked(tmp_path: Path) -> None:
    source = _source(tmp_path)
    fingerprint = source.fingerprint()
    assert "producer_root" not in fingerprint
    assert fingerprint["protocol"] == "lunar-rsi-retained-producer-replay-v1"
    with pytest.raises(RSILearningError, match="rsi_replay_source_pin_invalid"):
        type(_source(tmp_path))(
            producer_root=tmp_path / "producer", contract_path=tmp_path / "contract.json",
            request_path=tmp_path / "request.json", memory_path=tmp_path / "memory.json",
            receipts_path=tmp_path / "receipts.json", producer_id="openevolve",
            producer_fingerprint="z" * 64, contract_sha256=HEX, request_sha256="f" * 64,
            memory_sha256="1" * 64, receipts_sha256="2" * 64, envelope_sha256="3" * 64,
        )


def test_completed_replay_is_mapped_and_revalidated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    request = _request()
    result = _result(request)
    gateway = RetainedProducerReplayGateway(_source(tmp_path))
    monkeypatch.setattr(
        "lunar_evolution.rsi_replay_gateway.inspect_producer_replay",
        lambda **_: {"status": "completed", "result": result.to_dict()},
    )
    observed = gateway.run(request)
    assert observed == result
    assert gateway.validate_replay(request, observed) == result
    assert dict(observed.solver_provenance)["production_admission"] is False


def test_missing_replay_becomes_stable_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    request = _request()
    gateway = RetainedProducerReplayGateway(_source(tmp_path))
    monkeypatch.setattr(
        "lunar_evolution.rsi_replay_gateway.inspect_producer_replay",
        lambda **_: {"status": "unknown", "reason": "rsi_producer_replay_evidence_missing"},
    )
    first = gateway.run(request)
    second = gateway.run(request)
    assert first == second
    assert first.status == "unknown"
    assert first.candidate_receipt_sha256 is None


def test_drift_and_request_mismatch_fail_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    gateway = RetainedProducerReplayGateway(_source(tmp_path))
    with pytest.raises(RSILearningError, match="rsi_replay_request_mismatch"):
        gateway.run(_request("shinka"))
    monkeypatch.setattr(
        "lunar_evolution.rsi_replay_gateway.inspect_producer_replay",
        lambda **_: {"status": "drifted", "reason": "rsi_producer_replay_evidence_drift"},
    )
    with pytest.raises(RSILearningError, match="rsi_replay_evidence_drift"):
        gateway.run(_request())


def test_cached_result_drift_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    request = _request()
    gateway = RetainedProducerReplayGateway(_source(tmp_path))
    original = _result(request)
    changed = replace(original, trace_digest="9" * 64)
    monkeypatch.setattr(
        "lunar_evolution.rsi_replay_gateway.inspect_producer_replay",
        lambda **_: {"status": "completed", "result": changed.to_dict()},
    )
    with pytest.raises(RSILearningError, match="rsi_replay_result_drift"):
        gateway.validate_replay(request, original)


def test_controller_cached_execution_uses_opt_in_replay_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    request = _request()
    result = _result(request)
    gateway = RetainedProducerReplayGateway(_source(tmp_path))
    monkeypatch.setattr(
        "lunar_evolution.rsi_replay_gateway.inspect_producer_replay",
        lambda **_: {"status": "completed", "result": result.to_dict()},
    )
    controller = object.__new__(RSILearningController)
    controller.gateway = gateway
    cached = SimpleNamespace(episode=SimpleNamespace(), request=request, result=result)
    controller._validate_native_cached_execution(cached)
