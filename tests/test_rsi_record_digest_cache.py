"""Event digest reuse keeps fresh SQLite rows, decoder outputs and helper behavior."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

import lunar_evolution.rsi_store as store_module
from lunar_evolution import rsi_brs_rejection_ready_reference as ready_reference
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64


@pytest.fixture
def ledger(tmp_path):
    return RSILedger(tmp_path / "record-cache.sqlite3")


def _row(**changed):
    values = {
        "logical_id": "run", "revision": 0, "kind": "run", "state": "created",
        "request_sha256": HEX, "parent_record_sha256": None,
        "payload": '{"nested": {"value": "a"}}', "created_at": "2026-10-27T00:00:00Z",
    }
    values.update(changed)
    if "record_sha256" not in values:
        values["record_sha256"] = RSILedger._record_digest(
            **{name: value for name, value in values.items() if name not in {"payload", "created_at"}},
            payload=json.loads(values["payload"]),
        )
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        columns = ", ".join(f"? AS {name}" for name in values)
        return connection.execute("SELECT " + columns, tuple(values.values())).fetchone()


def _count_hashes(monkeypatch):
    original = store_module.hashlib.sha256
    calls = []

    def counted(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(store_module.hashlib, "sha256", counted)
    return calls


def _assert_bounded(ledger):
    assert len(ledger._record_digest_cache) <= store_module._RECORD_DIGEST_CACHE_MAX_ENTRIES
    assert ledger._record_digest_cache_retained_units == sum(
        cost for _, cost in ledger._record_digest_cache.values()
    )
    assert 0 <= ledger._record_digest_cache_retained_units <= (
        store_module._RECORD_DIGEST_CACHE_MAX_RETAINED_UNITS
    )
    assert all(type(digest) is str and type(cost) is int
               for digest, cost in ledger._record_digest_cache.values())


def test_warm_get_keeps_fresh_select_and_decoded_payload(ledger, monkeypatch):
    saved = ledger.create_run("run", HEX, {"nested": {"value": "\u03bb"}})
    original_connect = ledger._connect
    queries = []

    def traced_connect():
        connection = original_connect()
        connection.set_trace_callback(queries.append)
        return connection

    monkeypatch.setattr(ledger, "_connect", traced_connect)
    calls = _count_hashes(monkeypatch)
    first = ledger.get("run")
    second = ledger.get("run")
    assert first == second == saved
    assert first is not second and first.payload is not second.payload
    assert first.payload["nested"] is not second.payload["nested"]
    assert len(calls) == 1
    assert sum(query.startswith("SELECT * FROM rsi_records") for query in queries) == 2
    first.payload["nested"]["value"] = "changed"
    assert ledger.get("run").payload == {"nested": {"value": "\u03bb"}}
    assert len(calls) == 1
    _assert_bounded(ledger)


@pytest.mark.parametrize("changed", [
    {"logical_id": "other"}, {"revision": 1}, {"kind": "episode"}, {"state": "running"},
    {"request_sha256": "b" * 64}, {"parent_record_sha256": "c" * 64},
    {"payload": '{"nested": {"value": "b"}}'},
])
def test_every_digest_metadata_or_exact_payload_change_misses(ledger, monkeypatch, changed):
    original, updated = _row(), _row(**changed)
    calls = _count_hashes(monkeypatch)
    first = ledger._row_to_record_cached(original)
    second = ledger._row_to_record_cached(updated)
    assert first.record_sha256 != second.record_sha256
    assert len(calls) == 2
    assert ledger._row_to_record_cached(original) == first
    assert ledger._row_to_record_cached(updated) == second
    assert len(calls) == 2
    _assert_bounded(ledger)


def test_equal_canonical_payload_with_different_exact_text_misses(ledger, monkeypatch):
    original = _row(payload='{"value": "a"}')
    updated = _row(payload='{"value" :"a"}')
    assert original["payload"] != updated["payload"]
    assert len(original["payload"]) == len(updated["payload"])
    calls = _count_hashes(monkeypatch)
    assert ledger._row_to_record_cached(original) == ledger._row_to_record_cached(updated)
    assert len(calls) == 2 and len(ledger._record_digest_cache) == 2


def test_unicode_equal_fresh_sqlite_text_hits_without_rehash(ledger, monkeypatch):
    first = _row(payload='{"value": "\u03bb"}')
    second = _row(payload=first["payload"].encode().decode())
    assert first["payload"] == second["payload"] and first["payload"] is not second["payload"]
    calls = _count_hashes(monkeypatch)
    assert ledger._row_to_record_cached(first) == ledger._row_to_record_cached(second)
    assert len(calls) == 1


def test_current_stored_digest_is_always_compared_after_cache_hit(ledger, monkeypatch):
    original = _row()
    tampered = _row(record_sha256="b" * 64)
    ledger._row_to_record_cached(original)
    calls = _count_hashes(monkeypatch)
    with pytest.raises(RSILearningError, match="rsi_record_digest_mismatch"):
        ledger._row_to_record_cached(tampered)
    assert calls == []
    assert ledger._row_to_record_cached(original).record_sha256 == original["record_sha256"]


def test_created_at_is_fresh_and_outside_original_digest_key(ledger, monkeypatch):
    original, updated = _row(), _row(created_at="later")
    calls = _count_hashes(monkeypatch)
    assert ledger._row_to_record_cached(original).created_at != ledger._row_to_record_cached(updated).created_at
    assert len(calls) == 1


@pytest.mark.parametrize(("column", "replacement"), [
    ("payload", '{"nested": {"value": "changed"}}'), ("revision", 1),
    ("kind", "episode"), ("state", "running"), ("request_sha256", "b" * 64),
    ("parent_record_sha256", "b" * 64), ("record_sha256", "b" * 64),
])
def test_fresh_sqlite_replacement_is_not_hidden_by_warm_cache(ledger, column, replacement):
    ledger.create_run("run", HEX, {"nested": {"value": "a"}})
    assert ledger.get("run") is not None
    with ledger._connect() as connection:
        connection.execute(
            f"UPDATE rsi_records SET {column} = ? WHERE logical_id = ?", (replacement, "run"),
        )
    with pytest.raises(RSILearningError, match="rsi_record_digest_mismatch"):
        ledger.get("run")


def test_warm_cache_still_decodes_malformed_fresh_json(ledger):
    ledger.create_run("run", HEX, {})
    ledger.get("run")
    with ledger._connect() as connection:
        connection.execute("UPDATE rsi_records SET payload = ? WHERE logical_id = ?", ("{", "run"))
    with pytest.raises(json.JSONDecodeError):
        ledger.get("run")


@pytest.mark.parametrize("raw", [b'{"value": "a"}', '{"value": "a"}'])
def test_blob_payload_or_float_revision_keeps_uncached_original_behavior(ledger, monkeypatch, raw):
    row = _row(payload=raw, revision=0.0)
    expected = RSILedger._row_to_record(row)
    calls = _count_hashes(monkeypatch)
    assert ledger._row_to_record_cached(row) == expected
    assert ledger._row_to_record_cached(row) == expected
    assert len(calls) == 2 and not ledger._record_digest_cache


def test_non_sqlite_mapping_keeps_static_converter_behavior(ledger, monkeypatch):
    values = dict(_row())
    calls = _count_hashes(monkeypatch)
    assert ledger._row_to_record_cached(values) == ledger._row_to_record(values)
    assert len(calls) == 2 and not ledger._record_digest_cache


def test_static_class_entry_still_hashes_independently_of_warm_memo(ledger, monkeypatch):
    row = _row()
    expected = ledger._row_to_record_cached(row)
    calls = _count_hashes(monkeypatch)
    assert RSILedger._row_to_record(row) == expected
    assert len(calls) == 1


@pytest.mark.parametrize("scope", ["instance", "class"])
def test_replaced_converter_is_called_even_with_warm_memo(ledger, monkeypatch, scope):
    row = _row()
    expected = ledger._row_to_record_cached(row)
    original = RSILedger._row_to_record
    calls = []

    def replaced(value):
        calls.append(value)
        return original(value)

    if scope == "instance":
        monkeypatch.setattr(ledger, "_row_to_record", replaced)
    else:
        monkeypatch.setattr(RSILedger, "_row_to_record", staticmethod(replaced))
    assert ledger._row_to_record_cached(row) == expected
    assert calls == [row]


def test_replaced_class_digest_runs_on_every_warm_read(ledger, monkeypatch):
    row = _row()
    expected = ledger._row_to_record_cached(row)
    original = RSILedger._record_digest
    calls = []

    def replaced(**values):
        calls.append(values)
        return original(**values)

    monkeypatch.setattr(RSILedger, "_record_digest", staticmethod(replaced))
    assert ledger._row_to_record_cached(row) == expected
    assert ledger._row_to_record_cached(row) == expected
    assert len(calls) == 2


def test_instance_digest_shadow_uses_original_static_converter_semantics(ledger, monkeypatch):
    row = _row()
    expected = ledger._row_to_record_cached(row)

    def unused(**_values):
        pytest.fail("the original static row converter dispatches through RSILedger")

    monkeypatch.setattr(ledger, "_record_digest", unused)
    calls = _count_hashes(monkeypatch)
    assert ledger._row_to_record_cached(row) == expected
    assert len(calls) == 1


@pytest.mark.parametrize("helper", ["_record_digest", "_row_to_record"])
def test_in_place_helper_code_replacement_does_not_use_warm_memo(ledger, monkeypatch, helper):
    row = _row()
    ledger._row_to_record_cached(row)

    def changed_digest(**_values):
        return "0" * 64

    def changed_converter(_row):
        raise RuntimeError("changed converter")

    if helper == "_record_digest":
        monkeypatch.setattr(RSILedger._record_digest, "__code__", changed_digest.__code__)
        with pytest.raises(RSILearningError, match="rsi_record_digest_mismatch"):
            ledger._row_to_record_cached(row)
    else:
        monkeypatch.setattr(RSILedger._row_to_record, "__code__", changed_converter.__code__)
        with pytest.raises(RuntimeError, match="changed converter"):
            ledger._row_to_record_cached(row)


@pytest.mark.parametrize("in_place", [False, True])
def test_changed_decoder_graph_cannot_hit_digest_for_same_text(ledger, monkeypatch, in_place):
    row = _row()
    ledger._row_to_record_cached(row)

    def changed_loads(*_args, **_kwargs):
        return {"nested": {"value": "different decoder graph"}}

    if in_place:
        monkeypatch.setattr(store_module.json.loads, "__code__", changed_loads.__code__)
    else:
        monkeypatch.setattr(store_module.json, "loads", changed_loads)
    with pytest.raises(RSILearningError, match="rsi_record_digest_mismatch"):
        ledger._row_to_record_cached(row)


@pytest.mark.parametrize("replacement", [
    "decoder", "decode", "raw_decode", "scan_once", "decode_code", "raw_decode_code",
    "decode_instance", "raw_decode_instance",
])
def test_default_decoder_dispatch_replacement_cannot_reuse_old_graph(ledger, monkeypatch, replacement):
    row = _row()
    ledger._row_to_record_cached(row)
    decoder = store_module.json._default_decoder

    def changed_decode(self, value, *_args, **_kwargs):
        return {"nested": {"value": "different decoder graph"}}

    def changed_raw_decode(self, value, idx=0):
        return {"nested": {"value": "different decoder graph"}}, len(value)

    if replacement == "decoder":
        class ChangedDecoder(json.JSONDecoder):
            decode = changed_decode

        monkeypatch.setattr(store_module.json, "_default_decoder", ChangedDecoder())
    elif replacement in {"decode", "raw_decode"}:
        method = changed_decode if replacement == "decode" else changed_raw_decode
        monkeypatch.setattr(type(decoder), replacement, method)
    elif replacement in {"decode_code", "raw_decode_code"}:
        name = replacement.removesuffix("_code")
        method = changed_decode if name == "decode" else changed_raw_decode
        monkeypatch.setattr(getattr(type(decoder), name), "__code__", method.__code__)
    elif replacement == "scan_once":
        monkeypatch.setattr(decoder, "scan_once", lambda value, idx: (
            {"nested": {"value": "different decoder graph"}}, len(value),
        ))
    else:
        name = replacement.removesuffix("_instance")
        method = (lambda value: {"nested": {"value": "different decoder graph"}}) if name == "decode" else (
            lambda value, idx=0: ({"nested": {"value": "different decoder graph"}}, len(value))
        )
        # These names are inherited. Restoring them with setattr would create
        # an instance shadow and disable the memo in later, unrelated tests.
        assert name not in decoder.__dict__
        monkeypatch.setitem(decoder.__dict__, name, method)
    with pytest.raises(RSILearningError, match="rsi_record_digest_mismatch"):
        ledger._row_to_record_cached(row)


def test_decoder_keyword_default_change_cannot_use_warm_memo(ledger, monkeypatch):
    row = _row()
    ledger._row_to_record_cached(row)
    defaults = dict(store_module.json.loads.__kwdefaults__)
    defaults["object_hook"] = lambda _value: {"nested": {"value": "different decoder graph"}}
    monkeypatch.setattr(store_module.json.loads, "__kwdefaults__", defaults)
    with pytest.raises(RSILearningError, match="rsi_record_digest_mismatch"):
        ledger._row_to_record_cached(row)


def test_changed_canonicalizer_is_not_bypassed(ledger, monkeypatch):
    row = _row()
    expected = ledger._row_to_record_cached(row)
    original = store_module.canonical_json
    calls = []

    def changed(value, **kwargs):
        calls.append(value)
        return original(value, **kwargs)

    monkeypatch.setattr(store_module, "canonical_json", changed)
    assert ledger._row_to_record_cached(row) == expected
    assert len(calls) == 1


@pytest.mark.parametrize("helper", ["_json_bytes", "dumps", "dumps_defaults"])
def test_canonicalizer_direct_dispatch_replacement_is_not_bypassed(ledger, monkeypatch, helper):
    row = _row()
    ledger._row_to_record_cached(row)

    def changed(*_args, **_kwargs):
        raise RuntimeError("changed canonical encoding")

    if helper == "_json_bytes":
        monkeypatch.setitem(store_module.canonical_json.__globals__, "_json_bytes", changed)
    elif helper == "dumps":
        monkeypatch.setattr(store_module.json, "dumps", changed)
    else:
        class ChangedEncoder(json.JSONEncoder):
            def encode(self, value):
                raise RuntimeError("changed canonical encoding")

        defaults = dict(store_module.json.dumps.__kwdefaults__)
        defaults["cls"] = ChangedEncoder
        monkeypatch.setattr(store_module.json.dumps, "__kwdefaults__", defaults)
    with pytest.raises(RuntimeError, match="changed canonical encoding"):
        ledger._row_to_record_cached(row)


def test_foreign_record_constructor_keeps_original_error(ledger, monkeypatch):
    row = _row()
    ledger._row_to_record_cached(row)
    monkeypatch.setattr(store_module.RSIRecord, "__init__", object.__init__)
    with pytest.raises(TypeError):
        ledger._row_to_record_cached(row)


def test_subclass_reader_keeps_original_uncached_converter(tmp_path, monkeypatch):
    class OtherLedger(RSILedger):
        pass

    ledger = OtherLedger(tmp_path / "subclass.sqlite3")
    row = _row()
    calls = _count_hashes(monkeypatch)
    assert ledger._row_to_record_cached(row) == ledger._row_to_record_cached(row)
    assert len(calls) == 2 and not ledger._record_digest_cache


def test_entry_limit_promotes_hits_and_evicts_least_recent(ledger, monkeypatch):
    rows = [_row(revision=revision) for revision in range(3)]
    monkeypatch.setattr(store_module, "_RECORD_DIGEST_CACHE_MAX_ENTRIES", 2)
    calls = _count_hashes(monkeypatch)
    first, second = [ledger._row_to_record_cached(row) for row in rows[:2]]
    assert ledger._row_to_record_cached(rows[0]) == first
    ledger._row_to_record_cached(rows[2])
    assert ledger._row_to_record_cached(rows[0]) == first and len(calls) == 3
    assert ledger._row_to_record_cached(rows[1]) == second and len(calls) == 4
    _assert_bounded(ledger)


def test_retained_units_evict_before_entry_limit(ledger, monkeypatch):
    rows = [_row(revision=revision) for revision in range(6)]
    monkeypatch.setattr(store_module, "_RECORD_DIGEST_CACHE_MAX_RETAINED_UNITS", 2500)
    calls = _count_hashes(monkeypatch)
    for row in rows:
        ledger._row_to_record_cached(row)
        _assert_bounded(ledger)
    assert len(ledger._record_digest_cache) < store_module._RECORD_DIGEST_CACHE_MAX_ENTRIES
    ledger._row_to_record_cached(rows[0])
    assert len(calls) == 7


@pytest.mark.parametrize("large_part", ["logical_id", "parent_record_sha256", "payload"])
def test_oversized_keys_are_never_retained(ledger, monkeypatch, large_part):
    large = json.dumps({"value": "a" * 1000}) if large_part == "payload" else "a" * 1000
    row = _row(**{large_part: large})
    monkeypatch.setattr(store_module, "_RECORD_DIGEST_CACHE_MAX_RETAINED_UNITS", 2500)
    calls = _count_hashes(monkeypatch)
    assert ledger._row_to_record_cached(row) == ledger._row_to_record_cached(row)
    assert len(calls) == 2 and not ledger._record_digest_cache
    _assert_bounded(ledger)


def test_zero_entry_budget_disables_retention(ledger, monkeypatch):
    row = _row()
    monkeypatch.setattr(store_module, "_RECORD_DIGEST_CACHE_MAX_ENTRIES", 0)
    ledger._row_to_record_cached(row)
    assert not ledger._record_digest_cache
    _assert_bounded(ledger)


def test_concurrent_equal_key_misses_retain_one_entry(ledger, monkeypatch):
    row = _row()
    original = store_module.hashlib.sha256
    barrier = Barrier(4)

    def simultaneous(value):
        barrier.wait(timeout=5)
        return original(value)

    monkeypatch.setattr(store_module.hashlib, "sha256", simultaneous)
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda _: ledger._row_to_record_cached(row), range(4)))
    assert len({record.record_sha256 for record in records}) == 1
    assert len({id(record.payload) for record in records}) == 4
    assert len(ledger._record_digest_cache) == 1
    _assert_bounded(ledger)


def test_new_instance_reader_remains_in_ready_reference_shadow_gate(ledger, monkeypatch):
    monkeypatch.setattr(ledger, "_row_to_record_cached", lambda _row: None)
    with pytest.raises(RSILearningError, match="rsi_brs_rejection_ready_reference_reader_shadow"):
        ready_reference._shadows(ledger, RSILedger, ready_reference._LEDGER_READERS)
