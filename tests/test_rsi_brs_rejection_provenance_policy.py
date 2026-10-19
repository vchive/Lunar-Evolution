"""Finite native P policy observes drift without invoking substituted readers."""

from __future__ import annotations

import dataclasses
import gc
import hashlib
import json
import os
import pathlib
import re
import stat
import sys
import warnings
from types import FunctionType

import pytest

from lunar_evolution import candidate_evaluation_spec as json_spec
from lunar_evolution import rsi_brs_rejection_provenance_policy as policy
from lunar_evolution import rsi_native_rejection as native
from lunar_evolution import rsi_native_scheduler as scheduler
from lunar_evolution.rsi_fingerprint import _normalize_json
from lunar_evolution.rsi_identity import MAX_IDENTITY_BYTES, _normalize
from lunar_evolution.rsi_learning import RSILearningError


def _forbidden(*_args, **_kwargs):
    raise AssertionError("policy called a substituted native dependency")


def _refuses():
    with pytest.raises(RSILearningError, match="rejection_provenance_policy_drift"):
        policy.native_rejection_provenance_policy()


def test_finite_policy_fits_existing_normalizers_and_keeps_native_0400_domain():
    first = policy.native_rejection_provenance_policy()
    assert first == policy.native_rejection_provenance_policy()
    assert _normalize(first) == first
    _normalize_json(first)
    assert len(json.dumps(first, sort_keys=True).encode()) < MAX_IDENTITY_BYTES
    assert first["native_pin_mode"] == 0o400 and first["native_pin_nlink"] == 1
    assert first["constants"]["native"]["MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES"] == 1024 * 1024
    assert first["constants"]["native"]["MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES"] == 64 * 1024 * 1024
    assert len(first["functions"]["native"]) < 64


def test_warning_registry_does_not_change_finite_policy():
    first = policy.native_rejection_provenance_policy()
    registry = {}
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.warn_explicit(
            "fixture warning", RuntimeWarning, policy.__file__ or "rsi_brs_rejection_provenance_policy.py", 1,
            registry=registry,
        )
    # ``warn_explicit`` generated the same shape of registry that CPython
    # stores on a module; install it only for the projection and clean it up.
    vars(policy)["__warningregistry__"] = registry
    try:
        assert policy.native_rejection_provenance_policy() == first
    finally:
        vars(policy).pop("__warningregistry__", None)


@pytest.mark.parametrize("owner,name", [
    (native, "persist_native_rsi_rejection_provenance"),
    (native, "read_native_rsi_rejection_provenance"),
    (native, "_record"), (native, "_read_once"), (native, "_pin"),
    (native, "_dto_shape"), (native, "_plain_mapping"), (native, "_reparse"),
    (native.NativeRSIRejectionFilePin, "__post_init__"),
    (native.NativeRSIRejectionFilePin, "to_dict"), (native.NativeRSIRejectionFilePin, "from_dict"),
    (native.NativeRSIRejectionEvidence, "__post_init__"),
    (native.NativeRSIRejectionEvidence, "to_dict"), (native.NativeRSIRejectionEvidence, "from_dict"),
    (native.RejectionLineageC1Binding, "to_dict"), (native.RejectionLineageC1Binding, "from_dict"),
    (scheduler, "_read_ledger_identity"), (scheduler, "_fail"),
    (policy.store.RSILedger, "_native_claim_digest"),
    (policy.native_plan.NativeRSIExecutionPlan, "from_dict"),
    (policy.gateway.SolverRequest, "from_dict"),
    (policy.workspace_io.DirectoryChain, "check"),
    (pathlib.Path, "absolute"), (pathlib.Path, "expanduser"), (pathlib.PurePath, "is_absolute"),
])
def test_actual_native_and_shared_methods_cannot_be_replaced(owner, name, monkeypatch):
    monkeypatch.setattr(owner, name, _forbidden)
    _refuses()


@pytest.mark.parametrize("name", ["_record", "_dto_shape", "persist_native_rsi_rejection_provenance"])
def test_identical_source_with_foreign_globals_is_refused(name, monkeypatch):
    original = getattr(native, name)
    clone = FunctionType(original.__code__, dict(original.__globals__), original.__name__,
                         original.__defaults__, original.__closure__)
    clone.__module__, clone.__qualname__ = original.__module__, original.__qualname__
    monkeypatch.setattr(native, name, clone)
    _refuses()


