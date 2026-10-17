"""The compact owner policy still checks the complete finite C1/P/C2 graph."""

from __future__ import annotations

import re
from types import FunctionType

import pytest

from lunar_evolution import rsi_brs_publication_lineage as owner
from lunar_evolution import rsi_brs_rejection_provenance as provenance
from lunar_evolution import rsi_brs_rejection_provenance_policy as provenance_policy
from lunar_evolution import rsi_native_rejection as native
from lunar_evolution import rsi_native_scheduler as scheduler
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_fingerprint import (
    MAX_FINGERPRINT_RECORD_BYTES,
    RSIFingerprintContract,
    _normalize_json,
)
from lunar_evolution.rsi_identity import MAX_IDENTITY_BYTES, _normalize
from lunar_evolution.rsi_learning import RSILearningError


@pytest.fixture(scope="module")
def original_policy():
    return owner._policy()


def _replacement(*_args, **_kwargs):
    raise AssertionError("owner policy executed a substituted provenance dependency")


def _assert_drift(original):
    try:
        current = owner._policy()
    except RSILearningError:
        return
    assert current != original, "provenance dependency changed without invalidating owner policy"


def test_compact_dependency_preserves_original_fingerprint_limits(original_policy):
    assert original_policy["rejection_provenance_schema"] == provenance.REJECTION_PROVENANCE_SCHEMA
    assert original_policy["production_admission"] is False
    assert original_policy["online_publication"] is False
    assert re.fullmatch(r"[0-9a-f]{64}", original_policy["dependencies"]["rejection_provenance"])
    assert _normalize(original_policy) == original_policy
    _normalize_json(original_policy)
    assert len(canonical_json(original_policy, maximum=MAX_IDENTITY_BYTES)) < MAX_IDENTITY_BYTES

    contract = RSIFingerprintContract.build(
        contract_sha256="a" * 64,
        evaluator_sha256="b" * 64,
        environment_sha256="c" * 64,
        memory_snapshot_sha256="d" * 64,
        solver_id="native_population",
        solver_settings={"producer_brs_checkpoint_policy": original_policy},
        actor_fingerprint="e" * 64,
        verifier_fingerprint="f" * 64,
        curriculum_fingerprint="1" * 64,
        target_judge_fingerprint="2" * 64,
    )
    payload = contract.to_dict()
    assert RSIFingerprintContract.from_dict(payload) == contract
    assert len(canonical_json(payload, maximum=MAX_FINGERPRINT_RECORD_BYTES)) < MAX_FINGERPRINT_RECORD_BYTES


@pytest.mark.parametrize("name", ["_wire", "_read_p", "_readback", "_fresh", "_policy_gate"])
def test_owner_helper_replacement_changes_policy(monkeypatch, original_policy, name):
    monkeypatch.setattr(provenance, name, _replacement)
    _assert_drift(original_policy)


@pytest.mark.parametrize("target,name", [
    (provenance, "_wire"),
    (provenance, "_read_p"),
    (provenance_policy, "_check_function"),
    (provenance_policy, "native_rejection_provenance_policy"),
])
def test_identical_provenance_code_with_foreign_globals_is_refused(monkeypatch, original_policy, target, name):
    previous = getattr(target, name)
    shadow = FunctionType(previous.__code__, dict(previous.__globals__),
                          previous.__name__, previous.__defaults__, previous.__closure__)
    shadow.__module__ = previous.__module__
    shadow.__qualname__ = previous.__qualname__
    monkeypatch.setattr(target, name, shadow)
    with pytest.raises(RSILearningError):
        owner._policy()


@pytest.mark.parametrize("name", [
    "rejection_provenance_binding", "retain_rejection_provenance",
    "acknowledge_rejection_provenance", "rejection_provenance_file_pin",
])
def test_original_owner_public_alias_is_required(monkeypatch, original_policy, name):
    monkeypatch.setattr(owner._BRSLineageCheckpointOwner, name, _replacement)
    with pytest.raises(RSILearningError):
        owner._policy()


@pytest.mark.parametrize("name", [
    "persist_native_rsi_rejection_provenance", "read_native_rsi_rejection_provenance",
    "_read_ledger_identity", "retained_brs_c2_evidence_bytes",
    "validate_python_rsi_scheduler_inputs",
])
def test_owner_import_edge_is_refused_before_replacement_runs(monkeypatch, original_policy, name):
    monkeypatch.setattr(provenance, name, _replacement)
    with pytest.raises(RSILearningError):
        owner._policy()


@pytest.mark.parametrize("target,name", [
    (native, "persist_native_rsi_rejection_provenance"),
    (scheduler, "_read_ledger_identity"),
    (provenance_policy, "_check_function"),
])
def test_native_and_policy_helper_drift_reaches_integrated_policy(monkeypatch, original_policy, target, name):
    monkeypatch.setattr(target, name, _replacement)
    _assert_drift(original_policy)


def test_compressed_policy_still_checks_native_field_domain(monkeypatch, original_policy):
    monkeypatch.setattr(native, "_PIN_FIELDS", native._PIN_FIELDS | {"foreign"})
    _assert_drift(original_policy)


@pytest.mark.parametrize("target,name,literal", [
    (provenance, "_wire", "rejection_provenance"),
    (provenance, "_policy_gate", "policy_drift"),
    (provenance_policy, "_check_function", None),
])
def test_live_code_drift_with_unchanged_source_location_is_observed(
    monkeypatch, original_policy, target, name, literal,
):
    function = getattr(target, name)
    code = function.__code__
    if literal is None:
        constants = (*code.co_consts, "foreign-unused-constant")
    else:
        assert literal in code.co_consts
        constants = tuple("foreign-literal" if value == literal else value for value in code.co_consts)
    changed = code.replace(co_consts=constants)
    assert changed.co_filename == code.co_filename
    assert changed.co_firstlineno == code.co_firstlineno
    monkeypatch.setattr(function, "__code__", changed)
    _assert_drift(original_policy)


@pytest.mark.parametrize("target,name", [
    (provenance, "_wire"),
    (provenance_policy, "_check_function"),
])
@pytest.mark.parametrize("attribute", [
    "rsi_fingerprint_config", "fingerprint_config",
    "rsi_fingerprint_code", "fingerprint_code", "__wrapped__",
])
def test_new_callable_attributes_are_refused_before_any_fingerprint_callback(
    monkeypatch, original_policy, target, name, attribute,
):
    function = getattr(target, name)
    assert attribute not in function.__dict__
    code = function.__code__
    calls = []

    def injected():
        calls.append(attribute)
        raise AssertionError("fingerprint callback ran after the final physical material check")

    monkeypatch.setattr(function, attribute, injected, raising=False)
    assert getattr(target, name) is function and function.__code__ is code
    with pytest.raises(RSILearningError, match="^rsi_brs_publication_lineage_rejection_policy_drift$"):
        owner._policy()
    assert calls == []
