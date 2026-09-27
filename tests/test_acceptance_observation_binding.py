from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_acceptance_runtime_binding import _native_fixture

import lunar_evolution.acceptance_observation_binding as observation
import lunar_evolution.acceptance_runtime_binding as runtime


def _bound(tmp_path: Path):
    controller, parent, contract, registration, materials = _native_fixture(tmp_path)
    runtime.prepare_acceptance_runtime_binding(
        registration, store=controller.store, parent_id=parent.id, materials=materials,
        contract=contract, workspace=tmp_path / "holdouts",
    )
    return controller, parent, contract, registration, materials


def test_inspect_reconstructs_manifest_and_binding_without_provider(tmp_path):
    controller, parent, contract, registration, materials = _bound(tmp_path)
    result = observation.inspect_acceptance_observation_binding(
        registration, store=controller.store, parent_id=parent.id, materials=materials,
        contract=contract, workspace=tmp_path / "holdouts",
    )
    assert result["manifest"]["status"] == "criteria_bound"
    assert result["binding"]["status"] == "criteria_bound"
    assert result["manifest"]["runtime_binding_sha256"] == result["runtime_receipt"]["binding_sha256"]
    assert result["binding"]["manifest_sha256"] == result["manifest"]["manifest_sha256"]


def test_publish_is_create_only_and_writes_binding_last(tmp_path):
    controller, parent, contract, registration, materials = _bound(tmp_path)
    result = observation.publish_acceptance_observation_binding(
        registration, store=controller.store, parent_id=parent.id, materials=materials,
        contract=contract, workspace=tmp_path / "holdouts",
    )
    child = tmp_path / "holdouts" / "observation"
    assert json.loads((child / "manifest.json").read_bytes()) == result["manifest"]
    assert json.loads((child / "binding.json").read_bytes()) == result["binding"]
    with pytest.raises(observation.AcceptanceObservationBindingError, match="observation_publish_conflict"):
        observation.publish_acceptance_observation_binding(
            registration, store=controller.store, parent_id=parent.id, materials=materials,
            contract=contract, workspace=tmp_path / "holdouts",
        )


def test_inspect_rejects_retained_snapshot_drift(tmp_path):
    controller, parent, contract, registration, materials = _bound(tmp_path)
    (tmp_path / "holdouts" / "00" / "snapshot.bin").write_bytes(b"drift")
    with pytest.raises(observation.AcceptanceObservationBindingError, match="retained_probe_(missing|mismatch)"):
        observation.inspect_acceptance_observation_binding(
            registration, store=controller.store, parent_id=parent.id, materials=materials,
            contract=contract, workspace=tmp_path / "holdouts",
        )


def test_inspect_rejects_runtime_receipt_digest_drift(tmp_path):
    controller, parent, contract, registration, materials = _bound(tmp_path)
    receipt_path = tmp_path / "holdouts" / "binding-receipt.json"
    value = json.loads(receipt_path.read_bytes())
    value["binding_sha256"] = hashlib.sha256(b"wrong").hexdigest()
    receipt_path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(observation.AcceptanceObservationBindingError, match="runtime_receipt_digest_mismatch"):
        observation.inspect_acceptance_observation_binding(
            registration, store=controller.store, parent_id=parent.id, materials=materials,
            contract=contract, workspace=tmp_path / "holdouts",
        )


def test_publish_deadline_reserves_child_and_never_reuses_it(tmp_path):
    controller, parent, contract, registration, materials = _bound(tmp_path)

    def deadline(stage):
        return 0 if stage == "observation-publish" else 60

    with pytest.raises(observation.AcceptanceObservationBindingError, match="observation_deadline_exceeded"):
        observation.publish_acceptance_observation_binding(
            registration, store=controller.store, parent_id=parent.id, materials=materials,
            contract=contract, workspace=tmp_path / "holdouts", remaining_timeout=deadline,
        )
    assert (tmp_path / "holdouts" / "observation").is_dir()
    with pytest.raises(observation.AcceptanceObservationBindingError, match="observation_publish_conflict"):
        observation.publish_acceptance_observation_binding(
            registration, store=controller.store, parent_id=parent.id, materials=materials,
            contract=contract, workspace=tmp_path / "holdouts",
        )
