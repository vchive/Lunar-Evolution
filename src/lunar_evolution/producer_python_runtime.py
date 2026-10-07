"""Declared Python runtime file inventory, without discovery or execution.

The target ABI and launcher policy are declarations.  Two bounded no-follow
snapshots bind the listed bytes and directory identities; they do not inventory
unlisted imports, seal writable files, or protect bytes loaded by a later process.
This module never grants native read paths or changes a launch protocol.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from ._candidate_workspace_io import DirectoryChain
from .candidate_workspace_plan import CandidateWorkspaceError

MAX_PYTHON_RUNTIME_ROOTS = 16
MAX_PYTHON_RUNTIME_FILES = 4096
MAX_PYTHON_RUNTIME_FILE_BYTES = 256 * 1024 * 1024
MAX_PYTHON_RUNTIME_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_PYTHON_RUNTIME_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_IMPORT_ROOTS = 4096
_MAX_PATH_BYTES = 4096
_MAX_PATH_PARTS = 128
_MAX_DIRECTORY_PINS = (MAX_PYTHON_RUNTIME_FILES + _MAX_IMPORT_ROOTS + 1) * _MAX_PATH_PARTS
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SHA = re.compile(r"[0-9a-f]{64}")
_PROTOCOL = "lunar-python-runtime-inventory-v1"
_SCOPE = "declared-files-only"
_SLOTS = ("runtime", "dependency", "project", "resource", "metadata")
_ROLE_SLOTS = {
    "interpreter": "runtime", "loader": "runtime", "shared_library": "runtime",
    "stdlib": "runtime", "stdlib_archive": "runtime", "extension": "dependency",
    "site_package": "dependency", "project_source": "project",
    "project_resource": "resource", "venv_config": "metadata", "dependency_lock": "metadata",
}
_STAT_FIELDS = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
_MANIFEST_FIELDS = frozenset({
    "schema_version", "protocol", "scope", "target", "policy", "roots", "files",
    "import_roots", "entrypoint", "manifest_sha256", *(slot + "_sha256" for slot in _SLOTS),
})


class PythonRuntimeError(ValueError):
    """A fixed refusal code, without caller paths or exception contents."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(reason: str) -> NoReturn:
    raise PythonRuntimeError("python_runtime_" + reason)


def _canonical(value: object) -> bytes:
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                            allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail("json_invalid")
    if len(result) > MAX_PYTHON_RUNTIME_MANIFEST_BYTES:
        _fail("manifest_too_large")
    return result


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _integer(value: object, *, minimum: int = 0, maximum: int = 2**64 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("stat_invalid")
    return value


def _mode(value: object) -> int:
    mode = _integer(value, maximum=0o7777)
    if mode & (stat.S_ISUID | stat.S_ISGID):
        _fail("privileged_mode")
    return mode


def _label(value: object) -> str:
    if type(value) is not str or _LABEL.fullmatch(value) is None:
        _fail("root_label_invalid")
    return value


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("digest_invalid")
    return value


def _path(value: object, *, absolute: bool, dot: bool = False) -> str:
    if type(value) is not str or not value or any(char in value for char in "\x00\r\n\\"):
        _fail("path_invalid")
    try:
        path = Path(value)
        if (len(value.encode("utf-8")) > _MAX_PATH_BYTES or len(path.parts) > _MAX_PATH_PARTS
                or path.is_absolute() is not absolute or path.as_posix() != value
                or ".." in path.parts or (value == "." and not dot)
                or (absolute and value.startswith("//"))):
            _fail("path_invalid")
    except (TypeError, ValueError, UnicodeError):
        _fail("path_invalid")
    return value


def _policy() -> dict[str, object]:
    # An exact declared policy for a future launcher, never an observed enforcement claim.
    return {
        "argv_flags": ["-I", "-S", "-B"], "inherit_python_environment": False,
        "user_site": False, "pth_processing": False, "customization_imports": False,
        "cwd_imports": False, "bytecode_writes": False,
    }


class _DTO:
    __slots__ = ()

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class PythonRuntimeTarget(_DTO):
    """Caller-declared CPython compatibility; no binary ABI inspection is performed."""

    platform: str
    architecture: str
    python_version: str
    abi_tag: str
    layout: str = "portable-tree"

    def __post_init__(self) -> None:
        if (type(self.platform) is not str or self.platform not in {"linux", "darwin"}
                or type(self.architecture) is not str or self.architecture not in {"x86_64", "aarch64"}
                or type(self.python_version) is not str or self.python_version not in {"3.11", "3.12", "3.13"}
                or type(self.abi_tag) is not str or self.abi_tag != "cp" + self.python_version.replace(".", "")
                or type(self.layout) is not str or self.layout not in {"portable-tree", "venv-tree"}):
            _fail("target_unsupported")

    def to_dict(self) -> dict[str, Any]:
        return {"platform": self.platform, "architecture": self.architecture,
                "python_version": self.python_version, "abi_tag": self.abi_tag, "layout": self.layout}


@dataclass(frozen=True, slots=True)
class PythonRuntimeFileDeclaration(_DTO):
    root_label: str
    relative_path: str
    role: str

    def __post_init__(self) -> None:
        _label(self.root_label)
        _path(self.relative_path, absolute=False)
        if type(self.role) is not str or self.role not in _ROLE_SLOTS:
            _fail("role_invalid")
        basename = Path(self.relative_path).name.casefold()
        if basename.endswith(".pth") or basename in {"sitecustomize.py", "usercustomize.py"}:
            _fail("listed_import_hook")

    def to_dict(self) -> dict[str, Any]:
        return {"root_label": self.root_label, "relative_path": self.relative_path, "role": self.role}


@dataclass(frozen=True, slots=True)
class PythonRuntimeImportRoot(_DTO):
    root_label: str
    relative_path: str = "."

    def __post_init__(self) -> None:
        _label(self.root_label)
        _path(self.relative_path, absolute=False, dot=True)

    def to_dict(self) -> dict[str, Any]:
        return {"root_label": self.root_label, "relative_path": self.relative_path}


@dataclass(frozen=True, slots=True)
class PythonRuntimeDirectory(_DTO):
    path: str
    device: int
    inode: int
    mode: int

    def __post_init__(self) -> None:
        _path(self.path, absolute=True)
        _integer(self.device)
        _integer(self.inode, minimum=1)
        _mode(self.mode)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "device": self.device, "inode": self.inode, "mode": self.mode}


