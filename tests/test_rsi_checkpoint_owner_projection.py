"""Owner-local immutable projections retain every fresh history/row gate."""
from __future__ import annotations

import sqlite3
import sys
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from test_rsi_admission_checkpoint_observation import _FreshCheckpointReads
from test_rsi_admission_checkpoint_observation import retained as retained_fixture
from test_rsi_python_admission_flow import _forged_checkpoint_append

from lunar_evolution import rsi_brs_publication_lineage as lineage_policy
from lunar_evolution import rsi_brs_reserved_policy as reserved_policy
from lunar_evolution import rsi_store as store
from lunar_evolution.rsi_identity import RSIIdentityError, component_fingerprint
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan


@pytest.fixture
def retained(tmp_path):
    return retained_fixture.__wrapped__(tmp_path)


def _observe(value, *, change=None):
    with sqlite3.connect(value.ledger.database) as connection:
        connection.row_factory = sqlite3.Row
        fresh = _FreshCheckpointReads(connection, change, as_mapping=True)
        first = value.ledger._controller_checkpoint_history_tx(fresh, value.binding.run_id)
        second = value.ledger._controller_checkpoint_history_tx(fresh, value.binding.run_id)
        assert fresh.checkpoint_reads == 2
        return first, second


def _profile_read(value):
    codes = {
        "history": store.RSILedger._checkpoint_python_references_with_context.__code__,
        "row": store.RSILedger._python_admission_row.__code__,
        "match": store.validate_rsi_python_admission_reference_record.__code__,
    }
    counts = dict.fromkeys(codes, 0)
    previous = sys.getprofile()

    def profile(frame, event, _argument):
        if event == "call":
            for name, code in codes.items():
                if frame.f_code is code:
                    counts[name] += 1

    sys.setprofile(profile)
    try:
        result = value.ledger.controller_checkpoint_history(value.binding.run_id)
    finally:
        sys.setprofile(previous)
    return result, counts


def test_owner_projection_skips_only_pure_history_work_and_returns_fresh_json(retained):
    ledger = retained.ledger
    assert store._checkpoint_projection_helpers_current(ledger)
    original = ledger.controller_checkpoint_history(retained.binding.run_id)
    with ledger._checkpoint_projection_scope():
        first, initial = _profile_read(retained)
        second, hit = _profile_read(retained)
        assert first == second == original
        assert initial["history"] == len(first) and hit["history"] == 0
        assert initial["row"] == hit["row"] == 1
        assert hit["match"] == 1  # Fresh plan/journal and retained-row binding.
        second[-1][1]["python_admission_refs"].clear()
        assert ledger.controller_checkpoint_history(retained.binding.run_id) == original
        cache = ledger._checkpoint_projection_cache()
        assert cache and cache["entries"]
        for projection, _units in cache["entries"].values():
            assert type(projection) is store._CheckpointHistoryRowProjection
            assert type(projection.digest) is str and type(projection.references) is tuple
            assert all(type(name) is str and type(raw) is bytes for name, raw in projection.references)
    assert ledger._checkpoint_projection_local.cache is None
    assert not cache["entries"] and cache["retained_units"] == 0
    assert _profile_read(retained)[1]["history"] == len(first)


def test_each_projection_walk_selects_all_four_columns_afresh(retained):
    with retained.ledger._checkpoint_projection_scope():
        first, second = _observe(retained)
        assert first == second


@pytest.mark.parametrize("change", [
    lambda rows: rows[0].update(revision=99),
    lambda rows: rows[0].update(parent_sha256="b" * 64),
    lambda rows: rows[0].update(payload="{}"),
    lambda rows: rows[0].update(checkpoint_sha256="b" * 64),
    lambda rows: rows.reverse(),
    lambda rows: rows.append(dict(rows[-1])),
    lambda rows: rows.pop(0),
], ids=["revision", "parent", "payload", "digest", "reorder", "append", "delete"])
def test_projection_hit_cannot_hide_changed_raw_sql_input(retained, change):
    with retained.ledger._checkpoint_projection_scope(), pytest.raises(RSILearningError):
        _observe(retained, change=change)


