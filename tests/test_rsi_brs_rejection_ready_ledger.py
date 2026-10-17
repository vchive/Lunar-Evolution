"""Real local SQLite checks; raw comparison data is not semantically valid RSI evidence."""

from __future__ import annotations

import hashlib
import sqlite3
from threading import Event, Thread

import pytest

from lunar_evolution.rsi_brs_rejection_ready_ledger import (
    assert_rejection_ready_rows,
    read_rejection_ready_rows,
)
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger

_RUN = "run-a"
_EPISODES = ("episode-a", "episode-empty", "episode-ref")
_SCHEMA = """
CREATE TABLE rsi_records (logical_id TEXT,revision INTEGER,kind TEXT,state TEXT,
request_sha256 TEXT,parent_record_sha256 TEXT,payload TEXT,record_sha256 TEXT,created_at TEXT,
PRIMARY KEY(logical_id,revision));
CREATE TABLE rsi_controller_journal (run_id TEXT,revision INTEGER,parent_sha256 TEXT,
payload TEXT,checkpoint_sha256 TEXT,PRIMARY KEY(run_id,revision));
CREATE TABLE rsi_python_admissions (run_id TEXT,episode_id TEXT,journal_id TEXT,attempt_id TEXT,
payload TEXT,record_sha256 TEXT,created_at TEXT,PRIMARY KEY(run_id,episode_id,journal_id));
CREATE TABLE rsi_native_episode_claims (episode_id TEXT PRIMARY KEY,request_sha256 TEXT,
plan_sha256 TEXT,claim_sha256 TEXT,created_at TEXT);
CREATE TABLE rsi_episode_results (episode_id TEXT PRIMARY KEY,request_sha256 TEXT,
request_payload TEXT,result_payload TEXT,result_sha256 TEXT,created_at TEXT);
CREATE TABLE rsi_episode_reconciliations (episode_id TEXT,revision INTEGER,
parent_record_sha256 TEXT,worker_state TEXT,evidence TEXT,result_sha256 TEXT,
journal_sha256 TEXT,created_at TEXT,PRIMARY KEY(episode_id,revision));
"""
_ROWS = {
    "rsi_records": (
        (_RUN, 0, "run", "created", "request", None, '{"proof":"original"}', "run-0", "time-0"),
        (_RUN, 1, "run", "running", "request", "run-0", "{}", "run-1", "time-1"),
        ("episode-a", 0, "episode", "running", "request", None, "{}", "episode-0", "time-0"),
    ),
    "rsi_controller_journal": (
        (_RUN, 0, None, '{"staging":"original"}', "checkpoint-0"),
        (_RUN, 1, "checkpoint-0", '{"rejection_provenance":"held"}', "checkpoint-1"),
    ),
    "rsi_python_admissions": (
        (_RUN, "episode-a", "journal-a", "attempt-a", '{"anchor":"original"}', "admission-a", "time-0"),
        (_RUN, "episode-ref", "journal-ref", "attempt-ref", "{}", "admission-ref", "time-0"),
    ),
    "rsi_native_episode_claims": (("episode-a", "request", "plan", "claim", "time-0"),),
    "rsi_episode_results": (),
    "rsi_episode_reconciliations": (
        ("episode-a", 0, "episode-0", "running", '{"original":true}', None, "reconcile-0", "time-0"),
    ),
}


def _database(tmp_path, *, schema=_SCHEMA):
    path = tmp_path / "ledger ?#%.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(schema)
        for table, rows in _ROWS.items():
            for row in rows:
                connection.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in row)})", row)
    return path


def _capture(path):
    return read_rejection_ready_rows(str(path), run_id=_RUN, episode_ids=_EPISODES)


def _files(directory):
    return {path.name: (path.stat().st_ino, path.stat().st_mode,
                        hashlib.sha256(path.read_bytes()).hexdigest()) for path in directory.iterdir()}


