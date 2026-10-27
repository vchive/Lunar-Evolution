"""Call-local admission projections keep both original fresh checkpoint reads."""
from __future__ import annotations

import json
import sqlite3
import sys
from copy import deepcopy

import pytest
from test_rsi_python_admission import _register, _setup
from test_rsi_python_admission_flow import _pin

from lunar_evolution import rsi_brs_publication_lineage as lineage_policy
from lunar_evolution import rsi_brs_reserved_policy as reserved_policy
from lunar_evolution import rsi_store as store
from lunar_evolution.rsi_learning import RSILearningError

SQL = ("SELECT revision, parent_sha256, payload, checkpoint_sha256 "
       "FROM rsi_controller_journal WHERE run_id = ? ORDER BY revision")


@pytest.fixture
def retained(tmp_path):
    value = _setup(tmp_path)
    value.admission = _register(value)
    _pin(value)
    for ordinal in range(3):
        head, state = value.ledger.controller_checkpoint(value.binding.run_id)
        state["checkpoint_observation_marker"] = ordinal
        with value.ledger.controller_lock(value.binding.run_id):
            value.ledger.write_controller_checkpoint(value.binding.run_id, state, expected_sha256=head)
    value.head = value.ledger.controller_checkpoint(value.binding.run_id)[0]
    with sqlite3.connect(value.ledger.database) as connection:
        value.raw_history = tuple(row[0] for row in connection.execute(
            "SELECT payload FROM rsi_controller_journal ORDER BY revision"))
    return value


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _FreshCheckpointReads:
    def __init__(self, connection, change=None, *, as_mapping=False):
        self.connection = connection
        self.change = change
        self.as_mapping = as_mapping
        self.checkpoint_reads = 0

    def execute(self, sql, arguments=()):
        cursor = self.connection.execute(sql, arguments)
        if sql != SQL:
            return cursor
        self.checkpoint_reads += 1
        if self.as_mapping or (self.checkpoint_reads == 2 and self.change is not None):
            rows = [dict(row) for row in cursor.fetchall()]
            if self.checkpoint_reads == 2 and self.change is not None:
                self.change(rows)
            return _Rows(rows)
        return cursor


