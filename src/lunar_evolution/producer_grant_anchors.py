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
_U64_MAX = (1 << 64) - 1
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


def _open_node(path: str, nodes: dict[str, _Node], *, directory: bool) -> _Node:
    existing = nodes.get(path)
    if existing is not None:
        if directory != (existing.identity.kind == "directory"):
            _fail("object_kind_invalid")
        return existing
    if len(nodes) >= _MAX_NODES:
        _fail("node_count_invalid")
    parent_path, _, name = path.rpartition("/")
    parent = None if path == "/" else nodes[parent_path or "/"].fd
    node_name = None if path == "/" else name
    observed = os.stat(path if parent is None else name, dir_fd=parent, follow_symlinks=False)
    identity = _identity(observed)
    if directory != (identity.kind == "directory"):
        _fail("object_kind_invalid")
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
        except OSError as exc:
            raise ProducerGrantError("producer_grant_object_unavailable") from exc

    @property
    def anchors(self) -> tuple[ProducerGrantAnchor, ...]:
        self.validate()
        return tuple(ProducerGrantAnchor(record, self._nodes[record.path].fd) for record in self._records)

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return tuple(anchor.fd for anchor in self.anchors)

    @property
    def manifest(self) -> ProducerGrantManifest:
        self.validate()
        return ProducerGrantManifest(self._records, _digest(_records_payload(self._records)))


@contextmanager
def hold_producer_grants(requests: tuple[ProducerGrantRequest, ...]) -> Iterator[HeldProducerGrantPlan]:
    """Acquire original no-follow anchors, revalidate on success, always close them.

    Directory identities omitted by the caller are first observations at entry, not
    claims about earlier validation. Protected files require supplied original pins.
    """
    roles, expected = _requests(requests)
    if not all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_CLOEXEC", "O_DIRECTORY", "O_NONBLOCK")):
        _fail("platform_unsupported")
    nodes: dict[str, _Node] = {}
    plan: HeldProducerGrantPlan | None = None
    try:
        try:
            _open_node("/", nodes, directory=True)
            records = []
            for path, items in roles.items():
                current = ""
                parts = _path(path)
                for part in parts[:-1]:
                    current += "/" + part
                    _open_node(current, nodes, directory=True)
                node = _open_node(path, nodes, directory="protected-file" not in items)
                if path in expected and node.identity != expected[path]:
                    _fail("expected_identity_mismatch")
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
    "HeldProducerGrantPlan", "ProducerGrantAnchor", "ProducerGrantError", "ProducerGrantIdentity",
    "ProducerGrantManifest", "ProducerGrantRecord", "ProducerGrantRequest", "hold_producer_grants",
]
