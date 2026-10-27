"""Stored reserved rows use the same byte budget as their fresh raw reader."""

from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from lunar_evolution import rsi_brs_serial_finalization as finalization
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_brs_rejection_ready_ledger import _TABLES, _row_size
from lunar_evolution.rsi_brs_reserved_ledger import _read_reserved_rows
from lunar_evolution.rsi_checkpoint_storage import (
    MAX_RESERVED_CHECKPOINT_ROW_BYTES,
    canonical_checkpoint_text,
    reserved_checkpoint_payload_limit,
    reserved_run_payload_limit,
    validate_reserved_checkpoint_row,
)
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, MemoryItem, RSILearningError
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64


def _reserved_state(run_id="run-1"):
    return {
        "run_id": run_id, "mode": "brs",
        "plan": {"mode": "brs", "reserved_native_serial": True, "max_workers": 1},
        "producer_child_execution": True, "producer_multi_episode_publication": True,
        "producer_brs_checkpoint_policy": {
            "mode": "brs", "max_workers": 1, "production_admission": False, "online_publication": False,
        },
    }


@pytest.mark.parametrize("run_id", ["r", "r" * 128, "r-月"])
@pytest.mark.parametrize("parent", [None, HEX])
@pytest.mark.parametrize("prefix", ["", "é", "😀"])
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_actual_whole_row_bound_includes_metadata_and_utf8(run_id, parent, prefix, delta):
    revision = 0 if parent is None else 32
    overhead = _row_size((run_id, revision, parent, "", HEX), _TABLES[1])
    length = MAX_RESERVED_CHECKPOINT_ROW_BYTES - overhead + delta
    text = prefix + "x" * (length - len(prefix.encode("utf-8")))
    if delta > 0:
        with pytest.raises(RSILearningError, match="rsi_controller_checkpoint_capacity_exceeded"):
            validate_reserved_checkpoint_row(run_id, revision, parent, text, HEX)
    else:
        assert validate_reserved_checkpoint_row(run_id, revision, parent, text, HEX) == (
            MAX_RESERVED_CHECKPOINT_ROW_BYTES + delta)


def test_future_reservation_is_exact_for_subsequent_rows_and_bounded_run_metadata():
    run_id = "r" * 128
    limit = reserved_checkpoint_payload_limit(run_id)
    assert validate_reserved_checkpoint_row(run_id, 123, HEX, "x" * limit, HEX) == 128 * 1024
    run_row = (run_id, 123, "run", "completed", HEX, HEX,
               "x" * reserved_run_payload_limit(run_id), HEX, "2026-10-28T12:34:56.123456+00:00")
    assert _row_size(run_row, _TABLES[0]) == 128 * 1024


def _raw_rows(ledger):
    with closing(sqlite3.connect(ledger.database)) as connection:
        return tuple((spec[0], tuple(connection.execute("SELECT * FROM " + spec[0]))) for spec in _TABLES)


def test_compact_utf8_storage_removes_unbudgeted_spaces_and_ascii_escaping(tmp_path):
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    state = {**_reserved_state(), "padding": "测" * 30_000, "values": [1, 2, 3]}
    assert len(json.dumps(state, sort_keys=True).encode()) > 128 * 1024
    assert len(canonical_checkpoint_text(state).encode()) < reserved_checkpoint_payload_limit("run-1")
    with ledger.controller_lock("run-1"):
        head = ledger.write_controller_checkpoint("run-1", state, expected_sha256=None)
    with closing(sqlite3.connect(ledger.database)) as connection:
        raw, digest = connection.execute("SELECT payload,checkpoint_sha256 FROM rsi_controller_journal").fetchone()
    assert raw == canonical_checkpoint_text(state)
    assert digest == head == RSILedger._checkpoint_digest("run-1", 0, None, state)
    assert ledger.controller_checkpoint("run-1") == (head, state)
    # Exercise the actual fresh bounded raw reader, without granting semantics.
    assert _read_reserved_rows(str(ledger.database), run_id="run-1", episode_ids=("episode-1",))


