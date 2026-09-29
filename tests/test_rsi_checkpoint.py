from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from lunar_evolution import RSILearningError, RSILedger, RSIPracticeEpisode

HEX = "a" * 64


def _ledger(tmp_path: Path) -> RSILedger:
    return RSILedger(tmp_path / "rsi.sqlite3")


def _state(**extra: object) -> dict[str, object]:
    value: dict[str, object] = {
        "phase": "target",
        "current_episode_id": "target-0",
        "contract_sha256": HEX,
        "evaluator_sha256": HEX,
        "environment_sha256": HEX,
        "memory_snapshot_sha256": HEX,
        "solver_id": "mock",
        "budget": {"max_depth": 3, "max_target_attempts": 2},
        "consumed": {"depth": 0, "target_attempts": 0},
    }
    value.update(extra)
    return value


def test_controller_checkpoint_is_append_only_and_cas_protected(tmp_path: Path) -> None:
    store = _ledger(tmp_path)
    assert store.controller_checkpoint("run-1") is None
    with store.controller_lock("run-1"):
        first = store.write_controller_checkpoint("run-1", _state(), expected_sha256=None)
        second = store.write_controller_checkpoint(
            "run-1", _state(consumed={"depth": 1, "target_attempts": 1}), expected_sha256=first
        )

    assert store.controller_checkpoint("run-1") == (
        second,
        _state(consumed={"depth": 1, "target_attempts": 1}),
    )
    assert [digest for digest, _payload in store.controller_checkpoint_history("run-1")] == [
        first,
        second,
    ]
    with store.controller_lock("run-1"), pytest.raises(
        RSILearningError, match="rsi_controller_checkpoint_conflict"
    ):
        store.write_controller_checkpoint("run-1", _state(), expected_sha256=first)


def test_checkpoint_requires_lock_and_canonical_payload(tmp_path: Path) -> None:
    store = _ledger(tmp_path)
    with pytest.raises(RSILearningError, match="rsi_controller_lock_required"):
        store.write_controller_checkpoint("run-1", _state(), expected_sha256=None)

    with store.controller_lock("run-1"), pytest.raises(
        RSILearningError, match="rsi_controller_checkpoint_invalid"
    ):
        store.write_controller_checkpoint("run-1", {"bad": float("nan")}, expected_sha256=None)


def test_controller_lock_is_nonblocking_and_releases_after_scope(tmp_path: Path) -> None:
    store = _ledger(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    errors: list[str] = []

    def hold() -> None:
        with store.controller_lock("run-lock"):
            entered.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=hold)
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(RSILearningError, match="rsi_controller_busy"), store.controller_lock("run-lock"):
        errors.append("unexpected")
    release.set()
    thread.join(timeout=5)
    assert not errors
    with store.controller_lock("run-lock"):
        digest = store.write_controller_checkpoint("run-lock", _state(), expected_sha256=None)
    assert store.controller_checkpoint("run-lock")[0] == digest


def test_queries_return_typed_records_and_episode_ids(tmp_path: Path) -> None:
    store = _ledger(tmp_path)
    run = store.create_run("query-run", HEX, {"mode": "drs"})
    assert store.get_run("query-run") == run
    assert store.get_episode("missing") is None
    assert store.get_transfer("query-run", "target") is None
    episode = RSIPracticeEpisode(
        episode_id="query-target",
        run_id="query-run",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=HEX,
        solver_id="mock",
        status="planned",
    ).transition("running", request_sha256=HEX)
    store.create_episode_record(episode)
    assert store.get_episode(episode.episode_id).logical_id == episode.episode_id
    assert store.episode_ids_for_run("query-run") == (episode.episode_id,)


def test_canonical_episode_rejects_generic_transition_and_reconcile(tmp_path: Path) -> None:
    store = _ledger(tmp_path)
    episode = RSIPracticeEpisode(
        episode_id="canonical-target",
        run_id="canonical-run",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=HEX,
        solver_id="mock",
        status="planned",
    ).transition("running", request_sha256=HEX)
    record = store.create_episode_record(episode)
    with pytest.raises(RSILearningError, match="rsi_episode_canonical_transition_required"):
        store.transition(episode.episode_id, state="unknown", expected_record_sha256=record.record_sha256)
    with pytest.raises(RSILearningError, match="rsi_episode_canonical_reconcile_required"):
        store.reconcile_worker(
            episode.episode_id,
            worker_state="unknown",
            expected_record_sha256=record.record_sha256,
        )


def test_history_detects_record_digest_tampering(tmp_path: Path) -> None:
    store = _ledger(tmp_path)
    record = store.create_run("tamper-run", HEX, {})
    with sqlite3.connect(store.database) as connection:
        connection.execute(
            "UPDATE rsi_records SET payload = ? WHERE logical_id = ? AND revision = 0",
            ('{"tampered":true}', record.logical_id),
        )
    with pytest.raises(RSILearningError, match="rsi_record_digest_mismatch"):
        store.get_run(record.logical_id)
