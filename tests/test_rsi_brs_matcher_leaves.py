"""Scalar inlining keeps the held-policy matcher's fresh bounded traversal."""

from __future__ import annotations

import sys

import pytest

from lunar_evolution import rsi_brs_reserved_policy as policy
from lunar_evolution.rsi_learning import RSILearningError


@pytest.fixture(scope="module")
def observation_helpers():
    # Build a private graph without initializing or replacing the process-wide
    # original policy. These tests only invoke its real freeze/matcher helpers.
    project = policy._build_reserved_brs_policy()
    captures = dict(zip(project.__code__.co_freevars, project.__closure__, strict=True))
    return captures["freeze"].cell_contents, captures["matches_frozen"].cell_contents


def _observed_matcher_calls(matcher, value, held, remaining):
    calls = 0
    code = matcher.__code__
    previous = sys.getprofile()

    def observe(frame, event, _argument):
        nonlocal calls
        if event == "call" and frame.f_code is code:
            calls += 1

    try:
        sys.setprofile(observe)
        result = matcher(value, held, remaining=remaining)
    finally:
        sys.setprofile(previous)
    return result, calls


@pytest.mark.parametrize("container", [list, tuple, dict])
def test_flat_scalar_leaves_use_one_real_matcher_call_and_spend_each_node(observation_helpers, container):
    freeze, matcher = observation_helpers
    leaves = [None, "text", b"bytes", 17, False, -0.0, object()]
    value = dict(zip(map(str, range(len(leaves))), leaves, strict=True)) if container is dict else container(leaves)
    remaining = [1 + len(leaves) * (2 if container is dict else 1)]
    assert _observed_matcher_calls(matcher, value, freeze(value), remaining) == (True, 1)
    assert remaining == [0]


def test_nested_containers_still_recurse_and_each_shared_observation_is_charged(observation_helpers):
    freeze, matcher = observation_helpers
    shared = [1, 2]
    value = {"first": shared, "second": shared, "nested": (None, {"value": False})}
    # Root + three mapping keys + two separately observed three-node lists +
    # the tuple, None, inner mapping, its key and its bool leaf.
    remaining = [15]
    assert _observed_matcher_calls(matcher, value, freeze(value), remaining) == (True, 5)
    assert remaining == [0]


@pytest.mark.parametrize("value", [[1, 2], (1, 2), {"leaf": 1}])
def test_scalar_leaf_cannot_skip_the_last_node_charge(observation_helpers, value):
    freeze, matcher = observation_helpers
    held = freeze(value)
    remaining = [3]
    assert matcher(value, held, remaining=remaining)
    assert remaining == [0]
    with pytest.raises(RSILearningError, match="^rsi_brs_reserved_policy_drift$"):
        matcher(value, held, remaining=[2])


@pytest.mark.parametrize("before,after", [
    (None, False), (1, True), (True, 1), ("text", b"text"), (b"text", "text"),
    (1.0, 1), (1, 2), ("text", "other"), (b"text", b"other"), (False, True),
    (0.5, 0.75), (object(), object()),
])
@pytest.mark.parametrize("mapping", [False, True])
def test_every_observation_reads_current_scalar_type_value_and_identity(observation_helpers, before, after, mapping):
    freeze, matcher = observation_helpers
    value = {"leaf": before} if mapping else [before]
    held = freeze(value)
    assert matcher(value, held)
    value["leaf" if mapping else 0] = after
    assert not matcher(value, held)


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("mapping", [False, True])
def test_nonfinite_leaf_refuses_before_its_payload_can_match(observation_helpers, nonfinite, mapping):
    freeze, matcher = observation_helpers
    value = {"leaf": 0.5} if mapping else [0.5]
    held = freeze(value)
    value["leaf" if mapping else 0] = nonfinite
    with pytest.raises(RSILearningError, match="^rsi_brs_reserved_policy_drift$"):
        matcher(value, held)


@pytest.mark.parametrize("mapping_leaf", [False, True])
def test_scalar_depth_48_passes_and_49_refuses(observation_helpers, mapping_leaf):
    freeze, matcher = observation_helpers
    value = {"leaf": 0} if mapping_leaf else [0]
    for _ in range(47):
        value = [value]
    held = freeze(value)
    assert matcher(value, held)
    with pytest.raises(RSILearningError, match="^rsi_brs_reserved_policy_drift$"):
        matcher(value, held, depth=1)


def test_shared_scalar_leaves_spend_the_full_100000_node_budget(observation_helpers):
    freeze, matcher = observation_helpers
    branch = tuple(range(1000))
    value = [branch] * 99 + [tuple(range(899))]
    held = freeze(value)
    remaining = [100_000]
    assert matcher(value, held, remaining=remaining)
    assert remaining == [0]
    with pytest.raises(RSILearningError, match="^rsi_brs_reserved_policy_drift$"):
        matcher(value, held, remaining=[99_999])


def test_container_width_and_fresh_container_identity_remain_required(observation_helpers):
    freeze, matcher = observation_helpers
    value = [None] * 32768
    held = freeze(value)
    assert matcher(value, held)
    assert not matcher(value.copy(), held)
    value.append(None)
    with pytest.raises(RSILearningError, match="^rsi_brs_reserved_policy_drift$"):
        matcher(value, held)


@pytest.mark.parametrize("base", [object, str, int, list])
def test_foreign_scalar_types_remain_opaque_without_callbacks(observation_helpers, base):
    freeze, matcher = observation_helpers
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

    value = [Foreign()]
    held = freeze(value)
    assert matcher(value, held)
    value[0] = Foreign()
    assert not matcher(value, held)
    assert calls == []


def test_replaced_foreign_mapping_key_is_rejected_without_key_callbacks(observation_helpers):
    freeze, matcher = observation_helpers
    calls = []

    class Foreign(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            calls.append("key_equality")
            raise AssertionError("foreign key equality executed")

    value = {"leaf": 1}
    held = freeze(value)
    value.clear()
    value[Foreign("leaf")] = 1
    assert not matcher(value, held)
    assert calls == []
