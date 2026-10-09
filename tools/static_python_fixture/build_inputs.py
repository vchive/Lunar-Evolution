"""Pure emission of fixed reviewed candidate compile and freeze inputs.

The caller reads the tracked JSON; this module never discovers or reads source
files, invokes configure/compiler/freezer, or supplies an observed link closure.
Pins describe reviewed bytes or deterministic source-preparation bytes only.
Unresolved configure substitutions, toolchain inputs and runtime gates stay open.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, NoReturn

REVIEWED_BUILD_INPUTS_FILENAME = "reviewed-build-inputs.json"
REVIEWED_BUILD_INPUTS_SCHEMA = "lunar-static-python-reviewed-build-inputs-v1"
STATIC_PYTHON_BUILD_INPUTS_SCHEMA = "lunar-static-python-build-inputs-v1"
REVIEWED_BUILD_INPUTS_SHA256 = "ba5221310c10360b010d0b5a5b104586d3a1529f159c93a9c02a83319701a92b"
REVIEWED_BUILD_INPUTS_BYTES = 79459
MAX_REVIEWED_BUILD_INPUTS_BYTES = 128 * 1024

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TOP_FIELDS = frozenset({
    "schema", "source_version", "source_commit", "profile", "reviewed_controls", "shared_units",
    "freezer_units", "target_units", "freeze_tasks", "generated_sources", "fixture_headers",
    "source_preparation",
    "stock_excluded", "unresolved_configuration", "required_later_checks", "compile_requirements",
    "getbuildinfo_requirements", "states",
})
_UNIT_FIELDS = frozenset({
    "object", "source", "origin", "compile_role", "source_size", "source_sha256",
    "reviewed_source_sha256", "extra_flags",
})
_FREEZE_FIELDS = frozenset({
    "name", "generator_id", "symbol", "source", "origin", "source_size", "source_sha256",
    "output", "package",
})
_STATES = frozenset({
    "source_archive_verified", "toolchain_verified", "configure_performed", "compile_performed",
    "link_performed", "frozen_headers_generated", "execution_performed", "runtime_load_protection",
    "production_admission", "general_code_origin_protection",
})


class StaticPythonBuildInputsError(ValueError):
    """A fixed refusal reason, without caller metadata or paths in its message."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_build_inputs_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonBuildInputsError(reason)


def _object(value: object, fields: frozenset[str]) -> dict[str, Any]:
    if (type(value) is not dict or len(value) != len(fields)
            or any(type(key) is not str or len(key) > 64 for key in value)
            or set(value) != fields):
        _fail("shape_invalid")
    return value


def _bounded_tree(value: object) -> None:
    """Bound JSON depth, nodes and primitive shape before serialization."""
    nodes = 0
    text_bytes = 0

    def visit(item: object, depth: int) -> None:
        nonlocal nodes, text_bytes
        nodes += 1
        if depth > 8 or nodes > 4096:
            _fail("shape_budget_exceeded")
        if type(item) is dict:
            if len(item) > 32 or any(type(key) is not str or len(key) > 64 for key in item):
                _fail("shape_invalid")
            for key, child in item.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            if len(item) > 162:
                _fail("shape_budget_exceeded")
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            if not item or len(item) > 4096:
                _fail("text_invalid")
            try:
                raw = item.encode("utf-8")
            except UnicodeError as exc:
                raise StaticPythonBuildInputsError("text_invalid") from exc
            text_bytes += len(raw)
            if len(raw) > 4096 or text_bytes > MAX_REVIEWED_BUILD_INPUTS_BYTES:
                _fail("shape_budget_exceeded")
            if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in item):
                _fail("text_invalid")
        elif type(item) is int:
            if not 0 <= item <= 8 * 1024 * 1024:
                _fail("integer_invalid")
        elif type(item) is not bool:
            _fail("shape_invalid")

    visit(value, 0)


def _sha(value: object) -> None:
    if (type(value) is not str or _SHA.fullmatch(value) is None
            or value in {"0" * 64, "f" * 64}):
        _fail("digest_invalid")


def _path(value: object) -> None:
    if type(value) is not str or not 0 < len(value) <= 1024:
        _fail("path_invalid")
    parts = value.split("/")
    if (len(parts) > 64 or any(part in {"", ".", ".."} for part in parts)
            or "\\" in value or ":" in value):
        _fail("path_invalid")


def _size(value: object) -> None:
    if type(value) is not int or not 0 < value <= 8 * 1024 * 1024:
        _fail("source_size_invalid")


