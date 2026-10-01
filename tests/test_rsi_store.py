from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution import (
    RSILearningError,
    RSILedger,
    RSIPracticeEpisode,
    worker_to_episode_state,
)
from lunar_evolution.rsi_gateway import SolverRequest, SolverResult
from lunar_evolution.rsi_learning import MemorySnapshot

HEX = "a" * 64


def ledger(tmp_path: Path) -> RSILedger:
    return RSILedger(tmp_path / "rsi.sqlite3")


def canonical_running_episode() -> RSIPracticeEpisode:
    return RSIPracticeEpisode(
        episode_id="episode-record-1",
        run_id="run-1",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=HEX,
        solver_id="mock",
        status="planned",
    ).transition("running", request_sha256=HEX)


def test_canonical_episode_record_is_stored_and_appended(tmp_path: Path):
    store = ledger(tmp_path)
    running = canonical_running_episode()
    created = store.create_episode_record(running)
    assert created.logical_id == running.episode_id
    assert created.state == "running"
    assert created.request_sha256 == running.request_sha256
    assert created.payload == running.to_record_dict()

    completed = running.transition(
        "completed",
        candidate_receipt_sha256=HEX,
        execution_receipt_sha256=HEX,
        official_evaluation_receipt_sha256=HEX,
        trace_digest=HEX,
    )
    appended = store.append_episode_record(
        completed,
        expected_record_sha256=created.record_sha256,
    )
    assert appended.revision == 1
    assert appended.parent_record_sha256 == created.record_sha256
    assert appended.payload == completed.to_record_dict()
    assert [item.state for item in store.history(running.episode_id)] == ["running", "completed"]


def test_canonical_episode_record_rejects_identity_request_and_lineage_drift(tmp_path: Path):
    store = ledger(tmp_path)
    running = canonical_running_episode()
    created = store.create_episode_record(running)
    completed = running.transition(
        "completed",
        candidate_receipt_sha256=HEX,
        execution_receipt_sha256=HEX,
        official_evaluation_receipt_sha256=HEX,
        trace_digest=HEX,
    )
    with pytest.raises(RSILearningError) as lineage:
        store.append_episode_record(replace(completed, previous_record_sha256="b" * 64))
    assert lineage.value.code == "rsi_episode_lineage_conflict"

    with pytest.raises(RSILearningError) as identity:
        store.append_episode_record(replace(completed, run_id="other-run"))
    assert identity.value.code == "rsi_episode_identity_drift"

    with pytest.raises(RSILearningError) as request:
        store.append_episode_record(replace(completed, request_sha256="b" * 64))
    assert request.value.code == "rsi_episode_request_drift"

    with pytest.raises(RSILearningError) as parent:
        store.append_episode_record(completed, expected_record_sha256="b" * 64)
    assert parent.value.code == "rsi_record_parent_conflict"
    assert store.get(running.episode_id) == created


def test_canonical_episode_record_requires_request_bound_state(tmp_path: Path):
    store = ledger(tmp_path)
    planned = RSIPracticeEpisode(
        episode_id="episode-planned-1",
        run_id="run-1",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=HEX,
        solver_id="mock",
        status="planned",
    )
    with pytest.raises(RSILearningError) as error:
        store.create_episode_record(planned)
    assert error.value.code == "rsi_episode_request_missing"


def test_run_and_episode_history_are_append_only(tmp_path: Path):
    store = ledger(tmp_path)
    run = store.create_run("run-1", HEX, {"mode": "drs", "budget": 3})
    assert run.revision == 0
    running = store.transition("run-1", state="running", expected_record_sha256=run.record_sha256)
    assert running.revision == 1
    assert running.parent_record_sha256 == run.record_sha256
    assert [record.state for record in store.history("run-1")] == ["created", "running"]

    episode = store.create_episode("episode-1", HEX, {"run_id": "run-1", "wave": 0})
    assert episode.state == "planned"
    assert store.get("episode-1") == episode


def test_typed_queries_and_episode_ids_are_run_scoped(tmp_path: Path):
    store = ledger(tmp_path)
    run = store.create_run("query-run", HEX, {"mode": "drs"})
    assert store.get_run("query-run") == run
    episode = store.create_episode("query-episode", HEX, {"run_id": "query-run"})
    assert store.get_episode("query-episode") == episode
    assert store.get_transfer("query-run", "target-1") is None
    assert store.episode_ids_for_run("query-run") == ("query-episode",)


