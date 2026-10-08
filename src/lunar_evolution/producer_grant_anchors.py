"""Live host-owned original grant objects, without native execution authority.

This independent API does not change formal producer launching. Its detached manifest
is an observation, never a replacement for live FDs or a native enforcement receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import NoReturn

_ROLES = frozenset({"protected-file", "readonly-directory", "writable-directory", "cwd"})
_MAX_REQUESTS = 81
_MAX_NODES = 256
_MAX_DEPTH = 64
_MAX_PATH_BYTES = 4096
_MAX_TOTAL_PATH_BYTES = 65536
MAX_PRODUCER_GRANT_MATERIAL_BYTES = 512 * 1024
MAX_PRODUCER_GRANT_TOTAL_MATERIAL_BYTES = 1024 * 1024
MAX_PRODUCER_GRANT_MATERIALS = 64
_U64_MAX = (1 << 64) - 1
_I64_MIN = -(1 << 63)
_I64_MAX = (1 << 63) - 1
_OWNER_TOKEN = object()


class ProducerGrantError(ValueError):
    """Fixed refusal without filesystem paths or supplied exception prose."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(reason: str) -> NoReturn:
    raise ProducerGrantError("producer_grant_" + reason)


def _path(value: str) -> tuple[str, ...]:
    if type(value) is not str or not value or len(value) > _MAX_PATH_BYTES:
        _fail("path_invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        _fail("path_invalid")
    if len(encoded) > _MAX_PATH_BYTES or "\x00" in value or not value.startswith("/"):
        _fail("path_invalid")
    parts = () if value == "/" else tuple(value[1:].split("/"))
    if len(parts) > _MAX_DEPTH or any(part in {"", ".", ".."} for part in parts):
        _fail("path_invalid")
    return parts


@dataclass(frozen=True, slots=True)
class ProducerGrantIdentity:
    device: int
    inode: int
    kind: str

    def validate(self) -> None:
        if (type(self.device) is not int or not 0 <= self.device <= _U64_MAX
                or type(self.inode) is not int or not 1 <= self.inode <= _U64_MAX
                or type(self.kind) is not str or self.kind not in {"file", "directory"}):
            _fail("identity_invalid")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {"device": self.device, "inode": self.inode, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class ProducerGrantExpectedBinding:
    """Original directory expectation which confers no access role."""

    path: str
    identity: ProducerGrantIdentity

    def validate(self) -> None:
        _path(self.path)
        if type(self.identity) is not ProducerGrantIdentity:
            _fail("identity_invalid")
        self.identity.validate()
        if self.identity.kind != "directory":
            _fail("expected_binding_invalid")


@dataclass(frozen=True, slots=True)
class ProducerGrantBindingNode:
    """Detached original lineage observation, without a live descriptor."""

    path: str
    identity: ProducerGrantIdentity
    parent_index: int | None
    name: str

    def validate(self) -> None:
        parts = _path(self.path)
        if type(self.identity) is not ProducerGrantIdentity:
            _fail("identity_invalid")
        self.identity.validate()
        if not parts:
            if (self.parent_index is not None or type(self.name) is not str
                    or self.name != "" or self.identity.kind != "directory"):
                _fail("binding_node_invalid")
        elif (type(self.parent_index) is not int or not 0 <= self.parent_index < _MAX_NODES
              or type(self.name) is not str or self.name != parts[-1]):
            _fail("binding_node_invalid")


@dataclass(frozen=True, slots=True)
class ProducerGrantMaterial:
    """Retained expected bytes/metadata, not an execution or immutable-load receipt."""

    path: str
    identity: ProducerGrantIdentity
    content: bytes
    mtime_ns: int
    ctime_ns: int

    def validate(self) -> None:
        _path(self.path)
        if type(self.identity) is not ProducerGrantIdentity:
            _fail("identity_invalid")
        self.identity.validate()
        if self.identity.kind != "file":
            _fail("material_invalid")
        if (type(self.content) is not bytes or len(self.content) > MAX_PRODUCER_GRANT_MATERIAL_BYTES
                or any(type(value) is not int or not _I64_MIN <= value <= _I64_MAX
                       for value in (self.mtime_ns, self.ctime_ns))):
            _fail("material_invalid")


def _identity(info: os.stat_result) -> ProducerGrantIdentity:
    if stat.S_ISREG(info.st_mode):
        kind = "file"
    elif stat.S_ISDIR(info.st_mode):
        kind = "directory"
    else:
        _fail("object_kind_invalid")
    result = ProducerGrantIdentity(info.st_dev, info.st_ino, kind)
    result.validate()
    return result


@dataclass(frozen=True, slots=True)
class ProducerGrantRequest:
    path: str
    role: str
    expected_identity: ProducerGrantIdentity | None = None

    def validate(self) -> None:
        _path(self.path)
        if type(self.role) is not str or self.role not in _ROLES:
            _fail("role_invalid")
        if self.role in {"writable-directory", "cwd"} and self.path == "/":
            _fail("root_write_invalid")
        if self.expected_identity is None:
            if self.role == "protected-file":
                _fail("expected_identity_required")
        else:
            if type(self.expected_identity) is not ProducerGrantIdentity:
                _fail("identity_invalid")
            self.expected_identity.validate()
            kind = "file" if self.role == "protected-file" else "directory"
            if self.expected_identity.kind != kind:
                _fail("object_kind_invalid")


@dataclass(frozen=True, slots=True)
class ProducerGrantRecord:
    path: str
    roles: tuple[str, ...]
    identity: ProducerGrantIdentity

    def validate(self) -> None:
        _path(self.path)
        if (type(self.roles) is not tuple or not 1 <= len(self.roles) <= len(_ROLES)
                or any(type(role) is not str or role not in _ROLES for role in self.roles)
                or tuple(sorted(set(self.roles))) != self.roles):
            _fail("roles_invalid")
        if type(self.identity) is not ProducerGrantIdentity:
            _fail("identity_invalid")
        self.identity.validate()
        kind = "file" if "protected-file" in self.roles else "directory"
        if self.identity.kind != kind or (kind == "file" and self.roles != ("protected-file",)):
            _fail("object_kind_invalid")
        if "cwd" in self.roles and "writable-directory" not in self.roles:
            _fail("cwd_write_required")
        if ("readonly-directory" in self.roles and "writable-directory" in self.roles):
            _fail("write_overlap")
        if self.path == "/" and any(role in self.roles for role in ("cwd", "writable-directory")):
            _fail("root_write_invalid")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {"path": self.path, "roles": list(self.roles), "identity": self.identity.to_dict()}


def _records_payload(records: tuple[ProducerGrantRecord, ...]) -> dict[str, object]:
    if type(records) is not tuple or not 1 <= len(records) <= _MAX_REQUESTS:
        _fail("records_invalid")
    total = 0
    paths = []
    identities = set()
    for record in records:
        if type(record) is not ProducerGrantRecord:
            _fail("records_invalid")
        record.validate()
        total += len(record.path.encode())
        paths.append(record.path)
        key = (record.identity.device, record.identity.inode)
        if key in identities:
            _fail("object_alias")
        identities.add(key)
    if total > _MAX_TOTAL_PATH_BYTES or tuple(sorted(set(paths))) != tuple(paths):
        _fail("records_invalid")
    roles = [role for record in records for role in record.roles]
    if (len(roles) > _MAX_REQUESTS or roles.count("cwd") > 1
            or roles.count("writable-directory") > 16
            or roles.count("protected-file") + roles.count("readonly-directory") > 64):
        _fail("request_count_invalid")
    _check_overlap({record.path: record.roles for record in records})
    return {
        "schema_version": "1", "scope": "host-held-grant-anchors", "execution_enforced": False,
        "records": [record.to_dict() for record in records],
    }


def _digest(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ProducerGrantManifest:
    records: tuple[ProducerGrantRecord, ...]
    manifest_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = _records_payload(self.records)
        if (type(self.manifest_sha256) is not str or len(self.manifest_sha256) != 64
                or self.manifest_sha256 != _digest(payload)):
            _fail("manifest_digest_mismatch")
        return {**payload, "manifest_sha256": self.manifest_sha256}

    def validate(self) -> None:
        self.to_dict()


@dataclass(frozen=True, slots=True)
class ProducerGrantAnchor:
    record: ProducerGrantRecord
    fd: int


@dataclass(frozen=True, slots=True)
class _Node:
    path: str
    fd: int
    identity: ProducerGrantIdentity
    parent: int | None
    name: str | None
    owned: tuple[int, int, int]


def _below(path: str, root: str) -> bool:
    return path == root or root == "/" or path.startswith(root + "/")


def _check_overlap(roles: dict[str, tuple[str, ...]]) -> None:
    writes = [path for path, items in roles.items() if "writable-directory" in items]
    for path, items in roles.items():
        if "cwd" in items and path not in writes:
            _fail("cwd_write_required")
        if ("protected-file" in items and any(_below(path, write) for write in writes)):
            _fail("write_overlap")
        if ("readonly-directory" in items
                and any(_below(path, write) or _below(write, path) for write in writes)):
            _fail("write_overlap")


def _requests(requests: tuple[ProducerGrantRequest, ...]) -> tuple[
    dict[str, tuple[str, ...]], dict[str, ProducerGrantIdentity]
]:
    if type(requests) is not tuple or not 1 <= len(requests) <= _MAX_REQUESTS:
        _fail("requests_invalid")
    roles: dict[str, set[str]] = {}
    expected: dict[str, ProducerGrantIdentity] = {}
    total = 0
    for request in requests:
        if type(request) is not ProducerGrantRequest:
            _fail("requests_invalid")
        request.validate()
        total += len(request.path.encode())
        items = roles.setdefault(request.path, set())
        if request.role in items:
            _fail("duplicate_role")
        items.add(request.role)
        if request.expected_identity is not None:
            previous = expected.setdefault(request.path, request.expected_identity)
            if previous != request.expected_identity:
                _fail("expected_identity_conflict")
    counts = [request.role for request in requests]
    if (total > _MAX_TOTAL_PATH_BYTES or counts.count("cwd") > 1
            or counts.count("writable-directory") > 16
            or counts.count("protected-file") + counts.count("readonly-directory") > 64):
        _fail("request_count_invalid")
    canonical = {path: tuple(sorted(items)) for path, items in sorted(roles.items())}
    for items in canonical.values():
        if "protected-file" in items and items != ("protected-file",):
            _fail("object_kind_invalid")
    _check_overlap(canonical)
    return canonical, expected


def _graph_paths(roles: dict[str, tuple[str, ...]]) -> set[str]:
    paths = {"/"}
    for path in roles:
        current = ""
        for component in _path(path):
            current += "/" + component
            paths.add(current)
    return paths


def _acquisition_options(
    roles: dict[str, tuple[str, ...]], expected: dict[str, ProducerGrantIdentity],
    bindings: tuple[ProducerGrantExpectedBinding, ...], create: bool, creation_root: str | None,
) -> tuple[dict[str, ProducerGrantIdentity], set[str]]:
    if type(bindings) is not tuple or len(bindings) > _MAX_NODES:
        _fail("expected_bindings_invalid")
    if type(create) is not bool:
        _fail("creation_invalid")
    graph = _graph_paths(roles)
    combined = dict(expected)
    seen = set()
    total = 0
    for binding in bindings:
        if type(binding) is not ProducerGrantExpectedBinding:
            _fail("expected_bindings_invalid")
        binding.validate()
        total += len(binding.path.encode())
        if binding.path in seen:
            _fail("expected_binding_duplicate")
        seen.add(binding.path)
        if binding.path not in graph or "protected-file" in roles.get(binding.path, ()):
            _fail("expected_binding_invalid")
        previous = combined.setdefault(binding.path, binding.identity)
        if previous != binding.identity:
            _fail("expected_identity_conflict")
    if total > _MAX_TOTAL_PATH_BYTES:
        _fail("expected_bindings_invalid")
    if not create:
        if creation_root is not None:
            _fail("creation_invalid")
        return combined, set()
    if type(creation_root) is not str:
        _fail("creation_root_invalid")
    _path(creation_root)
    if (creation_root == "/" or creation_root not in graph
            or "protected-file" in roles.get(creation_root, ())):
        _fail("creation_root_invalid")
    allowed = set()
    for path, items in roles.items():
        if "writable-directory" not in items:
            continue
        if not _below(path, creation_root):
            _fail("creation_path_invalid")
        current = ""
        for component in _path(path):
            current += "/" + component
            if current != creation_root and _below(current, creation_root):
                allowed.add(current)
    return combined, allowed


def _open_node(
    path: str, nodes: dict[str, _Node], *, directory: bool,
    expected_identity: ProducerGrantIdentity | None = None, create: bool = False,
) -> _Node:
    existing = nodes.get(path)
    if existing is not None:
        if directory != (existing.identity.kind == "directory"):
            _fail("object_kind_invalid")
        if expected_identity is not None and existing.identity != expected_identity:
            _fail("expected_identity_mismatch")
        return existing
    if len(nodes) >= _MAX_NODES:
        _fail("node_count_invalid")
    parent_path, _, name = path.rpartition("/")
    parent = None if path == "/" else nodes[parent_path or "/"].fd
    node_name = None if path == "/" else name
    try:
        observed = os.stat(path if parent is None else name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        if not create or not directory or parent is None or expected_identity is not None:
            raise
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            _fail("creation_raced")
        # mkdir does not return an FD: authority starts at the checked opened
        # object below, not at an unobserved or atomic mkdir identity.
        observed = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stat.S_IMODE(observed.st_mode) != 0o700:
            _fail("creation_mode_invalid")
    identity = _identity(observed)
    if directory != (identity.kind == "directory"):
        _fail("object_kind_invalid")
    if expected_identity is not None and identity != expected_identity:
        _fail("expected_identity_mismatch")
    flags = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    flags |= os.O_PATH if sys.platform.startswith("linux") and hasattr(os, "O_PATH") else os.O_RDONLY
    if directory:
        flags |= os.O_DIRECTORY
    fd = os.open(path if parent is None else name, flags, dir_fd=parent)
    try:
        opened_info = os.fstat(fd)
    except OSError:
        os.close(fd)
        raise
    # Register immediately, so every later failure closes this original FD.
    owned = (opened_info.st_dev, opened_info.st_ino, stat.S_IFMT(opened_info.st_mode))
    node = _Node(path, fd, identity, parent, node_name, owned)
    nodes[path] = node
    current = _identity(os.fstat(fd))
    named = _identity(os.stat(path if parent is None else name, dir_fd=parent, follow_symlinks=False))
    if current != identity or named != identity:
        _fail("object_changed")
    return node


class HeldProducerGrantPlan:
    """Context-owned original nodes; not reconstructible from a detached manifest."""

    __slots__ = ("_closed", "_nodes", "_records")

    def __init__(self, token: object, nodes: dict[str, _Node], records: tuple[ProducerGrantRecord, ...]):
        if token is not _OWNER_TOKEN:
            _fail("owner_invalid")
        self._nodes = nodes
        self._records = records
        self._closed = False

    def _lineage(self, path: str) -> tuple[_Node, ...]:
        result = [self._nodes["/"]]
        current = ""
        for component in _path(path):
            current += "/" + component
            result.append(self._nodes[current])
        return tuple(result)

    def _check_observed_overlap(self) -> None:
        writes = [record for record in self._records if "writable-directory" in record.roles]
        root_identity = self._nodes["/"].identity
        for write in writes:
            if write.identity == root_identity:
                _fail("root_write_invalid")
            for record in self._records:
                if (any(role in record.roles for role in ("protected-file", "readonly-directory"))
                        and any(node.identity == write.identity for node in self._lineage(record.path))):
                    _fail("write_overlap")
                if ("readonly-directory" in record.roles
                        and any(node.identity == record.identity for node in self._lineage(write.path))):
                    _fail("write_overlap")

    def validate(self, *, reserved_fds: tuple[int, ...] = ()) -> None:
        if self._closed:
            _fail("owner_closed")
        if (type(reserved_fds) is not tuple or len(reserved_fds) > 256
                or any(type(fd) is not int or not 0 <= fd <= 0x7fffffff for fd in reserved_fds)):
            _fail("reserved_fds_invalid")
        _records_payload(self._records)
        try:
            for node in self._nodes.values():
                opened = _identity(os.fstat(node.fd))
                named = _identity(os.stat(
                    node.path if node.parent is None else node.name,
                    dir_fd=node.parent, follow_symlinks=False,
                ))
                if opened != node.identity or named != node.identity:
                    _fail("object_changed")
            for record in self._records:
                node = self._nodes[record.path]
                if node.identity != record.identity:
                    _fail("object_changed")
                if "protected-file" in record.roles and os.fstat(node.fd).st_nlink != 1:
                    _fail("protected_links_invalid")
                if node.fd <= 2 or node.fd in reserved_fds:
                    _fail("fd_alias")
            self._check_observed_overlap()
        except OSError as exc:
            raise ProducerGrantError("producer_grant_object_unavailable") from exc

    def validate_protected_materials(self, materials: tuple[ProducerGrantMaterial, ...]) -> None:
        """Recheck retained original bytes through temporary held-parent readers.

        The formal caller still applies its original config/RSI-specific limits and
        descriptors. This operation supplies no sealing or execution authority.
        """
        if self._closed:
            _fail("owner_closed")
        if type(materials) is not tuple or len(materials) > MAX_PRODUCER_GRANT_MATERIALS:
            _fail("materials_invalid")
        supplied = {}
        total = 0
        for material in materials:
            if type(material) is not ProducerGrantMaterial:
                _fail("materials_invalid")
            material.validate()
            if material.path in supplied:
                _fail("material_duplicate")
            supplied[material.path] = material
            total += len(material.content)
        if total > MAX_PRODUCER_GRANT_TOTAL_MATERIAL_BYTES:
            _fail("materials_invalid")
        protected = {record.path for record in self._records if "protected-file" in record.roles}
        if set(supplied) != protected:
            _fail("material_set_mismatch")
        self.validate()
        for path in sorted(supplied):
            material = supplied[path]
            node = self._nodes[path]
            if material.identity != node.identity:
                _fail("expected_identity_mismatch")
            try:
                _check_material_info(os.stat(node.name, dir_fd=node.parent, follow_symlinks=False), material)
                reader = os.open(node.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                 dir_fd=node.parent)
                try:
                    _check_material_info(os.fstat(reader), material)
                    chunks = []
                    remaining = len(material.content) + 1
                    while remaining:
                        chunk = os.read(reader, min(65536, remaining))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    content = b"".join(chunks)
                    if (content != material.content
                            or hashlib.sha256(content).digest() != hashlib.sha256(material.content).digest()):
                        _fail("material_changed")
                    _check_material_info(os.fstat(reader), material)
                    _check_material_info(os.stat(node.name, dir_fd=node.parent, follow_symlinks=False), material)
                finally:
                    active_exception = sys.exc_info()[0] is not None
                    try:
                        os.close(reader)
                    except OSError:
                        if not active_exception:
                            _fail("fd_close_failed")
            except OSError as exc:
                raise ProducerGrantError("producer_grant_material_unavailable") from exc
            self.validate()

    @property
    def anchors(self) -> tuple[ProducerGrantAnchor, ...]:
        self.validate()
        return tuple(ProducerGrantAnchor(record, self._nodes[record.path].fd) for record in self._records)

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return tuple(anchor.fd for anchor in self.anchors)

    @property
    def binding_nodes(self) -> tuple[ProducerGrantBindingNode, ...]:
        self.validate()
        paths = tuple(sorted(self._nodes))
        indexes = {path: index for index, path in enumerate(paths)}
        result = []
        for path in paths:
            node = self._nodes[path]
            parent_path = path.rpartition("/")[0] or "/"
            parent_index = None if path == "/" else indexes[parent_path]
            binding = ProducerGrantBindingNode(path, node.identity, parent_index, node.name or "")
            binding.validate()
            if parent_index is not None and (parent_index >= len(result)
                                            or result[parent_index].identity.kind != "directory"):
                _fail("binding_node_invalid")
            result.append(binding)
        return tuple(result)

    @property
    def manifest(self) -> ProducerGrantManifest:
        self.validate()
        return ProducerGrantManifest(self._records, _digest(_records_payload(self._records)))


def _check_material_info(info: os.stat_result, material: ProducerGrantMaterial) -> None:
    if (_identity(info) != material.identity or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o400 or info.st_size != len(material.content)
            or info.st_mtime_ns != material.mtime_ns or info.st_ctime_ns != material.ctime_ns):
        _fail("material_changed")


@contextmanager
def hold_producer_grants(
    requests: tuple[ProducerGrantRequest, ...], *,
    expected_bindings: tuple[ProducerGrantExpectedBinding, ...] = (),
    create_writable_directories: bool = False, creation_root: str | None = None,
) -> Iterator[HeldProducerGrantPlan]:
    """Acquire original no-follow anchors, revalidate on success, attempt cleanup.

    Directory identities omitted by the caller are first observations at entry, not
    claims about earlier validation. Protected files require supplied original pins.
    Expected ancestor bindings grant no access. Optional creation starts ownership at
    the first checked opened directory, without an atomic mkdir/FD identity claim.
    """
    roles, expected = _requests(requests)
    expected, creation_paths = _acquisition_options(
        roles, expected, expected_bindings, create_writable_directories, creation_root,
    )
    if not all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_CLOEXEC", "O_DIRECTORY", "O_NONBLOCK")):
        _fail("platform_unsupported")
    nodes: dict[str, _Node] = {}
    plan: HeldProducerGrantPlan | None = None
    try:
        try:
            _open_node("/", nodes, directory=True, expected_identity=expected.get("/"))
            if create_writable_directories:
                current = ""
                for part in _path(creation_root):
                    current += "/" + part
                    _open_node(current, nodes, directory=True, expected_identity=expected.get(current))
            records = []
            for path, items in roles.items():
                current = ""
                parts = _path(path)
                for part in parts[:-1]:
                    current += "/" + part
                    _open_node(current, nodes, directory=True, expected_identity=expected.get(current),
                               create=current in creation_paths)
                node = _open_node(path, nodes, directory="protected-file" not in items,
                                  expected_identity=expected.get(path), create=path in creation_paths)
                records.append(ProducerGrantRecord(path, items, node.identity))
            original = tuple(records)
            _records_payload(original)
            plan = HeldProducerGrantPlan(_OWNER_TOKEN, nodes, original)
            plan.validate()
        except OSError as exc:
            raise ProducerGrantError("producer_grant_object_unavailable") from exc
        yield plan
        plan.validate()
    finally:
        active_exception = sys.exc_info()[0] is not None
        if plan is not None:
            plan._closed = True
        close_failed = False
        for node in reversed(tuple(nodes.values())):
            try:
                current = os.fstat(node.fd)
                if (current.st_dev, current.st_ino, stat.S_IFMT(current.st_mode)) != node.owned:
                    close_failed = True
                    continue
                os.close(node.fd)
            except OSError:
                close_failed = True
        if close_failed and not active_exception:
            _fail("fd_close_failed")


__all__ = [
    "MAX_PRODUCER_GRANT_MATERIALS",
    "MAX_PRODUCER_GRANT_MATERIAL_BYTES",
    "MAX_PRODUCER_GRANT_TOTAL_MATERIAL_BYTES",
    "HeldProducerGrantPlan",
    "ProducerGrantAnchor",
    "ProducerGrantBindingNode",
    "ProducerGrantError",
    "ProducerGrantExpectedBinding",
    "ProducerGrantIdentity",
    "ProducerGrantManifest",
    "ProducerGrantMaterial",
    "ProducerGrantRecord",
    "ProducerGrantRequest",
    "hold_producer_grants",
]
