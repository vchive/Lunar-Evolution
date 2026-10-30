"""Operation-scoped pure comparisons retain every physical shape observation."""
from __future__ import annotations

import sys
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from threading import Thread

import pytest
from test_rsi_brs_reserved_rejection import _fixture

from lunar_evolution import rsi_brs_reserved_owner as owner_module
from lunar_evolution import rsi_brs_reserved_policy as policy
from lunar_evolution import rsi_brs_reserved_rejection as rejection
from lunar_evolution import rsi_publication_lineage as lineage
from lunar_evolution.producer_bundle_lineage import LineageSnapshotPin
from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
from lunar_evolution.rsi_learning import RSILearningError

_FIELD = "producer_publication_lineage"


def _case(workspace):
    before, c1, c2, kwargs = _fixture()
    for wire in (before, c1, c2):
        entry = wire["batches"][-1]
        entry["before_sources"] = {
            name: replace(LineageSnapshotPin.from_dict(entry["snapshots"][name + "-before"]),
                          name=name + "-before").to_dict()
            for name in ("archive", "state")
        }
    introduced = deepcopy(before)
    introduced["batches"][-1]["evidence_pins"] = {}
    history = [(str(index) * 64, {_FIELD: wire})
               for index, wire in enumerate((introduced, before, c1, c2), 1)]
    owner = object.__new__(_BRSLineageCheckpointOwner)
    owner._wave, owner._handoff = object(), object()
    owner._association = {key: value for key, value in before.items()
                          if key not in {"batches", "head", "rejections"}}
    owner._ordinal, owner._state = 0, {_FIELD: c2}
    owner._workspace, owner._reserved_prefix = workspace, kwargs["prefix"]
    return owner, history, (kwargs["prefix"],), []


@contextmanager
def _calls(shape_observations=None):
    targets = {
        rejection.validate_reserved_brs_c1_transition.__code__: "c1",
        rejection.validate_reserved_brs_c2_transition.__code__: "c2",
        owner_module._reserved_history_wire_checks.__code__: "wire",
        owner_module.reserved_validate_entry_shape.__code__: "shape",
        owner_module.reserved_validate_source_pin_maps.__code__: "source_maps",
        lineage._root_pin.__code__: "root",
    }
    counts, previous = Counter(), sys.getprofile()

    def observe(frame, event, _argument):
        if event == "call" and frame.f_code in targets:
            label = targets[frame.f_code]
            counts[label] += 1
            if label == "shape" and shape_observations is not None:
                shape_observations.append(frame.f_locals["entry"])

    sys.setprofile(observe)
    try:
        yield counts
    finally:
        sys.setprofile(previous)


def _compare(owner, history, prefixes):
    owner_module._compare_reserved_history_wires(owner, history, prefixes, None)


def test_identical_fresh_values_skip_only_pure_checks_and_reobserve_shapes(tmp_path):
    owner, history, prefixes, observations = _case(tmp_path)
    assert owner_module._reserved_history_projection_guard() == policy.reserved_brs_policy_projection()["sha256"]
    with owner_module._reserved_history_projection_scope(owner._wave, owner._handoff):
        with _calls(observations) as cold:
            _compare(owner, history, prefixes)
        assert cold["c1"] == cold["c2"] == 1
        assert cold["shape"] == cold["source_maps"] == 2
        assert len(observations) == 2
        cache = owner_module._HISTORY_PROJECTION_LOCAL.cache
        assert len(cache["entries"]) == 1
        fresh_history, fresh_prefixes = deepcopy(history), deepcopy(prefixes)
        with _calls(observations) as hot:
            _compare(owner, fresh_history, fresh_prefixes)
        assert hot["c1"] == hot["c2"] == hot["wire"] == 0
        assert hot["shape"] == hot["source_maps"] == 2
        assert len(observations) == 4
        assert observations[2] is fresh_history[0][1][_FIELD]["batches"][-1]
        assert observations[3] is fresh_history[1][1][_FIELD]["batches"][-1]
        # Cache keys contain immutable values only; the marker is accounting,
        # never a retained result, dictionary, descriptor or live evidence.
        def immutable(value):
            assert type(value) in {tuple, bytes, str, int, bool}
            if type(value) is tuple:
                for item in value:
                    immutable(item)
        for key, units in cache["entries"].items():
            immutable(key)
            assert type(units) is int and units > 0
    assert cache["entries"] == {} and cache["retained_units"] == 0 and cache["owner"] is None
    assert owner_module._HISTORY_PROJECTION_LOCAL.cache is None