def test_illegal_transition_and_compare_and_swap_conflict(tmp_path: Path):
    store = ledger(tmp_path)
    record = store.create_run("run-1", HEX, {})
    with pytest.raises(RSILearningError) as error:
        store.transition("run-1", state="completed", expected_record_sha256=record.record_sha256)
    assert error.value.code == "rsi_state_transition_invalid"

    running = store.transition("run-1", state="running", expected_record_sha256=record.record_sha256)
    with pytest.raises(RSILearningError) as error:
        store.transition("run-1", state="paused", expected_record_sha256=record.record_sha256)
    assert error.value.code == "rsi_record_parent_conflict"
    assert store.get("run-1") == running


def test_unknown_requires_reconciliation_and_cannot_silently_retry(tmp_path: Path):
    store = ledger(tmp_path)
    record = store.create_episode("episode-1", HEX, {})
    unknown = store.reconcile_worker(
        "episode-1", worker_state="unknown", expected_record_sha256=record.record_sha256
    )
    assert unknown.state == "unknown"
    with pytest.raises(RSILearningError) as error:
        store.transition("episode-1", state="running", expected_record_sha256=unknown.record_sha256)
    assert error.value.code == "rsi_state_transition_invalid"

    completed = store.reconcile_worker(
        "episode-1", worker_state="completed", expected_record_sha256=unknown.record_sha256,
        payload_patch={"reconciled": True},
    )
    assert completed.state == "completed"
    assert completed.payload["reconciled"] is True


@pytest.mark.parametrize(
    ("initial", "next_state"),
    [
        ("created", "running"),
        ("running", "paused"),
        ("paused", "running"),
        ("running", "completed"),
        ("running", "failed"),
        ("running", "cancelled"),
        ("running", "unknown"),
        ("unknown", "completed"),
        ("unknown", "failed"),
        ("unknown", "cancelled"),
    ],
)
def test_run_state_matrix_allows_only_explicit_recovery_edges(
    tmp_path: Path, initial: str, next_state: str
):
    store = ledger(tmp_path)
    record = store.create_run("run-matrix", HEX, {"mode": "drs"})
    if initial != "created":
        record = store.transition("run-matrix", state="running", expected_record_sha256=record.record_sha256)
    if initial == "paused":
        record = store.transition("run-matrix", state="paused", expected_record_sha256=record.record_sha256)
    if initial == "unknown":
        record = store.transition("run-matrix", state="unknown", expected_record_sha256=record.record_sha256)
    resumed = store.transition("run-matrix", state=next_state, expected_record_sha256=record.record_sha256)
    assert resumed.state == next_state
    assert resumed.parent_record_sha256 == record.record_sha256


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled", "unknown"])
def test_run_terminal_states_are_idempotent_but_do_not_restart(tmp_path: Path, terminal: str):
    store = ledger(tmp_path)
    record = store.create_run("run-terminal", HEX, {})
    record = store.transition("run-terminal", state="running", expected_record_sha256=record.record_sha256)
    record = store.transition("run-terminal", state=terminal, expected_record_sha256=record.record_sha256)
    same = store.transition("run-terminal", state=terminal, expected_record_sha256=record.record_sha256)
    assert same.revision == record.revision + 1
    assert same.state == terminal
    with pytest.raises(RSILearningError) as error:
        store.transition("run-terminal", state="running", expected_record_sha256=same.record_sha256)
    assert error.value.code == "rsi_state_transition_invalid"


@pytest.mark.parametrize("terminal", ["failed", "timed_out", "abandoned", "cancelled"])
def test_episode_terminal_states_are_not_resumable(tmp_path: Path, terminal: str):
    store = ledger(tmp_path)
    record = store.create_episode("episode-terminal", HEX, {})
    record = store.transition("episode-terminal", state="running", expected_record_sha256=record.record_sha256)
    record = store.transition("episode-terminal", state=terminal, expected_record_sha256=record.record_sha256)
    with pytest.raises(RSILearningError) as error:
        store.transition("episode-terminal", state="running", expected_record_sha256=record.record_sha256)
    assert error.value.code == "rsi_state_transition_invalid"


def test_unknown_episode_can_only_be_settled_by_reconciliation(tmp_path: Path):
    store = ledger(tmp_path)
    record = store.create_episode("episode-reconcile", HEX, {})
    running = store.transition(
        "episode-reconcile", state="running", expected_record_sha256=record.record_sha256
    )
    unknown = store.reconcile_worker(
        "episode-reconcile", worker_state="unknown", expected_record_sha256=running.record_sha256,
    )
    with pytest.raises(RSILearningError) as retry:
        store.transition("episode-reconcile", state="running", expected_record_sha256=unknown.record_sha256)
    assert retry.value.code == "rsi_state_transition_invalid"
    completed = store.reconcile_worker(
        "episode-reconcile", worker_state="completed", expected_record_sha256=unknown.record_sha256,
        payload_patch={"approval": "evidence-reconciled"},
    )
    assert completed.state == "completed"
    assert completed.payload["approval"] == "evidence-reconciled"


