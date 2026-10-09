"""Pure fixed-source preparation bound to one immutable archive snapshot."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn

from . import source_patches
from .archive_observation import (
    StaticPythonArchiveObservationError,
    StaticPythonArchiveSnapshot,
    _observe_archive_snapshot,
)
from .profile import CPYTHON_ARCHIVE

SOURCE_PROJECTION_SCHEMA = "lunar-static-python-source-projection-v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class StaticPythonSourceProjectionError(ValueError):
    """A fixed refusal code without archive paths, contents or clock values."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_source_projection_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonSourceProjectionError(reason)


@dataclass(frozen=True, slots=True)
class StaticPythonPreparedArchiveSource:
    path: str
    archive_path: str
    preimage_bytes: bytes
    preimage_size: int
    preimage_sha256: str
    postimage_bytes: bytes
    postimage_size: int
    postimage_sha256: str


@dataclass(frozen=True, slots=True)
class StaticPythonArchiveSourcePreparation:
    schema: str
    archive: str
    root: str
    version: str
    archive_sha256: str
    snapshot_sha256: str
    manifest_sha256: str
    source_commit: str
    source_version: str
    policy_sha256: str
    patch_set_sha256: str
    policy_json: bytes
    sources: tuple[StaticPythonPreparedArchiveSource, ...]
    profile_pin_verified: bool
    metadata_validation: str
    source_preimages_checked: bool
    signature_verification: str
    canonical_json: bytes
    projection_sha256: str
    release_verified: bool = False
    source_execution_performed: bool = False
    extraction_performed: bool = False
    build_performed: bool = False
    frozen_headers_generated: bool = False
    runtime_execution_performed: bool = False
    runtime_load_protection: bool = False
    production_admission: bool = False
    general_code_origin_protection: bool = False

    def to_manifest(self) -> dict[str, object]:
        """Return detached metadata; immutable source bytes remain in this DTO."""
        return json.loads(self.canonical_json)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def prepare_archive_sources(
    snapshot: StaticPythonArchiveSnapshot,
    *,
    expected_manifest_sha256: str,
    require_profile: bool = True,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> StaticPythonArchiveSourcePreparation:
    """Prepare exactly three fixed members after observing the complete snapshot.

    The manifest pin and absolute deadline are caller-retained inputs. This
    function has no filesystem, subprocess, network, extraction or build route.
    Synthetic snapshots use explicit ``require_profile=False`` and retain the
    skipped metadata status; a failed profile check never falls back to inert.
    """
    if (type(expected_manifest_sha256) is not str
            or _SHA.fullmatch(expected_manifest_sha256) is None
            or expected_manifest_sha256 in {"0" * 64, "f" * 64}):
        _fail("manifest_pin_invalid")
    if type(require_profile) is not bool:
        _fail("profile_flag_invalid")
    if type(deadline) is not float or not math.isfinite(deadline) or deadline <= 0:
        _fail("deadline_invalid")
    if not callable(monotonic):
        _fail("clock_invalid")
    if type(snapshot) is not StaticPythonArchiveSnapshot:
        _fail("snapshot_invalid")
    if type(snapshot.archive) is not str or snapshot.archive != "cpython":
        _fail("archive_invalid")

    def checkpoint() -> None:
        try:
            current = monotonic()
        except Exception as exc:
            raise StaticPythonSourceProjectionError("clock_invalid") from exc
        if type(current) not in {int, float}:
            _fail("clock_invalid")
        try:
            finite = math.isfinite(current)
        except (OverflowError, ValueError, TypeError) as exc:
            raise StaticPythonSourceProjectionError("clock_invalid") from exc
        if not finite:
            _fail("clock_invalid")
        if current >= deadline:
            _fail("wall_timeout")

    def digest(raw: bytes) -> str:
        checkpoint()
        result = hashlib.sha256(raw).hexdigest()
        checkpoint()
        return result

    checkpoint()
    fixed_paths = frozenset(
        CPYTHON_ARCHIVE["root"] + "/" + path for path in source_patches.SOURCE_PATHS
    )
    try:
        observed, selected = _observe_archive_snapshot(
            snapshot, expected_manifest_sha256=expected_manifest_sha256,
            require_profile=require_profile, checkpoint=checkpoint,
            selected_paths=fixed_paths,
            selected_max_file_bytes=source_patches.MAX_SOURCE_BYTES,
            selected_max_total_bytes=source_patches.MAX_TOTAL_SOURCE_BYTES,
        )
    except StaticPythonArchiveObservationError as exc:
        if type(exc.__cause__) is StaticPythonSourceProjectionError:
            # Keep the fixed primary reason without creating A -> P -> A in
            # the exception graph when the shared parser wrapped the hook.
            raise StaticPythonSourceProjectionError(
                exc.__cause__.reason.removeprefix("static_python_source_projection_"),
            ) from None
        raise StaticPythonSourceProjectionError(
            "archive_" + exc.reason.removeprefix("static_python_archive_observation_"),
        ) from exc
    checkpoint()
    if observed.manifest_sha256 != expected_manifest_sha256:
        _fail("manifest_pin_mismatch")
    captured = dict(selected)
    if set(captured) != fixed_paths or len(selected) != len(fixed_paths):
        _fail("source_missing")
    by_path = {member.path: member for member in observed.members}
    checkpoint()
    policy = source_patches.source_patch_manifest()
    checkpoint()
    policy_json = _canonical(policy)
    checkpoint()
    policy_sha256 = digest(policy_json)
    policy_by_path = {item["path"]: item for item in policy["files"]}
    inputs: dict[str, bytes] = {}
    preimage_pins: dict[str, tuple[int, str]] = {}
    for path in source_patches.SOURCE_PATHS:
        checkpoint()
        archive_path = observed.root + "/" + path
        raw = captured[archive_path]
        member = by_path[archive_path]
        actual = digest(raw)
        if member.kind != "file" or member.size != len(raw) or member.sha256 != actual:
            _fail("source_member_mismatch")
        pin = policy_by_path[path]
        if len(raw) != pin["before_size"] or actual != pin["before_sha256"]:
            _fail("source_preimage_mismatch")
        inputs[path] = raw
        preimage_pins[path] = (len(raw), actual)
    checkpoint()
    try:
        prepared, returned_policy = source_patches.prepare_static_python_sources(inputs)
    except source_patches.StaticPythonSourceError as exc:
        raise StaticPythonSourceProjectionError("preparation_failed") from exc
    checkpoint()
    if (type(prepared) is not dict or len(prepared) != len(source_patches.SOURCE_PATHS)
            or any(type(path) is not str for path in prepared)
            or set(prepared) != set(source_patches.SOURCE_PATHS)
            or _canonical(returned_policy) != policy_json):
        _fail("preparation_result_invalid")
    post_total = 0
    for path in source_patches.SOURCE_PATHS:
        raw = prepared[path]
        if type(raw) is not bytes or not 0 < len(raw) <= source_patches.MAX_SOURCE_BYTES:
            _fail("postimage_size_invalid")
        post_total += len(raw)
    if post_total > source_patches.MAX_TOTAL_SOURCE_BYTES:
        _fail("postimage_budget_exceeded")
    sources = []
    for path in sorted(source_patches.SOURCE_PATHS):
        checkpoint()
        raw = prepared[path]
        actual = digest(raw)
        pin = policy_by_path[path]
        if len(raw) != pin["after_size"] or actual != pin["after_sha256"]:
            _fail("source_postimage_mismatch")
        preimage_size, preimage_sha = preimage_pins[path]
        sources.append(StaticPythonPreparedArchiveSource(
            path, observed.root + "/" + path, inputs[path], preimage_size, preimage_sha,
            raw, len(raw), actual,
        ))
    checkpoint()
    manifest = {
        "schema": SOURCE_PROJECTION_SCHEMA, "archive": observed.archive,
        "root": observed.root, "version": observed.version,
        "archive_sha256": observed.archive_sha256,
        "snapshot_sha256": observed.snapshot_sha256,
        "manifest_sha256": observed.manifest_sha256,
        "source_commit": source_patches.SOURCE_COMMIT,
        "source_version": source_patches.SOURCE_VERSION,
        "policy_sha256": policy_sha256, "patch_set_sha256": policy["patch_set_sha256"],
        "profile_pin_verified": require_profile and snapshot.profile_pin_verified,
        "metadata_validation": observed.metadata_validation,
        "source_preimages_checked": True, "signature_verification": "not-performed",
        "sources": [{
            "path": source.path, "archive_path": source.archive_path,
            "preimage_size": source.preimage_size, "preimage_sha256": source.preimage_sha256,
            "postimage_size": source.postimage_size, "postimage_sha256": source.postimage_sha256,
        } for source in sources],
        "release_verified": False, "source_execution_performed": False,
        "extraction_performed": False, "build_performed": False,
        "frozen_headers_generated": False, "runtime_execution_performed": False,
        "runtime_load_protection": False, "production_admission": False,
        "general_code_origin_protection": False,
    }
    canonical = _canonical(manifest)
    checkpoint()
    projected = StaticPythonArchiveSourcePreparation(
        schema=SOURCE_PROJECTION_SCHEMA, archive=observed.archive, root=observed.root,
        version=observed.version, archive_sha256=observed.archive_sha256,
        snapshot_sha256=observed.snapshot_sha256, manifest_sha256=observed.manifest_sha256,
        source_commit=source_patches.SOURCE_COMMIT, source_version=source_patches.SOURCE_VERSION,
        policy_sha256=policy_sha256, patch_set_sha256=policy["patch_set_sha256"],
        policy_json=policy_json, sources=tuple(sources),
        profile_pin_verified=require_profile and snapshot.profile_pin_verified,
        metadata_validation=observed.metadata_validation, source_preimages_checked=True,
        signature_verification="not-performed", canonical_json=canonical,
        projection_sha256=digest(canonical),
    )
    checkpoint()
    return projected


__all__ = [
    "SOURCE_PROJECTION_SCHEMA",
    "StaticPythonArchiveSourcePreparation",
    "StaticPythonPreparedArchiveSource",
    "StaticPythonSourceProjectionError",
    "prepare_archive_sources",
]
