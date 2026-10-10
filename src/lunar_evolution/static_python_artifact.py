"""Detached byte-level checks for a retained static Python artifact.

This module consumes caller-provided bytes and a separately pinned installation
wire.  It never opens a path, launches a process, performs a build, or grants
runtime or production admission.  A successful result means only that the
provided bytes match the descriptor's bounded ELF format projection.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import NoReturn

from .static_python_elf import (
    MAX_STATIC_PYTHON_IMAGE_BYTES,
    StaticPythonELFError,
    StaticPythonELFProfile,
    inspect_static_python_elf,
)
from .static_python_installation import (
    StaticPythonInstallationError,
    parse_static_python_installation_descriptor,
)

ARTIFACT_VERIFICATION_SCHEMA = "lunar-static-python-artifact-verification-v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PROFILE_FIELDS = (
    "sha256", "size", "osabi", "entry_point", "program_header_count",
    "section_header_count", "load_segment_count", "executable_load_segment_count",
    "dynamic_table_count", "dynamic_entry_count", "elf_class", "byte_order",
    "machine", "elf_type", "has_pt_interp", "has_dt_needed",
    "runtime_load_protection", "general_code_origin_protection", "production_admission",
)
_CLAIM_FIELDS = (
    "execution_performed", "runtime_load_protection", "production_admission",
    "general_code_origin_protection",
)


class StaticPythonArtifactVerificationError(ValueError):
    """A fixed refusal code that never includes paths or image-controlled text."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or re.fullmatch(r"[a-z_]{1,64}", reason) is None:
            reason = "invalid"
        self.reason = "static_python_artifact_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonArtifactVerificationError(reason)


def _pin(value: object, name: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value in {
        "0" * 64, "f" * 64,
    }:
        _fail(name + "_invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise StaticPythonArtifactVerificationError("canonical_invalid") from exc


def _profile_wire(profile: StaticPythonELFProfile) -> dict[str, object]:
    if type(profile) is not StaticPythonELFProfile:
        _fail("elf_profile_invalid")
    return {field: getattr(profile, field) for field in _PROFILE_FIELDS}


def _map_descriptor_error(exc: StaticPythonInstallationError) -> NoReturn:
    reason = exc.reason.removeprefix("static_python_installation_")
    _fail("descriptor_" + reason)


def _map_elf_error(exc: StaticPythonELFError) -> NoReturn:
    reason = exc.reason.removeprefix("static_python_elf_")
    _fail("elf_" + reason)


@dataclass(frozen=True, slots=True)
class StaticPythonArtifactVerification:
    """Detached format evidence; it contains no execution authority."""

    schema: str
    descriptor_sha256: str
    installation_version: str
    artifact_sha256: str
    artifact_size: int
    elf_profile: StaticPythonELFProfile
    format_verified: bool
    execution_performed: bool
    runtime_load_protection: bool
    production_admission: bool
    general_code_origin_protection: bool
    canonical_bytes: bytes
    verification_sha256: str

    def to_json(self) -> bytes:
        """Return detached canonical verification bytes."""
        return self.canonical_bytes

    def to_dict(self) -> dict[str, object]:
        """Return a detached JSON-compatible projection."""
        return json.loads(self.canonical_bytes)


def verify_static_python_artifact_bytes(
    image: bytes,
    descriptor_raw: bytes,
    *,
    expected_descriptor_sha256: str,
    expected_installation_version: str,
    expected_artifact_sha256: str,
) -> StaticPythonArtifactVerification:
    """Verify one retained image against an independently pinned descriptor.

    The descriptor parser and ELF inspector are both pure.  This function
    compares their detached projections and returns format evidence only;
    matching bytes do not establish CPython identity, signatures, static-link
    closure, process ownership, runtime execution or production admission.
    """
    _pin(expected_descriptor_sha256, "descriptor_pin")
    if type(expected_installation_version) is not str or not expected_installation_version:
        _fail("installation_version_invalid")
    _pin(expected_artifact_sha256, "artifact_pin")
    if type(image) is not bytes:
        _fail("image_type_invalid")
    if not 1 <= len(image) <= MAX_STATIC_PYTHON_IMAGE_BYTES:
        _fail("image_size_invalid")

    try:
        descriptor = parse_static_python_installation_descriptor(
            descriptor_raw,
            expected_descriptor_sha256=expected_descriptor_sha256,
            expected_installation_version=expected_installation_version,
            expected_artifact_sha256=expected_artifact_sha256,
        )
    except StaticPythonInstallationError as exc:
        _map_descriptor_error(exc)

    try:
        observed = inspect_static_python_elf(image)
    except StaticPythonELFError as exc:
        _map_elf_error(exc)

    # The image digest/size are independent observations, not values inferred
    # from the descriptor's self-digest or from the expected pin alone.
    if observed.sha256 != expected_artifact_sha256:
        _fail("artifact_pin_mismatch")
    if observed.size != descriptor.artifact_size:
        _fail("artifact_size_mismatch")

    payload = descriptor.to_dict()
    declared = payload["elf_profile"]
    if type(declared) is not dict or any(
        declared[field] != getattr(observed, field) for field in _PROFILE_FIELDS
    ):
        _fail("elf_profile_mismatch")

    # Keep every runtime/production claim explicitly false.  The descriptor
    # parser already enforces this; the returned evidence repeats the state so
    # detached consumers cannot mistake a format match for admission.
    claims = {field: payload[field] for field in _CLAIM_FIELDS}
    if any(value is not False for value in claims.values()):
        _fail("claims_mismatch")
    record = {
        "schema": ARTIFACT_VERIFICATION_SCHEMA,
        "descriptor_sha256": descriptor.descriptor_sha256,
        "installation_version": descriptor.installation_version,
        "artifact_sha256": observed.sha256,
        "artifact_size": observed.size,
        "elf_profile": _profile_wire(observed),
        "format_verified": True,
        **claims,
    }
    canonical = _canonical(record)
    return StaticPythonArtifactVerification(
        schema=ARTIFACT_VERIFICATION_SCHEMA,
        descriptor_sha256=descriptor.descriptor_sha256,
        installation_version=descriptor.installation_version,
        artifact_sha256=observed.sha256,
        artifact_size=observed.size,
        elf_profile=observed,
        format_verified=True,
        execution_performed=False,
        runtime_load_protection=False,
        production_admission=False,
        general_code_origin_protection=False,
        canonical_bytes=canonical,
        verification_sha256=hashlib.sha256(canonical).hexdigest(),
    )


__all__ = [
    "ARTIFACT_VERIFICATION_SCHEMA",
    "StaticPythonArtifactVerification",
    "StaticPythonArtifactVerificationError",
    "verify_static_python_artifact_bytes",
]