@dataclass(frozen=True, slots=True)
class PythonRuntimeRoot(_DTO):
    label: str
    path: str
    device: int
    inode: int
    mode: int
    directories: tuple[PythonRuntimeDirectory, ...]

    def __post_init__(self) -> None:
        _label(self.label)
        _path(self.path, absolute=True)
        _integer(self.device)
        _integer(self.inode, minimum=1)
        _mode(self.mode)
        if (type(self.directories) is not tuple or not self.directories
                or len(self.directories) > _MAX_DIRECTORY_PINS
                or any(type(item) is not PythonRuntimeDirectory for item in self.directories)):
            _fail("directories_invalid")
        paths = tuple(item.path for item in self.directories)
        if paths != tuple(sorted(set(paths))):
            _fail("directories_not_canonical")
        root = next((item for item in self.directories if item.path == self.path), None)
        if root is None or (root.device, root.inode, root.mode) != (self.device, self.inode, self.mode):
            _fail("root_identity_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "path": self.path, "device": self.device, "inode": self.inode,
                "mode": self.mode, "directories": [item.to_dict() for item in self.directories]}


@dataclass(frozen=True, slots=True)
class PythonRuntimeFile(_DTO):
    root_label: str
    relative_path: str
    role: str
    size: int
    sha256: str
    device: int
    inode: int
    mode: int
    mtime_ns: int
    ctime_ns: int

    def __post_init__(self) -> None:
        PythonRuntimeFileDeclaration(self.root_label, self.relative_path, self.role)
        _integer(self.size, maximum=MAX_PYTHON_RUNTIME_FILE_BYTES)
        _sha(self.sha256)
        _integer(self.device)
        _integer(self.inode, minimum=1)
        _mode(self.mode)
        _integer(self.mtime_ns)
        _integer(self.ctime_ns)
        if self.role == "interpreter" and (not self.mode & 0o111 or self.size == 0):
            _fail("interpreter_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {"root_label": self.root_label, "relative_path": self.relative_path, "role": self.role,
                "size": self.size, "sha256": self.sha256, "device": self.device, "inode": self.inode,
                "mode": self.mode, "mtime_ns": self.mtime_ns, "ctime_ns": self.ctime_ns}


