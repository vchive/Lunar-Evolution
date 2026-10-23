"""History-local reference reuse keeps fresh wire, chain and retained-row gates."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace

import pytest
from test_rsi_python_admission import _plan, _register, _setup
from test_rsi_python_admission_flow import _forged_checkpoint_append, _pin

import lunar_evolution.rsi_python_admission as admission_module
import lunar_evolution.rsi_store as store_module
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_publication import ProducerBundlePublicationJournal
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_python_admission import RSIPythonAdmissionError


@pytest.fixture
def pinned(tmp_path):
    value = _setup(tmp_path)
    _register(value)
    _pin(value)
    return value


def _references(value):
    return deepcopy(value.ledger.controller_checkpoint(value.binding.run_id)[1]["python_admission_refs"])


def _append_unchanged(value, count=3):
    digest, state = value.ledger.controller_checkpoint(value.binding.run_id)
    with value.ledger.controller_lock(value.binding.run_id):
        for ordinal in range(count):
            state["reference_reuse_marker"] = ordinal
            digest = value.ledger.write_controller_checkpoint(
                value.binding.run_id, state, expected_sha256=digest,
            )


def _parse_map(value, *, previous=None):
    return admission_module._parse_rsi_python_admission_references_with_context(
        value, retain_context=True, reuse_contexts=previous,
    )


def _count_evidence(monkeypatch):
    counts = {"plan": 0, "journal": 0, "row": 0}
    original_plan = NativeRSIExecutionPlan.from_dict.__func__
    original_journal = ProducerBundlePublicationJournal.from_dict.__func__
    original_row = store_module.parse_rsi_python_admission_record

    def plan(cls, wire):
        counts["plan"] += 1
        return original_plan(cls, wire)

    def journal(cls, wire):
        counts["journal"] += 1
        return original_journal(cls, wire)

    def row(wire):
        counts["row"] += 1
        return original_row(wire)

    monkeypatch.setattr(NativeRSIExecutionPlan, "from_dict", classmethod(plan))
    monkeypatch.setattr(ProducerBundlePublicationJournal, "from_dict", classmethod(journal))
    monkeypatch.setattr(store_module, "parse_rsi_python_admission_record", row)
    return counts


def test_unchanged_references_parse_once_per_walk_but_final_row_is_always_fresh(pinned, monkeypatch):
    _append_unchanged(pinned)
    counts = _count_evidence(monkeypatch)

    first = pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)
    assert first[-1][1]["reference_reuse_marker"] == 2
    assert counts == {"plan": 1, "journal": 1, "row": 1}
    assert pinned.ledger.controller_checkpoint_history(pinned.binding.run_id) == first
    assert counts == {"plan": 2, "journal": 2, "row": 2}


def test_new_episode_key_does_not_reuse_identical_reference_bytes(pinned, monkeypatch):
    source = _references(pinned)
    _, contexts = _parse_map(source)
    added = "another-episode"
    source[added] = deepcopy(source[pinned.episode_id])
    counts = _count_evidence(monkeypatch)

    references, updated = _parse_map(source, previous=contexts)
    assert references == source
    assert updated[pinned.episode_id] is contexts[pinned.episode_id]
    assert updated[added] is not contexts[pinned.episode_id]
    assert counts == {"plan": 1, "journal": 1, "row": 0}


def test_same_length_reference_change_reparses_then_history_rejects_drift(pinned, monkeypatch):
    source = _references(pinned)
    _, contexts = _parse_map(source)
    source[pinned.episode_id]["record_sha256"] = "b" * 64
    counts = _count_evidence(monkeypatch)
    references, updated = _parse_map(source, previous=contexts)
    assert references == source
    assert len(updated[pinned.episode_id].canonical_bytes) == len(contexts[pinned.episode_id].canonical_bytes)
    assert updated[pinned.episode_id] is not contexts[pinned.episode_id]
    assert counts == {"plan": 1, "journal": 1, "row": 0}

    _forged_checkpoint_append(pinned, lambda state: state.update(python_admission_refs=source))
    with pytest.raises(RSILearningError, match="^rsi_python_admission_reference_history_drift$"):
        pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)


@pytest.mark.parametrize("replacement", [1.0, True])
def test_numeric_equality_cannot_reuse_one_as_float_or_boolean(pinned, replacement):
    source = _references(pinned)
    _, contexts = _parse_map(source)
    assert source[pinned.episode_id]["prepared_journal"]["num_islands"] == 1
    source[pinned.episode_id]["prepared_journal"]["num_islands"] = replacement
    assert source[pinned.episode_id] == contexts[pinned.episode_id].reference
    with pytest.raises(RSIPythonAdmissionError):
        _parse_map(source, previous=contexts)


@pytest.mark.parametrize("replacement", [0.0, -0.0])
def test_numeric_equality_cannot_reuse_zero_with_a_different_json_wire(pinned, replacement):
    source = _references(pinned)
    _, contexts = _parse_map(source)
    source[pinned.episode_id]["prepared_journal"]["candidates"][0]["generation"] = replacement
    assert source[pinned.episode_id] == contexts[pinned.episode_id].reference
    with pytest.raises(RSIPythonAdmissionError):
        _parse_map(source, previous=contexts)


@pytest.mark.parametrize("mutation", ["delete", "reattribute"])
def test_hash_valid_history_cannot_delete_or_reattribute_a_cached_reference(pinned, mutation):
    _append_unchanged(pinned)

    def change(state):
        reference = state["python_admission_refs"].pop(pinned.episode_id)
        if mutation == "reattribute":
            state["python_admission_refs"]["different-episode"] = reference

    _forged_checkpoint_append(pinned, change)
    with pytest.raises(RSILearningError, match="^rsi_python_admission_reference_history_drift$"):
        pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)


class _DictSubclass(dict):
    pass


@pytest.mark.parametrize("mutation", ["map-subclass", "reference-subclass", "key", "nan", "inf", "depth"])
def test_reuse_still_checks_fresh_exact_shapes_finiteness_and_depth(pinned, mutation):
    source = _references(pinned)
    _, contexts = _parse_map(source)
    if mutation == "map-subclass":
        source = _DictSubclass(source)
    elif mutation == "reference-subclass":
        source[pinned.episode_id] = _DictSubclass(source[pinned.episode_id])
    elif mutation == "key":
        source[1] = source.pop(pinned.episode_id)
    else:
        marker = float(mutation) if mutation in {"nan", "inf"} else None
        if mutation == "depth":
            for _ in range(50):
                marker = [marker]
        source[pinned.episode_id]["native_plan"]["request"]["solver_settings"]["marker"] = marker
    with pytest.raises(RSIPythonAdmissionError):
        _parse_map(source, previous=contexts)


def test_reference_size_is_checked_before_reusing_context_or_nested_parser(pinned, monkeypatch):
    source = _references(pinned)
    _, contexts = _parse_map(source)
    source[pinned.episode_id]["native_plan"]["request"]["solver_settings"]["padding"] = (
        "x" * admission_module.MAX_RSI_PYTHON_ADMISSION_BYTES
    )
    monkeypatch.setattr(
        NativeRSIExecutionPlan, "from_dict", classmethod(lambda *_: pytest.fail("unbounded plan parsed")),
    )
    with pytest.raises(RSIPythonAdmissionError, match="^rsi_python_admission_reference_invalid$"):
        _parse_map(source, previous=contexts)


def test_whole_reference_map_budget_remains_fresh_when_every_reference_is_reused(pinned, monkeypatch):
    source = _references(pinned)
    _, contexts = _parse_map(source)
    reference, context = source[pinned.episode_id], contexts[pinned.episode_id]
    count = (8 * 1024 * 1024) // len(context.canonical_bytes) + 1
    large = {f"episode-{ordinal}": reference for ordinal in range(count)}
    assert len(json.dumps(large, separators=(",", ":")).encode()) > 8 * 1024 * 1024
    previous = {episode_id: context for episode_id in large}
    counts = _count_evidence(monkeypatch)
    with pytest.raises(RSIPythonAdmissionError, match="^rsi_python_admission_reference_too_large$"):
        _parse_map(large, previous=previous)
    assert counts == {"plan": 0, "journal": 0, "row": 0}


@pytest.mark.parametrize("mutation", ["missing", "noncanonical", "same-length", "column"])
def test_fresh_final_select_and_complete_row_parse_follow_every_reused_history(pinned, mutation):
    _append_unchanged(pinned)
    assert pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)
    with sqlite3.connect(pinned.ledger.database) as connection:
        if mutation == "missing":
            connection.execute("DELETE FROM rsi_python_admissions")
        elif mutation == "column":
            connection.execute("UPDATE rsi_python_admissions SET record_sha256 = ?", ("b" * 64,))
        else:
            raw = connection.execute("SELECT payload FROM rsi_python_admissions").fetchone()[0]
            changed = json.dumps(json.loads(raw)) if mutation == "noncanonical" else raw.replace(
                '"production_admission":false', '"production_admission":true ',
            )
            if mutation == "same-length":
                assert len(changed) == len(raw) and changed != raw
            connection.execute("UPDATE rsi_python_admissions SET payload = ?", (changed,))
    code = "record_missing" if mutation == "missing" else "reference_record_drift"
    with pytest.raises(RSILearningError, match=f"^rsi_python_admission_{code}$"):
        pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)


@pytest.mark.parametrize("column,replacement", [
    ("revision", 99), ("parent_sha256", "b" * 64), ("checkpoint_sha256", "b" * 64),
    ("payload", "{"),
])
def test_fresh_checkpoint_json_and_chain_checks_survive_prior_success(pinned, column, replacement):
    _append_unchanged(pinned)
    assert pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)
    with sqlite3.connect(pinned.ledger.database) as connection:
        connection.execute(
            f"UPDATE rsi_controller_journal SET {column} = ? WHERE revision = "
            "(SELECT MAX(revision) FROM rsi_controller_journal)",
            (replacement,),
        )
    with pytest.raises(RSILearningError, match="^rsi_controller_checkpoint_corrupt$"):
        pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)


def test_returned_history_is_plain_detached_json_and_does_not_seed_next_call(pinned, monkeypatch):
    _append_unchanged(pinned)
    first = pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)
    original = deepcopy(first)
    assert json.loads(json.dumps(first[-1][1])) == first[-1][1]
    first[-1][1]["python_admission_refs"][pinned.episode_id]["native_plan"]["run_id"] = "tampered"
    assert pinned.ledger.controller_checkpoint_history(pinned.binding.run_id) == original

    def changed_parser(_cls, _wire):
        raise ValueError("parser changed after prior successful walk")

    monkeypatch.setattr(NativeRSIExecutionPlan, "from_dict", classmethod(changed_parser))
    with pytest.raises(RSILearningError, match="^rsi_python_admission_reference_invalid$"):
        pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)


def test_next_history_call_observes_rebound_full_record_parser(pinned, monkeypatch):
    _append_unchanged(pinned)
    assert pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)
    calls = []

    def changed_parser(wire):
        calls.append(wire)
        raise ValueError("row parser changed")

    monkeypatch.setattr(store_module, "parse_rsi_python_admission_record", changed_parser)
    with pytest.raises(RSILearningError, match="^rsi_python_admission_reference_record_drift$"):
        pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)
    assert len(calls) == 1 and type(calls[0]) is str


def _unicode_reference(pinned):
    reference = _references(pinned)[pinned.episode_id]
    request = replace(pinned.request, solver_settings=(("wire", {
        "unicode": "雪😀", "escaping": '"\\\n\t\x00',
        "numbers": [0, 0.0, -0.0, 1, 1.0, True, False, None],
    }),))
    reference["native_plan"] = _plan(pinned.binding, request, pinned.controller.snapshot).to_dict()
    return reference


def test_validated_reference_bytes_match_canonical_json_with_utf8_escapes_and_numeric_types(pinned):
    reference = _unicode_reference(pinned)
    _, contexts = _parse_map({pinned.episode_id: reference})
    context = contexts[pinned.episode_id]
    expected = canonical_json(reference, maximum=512 * 1024)
    assert admission_module._canonical(reference) == context.canonical_bytes == expected
    assert "雪😀".encode() in expected
    assert b'"escaping":"\\"\\\\\\n\\t\\u0000"' in expected
    assert b'"numbers":[0,0.0,-0.0,1,1.0,true,false,null]' in expected
    reordered = dict(reversed(list(reference.items())))
    _, updated = _parse_map({pinned.episode_id: reordered}, previous=contexts)
    assert updated[pinned.episode_id] is context


def _reference_map_with_encoded_size(reference, target):
    """Adjust only legal ASCII ID lengths; the independent JSON encoder is the oracle."""
    reference_size = len(canonical_json(reference, maximum=512 * 1024))
    count = (target - 2) // (reference_size + 132) + 1
    keys = [f"e{ordinal}:.-_" for ordinal in range(count)]
    original = {key: reference for key in keys}
    padding = target - len(canonical_json(original, maximum=16 * 1024 * 1024))
    assert 0 <= padding <= sum(128 - len(key) for key in keys)
    adjusted = []
    for key in keys:
        added = min(padding, 128 - len(key))
        adjusted.append(key + "x" * added)
        padding -= added
    assert padding == 0
    result = {key: reference for key in reversed(adjusted)}
    assert len(canonical_json(result, maximum=16 * 1024 * 1024)) == target
    return result


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_whole_reference_map_limit_matches_real_utf8_json_at_exact_boundary(pinned, offset):
    reference = _unicode_reference(pinned)
    _, contexts = _parse_map({pinned.episode_id: reference})
    context = contexts[pinned.episode_id]
    target = 8 * 1024 * 1024 + offset
    source = _reference_map_with_encoded_size(reference, target)
    previous = dict.fromkeys(source, context)

    if offset > 0:
        with pytest.raises(RSIPythonAdmissionError, match="^rsi_python_admission_reference_too_large$"):
            _parse_map(source, previous=previous)
    else:
        references, updated = _parse_map(source, previous=previous)
        assert len(canonical_json(references, maximum=8 * 1024 * 1024)) == target
        assert all(updated[key] is context for key in source)


def test_oversized_map_still_validates_later_reference_before_reporting_map_budget(pinned, monkeypatch):
    reference = _references(pinned)[pinned.episode_id]
    _, contexts = _parse_map({pinned.episode_id: reference})
    context = contexts[pinned.episode_id]
    source = _reference_map_with_encoded_size(reference, 8 * 1024 * 1024 + 1)
    previous = dict.fromkeys(source, context)
    invalid = {"journal_id": "missing-other-required-fields"}
    source["last-invalid"] = invalid
    original = admission_module._parse_rsi_python_admission_reference_context
    visits = []

    def visit(value, *, previous_context=None):
        visits.append(value)
        return original(value, previous_context=previous_context)

    monkeypatch.setattr(admission_module, "_parse_rsi_python_admission_reference_context", visit)
    with pytest.raises(RSIPythonAdmissionError, match="^rsi_python_admission_reference_invalid$"):
        _parse_map(source, previous=previous)
    assert len(visits) == len(source) and visits[-1] is invalid


def test_history_monotonic_comparison_uses_fresh_reference_bytes_without_store_reencoding(pinned, monkeypatch):
    _append_unchanged(pinned)
    expected = pinned.ledger.controller_checkpoint_history(pinned.binding.run_id)
    reference_visits = sum(len(payload.get("python_admission_refs", {})) for _, payload in expected)
    reference_fields = {"journal_id", "attempt_id", "record_sha256", "native_plan", "prepared_journal"}
    original_canonical = admission_module._canonical
    original_store_canonical = store_module.canonical_json
    fresh = []
    repeated = []

    def fresh_canonical(value):
        if type(value) is dict and set(value) == reference_fields:
            fresh.append(value)
        return original_canonical(value)

    def store_canonical(value, *args, **kwargs):
        if type(value) is dict and set(value) == reference_fields:
            repeated.append(value)
        return original_store_canonical(value, *args, **kwargs)

    monkeypatch.setattr(admission_module, "_canonical", fresh_canonical)
    monkeypatch.setattr(store_module, "canonical_json", store_canonical)
    assert pinned.ledger.controller_checkpoint_history(pinned.binding.run_id) == expected
    assert len(fresh) == reference_visits
    assert repeated == []
