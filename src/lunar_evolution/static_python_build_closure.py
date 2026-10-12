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

from lunar_evolution.static_python_rsi_installation import (
    MAX_CONTRACT_BYTES as MAX_INSTALLATION_CONTRACT_BYTES,
)
from lunar_evolution.static_python_rsi_installation import (
    StaticPythonRSIInstallationError,
    parse_static_python_rsi_installation_descriptor,
)

BUILD_CLOSURE_SCHEMA = "lunar-static-python-build-closure-v1"
MAX_BUILD_CLOSURE_BYTES = 512 * 1024
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_INPUT_BYTES = 1024 * 1024 * 1024
_MAX_NODES = 20_000
_MAX_DEPTH = 16
_MAX_TEXT_BYTES = 256 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_GIT_ID = re.compile(r"[0-9a-f]{40}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./+-]{0,511}\Z")
_FROZEN = (
    "_frozen_importlib", "_frozen_importlib_external", "_lunar_static_main",
    "abc", "codecs", "encodings", "encodings.aliases", "encodings.utf_8", "io",
)
_FREEZE_TASKS = {
    "_frozen_importlib": ("importlib._bootstrap", "_Py_M__importlib__bootstrap", False),
    "_frozen_importlib_external": (
        "importlib._bootstrap_external", "_Py_M__importlib__bootstrap_external", False,
    ),
    "_lunar_static_main": ("_lunar_static_main", "_Py_M___lunar_static_main", False),
    "abc": ("abc", "_Py_M__abc", False),
    "codecs": ("codecs", "_Py_M__codecs", False),
    "encodings": ("encodings", "_Py_M__encodings", True),
    "encodings.aliases": ("encodings.aliases", "_Py_M__encodings_aliases", False),
    "encodings.utf_8": ("encodings.utf_8", "_Py_M__encodings_utf_8", False),
    "io": ("io", "_Py_M__io", False),
}
_GENERATOR_NAMES = {task[0]: name for name, task in _FREEZE_TASKS.items()}
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
    "expected_installation_contract_sha256", "expected_installation_descriptor_sha256",
    "expected_installation_frozen_inventory_sha256", "expected_main_header_sha256",
)
_REASONS = frozenset({
    "invalid", "canonical", "digest", "label", "path", "integer", "schema",
    "duplicate_key", "json", "bounds", "collection", "ordering", "toolchain",
    "source", "source_pin", "manifest_pin", "toolchain_pin", "frozen_inventory",
    "frozen_header", "frozen_pin", "link_closure", "duplicate_object", "flags",
    "stock_objects", "link_pin", "elf", "artifact_pin", "claims",
    "installation_descriptor", "cross_field", "raw", "pin", "contract_pin",
})


class StaticPythonBuildClosureError(ValueError):
    """A fixed refusal code that never contains caller material or paths."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or reason not in _REASONS:
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
    """Hash a bounded exact-built-in projection using the wire's encoding."""
    try:
        _scan(value)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        pass
    # Suppressing chaining inside a handler still leaves __context__ available.
    raise StaticPythonBuildClosureError("canonical")


def _sha(value: object, reason: str = "digest") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value in {"0" * 64, "f" * 64}:
        _fail(reason)
    return value


def _label(value: object, reason: str = "label") -> str:
    if type(value) is not str or _LABEL.fullmatch(value) is None:
        _fail(reason)
    return value


def _git_id(value: object) -> str:
    if (type(value) is not str or _GIT_ID.fullmatch(value) is None
            or value in {"0" * 40, "f" * 40}):
        _fail("source")
    return value


def _same_typed(value: object, expected: object) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            _same_typed(value[key], item) for key, item in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _same_typed(left, right) for left, right in zip(value, expected, strict=True)
        )
    return value == expected


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
            if len(item) > _MAX_NODES:
                _fail("bounds")
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif type(item) is list:
            if len(item) > _MAX_NODES:
                _fail("bounds")
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            if len(item) > _MAX_TEXT_BYTES - text_bytes:
                _fail("bounds")
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
    _git_id(item["source_commit"])
    _git_id(item["source_git_tree"])
    for name in ("source_archive_sha256", "source_tree_sha256", "patch_set_sha256"):
        _sha(item[name])
    if item["source_tree_sha256"] != pins["expected_source_tree_sha256"]:
        _fail("source_pin")
    _records(item["files"])
    # This is the independently pinned source-tree digest also present in F01,
    # not a self-referential digest of this evidence projection. The complete
    # projection is already covered by expected_contract_sha256.
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
        name = _GENERATOR_NAMES.get(ident)
        if name is None or name in seen:
            _fail("frozen_inventory")
        seen.append(name)
        _, symbol, package = _FREEZE_TASKS[name]
        if not _same_typed(header["symbol"], symbol) or not _same_typed(header["is_package"], package):
            _fail("frozen_header")
        _record(header["source"])
        generated = _record(header["generated"])
        if generated["path"] != f"generated-sources/Python/frozen_modules/{ident}.h":
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
    fixed = {
        "sha256": item["artifact_sha256"], "size": item["artifact_size"],
        "elf_class": 64, "byte_order": "little", "machine": "x86_64", "elf_type": "ET_EXEC",
    }
    if any(not _same_typed(item[name], expected) for name, expected in fixed.items()):
        _fail("elf")
    if item["osabi"] not in (0, 3):
        _fail("elf")
    _integer(item["entry_point"], 2**64 - 1, 1, "elf")
    ph = _integer(item["program_header_count"], 256, 1, "elf")
    _integer(item["section_header_count"], 4096, reason="elf")
    loads = _integer(item["load_segment_count"], ph, 1, "elf")
    _integer(item["executable_load_segment_count"], loads, 1, "elf")
    tables = _integer(item["dynamic_table_count"], 4096 + 256, reason="elf")
    entries = _integer(item["dynamic_entry_count"], 4096, 1 if tables else 0, "elf")
    if not tables and entries:
        _fail("elf")
    if item["has_pt_interp"] or item["has_dt_needed"]:
        _fail("elf")
    if any(item[name] is not False for name in (
        "runtime_load_protection", "general_code_origin_protection", "production_admission",
    )):
        _fail("claims")
    return item