def _slot_digests(files: tuple[PythonRuntimeFile, ...]) -> dict[str, str]:
    return {slot + "_sha256": _digest({
        "slot": slot, "files": [item.to_dict() for item in files if _ROLE_SLOTS[item.role] == slot],
    }) for slot in _SLOTS}


@dataclass(frozen=True, slots=True)
class PythonRuntimeManifest(_DTO):
    target: PythonRuntimeTarget
    roots: tuple[PythonRuntimeRoot, ...]
    files: tuple[PythonRuntimeFile, ...]
    import_roots: tuple[PythonRuntimeImportRoot, ...]
    entrypoint: PythonRuntimeFileDeclaration
    runtime_sha256: str
    dependency_sha256: str
    project_sha256: str
    resource_sha256: str
    metadata_sha256: str
    manifest_sha256: str

    def __post_init__(self) -> None:
        _validate_manifest(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1", "protocol": _PROTOCOL, "scope": _SCOPE,
            "target": self.target.to_dict(), "policy": _policy(),
            "roots": [item.to_dict() for item in self.roots],
            "files": [item.to_dict() for item in self.files],
            "import_roots": [item.to_dict() for item in self.import_roots],
            "entrypoint": self.entrypoint.to_dict(),
            **{slot + "_sha256": getattr(self, slot + "_sha256") for slot in _SLOTS},
            "manifest_sha256": self.manifest_sha256,
        }


@dataclass(frozen=True, slots=True)
class PythonRuntimeObservation(_DTO):
    """Evidence for declared files only, without execution or load protection."""

    target: PythonRuntimeTarget
    manifest_sha256: str
    runtime_sha256: str
    dependency_sha256: str
    project_sha256: str
    resource_sha256: str
    metadata_sha256: str
    file_count: int
    total_bytes: int

    def __post_init__(self) -> None:
        if type(self.target) is not PythonRuntimeTarget:
            _fail("target_invalid")
        for field in ("manifest_sha256", *(slot + "_sha256" for slot in _SLOTS)):
            _sha(getattr(self, field))
        _integer(self.file_count, minimum=1, maximum=MAX_PYTHON_RUNTIME_FILES)
        _integer(self.total_bytes, maximum=MAX_PYTHON_RUNTIME_TOTAL_BYTES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": _SCOPE, "execution_performed": False, "runtime_load_protection": False,
            "target": self.target.to_dict(), "manifest_sha256": self.manifest_sha256,
            **{slot + "_sha256": getattr(self, slot + "_sha256") for slot in _SLOTS},
            "file_count": self.file_count, "total_bytes": self.total_bytes,
        }


def _file_key(value: PythonRuntimeFileDeclaration | PythonRuntimeFile) -> tuple[str, str]:
    return value.root_label, value.relative_path


def _import_key(value: PythonRuntimeImportRoot) -> tuple[str, str]:
    return value.root_label, value.relative_path


def _sequence(value: object, kind: type, maximum: int, *, empty: bool = False) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("sequence_invalid")
    count = len(value)
    if not (0 if empty else 1) <= count <= maximum:
        _fail("sequence_invalid")
    # Bound indexing even when a caller supplies a custom Sequence implementation.
    result = tuple(value[index] for index in range(count))
    if any(type(item) is not kind for item in result):
        _fail("sequence_invalid")
    # Recheck even frozen DTOs: caller-controlled object.__setattr__ is not authority.
    for item in result:
        item.__post_init__()
    return result


def _root_paths(value: object) -> dict[str, Path]:
    if not isinstance(value, Mapping) or not 1 <= len(value) <= MAX_PYTHON_RUNTIME_ROOTS:
        _fail("roots_invalid")
    result = {}
    for index, (label, raw) in enumerate(value.items()):
        if index >= MAX_PYTHON_RUNTIME_ROOTS:
            _fail("roots_invalid")
        _label(label)
        if not isinstance(raw, (str, Path)):
            _fail("path_invalid")
        path = Path(_path(str(raw), absolute=True))
        if label in result:
            _fail("root_duplicate")
        result[label] = path
    values = list(result.values())
    for index, path in enumerate(values):
        for other in values[index + 1:]:
            if path == other or path in other.parents or other in path.parents:
                _fail("roots_overlap")
    return dict(sorted(result.items()))


