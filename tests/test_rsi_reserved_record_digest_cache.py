"""Reserved plain-row digest reuse preserves class dispatch and fresh observations."""

import json
import sqlite3

import pytest
from test_rsi_record_digest_cache import _assert_bounded, _count_hashes, _row

import lunar_evolution.rsi_store as store_module
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger


@pytest.fixture
def ledger(tmp_path):
    return RSILedger(tmp_path / "reserved-record-cache.sqlite3")


def _convert(ledger, row):
    return RSILedger._row_to_record_cached(ledger, row, class_static=True)


def test_plain_rows_share_only_expected_digest_and_decode_every_time(ledger, monkeypatch):
    first_row, second_row = dict(_row()), dict(_row())
    calls = _count_hashes(monkeypatch)
    first, second = _convert(ledger, first_row), _convert(ledger, second_row)
    assert first == second and first is not second
    assert first.payload is not second.payload
    assert first.payload["nested"] is not second.payload["nested"]
    first.payload["nested"]["value"] = "caller mutation"
    assert _convert(ledger, second_row).payload == {"nested": {"value": "a"}}
    assert len(calls) == 1
    _assert_bounded(ledger)


@pytest.mark.parametrize("changed", [
    {"logical_id": "other"}, {"revision": 1}, {"kind": "episode"}, {"state": "running"},
    {"request_sha256": "b" * 64}, {"parent_record_sha256": "c" * 64},
    {"payload": '{"nested": {"value": "b"}}'},
])
def test_each_digest_input_stays_in_exact_key(ledger, monkeypatch, changed):
    rows = [dict(_row()), dict(_row(**changed))]
    calls = _count_hashes(monkeypatch)
    records = [_convert(ledger, row) for row in rows]
    assert records[0].record_sha256 != records[1].record_sha256
    assert [_convert(ledger, row) for row in rows] == records
    assert len(calls) == 2
    _assert_bounded(ledger)


def test_equivalent_different_json_text_never_shares_digest_entry(ledger, monkeypatch):
    first, second = dict(_row(payload='{"value": "a"}')), dict(_row(payload='{"value" :"a"}'))
    calls = _count_hashes(monkeypatch)
    assert _convert(ledger, first) == _convert(ledger, second)
    assert len(calls) == 2 and len(ledger._record_digest_cache) == 2


def test_current_claimed_digest_is_compared_on_warm_hit(ledger, monkeypatch):
    original = dict(_row())
    _convert(ledger, original)
    calls = _count_hashes(monkeypatch)
    with pytest.raises(RSILearningError, match="rsi_record_digest_mismatch"):
        _convert(ledger, {**original, "record_sha256": "0" * 64})
    assert not calls


def test_created_at_is_fresh_without_becoming_a_digest_input(ledger, monkeypatch):
    original = dict(_row())
    calls = _count_hashes(monkeypatch)
    assert _convert(ledger, original).created_at != _convert(ledger, {**original, "created_at": "later"}).created_at
    assert len(calls) == 1


def test_plain_row_malformed_json_is_parsed_after_a_warm_read(ledger):
    row = dict(_row())
    _convert(ledger, row)
    with pytest.raises(json.JSONDecodeError):
        _convert(ledger, {**row, "payload": "{"})


@pytest.mark.parametrize("column", [
    "logical_id", "revision", "kind", "state", "request_sha256", "parent_record_sha256",
    "payload", "record_sha256", "created_at",
])
def test_missing_column_keeps_original_class_exception(ledger, column):
    row = dict(_row())
    del row[column]
    with pytest.raises(KeyError) as original:
        RSILedger._row_to_record(row)
    with pytest.raises(KeyError) as actual:
        _convert(ledger, row)
    assert actual.value.args == original.value.args
    assert not ledger._record_digest_cache


@pytest.mark.parametrize("fault", ["extra", "dict-subclass", "float-revision", "blob-payload", "created-at-int"])
def test_non_exact_primitive_rows_keep_static_uncached_behavior(ledger, monkeypatch, fault):
    row = dict(_row())
    if fault == "extra":
        row["ignored"] = "extra"
    elif fault == "dict-subclass":
        class OtherDict(dict):
            pass
        row = OtherDict(row)
    elif fault == "float-revision":
        row = dict(_row(revision=0.0))
    elif fault == "blob-payload":
        row["payload"] = row["payload"].encode()
    else:
        row["created_at"] = 1
    expected = RSILedger._row_to_record(row)
    calls = _count_hashes(monkeypatch)
    assert _convert(ledger, row) == _convert(ledger, row) == expected
    assert len(calls) == 2 and not ledger._record_digest_cache


