from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from test_http_transport_deadline import clear_proxy_environment, local_http
from test_native_trusted_attempt import _attempt

from lunar_evolution.native_trusted_attempt import run_native_trusted_attempt
from lunar_evolution.native_trusted_capture import capture_native_trusted_output
from lunar_evolution.native_trusted_receipt import (
    NativeTrustedReceiptError,
    build_native_trusted_execution_receipt,
    persist_native_trusted_execution_receipt,
)
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig
from lunar_evolution.producer_process import _digest_without


def _materialize_broker_capture(batch: Path, intent, terminal: dict[str, object], observation) -> None:
    """Create the smallest envelope whose request declaration matches the broker ledger."""
    output = batch / intent.output_directory
    output.mkdir(parents=True, exist_ok=True)
    content = b"candidate = 1\n"
    (output / "candidate.py").write_bytes(content)
    declared = observation.snapshot.admitted_count
    envelope = {
        "schema_version": "1", "producer_id": intent.producer_id,
        "producer_fingerprint": intent.producer_fingerprint, "status": "completed",
        "contract_sha256": intent.contract_sha256,
        "budget": {"requests": declared},
        "materials": [{
            "kind": "candidate_source", "path": "candidate.py", "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }],
    }
    (output / "producer-result.json").write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")), encoding="utf-8",
    )
    deadline = json.loads((batch / "native-trusted-attempt-deadline.json").read_bytes())
    capture_native_trusted_output(
        batch, intent=intent, terminal_sha256=terminal["terminal_sha256"],
        broker=observation, deadline=deadline["deadline_monotonic"],
    )


def _valid_receipt_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clear_proxy_environment(monkeypatch)
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, broker_request=True,
    )
    with local_http() as (endpoint, _calls):
        result = run_native_trusted_attempt(
            workspace, producer_root=producer_root, intent=intent,
            attestation=attestation, artifact=artifact,
            broker_config=ProducerBrokerConfig(endpoint, {}),
        )
    assert result.broker_observation is not None
    terminal = json.loads((batch / "native-trusted-process-terminal.json").read_bytes())
    _materialize_broker_capture(batch, intent, terminal, result.broker_observation)
    return workspace, intent, attestation, artifact, batch


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_receipt_projection_stays_fail_closed_without_output_evidence(tmp_path: Path) -> None:
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    result = run_native_trusted_attempt(
        workspace,
        producer_root=producer_root,
        intent=intent,
        attestation=attestation,
        artifact=artifact,
    )
    assert result.status == "recovery_required"
    with pytest.raises(NativeTrustedReceiptError) as failure:
        build_native_trusted_execution_receipt(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert failure.value.code in {
        "native_trusted_receipt_output_invalid",
        "native_trusted_receipt_broker_incomplete",
        "native_trusted_receipt_cleanup_invalid",
    }
    assert not (batch / "execution-receipt.json").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_receipt_persistence_creates_formal_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, intent, attestation, artifact, batch = _valid_receipt_context(tmp_path, monkeypatch)
    receipt = persist_native_trusted_execution_receipt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    path = batch / "execution-receipt.json"
    assert path.is_file()
    assert json.loads(path.read_bytes()) == receipt.to_dict()
    assert receipt.status == "completed"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_receipt_persistence_replays_identical_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, intent, attestation, artifact, batch = _valid_receipt_context(tmp_path, monkeypatch)
    first = persist_native_trusted_execution_receipt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    before = (batch / "execution-receipt.json").read_bytes()
    second = persist_native_trusted_execution_receipt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    assert second == first
    assert (batch / "execution-receipt.json").read_bytes() == before


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_receipt_persistence_rejects_tampered_existing_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, intent, attestation, artifact, batch = _valid_receipt_context(tmp_path, monkeypatch)
    persist_native_trusted_execution_receipt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    path = batch / "execution-receipt.json"
    tampered = json.loads(path.read_bytes())
    tampered["status"] = "failed"
    tampered["receipt_sha256"] = _digest_without(tampered, "receipt_sha256")
    path.write_text(json.dumps(tampered, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(NativeTrustedReceiptError) as failure:
        persist_native_trusted_execution_receipt(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert failure.value.code == "native_trusted_receipt_existing_mismatch"


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        # Recovery validates stream/cleanup sidecars as part of the terminal chain first;
        # the projection therefore exposes the terminal-invalid gate for those omissions.
        ("stream", "native_trusted_receipt_terminal_invalid"),
        ("envelope", "native_trusted_receipt_output_invalid"),
        ("broker", "native_trusted_receipt_output_invalid"),
        ("cleanup", "native_trusted_receipt_terminal_invalid"),
    ],
)
@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_receipt_persistence_rejects_missing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str, expected: str,
) -> None:
    workspace, intent, attestation, artifact, batch = _valid_receipt_context(tmp_path, monkeypatch)
    paths = {
        "stream": batch / "native-trusted-stream-capture.json",
        "envelope": batch / intent.output_directory / "producer-result.json",
        "broker": batch / ".host-request-journal" / "requests",
        "cleanup": batch / "native-trusted-cleanup.json",
    }
    paths[missing].unlink()
    with pytest.raises(NativeTrustedReceiptError) as failure:
        persist_native_trusted_execution_receipt(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert failure.value.code == expected
