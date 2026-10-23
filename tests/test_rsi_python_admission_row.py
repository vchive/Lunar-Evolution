"""Fresh admission rows keep the complete parser and exact SQLite text boundary."""

import json
import sqlite3
from copy import deepcopy

import pytest
from test_rsi_python_admission import _register, _setup
from test_rsi_python_admission_flow import _pin

import lunar_evolution.rsi_python_admission as admission_module
import lunar_evolution.rsi_store as store_module
from lunar_evolution.producer_bundle_publication import ProducerBundlePublicationJournal
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
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


def test_history_admission_seam_reuses_only_call_local_parsed_reference_context(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    _register(value)
    _pin(value)
    checkpoint_sha256, checkpoint_state = value.ledger.controller_checkpoint(value.binding.run_id)
    with value.ledger.controller_lock(value.binding.run_id):
        checkpoint_state["followup_marker"] = "final-reference-head"
        value.ledger.write_controller_checkpoint(
            value.binding.run_id, checkpoint_state, expected_sha256=checkpoint_sha256,
        )

    source_references = deepcopy(checkpoint_state["python_admission_refs"])
    public_contexts = []
    original_reference_map_parser = admission_module._parse_rsi_python_admission_references_with_context

    def observe_public_parser(wire, *, retain_context=False):
        references, contexts = original_reference_map_parser(wire, retain_context=retain_context)
        public_contexts.append((retain_context, len(contexts)))
        return references, contexts

    monkeypatch.setattr(
        admission_module,
        "_parse_rsi_python_admission_references_with_context",
        observe_public_parser,
    )
    public_result = admission_module.parse_rsi_python_admission_references(source_references)
    episode_id = value.episode_id
    assert type(public_result) is dict and type(public_result[episode_id]) is dict
    assert public_result == source_references
    assert public_result[episode_id] is not source_references[episode_id]
    assert public_result[episode_id]["native_plan"] is not source_references[episode_id]["native_plan"]
    assert public_contexts == [(False, 0)]

    counts = {"plan": 0, "journal": 0, "record_json": 0, "row": 0}
    history_contexts = []

    original_plan_from_dict = NativeRSIExecutionPlan.from_dict.__func__
    original_journal_from_dict = ProducerBundlePublicationJournal.from_dict.__func__
    original_record_from_json = RSIPythonAdmissionRecord.from_json.__func__
    original_row = value.ledger._python_admission_row
    original_history_parser = store_module._parse_rsi_python_admission_references_with_context

    def count_plan(cls, wire):
        counts["plan"] += 1
        return original_plan_from_dict(cls, wire)

    def count_journal(cls, wire):
        counts["journal"] += 1
        return original_journal_from_dict(cls, wire)

    def count_record_json(cls, wire):
        counts["record_json"] += 1
        return original_record_from_json(cls, wire)

    def count_row(row):
        counts["row"] += 1
        return original_row(row)

    def observe_history_parser(wire, *, retain_context=False):
        references, contexts = original_history_parser(wire, retain_context=retain_context)
        history_contexts.append((retain_context, len(contexts)))
        return references, contexts

    monkeypatch.setattr(NativeRSIExecutionPlan, "from_dict", classmethod(count_plan))
    monkeypatch.setattr(ProducerBundlePublicationJournal, "from_dict", classmethod(count_journal))
    monkeypatch.setattr(RSIPythonAdmissionRecord, "from_json", classmethod(count_record_json))
    monkeypatch.setattr(value.ledger, "_python_admission_row", count_row)
    monkeypatch.setattr(
        store_module,
        "_parse_rsi_python_admission_references_with_context",
        observe_history_parser,
    )
    monkeypatch.setattr(
        ProducerBundlePublicationJournal,
        "digest",
        lambda _self: pytest.fail("history seam reparsed the parsed journal digest"),
    )
    monkeypatch.setattr(
        store_module,
        "validate_rsi_python_admission_reference_record",
        lambda *_args, **_kwargs: pytest.fail("history seam called the general reference validator"),
    )

    history = value.ledger.controller_checkpoint_history(value.binding.run_id)

    assert history[-1][1]["followup_marker"] == "final-reference-head"
    assert history[-1][1]["python_admission_refs"]
    assert history_contexts == [(False, 0), (True, 1)]
    assert counts == {"plan": 2, "journal": 2, "record_json": 1, "row": 1}
