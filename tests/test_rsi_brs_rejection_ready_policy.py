"""The finite pre-arm projection refuses drift before using changed dependencies."""

from __future__ import annotations

import _sqlite3
import builtins
import hashlib
import json
import sqlite3
import sys
from types import FunctionType

import pytest

from lunar_evolution import candidate_evaluation_spec as json_spec
from lunar_evolution import rsi_brs_publication_lineage as publication
from lunar_evolution import rsi_brs_rejection_ready_policy as policy
from lunar_evolution.rsi_fingerprint import _normalize_json
from lunar_evolution.rsi_identity import MAX_IDENTITY_BYTES, _normalize
from lunar_evolution.rsi_learning import RSILearningError


def _forbidden(*_args, **_kwargs):
    raise AssertionError("pre-arm policy executed a substituted dependency")


def _refuses():
    with pytest.raises(RSILearningError, match="rejection_ready_capture_policy_drift"):
        policy.rejection_ready_capture_policy()


def test_compact_projection_is_stable_json_safe_and_grants_no_authority():
    first = policy.rejection_ready_capture_policy()
    assert first == policy.rejection_ready_capture_policy()
    assert set(first) == {"protocol", "sha256"}
    assert first["protocol"] == "lunar-rsi-brs-rejection-ready-capture-policy-v1"
    assert len(first["sha256"]) == 64
    assert _normalize(first) == first
    _normalize_json(first)
    assert len(json.dumps(first, sort_keys=True).encode()) < MAX_IDENTITY_BYTES


@pytest.mark.parametrize("declared", [policy.state.queued._PENDING, policy.state.queued._READY])
def test_state_class_slot_declarations_are_checked_before_policy_projection(declared, monkeypatch):
    monkeypatch.setattr(declared, "__slots__", ("foreign",))
    with pytest.raises(RSILearningError, match="rejection_ready_state_invalid"):
        policy.rejection_ready_capture_policy()


@pytest.mark.parametrize("module,name", [
    (policy.owner, "_fail"), (policy.owner, "_owner"),
    (policy.owner, "_custody"), (policy.owner, "_assert_custody"),
    (policy.owner, "_domain"), (policy.owner, "_payload"),
    (policy.owner, "_empty"), (policy.owner, "_check_original"),
    (policy.owner, "retain_rejection_ready_capture"),
    (policy.reference, "_fail"), (policy.reference, "_digest"),
    (policy.reference, "_identifier"), (policy.reference, "_shadows"),
    (policy.reference, "_capture"), (policy.reference, "_check"),
    (policy.reference, "validate_existing_rejection_reference"),
    (policy.ledger, "_fail"), (policy.ledger, "_path"),
    (policy.ledger, "_readonly_uri"),
    (policy.ledger, "_identifier"), (policy.ledger, "_domain"),
    (policy.ledger, "_row_size"), (policy.ledger, "_schema_size"),
    (policy.ledger, "_snapshot_shape"), (policy.ledger, "_read"),
    (policy.ledger, "read_rejection_ready_rows"),
    (policy.ledger, "assert_rejection_ready_rows"),
    (policy.sync, "capture_ready_condition"), (policy.sync, "assert_ready_condition"),
    (policy.ack, "assert_rejection_ready_ack_graph"),
    (policy.ack, "build_rejection_ready_ack"), (policy.ack, "assert_rejection_ready_ack"),
    (policy.locks, "capture_rejection_ready_locks"), (policy.locks, "assert_rejection_ready_locks"),
    (policy.state, "assert_selected_ready_inflight"), (policy.state, "assert_selected_ready_committed"),
])
def test_declared_capture_helpers_are_not_replaceable(module, name, monkeypatch):
    monkeypatch.setattr(module, name, _forbidden)
    _refuses()


@pytest.mark.parametrize("function", [
    policy.owner._empty, policy.reference._capture, policy.ledger._read,
    json.loads, json_spec.canonical_json, policy.ledger._readonly_uri,
])
def test_original_function_code_cannot_change(function, monkeypatch):
    monkeypatch.setattr(function, "__code__", _forbidden.__code__)
    _refuses()


