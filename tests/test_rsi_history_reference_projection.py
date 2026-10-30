"""Exact-wire reference reuse keeps fresh complete SQL and record observations."""
from __future__ import annotations

import json
import sqlite3
import sys
from copy import deepcopy
from dataclasses import replace

import pytest
from test_rsi_admission_checkpoint_observation import SQL
from test_rsi_admission_checkpoint_observation import retained as retained_fixture

from lunar_evolution import rsi_store as store
from lunar_evolution.rsi_learning import RSILearningError


@pytest.fixture
def retained(tmp_path):
    return retained_fixture.__wrapped__(tmp_path)


class _AdmissionRow:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _FreshReads:
    def __init__(self, connection, *, change=None):
        self.connection = connection
        self.change = change
        self.history_reads = self.admission_reads = 0

    def execute(self, sql, arguments=()):
        cursor = self.connection.execute(sql, arguments)
        if sql == SQL:
            self.history_reads += 1
        elif sql.startswith("SELECT * FROM rsi_python_admissions WHERE"):
            self.admission_reads += 1
            row = cursor.fetchone()
            if row is not None and self.change is not None:
                row = dict(row)
                self.change(row)
            return _AdmissionRow(row)
        return cursor


def _observe(value, connection):
    codes = {
        "row": store.RSILedger._python_admission_row.__code__,
        "reference": store._parse_rsi_python_admission_reference_context.__code__,
        "binding": store.RSILedger._validate_history_admission_reference.__code__,
    }
    counts = dict.fromkeys((*codes, "history_json"), 0)
    decoder = json.loads.__code__
    previous = sys.getprofile()

    def profile(frame, event, _argument):
        if event != "call":
            return
        for name, code in codes.items():
            if frame.f_code is code:
                counts[name] += 1
        if frame.f_code is decoder and frame.f_locals.get("s") in value.raw_history:
            counts["history_json"] += 1

    sys.setprofile(profile)
    try:
        history = value.ledger._controller_checkpoint_history_tx(connection, value.binding.run_id)
    finally:
        sys.setprofile(previous)
    return history, counts


def test_exact_complete_reference_hit_keeps_fresh_sql_json_and_full_record_parse(retained):
    with sqlite3.connect(retained.ledger.database) as connection, retained.ledger._checkpoint_projection_scope():
        connection.row_factory = sqlite3.Row
        fresh = _FreshReads(connection)
        original, cold = _observe(retained, fresh)
        repeated, warm = _observe(retained, fresh)
        assert repeated == original
        assert fresh.history_reads == fresh.admission_reads == 2
        assert cold["history_json"] == warm["history_json"] == len(original)
        assert cold["row"] == warm["row"] == 1
        assert cold["reference"] > 0 and cold["binding"] == 1
        assert warm["reference"] == warm["binding"] == 0
        repeated[-1][1]["python_admission_refs"].clear()
        assert _observe(retained, fresh)[0] == original
        assert fresh.history_reads == fresh.admission_reads == 3


@pytest.mark.parametrize("column,value", [
    ("run_id", "different-run"), ("episode_id", "different-episode"),
    ("journal_id", "different-journal"), ("attempt_id", "different-attempt"),
    ("record_sha256", "b" * 64), ("created_at", ""),
    ("payload", None),
])
def test_all_fresh_admission_columns_remain_observed_after_reference_hit(retained, column, value):
    with sqlite3.connect(retained.ledger.database) as connection, retained.ledger._checkpoint_projection_scope():
        connection.row_factory = sqlite3.Row
        fresh = _FreshReads(connection)
        _observe(retained, fresh)
        _observe(retained, fresh)

        def change(row):
            row[column] = row["payload"] + " " if column == "payload" else value

        changed = _FreshReads(connection, change=change)
        with pytest.raises(RSILearningError):
            _observe(retained, changed)
        assert changed.history_reads == changed.admission_reads == 1


def test_valid_created_at_change_misses_pure_reference_projection_without_new_refusal(retained):
    with sqlite3.connect(retained.ledger.database) as connection, retained.ledger._checkpoint_projection_scope():
        connection.row_factory = sqlite3.Row
        original, _ = _observe(retained, _FreshReads(connection))
        connection.execute("UPDATE rsi_python_admissions SET created_at = ?", ("different-valid-text",))
        fresh = _FreshReads(connection)
        repeated, miss = _observe(retained, fresh)
        again, hit = _observe(retained, fresh)
        assert original == repeated == again
        assert miss["reference"] == miss["binding"] == 1
        assert hit["reference"] == hit["binding"] == 0
        assert miss["row"] == hit["row"] == 1


