"""The allocation-light matcher preserves the original finite freeze gate."""
from __future__ import annotations

import dataclasses
import math
from types import MappingProxyType

import pytest

from lunar_evolution import rsi_brs_reserved_policy as policy
from lunar_evolution.rsi_learning import RSILearningError


def _captures(function):
    return dict(zip(function.__code__.co_freevars,
                    (cell.cell_contents for cell in function.__closure__), strict=True))


@pytest.fixture(scope="module")
def observers():
    project = policy._build_reserved_brs_policy()
    captures = _captures(project)
    helpers = {pin[0].__name__: pin[0] for pin in captures["helper_pins"]}
    return helpers["freeze"], helpers["matches_frozen"], project


def _accepted(function, *args, **kwargs):
    try:
        return bool(function(*args, **kwargs))
    except RSILearningError as error:
        assert str(error) == "rsi_brs_reserved_policy_drift"
        return False


def _same_gate(observers, current, held, *, expected):
    freeze, matches, _project = observers

    def original_gate(value, saved):
        return freeze(value) == saved

    assert _accepted(original_gate, current, held) is expected
    assert _accepted(matches, current, held) is expected


@pytest.mark.parametrize("value", [
    None, "value", b"value", 7, True, False, 1.25, -0.0,
    [], (), {}, set(), frozenset(), MappingProxyType({}),
    [None, "text", b"bytes", 3, False, 2.5],
    {"name": "value", "nested": [{"enabled": True}, (1, 2)]},
    {1: "int", "2": "str"}, {object(): object()},
    MappingProxyType({"nested": [1, 2]}), {1, "two"},
    dataclasses.field(default=1, metadata={"kind": "inert"}),
    object(),
])
def test_matches_every_supported_frozen_shape(observers, value):
    freeze, _matches, _project = observers
    _same_gate(observers, value, freeze(value), expected=True)


@pytest.mark.parametrize(("original", "replacement"), [
    (True, 1), (False, 0), (1, True), (0, False), (1, 1.0),
    ("value", b"value"), (b"value", "value"), (None, object()),
])
def test_scalar_tags_remain_exact(observers, original, replacement):
    freeze, _matches, _project = observers
    _same_gate(observers, replacement, freeze(original), expected=False)


@pytest.mark.parametrize("replacement", [math.inf, -math.inf, math.nan])
def test_nonfinite_floats_are_always_rejected(observers, replacement):
    freeze, _matches, _project = observers
    _same_gate(observers, replacement, freeze(1.25), expected=False)


@pytest.mark.parametrize("value", [[], {}, (), set(), frozenset(), MappingProxyType({})])
def test_equal_container_contents_do_not_replace_held_identity(observers, value):
    freeze, _matches, _project = observers
    held = freeze(value)
    if type(value) is MappingProxyType:
        replacement = MappingProxyType({})
    elif type(value) is tuple:
        # Empty tuples are interpreter singletons: exercise nonempty identities.
        value = tuple(range(1, 3))
        held = freeze(value)
        replacement = tuple(range(1, 3))
    elif type(value) is frozenset:
        value = frozenset([1, 2])
        held = freeze(value)
        replacement = frozenset([1, 2])
    else:
        replacement = type(value)()
    assert replacement is not value
    _same_gate(observers, replacement, held, expected=False)


def test_nested_values_are_read_on_every_call(observers):
    freeze, _matches, _project = observers
    child = {"enabled": True}
    value = {"nested": [child]}
    held = freeze(value)
    _same_gate(observers, value, held, expected=True)
    child["enabled"] = False
    _same_gate(observers, value, held, expected=False)
    child["enabled"] = True
    _same_gate(observers, value, held, expected=True)
    value["nested"][0] = {"enabled": True}
    _same_gate(observers, value, held, expected=False)


def test_sequence_order_is_kept_and_mapping_order_is_not_added(observers):
    freeze, _matches, _project = observers
    sequence = [1, 2]
    held = freeze(sequence)
    sequence.reverse()
    _same_gate(observers, sequence, held, expected=False)
    mapping = {"first": 1, "second": 2}
    held = freeze(mapping)
    first = mapping.pop("first")
    mapping["first"] = first
    _same_gate(observers, mapping, held, expected=True)


def test_missing_sentinel_remains_a_valid_opaque_value(observers):
    freeze, matches, _project = observers
    sentinel = _captures(matches)["missing"]
    value = {"sentinel": sentinel}
    _same_gate(observers, value, freeze(value), expected=True)


def test_foreign_mapping_keys_and_values_never_invoke_hooks(observers):
    freeze, _matches, _project = observers
    calls = []

    class HostileMeta(type):
        def __eq__(self, other):
            calls.append("meta_eq")
            raise AssertionError("foreign type equality executed")

    class Foreign(metaclass=HostileMeta):
        def __hash__(self):
            calls.append("hash")
            return 7

        def __eq__(self, other):
            calls.append("eq")
            raise AssertionError("foreign equality executed")

    key = Foreign()
    value = {key: Foreign(), "ordinary": "value"}
    calls.clear()
    held = freeze(value)
    _same_gate(observers, value, held, expected=True)
    value["ordinary"] = "changed"
    _same_gate(observers, value, held, expected=False)
    assert calls == []