def _read(value, *, change=None, as_mapping=False):
    connection = sqlite3.connect(value.ledger.database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")
        fresh = _FreshCheckpointReads(connection, change, as_mapping=as_mapping)
        result = value.ledger._python_admission_state_tx(
            fresh, value.admission, expected_checkpoint_sha256=value.head,
        )
        assert fresh.checkpoint_reads == 2
        return result
    finally:
        connection.close()


def _decode_count(value):
    calls = []
    code = json.loads.__code__
    previous = sys.getprofile()

    def profile(frame, event, _argument):
        if event == "call" and frame.f_code is code and frame.f_locals.get("s") in value.raw_history:
            calls.append(frame.f_locals["s"])

    sys.setprofile(profile)
    try:
        result = _read(value)
    finally:
        sys.setprofile(previous)
    return result, calls


def test_exact_second_read_matches_old_path_with_fewer_full_history_decodes(retained, monkeypatch):
    optimized, calls = _decode_count(retained)
    # Each initial history row is decoded, then only the latest complete state
    # is decoded again. No earlier state has its large lineage decoded twice.
    assert len(calls) == len(retained.raw_history) + 1
    repeated, repeated_calls = _decode_count(retained)
    assert repeated == optimized and len(repeated_calls) == len(calls)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_admission_checkpoint_helpers_current", lambda _ledger: False)
        legacy, legacy_calls = _decode_count(retained)
    assert optimized == legacy
    assert len(legacy_calls) == 2 * len(retained.raw_history)
    optimized[1]["budget_state"]["planned"]["deadline_unix"] = 0
    assert _read(retained) == legacy


@pytest.mark.parametrize("change", [
    lambda rows: rows[0].update(revision=99),
    lambda rows: rows[0].update(parent_sha256="a" * 64),
    lambda rows: rows[0].update(payload="{}"),
    lambda rows: rows[0].update(checkpoint_sha256="b" * 64),
    lambda rows: rows.pop(),
    lambda rows: rows.reverse(),
    lambda rows: rows.append(dict(rows[-1])),
], ids=["revision", "parent", "payload", "digest", "missing-row", "row-order", "extra-row"])
def test_second_fresh_raw_drift_preserves_old_refusal(retained, monkeypatch, change):
    with pytest.raises(RSILearningError) as optimized:
        _read(retained, change=change)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_admission_checkpoint_helpers_current", lambda _ledger: False)
        with pytest.raises(RSILearningError) as legacy:
            _read(retained, change=change)
    assert optimized.value.code == legacy.value.code


@pytest.mark.parametrize("change", [
    lambda rows: rows[0].update(revision=99),
    lambda rows: rows[0].update(parent_sha256="a" * 64),
    lambda rows: rows[0].update(payload="{}"),
    lambda rows: rows[0].update(checkpoint_sha256="b" * 64),
    lambda rows: rows.pop(),
    lambda rows: rows.reverse(),
    lambda rows: rows.append(dict(rows[-1])),
], ids=["revision", "parent", "payload", "digest", "missing-row", "row-order", "extra-row"])
def test_mapping_rows_bind_values_not_only_matching_keys(retained, monkeypatch, change):
    assert _read(retained, as_mapping=True) == _read(retained)
    with pytest.raises(RSILearningError) as optimized:
        _read(retained, change=change, as_mapping=True)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_admission_checkpoint_helpers_current", lambda _ledger: False)
        with pytest.raises(RSILearningError) as legacy:
            _read(retained, change=change, as_mapping=True)
    assert optimized.value.code == legacy.value.code


def test_second_mapping_missing_payload_preserves_original_error_wrapping(retained, monkeypatch):
    def missing_payload(rows):
        rows[0].pop("payload")

    with pytest.raises(RSILearningError, match="^rsi_python_admission_checkpoint_drift$") as optimized:
        _read(retained, change=missing_payload, as_mapping=True)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_admission_checkpoint_helpers_current", lambda _ledger: False)
        with pytest.raises(RSILearningError, match="^rsi_python_admission_checkpoint_drift$") as legacy:
            _read(retained, change=missing_payload, as_mapping=True)
    assert optimized.value.code == legacy.value.code
    assert type(optimized.value.__cause__) is type(legacy.value.__cause__) is KeyError


@pytest.mark.parametrize("representation", ["blob", "whitespace"])
def test_different_raw_representation_preserves_old_success(retained, monkeypatch, representation):
    def change(rows):
        raw = rows[0]["payload"]
        rows[0]["payload"] = raw.encode("utf-8") if representation == "blob" else " " + raw

    optimized = _read(retained, change=change)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_admission_checkpoint_helpers_current", lambda _ledger: False)
        legacy = _read(retained, change=change)
    assert optimized == legacy


def test_staging_callback_cannot_mutate_private_projection_or_returned_state(retained, monkeypatch):
    expected = _read(retained)
    original = retained.ledger._validate_python_producer_staging_history_tx
    observed = []

    def mutate(history, **kwargs):
        original(history, **kwargs)
        observed.append(history)
        history[0][1]["budget_state"]["planned"]["deadline_unix"] = 0
        history[-1][1]["intents"].clear()
        history[-1][1]["root_snapshot"].clear()

    monkeypatch.setattr(retained.ledger, "_validate_python_producer_staging_history_tx", mutate)
    assert _read(retained) == expected
    observed[-1][-1][1].clear()
    assert _read(retained) == expected


def test_replaced_history_seam_keeps_legacy_per_row_decode_path(retained, monkeypatch):
    original = retained.ledger._controller_checkpoint_history_tx

    def compatibility(connection, run_id):
        history = original(connection, run_id)
        history[-1][1]["observation_seam_only"] = True
        return history

    monkeypatch.setattr(retained.ledger, "_controller_checkpoint_history_tx", compatibility)
    assert not store._admission_checkpoint_helpers_current(retained.ledger)
    result, calls = _decode_count(retained)
    assert len(calls) == 2 * len(retained.raw_history)
    assert "observation_seam_only" not in result[1]


def test_decoder_replacement_between_fresh_reads_uses_original_refusal(retained, monkeypatch):
    original = retained.ledger._validate_python_producer_staging_history_tx
    loads = json.loads
    calls = []

    def change_decoder(history, **kwargs):
        original(history, **kwargs)

        def replaced(raw, *args, **kwargs):
            if raw in retained.raw_history:
                calls.append(raw)
                raise ValueError("changed checkpoint decoder")
            return loads(raw, *args, **kwargs)

        monkeypatch.setattr(store.json, "loads", replaced)

    monkeypatch.setattr(retained.ledger, "_validate_python_producer_staging_history_tx", change_decoder)
    with pytest.raises(RSILearningError, match="^rsi_python_admission_checkpoint_drift$"):
        _read(retained)
    assert calls == [retained.raw_history[0]]


@pytest.mark.parametrize("edge", ["loads-defaults", "loads-keyword-defaults", "canonical",
                                   "json-bytes", "json-dumps", "sha256"])
def test_digest_or_decoder_dependency_drift_keeps_old_decode_path(retained, monkeypatch, edge):
    expected = _read(retained)
    original_stage = retained.ledger._validate_python_producer_staging_history_tx
    canonical, dumps, sha256 = store.canonical_json, json.dumps, store.hashlib.sha256
    json_bytes = canonical.__globals__["_json_bytes"]

    def stage(history, **kwargs):
        original_stage(history, **kwargs)
        if edge == "loads-defaults":
            monkeypatch.setattr(json.loads, "__defaults__", (None,))
        elif edge == "loads-keyword-defaults":
            monkeypatch.setitem(json.loads.__kwdefaults__, "object_pairs_hook", lambda pairs: dict(pairs))
        elif edge == "canonical":
            monkeypatch.setattr(store, "canonical_json", lambda *a, **kw: canonical(*a, **kw))
        elif edge == "json-bytes":
            monkeypatch.setitem(canonical.__globals__, "_json_bytes", lambda value: json_bytes(value))
        elif edge == "json-dumps":
            monkeypatch.setattr(json, "dumps", lambda *a, **kw: dumps(*a, **kw))
        else:
            monkeypatch.setattr(store.hashlib, "sha256", lambda *a, **kw: sha256(*a, **kw))

    monkeypatch.setattr(retained.ledger, "_validate_python_producer_staging_history_tx", stage)
    result, calls = _decode_count(retained)
    assert result == expected
    assert len(calls) == 2 * len(retained.raw_history)
    assert not store._admission_checkpoint_helpers_current(retained.ledger)


@pytest.mark.parametrize("error_type", [TypeError, ValueError, RecursionError])
def test_optional_projection_failure_preserves_old_second_pass(retained, monkeypatch, error_type):
    expected = _read(retained)
    calls = []

    def projection(_value):
        calls.append(error_type)
        raise error_type("optional projection unavailable")

    # Force the pure projection seam itself to fail while keeping the original
    # history, decoder, raw reads and second-pass validation under observation.
    monkeypatch.setattr(store, "_admission_checkpoint_helpers_current", lambda _ledger: True)
    monkeypatch.setattr(store, "_admission_checkpoint_projection", projection)
    result, decodes = _decode_count(retained)
    assert calls == [error_type]
    assert result == expected
    assert len(decodes) == 2 * len(retained.raw_history)


def test_projection_is_detached_and_retains_complete_relevant_json_shapes():
    source = {"budget_state": {"planned": {"max_solver_invocations": 2}},
              "generations": {"one": {"parent_memory": {"items": [{"data": [1, True, None]}]}}}}
    expected = deepcopy(source)
    projected = store._admission_checkpoint_projection(source)
    source["generations"]["one"]["parent_memory"]["items"][0]["data"].clear()
    assert projected == expected
    projected["budget_state"]["planned"].clear()
    assert source["budget_state"]["planned"] == expected["budget_state"]["planned"]


@pytest.mark.parametrize("target", ["projection", "guard", "history", "aliases"])
def test_new_projection_helpers_remain_in_original_policy_drift_gates(monkeypatch, target):
    lineage_policy._policy()
    reserved_policy.reserved_brs_policy_projection()

    def foreign(*_args, **_kwargs):
        pytest.fail("policy called a changed admission projection helper")

    if target == "projection":
        monkeypatch.setattr(store, "_admission_checkpoint_projection", foreign)
    elif target == "guard":
        monkeypatch.setattr(store, "_admission_checkpoint_helpers_current", foreign)
    elif target == "history":
        monkeypatch.setattr(store.RSILedger, "_controller_checkpoint_history_observation_tx", foreign)
    else:
        monkeypatch.setattr(store, "_ADMISSION_CHECKPOINT_METHOD_PINS", ())
    with pytest.raises(RSILearningError):
        lineage_policy._policy()
    with pytest.raises(RSILearningError, match="reserved_policy_drift"):
        reserved_policy.reserved_brs_policy_projection()
