"""Compare scheduler shape walks with the fixed pre-optimization AST oracle."""

from __future__ import annotations

import ast
import hashlib
import math
import random
from dataclasses import fields
from types import MappingProxyType

import pytest

from lunar_evolution import rsi_python_scheduler_inputs as scheduler

_ERROR = "rsi_python_scheduler_inputs_shape_invalid"
# AST source segment from git show 64ec3f54:src/lunar_evolution/rsi_python_scheduler_inputs.py.
# The source module SHA256 is 031580417c6f53109ab82701b0b1a7d0f4bbe4fe022a9b2c3578b60c4c7e4935.
# Keep the recursive oracle independent of the current product implementation and Git history.
_ORIGINAL_SHAPE_SOURCE = '''def _shape(value: object, *, depth: int = 0, remaining: list[int] | None = None) -> None:
    """Bound exact DTOs and detached collections before invoking older serializers."""
    if remaining is None:
        remaining = [100_000]
    remaining[0] -= 1
    if depth > 48 or remaining[0] < 0:
        _fail("shape_invalid")
    kind = type(value)
    if value is None or kind is bool:
        return
    if kind is str:
        if len(value) > 128 * 1024:
            _fail("shape_invalid")
        return
    if kind is int:
        if value.bit_length() > 4096:
            _fail("shape_invalid")
        return
    if kind is float:
        if not math.isfinite(value):
            _fail("shape_invalid")
        return
    if kind is dict:
        if len(value) > 10_000 or any(type(key) is not str for key in value):
            _fail("shape_invalid")
        # Keys are untrusted input too.  Visit them before serializers so their size contributes
        # to the same bounded shape walk and custom string-like objects cannot be substituted.
        for key in value:
            _shape(key, depth=depth + 1, remaining=remaining)
        items = value.values()
    elif kind in {list, tuple, frozenset}:
        if len(value) > 10_000:
            _fail("shape_invalid")
        items = value
    elif kind in _DTO_TYPES:
        declared = fields(value)
        try:
            attributes = object.__getattribute__(value, "__dict__")
        except AttributeError:
            pass
        else:
            # Frozen non-slotted DTOs can still be modified through object.__setattr__, including
            # an instance ``to_dict`` method that would run before older parsers see the value.
            if (type(attributes) is not dict
                    or any(type(key) is not str for key in attributes)
                    or set(attributes) - {item.name for item in declared}):
                _fail("shape_invalid")
        try:
            items = [object.__getattribute__(value, item.name) for item in declared]
        except AttributeError as exc:
            raise PythonRSISchedulerInputError("shape_invalid") from exc
    else:
        _fail("shape_invalid")
    for item in items:
        _shape(item, depth=depth + 1, remaining=remaining)
'''
_ORIGINAL_SHAPE_SHA256 = "1eb67118b680cab53540cfd889fd23bd7e7349265f45af16714c3fe62e1f3c7e"
_oracle_namespace = {
    "math": math,
    "fields": fields,
    "_DTO_TYPES": scheduler._DTO_TYPES,
    "_fail": scheduler._fail,
    "PythonRSISchedulerInputError": scheduler.PythonRSISchedulerInputError,
}
exec(  # noqa: S102 - execute only this pinned local AST oracle, never caller or fixture input
    compile(ast.parse(_ORIGINAL_SHAPE_SOURCE), "<scheduler-shape-64ec3f54>", "exec"),
    _oracle_namespace,
)
_original_shape = _oracle_namespace["_shape"]
_VALIDATORS = (_original_shape, scheduler._shape)


def _outcome(validator, value, *, nodes=100_000, depth=0):
    remaining = [nodes]
    try:
        result = validator(value, depth=depth, remaining=remaining)
    except Exception as exc:  # noqa: BLE001 - exception identity is part of this oracle comparison
        cause = type(exc.__cause__) if exc.__cause__ is not None else None
        return type(exc), str(exc), remaining[0], cause
    assert result is None
    return None, None, remaining[0], None


def _refused(remaining, cause=None):
    return scheduler.PythonRSISchedulerInputError, _ERROR, remaining, cause


def _bare_dto(kind):
    """Exercise shape alone without constructors, serializers, I/O or business validation."""
    value = object.__new__(kind)
    for item in fields(kind):
        object.__setattr__(value, item.name, None)
    return value


def test_original_ast_source_pin_and_namespace_are_independent():
    assert hashlib.sha256(_ORIGINAL_SHAPE_SOURCE.encode()).hexdigest() == _ORIGINAL_SHAPE_SHA256
    assert _original_shape is not scheduler._shape
    assert _original_shape.__globals__ is not scheduler.__dict__
    assert _original_shape.__globals__["_shape"] is _original_shape


