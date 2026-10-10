"""Create-only local source staging from one verified immutable archive snapshot.

Partial writes are deliberately retained. No existing tree is adopted or repaired;
this is not an execution, release-authentication or production-admission API.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import NoReturn

from .archive_observation import StaticPythonArchiveSnapshot
from .source_projection import StaticPythonSourceProjectionError, _prepare_archive_sources

SOURCE_STAGING_SCHEMA = "lunar-static-python-source-staging-v1"
MAX_STAGED_ENTRIES = 131_072
MAX_STAGED_DEPTH = 64
_CHUNK = 64 * 1024
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class StaticPythonSourceStagingError(ValueError):
    """A fixed reason, without caller paths or source content."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_source_staging_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonSourceStagingError(reason)


@dataclass(frozen=True, slots=True)
class StaticPythonSourceStaging:
    schema: str
    destination: str
    root_directory: str
    canonical_json: bytes
    staging_sha256: str
    extraction_performed: bool = True
    fixed_patches_staged: bool = True
    release_verified: bool = False
    source_execution_performed: bool = False
    build_performed: bool = False
    frozen_headers_generated: bool = False
    runtime_execution_performed: bool = False
    runtime_load_protection: bool = False
    production_admission: bool = False
    general_code_origin_protection: bool = False

    def to_manifest(self) -> dict[str, object]:
        return json.loads(self.canonical_json)


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _directory_identity(info: os.stat_result) -> tuple[int, int, int]:
    if not stat.S_ISDIR(info.st_mode):
        _fail("directory_invalid")
    return info.st_dev, info.st_ino, info.st_mode


