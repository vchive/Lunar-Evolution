"""Reserved-policy freezing preserves exact types and bounded observation."""

from __future__ import annotations

import math
import sys
from types import FunctionType, MappingProxyType

import pytest

from lunar_evolution import rsi_brs_reserved_policy as policy
from lunar_evolution.rsi_learning import RSILearningError


@pytest.fixture
def freeze():
    policy.reserved_brs_policy_projection()
    captures = dict(zip(policy._PROJECT.__code__.co_freevars, policy._PROJECT.__closure__, strict=True))
    original = captures["freeze"].cell_contents
    assert type(original) is FunctionType
    return original


@pytest.mark.parametrize("boolean,integer", [(False, 0), (True, 1)])
def test_equal_bool_and_int_values_keep_different_policy_type_labels(freeze, boolean, integer):
    assert boolean == integer
    assert freeze(boolean) == ("bool", boolean)
    assert freeze(integer) == ("int", integer)
    assert freeze(boolean) != freeze(integer)


def test_none_and_equal_text_bytes_keep_distinct_scalar_identities(freeze):
    assert freeze(None) == ("none",)
    assert freeze("value") == ("str", "value")
    assert freeze(b"value") == ("bytes", b"value")
    assert freeze("value") != freeze(b"value")


@pytest.mark.parametrize("value", [0.0, -0.0, 0.375, sys.float_info.max])
def test_finite_float_payload_and_signed_zero_are_preserved(freeze, value):
    result = freeze(value)
    assert result == ("float", value)
    assert type(result[1]) is float
    assert math.copysign(1, result[1]) == math.copysign(1, value)
    assert freeze(1.0) != freeze(1)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_float_refuses_even_when_nested(freeze, value):
    with pytest.raises(RSILearningError, match="^rsi_brs_reserved_policy_drift$"):
        freeze({"nested": [value]})


@pytest.mark.parametrize("base", [object, str, bytes, int, float, list, tuple, dict, set, frozenset])
@pytest.mark.parametrize("unhashable", [False, True])
def test_foreign_types_are_opaque_without_metaclass_or_value_callbacks(freeze, base, unhashable):
    calls = []

    class Meta(type):
        def __hash__(cls):
            calls.append("class_hash")
            raise AssertionError("foreign class hash executed")

        def __eq__(cls, other):
            calls.append("class_equality")
            raise AssertionError("foreign class equality executed")

        def __getattribute__(cls, name):
            calls.append("class_attribute")
            raise AssertionError("foreign class attribute executed")

    if unhashable:
        Meta.__hash__ = None

    class Foreign(base, metaclass=Meta):
        def __hash__(self):
            calls.append("value_hash")
            raise AssertionError("foreign value hash executed")

        def __eq__(self, other):
            calls.append("value_equality")
            raise AssertionError("foreign value equality executed")

        def __getattribute__(self, name):
            calls.append("value_attribute")
            raise AssertionError("foreign value attribute executed")

        def __len__(self):
            calls.append("value_length")
            raise AssertionError("foreign value length executed")

        def __iter__(self):
            calls.append("value_iteration")
            raise AssertionError("foreign value iteration executed")

    value = Foreign()
    expected = ("opaque", id(type(value)), id(value))
    assert freeze(value) == expected
    assert freeze([value, value])[3] == (expected, expected)
    assert calls == []


@pytest.mark.parametrize("depth,accepted", [(48, True), (49, False)])
def test_nested_depth_boundary_is_enforced_for_real_container_traversal(freeze, depth, accepted):
    value = 0
    for _ in range(depth):
        value = [value]
    if not accepted:
        with pytest.raises(RSILearningError, match="^rsi_brs_reserved_policy_drift$"):
            freeze(value)
        return
    result = freeze(value)
    for _ in range(depth):
        assert result[0] == "sequence"
        result = result[3][0]
    assert result == ("int", 0)


@pytest.mark.parametrize("last_size,accepted", [(899, True), (900, False)])
def test_shared_subtrees_still_spend_the_total_node_budget(freeze, last_size, accepted):
    # Repeated references are observed each time. The root, 100 branches and
    # their leaves total 100000 or 100001 nodes without a giant input container.
    branch = tuple(range(1000))
    value = [branch] * 99 + [tuple(range(last_size))]
    if accepted:
        result = freeze(value)
        assert len(result[3]) == 100
        assert len(result[3][-1][3]) == last_size
    else:
        with pytest.raises(RSILearningError, match="^rsi_brs_reserved_policy_drift$"):
            freeze(value)


def test_container_cycle_refuses_with_fixed_policy_error(freeze):
    value = []
    value.append(value)
    with pytest.raises(RSILearningError, match="^rsi_brs_reserved_policy_drift$"):
        freeze(value)


@pytest.mark.parametrize("size,accepted", [(32768, True), (32769, False)])
def test_container_width_limit_is_independent_of_the_total_node_budget(freeze, size, accepted):
    value = [None] * size
    if accepted:
        assert len(freeze(value)[3]) == size
    else:
        with pytest.raises(RSILearningError, match="^rsi_brs_reserved_policy_drift$"):
            freeze(value)


@pytest.mark.parametrize("read_only", [False, True])
def test_mapping_order_is_irrelevant_but_live_nested_changes_are_observed(freeze, read_only):
    source = {"first": [1], "second": [2]}
    value = MappingProxyType(source) if read_only else source
    baseline = freeze(value)
    first = source.pop("first")
    source["first"] = first
    assert freeze(value) == baseline
    first.append(3)
    assert freeze(value) != baseline
    first.pop()
    assert freeze(value) == baseline