@pytest.mark.parametrize("value,accepted", [
    (None, True), (False, True), (True, True), ("", True), ("\ud800", True),
    ("字🙂" * 65536, True), ("🙂" * 131073, False),
    (0, True), (-1, True), (1 << 4095, True), (-(1 << 4095), True),
    (1 << 4096, False), (-(1 << 4096), False),
    (0.0, True), (-0.0, True), (1.7976931348623157e308, True),
    (float("nan"), False), (float("inf"), False), (float("-inf"), False),
], ids=[
    "none", "false", "true", "empty-string", "surrogate-shape-only",
    "unicode-character-limit", "unicode-too-long", "zero-int", "negative-int",
    "integer-limit", "negative-integer-limit", "integer-too-large", "negative-too-large",
    "zero-float", "negative-zero", "finite-limit", "nan", "infinity", "negative-infinity",
])
def test_scalar_boundaries_at_root_and_in_each_collection(value, accepted):
    for subject in (value, [value], (value,), {"key": value}, frozenset((value,))):
        expected = _outcome(_original_shape, subject)
        assert (expected[0] is None) is accepted
        if not accepted:
            assert expected[:2] == (scheduler.PythonRSISchedulerInputError, _ERROR)
        assert _outcome(scheduler._shape, subject) == expected


@pytest.mark.parametrize("kind", [list, tuple, dict, frozenset])
def test_all_collection_lengths_keep_the_original_limit(kind):
    for length in (10_000, 10_001):
        value = {str(index): None for index in range(length)} if kind is dict else kind(range(length))
        expected = _outcome(_original_shape, value)
        assert (expected[0] is None) is (length == 10_000)
        assert _outcome(scheduler._shape, value) == expected


@pytest.mark.parametrize("depth", [-1, 0, 47, 48, 49])
def test_remaining_and_depth_gates_count_scalar_and_empty_container_nodes(depth):
    subjects = (None, 1.0, [], (), frozenset(), {}, [None], (None,), {"key": None})
    for value in subjects:
        for nodes in (-1, 0, 1, 2, 3, 5):
            expected = _outcome(_original_shape, value, nodes=nodes, depth=depth)
            assert _outcome(scheduler._shape, value, nodes=nodes, depth=depth) == expected
            if depth > 48 or nodes <= 0:
                assert expected == _refused(nodes - 1)


@pytest.mark.parametrize("extra", [9, 10])
def test_repeated_shared_collections_reach_the_exact_default_occurrence_budget(extra):
    shared = [None] * 9998
    subject = [shared] * 10 + [None] * extra
    expected = _outcome(_original_shape, subject)
    assert expected == ((None, None, 0, None) if extra == 9 else _refused(-1))
    assert _outcome(scheduler._shape, subject) == expected


def test_all_dictionary_keys_precede_values_and_keep_first_refusal(monkeypatch):
    events = []

    def observe(value):
        events.append(value.hex())
        return False

    monkeypatch.setattr(math, "isfinite", observe)
    for subject, expected_remaining, expected_events in (
        ({"first": float("nan"), 7: None}, 99, []),
        ({"first": float("nan"), "x" * 131073: None}, 97, []),
        ({"first": float("nan"), "last": None}, 96, ["nan"]),
    ):
        for validator in _VALIDATORS:
            events.clear()
            assert _outcome(validator, subject, nodes=100) == _refused(expected_remaining)
            assert events == expected_events
    subject = {"first": object(), "last": None}
    for nodes in range(6):
        assert _outcome(scheduler._shape, subject, nodes=nodes) == _outcome(
            _original_shape, subject, nodes=nodes,
        )
    assert _outcome(scheduler._shape, subject, nodes=100) == _refused(96)


@pytest.mark.parametrize("base", [str, int, float, dict, list, tuple, frozenset])
def test_foreign_subclasses_and_foreign_dictionary_keys_are_not_coerced(base):
    events = []

    class Foreign(base):
        def __len__(self):
            events.append("len")
            raise AssertionError("foreign length")

        def __iter__(self):
            events.append("iter")
            raise AssertionError("foreign iterator")

        def bit_length(self):
            events.append("bit_length")
            raise AssertionError("foreign integer")

        def __float__(self):
            events.append("float")
            raise AssertionError("foreign float")

    value = Foreign()
    for subject in (value, [value], (value,), {"key": value}):
        expected = _outcome(_original_shape, subject)
        assert expected[:2] == (scheduler.PythonRSISchedulerInputError, _ERROR)
        assert _outcome(scheduler._shape, subject) == expected
    if base is str:
        assert _outcome(scheduler._shape, {value: 1.0}, nodes=100) == _refused(99)
    assert events == []