@pytest.mark.parametrize("column", [
    "logical_id", "revision", "kind", "state", "request_sha256", "parent_record_sha256",
    "payload", "record_sha256", "created_at",
])
def test_every_scalar_column_requires_exact_primitive_type_before_memo(ledger, monkeypatch, column):
    class Scalar(str):
        pass

    row = dict(_row())
    row[column] = False if column == "revision" else Scalar(row[column] or "c" * 64)
    if column not in {"record_sha256", "created_at"}:
        row["record_sha256"] = RSILedger._record_digest(
            **{name: value for name, value in row.items()
               if name not in {"payload", "created_at", "record_sha256"}},
            payload=json.loads(row["payload"]),
        )
    expected = RSILedger._row_to_record(row)
    calls = _count_hashes(monkeypatch)
    assert _convert(ledger, row) == _convert(ledger, row) == expected
    assert len(calls) == 2 and not ledger._record_digest_cache
    _assert_bounded(ledger)


def test_reserved_plain_mode_shares_existing_sqlite_expected_digest_entry(ledger, monkeypatch):
    row = _row()
    expected = ledger._row_to_record_cached(row)
    calls = _count_hashes(monkeypatch)
    actual = _convert(ledger, dict(row))
    assert actual == expected and actual is not expected
    assert actual.payload is not expected.payload
    assert not calls and len(ledger._record_digest_cache) == 1
    _assert_bounded(ledger)


def test_reserved_mode_obeys_existing_zero_retention_budget(ledger, monkeypatch):
    row = dict(_row())
    monkeypatch.setattr(store_module, "_RECORD_DIGEST_CACHE_MAX_ENTRIES", 0)
    calls = _count_hashes(monkeypatch)
    assert _convert(ledger, row) == _convert(ledger, row)
    assert len(calls) == 2 and not ledger._record_digest_cache
    _assert_bounded(ledger)


def test_instance_converter_and_digest_shadows_are_ignored_in_class_mode(ledger, monkeypatch):
    row = dict(_row())
    expected = _convert(ledger, row)

    def forbidden(*_args, **_kwargs):
        pytest.fail("reserved class-static converter must ignore instance shadows")

    monkeypatch.setattr(ledger, "_row_to_record", forbidden)
    monkeypatch.setattr(ledger, "_record_digest", forbidden)
    calls = _count_hashes(monkeypatch)
    assert _convert(ledger, row) == expected
    assert not calls