def test_both_import_and_canonical_serializer_cannot_be_rebound_to_one_clone(monkeypatch):
    original = json_spec.canonical_json
    clone = FunctionType(original.__code__, dict(original.__globals__), original.__name__,
                         original.__defaults__, original.__closure__)
    clone.__module__, clone.__qualname__ = original.__module__, original.__qualname__
    monkeypatch.setattr(json_spec, "canonical_json", clone)
    monkeypatch.setattr(native, "canonical_json", clone)
    _refuses()


@pytest.mark.parametrize("owner,name", [
    (native, "gc"), (native, "fields"), (native, "MappingProxyType"),
    (native, "DirectoryChain"), (native, "NativeRSIExecutionPlan"),
    (native, "NativeRSIRejectionFilePin"), (native, "strict_json"),
    (scheduler, "DirectoryChain"), (scheduler, "os"), (scheduler, "stat"), (scheduler, "RSILedger"),
])
def test_canonical_import_edges_are_checked_before_callbacks(owner, name, monkeypatch):
    monkeypatch.setattr(owner, name, object())
    _refuses()


@pytest.mark.parametrize("owner,name", [
    (os, "open"), (os, "read"), (os, "write"), (os, "fchmod"), (os, "fsync"),
    (os, "fstat"), (os, "stat"), (os, "close"),
    (stat, "S_ISREG"), (stat, "S_ISDIR"), (stat, "S_IMODE"),
    (gc, "get_referents"), (dataclasses, "fields"),
    (json, "loads"), (json, "dumps"), (hashlib, "sha256"),
    (sys, "exception"), (os, "getcwd"), (os.path, "expanduser"),
])
def test_runtime_binding_drift_is_refused_before_fingerprinting(owner, name, monkeypatch):
    calls = []

    def callback(*_args, **_kwargs):
        calls.append(name)
        raise AssertionError("policy executed substituted runtime")

    with monkeypatch.context() as patch:
        patch.setattr(owner, name, callback)
        _refuses()
    assert calls == []


@pytest.mark.parametrize("function", [native._record, native._dto_shape, json.dumps, dataclasses.fields])
def test_original_function_live_code_is_checked(function, monkeypatch):
    monkeypatch.setattr(function, "__code__", _forbidden.__code__)
    _refuses()


def test_generated_dto_constructor_closure_is_checked():
    closure = native.NativeRSIRejectionFilePin.__init__.__closure__
    assert closure
    cell = closure[0]
    original = cell.cell_contents
    try:
        cell.cell_contents = object()
        _refuses()
    finally:
        cell.cell_contents = original


def test_classmethod_kwdefaults_mutation_is_checked_before_serialization(monkeypatch):
    defaults = native.NativeRSIRejectionEvidence.from_dict.__func__.__kwdefaults__
    monkeypatch.setitem(defaults, "provenance_sha256", "f" * 64)
    _refuses()


def test_function_code_hook_injection_cannot_execute_during_policy(monkeypatch):
    monkeypatch.setattr(native._record, "rsi_fingerprint_code", _forbidden, raising=False)
    _refuses()


@pytest.mark.parametrize("owner,name,value", [
    (native, "MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES", 1024 * 1024 + 1),
    (native, "MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES", 64 * 1024 * 1024 + 1),
    (native, "_PROTOCOL", "foreign"), (native, "_MAX_INT", 2**64),
    (native, "NATIVE_RSI_REJECTION_PROVENANCE_NAME", "foreign.json"),
    (native, "NATIVE_RSI_PROVENANCE_NAMES", ("foreign.json",)),
    (os, "O_NOFOLLOW", 0),
])
def test_finite_limits_protocols_names_and_open_flags_cannot_drift(owner, name, value, monkeypatch):
    monkeypatch.setattr(owner, name, value)
    _refuses()


def test_native_field_set_in_place_mutation_is_observed():
    fields = native._PIN_FIELDS
    try:
        fields.add("invented_permission")
        _refuses()
    finally:
        fields.remove("invented_permission")


def test_native_regex_flags_are_bound(monkeypatch):
    monkeypatch.setattr(native, "_SHA", re.compile(native._SHA.pattern, native._SHA.flags | re.IGNORECASE))
    _refuses()


def test_foreign_constant_type_is_rejected_before_equality(monkeypatch):
    class DangerousString(str):
        def __eq__(self, _other):
            pytest.fail("policy invoked foreign constant equality")

    monkeypatch.setattr(native, "_PROTOCOL", DangerousString(native._PROTOCOL))
    _refuses()


def test_native_dataclass_field_names_cannot_be_mutated(monkeypatch):
    field = native.NativeRSIRejectionFilePin.__dataclass_fields__["mode"]
    monkeypatch.setattr(field, "name", "permission")
    _refuses()
