"""Pure sealed-runtime startup and loader-negative evidence comparison.

This module validates caller-owned canonical bytes only.  It does not launch a
process, open an ELF image, inspect /proc, read a filesystem, or grant runtime
or production authority.  A successful DTO is synthetic/runtime evidence shape,
not an actual startup acceptance.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import NoReturn

RUNTIME_STARTUP_SCHEMA = "lunar-static-python-runtime-startup-v1"
MAX_RUNTIME_STARTUP_BYTES = 256 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./+-]{0,511}\Z")
_CASES = ("baseline", "loader-negative")
_MARKER = "--lunar-rsi-input-v1"
_CLAIMS = ("startup_performed", "loader_negative_verified", "owner_verified", "production_admission")


class StaticPythonRuntimeStartupError(ValueError):
    """Fixed refusal code without caller-controlled context."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_runtime_startup_" + (
            reason if type(reason) is str and _LABEL.fullmatch(reason) else "invalid"
        )
        super().__init__(self.reason)


class _Refusal(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    raise _Refusal(reason)


def _sha(value: object, reason: str = "digest") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value in {"0" * 64, "f" * 64}:
        _fail(reason)
    return value


def _label(value: object, reason: str = "label") -> str:
    if type(value) is not str or _LABEL.fullmatch(value) is None:
        _fail(reason)
    return value


def _path(value: object) -> str:
    if type(value) is not str or value.startswith("/") or _PATH.fullmatch(value) is None:
        _fail("path")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        _fail("path")
    return value


def _integer(value: object, *, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("integer")
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
        if nodes > 10_000 or depth > 12:
            _fail("bounds")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            text_bytes += len(item.encode("utf-8"))
            if text_bytes > 128 * 1024:
                _fail("bounds")
        elif type(item) not in (int, bool):
            _fail("json")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail("canonical")


def _record(value: object) -> dict:
    item = _object(value, frozenset({"path", "sha256", "size"}), "record")
    _path(item["path"])
    _sha(item["sha256"])
    _integer(item["size"], minimum=1, maximum=128 * 1024 * 1024)
    return item


def _validate(payload: dict, expected: dict[str, str]) -> None:
    if payload["schema"] != RUNTIME_STARTUP_SCHEMA:
        _fail("schema")
    _label(payload["installation_version"])
    for name in ("build_closure_sha256", "binding_sha256", "launch_intent_sha256"):
        if payload[name] != expected[name]:
            _fail("pin")
        _sha(payload[name])
    if payload["fixture_case"] not in _CASES:
        _fail("fixture_case")
    argv = payload["argv"]
    if type(argv) is not list or len(argv) != 3 or any(type(v) is not str for v in argv):
        _fail("argv")
    _path(argv[0])
    marker = _object(payload["marker"], frozenset({"name", "value"}), "marker")
    if marker["name"] != _MARKER or type(marker["value"]) is not str or not _SHA.fullmatch(marker["value"]):
        _fail("marker")
    if argv[1:] != [_MARKER, marker["value"]]:
        _fail("argv")
    startup = _object(payload["startup"], frozenset({"exit_code", "module", "callable", "stdout_sha256", "stderr_sha256"}), "startup")
    _integer(startup["exit_code"], maximum=255)
    if startup["module"] != "_lunar_static_main" or startup["callable"] != "_rsi_launch":
        _fail("entrypoint")
    _sha(startup["stdout_sha256"]); _sha(startup["stderr_sha256"])
    loader = _object(payload["loader"], frozenset({"pt_interp", "dt_needed", "dependencies", "sealed_material_sha256"}), "loader")
    if type(loader["pt_interp"]) is not bool or type(loader["dt_needed"]) is not bool:
        _fail("loader")
    _sha(loader["sealed_material_sha256"])
    deps = loader["dependencies"]
    if type(deps) is not list or len(deps) > 256 or any(type(v) is not str for v in deps):
        _fail("loader")
    if deps != sorted(set(deps)):
        _fail("loader")
    for dep in deps:
        _path(dep)
    owner = _object(payload["owner"], frozenset({"device", "inode", "mode", "executable"}), "owner")
    _integer(owner["device"]); _integer(owner["inode"], minimum=1); _integer(owner["mode"], maximum=0o7777); _record(owner["executable"])
    if owner["executable"]["path"] != argv[0] or not owner["mode"] & 0o111:
        _fail("owner")
    lifecycle = _object(payload["lifecycle"], frozenset({"events", "terminal"}), "lifecycle")
    events = lifecycle["events"]
    if type(events) is not list or not 1 <= len(events) <= 32 or any(type(v) is not str or not _LABEL.fullmatch(v) for v in events):
        _fail("lifecycle")
    if type(lifecycle["terminal"]) is not str or lifecycle["terminal"] not in {"exited", "loader_refused"}:
        _fail("lifecycle")
    if events != ["started", lifecycle["terminal"]]:
        _fail("lifecycle")
    claims = _object(payload["claims"], frozenset(_CLAIMS), "claims")
    if any(value is not False for value in claims.values()):
        _fail("claims")
    if payload["fixture_case"] == "loader-negative":
        if (lifecycle["terminal"] != "loader_refused" or startup["exit_code"] == 0
                or not loader["pt_interp"] and not loader["dt_needed"]):
            _fail("loader_negative")
    else:
        if (lifecycle["terminal"] != "exited" or startup["exit_code"] != 0
                or loader["pt_interp"] or loader["dt_needed"] or deps):
            _fail("startup")


@dataclass(frozen=True, slots=True)
class StaticPythonRuntimeStartup:
    canonical_bytes: bytes
    installation_version: str
    fixture_case: str
    terminal: str

    def to_json(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict:
        return json.loads(self.canonical_bytes)


def parse_static_python_runtime_startup(raw: bytes, *, expected_build_closure_sha256: str,
                                        expected_binding_sha256: str, expected_launch_intent_sha256: str) -> StaticPythonRuntimeStartup:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_RUNTIME_STARTUP_BYTES:
            _fail("raw")
        expected = {"build_closure_sha256": expected_build_closure_sha256, "binding_sha256": expected_binding_sha256, "launch_intent_sha256": expected_launch_intent_sha256}
        for value in expected.values(): _sha(value, "pin")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_float=_constant, parse_constant=_constant)
        _scan(payload)
        fields = frozenset({"schema", "installation_version", "build_closure_sha256", "binding_sha256", "launch_intent_sha256", "fixture_case", "argv", "marker", "startup", "loader", "owner", "lifecycle", "claims"})
        _object(payload, fields)
        if _canonical(payload) != raw:
            _fail("canonical")
        _validate(payload, expected)
        return StaticPythonRuntimeStartup(raw, payload["installation_version"], payload["fixture_case"], payload["lifecycle"]["terminal"])
    except _Refusal as exc:
        reason = exc.reason
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        reason = "json"
    # Raise after the handlers so malformed input is not retained as context.
    raise StaticPythonRuntimeStartupError(reason) from None


__all__ = ["MAX_RUNTIME_STARTUP_BYTES", "RUNTIME_STARTUP_SCHEMA", "StaticPythonRuntimeStartup", "StaticPythonRuntimeStartupError", "parse_static_python_runtime_startup"]
