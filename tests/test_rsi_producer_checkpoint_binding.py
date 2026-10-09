from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from test_python_producer_binding import _fixture

from lunar_evolution import (
    RSILearningController,
    RSILearningError,
    RSILedger,
    fixture_solver_gateway,
)
from lunar_evolution.python_producer_binding import build_python_producer_binding
from lunar_evolution.python_producer_binding_store import persist_python_producer_binding

DIGEST = "a" * 64


def _sidecar(tmp_path: Path):
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    binding = build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent,
        attestation=attestation, deadline_unix=4102444800.0, budget=budget,
    )
    batch = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id
    batch.mkdir(parents=True)
    batch.chmod(0o700)
    return binding, persist_python_producer_binding(tmp_path, binding=binding)


def test_controller_checkpoint_retains_and_revalidates_producer_pin(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    result = controller.run_drs(
        run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
        environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
    )
    assert result.status == "completed"
    checkpoint = ledger.controller_checkpoint(binding.run_id)
    assert checkpoint is not None
    assert checkpoint[1]["producer_checkpoint_binding"]["sidecar_pin"]["file_inode"] == sidecar.file_inode

    resumed = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    ).resume(binding.run_id)
    assert resumed.status == "completed"


def test_controller_resume_rejects_retained_pin_drift(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    ).run_drs(
        run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
        environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
    )
    drifted = replace(sidecar, file_inode=sidecar.file_inode + 1)
    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        RSILearningController(
            fixture_solver_gateway("mock"), ledger=ledger,
            producer_sidecar=drifted, producer_workspace=tmp_path,
        ).resume(binding.run_id)


def test_controller_without_producer_pin_keeps_existing_checkpoint_shape(tmp_path: Path) -> None:
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    result = RSILearningController(fixture_solver_gateway("mock"), ledger=ledger).run_drs(
        run_id="ordinary-rsi", contract_sha256=DIGEST, evaluator_sha256=DIGEST,
        environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
    )
    assert result.status == "completed"
    state = ledger.controller_checkpoint("ordinary-rsi")[1]
    assert "producer_checkpoint_binding" not in state


def test_fresh_producer_run_validates_sidecar_before_controller_checkpoint(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / "python-producer-binding.json"
    sidecar_path.unlink()
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )

    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
        )

    assert ledger.controller_checkpoint(binding.run_id) is None


def test_producer_bound_legacy_checkpoint_fails_closed_without_sidecar_proof(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    with ledger.controller_lock(binding.run_id):
        record = controller._start_run(
            run_id=binding.run_id, mode="drs", contract_sha256=DIGEST,
            evaluator_sha256=DIGEST, environment_sha256=DIGEST, solver_id="mock",
            budget={"max_target_attempts": 1, "max_practice_rounds": 0},
        )
        assert record is not None
        ledger.write_controller_checkpoint(
            binding.run_id, {"schema_version": "1"}, expected_sha256=None,
        )

    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        RSILearningController(
            fixture_solver_gateway("mock"), ledger=ledger,
            producer_sidecar=sidecar, producer_workspace=tmp_path,
        ).resume(binding.run_id)


class _DriftAfterFirstDispatchGateway:
    def __init__(self, sidecar_path: Path) -> None:
        self.sidecar_path = sidecar_path
        self.calls = 0
        self.delegate = fixture_solver_gateway("mock")

    def rsi_fingerprint_config(self):
        return {"fixture": "producer-sidecar-drift"}

    def run(self, request):
        self.calls += 1
        result = self.delegate.run(request)
        if self.calls == 1:
            self.sidecar_path.unlink()
        return result


def test_producer_sidecar_drift_between_episodes_blocks_next_dispatch(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / "python-producer-binding.json"
    gateway = _DriftAfterFirstDispatchGateway(sidecar_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        gateway, ledger=ledger, target_judge=lambda _execution: (False, "gap"),
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )

    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=1,
            max_target_attempts=2,
        )

    assert gateway.calls == 1
