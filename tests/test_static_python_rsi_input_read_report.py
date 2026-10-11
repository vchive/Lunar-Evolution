"""Bounded source/mock input reporting; no runtime build or solver execution."""

from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import json
import os
import socket
import subprocess
import time
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA = "lunar-static-python-rsi-input-read-report-v1"
_MARKER = "0123456789abcdef" * 4
_INPUT_LIMIT = 128 * 1024
_REPORT_LIMIT = 4 * _INPUT_LIMIT + 4096
_REQUEST_PATH = "../.rsi-input/request.json"
_MEMORY_PATH = "../.rsi-input/memory.json"
_REQUEST = b'{"task":"local fixture","version":1}'
_MEMORY = b'{"memories":[],"version":1}'
_CLAIMS = (
    "input_authority_verified", "runtime_execution_verified", "solver_result_accepted",
    "memory_use_verified", "production_admission",
)
_MATCH_FIELDS = (
    "manifest_sha256", "report_sha256", "request_sha256", "memory_sha256",
    "request_size", "memory_size",
)
_UNSET = object()


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode("ascii")


def _report(request=_REQUEST, memory=_MEMORY, marker=_MARKER):
    return {
        "schema": _SCHEMA,
        "manifest_sha256": marker,
        "request_hex": request.hex(),
        "memory_hex": memory.hex(),
        "computed": 285,
        "claims": dict.fromkeys(_CLAIMS, False),
    }


@pytest.fixture(scope="module")
def report_api():
    # Import the actual comparator from the checkout under test.
    return importlib.import_module("tools.static_python_rsi_fixture.input_read_report")


def _compare(api, raw=_UNSET, **updates):
    expected = {
        "expected_manifest_sha256": _MARKER,
        "expected_request": _REQUEST,
        "expected_memory": _MEMORY,
    }
    expected.update(updates)
    return api.compare_input_read_report(
        _canonical(_report()) if raw is _UNSET else raw, **expected,
    )


def _forbidden(*args, **kwargs):
    raise AssertionError("unexpected callback or effect")


class UnsafeBytes(bytes):
    __len__ = __iter__ = __getitem__ = __bytes__ = __eq__ = _forbidden
    hex = decode = _forbidden


class UnsafeString(str):
    __len__ = __iter__ = __getitem__ = __str__ = __eq__ = _forbidden
    encode = _forbidden


class UnsafeObject:
    __len__ = __iter__ = __getitem__ = __bytes__ = __str__ = __eq__ = _forbidden


class MockInput:
    def __init__(self, raw, path, events, read_failure=False):
        self.raw = raw
        self.path = path
        self.events = events
        self.read_failure = read_failure

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def read(self, size):
        assert type(size) is int and size == _INPUT_LIMIT + 1
        self.events.append(("read", self.path, size))
        if self.read_failure:
            raise OSError("inert read failure")
        # A fake return can intentionally violate the bytes contract. The source
        # must inspect its exact type without dispatching its methods.
        return self.raw

    def close(self):
        self.events.append(("close", self.path))


def _source_reader(request=_REQUEST, memory=_MEMORY, *, open_failure=None, read_failure=None):
    path = _ROOT / "tools/static_python_rsi_fixture/assets/input_read_report.py"
    source = path.read_bytes()
    tree = ast.parse(source)
    assert not any(isinstance(item, (ast.Import, ast.ImportFrom)) for item in ast.walk(tree))
    events = []
    inputs = {_REQUEST_PATH: request, _MEMORY_PATH: memory}

    def fake_open(name, mode, *args, **kwargs):
        assert type(name) is str and name in inputs
        assert type(mode) is str and mode == "rb"
        assert args == () and kwargs == {}
        opened = [item[1] for item in events if item[0] == "open"]
        assert name not in opened and len(opened) < 2
        events.append(("open", name, mode))
        if name == open_failure:
            raise OSError("inert open failure")
        return MockInput(inputs[name], name, events, read_failure=name == read_failure)

    allowed = dict(vars(builtins))
    for name in ("__import__", "print", "input", "eval", "exec", "compile"):
        allowed[name] = _forbidden
    allowed["open"] = fake_open

    def checked_sum(values):
        assert [(item[1], item[2]) for item in events if item[0] == "read"] == [
            (_REQUEST_PATH, 131073), (_MEMORY_PATH, 131073),
        ]
        return sum(values)

    allowed["sum"] = checked_sum
    namespace = {"__builtins__": allowed}
    exec(compile(tree, "<mock-two-grant-input-report>", "exec"), namespace)  # noqa: S102
    assert events == []
    return namespace["read_input_report"], events


