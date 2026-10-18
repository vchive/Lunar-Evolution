"""Finite reserved composition drift gates confer no execution authority."""
from __future__ import annotations

import importlib
import json
import sys
import threading
from types import FunctionType

import pytest

from lunar_evolution import rsi_brs_reserved_policy as policy
from lunar_evolution import rsi_brs_reserved_wave as wave
from lunar_evolution.rsi_learning import RSILearningError


def _forbidden(*_args, **_kwargs):
    raise AssertionError("reserved policy executed a replaced dependency")


@pytest.fixture(autouse=True)
def _original_graph():
    policy.reserved_brs_policy_projection()


def _refuses():
    with pytest.raises(RSILearningError, match="rsi_brs_reserved_policy_drift"):
        policy.reserved_brs_policy_projection()


def _captures(function):
    return dict(zip(function.__code__.co_freevars, function.__closure__, strict=True))


def test_projection_is_compact_stable_and_has_no_authority():
    first = policy.reserved_brs_policy_projection()
    assert first == policy.reserved_brs_policy_projection()
    assert set(first) == {"protocol", "sha256"}
    assert first["protocol"] == "lunar-rsi-brs-reserved-executable-policy-v1"
    assert len(first["sha256"]) == 64
    assert len(json.dumps(first)) < 256


@pytest.mark.parametrize("module_name", policy._MODULE_NAMES)
def test_finite_module_namespace_addition_is_rejected(module_name, monkeypatch):
    module = importlib.import_module("lunar_evolution." + module_name)
    monkeypatch.setattr(module, "foreign_reserved_alias", _forbidden, raising=False)
    _refuses()


@pytest.mark.parametrize("name", ["_fail", "_integer", "_checkpoint", "_raw"])
def test_imported_or_own_helper_replacement_is_rejected(name, monkeypatch):
    monkeypatch.setattr(wave, name, _forbidden)
    _refuses()


def test_same_function_identity_cannot_hide_code_change(monkeypatch):
    monkeypatch.setattr(wave._integer, "__code__", wave._integer.__code__.replace(co_name="foreign"))
    _refuses()


def test_function_mutable_attributes_are_observed(monkeypatch):
    monkeypatch.setitem(wave._integer.__dict__, "foreign", True)
    _refuses()


def test_nested_mutable_constants_are_observed(monkeypatch):
    monkeypatch.setattr(wave, "_TRACE_FIELDS", wave._TRACE_FIELDS)  # Restore the same original set.
    saved = set(wave._TRACE_FIELDS)
    try:
        wave._TRACE_FIELDS.add("foreign")
        _refuses()
    finally:
        wave._TRACE_FIELDS.clear()
        wave._TRACE_FIELDS.update(saved)


def test_dataclass_field_metadata_is_observed(monkeypatch):
    field = wave.BRSReservedChildSelection.__dataclass_fields__["ordinal"]
    monkeypatch.setattr(field, "init", False)
    _refuses()


def test_dataclass_annotations_are_observed(monkeypatch):
    monkeypatch.setitem(wave.BRSReservedChildSelection.__annotations__, "ordinal", "foreign")
    _refuses()


def test_dataclass_generated_constructor_code_is_observed(monkeypatch):
    function = wave.BRSReservedChildSelection.__init__
    monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="foreign"))
    _refuses()


def test_original_module_registration_cannot_be_replaced(monkeypatch):
    monkeypatch.setitem(sys.modules, wave.__name__, object())
    _refuses()


def test_runtime_alias_is_checked_before_it_can_execute(monkeypatch):
    monkeypatch.setattr(json, "loads", _forbidden)
    _refuses()


@pytest.mark.parametrize("name", ["len", "tuple", "type"])
def test_new_builtin_shadow_is_rejected_without_calling_it(name, monkeypatch):
    monkeypatch.setattr(policy, name, _forbidden, raising=False)
    _refuses()


def test_cached_project_replacement_is_rejected_without_calling_it(monkeypatch):
    monkeypatch.setattr(policy, "_PROJECT", _forbidden)
    _refuses()


def test_same_cached_project_cannot_hide_code_change(monkeypatch):
    original = policy._PROJECT
    monkeypatch.setattr(original, "__code__", original.__code__.replace(co_name="foreign"))
    _refuses()


@pytest.mark.parametrize("name", ["fail", "freeze"])
def test_nested_guard_helpers_are_checked_before_execution(name, monkeypatch):
    function = _captures(policy._PROJECT)[name].cell_contents
    assert type(function) is FunctionType
    monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="foreign"))
    _refuses()


def test_foreign_metaclass_is_not_invoked_by_nested_container_observation():
    calls = []

    class HostileMeta(type):
        def __eq__(self, other):
            calls.append("eq")
            raise AssertionError("foreign equality executed")

    class Foreign(metaclass=HostileMeta):
        pass

    field = wave.BRSReservedChildSelection.__dataclass_fields__["ordinal"]
    saved = field.default
    try:
        field.default = Foreign()
        _refuses()
        assert calls == []
    finally:
        field.default = saved


def test_thread_lifecycle_does_not_change_the_policy():
    original = policy.reserved_brs_policy_projection()
    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join()
    assert policy.reserved_brs_policy_projection() == original


@pytest.mark.parametrize("module_name,name", [
    ("rsi_producer_launch", "MAX_STAGING_BINDING_BYTES"),
    ("rsi_producer_staging_capsule", "MAX_READY_BINDING_BYTES"),
])
def test_declared_staging_limit_changes_identity_without_poisoning_unrelated_runs(module_name, name, monkeypatch):
    module = importlib.import_module("lunar_evolution." + module_name)
    original = policy.reserved_brs_policy_projection()
    with monkeypatch.context() as patch:
        patch.setattr(module, name, getattr(module, name) * 2)
        assert policy.reserved_brs_policy_projection() != original
    assert policy.reserved_brs_policy_projection() == original


@pytest.mark.parametrize("module_name,name", [
    ("rsi_native_scheduler", "__call__"),
    ("rsi_native_scheduler", "recover_live_rejection"),
    ("rsi_native_scheduler", "_native_rejection_snapshot"),
    ("rsi_brs_serial_budget", "validate_reserved_brs_finalization_budget"),
])
def test_reserved_delegates_remain_executable_pins(module_name, name, monkeypatch):
    module = importlib.import_module("lunar_evolution." + module_name)
    if module_name == "rsi_native_scheduler":
        function = vars(module.NativeRSISchedulerProvider)[name]
    else:
        function = vars(module)[name]
    monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="foreign"))
    _refuses()
