"""Fresh admission shapes retain the prior recursion and callback ordering."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields

import pytest

from lunar_evolution import rsi_python_admission as admission


def _recursive_oracle(value, *, dto_types=(), _depth=0):
    """Independent pre-inline validator from c5366cee, without scalar shortcuts."""
    if _depth > 48:
        raise admission.RSIPythonAdmissionError("shape_invalid")
    kind = type(value)
    if value is None or kind is str or kind is bool or kind is int:
        return
    if kind is float:
        if not math.isfinite(value):
            raise admission.RSIPythonAdmissionError("shape_invalid")
        return
    if kind is dict:
        for key in value:
            if type(key) is not str:
                raise admission.RSIPythonAdmissionError("shape_invalid")
        items = value.values()
    elif kind is list or kind is tuple:
        items = value
    else:
        for dto_type in dto_types:
            if kind is dto_type:
                items = (getattr(value, field.name) for field in fields(value))
                break
        else:
            raise admission.RSIPythonAdmissionError("shape_invalid")
    for item in items:
        _recursive_oracle(item, dto_types=dto_types, _depth=_depth + 1)


@dataclass
class _Cell:
    value: object


@dataclass
class _EmptyDTO:
    pass


def _observe(validator, factory, monkeypatch, *, dto_types=(_Cell, _EmptyDTO), **kwargs):
    with monkeypatch.context() as patch:
        events = []
        value = factory(events, patch)
        try:
            validator(value, dto_types=dto_types, **kwargs)
        except (admission.RSIPythonAdmissionError, RuntimeError) as exc:
            return type(exc), str(exc), events
        return None, None, events


def _compare(factory, monkeypatch, **kwargs):
    expected = _observe(_recursive_oracle, factory, monkeypatch, **kwargs)
    actual = _observe(admission.validate_rsi_python_admission_shapes, factory, monkeypatch, **kwargs)
    assert actual == expected
    return actual


@pytest.mark.parametrize("value,accepted", [
    (None, True), ("é", True), (False, True), (2**200, True),
    (-0.0, True), (1.25, True), (float("nan"), False),
    (float("inf"), False), (float("-inf"), False),
])
def test_nested_exact_scalars_match_recursive_oracle(monkeypatch, value, accepted):
    outcome = _compare(lambda *_: {"nested": [_Cell((None, True, 3, value))]}, monkeypatch)
    assert outcome[:2] == ((None, None) if accepted else
                          (admission.RSIPythonAdmissionError, "rsi_python_admission_shape_invalid"))


def _at_depth(value, depth):
    for _ in range(depth):
        value = [value]
    return value


@pytest.mark.parametrize("depth", [47, 48, 49])
@pytest.mark.parametrize("leaf", ["scalar", "list", "dict", "tuple", "empty-dto", "cell"])
def test_depth_boundary_includes_empty_containers_and_dto_fields(monkeypatch, depth, leaf):
    def factory(*_):
        value = {"scalar": 1.0, "list": [], "dict": {}, "tuple": (),
                 "empty-dto": _EmptyDTO(), "cell": _Cell(None)}[leaf]
        return _at_depth(value, depth)

    outcome = _compare(factory, monkeypatch)
    accepted = depth <= 48 and not (leaf == "cell" and depth == 48)
    assert (outcome[0] is None) is accepted


def test_child_depth_refuses_before_finiteness_callback(monkeypatch):
    def factory(events, patch):
        def forbidden(value):
            events.append("isfinite")
            raise AssertionError("depth must be checked first")

        patch.setattr(math, "isfinite", forbidden)
        return [1.0]

    outcome = _compare(factory, monkeypatch, _depth=48)
    assert outcome == (admission.RSIPythonAdmissionError, "rsi_python_admission_shape_invalid", [])


@pytest.mark.parametrize("kind", ["list", "dict", "dto"])
def test_cycles_still_fail_at_the_depth_boundary(monkeypatch, kind):
    def factory(*_):
        if kind == "list":
            value = []
            value.append(value)
        elif kind == "dict":
            value = {}
            value["self"] = value
        else:
            value = _Cell(None)
            value.value = value
        return value

    outcome = _compare(factory, monkeypatch)
    assert outcome[:2] == (admission.RSIPythonAdmissionError, "rsi_python_admission_shape_invalid")


def test_shared_subtree_rechecks_every_float_occurrence(monkeypatch):
    def factory(events, patch):
        def finite(value):
            events.append(value)
            return True

        patch.setattr(math, "isfinite", finite)
        shared = (1.0, _Cell(2.0))
        return [shared, {"again": shared}, (shared,)]

    assert _compare(factory, monkeypatch) == (None, None, [1.0, 2.0] * 3)


class _CallbackList(list):
    def __iter__(self):
        raise AssertionError("list subclass iterated")


class _CallbackDict(dict):
    def __iter__(self):
        raise AssertionError("dict subclass iterated")

    def values(self):
        raise AssertionError("dict subclass values read")


class _CallbackTuple(tuple):
    def __iter__(self):
        raise AssertionError("tuple subclass iterated")


class _Text(str):
    pass


class _Integer(int):
    pass


class _Float(float):
    pass


class _CellSubclass(_Cell):
    def __getattribute__(self, name):
        raise AssertionError("unapproved DTO subclass observed")


@pytest.mark.parametrize("factory", [
    lambda: _CallbackList([1]), lambda: _CallbackDict(a=1), lambda: _CallbackTuple((1,)),
    lambda: _Text("a"), lambda: _Integer(1), lambda: _Float(1), lambda: _CellSubclass(1),
])
def test_nested_subclasses_refuse_without_collection_or_dto_callbacks(monkeypatch, factory):
    outcome = _compare(lambda *_: {"nested": [factory()]}, monkeypatch)
    assert outcome[:2] == (admission.RSIPythonAdmissionError, "rsi_python_admission_shape_invalid")


class _ForeignMeta(type):
    def __eq__(cls, other):
        raise AssertionError("foreign metaclass equality observed")

    def __hash__(cls):
        raise AssertionError("foreign metaclass hash observed")


class _Foreign(metaclass=_ForeignMeta):
    pass


def test_nested_foreign_metaclass_is_neither_hashed_nor_compared(monkeypatch):
    outcome = _compare(lambda *_: [_Foreign()], monkeypatch)
    assert outcome[:2] == (admission.RSIPythonAdmissionError, "rsi_python_admission_shape_invalid")


@pytest.mark.parametrize("key", [1, _Text("bad"), _Foreign()])
def test_all_dictionary_keys_are_checked_before_any_value(monkeypatch, key):
    def factory(events, patch):
        def finite(value):
            events.append("value observed")
            raise RuntimeError("must reject the later key first")

        patch.setattr(math, "isfinite", finite)
        return {"first": 1.0, key: 2.0}

    assert _compare(factory, monkeypatch) == (
        admission.RSIPythonAdmissionError, "rsi_python_admission_shape_invalid", [],
    )


@dataclass
class _OrderedDTO:
    first: object
    second: object
    third: object

    def __getattribute__(self, name):
        if name in ("first", "second", "third"):
            object.__getattribute__(self, "_events").append("get:" + name)
            if name == "third":
                raise RuntimeError("later field read")
        return object.__getattribute__(self, name)


@pytest.mark.parametrize("mode", ["invalid-first", "raise", "replace", "mutate"])
def test_dto_fields_and_current_finiteness_hook_preserve_first_error(monkeypatch, mode):
    def factory(events, patch):
        value = _OrderedDTO(object() if mode == "invalid-first" else 1.0, 2.0, 3.0)
        value._events = events

        def replacement(number):
            events.append("replacement:" + str(number))
            raise RuntimeError("replacement failure")

        def finite(number):
            events.append("finite:" + str(number))
            if mode == "raise":
                raise RuntimeError("first finite failure")
            if mode == "replace":
                patch.setattr(math, "isfinite", replacement)
            elif mode == "mutate":
                value.second = object()
            return True

        patch.setattr(math, "isfinite", finite)
        return value

    outcome = _compare(factory, monkeypatch, dto_types=(_OrderedDTO,))
    expected = {
        "invalid-first": (admission.RSIPythonAdmissionError, "rsi_python_admission_shape_invalid", ["get:first"]),
        "raise": (RuntimeError, "first finite failure", ["get:first", "finite:1.0"]),
        "replace": (RuntimeError, "replacement failure",
                    ["get:first", "finite:1.0", "get:second", "replacement:2.0"]),
        "mutate": (admission.RSIPythonAdmissionError, "rsi_python_admission_shape_invalid",
                   ["get:first", "finite:1.0", "get:second"]),
    }
    assert outcome == expected[mode]


def test_dto_getter_can_replace_finiteness_hook_before_its_scalar_is_checked(monkeypatch):
    def factory(events, patch):
        value = _OrderedDTO(1.0, 2.0, 3.0)
        value._events = events
        original_getter = _OrderedDTO.__getattribute__

        def stale_hook(number):
            raise AssertionError("finiteness hook was captured before getattr")

        def replacement(number):
            events.append("replacement:" + str(number))
            return False

        def getter(self, name):
            result = original_getter(self, name)
            if name == "first":
                patch.setattr(math, "isfinite", replacement)
            return result

        patch.setattr(math, "isfinite", stale_hook)
        patch.setattr(_OrderedDTO, "__getattribute__", getter)
        return value

    assert _compare(factory, monkeypatch, dto_types=(_OrderedDTO,)) == (
        admission.RSIPythonAdmissionError, "rsi_python_admission_shape_invalid",
        ["get:first", "replacement:1.0"],
    )


@pytest.mark.parametrize("character,width", [("x", 1), ("é", 2)])
def test_canonical_limit_counts_encoded_bytes_and_accepts_exact_limit(character, width):
    maximum = admission.MAX_RSI_PYTHON_ADMISSION_BYTES
    assert maximum == 512 * 1024
    value = character * ((maximum - 2) // width)
    expected = b'"' + character.encode("utf-8") * ((maximum - 2) // width) + b'"'
    assert len(expected) == maximum
    assert admission._canonical(value) == expected
    with pytest.raises(admission.RSIPythonAdmissionError, match="^rsi_python_admission_record_too_large$"):
        admission._canonical(value + "a")


@pytest.mark.parametrize("invalid", [chr(0xD800), chr(0xDFFF)], ids=["high-surrogate", "low-surrogate"])
def test_unicode_encoding_failure_retains_json_error_after_shape_acceptance(invalid):
    value = {"nested": [invalid]}
    assert _recursive_oracle(value) is None
    assert admission.validate_rsi_python_admission_shapes(value) is None
    with pytest.raises(admission.RSIPythonAdmissionError, match="^rsi_python_admission_json_invalid$"):
        admission._canonical(value)
