"""Read-only observation of the staged CPython candidate source tree.

This module reopens a source-staging result through no-follow directory
descriptors and checks the complete on-disk inventory against independently
pinned staging, source-tree, and fixed patch inputs. It does not execute source,
apply patches, invoke a build tool, or establish that a future build consumes the
observed bytes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import NoReturn

from . import candidate_build_source

OBSERVATION_SCHEMA = "lunar-static-python-candidate-source-observation-v1"
MAX_OBSERVATION_BYTES = 512 * 1024
_CHUNK = 64 * 1024
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CLAIMS = frozenset({
    "source_execution_performed", "build_performed", "candidate_build_consumption_observed",
    "frozen_headers_generated", "runtime_execution_performed", "runtime_load_protection",
    "production_admission", "general_code_origin_protection",
})


class CandidateBuildSourceObservationError(ValueError):
    """Fixed refusal code that never includes caller paths or file contents."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or re.fullmatch(r"[a-z_]{1,64}", reason) is None:
            reason = "invalid"
        self.reason = "static_python_candidate_source_observation_" + reason
        super().__init__(self.reason)


class _Refusal(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    raise _Refusal(reason)


def _checkpoint(deadline: float, monotonic: Callable[[], float]) -> None:
    try:
        now = monotonic()
        valid = type(now) in {int, float} and math.isfinite(now)
    except Exception as exc:
        raise CandidateBuildSourceObservationError("clock_invalid") from exc
    if not valid:
        _fail("clock_invalid")
    if now >= deadline:
        _fail("wall_timeout")


def _stat_tuple(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _entry_tuple(entry: dict[str, object]) -> tuple[int, ...]:
    return tuple(entry[name] for name in (
        "device", "inode", "raw_mode", "nlink", "size", "mtime_ns", "ctime_ns",
    ))


def _wire_stat(entry: dict[str, object]) -> tuple[int, ...]:
    kind = entry["kind"]
    mode = entry["mode"]
    if kind == "directory":
        raw_mode = stat.S_IFDIR | mode
    elif kind == "file":
        raw_mode = stat.S_IFREG | mode
    else:
        _fail("entry_kind_invalid")
    return (entry["device"], entry["inode"], raw_mode, entry["nlink"], entry["size"],
            entry["mtime_ns"], entry["ctime_ns"])


def _path_parts(destination: object) -> tuple[str, ...]:
    if (type(destination) is not str or not destination.startswith("/")
            or "\\" in destination or "\0" in destination):
        _fail("destination_invalid")
    try:
        encoded = destination.encode("utf-8")
    except UnicodeError:
        _fail("destination_invalid")
    parts = tuple(destination[1:].split("/"))
    if (not parts or len(encoded) > 4096 or len(parts) > 64
            or any(part in {"", ".", ".."} or len(part.encode("utf-8")) > 255 for part in parts)):
        _fail("destination_invalid")
    return parts


def _close(fd: int, *, preserve: bool = False) -> None:
    try:
        os.close(fd)
    except OSError as exc:
        if not preserve:
            raise CandidateBuildSourceObservationError("descriptor_close_failed") from exc


@contextmanager
def _owned_descriptor(fd: int):
    failed = False
    try:
        yield fd
    except BaseException:
        failed = True
        raise
    finally:
        _close(fd, preserve=failed)


def _check_identity(fd: int, expected: tuple[int, ...], reason: str) -> None:
    try:
        actual = _stat_tuple(os.fstat(fd))
    except OSError as exc:
        raise CandidateBuildSourceObservationError("filesystem_observation_failed") from exc
    if actual != expected:
        _fail(reason)


def _open_root(staging: dict[str, object]) -> tuple[int, int, str, list[tuple[int, str, int, tuple[int, int]]]]:
    """Open the staged destination without following any path component."""
    parts = _path_parts(staging["destination"])
    ancestors = staging["ancestor_identities"]
    root_parent = os.open("/", _DIR_FLAGS)
    # Own each descriptor immediately after open.  In particular, fstat/stat
    # below can fail before an ancestor edge is appended to ``held``.
    owned = [root_parent]
    held: list[tuple[int, str, int, tuple[int, int]]] = []
    try:
        root_info = os.fstat(root_parent)
        if (root_info.st_dev, root_info.st_ino) != (ancestors[0]["device"], ancestors[0]["inode"]):
            _fail("ancestor_identity_mismatch")
        current = root_parent
        for index, component in enumerate(parts[:-1], start=1):
            child = os.open(component, _DIR_FLAGS, dir_fd=current)
            owned.append(child)
            info = os.fstat(child)
            expected = ancestors[index]
            identity = (info.st_dev, info.st_ino)
            named = os.stat(component, dir_fd=current, follow_symlinks=False)
            if (not stat.S_ISDIR(info.st_mode)
                    or identity != (expected["device"], expected["inode"])
                    or (named.st_dev, named.st_ino) != identity or not stat.S_ISDIR(named.st_mode)):
                _fail("ancestor_identity_mismatch")
            held.append((current, component, child, identity))
            current = child
        leaf = parts[-1]
        root_fd = os.open(leaf, _DIR_FLAGS, dir_fd=current)
        owned.append(root_fd)
        root_stat = os.fstat(root_fd)
        named_root = os.stat(leaf, dir_fd=current, follow_symlinks=False)
        if (not stat.S_ISDIR(root_stat.st_mode)
                or _stat_tuple(root_stat) != _entry_tuple(staging["tree_identity"])
                or _stat_tuple(named_root) != _entry_tuple(staging["tree_identity"])):
            _fail("root_identity_mismatch")
        # Ownership transfers to the caller, which closes the full chain with
        # _close_root().
        owned.clear()
        return root_fd, current, leaf, held
    except BaseException:
        # Close every successfully opened descriptor, including one that has
        # not yet been recorded in ``held`` because its verification failed.
        for fd in reversed(owned):
            _close(fd, preserve=True)
        raise


def _close_root(
    root_fd: int,
    parent_fd: int,
    held: list[tuple[int, str, int, tuple[int, int]]],
    *,
    preserve: bool,
) -> None:
    # Every child in held is the next parent. Close each child once; root_parent
    # is the first parent and remains separately owned.
    failures = False
    descriptors = [root_fd]
    for _parent, _name, child, _identity in held:
        if child not in descriptors:
            descriptors.append(child)
    first_parent = held[0][0] if held else parent_fd
    if first_parent not in descriptors:
        descriptors.append(first_parent)
    for fd in descriptors:
        try:
            os.close(fd)
        except OSError:
            failures = True
    if failures and not preserve:
        raise CandidateBuildSourceObservationError("descriptor_close_failed")


def _verify_held_edges(held: list[tuple[int, str, int, tuple[int, int]]]) -> None:
    for parent_fd, name, child_fd, identity in held:
        try:
            before = os.fstat(child_fd)
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise CandidateBuildSourceObservationError("ancestor_replaced") from exc
        if (not stat.S_ISDIR(before.st_mode) or (before.st_dev, before.st_ino) != identity
                or (named.st_dev, named.st_ino) != identity or not stat.S_ISDIR(named.st_mode)):
            _fail("ancestor_replaced")


def _open_relative_directory(root_fd: int, path: str, entries: dict[str, dict[str, object]]) -> int:
    current = os.dup(root_fd)
    if path == "":
        return current
    prefix = ""
    try:
        for component in path.split("/"):
            prefix = prefix + "/" + component if prefix else component
            expected = entries[prefix]
            child = os.open(component, _DIR_FLAGS, dir_fd=current)
            try:
                if _stat_tuple(os.fstat(child)) != _wire_stat(expected):
                    _fail("directory_identity_drift")
                named = os.stat(component, dir_fd=current, follow_symlinks=False)
                if ((named.st_dev, named.st_ino) != (expected["device"], expected["inode"])
                        or not stat.S_ISDIR(named.st_mode)):
                    _fail("directory_replaced")
            except BaseException:
                _close(child, preserve=True)
                raise
            previous, current = current, child
            _close(previous)
        return current
    except BaseException:
        _close(current, preserve=True)
        raise


def _source_tree_digest(
    staging: dict[str, object],
    patch: dict[str, object],
    *,
    expected_source_tree_sha256: str,
    deadline: float,
    monotonic: Callable[[], float],
) -> tuple[str, int]:
    """Join the staged pre/postimage records to the fixed source pins."""
    patch_files = {item["path"]: item for item in patch["files"]}
    root = staging["root"]
    if root != "Python-" + patch["source_version"]:
        _fail("staging_source_version_mismatch")
    patch_paths = {root + "/" + path for path in patch_files}
    staged_file_paths: set[str] = set()
    for entry in staging["entries"]:
        _checkpoint(deadline, monotonic)
        if entry["kind"] == "file":
            staged_file_paths.add(entry["path"])
    if patch_paths - staged_file_paths:
        _fail("staging_patch_inventory_mismatch")
    files: list[dict[str, object]] = []
    total = 0
    for entry in staging["entries"]:
        _checkpoint(deadline, monotonic)
        if entry["kind"] != "file":
            continue
        path = entry["path"]
        if path == root or not path.startswith(root + "/"):
            _fail("staged_path_invalid")
        relative = path[len(root) + 1:]
        item = patch_files.get(relative)
        if item is None:
            if entry["source_sha256"] != entry["staged_sha256"]:
                _fail("staging_unpatched_file_drift")
            size = entry["size"]
        else:
            if (entry["source_sha256"] != item["before_sha256"]
                    or entry["staged_sha256"] != item["after_sha256"]
                    or entry["size"] != item["after_size"]):
                _fail("staging_patch_image_mismatch")
            size = item["before_size"]
        files.append({"path": path, "mode": entry["archive_mode"],
                      "size": size, "sha256": entry["source_sha256"]})
        total += size
        if total > candidate_build_source.MAX_STAGING_BYTES:
            _fail("source_tree_size_exceeded")
    tree = {
        "schema": "lunar-static-python-source-tree-v1", "archive": staging["archive"],
        "root": root, "version": patch["source_version"],
        "files": sorted(files, key=lambda item: item["path"]),
    }
    raw = json.dumps(tree, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if not 0 < len(raw) <= candidate_build_source.MAX_STAGING_BYTES:
        _fail("source_tree_wire_exceeded")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_source_tree_sha256:
        _fail("source_tree_pin_mismatch")
    _checkpoint(deadline, monotonic)
    return digest, total


def _list_children(
    fd: int,
    expected: set[str],
    *,
    deadline: float,
    monotonic: Callable[[], float],
    reason: str,
) -> None:
    """Compare a directory inventory with bounded memory and deadline checks."""
    observed: set[str] = set()
    try:
        with os.scandir(fd) as iterator:
            for entry in iterator:
                _checkpoint(deadline, monotonic)
                name = entry.name
                if name not in expected or name in observed:
                    _fail(reason)
                observed.add(name)
                # An attacker-created oversized directory cannot force us to
                # materialize an unbounded list before detecting the mismatch.
                if len(observed) > len(expected):
                    _fail(reason)
    except OSError as exc:
        raise CandidateBuildSourceObservationError("filesystem_observation_failed") from exc
    if observed != expected:
        _fail(reason)
    _checkpoint(deadline, monotonic)


@dataclass(frozen=True, slots=True)
class CandidateBuildSourceObservation:
    canonical_json: bytes
    observation_sha256: str
    staging_manifest_sha256: str
    staged_tree_sha256: str
    source_tree_sha256: str
    patch_set_sha256: str
    file_count: int
    directory_count: int
    total_staged_bytes: int

    def to_dict(self) -> dict[str, object]:
        return json.loads(self.canonical_json)


def observe_staged_candidate_source_tree(
    staging_manifest: bytes,
    *,
    expected_staging_manifest_sha256: str,
    patch_policy: bytes,
    expected_patch_set_sha256: str,
    expected_source_tree_sha256: str,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> CandidateBuildSourceObservation:
    """Verify the complete staged source tree against fixed, external pins.

    The source staging manifest and patch policy must be retained separately;
    their expected digests are not derived from the supplied records. Every
    staged path is opened relative to no-follow directory descriptors and every
    regular file is rehashed. The result records observed source provenance only.
    """
    if (type(deadline) is not float or not math.isfinite(deadline) or deadline <= 0
            or not callable(monotonic)):
        raise CandidateBuildSourceObservationError("deadline_invalid")
    try:
        _checkpoint(deadline, monotonic)
        staging, staged_tree_sha256 = candidate_build_source._validate_staging(
            staging_manifest, expected_staging_manifest_sha256,
        )
        patch, _patch_files = candidate_build_source._validate_patch_set(
            patch_policy, expected_patch_set_sha256,
        )
        _checkpoint(deadline, monotonic)
        if hashlib.sha256(patch_policy).hexdigest() != staging["policy_sha256"]:
            _fail("patch_policy_pin_mismatch")
        if staging["patch_set_sha256"] != expected_patch_set_sha256:
            _fail("patch_set_pin_mismatch")
        candidate_build_source._sha(expected_source_tree_sha256, "source_tree_pin_invalid")
        source_tree_sha256, total_source_bytes = _source_tree_digest(
            staging, patch, expected_source_tree_sha256=expected_source_tree_sha256,
            deadline=deadline, monotonic=monotonic,
        )

        entries: dict[str, dict[str, object]] = {}
        directories: dict[str, dict[str, object]] = {}
        files: dict[str, dict[str, object]] = {}
        for item in staging["entries"]:
            _checkpoint(deadline, monotonic)
            entries[item["path"]] = item
            if item["kind"] == "directory":
                directories[item["path"]] = item
            elif item["kind"] == "file":
                files[item["path"]] = item
        children: dict[str, set[str]] = {"": set()}
        for path in entries:
            _checkpoint(deadline, monotonic)
            parent, _, leaf = path.rpartition("/")
            children.setdefault(parent, set()).add(leaf)
            if entries[path]["kind"] == "directory":
                children.setdefault(path, set())
        if set(children) - ({""} | set(directories)):
            _fail("staging_inventory_invalid")

        root_fd, parent_fd, leaf, held = _open_root(staging)
        failed = False
        try:
            total_staged_bytes = 0
            _list_children(
                root_fd, children[""], deadline=deadline, monotonic=monotonic,
                reason="destination_inventory_mismatch",
            )
            for path in sorted(directories, key=lambda value: (value.count("/"), value)):
                _checkpoint(deadline, monotonic)
                fd = _open_relative_directory(root_fd, path, directories)
                with _owned_descriptor(fd):
                    expected = directories[path]
                    if _stat_tuple(os.fstat(fd)) != _wire_stat(expected):
                        _fail("directory_identity_drift")
                    _list_children(
                        fd, children[path], deadline=deadline, monotonic=monotonic,
                        reason="directory_inventory_mismatch",
                    )
                    if _stat_tuple(os.fstat(fd)) != _wire_stat(expected):
                        _fail("directory_identity_drift")

            for path in sorted(files):
                _checkpoint(deadline, monotonic)
                parent, _, name = path.rpartition("/")
                parent_handle = _open_relative_directory(root_fd, parent, directories)
                with _owned_descriptor(parent_handle):
                    expected = files[path]
                    fd = os.open(name, _FILE_FLAGS, dir_fd=parent_handle)
                    with _owned_descriptor(fd):
                        before = os.fstat(fd)
                        if _stat_tuple(before) != _wire_stat(expected) or not stat.S_ISREG(before.st_mode):
                            _fail("file_identity_drift")
                        digest = hashlib.sha256()
                        size = 0
                        while True:
                            _checkpoint(deadline, monotonic)
                            block = os.read(fd, _CHUNK)
                            _checkpoint(deadline, monotonic)
                            if not block:
                                break
                            size += len(block)
                            if size > expected["size"] or size > candidate_build_source.MAX_STAGING_BYTES:
                                _fail("file_size_exceeded")
                            digest.update(block)
                        after = os.fstat(fd)
                        named = os.stat(name, dir_fd=parent_handle, follow_symlinks=False)
                        expected_sha = expected["staged_sha256"]
                        if (size != expected["size"] or digest.hexdigest() != expected_sha
                                or _stat_tuple(after) != _wire_stat(expected)
                                or _stat_tuple(named) != _wire_stat(expected)):
                            _fail("file_content_drift")
                        total_staged_bytes += size
                        if total_staged_bytes > candidate_build_source.MAX_STAGING_BYTES:
                            _fail("staged_tree_size_exceeded")

            # A second metadata/inventory pass catches replacement or mutation
            # after a file was hashed. Content writes cannot restore ctime.
            for path in sorted(directories, key=lambda value: (value.count("/"), value)):
                _checkpoint(deadline, monotonic)
                fd = _open_relative_directory(root_fd, path, directories)
                with _owned_descriptor(fd):
                    if (_stat_tuple(os.fstat(fd)) != _wire_stat(directories[path])
                            ):
                        _fail("directory_changed_after_read")
                    _list_children(
                        fd, children[path], deadline=deadline, monotonic=monotonic,
                        reason="directory_changed_after_read",
                    )
                    if _stat_tuple(os.fstat(fd)) != _wire_stat(directories[path]):
                        _fail("directory_changed_after_read")
            _list_children(
                root_fd, children[""], deadline=deadline, monotonic=monotonic,
                reason="destination_changed_after_read",
            )
            for path in sorted(files):
                _checkpoint(deadline, monotonic)
                parent, _, name = path.rpartition("/")
                parent_handle = _open_relative_directory(root_fd, parent, directories)
                with _owned_descriptor(parent_handle):
                    expected = files[path]
                    named = os.stat(name, dir_fd=parent_handle, follow_symlinks=False)
                    if _stat_tuple(named) != _wire_stat(expected):
                        _fail("file_changed_after_read")
            # Confirm directory inventories once more after checking file
            # names. This narrows the observation window for late entries in
            # empty or otherwise unread directories; the walk remains a
            # sequential observation rather than an atomic snapshot.
            for path in sorted(directories, key=lambda value: (value.count("/"), value)):
                _checkpoint(deadline, monotonic)
                fd = _open_relative_directory(root_fd, path, directories)
                with _owned_descriptor(fd):
                    if _stat_tuple(os.fstat(fd)) != _wire_stat(directories[path]):
                        _fail("directory_changed_after_read")
                    _list_children(
                        fd, children[path], deadline=deadline, monotonic=monotonic,
                        reason="directory_changed_after_read",
                    )
            _list_children(
                root_fd, children[""], deadline=deadline, monotonic=monotonic,
                reason="destination_changed_after_read",
            )
            _verify_held_edges(held)
            _check_identity(root_fd, _entry_tuple(staging["tree_identity"]), "root_changed_after_read")
            named_root = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            if _stat_tuple(named_root) != _entry_tuple(staging["tree_identity"]):
                _fail("root_replaced")
            _checkpoint(deadline, monotonic)
        except BaseException:
            failed = True
            raise
        finally:
            _close_root(root_fd, parent_fd, held, preserve=failed)

        record = {
            "schema": OBSERVATION_SCHEMA,
            "status": "staged-source-observed",
            "staging_manifest_sha256": expected_staging_manifest_sha256,
            "staged_tree_sha256": staged_tree_sha256,
            "source_tree_sha256": source_tree_sha256,
            "patch_set_sha256": expected_patch_set_sha256,
            "file_count": len(files), "directory_count": len(directories),
            "total_source_bytes": total_source_bytes, "total_staged_bytes": total_staged_bytes,
            "claims": dict.fromkeys(_CLAIMS, False),
        }
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if not 0 < len(raw) <= MAX_OBSERVATION_BYTES:
            _fail("observation_wire_exceeded")
        _checkpoint(deadline, monotonic)
        return CandidateBuildSourceObservation(
            raw, hashlib.sha256(raw).hexdigest(), expected_staging_manifest_sha256,
            staged_tree_sha256, source_tree_sha256, expected_patch_set_sha256,
            len(files), len(directories), total_staged_bytes,
        )
    except _Refusal as exc:
        raise CandidateBuildSourceObservationError(exc.reason) from None
    except CandidateBuildSourceObservationError:
        raise
    except candidate_build_source.CandidateBuildSourceError as exc:
        raise CandidateBuildSourceObservationError(exc.reason.removeprefix("static_python_candidate_build_source_")) from None
    except (OSError, KeyError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise CandidateBuildSourceObservationError("observation_invalid") from None


__all__ = [
    "OBSERVATION_SCHEMA",
    "CandidateBuildSourceObservation",
    "CandidateBuildSourceObservationError",
    "observe_staged_candidate_source_tree",
]