@pytest.mark.parametrize("name,value", [
    ("__defaults__", (object(),)), ("__kwdefaults__", {"invented": object()}),
    ("__annotations__", {"invented": object()}),
    ("__name__", "foreign"), ("__qualname__", "foreign"),
    ("__module__", "foreign"), ("__doc__", "foreign"),
])
def test_function_metadata_is_held_independently(name, value, monkeypatch):
    monkeypatch.setattr(policy.reference._capture, name, value)
    _refuses()


@pytest.mark.parametrize("attribute", ["__dict__", "__annotations__"])
def test_in_place_function_metadata_changes_are_refused(attribute, monkeypatch):
    monkeypatch.setitem(getattr(policy.ledger._read, attribute), "invented", _forbidden)
    _refuses()


def test_in_place_keyword_default_changes_are_refused(monkeypatch):
    monkeypatch.setitem(json.dumps.__kwdefaults__, "sort_keys", True)
    _refuses()


def test_sync_entrypoint_closure_cell_cannot_be_rebound():
    closure = policy.sync.capture_ready_condition.__closure__
    assert closure
    cell, original = closure[0], closure[0].cell_contents
    try:
        cell.cell_contents = object()
        _refuses()
    finally:
        cell.cell_contents = original


@pytest.mark.parametrize("module,name", [
    (policy.owner, "_empty"), (policy.reference, "_check"), (policy.ledger, "_read"),
])
def test_identical_code_in_foreign_globals_cannot_be_rebaselined(module, name, monkeypatch):
    original = getattr(module, name)
    clone = FunctionType(original.__code__, dict(original.__globals__), original.__name__,
                         original.__defaults__, original.__closure__)
    clone.__module__, clone.__qualname__ = original.__module__, original.__qualname__
    monkeypatch.setattr(module, name, clone)
    _refuses()


@pytest.mark.parametrize("module,name", [
    (policy.owner, "_CAPTURES"), (policy.owner, "provenance"),
    (policy.owner, "raw_ledger"), (policy.owner, "reference"), (policy.owner, "sync"),
    (policy.reference, "sync"), (policy.reference, "_CONTROLLER_READERS"),
    (policy.reference, "_LEDGER_READERS"),
    (policy.reference, "_MAX_REFERENCE_BYTES"), (policy.reference, "_MAX_EPISODES"),
    (policy.ledger, "_TABLES"), (policy.ledger, "_SCHEMA_SPEC"), (policy.ledger, "_ID"),
    (policy.ledger, "_MAX_ROWS"), (policy.ledger, "_MAX_IDS"),
    (policy.ledger, "_MAX_ROW_BYTES"), (policy.ledger, "_MAX_BYTES"),
    (policy.sync, "_MAX_WAITERS"),
])
def test_original_aliases_and_finite_domains_cannot_drift(module, name, monkeypatch):
    monkeypatch.setattr(module, name, object())
    _refuses()


@pytest.mark.parametrize("module,name", [
    (sqlite3, "connect"), (_sqlite3, "connect"),
    (sqlite3, "Connection"), (_sqlite3, "Connection"),
    (sqlite3, "Cursor"), (_sqlite3, "Cursor"),
    (sqlite3, "Error"), (_sqlite3, "Error"),
    (sqlite3, "DataError"), (_sqlite3, "DataError"), (sqlite3, "SQLITE_LIMIT_LENGTH"),
    (hashlib, "sha256"), (json, "loads"), (json, "dumps"),
    (json_spec, "canonical_json"),
])
def test_runtime_edges_are_checked_before_substituted_callbacks(module, name, monkeypatch):
    calls = []

    def callback(*_args, **_kwargs):
        calls.append(name)
        raise AssertionError("substituted runtime executed")

    with monkeypatch.context() as patch:
        patch.setattr(module, name, callback)
        _refuses()
    assert calls == []


def test_shared_serializer_and_all_capture_aliases_cannot_be_changed_together(monkeypatch):
    original = json_spec.canonical_json
    clone = FunctionType(original.__code__, original.__globals__, original.__name__,
                         original.__defaults__, original.__closure__)
    monkeypatch.setattr(json_spec, "canonical_json", clone)
    monkeypatch.setattr(policy.owner, "canonical_json", clone)
    monkeypatch.setattr(policy.reference, "canonical_json", clone)
    _refuses()


