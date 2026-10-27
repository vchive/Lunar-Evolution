"""Compare bounded detached encoding with the retained streaming implementation."""

from __future__ import annotations

import ast
import json

import pytest

from lunar_evolution import producer_python_runtime_tree as runtime

# Retain the pre-change helper as an AST differential oracle, including its
# original chunk limit, traversal order and exception normalization.
_STREAM_SOURCE = '''
def _canonical(value: object) -> bytes:
    try:
        encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        chunks, size = [], 0
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("utf-8")
            size += len(encoded)
            if size > MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES:
                _fail("manifest_too_large")
            chunks.append(encoded)
        return b"".join(chunks)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, PythonRuntimeTreeError):
            raise
        raise PythonRuntimeTreeError("json_invalid") from exc
'''
_STREAM_CODE = compile(ast.parse(_STREAM_SOURCE), "retained-runtime-tree-canonical", "exec")


def _stream(value):
    namespace = {
        "json": json,
        "MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES": runtime.MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES,
        "_fail": runtime._fail,
        "PythonRuntimeTreeError": runtime.PythonRuntimeTreeError,
    }
    exec(_STREAM_CODE, namespace)  # noqa: S102 - fixed retained-source differential oracle
    return namespace["_canonical"](value)


def _outcome(function, value):
    try:
        return "bytes", function(value)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError, RuntimeError) as exc:
        return "error", type(exc), getattr(exc, "code", None), exc.args


@pytest.mark.parametrize("value", [
    None, False, True, 0, -(2**63), 2**64 - 1, "", [], {}, (),
    {"z": [None, True, False, 17], "a": {"tuple": ("first", "second")}},
    {"unicode": "雪😀", "escaping": '\\"\n\t\x00', "control": "\x1f"},
    "\ud800", {"nested": "\udfff"},
    0.0, -0.0, 1.5, float("nan"), float("inf"), float("-inf"),
    2**64, -(2**64), pytest.param(1 << 20000, id="huge-integer"), object(),
    {1: "integer key"}, {"a": 1, None: "mixed key"},
])
def test_exact_bytes_and_fixed_errors_match_retained_stream(value):
    assert _outcome(runtime._canonical, value) == _outcome(_stream, value)


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_actual_byte_limit_still_matches_stream_at_boundary(monkeypatch, offset):
    monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES", 128)
    value = "x" * (126 + offset)
    assert _outcome(runtime._canonical, value) == _outcome(_stream, value)


@pytest.mark.parametrize("bad", [float("nan"), "\ud800", object()])
@pytest.mark.parametrize("bad_first", [False, True])
def test_oversize_and_invalid_value_keep_original_first_refusal(monkeypatch, bad, bad_first):
    monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES", 64)
    value = {"a": bad if bad_first else "x" * 100, "z": "x" * 100 if bad_first else bad}
    assert _outcome(runtime._canonical, value) == _outcome(_stream, value)


@pytest.mark.parametrize("kind", ["depth", "nodes", "float", "integer", "upper-bound"])
def test_uncertain_probe_falls_back_without_rejecting_valid_json(monkeypatch, kind):
    if kind == "depth":
        monkeypatch.setattr(runtime, "_JSON_FAST_MAX_DEPTH", 2)
        value = [[[[]]]]
    elif kind == "nodes":
        monkeypatch.setattr(runtime, "_JSON_FAST_MAX_NODES", 3)
        value = {"a": [1, 2, 3]}
    elif kind == "float":
        value = {"a": -0.0}
    elif kind == "integer":
        value = {"a": 2**100}
    else:
        monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES", 64)
        value = "x" * 32  # Actual encoding fits; its conservative bound does not.
    assert runtime._bounded_exact_json_snapshot(
        value, runtime.MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES,
    ) is runtime._JSON_FAST_UNAVAILABLE
    assert runtime._canonical(value) == _stream(value)


@pytest.mark.parametrize("kind", ["list", "dict"])
def test_cycles_retain_original_fixed_error(kind):
    value = [] if kind == "list" else {}
    if kind == "list":
        value.append(value)
    else:
        value["self"] = value
    assert _outcome(runtime._canonical, value) == _outcome(_stream, value)


