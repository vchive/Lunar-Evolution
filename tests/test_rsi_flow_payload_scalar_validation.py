"""Flow state shape and canonical boundaries remain fresh for every payload."""

from __future__ import annotations

import pytest

from lunar_evolution import rsi_controller as controller
from lunar_evolution.rsi_learning import RSILearningError

_payload = controller.RSILearningController._python_admission_flow_payload
_ERROR = "rsi_python_admission_flow_state_invalid"


@pytest.mark.parametrize("value,expected", [
    (None, b'{"value":null}'), (True, b'{"value":true}'),
    (False, b'{"value":false}'), (17, b'{"value":17}'),
    (-0.0, b'{"value":-0.0}'), ("\u03bb", '{"value":"\u03bb"}'.encode()),
    ([None, {"x": [2, False]}], b'{"value":[null,{"x":[2,false]}]}'),
])
def test_exact_scalars_keep_canonical_bytes(value, expected):
    assert _payload({"value": value}) == expected


def _at_depth(leaf, depth):
    for _ in range(depth - 1):
        leaf = [leaf]
    return {"value": leaf}


@pytest.mark.parametrize("depth", [47, 48, 49])
@pytest.mark.parametrize("leaf", [None, 1, 1.5, "", [], {}])
def test_depth_gate_includes_scalar_leaves_and_empty_containers(monkeypatch, depth, leaf):
    observed = []

    def canonical(value, *, maximum):
        observed.append((value, maximum))
        return b"validated"

    monkeypatch.setattr(controller, "canonical_json", canonical)
    value = _at_depth(leaf, depth)
    if depth <= 48:
        assert _payload(value) == b"validated"
        assert observed == [(value, 8 * 1024 * 1024)]
    else:
        with pytest.raises(RSILearningError, match=_ERROR):
            _payload(value)
        assert observed == []


class _ForeignList(list):
    def __iter__(self):
        pytest.fail("foreign iteration")


class _ForeignDict(dict):
    def values(self):
        pytest.fail("foreign values")


class _ForeignString(str):
    def __str__(self) -> str:
        raise AssertionError("foreign string conversion")


@pytest.mark.parametrize("value", [
    _ForeignList(), _ForeignDict(), _ForeignString("x"), (), b"x", object(),
    {1: "x"}, {_ForeignString("x"): None},
])
def test_foreign_types_and_keys_refuse_before_serialization(monkeypatch, value):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid shape reached serialization")

    monkeypatch.setattr(controller, "canonical_json", forbidden)
    with pytest.raises(RSILearningError, match=_ERROR):
        _payload({"value": value})


@pytest.mark.parametrize("kind", ["dict", "list"])
def test_cycles_refuse_before_serialization(monkeypatch, kind):
    value = {} if kind == "dict" else []
    if kind == "dict":
        value["cycle"] = value
    else:
        value.append(value)

    def forbidden(*args, **kwargs):
        pytest.fail("cycle reached serialization")

    monkeypatch.setattr(controller, "canonical_json", forbidden)
    with pytest.raises(RSILearningError, match=_ERROR):
        _payload({"value": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "\ud800"])
def test_canonical_boundary_still_rejects_nonfinite_or_invalid_unicode(value):
    with pytest.raises(RSILearningError, match=_ERROR):
        _payload({"value": value})


def test_canonical_payload_byte_ceiling_is_unchanged():
    with pytest.raises(RSILearningError, match=_ERROR):
        _payload({"value": "x" * (8 * 1024 * 1024)})


def test_same_object_is_revalidated_after_serializer_mutation(monkeypatch):
    state = {"value": []}
    calls = []

    def canonical(value, *, maximum):
        calls.append(maximum)
        value["value"].append(_ForeignList())
        return b"first"

    monkeypatch.setattr(controller, "canonical_json", canonical)
    assert _payload(state) == b"first"
    with pytest.raises(RSILearningError, match=_ERROR):
        _payload(state)
    assert calls == [8 * 1024 * 1024]
