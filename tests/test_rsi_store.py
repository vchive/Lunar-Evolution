from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution import (
    RSILearningError,
    RSILedger,
    RSIPracticeEpisode,
    worker_to_episode_state,
)

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


def test_worker_state_rejects_unknown_label():
    with pytest.raises(RSILearningError) as error:
        worker_to_episode_state("retrying")
    assert error.value.code == "rsi_worker_state_invalid"
