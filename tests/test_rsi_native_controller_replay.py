"""Native controller recovery rechecks evidence without dispatch or journal writes."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from test_rsi_producer_checkpoint_binding import _sidecar

from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import SolverRequest, SolverResult
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, MemorySnapshot, RSILearningError
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64


class ReadOnlyNativeGateway:
    """Local native-capability fixture with separately observable replay validation."""

    requires_memory_snapshot = True

    def __init__(self, ledger: RSILedger) -> None:
        self.ledger = ledger
        self.runs: list[tuple[SolverRequest, MemorySnapshot]] = []
        self.replays: list[tuple[SolverRequest, MemorySnapshot]] = []
        self.evidence_drift = False
        self.return_changed_result = False

    def rsi_fingerprint_config(self):
        return {"fixture": "read-only-native-controller-replay"}

    def run(self, request: SolverRequest, memory: MemorySnapshot) -> SolverResult:
        assert request.memory_snapshot_sha256 == memory.digest()
        self.runs.append((request, memory))
        # The provider-free fixture accepts the canonical local solver identifier; the
        # controller-level solver pin remains native-fixture for identity coverage.
        return SolverResult(
            episode_id=request.episode_id, request_sha256=request.digest(), status="completed",
            candidate_receipt_sha256="a" * 64, execution_receipt_sha256="b" * 64,
            official_evaluation_receipt_sha256="c" * 64, trace_digest="d" * 64,
            solver_score=1.0, terminal_reason="fixture_completed",
        )

    def validate_replay(
        self, request: SolverRequest, memory: MemorySnapshot, result: SolverResult,
    ) -> SolverResult:
        assert memory.digest() == request.memory_snapshot_sha256
        assert self.ledger.episode_result(request.episode_id) == (request, result)
        self.replays.append((request, memory))
        if self.evidence_drift:
            raise RSILearningError("fixture_native_retained_evidence_drift")
        if self.return_changed_result:
            return replace(result, trace_digest="b" * 64)
        return result


def _controller(tmp_path: Path, *, judge=None):
    ledger = RSILedger(tmp_path / "rsi.sqlite")
    gateway = ReadOnlyNativeGateway(ledger)
    options = {"target_judge": judge} if judge is not None else {}
    return RSILearningController(gateway, ledger=ledger, **options), gateway, ledger


def _run(controller: RSILearningController, *, rounds: int = 0):
    return controller.run_drs(
        run_id="native-replay", contract_sha256=HEX, evaluator_sha256=HEX,
        environment_sha256=HEX, solver_id="native-fixture", max_practice_rounds=rounds,
        max_target_attempts=rounds + 1,
    )


def _image(ledger: RSILedger):
    info = ledger.database.stat()
    # SQLite may checkpoint a WAL into the main file when a read connection closes.  That
    # layout detail differs between SQLite versions (notably 3.50 vs 3.52), even though no
    # ledger row was appended.  Compare the canonical logical database dump and file identity
    # instead of raw main-file bytes.
    with sqlite3.connect(ledger.database) as connection:
        logical_dump = tuple(connection.iterdump())
    return logical_dump, info.st_dev, info.st_ino


def _judge_after_practice(execution):
    return execution.episode.wave > 0, "needs practice"


def test_terminal_native_resume_validates_without_dispatch_or_ledger_write(tmp_path: Path):
    controller, gateway, ledger = _controller(tmp_path)
    first = _run(controller)
    before = _image(ledger)

    resumed = RSILearningController(gateway, ledger=ledger).resume("native-replay")

    assert resumed == first
    assert len(gateway.runs) == 1
    assert gateway.replays
    assert len(gateway.replays) == 1
    assert all(memory == EMPTY_MEMORY_SNAPSHOT for _, memory in gateway.replays)
    assert _image(ledger) == before


def test_terminal_native_resume_rejects_retained_drift_before_writes(tmp_path: Path):
    controller, gateway, ledger = _controller(tmp_path)
    _run(controller)
    gateway.evidence_drift = True
    before = _image(ledger)

    with pytest.raises(RSILearningError, match="retained_evidence_drift"):
        controller.resume("native-replay")

    assert len(gateway.runs) == 1
    assert _image(ledger) == before


def test_native_resume_uses_each_original_snapshot_after_practice_commit(tmp_path: Path):
    controller, gateway, ledger = _controller(tmp_path, judge=_judge_after_practice)
    first = _run(controller, rounds=1)
    assert len(first.memory_snapshot.items) == 1
    before = _image(ledger)

    resumed = RSILearningController(
        gateway, ledger=ledger, target_judge=_judge_after_practice,
    ).resume("native-replay")

    assert resumed == first
    assert len(gateway.runs) == 3
    original = {request.episode_id: memory for request, memory in gateway.runs}
    assert original["native-replay-target-0"] != first.memory_snapshot
    assert original["native-replay-target-1"] == first.memory_snapshot
    assert all(memory == original[request.episode_id] for request, memory in gateway.replays)
    assert _image(ledger) == before


def test_native_result_crash_drift_blocks_episode_settlement(tmp_path: Path, monkeypatch):
    controller, gateway, ledger = _controller(tmp_path)
    save = ledger.save_episode_result

    def crash_after_result(request, result):
        save(request, result)
        raise RuntimeError("fixture_result_crash")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", crash_after_result)
        with pytest.raises(RuntimeError, match="result_crash"):
            _run(controller)
    assert ledger.get_episode("native-replay-target-0").state == "running"
    gateway.evidence_drift = True
    before = _image(ledger)

    with pytest.raises(RSILearningError, match="retained_evidence_drift"):
        controller.resume("native-replay")

    assert len(gateway.runs) == 1
    assert ledger.get_episode("native-replay-target-0").state == "running"
    assert _image(ledger) == before


def test_native_cached_execution_drift_blocks_resume_before_callback_or_write(
    tmp_path: Path, monkeypatch,
):
    controller, gateway, ledger = _controller(tmp_path)
    with monkeypatch.context() as patch:
        def crash_before_finish(*_args, **_kwargs):
            raise RuntimeError("fixture_cached_execution_crash")

        patch.setattr(controller, "_finish_flow", crash_before_finish)
        with pytest.raises(RuntimeError, match="cached_execution_crash"):
            _run(controller)
    checkpoint = ledger.controller_checkpoint("native-replay")[1]
    assert checkpoint["executions"]
    assert checkpoint["status"] == "running"
    gateway.evidence_drift = True
    before = _image(ledger)

    with pytest.raises(RSILearningError, match="retained_evidence_drift"):
        controller.resume("native-replay")

    assert len(gateway.runs) == 1
    assert _image(ledger) == before


def test_native_terminal_checkpoint_drift_blocks_run_finalization(tmp_path: Path, monkeypatch):
    controller, gateway, ledger = _controller(tmp_path)
    with monkeypatch.context() as patch:
        def crash_before_run_publication(*_args, **_kwargs):
            raise RuntimeError("fixture_terminal_checkpoint_crash")

        patch.setattr(controller, "_finish_run", crash_before_run_publication)
        with pytest.raises(RuntimeError, match="terminal_checkpoint_crash"):
            _run(controller)
    assert ledger.get_run("native-replay").state == "running"
    assert ledger.controller_checkpoint("native-replay")[1]["status"] == "completed"
    gateway.evidence_drift = True
    before = _image(ledger)

    with pytest.raises(RSILearningError, match="retained_evidence_drift"):
        controller.resume("native-replay")

    assert ledger.get_run("native-replay").state == "running"
    assert len(gateway.runs) == 1
    assert _image(ledger) == before


def test_native_resume_cannot_substitute_current_memory_for_missing_history(tmp_path: Path, monkeypatch):
    controller, gateway, ledger = _controller(tmp_path, judge=_judge_after_practice)
    _run(controller, rounds=1)
    monkeypatch.setattr(ledger, "controller_checkpoint_history", lambda _run_id: [])
    before = _image(ledger)

    with pytest.raises(RSILearningError, match="memory_snapshot_missing"):
        controller.resume("native-replay")

    assert len(gateway.runs) == 3
    assert not gateway.replays
    assert _image(ledger) == before


def test_native_controller_rejects_missing_replay_validator(tmp_path: Path, monkeypatch):
    controller, gateway, ledger = _controller(tmp_path)
    _run(controller)
    monkeypatch.setattr(gateway, "validate_replay", None)
    before = _image(ledger)

    with pytest.raises(RSILearningError, match="replay_validation_required"):
        controller.resume("native-replay")

    assert len(gateway.runs) == 1
    assert _image(ledger) == before


def test_native_controller_rejects_replay_validator_result_substitution(tmp_path: Path):
    controller, gateway, ledger = _controller(tmp_path)
    _run(controller)
    gateway.return_changed_result = True
    before = _image(ledger)

    with pytest.raises(RSILearningError, match="replay_result_conflict"):
        controller.resume("native-replay")

    assert len(gateway.runs) == 1
    assert _image(ledger) == before


def test_native_replay_sidecar_drift_stops_before_reconciliation_or_verifier_append(tmp_path: Path):
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite")
    gateway = ReadOnlyNativeGateway(ledger)
    controller = RSILearningController(
        gateway, ledger=ledger, producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    first = controller.run_drs(
        run_id=binding.run_id, contract_sha256=HEX, evaluator_sha256=HEX,
        environment_sha256=HEX, solver_id="native-fixture", max_practice_rounds=0,
        max_target_attempts=1,
    )
    assert first.status == "completed"
    before = _image(ledger)
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / "python-producer-binding.json"
    original_validate = gateway.validate_replay

    def drift_after_replay(request, memory, result):
        value = original_validate(request, memory, result)
        sidecar_path.unlink()
        return value

    gateway.validate_replay = drift_after_replay
    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        RSILearningController(
            gateway, ledger=ledger, producer_sidecar=sidecar, producer_workspace=tmp_path,
        ).resume(binding.run_id)

    assert ledger.get_episode(f"{binding.run_id}-target-0").state == "completed"
    assert ledger.controller_checkpoint(binding.run_id)[1]["executions"]
    assert _image(ledger) == before
