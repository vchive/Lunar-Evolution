"""Compare one concrete Zig tree with an independently pinned archive inventory.

This is a sequential, read-only filesystem observation, not immutable custody
or evidence that a later compiler consumes the observed tree. The complete
inventory keeps extraction-manifest-v1; only a small observation record is new.
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
from typing import NoReturn

from . import candidate_build_source_observation as fd_observation
from . import verified_inputs
from .toolchain_observation import StaticPythonToolchainObservation

TOOLCHAIN_TREE_OBSERVATION_SCHEMA = "lunar-static-python-toolchain-tree-observation-v1"
MAX_TOOLCHAIN_TREE_OBSERVATION_BYTES = 16 * 1024
_CHUNK = 64 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CLAIMS = (
    "archive_acquisition_observed", "archive_signature_verified",
    "toolchain_execution_performed", "configure_performed", "build_performed",
    "runtime_execution_performed", "future_build_consumption_observed",
    "immutable_custody_established", "production_admission", "online_publication",
)


class StaticPythonToolchainTreeObservationError(ValueError):
    """Fixed refusal codes without paths, source bytes or clock messages."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or re.fullmatch(r"[a-z_]{1,80}", reason) is None:
            reason = "invalid"
        self.reason = "static_python_toolchain_tree_observation_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonToolchainTreeObservationError(reason)


def _checkpoint(deadline: float, monotonic: Callable[[], float]) -> None:
    try:
        now = monotonic()
        valid = type(now) in {int, float} and math.isfinite(now)
    except Exception:  # noqa: BLE001 - redact arbitrary caller-clock failures.
        raise StaticPythonToolchainTreeObservationError("clock_invalid") from None
    if not valid:
        _fail("clock_invalid")
    if now >= deadline:
        _fail("wall_timeout")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("manifest_duplicate_key")
        result[key] = value
    return result


def _json_constant(_value: str) -> NoReturn:
    _fail("manifest_json_invalid")


def _manifest(raw: bytes, pin: str) -> verified_inputs.StaticPythonExtractionManifest:
    if type(raw) is not bytes or not 0 < len(raw) <= verified_inputs.MAX_EXTRACTION_MANIFEST_BYTES:
        _fail("manifest_wire_invalid")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_float=_json_constant, parse_constant=_json_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        if isinstance(exc, StaticPythonToolchainTreeObservationError):
            raise
        raise StaticPythonToolchainTreeObservationError("manifest_json_invalid") from None
    manifest = verified_inputs.validate_static_python_extraction_manifest(value, expected_sha256=pin)
    if manifest.archive != "zig":
        _fail("archive_invalid")
    if manifest.canonical_json != raw:
        _fail("manifest_canonical_invalid")
    return manifest


def _open_tree(parts: tuple[str, ...], checkpoint: Callable[[], None]):
    """Acquire a root without pretending that an earlier staging DTO pinned it."""
    checkpoint()
    current = os.open("/", fd_observation._DIR_FLAGS)
    owned = [current]
    held = []
    try:
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            _fail("ancestor_identity_mismatch")
        for component in parts[:-1]:
            checkpoint()
            child = os.open(component, fd_observation._DIR_FLAGS, dir_fd=current)
            owned.append(child)
            before = os.fstat(child)
            named = os.stat(component, dir_fd=current, follow_symlinks=False)
            identity = (before.st_dev, before.st_ino)
            if (not stat.S_ISDIR(before.st_mode) or not stat.S_ISDIR(named.st_mode)
                    or (named.st_dev, named.st_ino) != identity):
                _fail("ancestor_identity_mismatch")
            held.append((current, component, child, identity))
            current = child
        checkpoint()
        leaf = parts[-1]
        root_fd = os.open(leaf, fd_observation._DIR_FLAGS, dir_fd=current)
        owned.append(root_fd)
        before = os.fstat(root_fd)
        named = os.stat(leaf, dir_fd=current, follow_symlinks=False)
        if (not stat.S_ISDIR(before.st_mode)
                or fd_observation._stat_tuple(before) != fd_observation._stat_tuple(named)):
            _fail("root_identity_mismatch")
        checkpoint()
        owned.clear()
        return root_fd, current, leaf, held, before
    except BaseException:
        for fd in reversed(owned):
            fd_observation._close(fd, preserve=True)
        raise


def _directory_pin(info: os.stat_result) -> dict[str, object]:
    # Internal observation pins only; there is no second serialized inventory.
    return {
        "kind": "directory", "mode": stat.S_IMODE(info.st_mode),
        "device": info.st_dev, "inode": info.st_ino, "nlink": info.st_nlink,
        "size": info.st_size, "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
    }


