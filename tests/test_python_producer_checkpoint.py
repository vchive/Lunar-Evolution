from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from test_python_producer_binding import _fixture

from lunar_evolution.python_producer_binding import build_python_producer_binding
from lunar_evolution.python_producer_binding_store import persist_python_producer_binding
from lunar_evolution.python_producer_checkpoint import (
    PythonProducerCheckpointBinding,
    PythonProducerCheckpointError,
)


def _sidecar(tmp_path: Path):
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    binding = build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent,
        attestation=attestation, deadline_unix=4102444800.0, budget=budget,
    )
    batch = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id
    batch.mkdir(parents=True)
    batch.chmod(0o700)
    return persist_python_producer_binding(tmp_path, binding=binding)


def test_checkpoint_binding_round_trip_retains_pin(tmp_path: Path) -> None:
    sidecar = _sidecar(tmp_path)
    checkpoint = PythonProducerCheckpointBinding.from_sidecar(sidecar)
    restored = PythonProducerCheckpointBinding.from_json(checkpoint.to_json())
    assert restored.to_dict() == checkpoint.to_dict()
    restored.validate_sidecar(sidecar)


def test_checkpoint_does_not_accept_missing_or_unknown_pin_fields(tmp_path: Path) -> None:
    sidecar = _sidecar(tmp_path)
    value = PythonProducerCheckpointBinding.from_sidecar(sidecar).to_dict()
    value.pop("sidecar_pin")
    with pytest.raises(PythonProducerCheckpointError, match="schema_invalid"):
        PythonProducerCheckpointBinding.from_dict(value)
    value = PythonProducerCheckpointBinding.from_sidecar(sidecar).to_dict()
    value["sidecar_pin"] = {**value["sidecar_pin"], "extra": 1}
    with pytest.raises(PythonProducerCheckpointError, match="pin_invalid"):
        PythonProducerCheckpointBinding.from_dict(value)


@pytest.mark.parametrize("field", ["raw_sha256", "file_inode", "file_device", "file_mtime_ns", "file_ctime_ns"])
def test_checkpoint_pin_drift_is_rejected_without_refresh(tmp_path: Path, field: str) -> None:
    sidecar = _sidecar(tmp_path)
    checkpoint = PythonProducerCheckpointBinding.from_sidecar(sidecar)
    pin = dict(checkpoint.sidecar_pin)
    pin[field] = "f" * 64 if field == "raw_sha256" else pin[field] + 1
    with pytest.raises(PythonProducerCheckpointError, match="pin_mismatch"):
        checkpoint.validate_sidecar(replace(sidecar, **{field: pin[field]}))


def test_checkpoint_binding_identity_drift_is_rejected(tmp_path: Path) -> None:
    sidecar = _sidecar(tmp_path)
    checkpoint = PythonProducerCheckpointBinding.from_sidecar(sidecar)
    with pytest.raises(PythonProducerCheckpointError, match="binding_mismatch"):
        replace(checkpoint, binding_sha256="f" * 64).validate_sidecar(sidecar)