@pytest.mark.parametrize(
    ("worker", "launched", "expected"),
    [
        ("running", True, "running"),
        ("idle", False, "planned"),
        ("idle", True, "running"),
        ("completed", True, "completed"),
        ("failed", True, "failed"),
        ("cancelled", True, "cancelled"),
        ("unknown", True, "unknown"),
    ],
)
def test_worker_lifecycle_mapping_is_explicit_and_fail_closed(
    worker: str, launched: bool, expected: str
):
    assert worker_to_episode_state(worker, launched=launched) == expected


@pytest.mark.parametrize(
    ("worker", "expected", "launched"),
    [
        ("running", "running", True),
        ("idle", "running", True),
        ("idle", "planned", False),
        ("completed", "completed", True),
        ("failed", "failed", True),
        ("cancelled", "cancelled", True),
        ("unknown", "unknown", True),
    ],
)
def test_worker_state_mapping(worker: str, expected: str, launched: bool):
    assert worker_to_episode_state(worker, launched=launched) == expected


def _request_result(episode_id: str, status: str = "completed") -> tuple[SolverRequest, SolverResult]:
    request = SolverRequest.build(
        episode_id=episode_id,
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=HEX,
        solver_id="mock",
    )
    digest = HEX
    return request, SolverResult(
        episode_id=episode_id,
        request_sha256=request.digest(),
        status=status,
        candidate_receipt_sha256=digest if status == "completed" else None,
        execution_receipt_sha256=digest if status == "completed" else None,
        official_evaluation_receipt_sha256=digest if status == "completed" else None,
        trace_digest=digest,
        solver_score=1.0 if status == "completed" else None,
        terminal_reason=f"fixture_{status}",
    )


def test_episode_result_is_request_bound_and_idempotent(tmp_path: Path):
    store = ledger(tmp_path)
    request, result = _request_result("result-episode")
    store.save_episode_result(request, result)
    store.save_episode_result(request, result)
    loaded_request, loaded_result = store.episode_result("result-episode")
    assert loaded_request.to_dict() == request.to_dict()
    assert loaded_result.to_dict() == result.to_dict()
    with pytest.raises(RSILearningError, match="rsi_episode_result_conflict"):
        store.save_episode_result(request, replace(result, terminal_reason="changed"))


def test_episode_result_rejects_request_binding_drift(tmp_path: Path):
    store = ledger(tmp_path)
    request, result = _request_result("result-drift")
    with pytest.raises(RSILearningError, match="rsi_episode_result_request_mismatch"):
        store.save_episode_result(replace(request, solver_id="other"), result)


def test_canonical_reconcile_completed_requires_persisted_complete_result(tmp_path: Path):
    store = ledger(tmp_path)
    request, result = _request_result("canonical-completed")
    episode = RSIPracticeEpisode(
        episode_id=request.episode_id,
        run_id="run-result",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=HEX,
        solver_id="mock",
        status="planned",
    ).transition("running", request_sha256=request.digest()).transition("unknown", terminal_reason="lost")
    record = store.create_episode_record(episode)
    with pytest.raises(RSILearningError, match="rsi_episode_result_missing"):
        store.reconcile_episode(
            episode.episode_id,
            worker_state="completed",
            expected_record_sha256=record.record_sha256,
            evidence={"reconciliation": {"source": "fixture"}},
            result=result,
        )
    store.save_episode_result(request, result)
    completed = store.reconcile_episode(
        episode.episode_id,
        worker_state="completed",
        expected_record_sha256=record.record_sha256,
        evidence={"reconciliation": {"source": "fixture", "receipt": True}},
        result=result,
    )
    assert completed.state == "completed"
    assert completed.payload["official_evaluation_receipt_sha256"] == HEX