def test_mapping_admission_backend_keeps_full_reference_matching_on_every_observation(retained):
    with sqlite3.connect(retained.ledger.database) as connection, retained.ledger._checkpoint_projection_scope():
        connection.row_factory = sqlite3.Row
        original, _ = _observe(retained, _FreshReads(connection))
        fresh = _FreshReads(connection, change=lambda _row: None)
        first, miss = _observe(retained, fresh)
        second, again = _observe(retained, fresh)
        assert original == first == second
        assert miss["reference"] == again["reference"] == 1
        assert miss["binding"] == again["binding"] == 1
        assert miss["row"] == again["row"] == 1


def test_reference_comparison_cannot_escape_its_exact_checkpoint_projection(retained):
    with sqlite3.connect(retained.ledger.database) as connection, retained.ledger._checkpoint_projection_scope():
        connection.row_factory = sqlite3.Row
        original, _ = _observe(retained, _FreshReads(connection))
        cache = retained.ledger._checkpoint_projection_cache()
        key, (projection, _units) = next(reversed(cache["entries"].items()))
        assert projection.admissions and len(projection.admissions[0][1]) == 7
        assert all(type(item) is str for item in projection.admissions[0][1])
        store._retain_checkpoint_projection(cache, key, replace(projection, admissions=None))
        repeated, miss = _observe(retained, _FreshReads(connection))
        assert repeated == original and miss["reference"] == miss["binding"] == 1
    assert not cache["entries"] and cache["retained_units"] == 0
    assert retained.ledger._checkpoint_projection_local.cache is None


def test_complete_admission_text_counts_against_existing_projection_retention_bound(retained, monkeypatch):
    with retained.ledger._checkpoint_projection_scope():
        retained.ledger.controller_checkpoint_history(retained.binding.run_id)
        cache = retained.ledger._checkpoint_projection_cache()
        key, (complete, complete_units) = next(reversed(cache["entries"].items()))
        assert complete.admissions
        store._retain_checkpoint_projection(cache, key, replace(complete, admissions=None))
        history_units = cache["entries"][key][1]
        assert complete_units > history_units
        assert complete_units - history_units >= sum(
            4 * len(item) for _episode, row in complete.admissions for item in row)
        monkeypatch.setattr(store, "_HISTORY_PROJECTION_CACHE_MAX_RETAINED_UNITS", history_units)
        before = deepcopy(cache)
        store._retain_checkpoint_projection(cache, key, complete)
        assert cache == before


def test_fresh_record_helper_change_disables_reference_result_reuse(retained, monkeypatch):
    with retained.ledger._checkpoint_projection_scope():
        original = retained.ledger.controller_checkpoint_history(retained.binding.run_id)
        function = store.RSILedger._python_admission_row
        monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="changed_record_parser"))
        assert retained.ledger._checkpoint_projection_cache() is None
        with sqlite3.connect(retained.ledger.database) as connection:
            connection.row_factory = sqlite3.Row
            observed, counts = _observe(retained, _FreshReads(connection))
        assert observed == original
        assert counts["row"] == 1 and counts["reference"] > 0 and counts["binding"] == 1


def test_sqlite_row_alias_replacement_keeps_full_history_and_reference_matching(retained, monkeypatch):
    with sqlite3.connect(retained.ledger.database) as connection, retained.ledger._checkpoint_projection_scope():
        # Retain the actual immutable backend row factory before replacing the
        # public module alias. The compatibility path still sees genuine rows.
        connection.row_factory = sqlite3.Row
        original, _ = _observe(retained, _FreshReads(connection))
        monkeypatch.setattr(sqlite3, "Row", type("ForeignRow", (), {}))
        assert retained.ledger._checkpoint_projection_cache() is None
        observed, counts = _observe(retained, _FreshReads(connection))
        assert observed == original
        assert counts["row"] == 1 and counts["reference"] > 0 and counts["binding"] == 1
