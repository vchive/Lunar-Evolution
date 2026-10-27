"""Real SQLite connections close independently of cyclic garbage collection."""

from __future__ import annotations

import gc
import sqlite3
from contextlib import closing, nullcontext

import pytest

from lunar_evolution import rsi_store
from lunar_evolution.rsi_learning import RSILearningError

HEX = "a" * 64


class InjectedFailure(RuntimeError):
    pass


@pytest.fixture
def tracked_sqlite(monkeypatch):
    original = sqlite3.connect
    retained = []
    options = {"fail_statement": None, "fail_close": False}
    enabled = gc.isenabled()
    gc.disable()

    class Connection(sqlite3.Connection):
        def execute(self, statement, *args, **kwargs):
            cursor = super().execute(statement, *args, **kwargs)
            if statement.startswith(options["fail_statement"] or "\0"):
                raise InjectedFailure("injected statement failure")
            return cursor

        def __exit__(self, *args):
            try:
                return super().__exit__(*args)
            finally:
                self.events.append("transaction_exit")

        def close(self):
            try:
                return super().close()
            finally:
                self.events.append("close")
                if options["fail_close"]:
                    raise InjectedFailure("injected close failure")

    def connect(*args, **kwargs):
        connection = original(*args, **kwargs, factory=Connection)
        connection.events = []
        connection.connect_args = (args, kwargs)
        retained.append(connection)  # Keep cycles and strong references alive.
        return connection

    monkeypatch.setattr(rsi_store.sqlite3, "connect", connect)
    try:
        yield retained, options, original
    finally:
        for connection in retained:
            sqlite3.Connection.close(connection)
        if enabled:
            gc.enable()


def assert_closed(connections, *, transaction=True):
    assert connections
    for connection in connections:
        assert connection.events == (["transaction_exit", "close"] if transaction else ["close"])
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            sqlite3.Connection.execute(connection, "SELECT 1")


def test_schema_write_and_materialized_reads_close_without_gc(tmp_path, tracked_sqlite):
    connections, _, original = tracked_sqlite
    ledger = rsi_store.RSILedger(tmp_path / "rsi.db")
    assert_closed(connections)
    record = ledger.create_run("run", HEX, {"mode": "drs"})
    assert_closed(connections)
    assert ledger.get_run("run") == record
    assert ledger.history("run") == (record,)
    assert ledger.controller_checkpoint_history("run") == []
    assert ledger.get("missing") is None
    assert_closed(connections)
    assert len(connections) >= 6
    assert len({id(connection) for connection in connections}) == len(connections)
    with closing(original(ledger.database)) as check:
        assert check.execute("SELECT state FROM rsi_records").fetchall() == [("created",)]
    # Returned record payloads are detached and usable after the connection closes.
    assert record.payload == {"mode": "drs"}


def test_readonly_observations_remain_fresh_query_only_and_close(tmp_path, tracked_sqlite):
    connections, _, _ = tracked_sqlite
    ledger = rsi_store.RSILedger(tmp_path / "rsi.db")
    record = ledger.create_run("run", HEX, {})
    start = len(connections)
    with ledger.read_only_observations():
        assert ledger.get_run("run") == record
        assert ledger.history("run") == (record,)
        assert ledger.controller_checkpoint_history("run") == []
        assert ledger._observation_scope.depth == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            ledger.create_run("forbidden", HEX, {})
    observed = connections[start:]
    assert len(observed) == 4
    assert all(c.connect_args[0][0].endswith("?mode=ro") for c in observed)
    assert_closed(observed)
    assert ledger._observation_scope.depth == 0


def test_combined_terminal_snapshot_failure_restores_scope_and_closes(tmp_path, tracked_sqlite):
    connections, _, _ = tracked_sqlite
    ledger = rsi_store.RSILedger(tmp_path / "rsi.db")
    with pytest.raises(RSILearningError, match="rsi_brs_terminal_root_missing"):
        ledger.read_brs_terminal_evidence_snapshot("missing-run", "missing-episode")
    assert connections[-1].connect_args[0][0].endswith("?mode=ro")
    assert ledger._observation_scope.depth == 0
    assert_closed(connections)
    assert ledger.create_run("subsequent-write", HEX, {}).state == "created"
    assert_closed(connections)


def test_duplicate_refusal_closes_after_rollback(tmp_path, tracked_sqlite):
    connections, _, _ = tracked_sqlite
    ledger = rsi_store.RSILedger(tmp_path / "rsi.db")
    original = ledger.create_run("run", HEX, {})
    with pytest.raises(RSILearningError, match="rsi_record_exists"):
        ledger.create_run("run", HEX, {})
    assert_closed(connections)
    assert ledger.history("run") == (original,)


def test_exception_after_real_insert_rolls_back_before_close(tmp_path, tracked_sqlite):
    connections, options, original = tracked_sqlite
    ledger = rsi_store.RSILedger(tmp_path / "rsi.db")
    options["fail_statement"] = "INSERT INTO rsi_records"
    with pytest.raises(InjectedFailure, match="injected statement failure"):
        ledger.create_run("run", HEX, {})
    assert_closed(connections)
    options["fail_statement"] = None
    with closing(original(ledger.database)) as check:
        assert check.execute("SELECT COUNT(*) FROM rsi_records").fetchone()[0] == 0
    assert ledger.create_run("run", HEX, {}).state == "created"
    assert_closed(connections)


def test_corrupt_history_refuses_and_closes_readonly_connection(tmp_path, tracked_sqlite):
    connections, _, original = tracked_sqlite
    ledger = rsi_store.RSILedger(tmp_path / "rsi.db")
    ledger.create_run("run", HEX, {})
    with closing(original(ledger.database)) as check, check:
        check.execute("UPDATE rsi_records SET record_sha256 = ?", ("b" * 64,))
    with ledger.read_only_observations(), pytest.raises(RSILearningError, match="rsi_record_digest_mismatch"):
        ledger.history("run")
    assert_closed(connections)


@pytest.mark.parametrize("readonly", [False, True])
@pytest.mark.parametrize("close_failure", [False, True])
def test_connection_configuration_failure_closes_and_preserves_original(
    tmp_path, tracked_sqlite, readonly, close_failure,
):
    connections, options, _ = tracked_sqlite
    ledger = rsi_store.RSILedger(tmp_path / "rsi.db")
    options["fail_statement"] = "PRAGMA query_only" if readonly else "PRAGMA journal_mode"
    options["fail_close"] = close_failure
    start = len(connections)
    with (
        ledger.read_only_observations() if readonly else nullcontext(),
        pytest.raises(InjectedFailure, match="injected statement failure"),
    ):
        ledger._connect()
    options["fail_close"] = False
    assert_closed(connections[start:], transaction=False)
