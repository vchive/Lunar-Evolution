"""Parse a detached real static-Python build probe receipt.

The receipt is an observation envelope for a host-side probe.  It deliberately
does not grant installation, runtime, producer, or production authority.  The
probe may report a successful core link alongside an open optional-module
closure or a startup failure; those states remain explicit in the wire.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import NoReturn

BUILD_PROBE_SCHEMA = "lunar-static-python-build-probe-v1"
MAX_BUILD_PROBE_BYTES = 256 * 1024
MAX_STATIC_IMAGE_BYTES = 128 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_MACHINE = "x86_64"
_CLAIMS = (
    "build_acceptance",
    "runtime_execution",
    "sealed_runtime",
    "production_admission",
)
_BUILD_STATUSES = ("not-run", "succeeded", "blocked", "failed")
_RUNTIME_STATUSES = ("not-run", "succeeded", "failed")


class StaticPythonBuildProbeError(ValueError):
    """Fixed refusal code without caller-controlled paths or text."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_build_probe_" + (
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
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail(reason)
    return value


def _label(value: object, reason: str = "label") -> str:
    if type(value) is not str or _LABEL.fullmatch(value) is None:
        _fail(reason)
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
        if nodes > 4096 or depth > 10:
            _fail("bounds")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            try:
                text_bytes += len(item.encode("utf-8"))
            except UnicodeError:
                _fail("json")
            if text_bytes > 128 * 1024:
                _fail("bounds")
        elif item is None:
            continue
        elif type(item) not in (int, bool):
            _fail("json")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail("canonical")


def _validate(payload: dict) -> None:
    if payload["schema"] != BUILD_PROBE_SCHEMA:
        _fail("schema")
    _label(payload["probe_id"], "probe_id")
    for name in ("source_archive_sha256", "source_tree_sha256", "toolchain_manifest_sha256", "recipe_sha256"):
        _sha(payload[name], "pin")

    build = _object(
        payload["build"],
        frozenset({"configure_status", "target_status", "target", "optional_module_closure", "blocker"}),
        "build",
    )
    if build["configure_status"] not in _BUILD_STATUSES or build["target_status"] not in _BUILD_STATUSES:
        _fail("build")
    _label(build["target"], "build")
    if build["optional_module_closure"] not in {"closed", "open", "not-observed"}:
        _fail("build")
    blocker = build["blocker"]
    if blocker is not None:
        _label(blocker, "build")
    if build["target_status"] == "blocked" and blocker is None:
        _fail("build")
    if build["target_status"] != "blocked" and blocker is not None:
        _fail("build")

    artifact = _object(
        payload["artifact"],
        frozenset({"present", "sha256", "size", "elf"}),
        "artifact",
    )
    if type(artifact["present"]) is not bool:
        _fail("artifact")
    if artifact["present"]:
        _sha(artifact["sha256"], "artifact")
        _integer(artifact["size"], minimum=1, maximum=MAX_STATIC_IMAGE_BYTES)
        elf = _object(
            artifact["elf"],
            frozenset({
                "class", "byte_order", "type", "machine", "program_headers",
                "section_headers", "pt_interp", "dt_needed", "dynamic_section",
            }),
            "elf",
        )
        if elf["class"] != 64 or elf["byte_order"] != "little" or elf["type"] != "ET_EXEC":
            _fail("elf")
        if elf["machine"] != _MACHINE:
            _fail("elf")
        for name in ("program_headers", "section_headers"):
            _integer(elf[name], maximum=4096)
        for name in ("pt_interp", "dt_needed", "dynamic_section"):
            if type(elf[name]) is not bool:
                _fail("elf")
    else:
        if artifact["sha256"] is not None or artifact["size"] is not None or artifact["elf"] is not None:
            _fail("artifact")

    runtime = _object(payload["runtime"], frozenset({"attempted", "status", "exit_code", "failure"}), "runtime")
    if type(runtime["attempted"]) is not bool or runtime["status"] not in _RUNTIME_STATUSES:
        _fail("runtime")
    if runtime["status"] == "not-run":
        if runtime["attempted"] or runtime["exit_code"] is not None or runtime["failure"] is not None:
            _fail("runtime")
    else:
        if not runtime["attempted"] or type(runtime["exit_code"]) is not int:
            _fail("runtime")
        if not -128 <= runtime["exit_code"] <= 255:
            _fail("runtime")
        if runtime["status"] == "failed":
            _label(runtime["failure"], "runtime")
        elif runtime["exit_code"] != 0 or runtime["failure"] is not None:
            _fail("runtime")

    claims = _object(payload["claims"], frozenset(_CLAIMS), "claims")
    if any(value is not False for value in claims.values()):
        _fail("claims")


@dataclass(frozen=True, slots=True)
class StaticPythonBuildProbe:
    """Detached probe observations; no execution or admission authority."""

    canonical_bytes: bytes
    probe_id: str
    build_status: str
    runtime_status: str
    artifact_sha256: str | None
    artifact_size: int | None

    def to_json(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict[str, object]:
        return json.loads(self.canonical_bytes)


def parse_static_python_build_probe(raw: bytes) -> StaticPythonBuildProbe:
    """Parse one canonical host probe receipt without filesystem or process access."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_BUILD_PROBE_BYTES:
            _fail("raw")
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_float=_constant, parse_constant=_constant,
        )
        _scan(payload)
        fields = frozenset({
            "schema", "probe_id", "source_archive_sha256", "source_tree_sha256",
            "toolchain_manifest_sha256", "recipe_sha256", "build", "artifact", "runtime", "claims",
        })
        _object(payload, fields)
        if _canonical(payload) != raw:
            _fail("canonical")
        _validate(payload)
        artifact = payload["artifact"]
        return StaticPythonBuildProbe(
            canonical_bytes=raw,
            probe_id=payload["probe_id"],
            build_status=payload["build"]["target_status"],
            runtime_status=payload["runtime"]["status"],
            artifact_sha256=artifact["sha256"],
            artifact_size=artifact["size"],
        )
    except _Refusal as exc:
        reason = exc.reason
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        reason = "json"
    raise StaticPythonBuildProbeError(reason) from None


__all__ = [
    "BUILD_PROBE_SCHEMA",
    "MAX_BUILD_PROBE_BYTES",
    "MAX_STATIC_IMAGE_BYTES",
    "StaticPythonBuildProbe",
    "StaticPythonBuildProbeError",
    "parse_static_python_build_probe",
]
