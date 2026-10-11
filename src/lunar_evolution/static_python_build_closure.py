"""Pure comparison of the reviewed static-Python build-closure wire.

This module deliberately validates descriptions supplied by a caller.  It does
not read a path, invoke a compiler/freezer/linker, inspect ELF bytes, or start
an executable.  A successful result is therefore a bounded comparison DTO,
not build, runtime, or installation evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import NoReturn

BUILD_CLOSURE_SCHEMA = "lunar-static-python-build-closure-v1"
MAX_BUILD_CLOSURE_BYTES = 512 * 1024
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_INPUT_BYTES = 1024 * 1024 * 1024
_MAX_NODES = 20_000
_MAX_DEPTH = 16
_MAX_TEXT_BYTES = 256 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./+-]{0,511}\Z")
_FROZEN = (
    "_frozen_importlib", "_frozen_importlib_external", "_lunar_static_main",
    "abc", "codecs", "encodings", "encodings.aliases", "encodings.utf_8", "io",
)
_FROZEN_OUTPUTS = {
    name: f"generated-sources/Python/frozen_modules/{name}.h" for name in _FROZEN
}
_FORBIDDEN_STOCK_OBJECTS = (
    "Modules/getpath.o", "Programs/_bootstrap_python.o", "Programs/python.o", "Python/frozen.o",
)
_CLAIMS = (
    "configured_closure_verified", "compilation_performed", "freezer_performed",
    "link_performed", "artifact_verified", "runtime_execution_performed",
    "installation_accepted", "input_consumption_verified", "runtime_load_protection",
    "production_admission", "general_code_origin_protection",
)
_ELF_FIELDS = (
    "sha256", "size", "osabi", "entry_point", "program_header_count",
    "section_header_count", "load_segment_count", "executable_load_segment_count",
    "dynamic_table_count", "dynamic_entry_count", "elf_class", "byte_order", "machine",
    "elf_type", "has_pt_interp", "has_dt_needed", "runtime_load_protection",
    "general_code_origin_protection", "production_admission",
)
_TOOL_FIELDS = ("path", "version", "sha256")
_RECORD_FIELDS = frozenset(("path", "mode", "size", "sha256"))
_PIN_FIELDS = (
    "expected_contract_sha256", "expected_source_tree_sha256",
    "expected_toolchain_manifest_sha256", "expected_frozen_inventory_sha256",
    "expected_link_manifest_sha256", "expected_artifact_sha256",
)


class StaticPythonBuildClosureError(ValueError):
    """A fixed refusal code that never contains caller material or paths."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or _LABEL.fullmatch(reason) is None:
            reason = "invalid"
        self.reason = "static_python_build_closure_" + reason
        super().__init__(self.reason)