def test_other_foreign_values_and_dto_subclasses_remain_refused():
    class ForeignDTO(scheduler.InputSpec):
        def __getattribute__(self, name):
            raise AssertionError("foreign DTO attribute")

    subjects = (b"bytes", set(), object(), MappingProxyType({}), object.__new__(ForeignDTO))
    for value in subjects:
        expected = _outcome(_original_shape, value, nodes=100)
        assert expected == _refused(99)
        assert _outcome(scheduler._shape, value, nodes=100) == expected


def test_foreign_metaclass_exception_keeps_original_type_and_counter():
    class Meta(type):
        def __hash__(cls):
            raise RuntimeError("inert foreign type hash")

    class Foreign(metaclass=Meta):
        pass

    for value in (Foreign(), [Foreign()], {"key": Foreign()}):
        expected = _outcome(_original_shape, value, nodes=100)
        assert expected[:2] == (RuntimeError, "inert foreign type hash")
        assert _outcome(scheduler._shape, value, nodes=100) == expected


def test_every_known_exact_dto_counts_declared_attributes_without_serializing():
    for kind in scheduler._DTO_TYPES:
        value = _bare_dto(kind)
        nodes = 1 + len(fields(kind))
        assert _outcome(_original_shape, value, nodes=nodes) == (None, None, 0, None)
        assert _outcome(scheduler._shape, value, nodes=nodes) == (None, None, 0, None)
        assert _outcome(scheduler._shape, value, nodes=nodes - 1) == _outcome(
            _original_shape, value, nodes=nodes - 1,
        )
        for depth in (48, 49):
            assert _outcome(scheduler._shape, value, nodes=100, depth=depth) == _outcome(
                _original_shape, value, nodes=100, depth=depth,
            )


def test_dto_dictionary_shadows_nonstring_keys_and_foreign_dicts_refuse_before_children():
    class ForeignDict(dict):
        def __iter__(self):
            raise AssertionError("foreign DTO dictionary iteration")

    for validator in _VALIDATORS:
        value = _bare_dto(scheduler.InputSpec)
        object.__setattr__(value, "to_dict", lambda: pytest.fail("serializer was called"))
        assert _outcome(validator, value, nodes=100) == _refused(99)
        value = _bare_dto(scheduler.InputSpec)
        value.__dict__[1] = None
        assert _outcome(validator, value, nodes=100) == _refused(99)
        value = _bare_dto(scheduler.InputSpec)
        object.__setattr__(value, "__dict__", ForeignDict(value.__dict__))
        assert _outcome(validator, value, nodes=100) == _refused(99)


@pytest.mark.parametrize("kind,missing", [
    (scheduler.InputSpec, "path"), (scheduler.BundleGroup, "entrypoint"),
])
def test_missing_slotted_and_nonslotted_dto_attributes_preserve_error_cause(kind, missing):
    value = _bare_dto(kind)
    object.__delattr__(value, missing)
    for validator in _VALIDATORS:
        assert _outcome(validator, value, nodes=100) == _refused(99, AttributeError)


@pytest.mark.parametrize("getter_failure", [False, True])
def test_all_dto_attributes_are_read_before_any_child_validation(monkeypatch, getter_failure):
    events = []
    value = _bare_dto(scheduler.InputSpec)
    names = [item.name for item in fields(value)]

    def getter(name):
        def read(_self):
            events.append(name)
            if getter_failure and name == names[-1]:
                raise RuntimeError("inert DTO getter")
            return 1.0 if name == names[0] else None
        return property(read)

    for name in names:
        monkeypatch.setattr(scheduler.InputSpec, name, getter(name), raising=False)

    def reject(item):
        events.append(("float", item))
        return False

    monkeypatch.setattr(math, "isfinite", reject)
    for validator in _VALIDATORS:
        events.clear()
        expected = (RuntimeError, "inert DTO getter", 99, None) if getter_failure else _refused(98)
        assert _outcome(validator, value, nodes=100) == expected
        assert events == names + ([] if getter_failure else [("float", 1.0)])


