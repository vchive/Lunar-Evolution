"""Offline durable preparation joins real local journal/capture/source evidence."""
from __future__ import annotations

import json
import time
from dataclasses import replace

import pytest
from test_native_trusted_output import _fixture

from lunar_evolution import native_trusted_preparation as preparation
from lunar_evolution.native_trusted_capture import capture_native_trusted_output
from lunar_evolution.producer_broker_ipc import ProducerBrokerObservation
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.producer_request_transport import (
    HostRequestJournal,
    HostRequestJournalIdentity,
    HostRequestLedger,
    read_host_request_journal,
)


def materialized(tmp_path, monkeypatch, *, brokered=True, uncertain=False):
    output, envelope, supplied = _fixture(tmp_path, monkeypatch)
    terminal = {
        "protocol": "lunar-native-trusted-process-terminal-v1", "process_status": "exited_zero",
        "cleanup_status": "cleaned", "gate_released": True, "target_started": True,
        "terminal_sha256": "c" * 64,
    }
    monkeypatch.setattr(preparation, "recover_native_trusted_attempt", lambda *args, **kwargs: terminal)
    intent = supplied["intent"]
    broker = None
    if brokered:
        journal_dir = output.parent / ".host-request-journal"
        journal_dir.mkdir(mode=0o700)
        identity = HostRequestJournalIdentity(
            launch_id=intent.launch_id, journal_id=intent.journal_id, run_id=intent.run_id,
            parent_task_id=intent.parent_task_id, task_id=intent.task_id,
            intent_sha256=intent.intent_sha256, request_timeout_seconds=intent.request_timeout_seconds,
            max_requests=intent.max_requests,
        )
        path = journal_dir / "requests"
        with HostRequestJournal.create(path, identity) as journal:
            ledger = HostRequestLedger(request_timeout_seconds=intent.request_timeout_seconds,
                                       max_requests=intent.max_requests, journal=journal)
            admission = ledger.admit("request-1")
            if not uncertain:
                ledger.finish(admission, status="completed")
            snapshot = ledger.snapshot()
        recovered = read_host_request_journal(path, expected_identity=identity)
        broker = ProducerBrokerObservation(snapshot, path, identity, recovered.journal_sha256,
                                           recovered.journal_bytes, not uncertain, "fixture")
    capture_native_trusted_output(output.parent, intent=intent, terminal_sha256="c" * 64,
                                  broker=broker, deadline=time.monotonic() + 30)
    arguments = {key: supplied[key] for key in ("intent", "attestation", "artifact", "contract", "groups")}
    return output, envelope, arguments


def test_persist_and_recover_exact_preparation_without_publication(tmp_path, monkeypatch):
    output, _, arguments = materialized(tmp_path, monkeypatch)
    result = preparation.persist_native_trusted_preparation(tmp_path, **arguments)
    before = result.receipt_path.read_bytes()
    assert result.publication_eligible is False
    assert result.publication_blockers == (
        "complete_egress_authority", "publication_transaction", "delivery_verification",
    )
    assert result.output.output_capture_sha256 is not None
    assert len(result.output.drafts) == 1
    assert result.output.request_coverage == "brokered_requests_only"
    repeated = preparation.persist_native_trusted_preparation(tmp_path, **arguments)
    recovered = preparation.recover_native_trusted_preparation(
        tmp_path, **arguments, expected_receipt_sha256=result.receipt_sha256,
    )
    assert repeated == recovered == result
    assert result.receipt_path.read_bytes() == before
    assert not (output.parent / "journal.prepared.json").exists()
    assert not (output.parent / "native-drafts").exists()
    assert not (tmp_path / "evolution/archive.jsonl").exists()