def test_canonical_reconcile_failed_requires_evidence_and_preserves_no_receipt(tmp_path: Path):
    store = ledger(tmp_path)
    request, _result = _request_result("canonical-failed", status="failed")
    episode = RSIPracticeEpisode(
        episode_id=request.episode_id,
        run_id="run-failed",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=HEX,
        solver_id="mock",
        status="planned",
    ).transition("running", request_sha256=request.digest()).transition("unknown", terminal_reason="lost")
    record = store.create_episode_record(episode)
    with pytest.raises(RSILearningError, match="rsi_unknown_reconcile_evidence_required"):
        store.reconcile_episode(
            episode.episode_id,
            worker_state="failed",
            expected_record_sha256=record.record_sha256,
        )
    failed = store.reconcile_episode(
        episode.episode_id,
        worker_state="failed",
        expected_record_sha256=record.record_sha256,
        evidence={"reconciliation": {"source": "fixture", "process_exited": True}},
    )
    assert failed.state == "failed"
    assert failed.payload["official_evaluation_receipt_sha256"] is None


def test_reconciliation_journal_is_readable_and_bound_to_episode(tmp_path: Path):
    store = ledger(tmp_path)
    request, _result = _request_result("journal-failed", status="failed")
    episode = RSIPracticeEpisode(
        episode_id=request.episode_id, run_id="journal-run", contract_sha256=HEX,
        evaluator_sha256=HEX, environment_sha256=HEX, memory_snapshot_sha256=HEX,
        solver_id="mock", status="planned",
    ).transition("running", request_sha256=request.digest())
    record = store.create_episode_record(episode)
    settled = store.reconcile_episode(
        episode.episode_id, worker_state="failed", expected_record_sha256=record.record_sha256,
        evidence={"reconciliation": {"source": "fixture", "process_exited": True}},
    )
    journal = store.episode_reconciliation(episode.episode_id)
    assert len(journal) == 1
    assert journal[0]["parent_record_sha256"] == record.record_sha256
    assert journal[0]["journal_sha256"]
    assert settled.record_sha256 != record.record_sha256


def test_reconciliation_journal_tampering_fails_closed(tmp_path: Path):
    import sqlite3

    store = ledger(tmp_path)
    request, _result = _request_result("journal-tamper", status="failed")
    episode = RSIPracticeEpisode(
        episode_id=request.episode_id, run_id="journal-run", contract_sha256=HEX,
        evaluator_sha256=HEX, environment_sha256=HEX, memory_snapshot_sha256=HEX,
        solver_id="mock", status="planned",
    ).transition("running", request_sha256=request.digest())
    record = store.create_episode_record(episode)
    store.reconcile_episode(
        episode.episode_id, worker_state="failed", expected_record_sha256=record.record_sha256,
        evidence={"reconciliation": {"source": "fixture"}},
    )
    with sqlite3.connect(store.database) as connection:
        connection.execute(
            "UPDATE rsi_episode_reconciliations SET evidence = ? WHERE episode_id = ?",
            ('{"reconciliation":{"source":"tampered"}}', episode.episode_id),
        )
    with pytest.raises(RSILearningError, match="rsi_episode_reconciliation_corrupt"):
        store.episode_reconciliation(episode.episode_id)


def test_reconcile_is_atomic_when_episode_append_fails(tmp_path: Path, monkeypatch):
    store = ledger(tmp_path)
    request, _result = _request_result("journal-atomic", status="failed")
    episode = RSIPracticeEpisode(
        episode_id=request.episode_id, run_id="journal-run", contract_sha256=HEX,
        evaluator_sha256=HEX, environment_sha256=HEX, memory_snapshot_sha256=HEX,
        solver_id="mock", status="planned",
    ).transition("running", request_sha256=request.digest())
    record = store.create_episode_record(episode)
    original = store._append_episode_record_tx

    def explode(*args, **kwargs):
        raise RSILearningError("fixture_append_failure")

    monkeypatch.setattr(store, "_append_episode_record_tx", explode)
    with pytest.raises(RSILearningError, match="fixture_append_failure"):
        store.reconcile_episode(
            episode.episode_id, worker_state="failed", expected_record_sha256=record.record_sha256,
            evidence={"reconciliation": {"source": "fixture"}},
        )
    monkeypatch.setattr(store, "_append_episode_record_tx", original)
    assert store.episode_reconciliation(episode.episode_id) == ()
    assert store.get_episode(episode.episode_id).record_sha256 == record.record_sha256


def test_memory_snapshot_write_is_exactly_idempotent(tmp_path: Path):
    store = ledger(tmp_path)
    snapshot = MemorySnapshot("memory-idempotent", None, ())
    first = store.create_memory_snapshot(snapshot)
    second = store.create_memory_snapshot(snapshot)
    assert second == first


def test_worker_state_rejects_unknown_label():
    with pytest.raises(RSILearningError) as error:
        worker_to_episode_state("retrying")
    assert error.value.code == "rsi_worker_state_invalid"
