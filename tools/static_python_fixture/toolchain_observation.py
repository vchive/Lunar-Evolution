"""Retain one complete Zig archive observation without executing its contents.

The existing archive observer owns acquisition and tar/XZ validation. This
composition binds its complete canonical manifest to an independent pin and a
small detached record. It neither observes an extracted tree nor selects or
executes a compiler. Callers must retain the manifest separately and pass the
same original absolute deadline to acquisition and this observation.
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

TOOLCHAIN_OBSERVATION_SCHEMA = "lunar-static-python-toolchain-archive-observation-v1"
MAX_TOOLCHAIN_OBSERVATION_BYTES = 16 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CLAIMS = (
    "extracted_tree_observed", "toolchain_execution_performed", "configure_performed",
    "build_performed", "runtime_execution_performed", "production_admission",
    "online_publication",
)


class StaticPythonToolchainObservationError(ValueError):
    """Fixed refusal codes without paths, archive contents or clock messages."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_toolchain_observation_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonToolchainObservationError(reason)


def _canonical(record: dict[str, object]) -> bytes:
    try:
        raw = json.dumps(record, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise StaticPythonToolchainObservationError("canonical_invalid") from None
    if not 0 < len(raw) <= MAX_TOOLCHAIN_OBSERVATION_BYTES:
        _fail("record_budget_exceeded")
    return raw


def _identity_wire(identity: ArchiveSourceIdentity | None) -> dict[str, int] | None:
    if identity is None:
        return None
    return {
        "device": identity.device, "inode": identity.inode, "size": identity.size,
        "mode": identity.mode, "mtime_ns": identity.mtime_ns, "ctime_ns": identity.ctime_ns,
    }


@dataclass(frozen=True, slots=True)
class StaticPythonToolchainObservation:
    """Immutable archive record and its separately retained complete manifest."""

    canonical_json: bytes
    observation_sha256: str
    manifest_json: bytes
    manifest_sha256: str

    def to_dict(self) -> dict[str, object]:
        """Return a fresh detached record projection."""
        return json.loads(self.canonical_json)

    def to_manifest(self) -> dict[str, object]:
        """Return the original extraction-manifest-v1 projection, without a new wire."""
        return json.loads(self.manifest_json)


def observe_toolchain_archive(
    snapshot: StaticPythonArchiveSnapshot,
    *,
    expected_manifest_sha256: str,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
    require_profile: bool = True,
) -> StaticPythonToolchainObservation:
    """Observe a Zig snapshot under an independent complete-manifest pin.

    ``require_profile=False`` is an explicit inert-fixture mode. Its record
    always keeps profile verification false, including for an acquired input.
    This API cannot retrospectively prove the deadline used to acquire a
    supplied snapshot. It checks the supplied deadline throughout its own work.
    """
    if type(deadline) is not float or not math.isfinite(deadline) or deadline <= 0:
        _fail("deadline_invalid")
    if not callable(monotonic):
        _fail("clock_invalid")

    def checkpoint() -> None:
        try:
            now = monotonic()
            valid = type(now) in {int, float} and math.isfinite(now)
        except Exception:  # noqa: BLE001 - redact arbitrary caller-clock failures.
            raise StaticPythonToolchainObservationError("clock_invalid") from None
        if not valid:
            _fail("clock_invalid")
        if now >= deadline:
            _fail("wall_timeout")

    checkpoint()
    if (type(expected_manifest_sha256) is not str
            or _SHA.fullmatch(expected_manifest_sha256) is None
            or expected_manifest_sha256 in {"0" * 64, "f" * 64}):
        _fail("manifest_pin_invalid")
    if type(require_profile) is not bool:
        _fail("profile_flag_invalid")
    if type(snapshot) is not StaticPythonArchiveSnapshot:
        _fail("snapshot_invalid")
    if type(snapshot.archive) is not str or snapshot.archive != "zig":
        _fail("archive_invalid")
    checkpoint()
    try:
        observed, _selected = _observe_archive_snapshot(
            snapshot, expected_manifest_sha256=expected_manifest_sha256,
            require_source_preimages=False, require_profile=require_profile,
            checkpoint=checkpoint,
        )
    except StaticPythonArchiveObservationError as exc:
        if isinstance(exc.__cause__, StaticPythonToolchainObservationError):
            raise exc.__cause__ from None
        raise StaticPythonToolchainObservationError(
            "archive_" + exc.reason.removeprefix("static_python_archive_observation_")
        ) from None
    checkpoint()
    # The underlying observer only requires the manifest pin in profile mode.
    # This separate comparison keeps the complete external pin mandatory for
    # inert observations too.
    if observed.manifest_sha256 != expected_manifest_sha256:
        _fail("manifest_pin_mismatch")
    file_count = 0
    directory_count = 0
    total_file_bytes = 0
    for member in observed.members:
        checkpoint()
        if member.kind == "file":
            file_count += 1
            total_file_bytes += member.size
        else:
            directory_count += 1
    checkpoint()
    record = {
        "schema": TOOLCHAIN_OBSERVATION_SCHEMA,
        "status": ("profile-pinned-archive-observed" if require_profile
                   else "inert-archive-observed"),
        "archive": observed.archive, "root": observed.root, "version": observed.version,
        "archive_size": snapshot.archive_size,
        "archive_sha256": observed.archive_sha256,
        "snapshot_sha256": observed.snapshot_sha256,
        "manifest_sha256": observed.manifest_sha256,
        "source_identity": _identity_wire(snapshot.source_identity),
        "member_count": len(observed.members), "file_count": file_count,
        "directory_count": directory_count, "total_file_bytes": total_file_bytes,
        "profile_pin_verified": require_profile and snapshot.profile_pin_verified,
        "metadata_validation": observed.metadata_validation,
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
        manifest_json=observed.manifest_json, manifest_sha256=observed.manifest_sha256,
    )
    checkpoint()
    return result


__all__ = [
    "MAX_TOOLCHAIN_OBSERVATION_BYTES",
    "TOOLCHAIN_OBSERVATION_SCHEMA",
    "StaticPythonToolchainObservation",
    "StaticPythonToolchainObservationError",
    "observe_toolchain_archive",
]