def test_same_complete_rows_and_absent_domains_are_read_only(tmp_path):
    path = _database(tmp_path)
    before = _files(tmp_path)
    snapshot = _capture(path)
    assert_rejection_ready_rows(str(path), snapshot)
    assert snapshot[2] == tuple(sorted(_EPISODES))
    assert dict(snapshot[4])["rsi_episode_results"] == ()
    assert len(dict(snapshot[4])["rsi_records"]) == 3
    assert _files(tmp_path) == before


def test_compatible_with_actual_initialized_ledger_schema(tmp_path):
    # This is comparison data, not a semantically validated RSI/owner fixture.
    ledger = RSILedger(tmp_path / "real-ledger.sqlite3")
    ledger.create_run(_RUN, "a" * 64, {"proof": "opaque"})
    snapshot = read_rejection_ready_rows(str(ledger.database), run_id=_RUN, episode_ids=_EPISODES)
    assert len(dict(snapshot[4])["rsi_records"]) == 1
    assert dict(snapshot[4])["rsi_records"][0][2:4] == ("run", "created")
    assert_rejection_ready_rows(str(ledger.database), snapshot)


@pytest.mark.parametrize("table,column", [
    ("rsi_records", "payload"), ("rsi_records", "created_at"),
    ("rsi_controller_journal", "payload"), ("rsi_controller_journal", "parent_sha256"),
    ("rsi_python_admissions", "payload"), ("rsi_python_admissions", "created_at"),
    ("rsi_native_episode_claims", "claim_sha256"),
    ("rsi_episode_reconciliations", "evidence"),
])
def test_raw_column_changes_reject_even_without_digest_change(tmp_path, table, column):
    path = _database(tmp_path)
    snapshot = _capture(path)
    with sqlite3.connect(path) as connection:
        connection.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = (SELECT min(rowid) FROM {table})",
                           ("changed",))
    before = _files(tmp_path)
    with pytest.raises(RSILearningError, match="rows_changed"):
        assert_rejection_ready_rows(str(path), snapshot)
    assert _files(tmp_path) == before


@pytest.mark.parametrize("table", [name for name, rows in _ROWS.items() if rows])
def test_deletion_from_any_held_table_rejects(tmp_path, table):
    path = _database(tmp_path)
    snapshot = _capture(path)
    with sqlite3.connect(path) as connection:
        connection.execute(f"DELETE FROM {table} WHERE rowid = (SELECT min(rowid) FROM {table})")
    with pytest.raises(RSILearningError, match="rows_changed"):
        assert_rejection_ready_rows(str(path), snapshot)


@pytest.mark.parametrize("table,row", [
    ("rsi_records", ("episode-empty", 0, "episode", "running", "r", None, "{}", "new", "now")),
    ("rsi_controller_journal", (_RUN, 2, "checkpoint-1", "{}", "checkpoint-2")),
    ("rsi_python_admissions", (_RUN, "episode-empty", "new", "new", "{}", "new", "now")),
    ("rsi_native_episode_claims", ("episode-empty", "r", "p", "c", "now")),
    ("rsi_episode_results", ("episode-a", "r", "{}", "{}", "result", "now")),
    ("rsi_episode_reconciliations", ("episode-empty", 0, "head", "running", "{}", None, "new", "now")),
])
def test_insert_into_original_or_absent_domain_rejects(tmp_path, table, row):
    path = _database(tmp_path)
    snapshot = _capture(path)
    with sqlite3.connect(path) as connection:
        connection.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in row)})", row)
    with pytest.raises(RSILearningError, match="rows_changed"):
        assert_rejection_ready_rows(str(path), snapshot)


def test_unrelated_run_rows_are_outside_frozen_domain(tmp_path):
    path = _database(tmp_path)
    snapshot = _capture(path)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO rsi_records VALUES (?,?,?,?,?,?,?,?,?)",
                           ("unrelated", 0, "run", "running", "r", None, "{}", "other", "now"))
    assert_rejection_ready_rows(str(path), snapshot)