def _canonical(record: dict[str, object]) -> bytes:
    try:
        raw = json.dumps(record, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError):
        raise StaticPythonToolchainTreeObservationError("canonical_invalid") from None
    if not 0 < len(raw) <= MAX_TOOLCHAIN_TREE_OBSERVATION_BYTES:
        _fail("record_budget_exceeded")
    return raw


def observe_extracted_toolchain_tree(
    manifest: bytes,
    *,
    expected_manifest_sha256: str,
    tree_directory: str,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> StaticPythonToolchainObservation:
    """Compare a complete Zig tree with a separately retained canonical manifest.

    ``tree_directory`` is the root itself, corresponding to the manifest's root
    member. Its parent siblings are outside this observation. Every parent
    directory of a manifest entry must be explicit in that manifest; absolute
    OS-path ancestors are acquired separately. No extraction, tool
    execution or later build-input consumption is performed or authorized.
    """
    if type(deadline) is not float or not math.isfinite(deadline) or deadline <= 0:
        _fail("deadline_invalid")
    if not callable(monotonic):
        _fail("clock_invalid")

    def checkpoint() -> None:
        _checkpoint(deadline, monotonic)

    checkpoint()
    if (type(expected_manifest_sha256) is not str
            or _SHA.fullmatch(expected_manifest_sha256) is None
            or expected_manifest_sha256 in {"0" * 64, "f" * 64}):
        _fail("manifest_pin_invalid")
    try:
        observed = _manifest(manifest, expected_manifest_sha256)
        checkpoint()
        parts = fd_observation._path_parts(tree_directory)
        entries = {}
        for member in observed.members:
            checkpoint()
            relative = "" if member.path == observed.root else member.path[len(observed.root) + 1:]
            entries[relative] = member
        directories = {path: member for path, member in entries.items() if member.kind == "directory"}
        files = {path: member for path, member in entries.items() if member.kind == "file"}
        children: dict[str, set[str]] = {path: set() for path in directories}
        for path in entries:
            checkpoint()
            if not path:
                continue
            parent, _, name = path.rpartition("/")
            if parent not in directories:
                _fail("manifest_parent_directory_missing")
            children[parent].add(name)
        ordered_directories = sorted(directories, key=lambda path: (path.count("/"), path))
        root_fd, parent_fd, leaf, held, root_info = _open_tree(parts, checkpoint)
        failed = False
        try:
            root_identity = fd_observation._stat_tuple(root_info)
            if stat.S_IMODE(root_info.st_mode) != directories[""].mode:
                _fail("directory_mode_mismatch")
            directory_pins = {"": _directory_pin(root_info)}
            fd_observation._list_children(
                root_fd, children[""], deadline=deadline, monotonic=monotonic,
                reason="root_inventory_mismatch",
            )
            for path in ordered_directories:
                checkpoint()
                if not path:
                    continue
                parent, _, name = path.rpartition("/")
                directory_parent = fd_observation._open_relative_directory(root_fd, parent, directory_pins)
                with fd_observation._owned_descriptor(directory_parent):
                    fd = os.open(name, fd_observation._DIR_FLAGS, dir_fd=directory_parent)
                    with fd_observation._owned_descriptor(fd):
                        before = os.fstat(fd)
                        named = os.stat(name, dir_fd=directory_parent, follow_symlinks=False)
                        if (not stat.S_ISDIR(before.st_mode)
                                or stat.S_IMODE(before.st_mode) != directories[path].mode):
                            _fail("directory_mode_mismatch")
                        identity = fd_observation._stat_tuple(before)
                        if identity != fd_observation._stat_tuple(named):
                            _fail("directory_identity_drift")
                        directory_pins[path] = _directory_pin(before)
                        fd_observation._list_children(
                            fd, children[path], deadline=deadline, monotonic=monotonic,
                            reason="directory_inventory_mismatch",
                        )
                        if fd_observation._stat_tuple(os.fstat(fd)) != identity:
                            _fail("directory_identity_drift")

            file_pins = {}
            total_file_bytes = 0
            for path, member in sorted(files.items()):
                checkpoint()
                parent, _, name = path.rpartition("/")
                directory_parent = fd_observation._open_relative_directory(root_fd, parent, directory_pins)
                with fd_observation._owned_descriptor(directory_parent):
                    fd = os.open(name, fd_observation._FILE_FLAGS, dir_fd=directory_parent)
                    with fd_observation._owned_descriptor(fd):
                        before = os.fstat(fd)
                        named = os.stat(name, dir_fd=directory_parent, follow_symlinks=False)
                        identity = fd_observation._stat_tuple(before)
                        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                                or stat.S_IMODE(before.st_mode) != member.mode
                                or before.st_size != member.size
                                or identity != fd_observation._stat_tuple(named)):
                            _fail("file_identity_mismatch")
                        digest = hashlib.sha256()
                        size = 0
                        while True:
                            checkpoint()
                            block = os.read(fd, _CHUNK)
                            checkpoint()
                            if not block:
                                break
                            size += len(block)
                            if size > member.size:
                                _fail("file_size_exceeded")
                            digest.update(block)
                        after = os.fstat(fd)
                        named = os.stat(name, dir_fd=directory_parent, follow_symlinks=False)
                        if (size != member.size or digest.hexdigest() != member.sha256
                                or fd_observation._stat_tuple(after) != identity
                                or fd_observation._stat_tuple(named) != identity):
                            _fail("file_content_drift")
                        file_pins[path] = identity
                        total_file_bytes += size
                        if total_file_bytes > observed.total_bytes:
                            _fail("tree_size_exceeded")

            def verify_directories() -> None:
                for path in ordered_directories:
                    checkpoint()
                    fd = fd_observation._open_relative_directory(root_fd, path, directory_pins)
                    with fd_observation._owned_descriptor(fd):
                        expected = fd_observation._wire_stat(directory_pins[path])
                        if fd_observation._stat_tuple(os.fstat(fd)) != expected:
                            _fail("directory_changed_after_read")
                        fd_observation._list_children(
                            fd, children[path], deadline=deadline, monotonic=monotonic,
                            reason="directory_changed_after_read",
                        )
                        if fd_observation._stat_tuple(os.fstat(fd)) != expected:
                            _fail("directory_changed_after_read")

            verify_directories()
            for path, identity in sorted(file_pins.items()):
                checkpoint()
                parent, _, name = path.rpartition("/")
                directory_parent = fd_observation._open_relative_directory(root_fd, parent, directory_pins)
                with fd_observation._owned_descriptor(directory_parent):
                    named = os.stat(name, dir_fd=directory_parent, follow_symlinks=False)
                    if fd_observation._stat_tuple(named) != identity:
                        _fail("file_changed_after_read")
            verify_directories()
            fd_observation._verify_held_edges(held)
            if (fd_observation._stat_tuple(os.fstat(root_fd)) != root_identity
                    or fd_observation._stat_tuple(os.stat(
                        leaf, dir_fd=parent_fd, follow_symlinks=False,
                    )) != root_identity):
                _fail("root_changed_after_read")
            checkpoint()
        except BaseException:
            failed = True
            raise
        finally:
            fd_observation._close_root(root_fd, parent_fd, held, preserve=failed)

        record = {
            "schema": TOOLCHAIN_TREE_OBSERVATION_SCHEMA,
            "status": "pinned-manifest-tree-observed", "archive": observed.archive,
            "root": observed.root, "archive_sha256": observed.archive_sha256,
            "manifest_sha256": observed.manifest_sha256,
            "tree_identity": dict(zip((
                "device", "inode", "raw_mode", "nlink", "size", "mtime_ns", "ctime_ns",
            ), root_identity, strict=True)),
            "member_count": len(entries), "file_count": len(files),
            "directory_count": len(directories), "total_file_bytes": total_file_bytes,
            "observation_scope": "sequential-held-directory-tree-comparison",
            "signature_verification": "not-performed",
            "claims": dict.fromkeys(_CLAIMS, False),
        }
        checkpoint()
        canonical = _canonical(record)
        checkpoint()
        digest = hashlib.sha256(canonical).hexdigest()
        checkpoint()
        result = StaticPythonToolchainObservation(
            canonical_json=canonical, observation_sha256=digest,
            manifest_json=manifest, manifest_sha256=observed.manifest_sha256,
        )
        checkpoint()
        return result
    except StaticPythonToolchainTreeObservationError:
        raise
    except verified_inputs.StaticPythonVerifiedInputError as exc:
        raise StaticPythonToolchainTreeObservationError(
            "manifest_" + exc.reason.removeprefix("static_python_verified_input_"),
        ) from None
    except fd_observation.CandidateBuildSourceObservationError as exc:
        raise StaticPythonToolchainTreeObservationError(
            exc.reason.removeprefix("static_python_candidate_source_observation_"),
        ) from None
    except fd_observation._Refusal as exc:
        raise StaticPythonToolchainTreeObservationError(exc.reason) from None
    except (OSError, KeyError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise StaticPythonToolchainTreeObservationError("filesystem_observation_failed") from None


__all__ = [
    "MAX_TOOLCHAIN_TREE_OBSERVATION_BYTES",
    "TOOLCHAIN_TREE_OBSERVATION_SCHEMA",
    "StaticPythonToolchainTreeObservationError",
    "observe_extracted_toolchain_tree",
]