def _declarations(
    root_paths: Mapping[str, Path], declarations: Sequence[PythonRuntimeFileDeclaration],
    imports: Sequence[PythonRuntimeImportRoot], entrypoint: PythonRuntimeFileDeclaration,
    target: PythonRuntimeTarget,
) -> tuple[tuple[PythonRuntimeFileDeclaration, ...], tuple[PythonRuntimeImportRoot, ...]]:
    if type(target) is not PythonRuntimeTarget:
        _fail("target_invalid")
    target.__post_init__()
    files = _sequence(declarations, PythonRuntimeFileDeclaration, MAX_PYTHON_RUNTIME_FILES)
    import_roots = _sequence(imports, PythonRuntimeImportRoot, _MAX_IMPORT_ROOTS, empty=True)
    if type(entrypoint) is not PythonRuntimeFileDeclaration:
        _fail("entrypoint_invalid")
    entrypoint.__post_init__()
    keys = [_file_key(item) for item in files]
    if len(set(keys)) != len(keys):
        _fail("file_duplicate")
    import_keys = [_import_key(item) for item in import_roots]
    if len(set(import_keys)) != len(import_keys):
        _fail("import_root_duplicate")
    used = {item.root_label for item in (*files, *import_roots)}
    if used != set(root_paths):
        _fail("root_references_invalid")
    if entrypoint.role != "project_source" or entrypoint not in files:
        _fail("entrypoint_invalid")
    roles = [item.role for item in files]
    if (roles.count("interpreter") != 1 or not {"stdlib", "stdlib_archive"}.intersection(roles)
            or "dependency_lock" not in roles):
        _fail("required_files_missing")
    venv = [item for item in files if item.role == "venv_config"]
    if target.layout == "venv-tree":
        if len(venv) != 1 or Path(venv[0].relative_path).name != "pyvenv.cfg":
            _fail("venv_config_invalid")
    elif venv:
        _fail("venv_config_invalid")
    return tuple(sorted(files, key=_file_key)), tuple(sorted(import_roots, key=_import_key))


def _directory_paths(
    root_paths: Mapping[str, Path], declarations: Sequence[PythonRuntimeFileDeclaration],
    imports: Sequence[PythonRuntimeImportRoot],
) -> dict[str, tuple[Path, ...]]:
    result = {}
    # Refuse an inventory too large to serialize before opening the selected tree.
    # This is a lower bound: actual stat numbers and the final schema add bytes.
    minimum_bytes = len(_canonical({
        "files": [item.to_dict() for item in declarations],
        "import_roots": [item.to_dict() for item in imports],
    }))
    for label, root in root_paths.items():
        wanted: set[Path] = set()

        def add(path: Path, collected: set[Path] = wanted) -> None:
            nonlocal minimum_bytes
            if path not in collected:
                minimum_bytes += len(_canonical({
                    "path": path.as_posix(), "device": 0, "inode": 1, "mode": 0,
                }))
                if minimum_bytes > MAX_PYTHON_RUNTIME_MANIFEST_BYTES:
                    _fail("manifest_too_large")
                collected.add(path)

        for path in (root, *root.parents):
            add(path)
        selected = [root / item.relative_path for item in declarations if item.root_label == label]
        for path in selected:
            _path(path.as_posix(), absolute=True)
        directories = [path.parent for path in selected]
        directories.extend(root / item.relative_path for item in imports if item.root_label == label)
        for path in directories:
            _path(path.as_posix(), absolute=True)
            for ancestor in (path, *path.parents):
                add(ancestor)
        result[label] = tuple(sorted(wanted, key=lambda item: item.as_posix()))
    return result