def test_dto_child_values_are_prefetched_but_reobserved_on_the_next_call(monkeypatch):
    for validator in _VALIDATORS:
        value = _bare_dto(scheduler.InputSpec)
        object.__setattr__(value, "path", 1.0)
        object.__setattr__(value, "format", 2.0)
        events = []

        def mutate(item, value=value, events=events):
            events.append(item)
            object.__setattr__(value, "format", b"new invalid field")
            return True

        monkeypatch.setattr(math, "isfinite", mutate)
        assert _outcome(validator, value, nodes=100) == (None, None, 95, None)
        assert events == [1.0, 2.0]
        events.clear()
        assert _outcome(validator, value, nodes=100) == _refused(97)
        assert events == [1.0]


@pytest.mark.parametrize("mode", ["replace-list", "append-list", "shrink-list", "replace-dict", "grow-dict"])
def test_live_collection_iteration_preserves_mutation_and_exception_results(monkeypatch, mode):
    for validator in _VALIDATORS:
        value = {"first": 1.0, "second": 2.0} if mode.endswith("dict") else [1.0, 2.0]
        events = []

        def mutate(item, value=value, events=events):
            events.append(item)
            if mode == "replace-list":
                value[1] = b"invalid later value"
            elif mode == "append-list":
                value.append(None)
            elif mode == "shrink-list":
                value.pop()
            elif mode == "replace-dict":
                value["second"] = b"invalid later value"
            else:
                value["new"] = None
            return True

        monkeypatch.setattr(math, "isfinite", mutate)
        expected = {
            "replace-list": _refused(97),
            "append-list": (None, None, 95, None),
            "shrink-list": (None, None, 98, None),
            "replace-dict": _refused(95),
            "grow-dict": (RuntimeError, "dictionary changed size during iteration", 96, None),
        }[mode]
        assert _outcome(validator, value, nodes=100) == expected
        assert events == ([1.0, 2.0] if mode == "append-list" else [1.0])


def test_finiteness_backend_is_live_for_each_occurrence_and_exception_types_survive(monkeypatch):
    for validator in _VALIDATORS:
        events = []

        def replacement(item, events=events):
            events.append(("replacement", item))
            return False

        def initial(item, events=events, replacement=replacement):
            events.append(("initial", item))
            monkeypatch.setattr(math, "isfinite", replacement)
            return True

        monkeypatch.setattr(math, "isfinite", initial)
        assert _outcome(validator, (1.0, 2.0, 3.0), nodes=100) == _refused(97)
        assert events == [("initial", 1.0), ("replacement", 2.0)]
        for error in (RuntimeError, TypeError):
            def interrupted(_item, error=error):
                raise error("inert finiteness failure")

            monkeypatch.setattr(math, "isfinite", interrupted)
            assert _outcome(validator, [1.0, object()], nodes=100) == (
                error, "inert finiteness failure", 98, None,
            )


@pytest.mark.parametrize("kind", ["list", "dict", "tuple-indirect", "dto"])
def test_cycles_preserve_depth_refusal_and_consumed_budget(kind):
    value = {} if kind == "dict" else _bare_dto(scheduler.InputSpec) if kind == "dto" else []
    if kind == "dict":
        value["self"] = value
    elif kind == "dto":
        object.__setattr__(value, "path", value)
    elif kind == "tuple-indirect":
        value.append((value,))
    else:
        value.append(value)
    expected = _outcome(_original_shape, value)
    assert expected[:2] == (scheduler.PythonRSISchedulerInputError, _ERROR)
    assert _outcome(scheduler._shape, value) == expected


def test_seeded_mixed_shapes_keep_errors_and_remaining_without_fixture_execution():
    rng = random.Random(1911027)
    scalars = (None, True, False, "字", "\ud800", 0, -1, 1.5, float("inf"), b"foreign")

    def generate(depth):
        if depth == 0 or rng.randrange(4) == 0:
            return rng.choice(scalars)
        choice = rng.randrange(5)
        if choice == 0:
            return {str(index): generate(depth - 1) for index in range(rng.randrange(4))}
        if choice == 1:
            return tuple(generate(depth - 1) for _ in range(rng.randrange(4)))
        if choice == 2:
            return frozenset(rng.choices(scalars, k=rng.randrange(4)))
        if choice == 3:
            value = _bare_dto(scheduler.InputSpec)
            object.__setattr__(value, "path", generate(depth - 1))
            return value
        return [generate(depth - 1) for _ in range(rng.randrange(4))]

    for _ in range(100):
        subject = generate(5)
        depth = rng.choice((0, 47, 48))
        for nodes in (1, 10, 100):
            assert _outcome(scheduler._shape, subject, depth=depth, nodes=nodes) == _outcome(
                _original_shape, subject, depth=depth, nodes=nodes,
            )