def test_snapshot_detaches_every_mutable_container_and_preserves_utf8_wire():
    source = {"a": [{"b": "雪😀"}], "tuple": ({"c": [1, False, None]},)}
    detached = runtime._bounded_exact_json_snapshot(source, 4096)
    assert detached is not runtime._JSON_FAST_UNAVAILABLE
    assert detached is not source
    assert detached["a"] is not source["a"]
    assert detached["a"][0] is not source["a"][0]
    assert detached["tuple"][0]["c"] is not source["tuple"][0]["c"]
    expected = _stream(source)
    source["a"][0]["b"] = "changed"
    source["tuple"][0]["c"].append("changed")
    assert _stream(detached) == expected


def test_c_encoder_receives_detached_snapshot_after_caller_graph_mutates(monkeypatch):
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if not runtime._json_fast_encoder_current(encoder):
        pytest.skip("standard C JSON encoder unavailable")
    source = {"a": [{"b": "original"}]}
    expected = _stream(source)
    original = runtime._bounded_exact_json_snapshot
    snapshots = []

    def snapshot_then_mutate(value, maximum):
        detached = original(value, maximum)
        snapshots.append(detached)
        value["a"][0]["b"] = "x" * (maximum + 1)
        return detached

    monkeypatch.setattr(runtime, "_bounded_exact_json_snapshot", snapshot_then_mutate)
    assert runtime._canonical(source) == expected
    assert len(snapshots) == 1 and snapshots[0] is not source


def test_append_during_snapshot_counts_every_actual_separator(monkeypatch):
    source = [""]
    appended = False

    class AppendAtFirstChild:
        def __lt__(self, nodes):
            nonlocal appended
            if nodes == 2 and not appended:
                source.extend([""] * 100)
                appended = True
            return nodes > 131072

    # This deterministic private work-budget observation stands in for a thread
    # appending after a container's initial length observation. No sleep or race.
    monkeypatch.setattr(runtime, "_JSON_FAST_MAX_NODES", AppendAtFirstChild())
    detached = runtime._bounded_exact_json_snapshot(source, 204)
    assert appended and len(source) == 101
    assert len(json.dumps(source, separators=(",", ":")).encode()) == 304
    assert detached is runtime._JSON_FAST_UNAVAILABLE


@pytest.mark.parametrize("kind", ["dict", "list", "tuple", "str", "int"])
@pytest.mark.parametrize("nested", [False, True])
def test_subclass_probe_invokes_no_callbacks_and_stream_observations_match(kind, nested):
    events = []

    class CallbackDict(dict):
        def items(self):
            events.append("items")
            return super().items()

    class CallbackList(list):
        def __iter__(self):
            events.append("iter")
            return super().__iter__()

        def __len__(self):
            events.append("len")
            return super().__len__()

    class CallbackTuple(tuple):
        def __iter__(self):
            events.append("iter")
            return super().__iter__()

    class CallbackStr(str):
        def __str__(self):
            events.append("str")
            return super().__str__()

    class CallbackInt(int):
        def bit_length(self):
            events.append("bit_length")
            return super().bit_length()

    source = {
        "dict": CallbackDict(a=1), "list": CallbackList([1]),
        "tuple": CallbackTuple((1,)), "str": CallbackStr("a"), "int": CallbackInt(1),
    }[kind]
    if nested:
        source = {"outer": [source]}
    assert runtime._bounded_exact_json_snapshot(source, 4096) is runtime._JSON_FAST_UNAVAILABLE
    assert events == []
    expected = _outcome(_stream, source)
    expected_events = list(events)
    events.clear()
    assert _outcome(runtime._canonical, source) == expected
    assert events == expected_events


@pytest.mark.parametrize("method", ["encode", "iterencode"])
def test_rebound_encoder_methods_retain_original_dispatch(monkeypatch, method):
    original = getattr(json.JSONEncoder, method)
    calls = []

    def observed(self, value, *args, **kwargs):
        calls.append(method)
        return original(self, value, *args, **kwargs)

    monkeypatch.setattr(json.JSONEncoder, method, observed)
    source = {"a": [1, 2, 3]}
    expected = _stream(source)
    expected_calls = list(calls)
    calls.clear()
    assert runtime._canonical(source) == expected
    assert calls == expected_calls


