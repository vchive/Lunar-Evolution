"""Ready-capsule leaf optimization preserves the original ordered shape walk."""

from __future__ import annotations

import math
import random

import pytest

from lunar_evolution import rsi_producer_staging_capsule as capsule
from lunar_evolution.rsi_learning import RSILearningError


def _original_shape(value, *, depth=0, remaining=None):
    """Independent copy of the recursive validator before scalar inlining."""
    if remaining is None:
        remaining = [100_000]
    remaining[0] -= 1
    if remaining[0] < 0 or depth > 48:
        raise RSILearningError("rsi_producer_ready_capsule_shape_invalid")
    kind = type(value)
    if kind is dict:
        if len(value) > 10_000 or any(type(key) is not str for key in value):
            raise RSILearningError("rsi_producer_ready_capsule_shape_invalid")
        for key, item in value.items():
            _original_shape(key, depth=depth + 1, remaining=remaining)
            _original_shape(item, depth=depth + 1, remaining=remaining)
    elif kind is list:
        if len(value) > 10_000:
            raise RSILearningError("rsi_producer_ready_capsule_shape_invalid")
        for item in value:
            _original_shape(item, depth=depth + 1, remaining=remaining)
    elif kind is str:
        if len(value) > 128 * 1024:
            raise RSILearningError("rsi_producer_ready_capsule_shape_invalid")
    elif kind is int:
        if value.bit_length() > 4096:
            raise RSILearningError("rsi_producer_ready_capsule_shape_invalid")
    elif kind is float:
        if not math.isfinite(value):
            raise RSILearningError("rsi_producer_ready_capsule_shape_invalid")
    elif value is not None and kind is not bool:
        raise RSILearningError("rsi_producer_ready_capsule_shape_invalid")


def _outcome(validator, value, *, depth=0, nodes=100_000):
    remaining = [nodes]
    try:
        validator(value, depth=depth, remaining=remaining)
    except (RSILearningError, RuntimeError) as exc:
        return type(exc), str(exc), remaining[0]
    return None, None, remaining[0]


@pytest.mark.parametrize("value,accepted", [
    (None, True), (False, True), (True, True), ("", True), (0, True), (-1, True),
    (0.0, True), (-0.0, True), (1.7976931348623157e308, True),
    ("字" * (128 * 1024), True), ("x" * (128 * 1024 + 1), False),
    (1 << 4095, True), (-(1 << 4095), True), (1 << 4096, False),
    (-(1 << 4096), False), (float("inf"), False), (float("-inf"), False),
    (float("nan"), False), (b"bytes", False), ((), False), (set(), False),
], ids=[
    "none", "false", "true", "empty-string", "zero-int", "negative-int",
    "zero-float", "negative-zero-float", "finite-limit", "string-limit",
    "string-too-long", "integer-limit", "negative-integer-limit", "integer-too-large",
    "negative-integer-too-large", "positive-infinity", "negative-infinity", "nan",
    "bytes", "tuple", "set",
])
def test_scalar_boundaries_match_original_at_root_and_both_container_kinds(value, accepted):
    for subject in (value, [value], {"key": value}):
        expected = _outcome(_original_shape, subject)
        assert (expected[0] is None) is accepted
        assert _outcome(capsule._shape, subject) == expected


@pytest.mark.parametrize("leaf", [None, "text", 1, 1.5, False, [], {}])
@pytest.mark.parametrize("depth", [47, 48, 49])
def test_depth_includes_scalar_and_empty_container_occurrences(leaf, depth):
    for subject in (leaf, [leaf], {"key": leaf}):
        assert _outcome(capsule._shape, subject, depth=depth) == _outcome(
            _original_shape, subject, depth=depth,
        )


@pytest.mark.parametrize("kind", ["list", "dict"])
@pytest.mark.parametrize("length", [10_000, 10_001])
def test_container_length_bound_is_unchanged(kind, length):
    value = [None] * length if kind == "list" else {str(index): None for index in range(length)}
    assert _outcome(capsule._shape, value) == _outcome(_original_shape, value)


@pytest.mark.parametrize("extra", [9, 10])
def test_shared_occurrences_count_toward_exact_node_boundary(extra):
    shared = [None] * 9998
    value = [shared] * 10 + [None] * extra
    expected = _outcome(_original_shape, value)
    assert (expected[0] is None) is (extra == 9)
    assert expected[2] == (0 if extra == 9 else -1)
    assert _outcome(capsule._shape, value) == expected


@pytest.mark.parametrize("nodes", [0, 1, 2, 3, 4])
def test_dictionary_keys_and_values_each_consume_one_node_in_order(nodes):
    value = {"key": 1.5}
    assert _outcome(capsule._shape, value, nodes=nodes) == _outcome(
        _original_shape, value, nodes=nodes,
    )


@pytest.mark.parametrize("kind", ["list", "dict"])
def test_cycles_keep_depth_refusal_and_counter_consumption(kind):
    value = [] if kind == "list" else {}
    if kind == "list":
        value.append(value)
    else:
        value["cycle"] = value
    assert _outcome(capsule._shape, value) == _outcome(_original_shape, value)