def test_str_subclass_keys_keep_original_opaque_identity(observers):
    freeze, _matches, _project = observers

    class Text(str):
        pass

    key = Text("ordinary")
    value = {key: "value"}
    held = freeze(value)
    _same_gate(observers, value, held, expected=True)
    value.clear()
    value[Text("ordinary")] = "value"
    _same_gate(observers, value, held, expected=False)


def test_mappingproxy_and_set_mutations_keep_the_fallback_gate(observers):
    freeze, _matches, _project = observers
    backing = {"enabled": True}
    proxy = MappingProxyType(backing)
    held = freeze(proxy)
    backing["enabled"] = False
    _same_gate(observers, proxy, held, expected=False)
    values = {1, 2}
    held = freeze(values)
    values.remove(2)
    values.add(3)
    _same_gate(observers, values, held, expected=False)


@pytest.mark.parametrize("name,replacement", [
    ("name", "changed"), ("type", int), ("default", 2),
    ("default_factory", list), ("init", False), ("repr", False),
    ("hash", True), ("compare", False), ("metadata", MappingProxyType({"changed": True})),
    ("kw_only", True), ("_field_type", object()),
])
def test_every_original_dataclass_field_attribute_is_observed(observers, name, replacement):
    freeze, _matches, _project = observers
    value = dataclasses.field(default=1)
    held = freeze(value)
    setattr(value, name, replacement)
    _same_gate(observers, value, held, expected=False)


def test_cycles_introduced_after_capture_cannot_match(observers):
    freeze, _matches, _project = observers
    value = [[]]
    held = freeze(value)
    value[0].append(value)
    _same_gate(observers, value, held, expected=False)


def test_depth_and_node_budget_match_for_accepted_shapes(observers):
    freeze, matches, _project = observers
    value = {"nested": [(None, {"key": [1, True, "value"]})]}
    held = freeze(value)
    first, second = [100_000], [100_000]
    assert freeze(value, remaining=first) == held
    assert matches(value, held, remaining=second)
    assert first == second
    for budget in (0, 1, 2, 3):
        with pytest.raises(RSILearningError, match="rsi_brs_reserved_policy_drift"):
            freeze(value, remaining=[budget])
        with pytest.raises(RSILearningError, match="rsi_brs_reserved_policy_drift"):
            matches(value, held, remaining=[budget])
    deep = None
    for _index in range(48):
        deep = [deep]
    held = freeze(deep)
    _same_gate(observers, deep, held, expected=True)
    with pytest.raises(RSILearningError, match="rsi_brs_reserved_policy_drift"):
        freeze([deep])
    assert not _accepted(matches, [deep], held)


def test_container_length_limit_is_unchanged(observers):
    freeze, matches, _project = observers
    value = [None] * 32768
    held = freeze(value)
    _same_gate(observers, value, held, expected=True)
    value.append(None)
    with pytest.raises(RSILearningError, match="rsi_brs_reserved_policy_drift"):
        freeze(value)
    with pytest.raises(RSILearningError, match="rsi_brs_reserved_policy_drift"):
        matches(value, held)


def test_matcher_code_is_pinned_before_it_can_execute(observers, monkeypatch):
    _freeze, matches, project = observers
    monkeypatch.setattr(matches, "__code__", matches.__code__.replace(co_name="foreign"))
    with pytest.raises(RSILearningError, match="rsi_brs_reserved_policy_drift"):
        project()


def test_matcher_capture_identity_is_pinned_before_it_can_execute(observers):
    _freeze, matches, project = observers
    cells = dict(zip(matches.__code__.co_freevars, matches.__closure__, strict=True))
    cell = cells["object_get"]
    original = cell.cell_contents
    try:
        cell.cell_contents = object()
        with pytest.raises(RSILearningError, match="rsi_brs_reserved_policy_drift"):
            project()
    finally:
        cell.cell_contents = original


def test_colliding_foreign_key_inserted_between_observations_never_executes_eq(observers):
    freeze, matches, _project = observers
    calls = []

    class EvilKey:
        def __hash__(self):
            return hash("ordinary")

        def __eq__(self, other):
            calls.append("eq")
            raise AssertionError("colliding foreign key equality executed")

    value = {"ordinary": 1}
    held = freeze(value)
    foreign = EvilKey()
    cells = dict(zip(matches.__code__.co_freevars, matches.__closure__, strict=True))
    cell = cells["some"]
    original = cell.cell_contents

    def mutate_after_shape_check(values):
        result = original(values)
        # Deterministically reproduce a concurrent insertion after eligibility
        # was observed. The foreign key has the exact str lookup's hash.
        value.clear()
        value[foreign] = 1
        return result

    try:
        cell.cell_contents = mutate_after_shape_check
        assert not _accepted(matches, value, held)
    finally:
        cell.cell_contents = original
    assert freeze(value) != held
    assert calls == []