@pytest.mark.parametrize("uncertain", [False, True])
def test_missing_or_unknown_broker_evidence_never_creates_preparation(tmp_path, monkeypatch, uncertain):
    output, _, arguments = materialized(tmp_path, monkeypatch, brokered=uncertain, uncertain=uncertain)
    with pytest.raises(preparation.NativeTrustedPreparationError, match="broker_incomplete|evidence_unverified"):
        preparation.persist_native_trusted_preparation(tmp_path, **arguments)
    assert not (output.parent / "native-trusted-preparation.json").exists()


def test_changed_grouping_rejected_without_overwriting_receipt(tmp_path, monkeypatch):
    _, _, arguments = materialized(tmp_path, monkeypatch)
    result = preparation.persist_native_trusted_preparation(tmp_path, **arguments)
    saved = result.receipt_path.read_bytes()
    arguments["groups"] = [BundleGroup("different-bundle", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))]
    with pytest.raises(preparation.NativeTrustedPreparationError, match="receipt_mismatch"):
        preparation.persist_native_trusted_preparation(tmp_path, **arguments)
    assert result.receipt_path.read_bytes() == saved


@pytest.mark.parametrize("change", ["source", "capture", "journal", "receipt", "unknown", "contract", "pin"])
def test_recovery_reopens_evidence_and_rejects_drift(tmp_path, monkeypatch, change):
    output, _, arguments = materialized(tmp_path, monkeypatch)
    result = preparation.persist_native_trusted_preparation(tmp_path, **arguments)
    expected = result.receipt_sha256
    if change == "source":
        (output / "pkg/helper.py").write_text("VALUE = 2\n")
    elif change == "capture":
        (output.parent / "native-trusted-output-capture.json").unlink()
    elif change == "journal":
        (output.parent / ".host-request-journal/requests").unlink()
    elif change == "receipt":
        raw = json.loads(result.receipt_path.read_bytes())
        raw["publication_eligible"] = True
        raw["receipt_sha256"] = preparation._digest({k: v for k, v in raw.items() if k != "receipt_sha256"})
        result.receipt_path.write_text(json.dumps(raw))
        expected = raw["receipt_sha256"]
    elif change == "unknown":
        monkeypatch.setattr(preparation, "recover_native_trusted_attempt", lambda *a, **kw: {"status": "unknown"})
    elif change == "contract":
        arguments["intent"] = replace(arguments["intent"], contract_sha256="d" * 64, intent_sha256=None)
    else:
        expected = "d" * 64
    with pytest.raises(preparation.NativeTrustedPreparationError):
        preparation.recover_native_trusted_preparation(tmp_path, **arguments, expected_receipt_sha256=expected)


def test_recovery_rejects_symlink_receipt_and_changed_ancestor(tmp_path, monkeypatch):
    output, _, arguments = materialized(tmp_path, monkeypatch)
    result = preparation.persist_native_trusted_preparation(tmp_path, **arguments)
    moved = output.parent / "receipt-copy"
    result.receipt_path.rename(moved)
    result.receipt_path.symlink_to(moved)
    with pytest.raises(preparation.NativeTrustedPreparationError, match="receipt_invalid"):
        preparation.recover_native_trusted_preparation(tmp_path, **arguments,
                                                       expected_receipt_sha256=result.receipt_sha256)


def test_failure_after_exclusive_receipt_write_is_recoverable(tmp_path, monkeypatch):
    _, _, arguments = materialized(tmp_path, monkeypatch)
    original = preparation._atomic_json
    def interrupted(path, value, **kwargs):
        original(path, value, **kwargs)
        raise RuntimeError("crash after write")
    with monkeypatch.context() as patch:
        patch.setattr(preparation, "_atomic_json", interrupted)
        with pytest.raises(RuntimeError, match="crash after write"):
            preparation.persist_native_trusted_preparation(tmp_path, **arguments)
    result = preparation.persist_native_trusted_preparation(tmp_path, **arguments)
    assert preparation.recover_native_trusted_preparation(
        tmp_path, **arguments, expected_receipt_sha256=result.receipt_sha256,
    ) == result
