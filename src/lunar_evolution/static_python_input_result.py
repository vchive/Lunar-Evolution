"""Pure cross-pin projection for the static-Python RSI input report.

This module joins caller-owned hashes from the F03 startup observation and the
F04 two-input report.  It deliberately does not read either report, open an
input file, start a process, or create a solver/result envelope.  A successful
DTO is only a bounded comparison of canonical bytes; all capability claims
remain false.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import NoReturn

INPUT_RESULT_SCHEMA = "lunar-static-python-input-result-v1"
INPUT_REPORT_SCHEMA = "lunar-static-python-rsi-input-read-report-v1"
MAX_INPUT_RESULT_BYTES = 64 * 1024
MAX_INPUT_RESULT_NODES = 256
MAX_INPUT_RESULT_TEXT_BYTES = 32 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CLAIMS = (
    "input_authority_verified", "runtime_execution_verified",
    "solver_result_accepted", "memory_use_verified", "production_admission",
)
_FIELDS = frozenset({
    "schema", "startup_sha256", "build_closure_sha256", "binding_sha256",
    "launch_intent_sha256", "input_report_schema", "manifest_sha256",
    "report_sha256", "request_sha256", "memory_sha256", "request_size",
    "memory_size", "computed", "claims",
})


class StaticPythonInputResultError(ValueError):
    """Fixed refusal code that never includes caller bytes or exception text."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", reason) is None:
            reason = "invalid"
        self.reason = "static_python_input_result_" + reason
        super().__init__(self.reason)


class _Refusal(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    raise _Refusal(reason)


def _digest(value: object, reason: str = "digest") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail(reason)
    return value


def _integer(value: object, reason: str = "integer", *, maximum: int = 128 * 1024) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        _fail(reason)
    return value


def _object(value: object, fields: frozenset[str], reason: str = "schema") -> dict:
    if type(value) is not dict or frozenset(value) != fields:
        _fail(reason)
    return value


def _pairs(items: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            _fail("duplicate_key")
        result[key] = value
    return result


def _constant(_: str) -> NoReturn:
    _fail("json")


def _scan(value: object) -> None:
    pending = [(value, 0)]
    nodes = text_bytes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > MAX_INPUT_RESULT_NODES or depth > 8:
            _fail("bounds")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            text_bytes += len(item.encode("utf-8"))
            if text_bytes > MAX_INPUT_RESULT_TEXT_BYTES:
                _fail("bounds")
        elif type(item) not in (int, bool):
            _fail("json")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise StaticPythonInputResultError("canonical") from exc


@dataclass(frozen=True, slots=True)
class StaticPythonInputResult:
    """Immutable digest/size projection; it contains no raw input or result."""

    canonical_bytes: bytes
    startup_sha256: str
    build_closure_sha256: str
    binding_sha256: str
    launch_intent_sha256: str
    input_report_schema: str
    manifest_sha256: str
    report_sha256: str
    request_sha256: str
    memory_sha256: str
    request_size: int
    memory_size: int
    computed: int

    def to_json(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict:
        return json.loads(self.canonical_bytes)


def parse_static_python_input_result(
    raw: bytes, *, expected_startup_sha256: str,
    expected_build_closure_sha256: str, expected_binding_sha256: str,
    expected_launch_intent_sha256: str, expected_manifest_sha256: str,
    expected_report_sha256: str, expected_request_sha256: str,
    expected_memory_sha256: str, expected_request_size: int,
    expected_memory_size: int,
) -> StaticPythonInputResult:
    """Validate a caller-owned cross-pin projection without external effects."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_INPUT_RESULT_BYTES:
            _fail("raw")
        expected = {
            "startup_sha256": expected_startup_sha256,
            "build_closure_sha256": expected_build_closure_sha256,
            "binding_sha256": expected_binding_sha256,
            "launch_intent_sha256": expected_launch_intent_sha256,
            "manifest_sha256": expected_manifest_sha256,
            "report_sha256": expected_report_sha256,
            "request_sha256": expected_request_sha256,
            "memory_sha256": expected_memory_sha256,
        }
        for value in expected.values():
            _digest(value, "pin")
        _integer(expected_request_size, "input_size")
        _integer(expected_memory_size, "input_size")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                             parse_float=_constant, parse_constant=_constant)
        _scan(payload)
        _object(payload, _FIELDS)
        if _canonical(payload) != raw:
            _fail("canonical")
        if payload["schema"] != INPUT_RESULT_SCHEMA:
            _fail("schema")
        for field in (
            "startup_sha256", "build_closure_sha256", "binding_sha256",
            "launch_intent_sha256", "manifest_sha256", "report_sha256",
            "request_sha256", "memory_sha256",
        ):
            _digest(payload[field])
            if payload[field] != expected[field]:
                _fail("cross_pin")
        if payload["input_report_schema"] != INPUT_REPORT_SCHEMA:
            _fail("report_schema")
        if payload["request_size"] != expected_request_size or payload["memory_size"] != expected_memory_size:
            _fail("input_size")
        if type(payload["computed"]) is not int or payload["computed"] != 285:
            _fail("computed")
        claims = _object(payload["claims"], frozenset(_CLAIMS), "claims")
        if any(value is not False for value in claims.values()):
            _fail("claims")
        return StaticPythonInputResult(
            raw, payload["startup_sha256"], payload["build_closure_sha256"],
            payload["binding_sha256"], payload["launch_intent_sha256"],
            payload["input_report_schema"], payload["manifest_sha256"],
            payload["report_sha256"], payload["request_sha256"], payload["memory_sha256"],
            payload["request_size"], payload["memory_size"], payload["computed"],
        )
    except _Refusal as exc:
        raise StaticPythonInputResultError(exc.reason) from None
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        # Do not retain malformed raw bytes or parser locals in the public error.
        raise StaticPythonInputResultError("json") from None


__all__ = [
    "INPUT_REPORT_SCHEMA", "INPUT_RESULT_SCHEMA", "MAX_INPUT_RESULT_BYTES",
    "StaticPythonInputResult", "StaticPythonInputResultError",
    "parse_static_python_input_result",
]