def _units(value: object, count: int) -> None:
    if type(value) is not list or len(value) != count:
        _fail("unit_inventory_invalid")
    objects = set()
    for item in value:
        item = _object(item, _UNIT_FIELDS)
        for name in ("object", "source"):
            _path(item[name])
        for name in ("source_sha256", "reviewed_source_sha256"):
            _sha(item[name])
        _size(item["source_size"])
        if type(item["compile_role"]) is not str or item["compile_role"] not in {"core", "builtin"}:
            _fail("compile_role_invalid")
        if type(item["origin"]) is not str or item["origin"] not in {
            "reviewed-cpython-git-source", "fixture-asset", "installation-owned-table",
        }:
            _fail("source_origin_invalid")
        if type(item["extra_flags"]) is not list or item["extra_flags"] not in (
            [], ["-fno-strict-aliasing"],
        ):
            _fail("extra_flags_invalid")
        if item["object"] in objects:
            _fail("duplicate_object")
        objects.add(item["object"])


def _shape(value: object) -> dict[str, Any]:
    value = _object(value, _TOP_FIELDS)
    _bounded_tree(value)
    if value["schema"] != REVIEWED_BUILD_INPUTS_SCHEMA:
        _fail("schema_invalid")
    for name, count in (("shared_units", 162), ("freezer_units", 2), ("target_units", 4)):
        _units(value[name], count)
    for name, count in (("reviewed_controls", 4), ("generated_sources", 4), ("fixture_headers", 1)):
        records = value[name]
        if type(records) is not list or len(records) != count:
            _fail("control_inventory_invalid")
        for record in records:
            record = _object(record, frozenset({"path", "source_size", "sha256"}))
            _path(record["path"])
            _size(record["source_size"])
            _sha(record["sha256"])
    tasks = value["freeze_tasks"]
    if type(tasks) is not list or len(tasks) != 9:
        _fail("freeze_inventory_invalid")
    for task in tasks:
        task = _object(task, _FREEZE_FIELDS)
        _path(task["source"])
        _path(task["output"])
        _size(task["source_size"])
        _sha(task["source_sha256"])
        if type(task["package"]) is not bool:
            _fail("package_flag_invalid")
    states = _object(value["states"], _STATES)
    if any(type(item) is not bool or item is not False for item in states.values()):
        _fail("unsupported_completion_claim")
    return value


def emit_static_python_build_inputs(reviewed_inputs: bytes) -> dict[str, object]:
    """Emit a fresh fixed input plan, without observing a configured build.

    The caller supplies the installation-owned tracked file's exact bytes. This
    function checks its fixed digest and encoding, not filesystem contents or
    archive/toolchain provenance. Changes to this plan require a new reviewed
    installation policy pin rather than accepting discovered extra inputs.
    """
    if type(reviewed_inputs) is not bytes:
        _fail("bytes_invalid")
    if not 0 < len(reviewed_inputs) <= MAX_REVIEWED_BUILD_INPUTS_BYTES:
        _fail("byte_budget_exceeded")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result = {}
        for key, item in items:
            if key in result:
                _fail("duplicate_json_key")
            result[key] = item
        return result

    try:
        value = json.loads(reviewed_inputs.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: _fail("json_invalid"))
    except StaticPythonBuildInputsError:
        raise
    except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
        raise StaticPythonBuildInputsError("json_invalid") from exc
    value = _shape(value)
    canonical = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                            allow_nan=False) + "\n").encode("utf-8")
    if reviewed_inputs != canonical:
        _fail("noncanonical_json")
    if (len(reviewed_inputs) != REVIEWED_BUILD_INPUTS_BYTES
            or hashlib.sha256(reviewed_inputs).hexdigest() != REVIEWED_BUILD_INPUTS_SHA256):
        _fail("policy_pin_drift")
    value["schema"] = STATIC_PYTHON_BUILD_INPUTS_SCHEMA
    value["reviewed_inputs_sha256"] = REVIEWED_BUILD_INPUTS_SHA256
    value["reviewed_inputs_size"] = REVIEWED_BUILD_INPUTS_BYTES
    return value


__all__ = [
    "MAX_REVIEWED_BUILD_INPUTS_BYTES",
    "REVIEWED_BUILD_INPUTS_BYTES",
    "REVIEWED_BUILD_INPUTS_FILENAME",
    "REVIEWED_BUILD_INPUTS_SCHEMA",
    "REVIEWED_BUILD_INPUTS_SHA256",
    "STATIC_PYTHON_BUILD_INPUTS_SCHEMA",
    "StaticPythonBuildInputsError",
    "emit_static_python_build_inputs",
]