def test_source_returns_canonical_report_after_exactly_two_bounded_reads(report_api, capsys):
    reader, events = _source_reader()
    raw = reader(_MARKER)
    assert type(raw) is bytes
    assert raw == _canonical(_report())
    assert [(event[1], event[2]) for event in events if event[0] == "open"] == [
        (_REQUEST_PATH, "rb"), (_MEMORY_PATH, "rb"),
    ]
    assert [(event[1], event[2]) for event in events if event[0] == "read"] == [
        (_REQUEST_PATH, 131073), (_MEMORY_PATH, 131073),
    ]
    assert _compare(report_api, raw).manifest_sha256 == _MARKER
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("marker", [_MARKER, "0" * 64, "f" * 64])
def test_source_accepts_only_digest_syntax_without_treating_marker_as_authority(marker):
    reader, _ = _source_reader(b"\x00\xff", b"opaque, not parsed, memory")
    value = json.loads(reader(marker))
    assert value == _report(b"\x00\xff", b"opaque, not parsed, memory", marker)
    assert all(item is False for item in value["claims"].values())


@pytest.mark.parametrize("marker", [
    None, False, 64, b"a" * 64, [], {}, "", "a" * 63, "a" * 65,
    "A" * 64, "g" * 64, "é" * 64, "a" * 63 + "\n", "a" * 63 + "/",
    UnsafeString(_MARKER), UnsafeObject(),
], ids=[f"invalid-marker-{index}" for index in range(16)])
def test_source_refuses_invalid_metadata_before_any_open(marker):
    reader, events = _source_reader()
    with pytest.raises((ValueError, TypeError), match="^static_python_rsi_input_report_"):
        reader(marker)
    assert events == []


@pytest.mark.parametrize("path", [_REQUEST_PATH, _MEMORY_PATH])
@pytest.mark.parametrize("failure", ["open", "read"])
def test_source_refuses_either_input_io_failure_without_reporting(path, failure):
    reader, events = _source_reader(**{failure + "_failure": path})
    with pytest.raises((OSError, ValueError)):
        reader(_MARKER)
    assert any(item[0] == failure and item[1] == path for item in events)
    assert all(item[1] in {_REQUEST_PATH, _MEMORY_PATH} for item in events)


@pytest.mark.parametrize("side", ["request", "memory"])
@pytest.mark.parametrize("raw", [
    b"", b"x" * (_INPUT_LIMIT + 1), "text", bytearray(b"bytes"), memoryview(b"bytes"),
    None, 1, [], {}, UnsafeBytes(b"bytes"), UnsafeObject(),
], ids=[f"invalid-input-{index}" for index in range(11)])
def test_source_refuses_empty_oversized_or_nonexact_bytes(side, raw):
    reader, events = _source_reader(**{side: raw})
    with pytest.raises((ValueError, TypeError), match="^static_python_rsi_input_report_"):
        reader(_MARKER)
    target = _REQUEST_PATH if side == "request" else _MEMORY_PATH
    assert ("read", target, _INPUT_LIMIT + 1) in events


@pytest.mark.parametrize("request_bytes,memory_bytes", [
    (b"x", b"y"), (b"\xff" * _INPUT_LIMIT, b"\x00" * _INPUT_LIMIT),
], ids=["minimal", "maximal"])
def test_maximal_or_minimal_inputs_round_trip_in_bounded_report(
    report_api, request_bytes, memory_bytes,
):
    reader, _ = _source_reader(request_bytes, memory_bytes)
    raw = reader(_MARKER)
    assert raw == _canonical(_report(request_bytes, memory_bytes))
    assert len(raw) <= _REPORT_LIMIT
    match = _compare(report_api, raw, expected_request=request_bytes, expected_memory=memory_bytes)
    assert match.request_size == len(request_bytes)
    assert match.memory_size == len(memory_bytes)
    assert match.request_sha256 == hashlib.sha256(request_bytes).hexdigest()
    assert match.memory_sha256 == hashlib.sha256(memory_bytes).hexdigest()


