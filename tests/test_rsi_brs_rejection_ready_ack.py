"""Pure constructor/slot custody checks; no owner, solver or publication fixture."""

from __future__ import annotations

import sys
from types import FunctionType, MappingProxyType

import pytest

from lunar_evolution import rsi_brs_rejection_ready_ack as guard
from lunar_evolution import rsi_learning as learning
from lunar_evolution import rsi_python_brs_admission as admission
from lunar_evolution.rsi_learning import RSILearningError

FIELDS = ("run", "episode", "1" * 64, "2" * 64)


def _forbidden(*_args, **_kwargs):
    raise AssertionError("changed ACK dependency executed")


def _refuses():
    with pytest.raises(RSILearningError, match="rejection_ready_ack_graph_drift"):
        guard.assert_rejection_ready_ack_graph()


def test_detached_ack_preserves_four_original_strings_and_grants_no_authority():
    assert guard.assert_rejection_ready_ack_graph() is None
    first = guard.build_rejection_ready_ack(FIELDS)
    second = guard.build_rejection_ready_ack(FIELDS)
    assert type(first) is admission.BRSAdmissionAck
    assert first is not second
    assert guard.assert_rejection_ready_ack(first, FIELDS) is None
    assert (first.run_id, first.episode_id, first.request_sha256, first.record_sha256) == FIELDS
    assert not hasattr(first, "__dict__")


@pytest.mark.parametrize("target,name", [
    (admission, "BRSAdmissionAck"), (admission, "RSIPythonBRSAdmissionError"),
    (learning, "RSILearningError"), (admission, "RSILearningError"),
    (admission, "_identity"), (admission, "_sha"), (admission, "_fail"),
    (admission, "_ID"), (admission, "_SHA"),
    (admission.BRSAdmissionAck, "__init__"),
    (admission.BRSAdmissionAck, "__post_init__"),
    (admission.RSIPythonBRSAdmissionError, "__init__"),
    (learning.RSILearningError, "__init__"),
    (admission.BRSAdmissionChannel, "request"),
])
def test_changed_graph_callbacks_are_rejected_without_invocation(target, name, monkeypatch):
    calls = []

    def changed(*_args, **_kwargs):
        calls.append(name)
        raise AssertionError("callback executed")

    monkeypatch.setattr(target, name, changed)
    _refuses()
    with pytest.raises(RSILearningError, match="rejection_ready_ack_graph_drift"):
        guard.build_rejection_ready_ack(FIELDS)
    assert calls == []


@pytest.mark.parametrize("function", [
    admission.BRSAdmissionAck.__post_init__, admission._identity, admission._sha,
    admission._fail, admission.BRSAdmissionChannel.request,
])
def test_original_executable_code_is_held(function, monkeypatch):
    monkeypatch.setattr(function, "__code__", _forbidden.__code__)
    _refuses()


@pytest.mark.parametrize("name,value", [
    ("__defaults__", (object(),)), ("__kwdefaults__", {"foreign": object()}),
    ("__annotations__", {"foreign": object()}), ("__name__", "foreign"),
    ("__qualname__", "foreign"), ("__module__", "foreign"), ("__doc__", "foreign"),
])
def test_function_metadata_cannot_rebaseline_the_original_constructor(name, value, monkeypatch):
    monkeypatch.setattr(admission.BRSAdmissionAck.__init__, name, value)
    _refuses()


@pytest.mark.parametrize("attribute", ["__dict__", "__annotations__"])
def test_in_place_function_metadata_is_held(attribute, monkeypatch):
    monkeypatch.setitem(getattr(admission._sha, attribute), "foreign", _forbidden)
    _refuses()


@pytest.mark.parametrize("function", [
    admission.BRSAdmissionAck.__init__,
    admission.RSIPythonBRSAdmissionError.__init__, learning.RSILearningError.__init__,
])
def test_original_constructor_and_error_super_closure_cells_are_held(function):
    cell = function.__closure__[0]
    original = cell.cell_contents
    try:
        cell.cell_contents = _forbidden
        _refuses()
    finally:
        cell.cell_contents = original


def test_empty_constructor_closure_is_a_fixed_refusal():
    cell = admission.BRSAdmissionAck.__init__.__closure__[0]
    original = cell.cell_contents
    try:
        del cell.cell_contents
        _refuses()
    finally:
        cell.cell_contents = original


def test_identical_function_code_in_foreign_globals_is_not_the_original(monkeypatch):
    original = admission._sha
    copy = FunctionType(original.__code__, dict(original.__globals__), original.__name__,
                        original.__defaults__, original.__closure__)
    monkeypatch.setattr(admission, "_sha", copy)
    _refuses()


