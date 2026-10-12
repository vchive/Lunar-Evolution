"""Malformed process journals remain fail-closed and read-only during Python recovery."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from test_python_producer_recovery import _binding, _receipt
from test_python_producer_recovery_anchor import _durable_snapshot

from lunar_evolution import producer_process
from lunar_evolution.python_producer_lifecycle import (
    PythonProducerLifecycleError,
    recover_python_producer_terminal,
)


def _process_files(workspace: Path, binding):
    """Persist coherent inert process wires without launching a child."""
    batch = workspace / "evolution" / "producer-batches" / binding.intent.journal_id
    receipt = _receipt(binding)
    identity = {key: getattr(receipt, key) for key in (
        "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
        "attestation_sha256", "executable_identity",
    )}
    claim = {
        "schema_version": "1", "protocol": producer_process.PRODUCER_PROCESS_PROTOCOL,
        **identity, "nonce": "malformed-journal-fixture",
    }
    claim["consumption_sha256"] = producer_process._digest_without(claim, "consumption_sha256")
    registration = {
        **claim, **{key: getattr(receipt, key) for key in (
            "execution_binding", "execution_snapshot_relative_path", "execution_snapshot_sha256",
            "execution_snapshot_size", "pid", "pgid", "owner_identity",
        )}, "owner_identity_sha256": producer_process._sha(dict(receipt.owner_identity)),
    }
    registration["registration_sha256"] = producer_process._digest_without(
        registration, "registration_sha256",
    )
    receipt = replace(
        receipt, consumption_sha256=claim["consumption_sha256"],
        registration_sha256=registration["registration_sha256"],
        previous_receipt_sha256=registration["registration_sha256"], receipt_sha256=None,
    )
    for name, wire in (
        ("attestation-consumption.json", claim), ("process-registration.json", registration),
        ("execution-receipt.json", receipt.to_dict()),
    ):
        producer_process._atomic_json(batch / name, wire, exclusive=True)
    return batch


@pytest.mark.parametrize(
    ("journal", "expected"),
    [
        ("attestation-consumption.json", "recovery_observation_invalid"),
        ("process-registration.json", "recovery_observation_invalid"),
        ("execution-receipt.json", "recovery_observation_invalid"),
    ],
)
def test_malformed_process_journal_refuses_without_repair(
    tmp_path: Path, journal: str, expected: str,
) -> None:
    """Recovery must preserve the first malformed boundary across repeated reads."""
    binding, sidecar = _binding(tmp_path)
    batch = _process_files(tmp_path, binding)
    path = batch / journal
    path.write_bytes(b'{"interrupted":')
    before = _durable_snapshot(tmp_path)

    for _ in range(2):
        with pytest.raises(
            PythonProducerLifecycleError,
            match=f"^python_producer_lifecycle_{expected}$",
        ):
            recover_python_producer_terminal(
                tmp_path, binding=binding, sidecar=sidecar,
            )
        assert _durable_snapshot(tmp_path) == before
