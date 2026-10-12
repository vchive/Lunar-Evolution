from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_rsi_producer_replay_cli import _fixture

from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import SolverRequest, SolverResult
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_replay_gateway import (
    RetainedProducerReplayGateway,
    RetainedProducerReplaySource,
)
from lunar_evolution.rsi_store import RSILedger

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
    request_path = tmp_path / "request.json"
    request_raw = json.dumps(_request(solver).to_dict(), sort_keys=True, separators=(",", ":")).encode()
    request_path.write_bytes(request_raw)
    return RetainedProducerReplaySource(
        producer_root=tmp_path / "producer",
        contract_path=tmp_path / "contract.json",
        request_path=request_path,
        memory_path=tmp_path / "memory.json",
        receipts_path=tmp_path / "receipts.json",
        producer_id=solver,
        producer_fingerprint="e" * 64,
        contract_sha256=HEX,
        request_sha256=hashlib.sha256(request_raw).hexdigest(),
        memory_sha256="1" * 64,
        receipts_sha256="2" * 64,
        envelope_sha256="3" * 64,
        materials_sha256="4" * 64,
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
            materials_sha256="4" * 64,
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


def test_actual_pinned_export_is_read_and_drift_rejected(tmp_path: Path) -> None:
    case = _fixture(tmp_path)
    source = RetainedProducerReplaySource(
        producer_root=case["root"], contract_path=case["contract"],
        request_path=case["request"], memory_path=case["memory"], receipts_path=case["receipts"],
        producer_id=case["solver"], producer_fingerprint=case["producer"],
        contract_sha256=case["contract_pin"], request_sha256=case["request_pin"],
        memory_sha256=case["memory_pin"], receipts_sha256=case["receipts_pin"],
        envelope_sha256=case["envelope_pin"], materials_sha256=case["materials_pin"],
    )
    gateway = RetainedProducerReplayGateway(source)
    request = SolverRequest.from_dict(json.loads(case["request"].read_text()))
    result = gateway.run(request)
    assert result.status == "completed"
    assert gateway.validate_replay(request, result) == result
    (case["root"] / "candidate.py").write_bytes(b"changed source")
    with pytest.raises(RSILearningError, match="rsi_replay_evidence_drift"):
        gateway.validate_replay(request, result)


def test_actual_request_drift_refuses_before_missing_receipts(tmp_path: Path) -> None:
    gateway = RetainedProducerReplayGateway(_source(tmp_path))
    changed = replace(_request(), budget=(("max_solver_invocations", 2),))
    with pytest.raises(RSILearningError, match="rsi_replay_request_mismatch"):
        gateway.run(changed)


class ReadOnlyReplayFixture:
    requires_replay_validation = True

    def __init__(self):
        self.runs = 0
        self.replays = 0
        self.drift = False

    def rsi_fingerprint_config(self):
        return {"fixture": "controller-replay-validation"}

    def run(self, request):
        self.runs += 1
        return _result(request)

    def validate_replay(self, request, result):
        self.replays += 1
        if self.drift:
            raise RSILearningError("fixture_replay_drift")
        return result


def test_terminal_controller_resume_revalidates_without_dispatch(tmp_path: Path) -> None:
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    gateway = ReadOnlyReplayFixture()
    controller = RSILearningController(gateway, ledger=ledger)
    original = controller.run_drs(
        run_id="replay-run", contract_sha256=HEX, evaluator_sha256=HEX,
        environment_sha256=HEX, solver_id="openevolve", max_practice_rounds=0,
        max_target_attempts=1,
    )
    head = ledger.get_run("replay-run")
    assert RSILearningController(gateway, ledger=ledger).resume("replay-run") == original
    assert gateway.runs == 1 and gateway.replays == 1
    assert ledger.get_run("replay-run") == head
    gateway.drift = True
    with pytest.raises(RSILearningError, match="fixture_replay_drift"):
        controller.resume("replay-run")
    assert gateway.runs == 1 and ledger.get_run("replay-run") == head