@pytest.mark.parametrize("axis", ["association", "ordinal", "wire", "wire_order", "wire_count",
                                  "current", "domain", "canonical", "batch"])
def test_key_covers_every_input_read_by_the_pure_comparison(axis, tmp_path):
    owner, history, prefixes, _observations = _case(tmp_path)
    original = owner_module._reserved_history_projection_key(owner, history, prefixes, None)
    assert original is not None
    if axis == "association":
        owner._association["run_id"] += "-foreign"
    elif axis == "ordinal":
        owner._ordinal += 1
    elif axis == "wire":
        history[1][1][_FIELD]["batches"][0]["evidence_pins"]["journal.prepared.json"]["inode"] += 1
    elif axis == "wire_order":
        history[:2] = reversed(history[:2])
    elif axis == "wire_count":
        history.append(deepcopy(history[-1]))
    elif axis == "current":
        owner._state = deepcopy(owner._state)
        owner._state[_FIELD]["run_id"] += "-foreign"
    elif axis == "domain":
        prefixes = (replace(prefixes[0], domain_bytes=prefixes[0].domain_bytes + b" "),)
    elif axis == "canonical":
        prefixes = (replace(prefixes[0], canonical_bytes=prefixes[0].canonical_bytes + b" "),)
    else:
        prefixes = (replace(prefixes[0], batch_bytes=(*prefixes[0].batch_bytes, b"foreign")),)
    assert owner_module._reserved_history_projection_key(owner, history, prefixes, None) != original


def test_changed_current_wire_refuses_and_clears_a_previously_valid_projection(tmp_path):
    owner, history, prefixes, _observations = _case(tmp_path)
    with owner_module._reserved_history_projection_scope(owner._wave, owner._handoff):
        _compare(owner, history, prefixes)
        cache = owner_module._HISTORY_PROJECTION_LOCAL.cache
        assert cache["entries"]
        owner._state = deepcopy(owner._state)
        owner._state[_FIELD]["run_id"] += "-foreign"
        with pytest.raises(RSILearningError, match="history_drift"):
            _compare(owner, history, prefixes)
        assert not cache["entries"] and cache["retained_units"] == 0


def test_nested_scope_shares_only_original_owner_and_thread_and_next_operation_starts_empty(tmp_path):
    owner, history, prefixes, _observations = _case(tmp_path)
    foreign, foreign_history, foreign_prefixes, _ = _case(tmp_path)
    foreign._wave, foreign._handoff = owner._wave, owner._handoff
    with owner_module._reserved_history_projection_scope(owner._wave, owner._handoff):
        _compare(owner, history, prefixes)
        cache = owner_module._HISTORY_PROJECTION_LOCAL.cache
        with owner_module._reserved_history_projection_scope(owner._wave, owner._handoff), _calls() as nested:
            _compare(owner, history, prefixes)
        assert nested["wire"] == 0
        with _calls() as other_owner:
            _compare(foreign, foreign_history, foreign_prefixes)
        assert other_owner["c1"] == other_owner["c2"] == 1
        observed = []
        def other_thread():
            observed.append(owner_module._reserved_history_projection_cache(owner))
        thread = Thread(target=other_thread)
        thread.start()
        thread.join()
        assert observed == [None]
        assert owner_module._HISTORY_PROJECTION_LOCAL.cache is cache
        with (pytest.raises(RSILearningError, match="history_projection_scope_drift"),
              owner_module._reserved_history_projection_scope(object(), owner._handoff)):
            pass
    with owner_module._reserved_history_projection_scope(owner._wave, owner._handoff), _calls() as later:
        _compare(owner, history, prefixes)
    assert later["c1"] == later["c2"] == 1


def test_exception_cleanup_also_covers_cancellation(tmp_path):
    owner, history, prefixes, _observations = _case(tmp_path)
    with pytest.raises(KeyboardInterrupt), owner_module._reserved_history_projection_scope(owner._wave, owner._handoff):
        _compare(owner, history, prefixes)
        cache = owner_module._HISTORY_PROJECTION_LOCAL.cache
        raise KeyboardInterrupt
    assert cache["entries"] == {} and cache["owner"] is None
    assert owner_module._HISTORY_PROJECTION_LOCAL.cache is None


