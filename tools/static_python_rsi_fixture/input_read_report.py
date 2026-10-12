"""Pure supplied-byte comparison; never original file/launch/runtime admission."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

MAX_INPUT_BYTES = 128 * 1024
MAX_REPORT_BYTES = 4 * MAX_INPUT_BYTES + 4096
SCHEMA = "lunar-static-python-rsi-input-read-report-v1"
_CLAIMS = frozenset({
    "input_authority_verified", "runtime_execution_verified", "solver_result_accepted",
    "memory_use_verified", "production_admission",
})
_FIELDS = frozenset({
    "schema", "manifest_sha256", "request_hex", "memory_hex", "computed", "claims",
})


class InputReadReportError(ValueError):
    """Fixed public refusal without input contents or caller exception text."""

    def __init__(self, reason: str) -> None:
        super().__init__("static_python_rsi_input_report_" + reason)


@dataclass(frozen=True, slots=True)
class InputReadReportMatch:
    """Hashes/sizes of matching supplied bytes; no retained evidence authority."""

    manifest_sha256: str
    report_sha256: str
    request_sha256: str
    memory_sha256: str
    request_size: int
    memory_size: int


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputReadReportError("json_invalid")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise InputReadReportError("json_invalid")


def _digest(value: object) -> str:
    if (type(value) is not str or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        raise InputReadReportError("marker_invalid")
    return value


def _decode(value: object) -> bytes:
    if (type(value) is not str or not 0 < len(value) <= 2 * MAX_INPUT_BYTES
            or len(value) % 2 or any(character not in "0123456789abcdef" for character in value)):
        raise InputReadReportError("hex_invalid")
    return bytes.fromhex(value)


def compare_input_read_report(
    raw: bytes, *, expected_manifest_sha256: str, expected_request: bytes,
    expected_memory: bytes,
) -> InputReadReportMatch:
    """Compare a prototype report to independent caller-supplied bytes and marker.

    Successful comparison says nothing about original retained files, launch
    authority, actual runtime, task semantics, solver result or memory usefulness.
    No descriptor, filesystem, process, broker or evaluator is consulted.
    """
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_REPORT_BYTES:
            raise InputReadReportError("report_shape_invalid")
        _digest(expected_manifest_sha256)
        for source in (expected_request, expected_memory):
            if type(source) is not bytes or not 0 < len(source) <= MAX_INPUT_BYTES:
                raise InputReadReportError("input_shape_invalid")
        report = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        if type(report) is not dict or set(report) != _FIELDS or report["schema"] != SCHEMA:
            raise InputReadReportError("schema_invalid")
        if (type(report["claims"]) is not dict or set(report["claims"]) != _CLAIMS
                or any(value is not False for value in report["claims"].values())
                or type(report["computed"]) is not int or report["computed"] != 285):
            raise InputReadReportError("claims_invalid")
        marker = _digest(report["manifest_sha256"])
        if marker != expected_manifest_sha256:
            raise InputReadReportError("marker_mismatch")
        request, memory = _decode(report["request_hex"]), _decode(report["memory_hex"])
        if request != expected_request or memory != expected_memory:
            raise InputReadReportError("input_bytes_mismatch")
        canonical = (json.dumps(report, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
        if canonical != raw:
            raise InputReadReportError("noncanonical")
        return InputReadReportMatch(
            marker, hashlib.sha256(raw).hexdigest(), hashlib.sha256(request).hexdigest(),
            hashlib.sha256(memory).hexdigest(), len(request), len(memory),
        )
    except InputReadReportError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        pass
    # Parser exceptions can retain the full input. Raise outside their handler
    # so neither __cause__ nor __context__ keeps raw request/memory bytes.
    raise InputReadReportError("json_invalid")