def test_compare_returns_deterministic_immutable_digest_only_dto(report_api):
    raw = _canonical(_report())
    first, second = _compare(report_api, raw), _compare(report_api, raw)
    assert type(first) is report_api.InputReadReportMatch
    assert first == second
    assert tuple(field.name for field in fields(first)) == _MATCH_FIELDS
    assert tuple(getattr(first, field) for field in _MATCH_FIELDS) == (
        _MARKER, hashlib.sha256(raw).hexdigest(), hashlib.sha256(_REQUEST).hexdigest(),
        hashlib.sha256(_MEMORY).hexdigest(), len(_REQUEST), len(_MEMORY),
    )
    with pytest.raises(FrozenInstanceError):
        first.manifest_sha256 = "f" * 64
    assert not any(hasattr(first, name) for name in (
        "raw", "request", "memory", "accepted_result", "production_admission",
        "eligibility", "input_authority_verified",
    ))
    # A DTO supplied as raw evidence cannot be promoted by the comparison API.
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, first)


def test_compare_has_no_io_environment_process_network_clock_or_output_effects(
    report_api, monkeypatch, capsys,
):
    raw = _canonical(_report())
    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", _forbidden)
        guard.setattr(Path, "read_bytes", _forbidden)
        guard.setattr(Path, "write_bytes", _forbidden)
        guard.setattr(os, "open", _forbidden)
        guard.setattr(os, "getenv", _forbidden)
        guard.setattr(subprocess, "run", _forbidden)
        guard.setattr(subprocess, "Popen", _forbidden)
        guard.setattr(socket, "socket", _forbidden)
        guard.setattr(time, "time", _forbidden)
        guard.setattr(time, "monotonic", _forbidden)
        match = _compare(report_api, raw)
    assert match.report_sha256 == hashlib.sha256(raw).hexdigest()
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


_UNSAFE_INPUTS = [
    None, False, 1, "bytes", bytearray(b"bytes"), memoryview(b"bytes"), [], {},
    UnsafeBytes(b"bytes"), UnsafeObject(), b"", b"x" * (_INPUT_LIMIT + 1),
]
_UNSAFE_MARKERS = [
    None, False, 1, b"a" * 64, [], {}, "", "a" * 63, "a" * 65,
    "A" * 64, "g" * 64, "é" * 64, "a" * 63 + "\n", UnsafeString(_MARKER), UnsafeObject(),
]


@pytest.mark.parametrize("field,value", [
    *[("expected_request", value) for value in _UNSAFE_INPUTS],
    *[("expected_memory", value) for value in _UNSAFE_INPUTS],
    *[("expected_manifest_sha256", value) for value in _UNSAFE_MARKERS],
], ids=[f"unsafe-caller-{index}" for index in range(39)])
def test_unsafe_caller_metadata_is_refused_before_parsing_or_hashing(
    report_api, monkeypatch, field, value,
):
    with monkeypatch.context() as guard:
        guard.setattr(json, "loads", _forbidden)
        guard.setattr(hashlib, "sha256", _forbidden)
        with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
            _compare(report_api, b"malformed and must not be parsed", **{field: value})


@pytest.mark.parametrize("raw", [
    None, False, 1, "{}", bytearray(b"{}"), memoryview(b"{}"), [], {},
    UnsafeBytes(b"{}"), UnsafeObject(), b"", b"x" * (_REPORT_LIMIT + 1),
], ids=[f"unsafe-report-{index}" for index in range(12)])
def test_unsafe_report_type_or_bound_is_refused_before_parsing_or_hashing(
    report_api, monkeypatch, raw,
):
    with monkeypatch.context() as guard:
        guard.setattr(json, "loads", _forbidden)
        guard.setattr(hashlib, "sha256", _forbidden)
        with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
            _compare(report_api, raw)


@pytest.mark.parametrize("raw", [
    b"{", b"[]", b"null", b"true", b"285", b'"report"', b"\xff",
    b'[{"nested":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}]",
])
def test_malformed_deep_or_nonobject_json_has_fixed_refusal(report_api, raw):
    with pytest.raises(
        report_api.InputReadReportError, match="^static_python_rsi_input_report_",
    ) as refusal:
        _compare(report_api, raw)
    assert refusal.value.__cause__ is None
    assert refusal.value.__context__ is None


@pytest.mark.parametrize("token", [b"NaN", b"Infinity", b"-Infinity"])
def test_nonfinite_json_is_refused(report_api, token):
    raw = _canonical(_report()).replace(b'"computed":285', b'"computed":' + token)
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, raw)


@pytest.mark.parametrize("location", ["top_level", "claims"])
def test_duplicate_json_keys_are_refused_even_if_values_match(report_api, location):
    raw = _canonical(_report())
    if location == "top_level":
        raw = b'{"computed":285,' + raw[1:]
    else:
        raw = raw.replace(b'"claims":{', b'"claims":{"production_admission":false,')
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, raw)