def test_rebound_c_encoder_is_not_newly_called_by_fast_path(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("original stream never calls the rebound C encoder")

    monkeypatch.setattr(json.encoder, "c_make_encoder", forbidden)
    source = {"a": [1, 2, 3]}
    assert runtime._canonical(source) == _stream(source)


def test_rebound_stream_defaults_with_same_code_keep_original_integer_encoding(monkeypatch):
    method = json.encoder._make_iterencode
    original_code = method.__code__
    defaults = method.__defaults__

    def shifted_integer(value):
        return int.__repr__(value + 1)

    monkeypatch.setattr(method, "__defaults__", (*defaults[:-1], shifted_integer))

    def forbidden(*_args, **_kwargs):
        pytest.fail("rebound streaming defaults must bypass the C fast path")

    monkeypatch.setattr(runtime, "_bounded_exact_json_snapshot", forbidden)
    assert method.__code__ is original_code
    assert runtime._canonical({"a": 1}) == _stream({"a": 1}) == b'{"a":2}'


@pytest.mark.parametrize("name", ["__init__", "encode", "iterencode"])
def test_encoder_default_tuple_rebinding_falls_back(monkeypatch, name):
    method = getattr(json.JSONEncoder, name)
    defaults = method.__defaults__
    replacement = (None,) if defaults is None else tuple(item for item in defaults)
    assert replacement is not defaults
    monkeypatch.setattr(method, "__defaults__", replacement)

    def forbidden(*_args, **_kwargs):
        pytest.fail("rebound encoder defaults must bypass the C fast path")

    monkeypatch.setattr(runtime, "_bounded_exact_json_snapshot", forbidden)
    source = {"a": [1, 2]}
    assert runtime._canonical(source) == _stream(source)


def test_in_place_primitive_keyword_default_drift_falls_back(monkeypatch):
    defaults = json.JSONEncoder.__init__.__kwdefaults__
    assert type(defaults) is dict and defaults["skipkeys"] is False
    monkeypatch.setitem(defaults, "skipkeys", True)

    def forbidden(*_args, **_kwargs):
        pytest.fail("changed keyword default values must bypass the C fast path")

    monkeypatch.setattr(runtime, "_bounded_exact_json_snapshot", forbidden)
    assert runtime._canonical({"a": [1]}) == _stream({"a": [1]})


def test_original_none_keyword_defaults_are_pinned(monkeypatch):
    method = json.JSONEncoder.encode
    assert method.__kwdefaults__ is None
    monkeypatch.setattr(method, "__kwdefaults__", {"unused": False})

    def forbidden(*_args, **_kwargs):
        pytest.fail("rebound None keyword defaults must bypass the C fast path")

    monkeypatch.setattr(runtime, "_bounded_exact_json_snapshot", forbidden)
    assert runtime._canonical({"a": [1]}) == _stream({"a": [1]})


@pytest.mark.parametrize("shadow", ["encode", "iterencode", "__init__"])
def test_factory_returning_exact_encoder_keeps_instance_shadow_dispatch(monkeypatch, shadow):
    original_class = json.JSONEncoder
    calls = []

    def factory(*args, **kwargs):
        encoder = original_class(*args, **kwargs)
        original = getattr(encoder, shadow)

        def observed(*args, **kwargs):
            calls.append(shadow)
            return original(*args, **kwargs)

        setattr(encoder, shadow, observed)
        return encoder

    monkeypatch.setattr(json, "JSONEncoder", factory)
    source = {"a": [1, 2, 3]}
    expected = _outcome(_stream, source)
    expected_calls = list(calls)
    calls.clear()
    assert _outcome(runtime._canonical, source) == expected
    assert calls == expected_calls


@pytest.mark.parametrize("shadow", ["encode", "iterencode", "__init__"])
def test_instance_method_shadows_are_not_fast_path_eligible(shadow):
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    setattr(encoder, shadow, lambda *_args, **_kwargs: None)
    assert not runtime._json_fast_encoder_current(encoder)


def test_rebound_string_encoder_keeps_stream_limit_and_dispatch(monkeypatch):
    monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES", 64)
    original = json.encoder.encode_basestring
    calls = []

    def oversized(value):
        calls.append(value)
        return original(value) + "x" * 65

    monkeypatch.setattr(json.encoder, "encode_basestring", oversized)
    expected = _outcome(_stream, {"a": "b"})
    expected_calls = list(calls)
    calls.clear()
    assert _outcome(runtime._canonical, {"a": "b"}) == expected
    assert calls == expected_calls