@pytest.mark.parametrize("name", ["run_id", "episode_id", "request_sha256", "record_sha256"])
def test_class_native_slot_descriptors_cannot_be_replaced(name, monkeypatch):
    calls = []

    def changed(_self):
        calls.append(name)
        raise AssertionError("property executed")

    monkeypatch.setattr(admission.BRSAdmissionAck, name, property(changed))
    _refuses()
    assert calls == []


@pytest.mark.parametrize("name,value", [
    ("__slots__", ("other",)), ("__annotations__", {"other": str}),
    ("__dataclass_fields__", {}), ("__dataclass_params__", object()),
    ("__getattribute__", _forbidden),
])
def test_class_shape_and_lookup_metadata_are_original(name, value, monkeypatch):
    monkeypatch.setattr(admission.BRSAdmissionAck, name, value, raising=False)
    _refuses()


def test_in_place_dataclass_field_table_change_is_rejected(monkeypatch):
    fields = admission.BRSAdmissionAck.__dataclass_fields__
    monkeypatch.setitem(fields, "run_id", fields["episode_id"])
    _refuses()


@pytest.mark.parametrize("name,value", [
    ("name", "other"), ("type", object()), ("default", "other"),
    ("default_factory", _forbidden), ("init", False), ("repr", False),
    ("hash", True), ("compare", False), ("kw_only", True),
    ("_field_type", object()), ("metadata", MappingProxyType({"other": _forbidden})),
])
def test_all_dataclass_field_metadata_slots_are_held(name, value, monkeypatch):
    field = admission.BRSAdmissionAck.__dataclass_fields__["run_id"]
    monkeypatch.setattr(field, name, value)
    _refuses()


def test_in_place_dataclass_annotations_are_held(monkeypatch):
    monkeypatch.setitem(admission.BRSAdmissionAck.__annotations__, "run_id", object())
    _refuses()


def test_dataclass_parameter_values_are_held(monkeypatch):
    monkeypatch.setattr(admission.BRSAdmissionAck.__dataclass_params__, "frozen", False)
    _refuses()


@pytest.mark.parametrize("name", ["type", "str", "super"])
def test_builtin_shadowing_in_constructor_namespace_is_rejected(name, monkeypatch):
    monkeypatch.setattr(admission, name, _forbidden, raising=False)
    _refuses()


def test_learning_error_builtin_shadowing_never_runs_changed_callback(monkeypatch):
    monkeypatch.setattr(learning, "super", _forbidden, raising=False)
    _refuses()


def test_module_builtin_domain_replacement_is_refused(monkeypatch):
    monkeypatch.setattr(admission, "__builtins__", dict(vars(__import__("builtins"))))
    _refuses()


@pytest.mark.parametrize("name", [
    "lunar_evolution.rsi_python_brs_admission", "lunar_evolution.rsi_learning",
    "dataclasses", "re", "types",
])
def test_original_module_registry_bindings_are_held(name, monkeypatch):
    monkeypatch.setitem(sys.modules, name, object())
    _refuses()


class _Hostile:
    calls = 0

    def __eq__(self, _other):
        type(self).calls += 1
        raise AssertionError("foreign equality executed")

    def __hash__(self):
        return 83427


@pytest.mark.parametrize("namespace", [vars(guard), vars(admission),
                                        admission.BRSAdmissionAck.__annotations__])
def test_non_string_mapping_keys_fail_before_lookup_or_equality(namespace):
    key = _Hostile()
    namespace[key] = None
    _Hostile.calls = 0
    try:
        _refuses()
        assert _Hostile.calls == 0
    finally:
        del namespace[key]


@pytest.mark.parametrize("fields", [None, [], FIELDS[:3], (*FIELDS, "extra"),
                                    (_Hostile(), *FIELDS[1:])])
def test_field_shape_is_exact_and_checked_before_foreign_operations(fields):
    _Hostile.calls = 0
    with pytest.raises(RSILearningError, match="ack_fields_invalid"):
        guard.build_rejection_ready_ack(fields)
    assert _Hostile.calls == 0


def test_tuple_subclasses_do_not_supply_input_fields():
    class ForeignTuple(tuple):
        def __len__(self):
            raise AssertionError("foreign length executed")

    with pytest.raises(RSILearningError, match="ack_fields_invalid"):
        guard.build_rejection_ready_ack(ForeignTuple(FIELDS))


@pytest.mark.parametrize("position,value", [(0, "bad id"), (1, ""),
                                            (2, "0" * 64), (3, "bad digest")])
def test_canonical_constructor_keeps_identity_and_digest_validation(position, value):
    fields = list(FIELDS)
    fields[position] = value
    with pytest.raises(admission.RSIPythonBRSAdmissionError):
        guard.build_rejection_ready_ack(tuple(fields))


