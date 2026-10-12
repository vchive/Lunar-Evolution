"""Pure post-execution handoff cross-pin contract for the static Python path.

The handoff is deliberately a detached comparison.  It joins startup, input
result, terminal, budget and publication-intent digests without reading any
of those records or starting a process/evaluator.  Every capability claim is
kept false; a matching DTO is evidence shape, not production admission.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import NoReturn

RUNTIME_HANDOFF_SCHEMA = "lunar-static-python-runtime-handoff-v1"
MAX_RUNTIME_HANDOFF_BYTES = 64 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_STATES = frozenset({"completed", "failed", "cancelled", "unknown"})
_PUBLICATION_STATES = frozenset({"prepared", "rejected", "unknown"})
_CLEANUP_STATES = frozenset({"cleaned", "already_exited", "unknown"})
_CLAIMS = (
    "runtime_startup_verified", "input_result_verified", "terminal_verified",
    "publication_ready", "recovery_verified", "production_admission",
)
_FIELDS = frozenset({
    "schema", "startup_sha256", "input_result_sha256", "terminal_sha256",
    "handoff_sha256", "binding_sha256", "launch_intent_sha256",
    "result_sha256", "publication_intent_sha256", "request_budget",
    "request_count", "wall_timeout_seconds", "deadline_unix", "terminal_state",
    "cleanup_status", "publication_state", "claims",
})


class StaticPythonRuntimeHandoffError(ValueError):
    """Fixed refusal code without caller-controlled bytes or exception text."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", reason) is None:
            reason = "invalid"
        self.reason = "static_python_runtime_handoff_" + reason
        super().__init__(self.reason)


class _Refusal(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    raise _Refusal(reason)


def _sha(value: object, reason: str = "digest") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail(reason)
    return value


def _integer(value: object, reason: str, *, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(reason)
    return value


def _number(value: object, reason: str, *, minimum: float = 0.0) -> int | float:
    if type(value) not in {int, float} or isinstance(value, bool):
        _fail(reason)
    if (type(value) is float and not math.isfinite(value)) or value < minimum:
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
        if nodes > 256 or depth > 8:
            _fail("bounds")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif type(item) is str:
            text_bytes += len(item.encode("utf-8"))
            if text_bytes > 32 * 1024:
                _fail("bounds")
        elif type(item) not in (int, bool, float) or (type(item) is float and not math.isfinite(item)):
            _fail("json")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail("canonical")


@dataclass(frozen=True, slots=True)
class StaticPythonRuntimeHandoff:
    """Immutable cross-pin projection with no raw result or live authority."""

    canonical_bytes: bytes
    handoff_sha256: str
    terminal_state: str
    publication_state: str
    request_budget: int
    request_count: int

    def to_json(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict:
        return json.loads(self.canonical_bytes)


def parse_static_python_runtime_handoff(
    raw: bytes, *, expected_startup_sha256: str, expected_input_result_sha256: str,
    expected_terminal_sha256: str, expected_handoff_sha256: str,
    expected_binding_sha256: str, expected_launch_intent_sha256: str,
    expected_result_sha256: str, expected_publication_intent_sha256: str,
    expected_request_budget: int, expected_request_count: int,
    expected_wall_timeout_seconds: float, expected_deadline_unix: float,
    expected_terminal_state: str, expected_cleanup_status: str,
    expected_publication_state: str,
) -> StaticPythonRuntimeHandoff:
    """Validate one bounded canonical post-execution projection, without I/O."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_RUNTIME_HANDOFF_BYTES:
            _fail("raw")
        expected = {
            "startup_sha256": expected_startup_sha256,
            "input_result_sha256": expected_input_result_sha256,
            "terminal_sha256": expected_terminal_sha256,
            "handoff_sha256": expected_handoff_sha256,
            "binding_sha256": expected_binding_sha256,
            "launch_intent_sha256": expected_launch_intent_sha256,
            "result_sha256": expected_result_sha256,
            "publication_intent_sha256": expected_publication_intent_sha256,
        }
        for value in expected.values():
            _sha(value, "pin")
        request_budget = _integer(expected_request_budget, "budget", minimum=1)
        request_count = _integer(expected_request_count, "request_count")
        if request_count > request_budget:
            _fail("budget")
        timeout = _number(expected_wall_timeout_seconds, "timeout", minimum=0.000001)
        deadline = _number(expected_deadline_unix, "deadline", minimum=0.000001)
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                             parse_float=float, parse_constant=_constant)
        _scan(payload)
        _object(payload, _FIELDS)
        if _canonical(payload) != raw:
            _fail("canonical")
        if payload["schema"] != RUNTIME_HANDOFF_SCHEMA:
            _fail("schema")
        for field, value in expected.items():
            _sha(payload[field])
            if payload[field] != value:
                _fail("cross_pin")
        _integer(payload["request_budget"], "budget", minimum=1)
        _integer(payload["request_count"], "budget")
        if payload["request_budget"] != request_budget or payload["request_count"] != request_count:
            _fail("budget")
        actual_timeout = _number(payload["wall_timeout_seconds"], "timeout", minimum=0.000001)
        actual_deadline = _number(payload["deadline_unix"], "deadline", minimum=0.000001)
        if actual_timeout != timeout or actual_deadline != deadline:
            _fail("budget")
        if (type(payload["terminal_state"]) is not str or payload["terminal_state"] not in _STATES
                or type(payload["publication_state"]) is not str or payload["publication_state"] not in _PUBLICATION_STATES):
            _fail("state")
        if type(payload["cleanup_status"]) is not str or payload["cleanup_status"] not in _CLEANUP_STATES:
            _fail("cleanup")
        if payload["publication_state"] == "prepared" and (
            payload["terminal_state"] != "completed" or payload["cleanup_status"] == "unknown"
        ):
            _fail("publication_state")
        states = {
            "terminal_state": (expected_terminal_state, _STATES),
            "cleanup_status": (expected_cleanup_status, _CLEANUP_STATES),
            "publication_state": (expected_publication_state, _PUBLICATION_STATES),
        }
        for field, (expected_state, allowed) in states.items():
            if type(expected_state) is not str or expected_state not in allowed:
                _fail("state_pin")
            if payload[field] != expected_state:
                _fail("state_pin")
        claims = _object(payload["claims"], frozenset(_CLAIMS), "claims")
        if any(value is not False for value in claims.values()):
            _fail("claims")
        return StaticPythonRuntimeHandoff(
            raw, payload["handoff_sha256"], payload["terminal_state"], payload["publication_state"],
            request_budget, request_count,
        )
    except _Refusal as exc:
        reason = exc.reason
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        reason = "json"
    raise StaticPythonRuntimeHandoffError(reason) from None


__all__ = [
    "MAX_RUNTIME_HANDOFF_BYTES", "RUNTIME_HANDOFF_SCHEMA",
    "StaticPythonRuntimeHandoff", "StaticPythonRuntimeHandoffError",
    "parse_static_python_runtime_handoff",
]