def test_publication_owner_capture_alias_is_the_original_function(monkeypatch):
    monkeypatch.setattr(publication._BRSLineageCheckpointOwner,
                        "retain_rejection_ready_capture", _forbidden)
    _refuses()


def test_publication_condition_seam_must_keep_the_original_guard(monkeypatch):
    monkeypatch.setattr(publication, "_ORIGINAL_READY_CONDITION_ASSERT", _forbidden)
    _refuses()


def test_replacing_sys_modules_cannot_hide_the_original_registry(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(sys, "modules", dict(sys.modules))
        _refuses()


@pytest.mark.parametrize("name", [
    "lunar_evolution.rsi_brs_rejection_ready_owner", "lunar_evolution.rsi_brs_rejection_ready_sync",
    "lunar_evolution.rsi_brs_rejection_ready_reference", "lunar_evolution.rsi_brs_rejection_ready_ledger",
    "lunar_evolution.rsi_brs_publication_lineage", "sqlite3",
    "lunar_evolution.rsi_brs_rejection_ready_ack",
    "lunar_evolution.rsi_brs_rejection_ready_locks",
    "lunar_evolution.rsi_brs_rejection_ready_state",
])
def test_canonical_module_registry_bindings_cannot_change(name, monkeypatch):
    monkeypatch.setitem(sys.modules, name, object())
    _refuses()


@pytest.mark.parametrize("module", [policy.owner, policy.reference, policy.ledger, policy.sync,
                                    policy.ack, policy.locks, policy.state])
def test_capture_namespaces_have_an_exact_key_domain(module, monkeypatch):
    monkeypatch.setattr(module, "invented_alias", _forbidden, raising=False)
    _refuses()


@pytest.mark.parametrize("namespace", [
    vars(policy), vars(policy.owner), vars(policy.reference), vars(policy.ledger),
    vars(sqlite3), vars(sys), sys.modules, vars(publication),
])
def test_non_string_keys_are_refused_before_any_key_hash_or_equality(namespace):
    calls = []
    armed = False

    class Key:
        def __hash__(self):
            calls.append("hash")
            return hash("connect")

        def __eq__(self, _other):
            calls.append("eq")
            if armed:
                raise AssertionError("foreign dictionary key compared")
            return False

    key = Key()
    namespace[key] = object()
    calls.clear()
    armed = True
    try:
        _refuses()
        observed = tuple(calls)
    finally:
        armed = False
        del namespace[key]
    assert observed == ()


@pytest.mark.parametrize("module", [policy.owner, policy.reference, policy.ledger, json_spec])
def test_new_builtin_shadows_are_rejected_before_execution(module, monkeypatch):
    monkeypatch.setattr(module, "type", _forbidden, raising=False)
    _refuses()


@pytest.mark.parametrize("name", ["type", "enumerate", "staticmethod", "classmethod", "property"])
def test_actual_builtin_lookup_bindings_are_held_before_use(name):
    original = vars(builtins)[name]
    error = None
    try:
        vars(builtins)[name] = _forbidden
        try:
            policy.rejection_ready_capture_policy()
        except RSILearningError as exc:
            error = exc
    finally:
        vars(builtins)[name] = original
    assert error is not None
    assert "rejection_ready_capture_policy_drift" in str(error)


def test_oversized_registry_is_rejected_without_visiting_all_entries(monkeypatch):
    additions = {f"lunar_ready_policy_test_{number}": None for number in range(16385)}
    try:
        for name, value in additions.items():
            monkeypatch.setitem(sys.modules, name, value)
        _refuses()
    finally:
        for name in additions:
            sys.modules.pop(name, None)


@pytest.mark.parametrize("function", policy.state._STATE_FUNCTIONS)
def test_finite_transition_reader_local_codes_are_independently_held(function, monkeypatch):
    monkeypatch.setattr(function, "__code__", _forbidden.__code__ if not function.__closure__
                        else function.__code__.replace(co_name="foreign"))
    _refuses()
