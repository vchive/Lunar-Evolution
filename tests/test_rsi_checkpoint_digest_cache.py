"""Pure digest reuse keeps fresh checkpoint validation and bounded retention."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

import lunar_evolution.rsi_store as store_module
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger


@pytest.fixture
def ledger(tmp_path):
    return RSILedger(tmp_path / "checkpoint-cache.sqlite3")


@pytest.fixture
def canonical_calls(ledger, monkeypatch):
    original = ledger._checkpoint_digest
    calls = []

    def counted(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(ledger, "_checkpoint_digest", counted)
    return calls


def _cached(ledger, raw='{"value": "a"}', *, run_id="run", revision=0, parent=None):
    return ledger._checkpoint_digest_cached(
        run_id, revision, parent, json.loads(raw), persisted_payload=raw,
    )


def _assert_bounded(ledger):
    assert len(ledger._checkpoint_digest_cache) <= store_module._CHECKPOINT_DIGEST_CACHE_MAX_ENTRIES
    assert (
        ledger._checkpoint_digest_cache_retained_units
        == sum(cost for _, cost in ledger._checkpoint_digest_cache.values())
    )
    assert 0 <= ledger._checkpoint_digest_cache_retained_units <= (
        store_module._CHECKPOINT_DIGEST_CACHE_MAX_RETAINED_UNITS
    )


def test_equal_fresh_sqlite_text_reuses_digest_without_another_sha256(ledger, monkeypatch):
    raw = '{"value": "\u03bb"}'
    expected = _cached(ledger, raw)
    fresh_raw = raw.encode("utf-8").decode("utf-8")
    assert raw == fresh_raw and raw is not fresh_raw

    def unexpected_sha256(*args, **kwargs):
        pytest.fail("a pure digest cache hit must not encode and rehash SQLite text")

    monkeypatch.setattr(store_module.hashlib, "sha256", unexpected_sha256)
    assert _cached(ledger, fresh_raw) == expected
    _assert_bounded(ledger)


@pytest.mark.parametrize("changed", [
    {"raw": '{"value": "b"}'},
    {"run_id": "other-run"},
    {"revision": 1},
    {"parent": "a" * 64},
])
def test_changed_text_run_revision_or_parent_requires_original_canonical_digest(
    ledger, canonical_calls, changed,
):
    first = _cached(ledger)
    second = _cached(ledger, **changed)
    assert len(canonical_calls) == 2
    assert second != first
    assert second == RSILedger._checkpoint_digest(*canonical_calls[-1])


def test_equal_length_different_json_spelling_misses_even_with_equal_canonical_payload(
    ledger, canonical_calls,
):
    first_raw = '{"value": "a"}'
    changed_raw = '{"value" :"a"}'
    assert len(first_raw) == len(changed_raw) and first_raw != changed_raw
    assert _cached(ledger, first_raw) == _cached(ledger, changed_raw)
    assert len(canonical_calls) == 2


class _StringSubclass(str):
    pass


@pytest.mark.parametrize("raw", [None, b'{"value": "a"}', _StringSubclass('{"value": "a"}')])
def test_non_exact_string_uses_original_canonical_path_without_cache(ledger, canonical_calls, raw):
    state = {"value": "a"}
    expected = RSILedger._checkpoint_digest("run", 0, None, state)
    for _ in range(2):
        assert ledger._checkpoint_digest_cached(
            "run", 0, None, state, persisted_payload=raw,
        ) == expected
    assert len(canonical_calls) == 2
    assert not ledger._checkpoint_digest_cache
    assert ledger._checkpoint_digest_cache_retained_units == 0


def test_entry_limit_evicts_least_recent_without_changing_canonical_digest(
    ledger, canonical_calls, monkeypatch,
):
    monkeypatch.setattr(store_module, "_CHECKPOINT_DIGEST_CACHE_MAX_ENTRIES", 2)
    first = _cached(ledger, revision=0)
    second = _cached(ledger, revision=1)
    assert _cached(ledger, revision=0) == first
    _cached(ledger, revision=2)
    _assert_bounded(ledger)
    assert _cached(ledger, revision=0) == first
    assert len(canonical_calls) == 3
    assert _cached(ledger, revision=1) == second
    assert len(canonical_calls) == 4
    _assert_bounded(ledger)


def test_retained_unit_budget_evicts_while_entry_count_remains_below_limit(
    ledger, canonical_calls, monkeypatch,
):
    monkeypatch.setattr(store_module, "_CHECKPOINT_DIGEST_CACHE_MAX_RETAINED_UNITS", 2500)
    original = _cached(ledger, revision=0)
    for revision in range(1, 10):
        _cached(ledger, revision=revision)
        _assert_bounded(ledger)
    assert len(ledger._checkpoint_digest_cache) < store_module._CHECKPOINT_DIGEST_CACHE_MAX_ENTRIES
    assert _cached(ledger, revision=0) == original
    assert len(canonical_calls) == 11
    _assert_bounded(ledger)


@pytest.mark.parametrize("large_part", ["raw", "run_id", "parent"])
def test_oversized_key_parts_are_not_retained(ledger, canonical_calls, monkeypatch, large_part):
    monkeypatch.setattr(store_module, "_CHECKPOINT_DIGEST_CACHE_MAX_RETAINED_UNITS", 2500)
    arguments = {large_part: json.dumps({"value": "a" * 1000}) if large_part == "raw" else "a" * 1000}
    first = _cached(ledger, **arguments)
    assert _cached(ledger, **arguments) == first
    assert len(canonical_calls) == 2
    assert not ledger._checkpoint_digest_cache
    assert ledger._checkpoint_digest_cache_retained_units == 0


def test_concurrent_misses_account_for_one_exact_key_once(ledger, monkeypatch):
    original = ledger._checkpoint_digest
    barrier = Barrier(4)

    def simultaneous(*args):
        barrier.wait(timeout=5)
        return original(*args)

    monkeypatch.setattr(ledger, "_checkpoint_digest", simultaneous)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _cached(ledger), range(4)))
    assert len(set(results)) == 1
    assert len(ledger._checkpoint_digest_cache) == 1
    _assert_bounded(ledger)


@pytest.mark.parametrize(("column", "replacement"), [
    ("payload", '{"value": "c"}'),
    ("revision", 2),
    ("parent_sha256", "b" * 64),
    ("checkpoint_sha256", "b" * 64),
])
def test_warm_cache_does_not_accept_fresh_history_row_replacement(ledger, column, replacement):
    with ledger.controller_lock("run"):
        head = ledger.write_controller_checkpoint("run", {"value": "a"}, expected_sha256=None)
        ledger.write_controller_checkpoint("run", {"value": "b"}, expected_sha256=head)
    assert len(ledger.controller_checkpoint_history("run")) == 2
    with ledger._connect() as connection:
        connection.execute(
            f"UPDATE rsi_controller_journal SET {column} = ? WHERE run_id = ? AND revision = 1",
            (replacement, "run"),
        )
    with pytest.raises(RSILearningError) as error:
        ledger.controller_checkpoint_history("run")
    assert error.value.code == "rsi_controller_checkpoint_corrupt"


def test_warm_cache_keeps_fresh_parsed_history_isolated_from_returned_payload_mutation(ledger):
    with ledger.controller_lock("run"):
        head = ledger.write_controller_checkpoint("run", {"nested": {"value": "a"}}, expected_sha256=None)
    history = ledger.controller_checkpoint_history("run")
    history[0][1]["nested"]["value"] = "changed"
    assert ledger.controller_checkpoint_history("run") == [(head, {"nested": {"value": "a"}})]