def test_admission_outside_frozen_closure_is_not_discovered(tmp_path):
    path = _database(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO rsi_python_admissions VALUES (?,?,?,?,?,?,?)",
                           (_RUN, "foreign-episode", "j", "a", "{}", "r", "now"))
    with pytest.raises(RSILearningError, match="domain_invalid"):
        _capture(path)


@pytest.mark.parametrize("episodes", [(_RUN,), (), ["episode-a"], ("episode-a", "episode-a"),
                                      (1,), ("bad\x00id",)])
def test_invalid_or_colliding_domain_refuses_without_opening(tmp_path, episodes):
    path = tmp_path / "not-created.sqlite3"
    with pytest.raises(RSILearningError, match="domain_invalid"):
        read_rejection_ready_rows(str(path), run_id=_RUN, episode_ids=episodes)
    assert not path.exists()


@pytest.mark.parametrize("missing", ["database", "parent", "table"])
def test_missing_database_parent_or_table_is_not_created_or_repaired(tmp_path, missing):
    path = _database(tmp_path)
    snapshot = _capture(path)
    if missing == "database":
        path.unlink()
    elif missing == "parent":
        path.unlink()
        path = tmp_path / "absent-parent" / path.name
    else:
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TABLE rsi_episode_results")
    before = _files(tmp_path)
    with pytest.raises(RSILearningError, match="read_failed|path_changed|schema_changed"):
        if missing == "parent":
            _capture(path)
        else:
            assert_rejection_ready_rows(str(path), snapshot)
    assert _files(tmp_path) == before