@pytest.mark.parametrize("encoding", ["spaces", "newline", "reordered", "escaped", "bom"])
def test_noncanonical_json_encoding_is_refused(report_api, encoding):
    record = _report()
    if encoding == "spaces":
        raw = json.dumps(record, sort_keys=True).encode("ascii")
    elif encoding == "newline":
        raw = _canonical(record) + b"\n"
    elif encoding == "reordered":
        raw = json.dumps(dict(reversed(list(record.items()))), separators=(",", ":")).encode("ascii")
    elif encoding == "escaped":
        raw = _canonical(record).replace(b"lunar-static", b"\\u006cunar-static")
    else:
        raw = b"\xef\xbb\xbf" + _canonical(record)
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, raw)


@pytest.mark.parametrize("field", ["schema", "manifest_sha256", "request_hex", "memory_hex", "computed", "claims"])
@pytest.mark.parametrize("change", ["missing", "extra"])
def test_report_requires_exact_fields(report_api, field, change):
    record = _report()
    if change == "missing":
        del record[field]
    else:
        record[field + "_extra"] = record[field]
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, _canonical(record))


@pytest.mark.parametrize("value", [None, [], {}, False, 1, "wrong-schema", _SCHEMA + "-accepted"])
def test_report_schema_cannot_select_authority_or_another_protocol(report_api, value):
    record = _report()
    record["schema"] = value
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, _canonical(record))


@pytest.mark.parametrize("value", [False, True, 285.0, "285", 284, 286, None, [], {}])
def test_computation_requires_exact_fixed_integer(report_api, value):
    record = _report()
    record["computed"] = value
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, _canonical(record))


@pytest.mark.parametrize("claim", _CLAIMS)
@pytest.mark.parametrize("value", [True, 0, None, "false"])
def test_each_claim_requires_exact_false(report_api, claim, value):
    record = _report()
    record["claims"][claim] = value
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, _canonical(record))


@pytest.mark.parametrize("change", ["missing", "extra", "list", "string", "null"])
def test_claims_require_exact_five_key_object(report_api, change):
    record = _report()
    if change == "missing":
        del record["claims"][_CLAIMS[0]]
    elif change == "extra":
        record["claims"]["accepted"] = False
    else:
        record["claims"] = {"list": [], "string": "false", "null": None}[change]
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, _canonical(record))


@pytest.mark.parametrize("value", [None, 1, [], {}, "", "a" * 63, "a" * 65, "A" * 64,
                                     "g" * 64, "a" * 63 + "\n", "f" * 64])
def test_report_marker_requires_exact_caller_marker_and_digest_syntax(report_api, value):
    record = _report()
    record["manifest_sha256"] = value
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, _canonical(record))


@pytest.mark.parametrize("field", ["request_hex", "memory_hex"])
@pytest.mark.parametrize("value", [None, False, 1, [], {}, "", "0", "AA", "gg", "0x00", "aa aa",
                                     "aa\n", "éé", "00" * (_INPUT_LIMIT + 1)],
                         ids=[f"invalid-hex-{index}" for index in range(14)])
def test_input_hex_requires_exact_lowercase_even_nonempty_bounded_shape(report_api, field, value):
    record = _report()
    record[field] = value
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, _canonical(record))


@pytest.mark.parametrize("side", ["request", "memory"])
@pytest.mark.parametrize("change", ["different_bytes", "shorter", "longer"])
def test_either_input_requires_exact_original_bytes(report_api, side, change):
    original = _REQUEST if side == "request" else _MEMORY
    changed = {"different_bytes": b"!" + original[1:], "shorter": original[:-1],
               "longer": original + b" "}[change]
    record = _report()
    record[side + "_hex"] = changed.hex()
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, _canonical(record))


def test_unvalidated_match_dto_is_only_a_value_and_never_comparison_evidence(report_api):
    caller_created = report_api.InputReadReportMatch(
        manifest_sha256=_MARKER, report_sha256="a" * 64, request_sha256="b" * 64,
        memory_sha256="c" * 64, request_size=1, memory_size=1,
    )
    with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
        _compare(report_api, caller_created)


def test_report_limit_is_enforced_on_exact_boundary_even_when_json_is_invalid(report_api):
    for size in (_REPORT_LIMIT, _REPORT_LIMIT + 1):
        with pytest.raises(report_api.InputReadReportError, match="^static_python_rsi_input_report_"):
            _compare(report_api, b" " * size)
