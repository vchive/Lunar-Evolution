"""Evidence recovery must preserve worker identity, ownership and immutable receipts."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from dataclasses import replace

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_gateway import SolverRequest, SolverResult
from lunar_evolution.rsi_learning import (
    PracticeEpisode,
    RSILearningError,
    TraceEvent,
    TransferReceipt,
)
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64
OTHER = "b" * 64
EVIDENCE = {"reconciliation": {"source": "local-worker-receipt"}}


def _episode(store, *, status="failed", unknown=True, request_changes=None, episode_changes=None):
    pins = {
        "contract_sha256": HEX, "evaluator_sha256": HEX, "environment_sha256": HEX,
        "memory_snapshot_sha256": HEX, "solver_id": "mock",
    }
    request = SolverRequest.build(episode_id="episode", **(pins | (request_changes or {})))
    episode = PracticeEpisode(
        episode_id="episode", run_id="run", status="planned", **(pins | (episode_changes or {})),
    ).transition("running", request_sha256=request.digest())
    if unknown:
        episode = episode.transition("unknown", terminal_reason="worker_disconnected")
    head = store.create_episode_record(episode)
    result = SolverResult(
        "episode", request.digest(), status, HEX, HEX, HEX, HEX,
        solver_score=1.0 if status == "completed" else None,
        terminal_reason="worker_terminal",
        candidate_source_sha256=OTHER, dependency_sha256=OTHER,
        trace_events=(TraceEvent(0, "tool", "evaluate", OTHER, HEX),),
        actor_fingerprint=OTHER,
    )
    store.save_episode_result(request, result)
    return head, request, result


@pytest.mark.parametrize("status", ["completed", "failed", "timed_out", "abandoned", "cancelled"])
def test_all_persisted_terminal_results_bind_complete_evidence(tmp_path, status):
    store = RSILedger(tmp_path / "ledger.sqlite")
    head, request, result = _episode(store, status=status)
    settled = store.reconcile_episode(
        head.logical_id, worker_state=status, expected_record_sha256=head.record_sha256,
        result=result, evidence=EVIDENCE,
    )
    loaded = PracticeEpisode.from_dict(settled.payload)
    assert loaded.status == status
    assert loaded.trace_events == result.trace_events
    assert loaded.actor_fingerprint == result.actor_fingerprint
    assert loaded.candidate_source_sha256 == result.candidate_source_sha256
    assert loaded.dependency_sha256 == result.dependency_sha256
    assert loaded.trace_digest == result.trace_digest
    assert loaded.request_sha256 == request.digest()
    assert loaded.solver_fingerprint is not None
    assert store.episode_reconciliation(head.logical_id)[-1]["result_sha256"] == hashlib.sha256(
        canonical_json(result.to_dict())
    ).hexdigest()


@pytest.mark.parametrize("status", ["failed", "timed_out", "abandoned", "cancelled"])
def test_unknown_canonical_episode_cannot_bypass_evidence_via_append(tmp_path, status):
    store = RSILedger(tmp_path / "ledger.sqlite")
    head, _request, _result = _episode(store, status=status)
    episode = PracticeEpisode.from_dict(head.payload)
    with pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
        store.append_episode_record(
            episode.transition(status, terminal_reason="unbound_claim"),
            expected_record_sha256=head.record_sha256,
        )
    assert store.get_episode(head.logical_id) == head


@pytest.mark.parametrize("field", [
    "contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256", "solver_id",
])
def test_reconcile_checks_request_pins_even_when_digest_is_bound(tmp_path, field):
    store = RSILedger(tmp_path / "ledger.sqlite")
    value = "other-solver" if field == "solver_id" else OTHER
    head, _request, result = _episode(store, request_changes={field: value})
    with pytest.raises(RSILearningError, match="rsi_episode_result_request_mismatch"):
        store.reconcile_episode(
            head.logical_id, worker_state="failed", expected_record_sha256=head.record_sha256,
            result=result, evidence=EVIDENCE,
        )
    assert store.get_episode(head.logical_id) == head
    assert store.episode_reconciliation(head.logical_id) == ()


@pytest.mark.parametrize("column,value", [("episode_id", "substituted"), ("request_sha256", OTHER)])
def test_result_row_identity_tampering_is_rejected(tmp_path, column, value):
    store = RSILedger(tmp_path / "ledger.sqlite")
    _episode(store)
    with sqlite3.connect(store.database) as connection:
        connection.execute(f"UPDATE rsi_episode_results SET {column} = ?", (value,))
    with pytest.raises(RSILearningError, match="rsi_episode_result_corrupt"):
        store.episode_result("substituted" if column == "episode_id" else "episode")


def test_shared_ledger_lock_is_owned_by_one_thread(tmp_path):
    store = RSILedger(tmp_path / "ledger.sqlite")
    seen = []
    errors = []

    def other_thread():
        seen.append(store.controller_lock_held("run"))
        try:
            store.write_controller_checkpoint("run", {"phase": "target"}, expected_sha256=None)
        except RSILearningError as exc:
            errors.append(exc.code)

    with store.controller_lock("run"):
        assert store.controller_lock_held("run")
        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert seen == [False]
        assert errors == ["rsi_controller_lock_required"]
        assert store.controller_checkpoint("run") is None
    assert not store.controller_lock_held("run")


def test_transfer_receipt_is_idempotent_and_conflict_checked(tmp_path):
    store = RSILedger(tmp_path / "ledger.sqlite")
    receipt = TransferReceipt("run", "target", HEX, HEX, HEX, "passed", HEX)
    first = store.create_transfer_receipt(receipt)
    assert store.create_transfer_receipt(receipt) == first
    with pytest.raises(RSILearningError, match="rsi_transfer_receipt_conflict"):
        store.create_transfer_receipt(replace(receipt, status="failed"))
    assert len(store.history(first.logical_id)) == 1


def _unknown_run(store):
    record = store.create_run("run", HEX, {"mode": "drs"})
    record = store.transition("run", state="running", expected_record_sha256=record.record_sha256)
    return store.transition("run", state="unknown", expected_record_sha256=record.record_sha256)


def test_unknown_run_resume_requires_settled_evidence_and_lock(tmp_path):
    store = RSILedger(tmp_path / "ledger.sqlite")
    run = _unknown_run(store)
    episode, _request, result = _episode(store)
    with pytest.raises(RSILearningError, match="rsi_state_transition_invalid"):
        store.transition("run", state="running", expected_record_sha256=run.record_sha256)
    with pytest.raises(RSILearningError, match="rsi_controller_lock_required"):
        store.reconcile_run("run", expected_record_sha256=run.record_sha256, evidence=EVIDENCE)
    with store.controller_lock("run"):
        with pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
            store.reconcile_run("run", expected_record_sha256=run.record_sha256, evidence=EVIDENCE)
        settled = store.reconcile_episode(
            "episode", worker_state="failed", expected_record_sha256=episode.record_sha256,
            result=result, evidence=EVIDENCE,
        )
        resumed = store.reconcile_run("run", expected_record_sha256=run.record_sha256, evidence=EVIDENCE)
    assert resumed.state == "running"
    assert resumed.parent_record_sha256 == run.record_sha256
    assert resumed.payload["run_reconciliation"]["episodes"][0]["record_sha256"] == settled.record_sha256
    assert resumed.payload["run_reconciliation"]["episodes"][0]["reconciliation_sha256"]


def test_unknown_run_without_episodes_cannot_restart(tmp_path):
    store = RSILedger(tmp_path / "ledger.sqlite")
    run = _unknown_run(store)
    with store.controller_lock("run"), pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
        store.reconcile_run("run", expected_record_sha256=run.record_sha256, evidence=EVIDENCE)


def test_unknown_result_keeps_run_quarantined(tmp_path):
    store = RSILedger(tmp_path / "ledger.sqlite")
    run = _unknown_run(store)
    episode, _request, result = _episode(store, status="unknown", unknown=False)
    store.reconcile_episode(
        "episode", worker_state="unknown", expected_record_sha256=episode.record_sha256,
        result=result, evidence=EVIDENCE,
    )
    with store.controller_lock("run"), pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
        store.reconcile_run("run", expected_record_sha256=run.record_sha256, evidence=EVIDENCE)
