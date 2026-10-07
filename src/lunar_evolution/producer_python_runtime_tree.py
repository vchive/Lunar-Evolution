"""Bounded closed filesystem layout preflight, without runtime load protection.

This separate contract preserves Feature171's declared-file wire. Every file in the selected
roots must be declared, and directory membership includes empty directories. Neither a successful
preflight nor a parsed self-digest authorizes execution, imports or filesystem grants.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from . import producer_python_runtime as declared
from ._candidate_workspace_io import DirectoryChain
from .candidate_workspace_plan import CandidateWorkspaceError

MAX_PYTHON_RUNTIME_TREE_ENTRIES = 8192
MAX_PYTHON_RUNTIME_TREE_DEPTH = 64
MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES = 8 * 1024 * 1024
_PROTOCOL = "lunar-python-runtime-closed-tree-v1"
_SCOPE = "closed-filesystem-layout"
_CAPABILITIES = {
    "execution_performed": False, "runtime_load_protection": False,
    "archive_contents_complete": False, "loader_dependencies_complete": False,
}
_DIRECTORY_FIELDS = {
    "root_label", "relative_path", "device", "inode", "mode", "mtime_ns", "ctime_ns", "children",
}
_FIELDS = {"schema_version", "protocol", "scope", "declared_manifest", "directories", "tree_sha256", *_CAPABILITIES}
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class PythonRuntimeTreeError(ValueError):
    """Fixed refusal code without caller paths or exception contents."""

    def __init__(self, code: str) -> None:
        self.code = "python_runtime_tree_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise PythonRuntimeTreeError(code)


def _canonical(value: object) -> bytes:
    try:
        encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        chunks, size = [], 0
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("utf-8")
            size += len(encoded)
            if size > MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES:
                _fail("manifest_too_large")
            chunks.append(encoded)
        return b"".join(chunks)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, PythonRuntimeTreeError):
            raise
        raise PythonRuntimeTreeError("json_invalid") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail("digest_invalid")
    return value


def _integer(value: object, *, minimum: int = 0, maximum: int = 2**64 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("stat_invalid")
    return value


def _relative(value: object, *, root: bool = False) -> str:
    checked = declared._path(value, absolute=False, dot=root)
    if len(Path(checked).parts) > MAX_PYTHON_RUNTIME_TREE_DEPTH:
        _fail("depth_exceeded")
    return checked


def _name(value: object) -> str:
    checked = _relative(value)
    if len(Path(checked).parts) != 1:
        _fail("name_invalid")
    return checked


class _DTO:
    __slots__ = ()

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class PythonRuntimeTreeDirectory(_DTO):
    root_label: str
    relative_path: str
    device: int
    inode: int
    mode: int
    mtime_ns: int
    ctime_ns: int
    children: tuple[str, ...]

    def __post_init__(self) -> None:
        declared._label(self.root_label)
        _relative(self.relative_path, root=True)
        _integer(self.device)
        _integer(self.inode, minimum=1)
        declared._mode(self.mode)
        _integer(self.mtime_ns)
        _integer(self.ctime_ns)
        if type(self.children) is not tuple or len(self.children) > MAX_PYTHON_RUNTIME_TREE_ENTRIES:
            _fail("membership_invalid")
        for name in self.children:
            _name(name)
        if self.children != tuple(sorted(set(self.children))):
            _fail("membership_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_label": self.root_label, "relative_path": self.relative_path,
            "device": self.device, "inode": self.inode, "mode": self.mode,
            "mtime_ns": self.mtime_ns, "ctime_ns": self.ctime_ns, "children": list(self.children),
        }


@dataclass(frozen=True, slots=True)
class PythonRuntimeTreeManifest(_DTO):
    declared_manifest: declared.PythonRuntimeManifest
    directories: tuple[PythonRuntimeTreeDirectory, ...]
    tree_sha256: str

    def __post_init__(self) -> None:
        _validate_tree(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1", "protocol": _PROTOCOL, "scope": _SCOPE, **_CAPABILITIES,
            "declared_manifest": self.declared_manifest.to_dict(),
            "directories": [item.to_dict() for item in self.directories], "tree_sha256": self.tree_sha256,
        }


@dataclass(frozen=True, slots=True)
class PythonRuntimeTreeObservation(_DTO):
    target: declared.PythonRuntimeTarget
    declared_manifest_sha256: str
    tree_sha256: str
    file_count: int
    directory_count: int
    entry_count: int
    total_bytes: int

    def __post_init__(self) -> None:
        if type(self.target) is not declared.PythonRuntimeTarget:
            _fail("target_invalid")
        self.target.__post_init__()
        _sha(self.declared_manifest_sha256)
        _sha(self.tree_sha256)
        _integer(self.file_count, minimum=1, maximum=declared.MAX_PYTHON_RUNTIME_FILES)
        _integer(self.directory_count, minimum=1, maximum=MAX_PYTHON_RUNTIME_TREE_ENTRIES)
        _integer(self.entry_count, minimum=1, maximum=MAX_PYTHON_RUNTIME_TREE_ENTRIES)
        _integer(self.total_bytes, maximum=declared.MAX_PYTHON_RUNTIME_TOTAL_BYTES)
        if self.entry_count != self.file_count + self.directory_count:
            _fail("count_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": _SCOPE, **_CAPABILITIES, "target": self.target.to_dict(),
            "declared_manifest_sha256": self.declared_manifest_sha256, "tree_sha256": self.tree_sha256,
            "file_count": self.file_count, "directory_count": self.directory_count,
            "entry_count": self.entry_count, "total_bytes": self.total_bytes,
        }


def _key(directory: PythonRuntimeTreeDirectory) -> tuple[str, str]:
    return directory.root_label, directory.relative_path


def _collection(value: object, *, maximum: int, empty: bool = False) -> tuple[Any, ...]:
    # Never ask a caller-supplied Sequence/iterable for its length or members.
    if type(value) is not tuple or not (0 if empty else 1) <= len(value) <= maximum:
        _fail("collection_invalid")
    return value


def _declared_shape(value: object) -> None:
    """Bound exact immutable DTOs before v1 validation or any serialization.

    The unchanged v1 validator accepts Sequence inputs before its final tuple check.
    This boundary must reject callback-bearing collections before entering it. Ancestor
    pins can extend above the selected roots, but cannot widen the roots being scanned.
    """
    if type(value) is not declared.PythonRuntimeManifest:
        _fail("declared_manifest_invalid")
    roots = _collection(value.roots, maximum=declared.MAX_PYTHON_RUNTIME_ROOTS)
    files = _collection(value.files, maximum=declared.MAX_PYTHON_RUNTIME_FILES)
    imports = _collection(value.import_roots, maximum=declared._MAX_IMPORT_ROOTS, empty=True)
    if type(value.target) is not declared.PythonRuntimeTarget or type(value.entrypoint) is not declared.PythonRuntimeFileDeclaration:
        _fail("declared_manifest_invalid")
    pinned_roots, pin_count = [], 0
    for root in roots:
        if type(root) is not declared.PythonRuntimeRoot:
            _fail("declared_manifest_invalid")
        pins = _collection(root.directories, maximum=min(
            declared._MAX_DIRECTORY_PINS, MAX_PYTHON_RUNTIME_TREE_ENTRIES + declared._MAX_PATH_PARTS,
        ))
        pin_count += len(pins)
        if pin_count > MAX_PYTHON_RUNTIME_TREE_ENTRIES + declared.MAX_PYTHON_RUNTIME_ROOTS * declared._MAX_PATH_PARTS:
            _fail("entries_exceeded")
        pinned_roots.append((root, pins))
    # Validate directory scalars before root's canonical set/hash checks.
    for root, pins in pinned_roots:
        for directory in pins:
            if type(directory) is not declared.PythonRuntimeDirectory:
                _fail("declared_manifest_invalid")
            directory.__post_init__()
        root.__post_init__()
    for file in files:
        if type(file) is not declared.PythonRuntimeFile:
            _fail("declared_manifest_invalid")
        file.__post_init__()
        _relative(file.relative_path)
    for import_root in imports:
        if type(import_root) is not declared.PythonRuntimeImportRoot:
            _fail("declared_manifest_invalid")
        import_root.__post_init__()
        _relative(import_root.relative_path, root=True)
    value.target.__post_init__()
    value.entrypoint.__post_init__()
    for field in ("manifest_sha256", *(slot + "_sha256" for slot in declared._SLOTS)):
        _sha(getattr(value, field))


def _declared_manifest(value: object) -> declared.PythonRuntimeManifest:
    _declared_shape(value)
    value.__post_init__()
    return declared.parse_python_runtime_manifest(value.to_json())


def _validate_tree(tree: PythonRuntimeTreeManifest) -> None:
    directories = _collection(tree.directories, maximum=MAX_PYTHON_RUNTIME_TREE_ENTRIES)
    _declared_shape(tree.declared_manifest)
    if len(directories) + len(tree.declared_manifest.files) > MAX_PYTHON_RUNTIME_TREE_ENTRIES:
        _fail("entries_exceeded")
    for item in directories:
        if type(item) is not PythonRuntimeTreeDirectory:
            _fail("directory_invalid")
        item.__post_init__()
    _sha(tree.tree_sha256)
    original = _declared_manifest(tree.declared_manifest)
    keys = tuple(_key(item) for item in directories)
    if keys != tuple(sorted(set(keys))):
        _fail("directories_not_canonical")
    observed = dict(zip(keys, directories, strict=True))
    roots = {root.label: root for root in original.roots}
    files = {(file.root_label, file.relative_path): file for file in original.files}
    if any(label not in roots for label, _path in keys) or set(keys) & set(files):
        _fail("graph_invalid")
    identities = [(item.device, item.inode) for item in directories] + [(file.device, file.inode) for file in original.files]
    if len(identities) != len(set(identities)):
        _fail("entry_alias")
    children = {key: set() for key in keys}
    for label, path in (*keys, *files):
        _relative(path, root=path == ".")
        if path == ".":
            continue
        parent = (label, Path(path).parent.as_posix())
        if parent not in observed:
            _fail("graph_invalid")
        children[parent].add(Path(path).name)
    for key, directory in observed.items():
        if directory.children != tuple(sorted(children[key])):
            _fail("membership_invalid")
    for label, root in roots.items():
        directory = observed.get((label, "."))
        if directory is None or (directory.device, directory.inode, directory.mode) != (root.device, root.inode, root.mode):
            _fail("root_binding_invalid")
        path = Path(root.path)
        for original_directory in root.directories:
            pinned = Path(original_directory.path)
            if pinned.is_relative_to(path):
                relative = pinned.relative_to(path).as_posix()
                found = observed.get((label, relative))
                if found is None or (found.device, found.inode, found.mode) != (
                    original_directory.device, original_directory.inode, original_directory.mode,
                ):
                    _fail("directory_binding_invalid")
    body = tree.to_dict()
    body.pop("tree_sha256")
    if _sha(tree.tree_sha256) != _digest(body):
        _fail("digest_mismatch")


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory(label: str, relative: str, info: os.stat_result, children: tuple[str, ...]) -> PythonRuntimeTreeDirectory:
    if not stat.S_ISDIR(info.st_mode) or info.st_nlink < 1:
        _fail("directory_invalid")
    return PythonRuntimeTreeDirectory(label, relative, info.st_dev, info.st_ino,
                                      stat.S_IMODE(info.st_mode), info.st_mtime_ns, info.st_ctime_ns, children)


def _same_directory(info: os.stat_result, expected: PythonRuntimeTreeDirectory) -> bool:
    return stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), info.st_mtime_ns, info.st_ctime_ns) == (
        expected.device, expected.inode, expected.mode, expected.mtime_ns, expected.ctime_ns,
    )


def _same_file(info: os.stat_result, expected: declared.PythonRuntimeFile) -> bool:
    return stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), info.st_nlink,
                                           info.st_size, info.st_mtime_ns, info.st_ctime_ns) == (
        expected.device, expected.inode, expected.mode, 1, expected.size, expected.mtime_ns, expected.ctime_ns,
    )


def _read_file(parent: int, name: str, expected: declared.PythonRuntimeFile, *, read_bytes: bool) -> None:
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not _same_file(before, expected):
        _fail("file_drift")
    if expected.size > declared.MAX_PYTHON_RUNTIME_FILE_BYTES:
        _fail("file_too_large")
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    try:
        opened = os.fstat(descriptor)
        if _fingerprint(opened) != _fingerprint(before):
            _fail("file_changed")
        if read_bytes:
            digest, count = hashlib.sha256(), 0
            while True:
                chunk = os.read(descriptor, min(65536, expected.size + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                if count > expected.size:
                    _fail("file_changed")
                digest.update(chunk)
            if count != expected.size or digest.hexdigest() != expected.sha256:
                _fail("file_changed")
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if _fingerprint(opened) != _fingerprint(after) or _fingerprint(after) != _fingerprint(named):
            _fail("file_changed")
    finally:
        os.close(descriptor)


def _close_descriptors(descriptors: list[int]) -> None:
    active, failure = sys.exception(), None
    while descriptors:
        try:
            os.close(descriptors.pop())
        except BaseException as exc:  # noqa: BLE001 - release all other owned FDs on interrupts
            if failure is None or isinstance(exc, (KeyboardInterrupt, SystemExit)):
                failure = exc
    if failure is not None and not isinstance(active, (KeyboardInterrupt, SystemExit)):
        raise failure


def _check_directory(
    root_fd: int, wanted: PythonRuntimeTreeDirectory,
    directories: dict[tuple[str, str], PythonRuntimeTreeDirectory],
    files: dict[tuple[str, str], declared.PythonRuntimeFile],
) -> None:
    descriptor, opened, links = root_fd, [], []
    relative = Path(wanted.relative_path)
    try:
        parts = () if wanted.relative_path == "." else relative.parts
        for index, name in enumerate(parts, 1):
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
            opened.append(child)
            if _fingerprint(before) != _fingerprint(os.fstat(child)):
                _fail("directory_changed")
            expected = directories[(wanted.root_label, Path(*parts[:index]).as_posix())]
            if not _same_directory(before, expected):
                _fail("directory_changed")
            links.append((descriptor, name, child, expected))
            descriptor = child
        before = os.fstat(descriptor)
        if not _same_directory(before, wanted):
            _fail("directory_changed")
        seen = set()
        with os.scandir(descriptor) as entries:
            for entry in entries:
                name = _name(entry.name)
                if name not in wanted.children or name in seen:
                    _fail("membership_changed")
                seen.add(name)
                path = name if wanted.relative_path == "." else wanted.relative_path + "/" + name
                key = wanted.root_label, path
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if key in files:
                    if not _same_file(info, files[key]):
                        _fail("file_changed")
                elif key not in directories or not _same_directory(info, directories[key]):
                    _fail("directory_changed")
        if seen != set(wanted.children) or _fingerprint(before) != _fingerprint(os.fstat(descriptor)):
            _fail("membership_changed")
        for parent, name, child, expected in reversed(links):
            named, held = os.stat(name, dir_fd=parent, follow_symlinks=False), os.fstat(child)
            if _fingerprint(named) != _fingerprint(held) or not _same_directory(held, expected):
                _fail("directory_changed")
    finally:
        _close_descriptors(opened)


def _observe_snapshot(
    manifest: declared.PythonRuntimeManifest, *, read_bytes: bool = True,
) -> tuple[PythonRuntimeTreeDirectory, ...]:
    chains: list[DirectoryChain] = []
    root_fds, directories, seen_files, identities = {}, {}, set(), set()
    files = {(file.root_label, file.relative_path): file for file in manifest.files}
    entry_count, total_bytes = 0, 0

    def reserve(info: os.stat_result) -> None:
        nonlocal entry_count
        entry_count += 1
        if entry_count > MAX_PYTHON_RUNTIME_TREE_ENTRIES:
            _fail("entries_exceeded")
        identity = info.st_dev, info.st_ino
        if identity in identities:
            _fail("entry_alias")
        identities.add(identity)

    def walk(label: str, relative: str, descriptor: int) -> None:
        nonlocal total_bytes
        _relative(relative, root=True)
        before, names = os.fstat(descriptor), set()
        reserve(before)
        with os.scandir(descriptor) as entries:
            for entry in entries:
                name = _name(entry.name)
                if name in names or len(names) >= MAX_PYTHON_RUNTIME_TREE_ENTRIES:
                    _fail("membership_invalid")
                names.add(name)
                path = name if relative == "." else relative + "/" + name
                _relative(path)
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                key = label, path
                if stat.S_ISDIR(info.st_mode):
                    if key in files:
                        _fail("file_drift")
                    child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
                    try:
                        if _fingerprint(info) != _fingerprint(os.fstat(child)):
                            _fail("directory_changed")
                        walk(label, path, child)
                        named = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                        if _fingerprint(info) != _fingerprint(os.fstat(child)) or _fingerprint(info) != _fingerprint(named):
                            _fail("directory_changed")
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    reserve(info)
                    if key not in files:
                        _fail("unlisted_file")
                    total_bytes += info.st_size
                    if total_bytes > declared.MAX_PYTHON_RUNTIME_TOTAL_BYTES:
                        _fail("total_too_large")
                    _read_file(descriptor, name, files[key], read_bytes=read_bytes)
                    seen_files.add(key)
                else:
                    _fail("entry_invalid")
        if _fingerprint(before) != _fingerprint(os.fstat(descriptor)):
            _fail("directory_changed")
        directories[(label, relative)] = _directory(label, relative, before, tuple(sorted(names)))

    try:
        for root in manifest.roots:
            chain = DirectoryChain(Path(root.path), "python_runtime_tree_root_changed")
            chains.append(chain)
            info = os.fstat(chain.fd)
            if (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode)) != (root.device, root.inode, root.mode):
                _fail("root_changed")
            root_fds[root.label] = chain.fd
            walk(root.label, ".", chain.fd)
        if seen_files != set(files):
            _fail("declared_file_missing")
        # A later file read may change an earlier subtree; close the entire observed set.
        for directory in sorted(directories.values(), key=_key):
            _check_directory(root_fds[directory.root_label], directory, directories, files)
        for root, chain in zip(manifest.roots, chains, strict=True):
            chain.check()
            ancestor_pins = {item.path: item for item in root.directories}
            for index, descriptor in enumerate(chain.fds):
                path = Path(*Path(root.path).parts[:index + 1]).as_posix()
                info, wanted = os.fstat(descriptor), ancestor_pins[path]
                if (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode)) != (wanted.device, wanted.inode, wanted.mode):
                    _fail("root_changed")
            if not _same_directory(os.fstat(chain.fd), directories[(root.label, ".")]):
                _fail("root_changed")
        return tuple(sorted(directories.values(), key=_key))
    finally:
        active, failure = sys.exception(), None
        for chain in reversed(chains):
            try:
                chain.close()
            except BaseException as exc:  # noqa: BLE001 - all held root FDs must close
                if failure is None or isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    failure = exc
        if failure is not None and not isinstance(active, (KeyboardInterrupt, SystemExit)):
            raise failure


def _pins(
    manifest: declared.PythonRuntimeManifest, digest: str, target: declared.PythonRuntimeTarget,
) -> None:
    declared.verify_python_runtime_manifest(manifest, expected_manifest_sha256=digest, expected_target=target)


def _checked_snapshots(
    original: declared.PythonRuntimeManifest, digest: str, target: declared.PythonRuntimeTarget,
) -> tuple[PythonRuntimeTreeDirectory, ...]:
    _pins(original, digest, target)
    first = _observe_snapshot(original)
    if _observe_snapshot(original) != first:
        _fail("tree_changed")
    _pins(original, digest, target)
    # Close membership again after the final v1 byte reads, without a third hash pass.
    if _observe_snapshot(original, read_bytes=False) != first:
        _fail("tree_changed")
    return first


def _refusal(exc: Exception) -> PythonRuntimeTreeError:
    return PythonRuntimeTreeError("filesystem_invalid" if isinstance(exc, (OSError, CandidateWorkspaceError)) else "invalid")


def build_python_runtime_tree_manifest(
    *, declared_manifest: declared.PythonRuntimeManifest, expected_manifest_sha256: str,
    expected_target: declared.PythonRuntimeTarget,
) -> PythonRuntimeTreeManifest:
    """Build only from an independently pinned v1 inventory; never admit unlisted files."""
    try:
        original = _declared_manifest(declared_manifest)
        _sha(expected_manifest_sha256)
        directories = _checked_snapshots(original, expected_manifest_sha256, expected_target)
        body = {
            "schema_version": "1", "protocol": _PROTOCOL, "scope": _SCOPE, **_CAPABILITIES,
            "declared_manifest": original.to_dict(), "directories": [item.to_dict() for item in directories],
        }
        return PythonRuntimeTreeManifest(original, directories, _digest(body))
    except PythonRuntimeTreeError:
        raise
    except (OSError, CandidateWorkspaceError, declared.PythonRuntimeError, TypeError, ValueError,
            AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise _refusal(exc) from exc


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for name, value in items:
        if name in result:
            _fail("duplicate_json_key")
        result[name] = value
    return result


def parse_python_runtime_tree_manifest(value: bytes | str) -> PythonRuntimeTreeManifest:
    """Parse canonical bounded detached evidence without filesystem reads or authority."""
    try:
        if type(value) not in {bytes, str}:
            _fail("json_invalid")
        raw = value.encode("utf-8") if type(value) is str else value
        if len(raw) > MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES:
            _fail("manifest_too_large")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                             parse_constant=lambda _value: _fail("json_invalid"))
        if type(payload) is not dict or set(payload) != _FIELDS or _canonical(payload) != raw:
            _fail("schema_invalid")
        if (payload["schema_version"] != "1" or payload["protocol"] != _PROTOCOL or payload["scope"] != _SCOPE
                or any(payload[key] is not False for key in _CAPABILITIES)):
            _fail("schema_invalid")
        original = declared.parse_python_runtime_manifest(_canonical(payload["declared_manifest"]))
        values = payload["directories"]
        if type(values) is not list or len(values) + len(original.files) > MAX_PYTHON_RUNTIME_TREE_ENTRIES:
            _fail("entries_exceeded")
        directories = []
        for item in values:
            if type(item) is not dict or set(item) != _DIRECTORY_FIELDS or type(item["children"]) is not list:
                _fail("schema_invalid")
            if len(item["children"]) > MAX_PYTHON_RUNTIME_TREE_ENTRIES:
                _fail("entries_exceeded")
            directories.append(PythonRuntimeTreeDirectory(**{**item, "children": tuple(item["children"])}))
        return PythonRuntimeTreeManifest(original, tuple(directories), payload["tree_sha256"])
    except PythonRuntimeTreeError:
        raise
    except (declared.PythonRuntimeError, TypeError, ValueError, AttributeError,
            UnicodeError, OverflowError, RecursionError) as exc:
        raise PythonRuntimeTreeError("json_invalid") from exc


def verify_python_runtime_tree_manifest(
    manifest: PythonRuntimeTreeManifest, *, expected_tree_sha256: str,
    expected_manifest_sha256: str, expected_target: declared.PythonRuntimeTarget,
) -> PythonRuntimeTreeObservation:
    """Reverify original tree/declared/target pins without launch, grants, writes or repair."""
    try:
        if type(manifest) is not PythonRuntimeTreeManifest:
            _fail("manifest_invalid")
        manifest.__post_init__()
        checked = parse_python_runtime_tree_manifest(manifest.to_json())
        if checked.tree_sha256 != _sha(expected_tree_sha256):
            _fail("external_pin_mismatch")
        original = checked.declared_manifest
        directories = _checked_snapshots(original, expected_manifest_sha256, expected_target)
        if directories != checked.directories:
            _fail("tree_drift")
        return PythonRuntimeTreeObservation(
            original.target, original.manifest_sha256, checked.tree_sha256, len(original.files),
            len(directories), len(original.files) + len(directories), sum(file.size for file in original.files),
        )
    except PythonRuntimeTreeError:
        raise
    except (OSError, CandidateWorkspaceError, declared.PythonRuntimeError, TypeError, ValueError,
            AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise _refusal(exc) from exc


__all__ = [
    "MAX_PYTHON_RUNTIME_TREE_DEPTH", "MAX_PYTHON_RUNTIME_TREE_ENTRIES", "MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES",
    "PythonRuntimeTreeDirectory", "PythonRuntimeTreeError", "PythonRuntimeTreeManifest", "PythonRuntimeTreeObservation",
    "build_python_runtime_tree_manifest", "parse_python_runtime_tree_manifest", "verify_python_runtime_tree_manifest",
]
