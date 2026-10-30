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


def test_module_warning_registry_mutation_is_not_executable_policy_drift(monkeypatch):
    module = importlib.import_module("lunar_evolution.rsi_brs_reserved_wave")
    registry = {}
    monkeypatch.setattr(module, "__warningregistry__", registry, raising=False)
    # Rebuild the private projection so the test exercises a registry present
    # at capture time, then a warning-cache insertion into that dictionary.
    monkeypatch.setattr(policy, "_PROJECT", None)
    monkeypatch.setattr(
        policy, "reserved_brs_policy_projection", policy._build_reserved_brs_policy_entry(),
    )

    first = policy.reserved_brs_policy_projection()
    registry[("routine warning", 17, Warning)] = True

    assert policy.reserved_brs_policy_projection() == first


def test_module_warning_registry_rejects_non_dict_replacement(monkeypatch):
    module = importlib.import_module("lunar_evolution.rsi_brs_reserved_wave")
    monkeypatch.setattr(module, "__warningregistry__", object(), raising=False)

    _refuses()


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


@pytest.mark.parametrize(("module_name", "owner_name", "name"), [
    ("rsi_native_scheduler", "NativeRSISchedulerContext", "__post_init__"),
    ("rsi_native_scheduler", "NativeRSISchedulerContext", "_assert_live_modules_sink"),
    ("rsi_native_scheduler", "NativeRSISchedulerContext", "_live_modules_sink_projection"),
    ("rsi_native_scheduler", "NativeRSISchedulerContext", "_native_scope_options"),
    ("rsi_native_scheduler", "NativeRSISchedulerContext", "_native_scope_projection"),
    ("native_trusted_scheduler", "_NativeSchedulerScopePin", "__init__"),
    ("native_trusted_scheduler", "_NativeSchedulerScopePin", "options"),
    ("native_pycache_diagnostic", "NativePycacheDiagnosticRequest", "validate"),
    ("native_trusted_scheduler", None, "_pin_native_scheduler_scope"),
    ("native_trusted_scheduler", None, "_native_scope_profile_snapshot"),
    ("native_trusted_scheduler", None, "_native_scope_deadline"),
    ("native_fixed_live_sink", "FixedPythonLiveSinkRequest", "validate"),
    ("native_fixed_live_sink", "FixedPythonLiveSinkRequest", "compare"),
    ("native_fixed_live_sink", "_FixedPythonLiveSinkPin", "__init__"),
    ("native_fixed_live_sink", "_FixedPythonLiveSinkPin", "assert_current"),
    ("native_fixed_live_sink", "_FixedPythonLiveSinkPin", "to_dict"),
    ("native_fixed_live_sink", None, "_pin_fixed_python_live_sink_request"),
    ("static_python_fixed_profile", None, "_reparse"),
    ("static_python_fixed_profile", None, "_parse_installation"),
    ("static_python_fixed_profile", None, "verify_fixed_python_image"),
    ("static_python_fixed_profile", "FixedPythonInstallation", "to_dict"),
    ("static_python_fixed_live_modules", None, "_compose"),
    ("static_python_fixed_live_modules", None, "compare_fixed_python_bound_live_modules"),
    ("static_python_fixed_live_modules", None, "_compare_live_payload"),
    ("static_python_fixed_runtime_observation", None, "_runtime_facts"),
    ("static_python_fixed_runtime_observation", None, "map_fixed_python_runtime_observation"),
    ("static_python_fixed_runtime_observation", None, "validate_fixed_python_runtime_observation_policy"),
    ("native_trusted_scheduler", None, "_run_native_trusted_producer"),
    ("native_trusted_scheduler", None, "_prepare_native_trusted_python_producer"),
    ("native_trusted_scheduler", None, "run_native_trusted_producer"),
    ("native_trusted_scheduler", None, "run_native_trusted_producer_outcome"),
])
def test_live_sink_scheduler_code_drift_is_rejected(module_name, owner_name, name, monkeypatch):
    module = importlib.import_module("lunar_evolution." + module_name)
    owner = module if owner_name is None else getattr(module, owner_name)
    function = getattr(owner, name)
    monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="foreign"))
    _refuses()


@pytest.mark.parametrize("name", [
    "_pin_native_scheduler_scope", "_native_scope_profile_snapshot", "_native_scope_deadline",
])
def test_original_scope_helper_alias_drift_is_rejected_without_execution(name, monkeypatch):
    module = importlib.import_module("lunar_evolution.native_trusted_scheduler")
    monkeypatch.setattr(module, name, _forbidden)
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


@pytest.mark.parametrize("name", ["fail", "freeze", "matches_frozen"])
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


@pytest.mark.parametrize("name", [
    "_memory_item", "_decision_from_dict", "_deserialize_execution", "_serialize_execution",
])
def test_capacity_prediction_static_controller_helpers_reject_code_drift(monkeypatch, name):
    from lunar_evolution.rsi_controller import RSILearningController

    descriptor = vars(RSILearningController)[name]
    assert isinstance(descriptor, staticmethod)
    function = descriptor.__func__
    monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="foreign"))
    _refuses()


@pytest.mark.parametrize("name", [
    "_validate_brs_reserved_prefixes", "_validate_brs_reserved_prefix_walk", "_project_brs_reserved_prefix",
])
@pytest.mark.parametrize("drift", ["alias", "code", "defaults", "annotations"])
def test_ordered_prefix_walk_helpers_are_full_executable_and_capture_pins(name, drift, monkeypatch):
    module = importlib.import_module("lunar_evolution.rsi_brs_lineage_prefix")
    function = vars(module)[name]
    if drift == "alias":
        monkeypatch.setattr(module, name, _forbidden)
    elif drift == "code":
        monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="foreign"))
    elif drift == "defaults":
        monkeypatch.setattr(function, "__kwdefaults__", {"foreign": True})
    else:
        monkeypatch.setitem(function.__annotations__, "foreign", True)
    _refuses()


def test_reserved_owner_ordered_prefix_alias_remains_pinned(monkeypatch):
    module = importlib.import_module("lunar_evolution.rsi_brs_reserved_owner")
    monkeypatch.setattr(module, "_validate_brs_reserved_prefixes", _forbidden)
    _refuses()
