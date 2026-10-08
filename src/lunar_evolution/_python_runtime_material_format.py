"""Pure bounded framing for sealed material; no live ownership or filesystem IO."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass
from typing import Any, NoReturn

from . import producer_python_runtime as declared
from . import producer_python_runtime_tree as closed

PROTOCOL = "lunar-python-runtime-sealed-material-v1"
SCOPE = "sealed-runtime-material-only"
BINDING = "linux-sealed-material-memfd-v1"
MAGIC = b"LUNARPYMAT" + b"\x00" * 5 + b"\x01"
HEADER_SIZE = 32
_HEADER = struct.Struct(">16sQQ")
MAX_ROOTS = 16
MAX_FILES = 4096
MAX_ENTRIES = 8192
MAX_MEMBERSHIP_EDGES = 8192
MAX_DEPTH = 64
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_PAYLOAD_BYTES = 1024 * 1024 * 1024
MAX_TABLE_BYTES = 8 * 1024 * 1024
MAX_DESCRIPTOR_BYTES = 16 * 1024
MAX_FRAME_BYTES = HEADER_SIZE + MAX_TABLE_BYTES + MAX_PAYLOAD_BYTES
MAX_PATH_BYTES = 4096
MAX_LABEL_LENGTH = 128
_TARGET_LIMITS = {"platform": 6, "architecture": 7, "python_version": 4, "abi_tag": 5, "layout": 13}
_CAPABILITIES = (
    "execution_performed",
    "runtime_load_protection",
    "production_admission",
    "archive_contents_complete",
    "loader_dependencies_complete",
)
_TABLE_FIELDS = {
    "schema_version",
    "protocol",
    "material_version",
    "declared_manifest_sha256",
    "tree_sha256",
    "target",
    "roots",
    "directories",
    "files",
}
_DIRECTORY_FIELDS = {"root_label", "relative_path", "children"}
_FILE_FIELDS = {"root_label", "relative_path", "role", "size", "offset", "sha256"}
_DESCRIPTOR_FIELDS = {
    "schema_version",
    "protocol",
    "scope",
    "binding",
    "material_version",
    "target",
    "declared_manifest_sha256",
    "tree_sha256",
    "table_sha256",
    "table_size",
    "payload_sha256",
    "payload_size",
    "frame_sha256",
    "frame_size",
    "root_count",
    "file_count",
    "directory_count",
    *_CAPABILITIES,
}


class PythonRuntimeMaterialError(ValueError):
    """Fixed refusal code, never including caller paths or values."""

    def __init__(self, code: str) -> None:
        if (
            type(code) is not str
            or len(code) > 64
            or re.fullmatch(r"[a-z][a-z0-9_]*", code) is None
        ):
            code = "invalid"
        self.code = "python_runtime_material_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise PythonRuntimeMaterialError(code)


def _text(value: object, maximum: int) -> str:
    if type(value) is not str or len(value) > maximum:
        _fail("text_invalid")
    return value


def _label(value: object) -> str:
    text = _text(value, MAX_LABEL_LENGTH)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", text) is None:
        _fail("label_invalid")
    return text


def _sha(value: object) -> str:
    text = _text(value, 64)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        _fail("digest_invalid")
    return text


def _integer(value: object, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("integer_invalid")
    return value


def _relative(value: object, *, root: bool = False, child: bool = False) -> str:
    text = _text(value, MAX_PATH_BYTES)
    if not text or any(char in text for char in "\x00\r\n\\"):
        _fail("path_invalid")
    try:
        if len(text.encode("utf-8")) > MAX_PATH_BYTES:
            _fail("path_invalid")
    except UnicodeError:
        _fail("path_invalid")
    if root and text == ".":
        return text
    parts = text.split("/")
    if (
        any(part in ("", ".", "..") for part in parts)
        or len(parts) > MAX_DEPTH
        or (child and len(parts) != 1)
    ):
        _fail("path_invalid")
    return text


def _target(value: object) -> declared.PythonRuntimeTarget:
    if type(value) is not declared.PythonRuntimeTarget:
        _fail("target_invalid")
    for field, maximum in _TARGET_LIMITS.items():
        _text(getattr(value, field), maximum)
    try:
        value.__post_init__()
    except declared.PythonRuntimeError:
        _fail("target_invalid")
    return value


def _target_dict(value: declared.PythonRuntimeTarget) -> dict[str, str]:
    return {field: getattr(value, field) for field in _TARGET_LIMITS}


def _target_from_dict(value: object) -> declared.PythonRuntimeTarget:
    fields = _object(value, set(_TARGET_LIMITS))
    for field, maximum in _TARGET_LIMITS.items():
        _text(fields[field], maximum)
    try:
        return declared.PythonRuntimeTarget(**fields)
    except declared.PythonRuntimeError as exc:
        raise PythonRuntimeMaterialError("target_invalid") from exc


def _tuple(value: object, maximum: int, *, empty: bool = False) -> tuple:
    if type(value) is not tuple or not (0 if empty else 1) <= len(value) <= maximum:
        _fail("collection_invalid")
    return value


def _object(value: object, fields: set[str]) -> dict:
    if type(value) is not dict or len(value) != len(fields):
        _fail("schema_invalid")
    if any(type(key) is not str or len(key) > 64 for key in value) or set(value) != fields:
        _fail("schema_invalid")
    return value


def _list(value: object, maximum: int, *, empty: bool = False) -> list:
    if type(value) is not list or not (0 if empty else 1) <= len(value) <= maximum:
        _fail("collection_invalid")
    return value


def _canonical(value: object, maximum: int) -> bytes:
    try:
        encoder = json.JSONEncoder(
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        chunks, size = [], 0
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("utf-8")
            size += len(encoded)
            if size > maximum:
                _fail("json_too_large")
            chunks.append(encoded)
        return b"".join(chunks)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, PythonRuntimeMaterialError):
            raise
        raise PythonRuntimeMaterialError("json_invalid") from exc


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_json_key")
        result[key] = value
    return result


def _constant(_value: str) -> NoReturn:
    _fail("json_invalid")


def _decode(value: object, maximum: int, *, text: bool = False) -> tuple[object, bytes]:
    if type(value) is not bytes and not (text and type(value) is str):
        _fail("json_invalid")
    if len(value) > maximum:
        _fail("json_too_large")
    try:
        raw = value.encode("utf-8") if type(value) is str else value
        if len(raw) > maximum:
            _fail("json_too_large")
        decoded = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        return decoded, raw
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, PythonRuntimeMaterialError):
            raise
        raise PythonRuntimeMaterialError("json_invalid") from exc


@dataclass(frozen=True, slots=True)
class MaterialDirectory:
    root_label: str
    relative_path: str
    children: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self) is not MaterialDirectory:
            _fail("directory_invalid")
        _label(self.root_label)
        _relative(self.relative_path, root=True)
        for name in _tuple(self.children, MAX_MEMBERSHIP_EDGES, empty=True):
            _relative(name, child=True)
        if self.children != tuple(sorted(set(self.children))):
            _fail("membership_invalid")

    def to_dict(self) -> dict:
        MaterialDirectory.__post_init__(self)
        return {
            "root_label": self.root_label,
            "relative_path": self.relative_path,
            "children": list(self.children),
        }


@dataclass(frozen=True, slots=True)
class MaterialFile:
    root_label: str
    relative_path: str
    role: str
    size: int
    offset: int
    sha256: str

    def __post_init__(self) -> None:
        if type(self) is not MaterialFile:
            _fail("file_invalid")
        _label(self.root_label)
        _relative(self.relative_path)
        role = _text(self.role, max(map(len, declared._ROLE_SLOTS)))
        if role not in declared._ROLE_SLOTS:
            _fail("role_invalid")
        _integer(self.size, MAX_FILE_BYTES)
        _integer(self.offset, MAX_PAYLOAD_BYTES)
        _sha(self.sha256)

    def to_dict(self) -> dict:
        MaterialFile.__post_init__(self)
        return {field: getattr(self, field) for field in _FILE_FIELDS}


@dataclass(frozen=True, slots=True)
class MaterialTable:
    material_version: str
    declared_manifest_sha256: str
    tree_sha256: str
    target: declared.PythonRuntimeTarget
    roots: tuple[str, ...]
    directories: tuple[MaterialDirectory, ...]
    files: tuple[MaterialFile, ...]

    def __post_init__(self) -> None:
        _validate_table(self)

    @property
    def payload_size(self) -> int:
        _validate_table(self)
        return sum(item.size for item in self.files)

    def to_dict(self) -> dict:
        _validate_table(self)
        return {
            "schema_version": "1",
            "protocol": PROTOCOL,
            "material_version": self.material_version,
            "declared_manifest_sha256": self.declared_manifest_sha256,
            "tree_sha256": self.tree_sha256,
            "target": _target_dict(self.target),
            "roots": list(self.roots),
            "directories": [item.to_dict() for item in self.directories],
            "files": [item.to_dict() for item in self.files],
        }

    def to_json(self) -> bytes:
        _validate_table(self)
        return _canonical(self.to_dict(), MAX_TABLE_BYTES)


def _validate_table(value: MaterialTable) -> None:
    if type(value) is not MaterialTable:
        _fail("table_invalid")
    roots = _tuple(value.roots, MAX_ROOTS)
    directories = _tuple(value.directories, MAX_ENTRIES)
    files = _tuple(value.files, MAX_FILES)
    if len(directories) + len(files) > MAX_ENTRIES:
        _fail("entries_exceeded")
    edges = 0
    for item in directories:
        if type(item) is not MaterialDirectory:
            _fail("directory_invalid")
        edges += len(_tuple(item.children, MAX_MEMBERSHIP_EDGES, empty=True))
        if edges > MAX_MEMBERSHIP_EDGES:
            _fail("entries_exceeded")
    if any(type(item) is not MaterialFile for item in files):
        _fail("file_invalid")
    _label(value.material_version)
    _sha(value.declared_manifest_sha256)
    _sha(value.tree_sha256)
    _target(value.target)
    for label in roots:
        _label(label)
    for item in (*directories, *files):
        item.__post_init__()
    if roots != tuple(sorted(set(roots))):
        _fail("roots_not_canonical")
    keys = [(item.root_label, item.relative_path) for item in directories]
    file_keys = [(item.root_label, item.relative_path) for item in files]
    if keys != sorted(set(keys)) or file_keys != sorted(set(file_keys)):
        _fail("entries_not_canonical")
    if set(keys) & set(file_keys) or any(
        label not in roots for label, _path in (*keys, *file_keys)
    ):
        _fail("graph_invalid")
    children = {key: set() for key in keys}
    if {(label, ".") for label in roots} - set(keys):
        _fail("graph_invalid")
    for label, path in (*keys, *file_keys):
        if path == ".":
            continue
        parent, _separator, name = path.rpartition("/")
        key = label, parent or "."
        if key not in children:
            _fail("graph_invalid")
        children[key].add(name)
    for item in directories:
        if item.children != tuple(sorted(children[item.root_label, item.relative_path])):
            _fail("membership_invalid")
    offset = 0
    for item in files:
        if item.offset != offset:
            _fail("offset_invalid")
        offset += item.size
        if offset > MAX_PAYLOAD_BYTES:
            _fail("payload_too_large")


def table_from_tree(
    original: closed.PythonRuntimeTreeManifest, material_version: str
) -> MaterialTable:
    """Pure conversion of the original validated DTO, never source discovery."""
    _label(material_version)
    if type(original) is not closed.PythonRuntimeTreeManifest:
        _fail("source_shape_invalid")
    try:
        original.__post_init__()
    except (
        closed.PythonRuntimeTreeError,
        declared.PythonRuntimeError,
        TypeError,
        ValueError,
        AttributeError,
        UnicodeError,
        OverflowError,
        RecursionError,
    ) as exc:
        raise PythonRuntimeMaterialError("source_shape_invalid") from exc
    target = declared.PythonRuntimeTarget(
        **_target_dict(_target(original.declared_manifest.target))
    )
    directories = tuple(
        MaterialDirectory(item.root_label, item.relative_path, item.children)
        for item in original.directories
    )
    files, offset = [], 0
    for item in original.declared_manifest.files:
        files.append(
            MaterialFile(
                item.root_label, item.relative_path, item.role, item.size, offset, item.sha256
            )
        )
        offset += item.size
    return MaterialTable(
        material_version,
        original.declared_manifest.manifest_sha256,
        original.tree_sha256,
        target,
        tuple(root.label for root in original.declared_manifest.roots),
        directories,
        tuple(files),
    )


def parse_table(value: bytes) -> MaterialTable:
    payload, raw = _decode(value, MAX_TABLE_BYTES)
    body = _object(payload, _TABLE_FIELDS)
    if (
        type(body["schema_version"]) is not str
        or body["schema_version"] != "1"
        or type(body["protocol"]) is not str
        or body["protocol"] != PROTOCOL
    ):
        _fail("schema_invalid")
    roots = _list(body["roots"], MAX_ROOTS)
    directories = _list(body["directories"], MAX_ENTRIES)
    files = _list(body["files"], MAX_FILES)
    if len(directories) + len(files) > MAX_ENTRIES:
        _fail("entries_exceeded")
    edges = 0
    for item in directories:
        _object(item, _DIRECTORY_FIELDS)
        edges += len(_list(item["children"], MAX_MEMBERSHIP_EDGES, empty=True))
        if edges > MAX_MEMBERSHIP_EDGES:
            _fail("entries_exceeded")
    try:
        target = _target_from_dict(body["target"])
        result = MaterialTable(
            body["material_version"],
            body["declared_manifest_sha256"],
            body["tree_sha256"],
            target,
            tuple(roots),
            tuple(
                MaterialDirectory(**{**item, "children": tuple(item["children"])})
                for item in directories
            ),
            tuple(MaterialFile(**_object(item, _FILE_FIELDS)) for item in files),
        )
    except declared.PythonRuntimeError as exc:
        raise PythonRuntimeMaterialError("target_invalid") from exc
    if result.to_json() != raw:
        _fail("json_not_canonical")
    return result


def pack_header(table_size: int, payload_size: int) -> bytes:
    _integer(table_size, MAX_TABLE_BYTES, 1)
    _integer(payload_size, MAX_PAYLOAD_BYTES)
    return _HEADER.pack(MAGIC, table_size, payload_size)


def unpack_header(header: bytes, total_size: int) -> tuple[int, int]:
    if type(header) is not bytes or len(header) != HEADER_SIZE:
        _fail("header_invalid")
    _integer(total_size, MAX_FRAME_BYTES, HEADER_SIZE + 1)
    magic, table_size, payload_size = _HEADER.unpack(header)
    if magic != MAGIC:
        _fail("header_invalid")
    pack_header(table_size, payload_size)
    if total_size != HEADER_SIZE + table_size + payload_size:
        _fail("frame_size_invalid")
    return table_size, payload_size


@dataclass(frozen=True, slots=True)
class PythonRuntimeMaterialDescriptor:
    material_version: str
    declared_manifest_sha256: str
    tree_sha256: str
    target: declared.PythonRuntimeTarget
    table_sha256: str
    table_size: int
    payload_sha256: str
    payload_size: int
    frame_sha256: str
    frame_size: int
    root_count: int
    file_count: int
    directory_count: int
    schema_version: str = "1"
    protocol: str = PROTOCOL
    scope: str = SCOPE
    binding: str = BINDING
    execution_performed: bool = False
    runtime_load_protection: bool = False
    production_admission: bool = False
    archive_contents_complete: bool = False
    loader_dependencies_complete: bool = False

    def __post_init__(self) -> None:
        if type(self) is not PythonRuntimeMaterialDescriptor:
            _fail("descriptor_invalid")
        for field, expected in (
            ("schema_version", "1"),
            ("protocol", PROTOCOL),
            ("scope", SCOPE),
            ("binding", BINDING),
        ):
            value = _text(getattr(self, field), len(expected))
            if value != expected:
                _fail("schema_invalid")
        if any(getattr(self, field) is not False for field in _CAPABILITIES):
            _fail("capability_invalid")
        _label(self.material_version)
        _target(self.target)
        for field in (
            "declared_manifest_sha256",
            "tree_sha256",
            "table_sha256",
            "payload_sha256",
            "frame_sha256",
        ):
            _sha(getattr(self, field))
        _integer(self.table_size, MAX_TABLE_BYTES, 1)
        _integer(self.payload_size, MAX_PAYLOAD_BYTES)
        _integer(self.frame_size, MAX_FRAME_BYTES, HEADER_SIZE + 1)
        _integer(self.root_count, MAX_ROOTS, 1)
        _integer(self.file_count, MAX_FILES, 1)
        _integer(self.directory_count, MAX_ENTRIES, 1)
        if (
            self.frame_size != HEADER_SIZE + self.table_size + self.payload_size
            or self.file_count + self.directory_count > MAX_ENTRIES
            or self.directory_count < self.root_count
            or self.payload_size > self.file_count * MAX_FILE_BYTES
        ):
            _fail("descriptor_inconsistent")

    def to_dict(self) -> dict:
        PythonRuntimeMaterialDescriptor.__post_init__(self)
        result = {field: getattr(self, field) for field in _DESCRIPTOR_FIELDS}
        result["target"] = _target_dict(self.target)
        return result

    def to_json(self) -> bytes:
        PythonRuntimeMaterialDescriptor.__post_init__(self)
        return _canonical(self.to_dict(), MAX_DESCRIPTOR_BYTES)


def descriptor_from_table(
    table: MaterialTable,
    table_size: int,
    table_sha256: str,
    payload_sha256: str,
    frame_sha256: str,
) -> PythonRuntimeMaterialDescriptor:
    _validate_table(table)
    _integer(table_size, MAX_TABLE_BYTES, 1)
    for digest in (table_sha256, payload_sha256, frame_sha256):
        _sha(digest)
    raw = table.to_json()
    if len(raw) != table_size or hashlib.sha256(raw).hexdigest() != table_sha256:
        _fail("table_binding_invalid")
    return PythonRuntimeMaterialDescriptor(
        table.material_version,
        table.declared_manifest_sha256,
        table.tree_sha256,
        declared.PythonRuntimeTarget(**_target_dict(table.target)),
        table_sha256,
        table_size,
        payload_sha256,
        table.payload_size,
        frame_sha256,
        HEADER_SIZE + table_size + table.payload_size,
        len(table.roots),
        len(table.files),
        len(table.directories),
    )


def parse_python_runtime_material_descriptor(value: bytes | str) -> PythonRuntimeMaterialDescriptor:
    payload, raw = _decode(value, MAX_DESCRIPTOR_BYTES, text=True)
    body = _object(payload, _DESCRIPTOR_FIELDS)
    try:
        target = _target_from_dict(body["target"])
        result = PythonRuntimeMaterialDescriptor(**{**body, "target": target})
    except declared.PythonRuntimeError as exc:
        raise PythonRuntimeMaterialError("target_invalid") from exc
    if result.to_json() != raw:
        _fail("json_not_canonical")
    return result
