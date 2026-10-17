"""Coherent ledger snapshots and atomic pins; explicit component fixtures only."""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import nullcontext
from pathlib import Path

import pytest
from test_rsi_brs_reconcile_controller import HEX, OTHER, _fixture, _register, _terminal_evidence

from lunar_evolution import RSILearningError
from lunar_evolution.candidate_evaluation_spec import canonical_json


def _terminal(tmp_path):
    ledger, run_id, episode_id, request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    evidence = _terminal_evidence(ledger, request, registration.obligation)
    return ledger, run_id, episode_id, registration.obligation, evidence


def test_snapshot_reparses_exact_domains_without_writes(tmp_path: Path) -> None:
    ledger, run_id, episode_id, obligation, _ = _terminal(tmp_path)
    before = ledger.database.read_bytes()
    snapshot = ledger.read_brs_terminal_evidence_snapshot(run_id, episode_id)
    request, result = snapshot["saved_result"]
    assert snapshot["pins"] == {
        "root_checkpoint_sha256": ledger.controller_checkpoint(run_id)[0],
        "mailbox_checkpoint_sha256": None,
        "terminal_checkpoint_sha256": None,
        "run_record_sha256": ledger.get_run(run_id).record_sha256,
        "episode_record_sha256": ledger.get_episode(episode_id).record_sha256,
        "native_claim_sha256": snapshot["native_claim"].claim_sha256,
        "result_sha256": hashlib.sha256(canonical_json(result.to_dict())).hexdigest(),
        "obligation_sha256": obligation.digest(),
    }
    assert request.digest() == obligation.request_sha256
    assert snapshot["native_claim"].status == "completed"
    assert snapshot["mailbox_history"] == snapshot["terminal_history"] == []
    assert ledger.database.read_bytes() == before


def test_snapshot_does_not_recreate_removed_database(tmp_path: Path) -> None:
    ledger, run_id, episode_id, _, _ = _terminal(tmp_path)
    ledger.database.unlink()
    with pytest.raises(sqlite3.OperationalError):
        ledger.read_brs_terminal_evidence_snapshot(run_id, episode_id)
    assert not ledger.database.exists()


@pytest.mark.parametrize("pin", [
    "root_checkpoint_sha256", "mailbox_checkpoint_sha256", "terminal_checkpoint_sha256",
    "run_record_sha256", "episode_record_sha256", "native_claim_sha256", "result_sha256",
    "obligation_sha256",
])
def test_consume_rechecks_every_composed_source_pin(tmp_path: Path, pin: str) -> None:
    ledger, run_id, episode_id, _, evidence = _terminal(tmp_path)
    pins = ledger.read_brs_terminal_evidence_snapshot(run_id, episode_id)["pins"]
    pins[pin] = OTHER
    before = ledger.controller_checkpoint_history(run_id)
    with ledger.controller_lock(run_id), pytest.raises(RSILearningError, match="terminal_consume_drift"):
        ledger._consume_brs_reconcile_obligation(run_id, episode_id, evidence, expected_pins=pins)
    assert ledger.controller_checkpoint_history(run_id) == before


@pytest.mark.parametrize("lane", ["root", "mailbox", "terminal"])
def test_new_checkpoint_between_composition_and_consume_preserves_fence(tmp_path: Path, lane: str) -> None:
    ledger, run_id, episode_id, obligation, evidence = _terminal(tmp_path)
    with ledger.controller_lock(run_id):
        pins = ledger.read_brs_terminal_evidence_snapshot(run_id, episode_id)["pins"]
        namespace = run_id if lane == "root" else "rsi-brs-" + lane + ":" + obligation.digest()
        with ledger.controller_lock(namespace) if namespace != run_id else nullcontext():
            current = ledger.controller_checkpoint(namespace)
            state = current[1] if current else {"fixture": True}
            ledger.write_controller_checkpoint(
                namespace, state, expected_sha256=current[0] if current else None,
            )
        before = ledger.controller_checkpoint_history(run_id)
        with pytest.raises(RSILearningError, match="terminal_consume_drift"):
            ledger._consume_brs_reconcile_obligation(run_id, episode_id, evidence, expected_pins=pins)
    assert ledger.controller_checkpoint_history(run_id) == before
    assert episode_id in ledger.controller_brs_reconcile_obligations(run_id)


def test_source_pin_recheck_and_consume_hold_same_sqlite_transaction(tmp_path: Path, monkeypatch) -> None:
    ledger, run_id, episode_id, _, evidence = _terminal(tmp_path)
    pins = ledger.read_brs_terminal_evidence_snapshot(run_id, episode_id)["pins"]
    original = ledger._brs_terminal_evidence_snapshot_tx
    observed = []

    def snapshot(connection, selected_run, selected_episode):
        result = original(connection, selected_run, selected_episode)
        with sqlite3.connect(ledger.database, timeout=0) as other, pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("BEGIN IMMEDIATE")
        observed.append(result["pins"])
        return result

    monkeypatch.setattr(ledger, "_brs_terminal_evidence_snapshot_tx", snapshot)
    with ledger.controller_lock(run_id):
        consumed = ledger._consume_brs_reconcile_obligation(run_id, episode_id, evidence, expected_pins=pins)
    assert observed == [pins]
    assert consumed.consumed is True


def test_corrupt_saved_result_is_not_an_unchanged_pin(tmp_path: Path) -> None:
    ledger, run_id, episode_id, _, evidence = _terminal(tmp_path)
    pins = ledger.read_brs_terminal_evidence_snapshot(run_id, episode_id)["pins"]
    with sqlite3.connect(ledger.database) as connection:
        connection.execute("UPDATE rsi_episode_results SET result_sha256 = ? WHERE episode_id = ?", (HEX, episode_id))
    before = ledger.controller_checkpoint_history(run_id)
    with ledger.controller_lock(run_id), pytest.raises(RSILearningError, match="native_episode_result_binding_drift"):
        ledger._consume_brs_reconcile_obligation(run_id, episode_id, evidence, expected_pins=pins)
    assert ledger.controller_checkpoint_history(run_id) == before