def _validate_manifest(manifest: PythonRuntimeManifest) -> None:
    if type(manifest.target) is not PythonRuntimeTarget:
        _fail("target_invalid")
    roots = _sequence(manifest.roots, PythonRuntimeRoot, MAX_PYTHON_RUNTIME_ROOTS)
    files = _sequence(manifest.files, PythonRuntimeFile, MAX_PYTHON_RUNTIME_FILES)
    imports = _sequence(manifest.import_roots, PythonRuntimeImportRoot, _MAX_IMPORT_ROOTS, empty=True)
    if (type(manifest.roots) is not tuple or type(manifest.files) is not tuple
            or type(manifest.import_roots) is not tuple):
        _fail("manifest_not_immutable")
    labels = tuple(item.label for item in roots)
    if labels != tuple(sorted(set(labels))):
        _fail("roots_not_canonical")
    paths = _root_paths({item.label: item.path for item in roots})
    declarations = tuple(PythonRuntimeFileDeclaration(item.root_label, item.relative_path, item.role)
                         for item in files)
    canonical_files, canonical_imports = _declarations(paths, declarations, imports,
                                                      manifest.entrypoint, manifest.target)
    if declarations != canonical_files or imports != canonical_imports:
        _fail("files_not_canonical")
    if sum(item.size for item in files) > MAX_PYTHON_RUNTIME_TOTAL_BYTES:
        _fail("total_too_large")
    identities = [(item.device, item.inode) for item in files]
    if len(set(identities)) != len(identities):
        _fail("file_alias")
    root_identities = [(item.device, item.inode) for item in roots]
    if len(set(root_identities)) != len(root_identities):
        _fail("root_alias")
    directory_paths = _directory_paths(paths, declarations, imports)
    shared_directories: dict[str, PythonRuntimeDirectory] = {}
    for root in roots:
        if tuple(item.path for item in root.directories) != tuple(
                path.as_posix() for path in directory_paths[root.label]):
            _fail("directory_inventory_invalid")
        for directory in root.directories:
            directory.__post_init__()
            if directory.path in shared_directories and shared_directories[directory.path] != directory:
                _fail("directory_identity_invalid")
            shared_directories[directory.path] = directory
    expected_slots = _slot_digests(files)
    for field, expected in expected_slots.items():
        if _sha(getattr(manifest, field)) != expected:
            _fail("slot_digest_mismatch")
    body = manifest.to_dict()
    body.pop("manifest_sha256")
    if _sha(manifest.manifest_sha256) != _digest(body):
        _fail("manifest_digest_mismatch")


def _observe_directory(path: Path) -> PythonRuntimeDirectory:
    chain = None
    try:
        chain = DirectoryChain(path, "python_runtime_directory_changed")
        opened = os.fstat(chain.fd)
        chain.check()
        return PythonRuntimeDirectory(path.as_posix(), opened.st_dev, opened.st_ino,
                                      stat.S_IMODE(opened.st_mode))
    except (OSError, CandidateWorkspaceError):
        _fail("directory_unavailable")
    finally:
        if chain is not None:
            chain.close()


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return tuple(getattr(info, field) for field in _STAT_FIELDS)


def _observe_file(root_path: Path, declaration: PythonRuntimeFileDeclaration,
                  maximum_bytes: int) -> PythonRuntimeFile:
    path = root_path / declaration.relative_path
    chain = None
    descriptor = -1
    try:
        chain = DirectoryChain(path.parent, "python_runtime_directory_changed")
        before = os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_mode & (stat.S_ISUID | stat.S_ISGID)):
            _fail("file_invalid")
        if before.st_size > maximum_bytes:
            _fail("file_too_large")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=chain.fd)
        opened = os.fstat(descriptor)
        if _fingerprint(before) != _fingerprint(opened):
            _fail("file_changed")
        digest = hashlib.sha256()
        count = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum_bytes + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            if count > maximum_bytes:
                _fail("file_too_large")
            digest.update(chunk)
        after = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False)
        if (_fingerprint(opened) != _fingerprint(after)
                or _fingerprint(after) != _fingerprint(named) or count != after.st_size):
            _fail("file_changed")
        chain.check()
        return PythonRuntimeFile(declaration.root_label, declaration.relative_path, declaration.role,
                                 count, digest.hexdigest(), opened.st_dev, opened.st_ino,
                                 stat.S_IMODE(opened.st_mode), opened.st_mtime_ns, opened.st_ctime_ns)
    except (OSError, CandidateWorkspaceError):
        _fail("file_unavailable")
    finally:
        try:
            if descriptor >= 0:
                os.close(descriptor)
        finally:
            if chain is not None:
                chain.close()