def _cross_check_f01(descriptor: dict, closure: dict) -> None:
    # Only a complete canonical wrapper that has passed the F01 parser reaches
    # this comparison. No caller digest is derived from unverified metadata.
    source = closure["source_identity"]
    if any(not _same_typed(descriptor["source_provenance"][name], source[name]) for name in (
        "source_tag", "source_commit", "source_git_tree", "source_tree_sha256", "source_archive_sha256",
    )):
        _fail("cross_field")
    if not _same_typed(descriptor["patch_set_sha256"], source["patch_set_sha256"]):
        _fail("cross_field")
    elf = closure["elf"]
    if not _same_typed(descriptor["artifact_sha256"], elf["artifact_sha256"]) \
            or not _same_typed(descriptor["artifact_size"], elf["artifact_size"]):
        _fail("cross_field")
    if not _same_typed(descriptor["elf_profile"], {name: elf[name] for name in _ELF_FIELDS}):
        _fail("cross_field")
    declared_headers = {item["name"]: item for item in descriptor["frozen_modules"]}
    for header in closure["frozen_headers"]["headers"]:
        declared = declared_headers[_GENERATOR_NAMES[header["generator_id"]]]
        if not _same_typed(declared["is_package"], header["is_package"]):
            _fail("cross_field")
        for key in ("source", "generated"):
            actual = header[key]
            if not _same_typed(declared[key], {field: actual[field] for field in ("path", "size", "sha256")}):
                _fail("cross_field")
    declared_paths = {record["path"] for record in descriptor["recipe"]["link_inputs"]}
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
    expected_installation_contract_sha256: str, expected_installation_descriptor_sha256: str,
    expected_installation_frozen_inventory_sha256: str, expected_main_header_sha256: str,
) -> StaticPythonBuildClosure:
    """Validate one canonical closure and compare it with an F01 descriptor.

    Every input is caller-owned bytes.  This function performs no filesystem,
    process, network, environment, compiler, freezer, linker, or ELF operation.
    """
    reason = "invalid"
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_BUILD_CLOSURE_BYTES:
            _fail("raw")
        if (type(installation_descriptor_raw) is not bytes
                or not 0 < len(installation_descriptor_raw) <= MAX_INSTALLATION_CONTRACT_BYTES):
            _fail("installation_descriptor")
        if type(expected_installation_version) is not str or not _LABEL.fullmatch(expected_installation_version):
            _fail("pin")
        pins = {
            "expected_contract_sha256": expected_contract_sha256,
            "expected_source_tree_sha256": expected_source_tree_sha256,
            "expected_toolchain_manifest_sha256": expected_toolchain_manifest_sha256,
            "expected_frozen_inventory_sha256": expected_frozen_inventory_sha256,
            "expected_link_manifest_sha256": expected_link_manifest_sha256,
            "expected_artifact_sha256": expected_artifact_sha256,
            "expected_installation_contract_sha256": expected_installation_contract_sha256,
            "expected_installation_descriptor_sha256": expected_installation_descriptor_sha256,
            "expected_installation_frozen_inventory_sha256": expected_installation_frozen_inventory_sha256,
            "expected_main_header_sha256": expected_main_header_sha256,
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
        installation = parse_static_python_rsi_installation_descriptor(
            installation_descriptor_raw,
            expected_contract_sha256=expected_installation_contract_sha256,
            expected_descriptor_sha256=expected_installation_descriptor_sha256,
            expected_installation_version=expected_installation_version,
            expected_artifact_sha256=expected_artifact_sha256,
            expected_frozen_inventory_sha256=expected_installation_frozen_inventory_sha256,
            expected_main_header_sha256=expected_main_header_sha256,
        )
        _cross_check_f01(installation.to_dict()["descriptor"], payload)
        canonical = raw
        return StaticPythonBuildClosure(
            canonical, expected_contract_sha256, pins["expected_source_tree_sha256"],
            pins["expected_toolchain_manifest_sha256"], pins["expected_frozen_inventory_sha256"],
            pins["expected_link_manifest_sha256"], pins["expected_artifact_sha256"],
            expected_installation_version, tuple(_FROZEN),
        )
    except _Refusal as exc:
        reason = exc.reason
    except StaticPythonRSIInstallationError:
        reason = "installation_descriptor"
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        reason = "json"
    raise StaticPythonBuildClosureError(reason)


__all__ = [
    "BUILD_CLOSURE_SCHEMA", "MAX_BUILD_CLOSURE_BYTES", "StaticPythonBuildClosure",
    "StaticPythonBuildClosureError", "canonical_sha256", "parse_static_python_build_closure",
]
