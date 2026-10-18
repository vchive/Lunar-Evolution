"""Fresh C1 policy binds live dependencies without expanding identity limits."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import stat
from types import FunctionType

import pytest

from lunar_evolution import producer_bundle_receipts as receipts
from lunar_evolution import producer_bundle_rejection as native_rejection
from lunar_evolution import rsi_brs_publication_lineage as owner
from lunar_evolution import rsi_brs_rejection_c1 as rejection
from lunar_evolution import rsi_brs_rejection_capacity as capacity
from lunar_evolution import rsi_brs_rejection_owner as retention
from lunar_evolution import rsi_store
from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_fingerprint import _normalize_json
from lunar_evolution.rsi_identity import MAX_IDENTITY_BYTES, _normalize
from lunar_evolution.rsi_learning import RSILearningError


@pytest.fixture(scope="module")
def original_policy():
    return owner._policy()


def _replacement(*_args, **_kwargs):
    raise AssertionError("policy observation executed a substituted C1 dependency")


def _assert_drift(original):
    try:
        current = owner._policy()
    except RSILearningError:
        return
    assert current != original, "C1 dependency changed without invalidating captured policy"


def test_rejection_policy_uses_explicit_schema_and_original_normalizers(original_policy):
    assert original_policy["rejection_schema"] == rejection.REJECTION_SCHEMA
    assert original_policy["production_admission"] is False
    assert original_policy["online_publication"] is False
    assert _normalize(original_policy) == original_policy
    _normalize_json(original_policy)
    assert len(json.dumps(original_policy, sort_keys=True).encode()) < MAX_IDENTITY_BYTES


@pytest.mark.parametrize("target,name", [
    (owner._BRSLineageCheckpointOwner, "retain_rejected_terminal"),
    (owner._BRSLineageCheckpointOwner, "checkpoint_rejected"),
    (retention, "_rejection_cap_unchanged"),
    (retention, "_rejection_readback"),
    (retention, "_rejection_readback_observe"),
    (retention, "_rejection_final_readback"),
    (native_rejection, "_exact_evidence_shape"),
    (native_rejection.VerifiedProducerBundleRejection, "__post_init__"),
    (RSIRunBudget, "check"),
    (rejection, "rejected_c1_entry"),
    (rejection, "rejected_c1_index"),
    (rejection, "validate_rejected_c1_transition"),
    (capacity, "retained_brs_c1_evidence_bytes"),
    (capacity, "_add_material"),
    (capacity, "_pin_record"),
])
def test_c1_live_method_drift_is_observed(monkeypatch, original_policy, target, name):
    monkeypatch.setattr(target, name, _replacement)
    _assert_drift(original_policy)


@pytest.mark.parametrize("name", [
    "MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES",
    "MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES",
])
def test_capacity_constant_drift_is_observed(monkeypatch, original_policy, name):
    monkeypatch.setattr(capacity, name, getattr(capacity, name) + 1)
    _assert_drift(original_policy)


def test_schema_drift_cannot_backfill_old_policy(monkeypatch, original_policy):
    monkeypatch.setattr(rejection, "REJECTION_SCHEMA", "lunar-rsi-brs-rejection-c1-foreign")
    _assert_drift(original_policy)


def test_rejection_field_domain_drift_is_observed(monkeypatch, original_policy):
    monkeypatch.setattr(rejection, "_REJECTED_FIELDS", rejection._REJECTED_FIELDS | {"foreign"})
    _assert_drift(original_policy)


def test_capacity_regex_flags_participate_in_policy(monkeypatch, original_policy):
    previous = capacity._IDENTIFIER
    monkeypatch.setattr(capacity, "_IDENTIFIER", re.compile(previous.pattern, previous.flags | re.IGNORECASE))
    _assert_drift(original_policy)


@pytest.mark.parametrize("target,name", [
    (rejection, "rejected_c1_entry"),
    (capacity, "retained_brs_c1_evidence_bytes"),
    (retention, "_rejection_final_readback"),
    (rsi_store.RSILedger, "controller_checkpoint_history"),
])
def test_identical_code_with_foreign_globals_is_refused(monkeypatch, original_policy, target, name):
    previous = getattr(target, name)
    shadow = FunctionType(previous.__code__, dict(previous.__globals__),
                          previous.__name__, previous.__defaults__, previous.__closure__)
    shadow.__module__ = previous.__module__
    shadow.__qualname__ = previous.__qualname__
    monkeypatch.setattr(target, name, shadow)
    with pytest.raises(RSILearningError):
        owner._policy()


@pytest.mark.parametrize("name", ["persist_lineage_v2_descriptor", "read_lineage_v2_descriptor_pinned"])
def test_descriptor_alias_rebinding_is_refused(monkeypatch, original_policy, name):
    monkeypatch.setattr(retention, name, _replacement)
    with pytest.raises(RSILearningError):
        owner._policy()


@pytest.mark.parametrize("target,name", [
    (native_rejection, "_EVIDENCE_FIELDS"), (native_rejection, "_MANIFEST_FIELDS"),
    (receipts, "_RETAINED_EVIDENCE_FIELDS"), (receipts, "_RETAINED_ENTRY_FIELDS"),
])
def test_native_rejection_live_fields_participate_in_policy(monkeypatch, original_policy, target, name):
    monkeypatch.setattr(target, name, getattr(target, name) | {"foreign"})
    _assert_drift(original_policy)


@pytest.mark.parametrize("target,name", [
    (native_rejection, "_DIGEST"), (receipts, "_SHA256"), (receipts, "_ID"),
])
def test_native_rejection_regex_flags_participate_in_policy(monkeypatch, original_policy, target, name):
    previous = getattr(target, name)
    monkeypatch.setattr(target, name, re.compile(previous.pattern, previous.flags | re.IGNORECASE))
    _assert_drift(original_policy)


@pytest.mark.parametrize("target,name", [
    (rejection, "hashlib"), (capacity, "hashlib"),
    (rsi_store, "sqlite3"), (rsi_store, "json"), (rsi_store, "hashlib"),
])
def test_final_rejection_module_alias_drift_is_refused(monkeypatch, original_policy, target, name):
    monkeypatch.setattr(target, name, object())
    with pytest.raises(RSILearningError):
        owner._policy()


@pytest.mark.parametrize("target,name", [
    (sqlite3, "connect"), (sqlite3, "Row"), (json, "loads"), (json, "dumps"),
    (hashlib, "sha256"), (os, "fstat"), (os, "stat"),
    (stat, "S_ISDIR"), (stat, "S_ISREG"), (contextlib, "_GeneratorContextManager"),
])
def test_final_runtime_substitution_is_refused_before_policy_callbacks(monkeypatch, original_policy, target, name):
    calls = []
    def forbidden(*_args, **_kwargs):
        calls.append(name)
        raise AssertionError("substituted runtime reader ran during policy construction")
    with monkeypatch.context() as patch:
        patch.setattr(target, name, forbidden)
        with pytest.raises(RSILearningError):
            owner._policy()
    assert calls == []


@pytest.mark.parametrize("function", [json.loads, json.dumps, contextlib._GeneratorContextManager.__enter__])
def test_same_runtime_function_code_substitution_is_refused(monkeypatch, original_policy, function):
    with monkeypatch.context() as patch:
        patch.setattr(function, "__code__", _replacement.__code__)
        with pytest.raises(RSILearningError):
            owner._policy()
