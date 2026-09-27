"""Cross-stage provider-free lifecycle acceptance matrix.

The individual producer-process tests exercise each primitive.  These tests keep
the acceptance contract visible at the attempt boundary: one consumed
attestation, one durable terminal receipt, bounded capture/deadline evidence,
and recovery that observes or cleans only the recorded owner.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_producer_process import _fixture, _registered_live_process

from lunar_evolution import (
    ProducerProcessError,
    producer_process,
    recover_producer_process,
    run_producer_process,
)


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    [
        ("success", "completed"),
        ("failed", "failed"),
        ("over-requests", "failed"),
        ("overflow", "failed"),
        ("dual-overflow", "failed"),
        ("symlink-envelope", "failed"),
    ],
)
def test_attempt_matrix_publishes_one_bound_terminal_receipt(
    tmp_path: Path, mode: str, expected_status: str,
):
    producer_root, intent, attestation = _fixture(tmp_path, mode=mode)
    receipt = run_producer_process(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
    )

    batch = tmp_path / "evolution/producer-batches/journal-001"
    receipt_path = batch / "execution-receipt.json"
    raw = json.loads(receipt_path.read_bytes())
    assert receipt.status == expected_status == raw["status"]
    assert raw["receipt_sha256"] == producer_process._digest_without(raw, "receipt_sha256")
    assert raw["previous_receipt_sha256"] == raw["registration_sha256"]
    assert raw["launch_id"] == intent.launch_id
    assert raw["journal_id"] == intent.journal_id
    assert raw["intent_sha256"] == intent.intent_sha256
    assert raw["attestation_sha256"] == attestation.attestation_sha256
    assert raw["gate_released"] is True
    assert raw["stdout_evidence"]["bytes_observed"] >= 0
    assert raw["stderr_evidence"]["bytes_observed"] >= 0
    assert len(list(batch.glob("execution-receipt.json"))) == 1

    if mode == "success":
        assert raw["envelope_evidence"]["read_status"] == "stable"
        assert raw["envelope_evidence"]["identity_before"] == raw["envelope_evidence"]["identity_after"]
    elif mode == "dual-overflow":
        assert raw["failure_code"] == "producer_process_output_limit_exceeded"
        assert raw["stdout_evidence"]["truncated"] is True
        assert raw["stderr_evidence"]["truncated"] is True
        assert raw["envelope_evidence"] is None
    elif mode == "symlink-envelope":
        assert raw["failure_code"] == "producer_process_envelope_invalid"
        assert raw["envelope_evidence"] is None


def test_replay_and_gate_failure_never_create_a_second_terminal_attempt(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="success")
    first = run_producer_process(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
    )
    with pytest.raises(ProducerProcessError) as replay:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            popen_factory=lambda *args, **kwargs: pytest.fail("replay spawned a child"),
        )
    assert replay.value.code == "producer_process_attestation_replayed"
    batch = tmp_path / "evolution/producer-batches/journal-001"
    assert json.loads((batch / "execution-receipt.json").read_bytes())["receipt_sha256"] == first.receipt_sha256

    gate_workspace = tmp_path / "gate"
    gate_workspace.mkdir()
    gate_root, gate_intent, gate_attestation = _fixture(gate_workspace, mode="success")
    original_write = producer_process.os.write

    def break_gate(fd: int, data: bytes) -> int:
        if data == b"1":
            raise BrokenPipeError("matrix gate failure")
        return original_write(fd, data)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(producer_process.os, "write", break_gate)
        with pytest.raises(ProducerProcessError) as gate:
            run_producer_process(
                gate_workspace, intent=gate_intent, attestation=gate_attestation,
                producer_root=gate_root,
            )
    assert gate.value.code == "producer_process_launch_unknown"
    gate_batch = gate_workspace / "evolution/producer-batches/journal-001"
    assert (gate_batch / "process-registration.json").is_file()
    assert not (gate_batch / "execution-receipt.json").exists()
    observation = recover_producer_process(gate_workspace, journal_id=gate_intent.journal_id)
    registration = json.loads((gate_batch / "process-registration.json").read_bytes())
    assert observation == {
        "status": "recovery_required",
        "reason": "producer_process_terminal_receipt_missing",
        "journal_id": gate_intent.journal_id,
        "launch_id": gate_intent.launch_id,
        "registration_sha256": registration["registration_sha256"],
        "pid": registration["pid"],
        "pgid": registration["pgid"],
    }


def test_recovery_matrix_is_read_only_then_single_owner_checked_cleanup(tmp_path: Path, monkeypatch):
    batch, intent, process = _registered_live_process(tmp_path)
    try:
        observed = recover_producer_process(tmp_path, journal_id=intent.journal_id)
        assert observed["status"] == "recovery_required"
        assert observed["reason"] == "producer_process_terminal_receipt_missing"
        assert not (batch / "recovery-receipt.json").exists()

        monkeypatch.setattr(
            producer_process.subprocess, "Popen",
            lambda *args, **kwargs: pytest.fail("recovery must not relaunch"),
        )
        cleaned = recover_producer_process(tmp_path, journal_id=intent.journal_id, cleanup=True)
        assert cleaned["status"] == "recovery_required"
        assert cleaned["execution_outcome"] == "unknown"
        assert cleaned["previous_receipt_sha256"] == cleaned["registration_sha256"]
        assert cleaned["recovery_sha256"] == producer_process._digest_without(cleaned, "recovery_sha256")
        assert cleaned["cleanup_status"] in {"cleaned", "cleanup_unverified", "ownership_lost"}
        assert recover_producer_process(tmp_path, journal_id=intent.journal_id) == cleaned
        with pytest.raises(ProducerProcessError) as duplicate:
            recover_producer_process(tmp_path, journal_id=intent.journal_id, cleanup=True)
        assert duplicate.value.code == "producer_process_recovery_already_recorded"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
