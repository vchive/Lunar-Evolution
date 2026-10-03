from __future__ import annotations

from dataclasses import replace

import pytest

from lunar_evolution.external_worker_evidence import (
    ExternalWorkerEvidenceError,
    ExternalWorkerEvidenceStore,
    ExternalWorkerTrustProfile,
)
from lunar_evolution.rsi_store import RSILedger

H = "a" * 64


def profile() -> ExternalWorkerTrustProfile:
    return ExternalWorkerTrustProfile(
        "fixture-project", "1", H, "b" * 64, "c" * 64, "d" * 64, "e" * 64,
        "parent-run", "task", "episode", "f" * 64, 123, 123,
        "pid-start-identity", 1, 2, 1, 3, 1, 4,
    )


def test_claim_heartbeat_and_terminal_failure_are_durable_and_replayable(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.sqlite")
    store = ExternalWorkerEvidenceStore(ledger, scope_id="worker-scope")
    worker = profile()
    claim = store.claim(worker, heartbeat_sha256=H)
    assert claim.status == "running"
    heartbeat = store.heartbeat(worker, checkpoint_sha256=claim.checkpoint_sha256, heartbeat_sha256="1" * 64)
    terminal = store.settle(worker, checkpoint_sha256=claim.checkpoint_sha256, status="failed",
                            terminal_receipt_sha256="2" * 64, controller_observed_terminal=True,
                            cleanup_confirmed=True)
    assert heartbeat.status == "running"
    assert terminal.status == "failed"
    assert ExternalWorkerEvidenceStore(ledger, scope_id="worker-scope").inspect(worker).status == "failed"
    assert store.inspect(worker).status == "failed"


def test_unknown_stays_quarantined_and_cannot_be_completed(tmp_path):
    store = ExternalWorkerEvidenceStore(RSILedger(tmp_path / "rsi.sqlite"), scope_id="worker-scope")
    worker = profile()
    claim = store.claim(worker, heartbeat_sha256=H)
    unknown = store.settle(worker, checkpoint_sha256=claim.checkpoint_sha256, status="unknown",
                           terminal_receipt_sha256="2" * 64, controller_observed_terminal=False,
                           cleanup_confirmed=False)
    assert unknown.status == "unknown"
    with pytest.raises(ExternalWorkerEvidenceError, match="terminal_conflict"):
        store.settle(worker, checkpoint_sha256=claim.checkpoint_sha256, status="failed",
                     terminal_receipt_sha256="3" * 64, controller_observed_terminal=True, cleanup_confirmed=True)


def test_claim_and_terminal_require_exact_profile_and_cleanup(tmp_path):
    store = ExternalWorkerEvidenceStore(RSILedger(tmp_path / "rsi.sqlite"), scope_id="worker-scope")
    worker = profile()
    claim = store.claim(worker, heartbeat_sha256=H)
    drifted = replace(worker, pid=124)
    with pytest.raises(ExternalWorkerEvidenceError, match="profile_drift"):
        store.inspect(drifted)
    with pytest.raises(ExternalWorkerEvidenceError, match="cleanup_unconfirmed"):
        store.settle(worker, checkpoint_sha256=claim.checkpoint_sha256, status="cancelled",
                     terminal_receipt_sha256="2" * 64, controller_observed_terminal=True,
                     cleanup_confirmed=False)


def test_bad_owner_or_heartbeat_digest_rejected_before_claim(tmp_path):
    store = ExternalWorkerEvidenceStore(RSILedger(tmp_path / "rsi.sqlite"), scope_id="worker-scope")
    with pytest.raises(ExternalWorkerEvidenceError, match="heartbeat_invalid"):
        store.claim(profile(), heartbeat_sha256="bad")