@pytest.mark.parametrize("base", [str, int, float, list, dict])
def test_subclasses_are_rejected_without_foreign_hooks(base):
    events = []

    class Meta(type):
        def __hash__(cls):
            events.append("metaclass hash")
            raise AssertionError("foreign metaclass hash")

        def __eq__(cls, other):
            events.append("metaclass equality")
            raise AssertionError("foreign metaclass equality")

    class Foreign(base, metaclass=Meta):
        def __len__(self):
            events.append("length")
            raise AssertionError("foreign length")

        def __iter__(self):
            events.append("iteration")
            raise AssertionError("foreign iteration")

        def items(self):
            events.append("items")
            raise AssertionError("foreign items")

        def bit_length(self):
            events.append("bit length")
            raise AssertionError("foreign bit length")

        def __float__(self):
            events.append("float")
            raise AssertionError("foreign float")

    value = Foreign()
    for subject in (value, [value], {"key": value}):
        expected = _outcome(_original_shape, subject)
        assert expected[0] is RSILearningError
        assert _outcome(capsule._shape, subject) == expected
    assert events == []


@pytest.mark.parametrize("value", [
    {"first": 1.0, 2: 2.0},
    {"x" * (128 * 1024 + 1): 1.0, "later": 2.0},
    ["x" * (128 * 1024 + 1), 1.0],
    [1 << 4096, 1.0],
    [float("nan"), 2.0],
])
def test_first_refusal_preserves_live_finiteness_order(monkeypatch, value):
    original = math.isfinite
    observed = []

    def observe(item):
        observed.append(item.hex())
        return original(item)

    monkeypatch.setattr(math, "isfinite", observe)
    expected = _outcome(_original_shape, value)
    prior = list(observed)
    observed.clear()
    assert _outcome(capsule._shape, value) == expected
    assert observed == prior


@pytest.mark.parametrize("validator", [_original_shape, capsule._shape])
def test_every_float_observes_the_current_finiteness_backend(monkeypatch, validator):
    events = []

    def replacement(value):
        events.append(("replacement", value))
        return False

    def initial(value):
        events.append(("initial", value))
        monkeypatch.setattr(math, "isfinite", replacement)
        return True

    monkeypatch.setattr(math, "isfinite", initial)
    result = _outcome(validator, [1.0, 2.0, 3.0])
    assert result == (RSILearningError, "rsi_producer_ready_capsule_shape_invalid", 99_997)
    assert events == [("initial", 1.0), ("replacement", 2.0)]


@pytest.mark.parametrize("validator", [_original_shape, capsule._shape])
def test_live_finiteness_exception_keeps_original_counter_and_first_failure(monkeypatch, validator):
    events = []

    def interrupted(value):
        events.append(value)
        raise RuntimeError("inert finiteness interruption")

    monkeypatch.setattr(math, "isfinite", interrupted)
    assert _outcome(validator, [1.0, b"later invalid"]) == (
        RuntimeError, "inert finiteness interruption", 99_998,
    )
    assert events == [1.0]


@pytest.mark.parametrize("validator", [_original_shape, capsule._shape])
def test_dictionary_size_change_during_live_hook_retains_iterator_refusal(monkeypatch, validator):
    value = {"first": 1.0, "second": 2.0}
    events = []

    def grow(item):
        events.append(item)
        value["new"] = None
        return True

    monkeypatch.setattr(math, "isfinite", grow)
    assert _outcome(validator, value) == (
        RuntimeError, "dictionary changed size during iteration", 99_997,
    )
    assert events == [1.0]


@pytest.mark.parametrize("kind", ["list", "dict"])
@pytest.mark.parametrize("validator", [_original_shape, capsule._shape])
def test_later_values_are_not_prefetched_before_finiteness_hook(monkeypatch, kind, validator):
    subject = [1.0, 2.0] if kind == "list" else {"first": 1.0, "second": 2.0}
    events = []

    def mutate(value):
        events.append(value)
        subject[1 if kind == "list" else "second"] = b"invalid later value"
        return True

    monkeypatch.setattr(math, "isfinite", mutate)
    result = _outcome(validator, subject)
    assert result[0] is RSILearningError
    assert events == [1.0]


def test_repeated_float_occurrences_are_revalidated_across_calls(monkeypatch):
    calls = []

    def observe(value):
        calls.append(value)
        return True

    monkeypatch.setattr(math, "isfinite", observe)
    shared = [1.0, 1.0]
    subject = {"first": shared, "second": shared}
    capsule._shape(subject)
    capsule._shape(subject)
    assert calls == [1.0] * 8


def test_seeded_nested_values_keep_original_results_and_node_counts():
    rng = random.Random(1911026)
    leaves = [None, True, False, "", "text", "字", 0, -1, 1.5, float("inf"), (), b"invalid"]

    def generate(depth):
        if depth == 0 or rng.randrange(3) == 0:
            return rng.choice(leaves)
        if rng.randrange(2):
            return [generate(depth - 1) for _ in range(rng.randrange(5))]
        return {str(index): generate(depth - 1) for index in range(rng.randrange(5))}

    for _ in range(400):
        subject = generate(6)
        nodes = rng.choice((0, 1, 3, 20, 100_000))
        depth = rng.choice((0, 43, 48, 49))
        assert _outcome(capsule._shape, subject, nodes=nodes, depth=depth) == _outcome(
            _original_shape, subject, nodes=nodes, depth=depth,
        )