def test_equal_length_changed_raw_text_is_reparsed(retained):
    def change(rows):
        old = rows[-1]["payload"]
        new = old.replace('"checkpoint_observation_marker":2', '"checkpoint_observation_marker":3')
        assert old != new and len(old) == len(new)
        rows[-1]["payload"] = new

    with (retained.ledger._checkpoint_projection_scope(),
          pytest.raises(RSILearningError, match="^rsi_controller_checkpoint_corrupt$")):
        _observe(retained, change=change)


@pytest.mark.parametrize("mutation", ["missing", "column", "wire"])
def test_final_admission_row_is_not_cached_after_a_successful_history(retained, mutation):
    with retained.ledger._checkpoint_projection_scope():
        retained.ledger.controller_checkpoint_history(retained.binding.run_id)
        with sqlite3.connect(retained.ledger.database) as connection:
            if mutation == "missing":
                connection.execute("DELETE FROM rsi_python_admissions")
            elif mutation == "column":
                connection.execute("UPDATE rsi_python_admissions SET record_sha256 = ?", ("b" * 64,))
            else:
                connection.execute("UPDATE rsi_python_admissions SET payload = payload || ' '")
        with pytest.raises(RSILearningError, match="^rsi_python_admission_(record_missing|reference_record_drift)$"):
            retained.ledger.controller_checkpoint_history(retained.binding.run_id)


@pytest.mark.parametrize("mutation", ["delete", "reattribute"])
def test_hash_valid_append_preserves_reference_monotonicity_after_cached_walk(retained, mutation):
    def change(state):
        reference = state["python_admission_refs"].pop(retained.episode_id)
        if mutation == "reattribute":
            state["python_admission_refs"]["different-episode"] = reference

    with retained.ledger._checkpoint_projection_scope():
        retained.ledger.controller_checkpoint_history(retained.binding.run_id)
        _forged_checkpoint_append(retained, change)
        with pytest.raises(RSILearningError, match="^rsi_python_admission_reference_history_drift$"):
            retained.ledger.controller_checkpoint_history(retained.binding.run_id)


@pytest.mark.parametrize("edge", ["parser", "parser-code", "constructor", "scope-code", "guard-code", "pin-alias"])
def test_executable_drift_disables_projection_and_owner_policy_refuses(retained, monkeypatch, edge):
    policy = reserved_policy.reserved_brs_policy_projection()
    with retained.ledger._checkpoint_projection_scope():
        retained.ledger.controller_checkpoint_history(retained.binding.run_id)
        if edge == "parser":
            original = NativeRSIExecutionPlan.from_dict.__func__
            monkeypatch.setattr(NativeRSIExecutionPlan, "from_dict", classmethod(lambda cls, wire: original(cls, wire)))
        elif edge == "parser-code":
            function = NativeRSIExecutionPlan.from_dict.__func__
            monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="changed"))
        elif edge == "constructor":
            function = store._CheckpointHistoryRowProjection.__init__
            monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="changed"))
        elif edge == "scope-code":
            function = store.RSILedger._checkpoint_projection_scope.__wrapped__
            monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="changed"))
        elif edge == "guard-code":
            function = store._checkpoint_projection_helpers_current
            monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="changed"))
        else:
            monkeypatch.setattr(store, "_HISTORY_PROJECTION_FUNCTION_PINS", ())
        assert retained.ledger._checkpoint_projection_cache() is None
        assert _profile_read(retained)[1]["history"] == len(retained.raw_history)
        # The lineage guard pins the aliases independently; the finite graph
        # pins executable method/constructor edges and rejects their mutation.
        if edge in {"constructor", "scope-code"}:
            with pytest.raises(RSILearningError, match="reserved_policy_drift"):
                reserved_policy.reserved_brs_policy_projection()
        else:
            assert policy["protocol"] == "lunar-rsi-brs-reserved-executable-policy-v1"