class _Refusal(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    raise _Refusal(reason)


def canonical_sha256(value: object) -> str:
    """Hash a JSON-compatible projection using the wire's canonical encoding."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise StaticPythonBuildClosureError("canonical") from exc
    return hashlib.sha256(encoded).hexdigest()


def _sha(value: object, reason: str = "digest") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value in {"0" * 64, "f" * 64}:
        _fail(reason)
    return value


def _label(value: object, reason: str = "label") -> str:
    if type(value) is not str or _LABEL.fullmatch(value) is None:
        _fail(reason)
    return value


def _path(value: object) -> str:
    if type(value) is not str or _PATH.fullmatch(value) is None or value.startswith("/"):
        _fail("path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _fail("path")
    return value


def _integer(value: object, maximum: int, minimum: int = 0, reason: str = "integer") -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(reason)
    return value


def _object(value: object, fields: frozenset[str], reason: str = "schema") -> dict:
    if type(value) is not dict or frozenset(value) != fields:
        _fail(reason)
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_key")
        result[key] = value
    return result


def _constant(_: str) -> NoReturn:
    _fail("json")


def _scan(value: object) -> None:
    nodes = text_bytes = 0
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
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
            if text_bytes > _MAX_TEXT_BYTES:
                _fail("bounds")
        elif type(item) not in (int, bool):
            _fail("json")


def _record(value: object, *, mode: bool = True) -> dict:
    item = _object(value, _RECORD_FIELDS)
    _path(item["path"])
    if mode:
        _integer(item["mode"], 0o7777)
    _integer(item["size"], MAX_INPUT_BYTES, 1)
    _sha(item["sha256"])
    return item


def _records(value: object, *, minimum: int = 1, maximum: int = 8192,
             duplicate_reason: str = "ordering") -> list[dict]:
    if type(value) is not list or not minimum <= len(value) <= maximum:
        _fail("collection")
    result = [_record(item) for item in value]
    paths = [item["path"] for item in result]
    if len(paths) != len(set(paths)):
        _fail(duplicate_reason)
    if paths != sorted(paths):
        _fail("ordering")
    return result


def _tool(value: object) -> dict:
    item = _object(value, frozenset(_TOOL_FIELDS), "toolchain")
    _path(item["path"])
    _label(item["version"])
    _sha(item["sha256"])
    return item


def _manifest_digest(value: dict, field: str) -> str:
    projection = dict(value)
    projection.pop(field, None)
    return canonical_sha256(projection)


def _validate_source(value: object, pins: dict[str, str]) -> dict:
    item = _object(value, frozenset({
        "source_tag", "source_commit", "source_git_tree", "source_archive_sha256",
        "source_tree_sha256", "patch_set_sha256", "files",
    }), "source")
    _label(item["source_tag"])
    _sha(item["source_commit"])
    _sha(item["source_git_tree"])
    for name in ("source_archive_sha256", "source_tree_sha256", "patch_set_sha256"):
        _sha(item[name])
    if item["source_tree_sha256"] != pins["expected_source_tree_sha256"]:
        _fail("source_pin")
    _records(item["files"])
    if _manifest_digest(item, "source_tree_sha256") != item["source_tree_sha256"]:
        _fail("manifest_pin")
    return item


def _validate_toolchain(value: object, pins: dict[str, str]) -> dict:
    item = _object(value, frozenset({
        "target_triple", "compiler", "linker", "archiver", "sysroot", "libc",
        "compiler_support", "manifest_sha256",
    }), "toolchain")
    _label(item["target_triple"])
    for name in ("compiler", "linker", "archiver", "sysroot", "libc", "compiler_support"):
        _tool(item[name])
    _sha(item["manifest_sha256"])
    if item["manifest_sha256"] != pins["expected_toolchain_manifest_sha256"]:
        _fail("toolchain_pin")
    if _manifest_digest(item, "manifest_sha256") != item["manifest_sha256"]:
        _fail("manifest_pin")
    return item


def _validate_frozen(value: object, pins: dict[str, str]) -> tuple[list[dict], str]:
    if type(value) is not dict:
        _fail("frozen_inventory")
    item = _object(value, frozenset({"inventory_sha256", "headers"}), "frozen_inventory")
    _sha(item["inventory_sha256"])
    headers = item["headers"]
    if type(headers) is not list or len(headers) != len(_FROZEN):
        _fail("frozen_inventory")
    seen: list[str] = []
    for header in headers:
        header = _object(header, frozenset({"generator_id", "symbol", "is_package", "source",
                                            "generated", "freezer"}), "frozen_header")
        ident = _label(header["generator_id"])
        if ident not in _FROZEN or ident in seen:
            _fail("frozen_inventory")
        seen.append(ident)
        _label(header["symbol"])
        if type(header["is_package"]) is not bool:
            _fail("frozen_header")
        _record(header["source"])
        generated = _record(header["generated"])
        if generated["path"] != _FROZEN_OUTPUTS[ident]:
            _fail("frozen_header")
        freezer = _object(header["freezer"], frozenset({"path", "recipe_sha256"}), "frozen_header")
        _path(freezer["path"])
        _sha(freezer["recipe_sha256"])
    if seen != list(_FROZEN):
        _fail("ordering")
    if item["inventory_sha256"] != pins["expected_frozen_inventory_sha256"]:
        _fail("frozen_pin")
    if _manifest_digest(item, "inventory_sha256") != item["inventory_sha256"]:
        _fail("manifest_pin")
    return headers, item["inventory_sha256"]


def _validate_link(value: object, pins: dict[str, str]) -> dict:
    fields = frozenset({
        "objects", "archives", "crt_objects", "libc_objects", "libm_objects", "compile_flags",
        "link_flags", "generated_config", "module_config", "link_map", "excluded_stock_objects",
        "manifest_sha256",
    })
    item = _object(value, fields, "link_closure")
    all_records: list[dict] = []
    for name in ("objects", "archives", "crt_objects", "libc_objects", "libm_objects"):
        all_records.extend(_records(item[name], maximum=16384, duplicate_reason="duplicate_object"))
    paths = [record["path"] for record in all_records]
    if len(paths) != len(set(paths)):
        _fail("duplicate_object")
    for name in ("compile_flags", "link_flags"):
        flags = item[name]
        if type(flags) is not list or not 0 <= len(flags) <= 512:
            _fail("flags")
        if any(type(flag) is not str or not flag or len(flag) > 4096 for flag in flags):
            _fail("flags")
    for name in ("generated_config", "module_config", "link_map"):
        _record(item[name])
    excluded = item["excluded_stock_objects"]
    if type(excluded) is not list or excluded != list(_FORBIDDEN_STOCK_OBJECTS):
        _fail("stock_objects")
    if any(path in _FORBIDDEN_STOCK_OBJECTS for path in paths):
        _fail("stock_objects")
    _sha(item["manifest_sha256"])
    if item["manifest_sha256"] != pins["expected_link_manifest_sha256"]:
        _fail("link_pin")
    if _manifest_digest(item, "manifest_sha256") != item["manifest_sha256"]:
        _fail("manifest_pin")
    return item


def _validate_elf(value: object, pins: dict[str, str]) -> dict:
    item = _object(value, frozenset((*_ELF_FIELDS, "artifact_sha256", "artifact_size")), "elf")
    _sha(item["artifact_sha256"])
    _integer(item["artifact_size"], MAX_ARTIFACT_BYTES, 1)
    if item["artifact_sha256"] != pins["expected_artifact_sha256"]:
        _fail("artifact_pin")
    for name in _ELF_FIELDS:
        expected_type = bool if name.startswith("has_") or name.endswith("protection") \
            or name == "production_admission" else int if name in {
                "size", "osabi", "entry_point", "program_header_count", "section_header_count",
                "load_segment_count", "executable_load_segment_count", "dynamic_table_count",
                "dynamic_entry_count", "elf_class",
            } else str
        if type(item[name]) is not expected_type:
            _fail("elf")
    if item["size"] != item["artifact_size"] or item["size"] > MAX_ARTIFACT_BYTES:
        _fail("elf")
    if item["has_pt_interp"] or item["has_dt_needed"]:
        _fail("elf")
    if any(item[name] is not False for name in (
        "runtime_load_protection", "general_code_origin_protection", "production_admission",
    )):
        _fail("claims")
    return item


def _cross_check_f01(raw: bytes, closure: dict, expected_version: str) -> None:
    if type(raw) is not bytes or not 0 < len(raw) <= 384 * 1024:
        _fail("installation_descriptor")
    try:
        descriptor_top = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                                    parse_float=_constant, parse_constant=_constant)
    except (UnicodeError, ValueError, RecursionError):
        _fail("installation_descriptor")
    _scan(descriptor_top)
    if not isinstance(descriptor_top, dict):
        _fail("installation_descriptor")
    descriptor = descriptor_top.get("descriptor", descriptor_top)
    if type(descriptor) is not dict or descriptor.get("installation_version") != expected_version:
        _fail("installation_descriptor")
    source = closure["source_identity"]
    if any(descriptor.get(name) != source.get(name) for name in (
        "source_tree_sha256", "source_archive_sha256",
    )):
        _fail("cross_field")
    elf = closure["elf"]
    if descriptor.get("artifact_sha256") != elf["artifact_sha256"] \
            or descriptor.get("artifact_size") != elf["artifact_size"]:
        _fail("cross_field")
    declared_elf = descriptor.get("elf_profile")
    if type(declared_elf) is not dict or any(declared_elf.get(name) != elf.get(name) for name in _ELF_FIELDS):
        _fail("cross_field")
    declared_headers = {item.get("name"): item for item in descriptor.get("frozen_modules", [])}
    for header in closure["frozen_headers"]["headers"]:
        declared = declared_headers.get(header["generator_id"])
        if type(declared) is not dict:
            _fail("cross_field")
        for key in ("source", "generated"):
            actual = header[key]
            expected = declared.get(key)
            if type(expected) is not dict or any(expected.get(field) != actual.get(field)
                                                for field in ("path", "size", "sha256")):
                _fail("cross_field")
    declared_links = descriptor.get("recipe", {}).get("link_inputs")
    if type(declared_links) is not list:
        _fail("cross_field")
    declared_paths = {record.get("path") for record in declared_links if type(record) is dict}
    if any(record["path"] not in declared_paths for name in (
        "objects", "archives", "crt_objects", "libc_objects", "libm_objects",
    ) for record in closure["link_closure"][name]):
        _fail("cross_field")


@dataclass(frozen=True, slots=True)
class StaticPythonBuildClosure:
    """Detached closure evidence; no field grants build or runtime authority."""

    canonical_bytes: bytes
    contract_sha256: str
    source_tree_sha256: str
    toolchain_manifest_sha256: str
    frozen_inventory_sha256: str
    link_manifest_sha256: str
    artifact_sha256: str
    installation_version: str
    frozen_slots: tuple[str, ...]

    def to_json(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict:
        return json.loads(self.canonical_bytes)


def parse_static_python_build_closure(
    raw: bytes, *, expected_contract_sha256: str, expected_source_tree_sha256: str,
    expected_toolchain_manifest_sha256: str, expected_frozen_inventory_sha256: str,
    expected_link_manifest_sha256: str, expected_artifact_sha256: str,
    expected_installation_version: str, installation_descriptor_raw: bytes,
) -> StaticPythonBuildClosure:
    """Validate one canonical closure and compare it with an F01 descriptor.

    Every input is caller-owned bytes.  This function performs no filesystem,
    process, network, environment, compiler, freezer, linker, or ELF operation.
    """
    reason = "invalid"
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_BUILD_CLOSURE_BYTES:
            _fail("raw")
        if type(expected_installation_version) is not str or not _LABEL.fullmatch(expected_installation_version):
            _fail("pin")
        pins = {
            "expected_contract_sha256": expected_contract_sha256,
            "expected_source_tree_sha256": expected_source_tree_sha256,
            "expected_toolchain_manifest_sha256": expected_toolchain_manifest_sha256,
            "expected_frozen_inventory_sha256": expected_frozen_inventory_sha256,
            "expected_link_manifest_sha256": expected_link_manifest_sha256,
            "expected_artifact_sha256": expected_artifact_sha256,
        }
        for name in _PIN_FIELDS:
            _sha(pins[name], "pin")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                             parse_float=_constant, parse_constant=_constant)
        _scan(payload)
        if type(payload) is not dict or frozenset(payload) != frozenset({
            "schema", "installation_version", "source_identity", "toolchain_identity",
            "frozen_headers", "link_closure", "elf", "claims",
        }):
            _fail("schema")
        if payload["schema"] != BUILD_CLOSURE_SCHEMA or payload["installation_version"] != expected_installation_version:
            _fail("schema")
        if json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8") != raw:
            _fail("canonical")
        if hashlib.sha256(raw).hexdigest() != expected_contract_sha256:
            _fail("contract_pin")
        _validate_source(payload["source_identity"], pins)
        _validate_toolchain(payload["toolchain_identity"], pins)
        _validate_frozen(payload["frozen_headers"], pins)
        _validate_link(payload["link_closure"], pins)
        _validate_elf(payload["elf"], pins)
        claims = _object(payload["claims"], frozenset(_CLAIMS), "claims")
        if any(value is not False for value in claims.values()):
            _fail("claims")
        _cross_check_f01(installation_descriptor_raw, payload, expected_installation_version)
        canonical = raw
        return StaticPythonBuildClosure(
            canonical, expected_contract_sha256, pins["expected_source_tree_sha256"],
            pins["expected_toolchain_manifest_sha256"], pins["expected_frozen_inventory_sha256"],
            pins["expected_link_manifest_sha256"], pins["expected_artifact_sha256"],
            expected_installation_version, tuple(_FROZEN),
        )
    except _Refusal as exc:
        reason = exc.reason
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        reason = "json"
    raise StaticPythonBuildClosureError(reason)


__all__ = [
    "BUILD_CLOSURE_SCHEMA", "MAX_BUILD_CLOSURE_BYTES", "StaticPythonBuildClosure",
    "StaticPythonBuildClosureError", "canonical_sha256", "parse_static_python_build_closure",
]