def _stat_wire(info: os.stat_result) -> dict[str, int]:
    return {"device": info.st_dev, "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode),
            "nlink": info.st_nlink, "size": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def _close_fd(fd: int, *, preserve_primary: bool = False) -> None:
    # Never replace an original refusal with cleanup uncertainty. A successful
    # operation with uncertain cleanup still cannot produce a success result.
    try:
        os.close(fd)
    except OSError as exc:
        if not preserve_primary:
            raise StaticPythonSourceStagingError("descriptor_close_failed") from exc


@contextmanager
def _owned_descriptor(fd: int):
    failed = False
    try:
        yield fd
    except BaseException:
        failed = True
        raise
    finally:
        _close_fd(fd, preserve_primary=failed)


def _destination_parts(destination: object) -> tuple[str, ...]:
    if (type(destination) is not str or not destination.startswith("/")
            or "\\" in destination or "\0" in destination):
        _fail("destination_invalid")
    try:
        encoded = destination.encode("utf-8")
    except UnicodeError:
        _fail("destination_invalid")
    parts = tuple(destination[1:].split("/"))
    if (len(encoded) > 4096 or len(parts) > MAX_STAGED_DEPTH
            or any(part in {"", ".", ".."} or len(part.encode("utf-8")) > 255
                   for part in parts)):
        _fail("destination_invalid")
    return parts


def stage_archive_sources(
    snapshot: StaticPythonArchiveSnapshot,
    destination: str,
    *,
    expected_manifest_sha256: str,
    require_profile: bool = True,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> StaticPythonSourceStaging:
    """Validate all bytes, then stage once through original directory identities.

    Explicit inert mode is for local fixtures; it never authenticates a release.
    A refusal may leave partial files after creation. Nothing is removed or retried.
    """
    parts = _destination_parts(destination)
    if type(deadline) is not float or not math.isfinite(deadline) or deadline <= 0:
        _fail("deadline_invalid")
    if not callable(monotonic):
        _fail("clock_invalid")

    def checkpoint() -> float:
        try:
            now = monotonic()
            if type(now) not in {int, float} or not math.isfinite(now):
                _fail("clock_invalid")
        except StaticPythonSourceStagingError:
            raise
        except Exception as exc:
            raise StaticPythonSourceStagingError("clock_invalid") from exc
        if now >= deadline:
            _fail("wall_timeout")
        return now

    def digest(raw: bytes) -> str:
        hashed = hashlib.sha256()
        for offset in range(0, len(raw), _CHUNK):
            checkpoint()
            hashed.update(raw[offset:offset + _CHUNK])
            checkpoint()
        checkpoint()
        return hashed.hexdigest()

    checkpoint()
    try:
        prepared, observed, captured = _prepare_archive_sources(
            snapshot, expected_manifest_sha256=expected_manifest_sha256,
            require_profile=require_profile, deadline=deadline, monotonic=monotonic,
            capture_all_files=True,
        )
    except StaticPythonSourceProjectionError as exc:
        raise StaticPythonSourceStagingError(
            "projection_" + exc.reason.removeprefix("static_python_source_projection_"),
        ) from exc
    checkpoint()
    if (type(captured) is not tuple
            or any(type(item) is not tuple or len(item) != 2
                   or type(item[0]) is not str or type(item[1]) is not bytes for item in captured)):
        _fail("payload_invalid")
    payloads = dict(captured)
    members = {member.path: member for member in observed.members}
    if (len(payloads) != len(captured)
            or set(payloads) != {path for path, member in members.items() if member.kind == "file"}):
        _fail("payload_inventory_mismatch")
    replacements = {item.archive_path: item for item in prepared.sources}
    staged: dict[str, bytes] = {}
    directories: set[str] = set()
    if len(payloads) > MAX_STAGED_ENTRIES:
        _fail("entry_count_exceeded")

    def add_directory(path: str) -> None:
        if path not in directories:
            if len(directories) + len(payloads) >= MAX_STAGED_ENTRIES:
                _fail("entry_count_exceeded")
            directories.add(path)

    for path, member in members.items():
        checkpoint()
        if len(path.split("/")) > MAX_STAGED_DEPTH:
            _fail("entry_depth_exceeded")
        parent = path.rpartition("/")[0]
        while parent:
            add_directory(parent)
            parent = parent.rpartition("/")[0]
        if member.kind == "directory":
            add_directory(path)
        else:
            raw = payloads[path]
            if len(raw) != member.size or digest(raw) != member.sha256:
                _fail("payload_member_mismatch")
            if path in replacements:
                replacement = replacements[path]
                if (replacement.preimage_bytes != raw
                        or digest(replacement.postimage_bytes) != replacement.postimage_sha256):
                    _fail("patch_projection_mismatch")
                raw = replacement.postimage_bytes
            staged[path] = raw
    if len(directories) + len(staged) > MAX_STAGED_ENTRIES:
        _fail("entry_count_exceeded")
    staged_digests = {path: digest(raw) for path, raw in staged.items()}
    checkpoint()

    # Ancestor handles are retained for the whole operation. Subtree descriptors
    # are bounded by path depth and reopened only against original creation pins.
    ancestors: list[int] = []
    edges: list[tuple[int, str, int, tuple[int, int, int]]] = []
    tree_fd: int | None = None
    directory_pins: dict[str, tuple[int, int, int]] = {}
    file_pins: dict[str, tuple[int, ...]] = {}
    dest_leaf = parts[-1]

    def guard(*, check_clock: bool = True) -> None:
        if check_clock:
            checkpoint()
        for parent_fd, leaf, child_fd, original in edges:
            if (_directory_identity(os.fstat(child_fd)) != original
                    or _directory_identity(os.stat(leaf, dir_fd=parent_fd,
                                                    follow_symlinks=False)) != original):
                _fail("ancestor_drift")
        if tree_fd is not None:
            original = directory_pins[""]
            if (_directory_identity(os.fstat(tree_fd)) != original
                    or _directory_identity(os.stat(dest_leaf, dir_fd=ancestors[-1],
                                                    follow_symlinks=False)) != original):
                _fail("destination_drift")
        if check_clock:
            checkpoint()

    @contextmanager
    def directory(path: str, *, check_clock: bool = True):
        guard(check_clock=check_clock)
        assert tree_fd is not None
        current = os.dup(tree_fd)
        prefix = ""
        failed = False
        try:
            for leaf in path.split("/") if path else ():
                if check_clock:
                    checkpoint()
                prefix = prefix + "/" + leaf if prefix else leaf
                original = directory_pins[prefix]
                child = os.open(leaf, _DIR_FLAGS, dir_fd=current)
                try:
                    if (_directory_identity(os.fstat(child)) != original
                            or _directory_identity(os.stat(leaf, dir_fd=current,
                                                           follow_symlinks=False)) != original):
                        _fail("directory_drift")
                except BaseException:
                    _close_fd(child, preserve_primary=True)
                    raise
                previous, current = current, child
                _close_fd(previous)
            if check_clock:
                checkpoint()
            yield current
        except BaseException:
            failed = True
            raise
        finally:
            _close_fd(current, preserve_primary=failed)

    def readback(fd: int, expected: bytes, expected_sha: str) -> None:
        before = _identity(os.fstat(fd))
        os.lseek(fd, 0, os.SEEK_SET)
        hashed = hashlib.sha256()
        size = 0
        while True:
            checkpoint()
            chunk = os.read(fd, min(_CHUNK, len(expected) - size + 1))
            checkpoint()
            if type(chunk) is not bytes or len(chunk) > min(_CHUNK, len(expected) - size + 1):
                _fail("readback_invalid")
            if not chunk:
                break
            size += len(chunk)
            if size > len(expected):
                _fail("readback_mismatch")
            hashed.update(chunk)
        if (size != len(expected) or hashed.hexdigest() != expected_sha
                or _identity(os.fstat(fd)) != before):
            _fail("readback_mismatch")
        checkpoint()

    operation_failed = False
    try:
        ancestors.append(os.open("/", _DIR_FLAGS))
        for leaf in parts[:-1]:
            checkpoint()
            parent_fd = ancestors[-1]
            child_fd = os.open(leaf, _DIR_FLAGS, dir_fd=parent_fd)
            ancestors.append(child_fd)
            original = _directory_identity(os.fstat(child_fd))
            edges.append((parent_fd, leaf, child_fd, original))
            guard()
        guard()
        os.mkdir(dest_leaf, 0o700, dir_fd=ancestors[-1])
        created = os.stat(dest_leaf, dir_fd=ancestors[-1], follow_symlinks=False)
        directory_pins[""] = _directory_identity(created)
        if stat.S_IMODE(created.st_mode) != 0o700:
            _fail("directory_mode_invalid")
        tree_fd = os.open(dest_leaf, _DIR_FLAGS, dir_fd=ancestors[-1])
        guard()
        for path in sorted(directories, key=lambda value: (value.count("/"), value)):
            parent, _, leaf = path.rpartition("/")
            with directory(parent) as parent_fd:
                os.mkdir(leaf, 0o700, dir_fd=parent_fd)
                created = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                directory_pins[path] = _directory_identity(created)
                if stat.S_IMODE(created.st_mode) != 0o700:
                    _fail("directory_mode_invalid")
                with directory(path) as child_fd:
                    os.fsync(child_fd)
                os.fsync(parent_fd)
                guard()
        for path in sorted(staged):
            raw = staged[path]
            parent, _, leaf = path.rpartition("/")
            with (
                directory(parent) as parent_fd,
                _owned_descriptor(os.open(leaf, _FILE_FLAGS, 0o600, dir_fd=parent_fd)) as fd,
            ):
                initial = os.fstat(fd)
                if (not stat.S_ISREG(initial.st_mode) or stat.S_IMODE(initial.st_mode) != 0o600
                        or initial.st_nlink != 1 or initial.st_size != 0):
                    _fail("file_invalid")
                offset = 0
                while offset < len(raw):
                    guard()
                    block = raw[offset:offset + _CHUNK]
                    written = os.write(fd, block)
                    if type(written) is not int or not 0 < written <= len(block):
                        _fail("write_progress_invalid")
                    offset += written
                    checkpoint()
                os.fsync(fd)
                after = os.fstat(fd)
                if (after.st_dev != initial.st_dev or after.st_ino != initial.st_ino
                        or not stat.S_ISREG(after.st_mode) or stat.S_IMODE(after.st_mode) != 0o600
                        or after.st_nlink != 1 or after.st_size != len(raw)):
                    _fail("file_drift")
                readback(fd, raw, staged_digests[path])
                if _identity(os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)) != _identity(after):
                    _fail("file_drift")
                file_pins[path] = _identity(after)
                os.fsync(parent_fd)
                guard()

        # Exact final inventory and original inode readback, including implicit
        # directories. This detects later modification of an earlier staged file.
        children: dict[str, set[str]] = {path: set() for path in directory_pins}
        for path in directories | set(staged):
            parent, _, leaf = path.rpartition("/")
            children[parent].add(leaf)
        final_directory_stats: dict[str, tuple[int, ...]] = {}
        entries = []
        for path in sorted(directory_pins):
            with directory(path) as fd:
                before = os.fstat(fd)
                if set(os.listdir(fd)) != children[path]:
                    _fail("inventory_drift")
                os.fsync(fd)
                after = os.fstat(fd)
                if _identity(before) != _identity(after):
                    _fail("directory_drift")
                final_directory_stats[path] = _identity(after)
                if path:
                    member = members.get(path)
                    entries.append({"path": path, "kind": "directory", "implicit": member is None,
                                    "source_sha256": None, "staged_sha256": None,
                                    "archive_mode": None if member is None else member.mode,
                                    **_stat_wire(after)})
        for path in sorted(staged):
            parent, _, leaf = path.rpartition("/")
            with (
                directory(parent) as parent_fd,
                _owned_descriptor(os.open(leaf, _READ_FLAGS, dir_fd=parent_fd)) as fd,
            ):
                info = os.fstat(fd)
                if _identity(info) != file_pins[path]:
                    _fail("file_drift")
                readback(fd, staged[path], staged_digests[path])
                if _identity(os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)) != file_pins[path]:
                    _fail("file_drift")
                entries.append({"path": path, "kind": "file", "implicit": False,
                                "source_sha256": members[path].sha256,
                                "staged_sha256": staged_digests[path],
                                "archive_mode": members[path].mode, **_stat_wire(info)})
        for path, expected in final_directory_stats.items():
            with directory(path) as fd:
                if _identity(os.fstat(fd)) != expected:
                    _fail("directory_drift")
        os.fsync(ancestors[-1])
        guard()
        manifest = {
            "schema": SOURCE_STAGING_SCHEMA, "destination": destination,
            "root": observed.root, "root_directory": destination + "/" + observed.root,
            "archive": observed.archive, "archive_sha256": observed.archive_sha256,
            "snapshot_sha256": observed.snapshot_sha256, "manifest_sha256": observed.manifest_sha256,
            "projection_sha256": prepared.projection_sha256,
            "policy_sha256": prepared.policy_sha256, "patch_set_sha256": prepared.patch_set_sha256,
            "profile_pin_verified": prepared.profile_pin_verified,
            "metadata_validation": prepared.metadata_validation,
            "source_preimages_checked": True, "signature_verification": "not-performed",
            "tree_identity": dict(zip(("device", "inode", "raw_mode", "nlink", "size",
                                       "mtime_ns", "ctime_ns"), final_directory_stats[""])),
            "ancestor_identities": [{"device": os.fstat(fd).st_dev, "inode": os.fstat(fd).st_ino}
                                    for fd in ancestors],
            "entries": sorted(entries, key=lambda item: item["path"]),
            "extraction_performed": True, "fixed_patches_staged": True,
            "release_verified": False, "source_execution_performed": False,
            "build_performed": False, "frozen_headers_generated": False,
            "runtime_execution_performed": False, "runtime_load_protection": False,
            "production_admission": False, "general_code_origin_protection": False,
        }
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode("utf-8")
        result = StaticPythonSourceStaging(
            SOURCE_STAGING_SCHEMA, destination, destination + "/" + observed.root,
            canonical, digest(canonical),
        )
        guard()
        # The last caller clock can perform work. Recheck all retained objects
        # after it, without invoking another caller callback. Charge elapsed host
        # time against its last original-clock observation, never a fresh budget.
        final_started = time.perf_counter()
        final_now = checkpoint()
        for path, expected in final_directory_stats.items():
            with directory(path, check_clock=False) as fd:
                if (_identity(os.fstat(fd)) != expected
                        or set(os.listdir(fd)) != children[path]):
                    _fail("directory_drift")
                for leaf in children[path]:
                    child_path = path + "/" + leaf if path else leaf
                    info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
                    expected_child = (file_pins[child_path] if child_path in file_pins
                                      else final_directory_stats[child_path])
                    if _identity(info) != expected_child:
                        _fail("file_drift" if child_path in file_pins else "directory_drift")
        guard(check_clock=False)
        elapsed = time.perf_counter() - final_started
        if not math.isfinite(elapsed) or elapsed < 0 or final_now + elapsed >= deadline:
            _fail("wall_timeout")
    except OSError as exc:
        operation_failed = True
        raise StaticPythonSourceStagingError("filesystem_refused") from exc
    except BaseException:
        operation_failed = True
        raise
    finally:
        closing_failed = False
        for fd in ([tree_fd] if tree_fd is not None else []) + list(reversed(ancestors)):
            try:
                os.close(fd)
            except OSError:
                closing_failed = True
        if closing_failed and not operation_failed:
            _fail("descriptor_close_failed")
    # Success is returned only after owned descriptor cleanup; its cost belongs
    # to the same original budget as validation and writes.
    elapsed = time.perf_counter() - final_started
    if not math.isfinite(elapsed) or elapsed < 0 or final_now + elapsed >= deadline:
        _fail("wall_timeout")
    return result


__all__ = ["SOURCE_STAGING_SCHEMA", "StaticPythonSourceStaging", "StaticPythonSourceStagingError",
           "stage_archive_sources"]