@pytest.mark.parametrize("name", ["_row_to_record", "_record_digest"])
def test_replaced_class_helper_is_executed_on_every_warm_read(ledger, monkeypatch, name):
    row = dict(_row())
    expected = _convert(ledger, row)
    original = getattr(RSILedger, name)
    calls = []

    def replaced(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(RSILedger, name, staticmethod(replaced))
    assert _convert(ledger, row) == _convert(ledger, row) == expected
    assert len(calls) == 2


@pytest.mark.parametrize("name", ["_row_to_record", "_record_digest"])
def test_in_place_class_helper_code_drift_cannot_hit_memo(ledger, monkeypatch, name):
    row = dict(_row())
    _convert(ledger, row)

    def changed(*_args, **_kwargs):
        raise RuntimeError("changed class helper")

    monkeypatch.setattr(getattr(RSILedger, name), "__code__", changed.__code__)
    with pytest.raises(RuntimeError, match="changed class helper"):
        _convert(ledger, row)


@pytest.mark.parametrize("replacement", ["loads", "decoder", "scan_once", "decode-instance", "raw-decode-code", "loads-defaults"])
def test_changed_decoder_graph_cannot_reuse_same_plain_text_digest(ledger, monkeypatch, replacement):
    row = dict(_row())
    _convert(ledger, row)
    decoder = store_module.json._default_decoder

    def changed(*_args, **_kwargs):
        return {"nested": {"value": "changed decoder graph"}}

    if replacement == "loads":
        monkeypatch.setattr(store_module.json, "loads", changed)
    elif replacement == "decoder":
        class OtherDecoder(json.JSONDecoder):
            def decode(self, *_args, **_kwargs):
                return changed()
        monkeypatch.setattr(store_module.json, "_default_decoder", OtherDecoder())
    elif replacement == "scan_once":
        monkeypatch.setattr(decoder, "scan_once", lambda value, idx: (changed(), len(value)))
    elif replacement == "decode-instance":
        monkeypatch.setitem(decoder.__dict__, "decode", changed)
    elif replacement == "raw-decode-code":
        def changed_raw_decode(self, value, idx=0):
            return {"nested": {"value": "changed decoder graph"}}, len(value)
        monkeypatch.setattr(type(decoder).raw_decode, "__code__", changed_raw_decode.__code__)
    else:
        defaults = dict(store_module.json.loads.__kwdefaults__)
        defaults["object_hook"] = changed
        monkeypatch.setattr(store_module.json.loads, "__kwdefaults__", defaults)
    with pytest.raises(RSILearningError, match="rsi_record_digest_mismatch"):
        _convert(ledger, row)


@pytest.mark.parametrize("helper", ["canonical_json", "_json_bytes", "dumps"])
def test_canonical_helper_drift_keeps_original_exception_path(ledger, monkeypatch, helper):
    row = dict(_row())
    _convert(ledger, row)

    def changed(*_args, **_kwargs):
        raise RuntimeError("changed canonical helper")

    if helper == "canonical_json":
        monkeypatch.setattr(store_module, helper, changed)
    elif helper == "_json_bytes":
        monkeypatch.setitem(store_module.canonical_json.__globals__, helper, changed)
    else:
        monkeypatch.setattr(store_module.json, helper, changed)
    with pytest.raises(RuntimeError, match="changed canonical helper"):
        _convert(ledger, row)


def test_foreign_constructor_still_raises_even_after_warm_memo(ledger, monkeypatch):
    row = dict(_row())
    _convert(ledger, row)
    monkeypatch.setattr(store_module.RSIRecord, "__init__", object.__init__)
    with pytest.raises(TypeError):
        _convert(ledger, row)


def test_reserved_mode_subclass_keeps_class_converter_and_no_memo(tmp_path, monkeypatch):
    class OtherLedger(RSILedger):
        @staticmethod
        def _row_to_record(_row):
            pytest.fail("the previous reserved entry explicitly used the base class")

    other = OtherLedger(tmp_path / "subclass.sqlite3")
    row = dict(_row())
    expected = RSILedger._row_to_record(row)
    calls = _count_hashes(monkeypatch)
    assert _convert(other, row) == _convert(other, row) == expected
    assert len(calls) == 2 and not other._record_digest_cache


def test_ordinary_dict_call_remains_uncached_instance_dispatch(ledger, monkeypatch):
    row = dict(_row())
    expected = RSILedger._row_to_record(row)
    original = ledger._row_to_record
    calls = []

    def replaced(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(ledger, "_row_to_record", replaced)
    assert ledger._row_to_record_cached(row) == ledger._row_to_record_cached(row) == expected
    assert calls == [row, row] and not ledger._record_digest_cache


def test_reserved_whole_reader_keeps_both_fresh_raw_snapshots_and_reuses_no_dto(tmp_path, monkeypatch):
    from test_rsi_brs_reserved_ledger import _read, _setup

    import lunar_evolution.rsi_brs_reserved_ledger as reserved

    ledger, ids, _requests, _state, head = _setup(tmp_path)
    ledger._record_digest_cache.clear()
    ledger._record_digest_cache_retained_units = 0
    original_rows = reserved._read_reserved_rows
    original_sha = store_module.hashlib.sha256
    reads, hashes = [], []

    def observed_rows(*args, **kwargs):
        value = original_rows(*args, **kwargs)
        reads.append(value)
        return value

    def counted_sha(value):
        if b'"logical_id"' in value and b'"parent_record_sha256"' in value:
            hashes.append(value)
        return original_sha(value)

    monkeypatch.setattr(reserved, "_read_reserved_rows", observed_rows)
    monkeypatch.setattr(store_module.hashlib, "sha256", counted_sha)
    with ledger.controller_lock("reserved"):
        first = _read(ledger, ids, head)
        first_count = len(hashes)
        second = _read(ledger, ids, head)
    assert first == second and first is not second
    assert len(reads) == 4 and reads[0] == reads[1] == reads[2] == reads[3]
    assert first_count == 2 and len(hashes) == first_count
    _assert_bounded(ledger)


def test_reserved_reader_warm_digest_never_hides_external_row_replacement(tmp_path):
    from test_rsi_brs_reserved_ledger import _read, _setup

    ledger, ids, _requests, _state, head = _setup(tmp_path)
    with ledger.controller_lock("reserved"):
        _read(ledger, ids, head)
        with sqlite3.connect(ledger.database) as connection:
            connection.execute("UPDATE rsi_records SET record_sha256 = ? WHERE logical_id = ? AND revision = 0", ("0" * 64, "reserved"))
        with pytest.raises(RSILearningError, match="rsi_record_digest_mismatch"):
            _read(ledger, ids, head)