def test_scope_is_nested_thread_local_and_cleared_after_exception(retained):
    ledger = retained.ledger
    with pytest.raises(RuntimeError, match="stop"), ledger._checkpoint_projection_scope():
        outer = ledger._checkpoint_projection_cache()
        with ledger._checkpoint_projection_scope():
            assert ledger._checkpoint_projection_cache() is outer
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(ledger._checkpoint_projection_cache).result() is None
        raise RuntimeError("stop")
    assert ledger._checkpoint_projection_local.cache is None
    with ledger._checkpoint_projection_scope():
        assert ledger._checkpoint_projection_cache() is not outer
        assert not ledger._checkpoint_projection_cache()["entries"]


@pytest.mark.parametrize("column,value", [
    ("revision", True), ("revision", 0.0), ("payload", b"{}"),
    ("payload", type("Text", (str,), {})("{}")),
])
def test_projection_key_requires_exact_wire_scalar_types(column, value):
    row = {"revision": 0, "parent_sha256": None, "payload": "{}", "checkpoint_sha256": "a" * 64}
    assert store._checkpoint_projection_key("run", row) is not None
    row[column] = value
    assert store._checkpoint_projection_key("run", row) is None
    assert store._checkpoint_projection_key("run", type("Mapping", (dict,), {})(row)) is None


def test_projection_retention_has_entry_unit_and_oversized_bounds(monkeypatch):
    cache = {"entries": OrderedDict(), "retained_units": 0}
    projection = store._CheckpointHistoryRowProjection("a" * 64, (("episode", b"{}"),))
    monkeypatch.setattr(store, "_HISTORY_PROJECTION_CACHE_MAX_ENTRIES", 2)
    keys = [("run", revision, None, "{}", "a" * 64) for revision in range(3)]
    for key in keys:
        store._retain_checkpoint_projection(cache, key, projection)
    assert list(cache["entries"]) == keys[1:]
    assert cache["retained_units"] == sum(units for _, units in cache["entries"].values())
    unit = cache["entries"][keys[-1]][1]
    monkeypatch.setattr(store, "_HISTORY_PROJECTION_CACHE_MAX_RETAINED_UNITS", unit)
    store._retain_checkpoint_projection(cache, keys[0], projection)
    assert list(cache["entries"]) == [keys[0]] and cache["retained_units"] == unit
    original = deepcopy(cache)
    oversized = ("run", 99, None, "x" * unit, "a" * 64)
    store._retain_checkpoint_projection(cache, oversized, projection)
    assert cache == original


def test_full_lineage_policy_binds_generated_projection_constructor():
    policy = lineage_policy._policy()
    constructor = store._CheckpointHistoryRowProjection.__init__
    assert constructor.__code__.co_freevars == ("__dataclass_builtins_object__",)
    with pytest.raises(RSIIdentityError, match="^rsi_identity_config_hook_required$"):
        component_fingerprint(constructor)
    assert len(component_fingerprint(constructor, config={})) == 64
    assert len(policy["dependencies"]["rejection_c1"]) == 64


@pytest.mark.parametrize("edge", ["closure", "code", "defaults"])
def test_generated_constructor_explicit_config_keeps_independent_drift_gate(monkeypatch, edge):
    lineage_policy._policy()
    constructor = store._CheckpointHistoryRowProjection.__init__
    closure_cell = constructor.__closure__[0]
    original_capture = closure_cell.cell_contents
    try:
        if edge == "closure":
            closure_cell.cell_contents = object()
        elif edge == "code":
            monkeypatch.setattr(constructor, "__code__", constructor.__code__.replace(co_name="changed"))
        else:
            monkeypatch.setattr(constructor, "__defaults__", (None,))
        with pytest.raises(RSILearningError, match="^rsi_brs_reserved_policy_drift$"):
            lineage_policy._policy()
    finally:
        closure_cell.cell_contents = original_capture