@pytest.mark.parametrize("position", range(4))
def test_mutated_ack_slot_is_rejected_against_retained_strings(position):
    ack = guard.build_rejection_ready_ack(FIELDS)
    name = ("run_id", "episode_id", "request_sha256", "record_sha256")[position]
    object.__setattr__(ack, name, _Hostile())
    _Hostile.calls = 0
    with pytest.raises(RSILearningError, match="ack_mismatch"):
        guard.assert_rejection_ready_ack(ack, FIELDS)
    assert _Hostile.calls == 0


def test_uninitialized_ack_is_a_fixed_refusal():
    ack = object.__new__(admission.BRSAdmissionAck)
    with pytest.raises(RSILearningError, match="ack_mismatch"):
        guard.assert_rejection_ready_ack(ack, FIELDS)


def test_matching_but_forged_invalid_ack_does_not_pass_slot_comparison():
    ack = guard.build_rejection_ready_ack(FIELDS)
    object.__setattr__(ack, "run_id", "bad id")
    with pytest.raises(admission.RSIPythonBRSAdmissionError, match="identity_invalid"):
        guard.assert_rejection_ready_ack(ack, ("bad id", *FIELDS[1:]))


@pytest.mark.parametrize("entry", [guard.build_rejection_ready_ack,
                                   guard.assert_rejection_ready_ack])
def test_held_guard_entry_code_is_checked_before_it_can_execute(entry, monkeypatch):
    original = guard.assert_rejection_ready_ack_graph
    # Preserve the original closure arity so this mutates the held function in place.
    replacement = original.__code__.replace(co_consts=(*original.__code__.co_consts, "foreign"))
    ack = guard.build_rejection_ready_ack(FIELDS)
    monkeypatch.setattr(original, "__code__", replacement)
    args = (FIELDS,) if entry is guard.build_rejection_ready_ack else (ack, FIELDS)
    with pytest.raises(RSILearningError, match="ack_graph_drift"):
        entry(*args)


@pytest.mark.parametrize("entry", [guard.build_rejection_ready_ack,
                                   guard.assert_rejection_ready_ack])
def test_held_guard_entry_closure_cells_are_checked_independently(entry):
    original = guard.assert_rejection_ready_ack_graph
    ack = guard.build_rejection_ready_ack(FIELDS)
    index = original.__code__.co_freevars.index("constructor") if (
        "constructor" in original.__code__.co_freevars) else original.__code__.co_freevars.index("edges")
    cell = original.__closure__[index]
    held = cell.cell_contents
    try:
        cell.cell_contents = object()
        args = (FIELDS,) if entry is guard.build_rejection_ready_ack else (ack, FIELDS)
        with pytest.raises(RSILearningError, match="ack_graph_drift"):
            entry(*args)
    finally:
        cell.cell_contents = held


def test_changed_own_alias_is_refused_before_construction(monkeypatch):
    monkeypatch.setattr(guard, "assert_rejection_ready_ack_graph", _forbidden)
    with pytest.raises(RSILearningError, match="ack_graph_drift"):
        guard.build_rejection_ready_ack(FIELDS)


@pytest.mark.parametrize("entry", [guard.build_rejection_ready_ack,
                                   guard.assert_rejection_ready_ack])
@pytest.mark.parametrize("name,value", [
    ("__defaults__", (object(),)), ("__kwdefaults__", {"foreign": object()}),
    ("__annotations__", {"foreign": object()}), ("__name__", "foreign"),
    ("__qualname__", "foreign"), ("__module__", "foreign"), ("__doc__", "foreign"),
])
def test_guard_entry_metadata_is_checked_before_execution(entry, name, value, monkeypatch):
    ack = guard.build_rejection_ready_ack(FIELDS)
    monkeypatch.setattr(guard.assert_rejection_ready_ack_graph, name, value)
    args = (FIELDS,) if entry is guard.build_rejection_ready_ack else (ack, FIELDS)
    with pytest.raises(RSILearningError, match="ack_graph_drift"):
        entry(*args)


@pytest.mark.parametrize("position", range(4))
def test_string_subclasses_cannot_run_comparisons_before_rejection(position):
    class ForeignString(str):
        def __eq__(self, _other):
            raise AssertionError("foreign string equality executed")

    fields = list(FIELDS)
    fields[position] = ForeignString(fields[position])
    with pytest.raises(RSILearningError, match="ack_fields_invalid"):
        guard.build_rejection_ready_ack(tuple(fields))


def test_foreign_ack_type_is_refused_before_attribute_lookup():
    class ForeignAck:
        def __getattribute__(self, _name):
            raise AssertionError("foreign ACK attribute lookup executed")

    with pytest.raises(RSILearningError, match="ack_fields_invalid"):
        guard.assert_rejection_ready_ack(ForeignAck(), FIELDS)