def _recheck_file(root_path: Path, file: PythonRuntimeFile) -> None:
    """Recheck earlier file names/stat pins after the complete streaming pass."""
    path = root_path / file.relative_path
    chain = None
    descriptor = -1
    try:
        chain = DirectoryChain(path.parent, "python_runtime_directory_changed")
        before = os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=chain.fd)
        opened = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False)
        expected = (file.device, file.inode, file.mode, 1, file.size, file.mtime_ns, file.ctime_ns)
        observed = (opened.st_dev, opened.st_ino, stat.S_IMODE(opened.st_mode), opened.st_nlink,
                    opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
        if (not stat.S_ISREG(opened.st_mode) or _fingerprint(before) != _fingerprint(opened)
                or _fingerprint(opened) != _fingerprint(named) or observed != expected):
            _fail("file_changed")
        chain.check()
    except (OSError, CandidateWorkspaceError):
        _fail("file_unavailable")
    finally:
        try:
            if descriptor >= 0:
                os.close(descriptor)
        finally:
            if chain is not None:
                chain.close()


def _observe_snapshot(
    root_paths: Mapping[str, Path], declarations: Sequence[PythonRuntimeFileDeclaration],
    import_roots: Sequence[PythonRuntimeImportRoot],
) -> tuple[tuple[PythonRuntimeRoot, ...], tuple[PythonRuntimeFile, ...]]:
    roots = []
    directories = _directory_paths(root_paths, declarations, import_roots)
    for label, path in root_paths.items():
        pins = tuple(_observe_directory(directory) for directory in directories[label])
        root = next(pin for pin in pins if pin.path == path.as_posix())
        roots.append(PythonRuntimeRoot(label, path.as_posix(), root.device, root.inode, root.mode, pins))
    files = []
    total = 0
    for declaration in declarations:
        remaining = MAX_PYTHON_RUNTIME_TOTAL_BYTES - total
        file = _observe_file(root_paths[declaration.root_label], declaration,
                             min(MAX_PYTHON_RUNTIME_FILE_BYTES, remaining))
        total += file.size
        files.append(file)
    # A later file read may have changed an earlier file or directory after its
    # bytes were hashed.  Recheck the entire observed set before returning it.
    # These checks still cannot seal any file against changes after preflight.
    for file in files:
        _recheck_file(root_paths[file.root_label], file)
    for root in roots:
        for directory in root.directories:
            if _observe_directory(Path(directory.path)) != directory:
                _fail("directory_changed")
    return tuple(roots), tuple(files)


def build_python_runtime_manifest(
    *, root_paths: Mapping[str, str | Path], file_declarations: Sequence[PythonRuntimeFileDeclaration],
    target: PythonRuntimeTarget, import_roots: Sequence[PythonRuntimeImportRoot],
    entrypoint: PythonRuntimeFileDeclaration,
) -> PythonRuntimeManifest:
    """Observe only explicit paths twice.  No target import or process is started."""
    try:
        paths = _root_paths(root_paths)
        declarations, imports = _declarations(paths, file_declarations, import_roots, entrypoint, target)
        first = _observe_snapshot(paths, declarations, imports)
        second = _observe_snapshot(paths, declarations, imports)
        if first != second:
            _fail("inventory_changed")
        roots, files = first
        slots = _slot_digests(files)
        body = {
            "schema_version": "1", "protocol": _PROTOCOL, "scope": _SCOPE,
            "target": target.to_dict(), "policy": _policy(),
            "roots": [item.to_dict() for item in roots], "files": [item.to_dict() for item in files],
            "import_roots": [item.to_dict() for item in imports], "entrypoint": entrypoint.to_dict(),
            **slots,
        }
        return PythonRuntimeManifest(target, roots, files, imports, entrypoint, **slots,
                                     manifest_sha256=_digest(body))
    except PythonRuntimeError:
        raise
    except (TypeError, ValueError, AttributeError, UnicodeError, OverflowError, RecursionError, OSError):
        _fail("inventory_invalid")


def _object(value: object, fields: set[str] | frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        _fail("schema_invalid")
    return value


def _list(value: object, maximum: int) -> list[Any]:
    if type(value) is not list or len(value) > maximum:
        _fail("schema_invalid")
    return value


def _target(value: object) -> PythonRuntimeTarget:
    return PythonRuntimeTarget(**_object(value, {"platform", "architecture", "python_version", "abi_tag", "layout"}))


def _declaration(value: object) -> PythonRuntimeFileDeclaration:
    return PythonRuntimeFileDeclaration(**_object(value, {"root_label", "relative_path", "role"}))


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for name, value in items:
        if name in result:
            _fail("duplicate_json_key")
        result[name] = value
    return result


def parse_python_runtime_manifest(value: bytes | str) -> PythonRuntimeManifest:
    """Parse a bounded exact schema, requiring canonical bytes and every digest."""
    try:
        if type(value) not in {bytes, str}:
            _fail("json_invalid")
        raw = value.encode("utf-8") if type(value) is str else value
        if len(raw) > MAX_PYTHON_RUNTIME_MANIFEST_BYTES:
            _fail("manifest_too_large")
        payload = _object(json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                                     parse_constant=lambda _value: _fail("json_invalid")), _MANIFEST_FIELDS)
        if _canonical(payload) != raw:
            _fail("noncanonical_json")
        if (payload["schema_version"] != "1" or payload["protocol"] != _PROTOCOL
                or payload["scope"] != _SCOPE or _canonical(payload["policy"]) != _canonical(_policy())):
            _fail("schema_invalid")
        roots = []
        for raw_root in _list(payload["roots"], MAX_PYTHON_RUNTIME_ROOTS):
            root = _object(raw_root, {"label", "path", "device", "inode", "mode", "directories"})
            directories = tuple(PythonRuntimeDirectory(**_object(item, {"path", "device", "inode", "mode"}))
                                for item in _list(root["directories"], _MAX_DIRECTORY_PINS))
            roots.append(PythonRuntimeRoot(**{**root, "directories": directories}))
        fields = {"root_label", "relative_path", "role", "size", "sha256", "device", "inode",
                  "mode", "mtime_ns", "ctime_ns"}
        files = tuple(PythonRuntimeFile(**_object(item, fields))
                      for item in _list(payload["files"], MAX_PYTHON_RUNTIME_FILES))
        imports = tuple(PythonRuntimeImportRoot(**_object(item, {"root_label", "relative_path"}))
                        for item in _list(payload["import_roots"], _MAX_IMPORT_ROOTS))
        return PythonRuntimeManifest(
            target=_target(payload["target"]), roots=tuple(roots), files=files, import_roots=imports,
            entrypoint=_declaration(payload["entrypoint"]),
            **{slot + "_sha256": payload[slot + "_sha256"] for slot in _SLOTS},
            manifest_sha256=payload["manifest_sha256"],
        )
    except PythonRuntimeError:
        raise
    except (TypeError, ValueError, AttributeError, UnicodeError, OverflowError, RecursionError, OSError):
        _fail("json_invalid")


def verify_python_runtime_manifest(
    manifest: PythonRuntimeManifest, *, expected_manifest_sha256: str,
    expected_target: PythonRuntimeTarget,
) -> PythonRuntimeObservation:
    """Read-only preflight against caller-owned pins, with two complete snapshots."""
    try:
        if type(manifest) is not PythonRuntimeManifest or type(expected_target) is not PythonRuntimeTarget:
            _fail("manifest_invalid")
        expected_target.__post_init__()
        expected = _sha(expected_manifest_sha256)
        checked = parse_python_runtime_manifest(manifest.to_json())
        if checked.manifest_sha256 != expected or checked.target != expected_target:
            _fail("external_pin_mismatch")
        paths = _root_paths({item.label: item.path for item in checked.roots})
        declarations = tuple(PythonRuntimeFileDeclaration(item.root_label, item.relative_path, item.role)
                             for item in checked.files)
        first = _observe_snapshot(paths, declarations, checked.import_roots)
        if first != (checked.roots, checked.files):
            _fail("inventory_drift")
        second = _observe_snapshot(paths, declarations, checked.import_roots)
        if second != first:
            _fail("inventory_changed")
        return PythonRuntimeObservation(
            target=checked.target, manifest_sha256=checked.manifest_sha256,
            **{slot + "_sha256": getattr(checked, slot + "_sha256") for slot in _SLOTS},
            file_count=len(checked.files), total_bytes=sum(item.size for item in checked.files),
        )
    except PythonRuntimeError:
        raise
    except (TypeError, ValueError, AttributeError, UnicodeError, OverflowError, RecursionError, OSError):
        _fail("inventory_invalid")


__all__ = [
    "MAX_PYTHON_RUNTIME_FILES",
    "MAX_PYTHON_RUNTIME_FILE_BYTES",
    "MAX_PYTHON_RUNTIME_MANIFEST_BYTES",
    "MAX_PYTHON_RUNTIME_ROOTS",
    "MAX_PYTHON_RUNTIME_TOTAL_BYTES",
    "PythonRuntimeDirectory",
    "PythonRuntimeError",
    "PythonRuntimeFile",
    "PythonRuntimeFileDeclaration",
    "PythonRuntimeImportRoot",
    "PythonRuntimeManifest",
    "PythonRuntimeObservation",
    "PythonRuntimeRoot",
    "PythonRuntimeTarget",
    "build_python_runtime_manifest",
    "parse_python_runtime_manifest",
    "verify_python_runtime_manifest",
]