def test_integer_real_drift_is_not_hidden_by_python_equality(tmp_path):
    path = _database(tmp_path, schema=_SCHEMA.replace("revision INTEGER", "revision"))
    snapshot = _capture(path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE rsi_records SET revision = 1.0 WHERE logical_id = ? AND revision = 1", (_RUN,))
        assert connection.execute("SELECT typeof(revision) FROM rsi_records WHERE revision = 1").fetchone() == ("real",)
    with pytest.raises(RSILearningError, match="row_invalid"):
        assert_rejection_ready_rows(str(path), snapshot)


def test_forged_real_in_expected_snapshot_refuses_before_equality(tmp_path):
    path = _database(tmp_path)
    path_value, run_id, episodes, schema, groups = _capture(path)
    name, rows = groups[0]
    first = (*rows[0][:1], float(rows[0][1]), *rows[0][2:])
    malformed = (path_value, run_id, episodes, schema, ((name, (first, *rows[1:])), *groups[1:]))
    with pytest.raises(RSILearningError, match="row_invalid"):
        assert_rejection_ready_rows(str(path), malformed)


def test_too_many_rows_are_bounded(tmp_path):
    path = _database(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.executemany("INSERT INTO rsi_records VALUES (?,?,?,?,?,?,?,?,?)", (
            (_RUN, revision, "run", "running", "r", "p", "{}", f"row-{revision}", "now")
            for revision in range(2, 4097)
        ))
    with pytest.raises(RSILearningError, match="capacity_exceeded"):
        _capture(path)


def test_oversized_row_and_total_bytes_are_bounded(tmp_path):
    path = _database(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE rsi_records SET payload = ? WHERE logical_id = ? AND revision = 0",
                           ("x" * (128 * 1024), _RUN))
    with pytest.raises(RSILearningError, match="capacity_exceeded"):
        _capture(path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE rsi_records SET payload = '{}' WHERE logical_id = ? AND revision = 0", (_RUN,))
        connection.executemany("INSERT INTO rsi_records VALUES (?,?,?,?,?,?,?,?,?)", (
            (_RUN, revision, "run", "running", "r", "p", "x" * 125_000, f"row-{revision}", "now")
            for revision in range(2, 140)
        ))
    with pytest.raises(RSILearningError, match="capacity_exceeded"):
        _capture(path)


def test_wal_committed_rows_are_read_and_late_change_rejected(tmp_path):
    path = _database(tmp_path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("UPDATE rsi_records SET payload = ? WHERE logical_id = ? AND revision = 0",
                           ('{"wal":"held"}', _RUN))
        connection.commit()
        before = (path.read_bytes(), path.with_name(path.name + "-wal").read_bytes())
        snapshot = _capture(path)
        assert dict(snapshot[4])["rsi_records"][-2][6] == '{"wal":"held"}'
        assert_rejection_ready_rows(str(path), snapshot)
        assert (path.read_bytes(), path.with_name(path.name + "-wal").read_bytes()) == before
        connection.execute("UPDATE rsi_records SET payload = ? WHERE logical_id = ? AND revision = 0",
                           ('{"wal":"changed"}', _RUN))
        connection.commit()
        with pytest.raises(RSILearningError, match="rows_changed"):
            assert_rejection_ready_rows(str(path), snapshot)
    finally:
        connection.close()


@pytest.mark.parametrize("view", [False, True])
def test_same_rows_cannot_hide_table_to_view_or_schema_change(tmp_path, view):
    path = _database(tmp_path)
    snapshot = _capture(path)
    with sqlite3.connect(path) as connection:
        if view:
            connection.execute("DROP TABLE rsi_native_episode_claims")
            connection.execute("CREATE VIEW rsi_native_episode_claims AS SELECT "
                               "'episode-a' AS episode_id,'request' AS request_sha256,"
                               "'plan' AS plan_sha256,'claim' AS claim_sha256,'time-0' AS created_at")
        else:
            connection.execute("ALTER TABLE rsi_records ADD COLUMN unexpected TEXT")
    with pytest.raises(RSILearningError, match="schema_changed"):
        assert_rejection_ready_rows(str(path), snapshot)


def test_virtual_table_is_not_a_capture_source(tmp_path):
    path = _database(tmp_path)
    with sqlite3.connect(path) as connection:
        if not connection.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0]:
            pytest.skip("SQLite build has no FTS5 virtual-table module")
        connection.execute("DROP TABLE rsi_episode_results")
        connection.execute("CREATE VIRTUAL TABLE rsi_episode_results USING fts5(episode_id)")
    with pytest.raises(RSILearningError, match="schema_changed"):
        _capture(path)


@pytest.mark.parametrize("value", [-(2**63) - 1, 2**63, True])
def test_held_integer_domain_is_exact_signed64(tmp_path, value):
    path = _database(tmp_path)
    path_value, run_id, episodes, schema, groups = _capture(path)
    name, rows = groups[0]
    first = (rows[0][0], value, *rows[0][2:])
    with pytest.raises(RSILearningError, match="row_invalid"):
        assert_rejection_ready_rows(str(path),
                                    (path_value, run_id, episodes, schema,
                                     ((name, (first, *rows[1:])), *groups[1:])))


@pytest.mark.parametrize("value", [-(2**63), 2**63 - 1])
def test_sqlite_signed64_boundary_values_remain_exact(tmp_path, value):
    path = _database(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE rsi_records SET revision = ? WHERE logical_id = ? AND revision = 1",
                           (value, _RUN))
    snapshot = _capture(path)
    assert_rejection_ready_rows(str(path), snapshot)


@pytest.mark.parametrize("schema_value", [False, True])
def test_held_invalid_unicode_has_fixed_refusal(tmp_path, schema_value):
    path = _database(tmp_path)
    path_value, run_id, episodes, schema, groups = _capture(path)
    if schema_value:
        schema = ((*schema[0][:-1], "\ud800"), *schema[1:])
    else:
        name, rows = groups[0]
        first = (*rows[0][:6], "\ud800", *rows[0][7:])
        groups = ((name, (first, *rows[1:])), *groups[1:])
    with pytest.raises(RSILearningError, match="row_invalid"):
        assert_rejection_ready_rows(str(path), (path_value, run_id, episodes, schema, groups))


def test_held_text_size_is_bounded_before_encoding(tmp_path):
    path = _database(tmp_path)
    path_value, run_id, episodes, schema, groups = _capture(path)
    name, rows = groups[0]
    first = (*rows[0][:6], "x" * (128 * 1024 + 1), *rows[0][7:])
    with pytest.raises(RSILearningError, match="capacity_exceeded"):
        assert_rejection_ready_rows(str(path),
                                    (path_value, run_id, episodes, schema,
                                     ((name, (first, *rows[1:])), *groups[1:])))


@pytest.mark.parametrize("kind", [str, int])
def test_held_primitive_subclasses_reject_before_comparison(tmp_path, kind):
    calls = []

    class Foreign(kind):
        def __eq__(self, other):
            calls.append("eq")
            raise AssertionError("foreign equality")

    path = _database(tmp_path)
    path_value, run_id, episodes, schema, groups = _capture(path)
    name, rows = groups[0]
    first = list(rows[0])
    index = 0 if kind is str else 1
    first[index] = Foreign(first[index])
    with pytest.raises(RSILearningError, match="row_invalid"):
        assert_rejection_ready_rows(str(path),
                                    (path_value, run_id, episodes, schema,
                                     ((name, (tuple(first), *rows[1:])), *groups[1:])))
    assert calls == []


@pytest.mark.parametrize("blob", [False, True])
def test_large_late_insert_is_rejected_before_full_python_value(tmp_path, blob):
    path = _database(tmp_path)
    snapshot = _capture(path)
    with sqlite3.connect(path) as connection:
        payload = b"x" * (4 * 1024 * 1024) if blob else "x" * (4 * 1024 * 1024)
        connection.execute("INSERT INTO rsi_records VALUES (?,?,?,?,?,?,?,?,?)",
                           (_RUN, 2, "run", "running", "r", "p", payload, "late", "now"))
    with pytest.raises(RSILearningError, match="capacity_exceeded"):
        assert_rejection_ready_rows(str(path), snapshot)


def test_read_failure_releases_transaction_for_next_writer(tmp_path):
    path = _database(tmp_path)
    snapshot = _capture(path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE rsi_records SET payload = 'changed' WHERE logical_id = ?", (_RUN,))
    with pytest.raises(RSILearningError, match="rows_changed"):
        assert_rejection_ready_rows(str(path), snapshot)
    with sqlite3.connect(path, timeout=0) as connection:
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute("UPDATE rsi_records SET payload = '{}' WHERE logical_id = ?", (_RUN,))


def test_six_groups_share_one_wal_read_snapshot(tmp_path, monkeypatch):
    path = _database(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("UPDATE rsi_records SET payload = 'old' WHERE logical_id = ?", (_RUN,))
        connection.execute("UPDATE rsi_controller_journal SET payload = 'old' WHERE run_id = ?", (_RUN,))
    real_connect = sqlite3.connect
    change, committed, errors = Event(), Event(), []

    def writer():
        try:
            assert change.wait(5)
            with real_connect(path) as connection:
                connection.execute("UPDATE rsi_records SET payload = 'new' WHERE logical_id = ?", (_RUN,))
                connection.execute("UPDATE rsi_controller_journal SET payload = 'new' WHERE run_id = ?", (_RUN,))
        except (AssertionError, sqlite3.Error) as exc:
            errors.append(exc)
        finally:
            committed.set()

    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)

        def trace(sql):
            # Test-only native trace instrumentation: publish a real atomic WAL change
            # between the helper's records and journal SELECTs, without a product seam.
            if " FROM rsi_controller_journal " in sql and not change.is_set():
                change.set()
                assert committed.wait(5)

        connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    thread = Thread(target=writer)
    thread.start()
    try:
        groups = dict(_capture(path)[4])
        assert change.is_set() and committed.is_set()
        assert {row[6] for row in groups["rsi_records"] if row[0] == _RUN} == {"old"}
        assert {row[3] for row in groups["rsi_controller_journal"]} == {"old"}
        groups = dict(_capture(path)[4])
        assert {row[6] for row in groups["rsi_records"] if row[0] == _RUN} == {"new"}
        assert {row[3] for row in groups["rsi_controller_journal"]} == {"new"}
    finally:
        change.set()
        thread.join(5)
    assert not thread.is_alive()
    assert errors == []