@pytest.mark.parametrize("delta", [-1, 0, 1])
@pytest.mark.parametrize("writer", ["controller", "transfer"])
def test_reserved_append_exact_storage_boundary_is_atomic(tmp_path, delta, writer):
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    state = _reserved_state()
    with ledger.controller_lock("run-1"):
        head = ledger.write_controller_checkpoint("run-1", state, expected_sha256=None)
        before = _raw_rows(ledger)
        following = {**state, "padding": ""}
        needed = reserved_checkpoint_payload_limit("run-1") + delta
        following["padding"] = "x" * (needed - len(canonical_checkpoint_text(following).encode()))

        def append():
            if writer == "controller":
                return ledger.write_controller_checkpoint("run-1", following, expected_sha256=head)
            with closing(ledger._connect()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                return ledger._append_transfer_checkpoint_tx(connection, "run-1", following, expected_sha256=head)

        if delta > 0:
            with pytest.raises(RSILearningError, match="checkpoint_capacity_exceeded"):
                append()
            assert _raw_rows(ledger) == before
            assert ledger.controller_checkpoint("run-1") == (head, state)
        else:
            next_head = append()
            assert ledger.controller_checkpoint("run-1") == (next_head, following)
            _read_reserved_rows(str(ledger.database), run_id="run-1", episode_ids=("episode-1",))


def test_old_spaced_ascii_history_keeps_its_original_digest_and_raw_text(tmp_path):
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    state = {**_reserved_state(), "note": "历史"}
    with ledger.controller_lock("run-1"):
        first = ledger.write_controller_checkpoint("run-1", state, expected_sha256=None)
        legacy = json.dumps(state, sort_keys=True)
        with closing(sqlite3.connect(ledger.database)) as connection, connection:
            connection.execute("UPDATE rsi_controller_journal SET payload=? WHERE revision=0", (legacy,))
        assert ledger.controller_checkpoint("run-1") == (first, state)
        following = {**state, "note": "next"}
        second = ledger.write_controller_checkpoint("run-1", following, expected_sha256=first)
    assert ledger.controller_checkpoint_history("run-1") == [(first, state), (second, following)]
    with closing(sqlite3.connect(ledger.database)) as connection:
        assert connection.execute("SELECT payload FROM rsi_controller_journal WHERE revision=0").fetchone() == (legacy,)


def test_generic_checkpoints_keep_their_original_wider_payload_contract(tmp_path):
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    state = {"run_id": "run-1", "padding": "x" * (192 * 1024)}
    with ledger.controller_lock("run-1"):
        head = ledger.write_controller_checkpoint("run-1", state, expected_sha256=None)
    assert ledger.controller_checkpoint("run-1") == (head, state)


def _finalization_vector(*, governed=False):
    key = "episode-1"
    memory = EMPTY_MEMORY_SNAPSHOT
    state = {
        **_reserved_state(), "status": "running", "phase": "evaluated", "current_episode_id": key,
        "memory_snapshot": memory.to_dict(), "root_snapshot": memory.to_dict(), "generations": {},
        "executions": {key: {"episode_id": key}}, "budget_state": {}, "padding": "",
    }
    state["plan"]["practices"] = [{"episode_id": key}]
    execution = SimpleNamespace(passed=True, episode=SimpleNamespace(episode_id=key))
    item = MemoryItem("memory-" + key, "sorting", "trigger", "strategy", "expected", "boundary",
                      (HEX,), ("native",), "pass", HEX, key)
    ledger = SimpleNamespace(
        controller_checkpoint_history=lambda run: [
            (RSILedger._checkpoint_digest(run, 0, None, state), copy.deepcopy(state)),
        ],
        _checkpoint_digest=RSILedger._checkpoint_digest,
    )
    controller = SimpleNamespace(
        ledger=ledger, generation_regression_tasks=("holdout",) if governed else (), memory_store=None,
        _deserialize_execution=lambda _wire: execution, _decision_from_dict=lambda wire: wire,
        _memory_item=lambda _execution, _decision: item,
        _serialize_execution=lambda _execution: {"episode_id": key},
    )
    controller._flow_result = lambda planned: SimpleNamespace(
        target_attempts=(), practice_episodes=(execution,), transfer=None, current_episode_id=key,
        memory_snapshot=type(memory).from_dict(planned["memory_snapshot"]),
    )
    record = SimpleNamespace(state="running", payload={"run_id": "run-1"})
    return controller, record, state, (key,)


@pytest.mark.parametrize("governed", [False, True])
def test_known_finalization_growth_refuses_before_memory_publication(monkeypatch, governed):
    controller, record, state, domain = _finalization_vector(governed=governed)
    state["padding"] = "x" * (reserved_checkpoint_payload_limit("run-1")
                              - len(canonical_checkpoint_text(state).encode()) - 10)
    before = copy.deepcopy(state)
    calls = []
    controller._commit_flow = lambda *_args, **_kwargs: calls.append("memory")
    monkeypatch.setattr(finalization, "read_reserved_brs_finalization", lambda *_args: domain)
    with pytest.raises(RSILearningError, match="checkpoint_capacity_exceeded"):
        finalization.finalize_reserved_brs_serial(controller, record, state)
    assert calls == [] and controller.memory_store is None
    assert state == before


def test_known_finalization_tail_is_pure_repeatable_and_checks_all_planned_rows(monkeypatch):
    controller, record, state, domain = _finalization_vector()
    before = copy.deepcopy(state)
    observed = []
    from lunar_evolution import rsi_checkpoint_storage as storage

    original = storage.validate_reserved_checkpoint_row

    def capture(run_id, revision, parent, text, digest):
        observed.append((revision, json.loads(text)["phase"]))
        return original(run_id, revision, parent, text, digest)

    monkeypatch.setattr(storage, "validate_reserved_checkpoint_row", capture)
    for _ in range(2):
        finalization.preflight_reserved_brs_finalization_capacity(controller, record, state, domain)
    assert observed == [(1, "commit"), (2, "committed"), (3, "terminal")] * 2
    assert state == before and controller.memory_store is None


def test_capacity_contract_does_not_change_canonical_hash_inputs():
    value = {"unicode": "月", "spaces": [1, 2, 3]}
    assert canonical_checkpoint_text(value).encode() == canonical_json(value)