@pytest.mark.parametrize("axis", ["guard_code", "comparison_code", "entry_capture"])
def test_helper_or_policy_capture_drift_falls_back_before_reuse(axis, monkeypatch, tmp_path):
    owner, history, prefixes, _observations = _case(tmp_path)
    with owner_module._reserved_history_projection_scope(owner._wave, owner._handoff):
        _compare(owner, history, prefixes)
        if axis == "entry_capture":
            cells = dict(zip(policy.reserved_brs_policy_projection.__code__.co_freevars,
                             policy.reserved_brs_policy_projection.__closure__, strict=True))
            cell, previous = cells["builder"], cells["builder"].cell_contents
            cell.cell_contents = object()
        else:
            function = (owner_module._reserved_history_projection_guard if axis == "guard_code"
                        else owner_module._reserved_history_wire_checks)
            monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="foreign"))
        try:
            with _calls() as counts:
                _compare(owner, history, prefixes)
            assert counts["c1"] == counts["c2"] == 1
        finally:
            if axis == "entry_capture":
                cell.cell_contents = previous


def test_optional_encoding_and_retention_are_bounded_without_retaining_dtos(monkeypatch, tmp_path):
    owner, history, prefixes, _observations = _case(tmp_path)
    monkeypatch.setattr(owner_module, "_HISTORY_PROJECTION_MAX_UNITS", 4096)
    assert owner_module._reserved_history_projection_key(owner, history, prefixes, None) is None
    with _calls() as counts:
        _compare(owner, history, prefixes)
    assert counts["c1"] == counts["c2"] == 1
    with owner_module._reserved_history_projection_scope(owner._wave, owner._handoff):
        cache = owner_module._HISTORY_PROJECTION_LOCAL.cache
        monkeypatch.setattr(owner_module, "_HISTORY_PROJECTION_MAX_ENTRIES", 2)
        for key, units in ((b"a", 2000), (b"b", 2000), (b"a", 2000), (b"c", 2000)):
            owner_module._retain_reserved_history_projection(cache, key, units)
        assert list(cache["entries"]) == [b"a", b"c"]
        assert cache["retained_units"] == 4000
        owner_module._retain_reserved_history_projection(cache, b"oversize", 4097)
        assert list(cache["entries"]) == [b"a", b"c"]
        owner_module._clear_reserved_history_projection()
        assert not cache["entries"] and cache["retained_units"] == 0


def test_cache_hit_reobserves_actual_missing_archive_parent_inode(tmp_path):
    owner, history, prefixes, _observations = _case(tmp_path)
    evolution = tmp_path / "evolution"
    evolution.mkdir()
    introduced = deepcopy(history[0][1][_FIELD])
    entry = introduced["batches"][-1]
    entry["snapshots"]["archive-before"].update(size=0, sha256=lineage._sha(b""))
    state_pin = replace(LineageSnapshotPin.from_dict(entry["snapshots"]["state-before"]), name="state-before")
    entry["before_sources"] = {"archive": {"missing": True, "parent": lineage._root_pin(evolution)},
                               "state": state_pin.to_dict()}
    history, owner._state = [("a" * 64, {_FIELD: introduced})], {_FIELD: deepcopy(introduced)}
    owner._workspace, owner._reserved_prefix = tmp_path, prefixes[0]
    with owner_module._reserved_history_projection_scope(owner._wave, owner._handoff):
        with _calls() as cold:
            _compare(owner, history, prefixes)
        cache = owner_module._HISTORY_PROJECTION_LOCAL.cache
        assert len(cache["entries"]) == 1 and cold["root"] == 1
        with _calls() as hot:
            _compare(owner, history, prefixes)
        assert hot["wire"] == 0 and hot["root"] == 1
        evolution.rename(tmp_path / "retained-evolution")
        evolution.mkdir()
        with pytest.raises(RSILearningError, match="source_pins_invalid"), _calls() as replaced:
            _compare(owner, history, prefixes)
        assert replaced["root"] == 1
        assert not cache["entries"] and cache["retained_units"] == 0
