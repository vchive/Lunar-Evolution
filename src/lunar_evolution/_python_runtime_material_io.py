"""Guarded observations of privately validated 171/177 source vectors.

The supplied checkpoint belongs to the trusted controller. It surrounds each
filesystem operation and streaming hash/write; it cannot preempt a blocked
kernel call. Controller threads must not concurrently rebind private FD numbers.
Neither helper observes imports or grants execution/loading authority.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, NoReturn

from . import producer_python_runtime as declared
from . import producer_python_runtime_tree as runtime
from ._python_runtime_material_format import PythonRuntimeMaterialError

_CHUNK = 65536
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_CLEANUP_NOTE = "python_runtime_material_cleanup_unknown"
Checkpoint = Callable[[], None]


def _fail(code: str) -> NoReturn:
    raise PythonRuntimeMaterialError(code)


def _text(value: object, limit: int) -> None:
    if type(value) is not str or not 1 <= len(value) <= limit:
        _fail("source_shape_invalid")


def _integer(value: object, maximum: int = 2**64 - 1) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        _fail("source_shape_invalid")


def _tuple(value: object, maximum: int, *, empty: bool = False) -> None:
    if type(value) is not tuple or not (0 if empty else 1) <= len(value) <= maximum:
        _fail("source_shape_invalid")


def _path(value: object, *, absolute: bool = False, dot: bool = False) -> None:
    _text(value, declared._MAX_PATH_BYTES)
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        _fail("source_shape_invalid")
    if any(character in value for character in "\x00\r\n\\") or size > declared._MAX_PATH_BYTES:
        _fail("source_shape_invalid")
    if dot and value == ".":
        return
    parts = value.split("/")
    if absolute:
        if parts.pop(0) != "":
            _fail("source_shape_invalid")
        if value == "/":
            return
    if any(part in ("", ".", "..") for part in parts) or len(parts) > (declared._MAX_PATH_PARTS if absolute else 64):
        _fail("source_shape_invalid")


def _shape(tree: object) -> None:
    """Cheap exact shape/count guards before invoking the trusted checkpoint.

    Full graph, self-digest and external-pin validation/deep cloning belongs to
    the caller's pure admission boundary, not a fresh filesystem reconstruction.
    """
    if type(tree) is not runtime.PythonRuntimeTreeManifest:
        _fail("source_shape_invalid")
    original = tree.declared_manifest
    if type(original) is not declared.PythonRuntimeManifest:
        _fail("source_shape_invalid")
    for digest in (tree.tree_sha256, original.manifest_sha256, *(getattr(original, slot + "_sha256") for slot in declared._SLOTS)):
        _sha(digest)
    _tuple(tree.directories, 8192)
    _tuple(original.roots, 16)
    _tuple(original.files, 4096)
    _tuple(original.import_roots, declared._MAX_IMPORT_ROOTS, empty=True)
    if len(tree.directories) + len(original.files) > 8192:
        _fail("source_shape_invalid")
    if type(original.target) is not declared.PythonRuntimeTarget or type(original.entrypoint) is not declared.PythonRuntimeFileDeclaration:
        _fail("source_shape_invalid")
    for name, limit in runtime._TARGET_TEXT_LIMITS.items():
        _text(getattr(original.target, name), limit)
    for field in ("root_label", "relative_path", "role"):
        _text(getattr(original.entrypoint, field), 4096 if field == "relative_path" else 128)
    pin_count = 0
    for root in original.roots:
        if type(root) is not declared.PythonRuntimeRoot:
            _fail("source_shape_invalid")
        _text(root.label, 128)
        _path(root.path, absolute=True)
        _tuple(root.directories, 8192 + declared._MAX_PATH_PARTS)
        pin_count += len(root.directories)
        if pin_count > 8192 + 16 * declared._MAX_PATH_PARTS:
            _fail("source_shape_invalid")
        for field in ("device", "inode", "mode"):
            _integer(getattr(root, field))
        for pin in root.directories:
            if type(pin) is not declared.PythonRuntimeDirectory:
                _fail("source_shape_invalid")
            _path(pin.path, absolute=True)
            for field in ("device", "inode", "mode"):
                _integer(getattr(pin, field))
    total = 0
    for file in original.files:
        if type(file) is not declared.PythonRuntimeFile:
            _fail("source_shape_invalid")
        _text(file.root_label, 128)
        _path(file.relative_path)
        _text(file.role, 128)
        _sha(file.sha256)
        for field in ("device", "inode", "mode", "mtime_ns", "ctime_ns"):
            _integer(getattr(file, field))
        _integer(file.size, 256 * 1024 * 1024)
        total += file.size
        if total > 1024 * 1024 * 1024:
            _fail("source_shape_invalid")
    edges = 0
    for directory in tree.directories:
        if type(directory) is not runtime.PythonRuntimeTreeDirectory:
            _fail("source_shape_invalid")
        _text(directory.root_label, 128)
        _path(directory.relative_path, dot=True)
        _tuple(directory.children, 8192, empty=True)
        edges += len(directory.children)
        if edges > 8192:
            _fail("source_shape_invalid")
        for name in directory.children:
            _path(name)
            if "/" in name:
                _fail("source_shape_invalid")
        for field in ("device", "inode", "mode", "mtime_ns", "ctime_ns"):
            _integer(getattr(directory, field))
    for item in original.import_roots:
        if type(item) is not declared.PythonRuntimeImportRoot:
            _fail("source_shape_invalid")
        _text(item.root_label, 128)
        _path(item.relative_path, dot=True)


def _call(checkpoint: Checkpoint, operation: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    checkpoint()
    value = operation(*args, **kwargs)
    checkpoint()
    return value


def _sha(value: object) -> None:
    if type(value) is not str or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        _fail("source_shape_invalid")


def _io_failed(exc: OSError) -> NoReturn:
    error = PythonRuntimeMaterialError("source_io_failed")
    if _CLEANUP_NOTE in getattr(exc, "__notes__", ()):
        error.add_note(_CLEANUP_NOTE)
    raise error from exc


def _identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _cleanup_error(primary: BaseException | None) -> None:
    if primary is not None:
        primary.add_note(_CLEANUP_NOTE)
    else:
        _fail("cleanup_unknown")


class _OwnedFDs:
    def __init__(self, checkpoint: Checkpoint) -> None:
        self.checkpoint = checkpoint
        self.fds: list[tuple[int, tuple[int, int, int] | None]] = []

    def open(self, path: str, flags: int, *, parent: int | None = None) -> tuple[int, os.stat_result]:
        self.checkpoint()
        fd = os.open(path, flags, **({"dir_fd": parent} if parent is not None else {}))
        # Acquisition rollback precedes the post-open checkpoint. An unpinned
        # newly acquired private FD remains ours under the trusted-controller
        # rule; no borrower can see or rebind it through this API.
        self.fds.append((fd, None))
        self.checkpoint()
        self.checkpoint()
        info = os.fstat(fd)
        self.fds[-1] = fd, _identity(info)
        self.checkpoint()
        return fd, info

    def close(self, primary: BaseException | None) -> None:
        uncertain = False
        while self.fds:
            fd, identity = self.fds.pop()
            try:
                if identity is not None and _identity(os.fstat(fd)) != identity:
                    uncertain = True
                    continue  # Known foreign reuse is never closed.
                os.close(fd)
            except BaseException:  # noqa: BLE001 - release all other owned FDs after interrupts
                uncertain = True
        if uncertain:
            _cleanup_error(primary)


@contextmanager
def _owned(checkpoint: Checkpoint):
    resources = _OwnedFDs(checkpoint)
    try:
        yield resources
    finally:
        resources.close(sys.exception())


def _ancestor_same(info: os.stat_result, expected: declared.PythonRuntimeDirectory) -> bool:
    return stat.S_ISDIR(info.st_mode) and info.st_nlink >= 1 and (
        info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode)
    ) == (expected.device, expected.inode, expected.mode)


class _Root:
    def __init__(self, root: declared.PythonRuntimeRoot, directories: dict, resources: _OwnedFDs) -> None:
        self.checkpoint = resources.checkpoint
        self.root = root
        self.links: list[tuple[int | None, str, int, declared.PythonRuntimeDirectory, tuple[int, ...]]] = []
        pins = {pin.path: pin for pin in root.directories}
        parent, path = None, ""
        parts = ("/", *root.path.strip("/").split("/")) if root.path != "/" else ("/",)
        for name in parts:
            path = "/" if name == "/" else path.rstrip("/") + "/" + name
            wanted = pins.get(path)
            if wanted is None:
                _fail("source_shape_invalid")
            before = _call(self.checkpoint, os.stat, name, follow_symlinks=False,
                           **({"dir_fd": parent} if parent is not None else {}))
            if not _ancestor_same(before, wanted):
                _fail("source_drift")
            child, opened = resources.open(name, _DIRECTORY_FLAGS, parent=parent)
            if runtime._fingerprint(before) != runtime._fingerprint(opened):
                _fail("source_drift")
            self.links.append((parent, name, child, wanted, runtime._fingerprint(opened)))
            parent = child
        self.fd = parent
        self.expected = directories[(root.label, ".")]
        self.check()

    def check(self) -> None:
        for parent, name, fd, wanted, fingerprint in reversed(self.links):
            held = _call(self.checkpoint, os.fstat, fd)
            named = _call(self.checkpoint, os.stat, name, follow_symlinks=False,
                          **({"dir_fd": parent} if parent is not None else {}))
            # Ancestor timestamps are not original 171 pins, but the held/name
            # pair must remain identical during this observation.
            if not _ancestor_same(held, wanted) or runtime._fingerprint(held) != runtime._fingerprint(named):
                _fail("source_drift")
            if (held.st_dev, held.st_ino, held.st_mode) != fingerprint[:3]:
                _fail("source_drift")
        if not runtime._same_directory(_call(self.checkpoint, os.fstat, self.fd), self.expected):
            _fail("source_drift")


@contextmanager
def _parents(root: _Root, relative: str, directories: dict):
    parts = () if relative == "." else relative.split("/")
    links, parent = [], root.fd
    with _owned(root.checkpoint) as resources:
        for index, name in enumerate(parts, 1):
            wanted = directories[(root.root.label, "/".join(parts[:index]))]
            before = _call(root.checkpoint, os.stat, name, dir_fd=parent, follow_symlinks=False)
            if not runtime._same_directory(before, wanted):
                _fail("source_drift")
            child, opened = resources.open(name, _DIRECTORY_FLAGS, parent=parent)
            if runtime._fingerprint(before) != runtime._fingerprint(opened):
                _fail("source_drift")
            links.append((parent, name, child, wanted))
            parent = child
        yield parent
        for ancestor, name, child, wanted in reversed(links):
            held = _call(root.checkpoint, os.fstat, child)
            named = _call(root.checkpoint, os.stat, name, dir_fd=ancestor, follow_symlinks=False)
            if not runtime._same_directory(held, wanted) or runtime._fingerprint(held) != runtime._fingerprint(named):
                _fail("source_drift")
        root.check()


def _directory(root: _Root, wanted: runtime.PythonRuntimeTreeDirectory, directories: dict, files: dict) -> None:
    with _parents(root, wanted.relative_path, directories) as fd:
        before = _call(root.checkpoint, os.fstat, fd)
        if not runtime._same_directory(before, wanted):
            _fail("source_drift")
        root.checkpoint()
        entries = os.scandir(fd)
        try:
            root.checkpoint()
            seen: set[str] = set()
            children = set(wanted.children)
            while True:
                root.checkpoint()
                try:
                    entry = next(entries)
                except StopIteration:
                    root.checkpoint()
                    break
                root.checkpoint()
                name = entry.name
                if name not in children or name in seen:
                    _fail("source_drift")
                seen.add(name)
                key = wanted.root_label, name if wanted.relative_path == "." else wanted.relative_path + "/" + name
                info = _call(root.checkpoint, os.stat, name, dir_fd=fd, follow_symlinks=False)
                expected = files.get(key)
                if expected is not None:
                    valid = runtime._same_file(info, expected)
                else:
                    expected = directories.get(key)
                    valid = expected is not None and runtime._same_directory(info, expected)
                if not valid:
                    _fail("source_drift")
            if seen != children or runtime._fingerprint(before) != runtime._fingerprint(_call(root.checkpoint, os.fstat, fd)):
                _fail("source_drift")
        finally:
            primary = sys.exception()
            try:
                entries.close()
            except BaseException:  # noqa: BLE001 - preserve primary source refusal/interrupt
                _cleanup_error(primary)


def _file(root: _Root, wanted: declared.PythonRuntimeFile, directories: dict,
          destination: int | None, payload_digest: Any) -> None:
    parent_path, _, name = wanted.relative_path.rpartition("/")
    with _parents(root, parent_path or ".", directories) as parent, _owned(root.checkpoint) as resources:
        before = _call(root.checkpoint, os.stat, name, dir_fd=parent, follow_symlinks=False)
        if not runtime._same_file(before, wanted):
            _fail("source_drift")
        fd, opened = resources.open(name, _FILE_FLAGS, parent=parent)
        if runtime._fingerprint(opened) != runtime._fingerprint(before):
            _fail("source_drift")
        digest = _call(root.checkpoint, hashlib.sha256)
        count = 0
        while True:
            chunk = _call(root.checkpoint, os.read, fd, min(_CHUNK, wanted.size - count + 1))
            if not chunk:
                break
            count += len(chunk)
            if count > wanted.size:
                _fail("source_drift")
            _call(root.checkpoint, digest.update, chunk)
            if payload_digest is not None:
                _call(root.checkpoint, payload_digest.update, chunk)
            if destination is not None:
                offset = 0
                while offset < len(chunk):
                    written = _call(root.checkpoint, os.write, destination, chunk[offset:])
                    if type(written) is not int or not 0 < written <= len(chunk) - offset:
                        _fail("source_write_failed")
                    offset += written
        if count != wanted.size or _call(root.checkpoint, digest.hexdigest) != wanted.sha256:
            _fail("source_drift")
        after = _call(root.checkpoint, os.fstat, fd)
        named = _call(root.checkpoint, os.stat, name, dir_fd=parent, follow_symlinks=False)
        if runtime._fingerprint(opened) != runtime._fingerprint(after) or runtime._fingerprint(after) != runtime._fingerprint(named):
            _fail("source_drift")


def _scan(tree: runtime.PythonRuntimeTreeManifest, checkpoint: Checkpoint, *,
          read_files: bool, destination: int | None = None, payload_digest: Any = None) -> None:
    directories = {(item.root_label, item.relative_path): item for item in tree.directories}
    files = {(item.root_label, item.relative_path): item for item in tree.declared_manifest.files}
    for original in sorted(tree.declared_manifest.roots, key=lambda item: item.label):
        with _owned(checkpoint) as resources:
            root = _Root(original, directories, resources)
            for key, directory in sorted(directories.items()):
                if key[0] == original.label:
                    _directory(root, directory, directories, files)
            if read_files:
                for key, file in sorted(files.items()):
                    if key[0] == original.label:
                        _file(root, file, directories, destination, payload_digest)
            root.check()


def verify_source(tree: runtime.PythonRuntimeTreeManifest, *, checkpoint: Checkpoint) -> None:
    """Check original source bytes, then close all original metadata/membership."""
    _shape(tree)
    try:
        _scan(tree, checkpoint, read_files=True)
        _scan(tree, checkpoint, read_files=False)
        checkpoint()  # Observe any overrun during the final owned-FD cleanup.
    except OSError as exc:
        _io_failed(exc)


def copy_payload(tree: runtime.PythonRuntimeTreeManifest, destination_fd: int, *, checkpoint: Checkpoint) -> str:
    """Append bounded canonical payload, without taking ownership of destination."""
    _shape(tree)
    if type(destination_fd) is not int or not 0 <= destination_fd <= 2**31 - 1:
        _fail("source_shape_invalid")
    try:
        digest = _call(checkpoint, hashlib.sha256)
        _scan(tree, checkpoint, read_files=True, destination=destination_fd, payload_digest=digest)
        _scan(tree, checkpoint, read_files=False)
        return _call(checkpoint, digest.hexdigest)
    except OSError as exc:
        _io_failed(exc)
