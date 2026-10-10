"""Observe the original regular-file source tree in one archive snapshot.

This is a read-only, snapshot-bound provenance observation.  It does not
acquire, authenticate, extract, stage, patch, build, execute, or publish a
source tree.  The source-tree digest is a separate canonical domain from the
archive extraction manifest and from any staged postimage inventory.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn

from .archive_observation import (
    ArchiveSourceIdentity,
    StaticPythonArchiveObservationError,
    StaticPythonArchiveSnapshot,
    _observe_archive_snapshot,
)
from .verified_inputs import StaticPythonArchiveMember

SOURCE_TREE_OBSERVATION_SCHEMA = "lunar-static-python-source-tree-observation-v1"
SOURCE_TREE_SCHEMA = "lunar-static-python-source-tree-v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class StaticPythonSourceTreeObservationError(ValueError):
    """A fixed refusal code without caller paths or source contents."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_source_tree_observation_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonSourceTreeObservationError(reason)


def _pin(value: object, name: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value in {"0" * 64, "f" * 64}:
        _fail(name + "_invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise StaticPythonSourceTreeObservationError("canonical_invalid") from exc


def _identity_wire(identity: ArchiveSourceIdentity | None) -> dict[str, int] | None:
    if identity is None:
        return None
    if type(identity) is not ArchiveSourceIdentity or any(
            type(item) is not int for item in (
                identity.device, identity.inode, identity.size, identity.mode,
                identity.mtime_ns, identity.ctime_ns)):
        _fail("source_identity_invalid")
    return {
        "device": identity.device, "inode": identity.inode, "size": identity.size,
        "mode": identity.mode, "mtime_ns": identity.mtime_ns,
        "ctime_ns": identity.ctime_ns,
    }


@dataclass(frozen=True, slots=True)
class StaticPythonSourceTreeFile:
    """One original regular file, retaining the archive mode and prepatch bytes."""

    path: str
    mode: int
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class StaticPythonSourceTreeObservation:
    """Detached evidence for one complete original source-tree inventory."""

    schema: str
    archive: str
    root: str
    version: str
    archive_sha256: str
    snapshot_sha256: str
    manifest_sha256: str
    source_tree_sha256: str
    files: tuple[StaticPythonSourceTreeFile, ...]
    total_bytes: int
    tree_json: bytes
    profile_pin_verified: bool
    metadata_validation: str
    source_preimages_checked: bool
    signature_verification: str
    source_identity: ArchiveSourceIdentity | None
    canonical_json: bytes
    observation_sha256: str

    def to_tree(self) -> dict[str, object]:
        """Return a detached canonical source-tree projection."""
        return json.loads(self.tree_json)

    def to_manifest(self) -> dict[str, object]:
        """Return a detached observation projection."""
        return json.loads(self.canonical_json)


def _tree_payload(
    archive: str,
    root: str,
    version: str,
    files: tuple[StaticPythonSourceTreeFile, ...],
) -> dict[str, object]:
    # The source-tree wire deliberately contains only original regular files.
    # Directory entries remain in extraction-manifest-v1.  ``mode`` is the
    # archive mode captured before any patch or staging operation.
    return {
        "schema": SOURCE_TREE_SCHEMA,
        "archive": archive,
        "root": root,
        "version": version,
        "files": [
            {"path": item.path, "mode": item.mode, "size": item.size,
             "sha256": item.sha256}
            for item in files
        ],
    }


def observe_snapshot_source_tree(
    snapshot: StaticPythonArchiveSnapshot,
    *,
    expected_manifest_sha256: str,
    expected_source_tree_sha256: str,
    require_profile: bool = True,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> StaticPythonSourceTreeObservation:
    """Observe a complete source tree from one immutable archive snapshot.

    ``expected_manifest_sha256`` and ``expected_source_tree_sha256`` are
    caller-retained independent pins.  They are never inferred from the
    observer's output.  ``require_profile=False`` is an explicit inert-fixture
    mode and keeps ``profile_pin_verified`` false.
    """
    _pin(expected_manifest_sha256, "manifest_pin")
    _pin(expected_source_tree_sha256, "source_tree_pin")
    if type(require_profile) is not bool:
        _fail("profile_flag_invalid")
    if type(deadline) is not float or not math.isfinite(deadline) or deadline <= 0:
        _fail("deadline_invalid")
    if not callable(monotonic):
        _fail("clock_invalid")
    if type(snapshot) is not StaticPythonArchiveSnapshot:
        _fail("snapshot_invalid")
    # The first source-tree provenance slice is intentionally CPython-only.
    # Toolchain archives use a separate provenance contract and cannot be
    # silently admitted through this source-tree wire.
    if snapshot.archive != "cpython":
        _fail("archive_invalid")

    def checkpoint() -> None:
        try:
            now = monotonic()
            valid = type(now) in {int, float} and math.isfinite(now)
        except (OverflowError, TypeError, ValueError) as exc:
            raise StaticPythonSourceTreeObservationError("clock_invalid") from exc
        except Exception as exc:
            raise StaticPythonSourceTreeObservationError("clock_invalid") from exc
        if not valid:
            _fail("clock_invalid")
        if now >= deadline:
            _fail("wall_timeout")

    checkpoint()
    try:
        observed, _selected = _observe_archive_snapshot(
            snapshot,
            expected_manifest_sha256=expected_manifest_sha256,
            require_profile=require_profile,
            checkpoint=checkpoint,
        )
    except StaticPythonArchiveObservationError as exc:
        cause = exc.__cause__
        if isinstance(cause, StaticPythonSourceTreeObservationError):
            raise cause
        raise StaticPythonSourceTreeObservationError(
            "archive_" + exc.reason.removeprefix("static_python_archive_observation_")
        ) from exc
    checkpoint()
    if observed.manifest_sha256 != expected_manifest_sha256:
        _fail("manifest_pin_mismatch")

    files: list[StaticPythonSourceTreeFile] = []
    total = 0
    for member in observed.members:
        checkpoint()
        if type(member) is not StaticPythonArchiveMember:
            _fail("member_invalid")
        if member.kind == "directory":
            continue
        if member.kind != "file" or type(member.path) is not str:
            _fail("member_invalid")
        if (type(member.mode) is not int or member.mode < 0 or member.mode & ~0o777
                or type(member.size) is not int or member.size < 0
                or type(member.sha256) is not str or _SHA.fullmatch(member.sha256) is None):
            _fail("member_invalid")
        total += member.size
        if total < 0:
            _fail("size_overflow")
        files.append(StaticPythonSourceTreeFile(
            member.path, member.mode, member.size, member.sha256,
        ))
    ordered = tuple(sorted(files, key=lambda item: item.path))
    if len(ordered) != len(files) or tuple(item.path for item in ordered) != tuple(
            sorted({item.path for item in files})):
        _fail("member_duplicate_path")
    checkpoint()
    tree = _tree_payload(observed.archive, observed.root, observed.version, ordered)
    tree_json = _canonical(tree)
    checkpoint()
    tree_digest = hashlib.sha256(tree_json).hexdigest()
    checkpoint()
    if tree_digest != expected_source_tree_sha256:
        _fail("source_tree_pin_mismatch")
    identity = _identity_wire(snapshot.source_identity)
    profile_pin_verified = require_profile and snapshot.profile_pin_verified
    if type(profile_pin_verified) is not bool:
        _fail("profile_state_invalid")
    record = {
        "schema": SOURCE_TREE_OBSERVATION_SCHEMA,
        "archive": observed.archive,
        "root": observed.root,
        "version": observed.version,
        "archive_sha256": observed.archive_sha256,
        "snapshot_sha256": observed.snapshot_sha256,
        "manifest_sha256": observed.manifest_sha256,
        "source_tree_sha256": tree_digest,
        "profile_pin_verified": profile_pin_verified,
        "metadata_validation": observed.metadata_validation,
        "source_preimages_checked": observed.source_preimages_checked,
        "signature_verification": "not-performed",
        "source_identity": identity,
        "total_bytes": total,
        "files": [
            {"path": item.path, "mode": item.mode, "size": item.size,
             "sha256": item.sha256}
            for item in ordered
        ],
    }
    canonical = _canonical(record)
    checkpoint()
    result = StaticPythonSourceTreeObservation(
        schema=SOURCE_TREE_OBSERVATION_SCHEMA,
        archive=observed.archive,
        root=observed.root,
        version=observed.version,
        archive_sha256=observed.archive_sha256,
        snapshot_sha256=observed.snapshot_sha256,
        manifest_sha256=observed.manifest_sha256,
        source_tree_sha256=tree_digest,
        files=ordered,
        total_bytes=total,
        tree_json=tree_json,
        profile_pin_verified=profile_pin_verified,
        metadata_validation=observed.metadata_validation,
        source_preimages_checked=observed.source_preimages_checked,
        signature_verification="not-performed",
        source_identity=snapshot.source_identity,
        canonical_json=canonical,
        observation_sha256=hashlib.sha256(canonical).hexdigest(),
    )
    checkpoint()
    return result


__all__ = [
    "SOURCE_TREE_OBSERVATION_SCHEMA",
    "SOURCE_TREE_SCHEMA",
    "StaticPythonSourceTreeFile",
    "StaticPythonSourceTreeObservation",
    "StaticPythonSourceTreeObservationError",
    "observe_snapshot_source_tree",
]
