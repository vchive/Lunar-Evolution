"""Fresh admission rows keep the complete parser and exact SQLite text boundary."""

import json
import sqlite3

import pytest
from test_rsi_python_admission import _register, _setup

import lunar_evolution.rsi_store as store_module
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_admission import (
    RSIPythonAdmissionRecord,
    parse_rsi_python_admission_record,
)


@pytest.fixture
def retained(tmp_path):
    value = _setup(tmp_path)
    _register(value)
    return value


def _row(value):
    with sqlite3.connect(value.ledger.database) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute("SELECT * FROM rsi_python_admissions").fetchone()


def _replace(value, column, replacement):
    with sqlite3.connect(value.ledger.database) as connection:
        connection.execute(f"UPDATE rsi_python_admissions SET {column} = ?", (replacement,))


def _assert_corrupt(ledger, row):
    with pytest.raises(RSILearningError) as error:
        ledger._python_admission_row(row)
    assert error.value.code == "rsi_python_admission_record_corrupt"


def test_fresh_sqlite_text_runs_full_parser_without_extra_dto_serialization(retained, monkeypatch):
    row = _row(retained)
    assert type(row["payload"]) is str
    original = RSIPythonAdmissionRecord.to_json
    serializations = []

    def counted(record):
        serializations.append(record)
        return original(record)

    monkeypatch.setattr(RSIPythonAdmissionRecord, "to_json", counted)
    expected = parse_rsi_python_admission_record(row["payload"])
    parser_serializations = len(serializations)
    assert parser_serializations > 0
    serializations.clear()
    parsed_inputs = []

    def parse(raw):
        parsed_inputs.append(raw)
        return parse_rsi_python_admission_record(raw)

    monkeypatch.setattr(store_module, "parse_rsi_python_admission_record", parse)
    assert retained.ledger._python_admission_row(_row(retained)) == expected
    assert parsed_inputs == [row["payload"]]
    assert len(serializations) == parser_serializations


def test_canonical_blob_remains_invalid_for_sqlite_text_column(retained):
    raw = _row(retained)["payload"]
    assert parse_rsi_python_admission_record(raw.encode("utf-8"))
    _replace(retained, "payload", sqlite3.Binary(raw.encode("utf-8")))
    row = _row(retained)
    assert type(row["payload"]) is bytes
    _assert_corrupt(retained.ledger, row)


@pytest.mark.parametrize("replacement", [None, 1, True, {}, []])
def test_non_text_row_value_keeps_fixed_refusal(retained, replacement):
    row = dict(_row(retained))
    row["payload"] = replacement
    _assert_corrupt(retained.ledger, row)


@pytest.mark.parametrize("mutation", ["noncanonical", "same_length", "digest", "duplicate"])
def test_fresh_row_payload_drift_is_still_rejected_after_valid_read(retained, mutation):
    row = _row(retained)
    assert retained.ledger._python_admission_row(row)
    raw = row["payload"]
    if mutation == "noncanonical":
        changed = json.dumps(json.loads(raw))
    elif mutation == "same_length":
        changed = raw.replace('"production_admission":false', '"production_admission":true ')
        assert len(changed) == len(raw) and changed != raw
    elif mutation == "digest":
        wire = json.loads(raw)
        wire["record_sha256"] = "b" * 64
        changed = json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        changed = raw[:-1] + ',"production_admission":false}'
    _replace(retained, "payload", changed)
    _assert_corrupt(retained.ledger, _row(retained))


@pytest.mark.parametrize(("column", "replacement"), [
    ("run_id", "other"), ("episode_id", "other"), ("journal_id", "other"),
    ("attempt_id", "other"), ("record_sha256", "b" * 64), ("created_at", " "),
])
def test_fresh_independent_row_identity_still_binds_parsed_record(retained, column, replacement):
    assert retained.ledger._python_admission_row(_row(retained))
    _replace(retained, column, replacement)
    _assert_corrupt(retained.ledger, _row(retained))
