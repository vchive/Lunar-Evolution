"""Provider-free project lifecycle profile preflight.

This module defines the narrow contract that a future OpenEvolve/Shinka project launcher must
satisfy before it can be connected to the RSI controller.  It only parses a detached profile and
returns a fail-closed gate report; it never imports a project, starts a process, invokes an
 evaluator, opens a ledger, or changes publication state.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from . import _benchmark_files as files
from .candidate_evaluation_spec import canonical_json, strict_json

PROJECT_LIFECYCLE_PROTOCOL = "lunar-rsi-project-lifecycle-profile-v1"
PROJECT_LIFECYCLE_SCHEMA_VERSION = "1"
MAX_PROFILE_BYTES = 128 * 1024
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ENTRYPOINT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,255}$")
_REQUIRED_FIELDS = frozenset({
    "schema_version", "protocol", "producer_id", "project_id", "entrypoint",
    "source_sha256", "runtime_sha256", "toolchain_sha256", "request_schema_sha256",
    "result_schema_sha256", "launch_mode", "cancel_mode", "resume_mode",
})

# This is deliberately a diagnostic projection rather than an admission policy.  The
# profile proves only that the detached declaration is well formed; the remaining entries
# identify the evidence that a future production RSI CLI would still have to acquire.
PROJECT_LIFECYCLE_DIAGNOSTIC_PROTOCOL = "lunar-rsi-project-lifecycle-diagnostic-v1"
_DIAGNOSTIC_CAPABILITIES = (
    ("detached_profile", "verified", "profile_contract"),
    ("accepted_runtime_profile", "blocked", "accepted_runtime_profile"),
    ("trusted_project_entrypoint", "blocked", "trusted_project_entrypoint"),
    ("runtime_lifecycle_acceptance", "blocked", "runtime_lifecycle_acceptance"),
    ("linux_acceptance_matrix", "blocked", "linux_acceptance_matrix"),
    ("controller_admission", "blocked", "controller_admission"),
)


class ProjectLifecyclePreflightError(ValueError):
    """Fixed-code profile refusal without caller-controlled path or exception text."""

    def __init__(self, code: str) -> None:
        self.code = "rsi_project_lifecycle_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise ProjectLifecyclePreflightError(code)


def _digest(value: object) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None or value == "0" * 64:
        _fail("digest_invalid")
    return value


def _identifier(value: object, code: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail(code)
    return value


def _entrypoint(value: object) -> str:
    if (type(value) is not str or _ENTRYPOINT.fullmatch(value) is None
            or value.startswith("/") or value.endswith("/") or "\\" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        _fail("entrypoint_invalid")
    return value


def _profile_object(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _REQUIRED_FIELDS:
        _fail("schema_invalid")
    return value


@dataclass(frozen=True, slots=True)
class ProjectLifecycleProfile:
    """Immutable declaration for one future single-project producer lifecycle.

    The digests identify source, runtime and contracts; they do not prove those bytes were
    executed.  The three mode fields make the required future implementation explicit and keep
    arbitrary shell/module launchers out of this preflight contract.
    """

    producer_id: str
    project_id: str
    entrypoint: str
    source_sha256: str
    runtime_sha256: str
    toolchain_sha256: str
    request_schema_sha256: str
    result_schema_sha256: str
    launch_mode: str = "native_bootstrap"
    cancel_mode: str = "owner_group"
    resume_mode: str = "retained_read_only"
    schema_version: str = PROJECT_LIFECYCLE_SCHEMA_VERSION
    protocol: str = PROJECT_LIFECYCLE_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != PROJECT_LIFECYCLE_SCHEMA_VERSION or self.protocol != PROJECT_LIFECYCLE_PROTOCOL:
            _fail("schema_invalid")
        if self.producer_id not in {"openevolve", "shinka"}:
            _fail("producer_invalid")
        _identifier(self.project_id, "project_invalid")
        _entrypoint(self.entrypoint)
        for value in (
            self.source_sha256, self.runtime_sha256, self.toolchain_sha256,
            self.request_schema_sha256, self.result_schema_sha256,
        ):
            _digest(value)
        if self.launch_mode != "native_bootstrap":
            _fail("launch_mode_invalid")
        if self.cancel_mode != "owner_group":
            _fail("cancel_mode_invalid")
        if self.resume_mode != "retained_read_only":
            _fail("resume_mode_invalid")

    @classmethod
    def from_dict(cls, value: object) -> ProjectLifecycleProfile:
        raw = _profile_object(value)
        try:
            return cls(
                producer_id=raw["producer_id"], project_id=raw["project_id"],
                entrypoint=raw["entrypoint"], source_sha256=raw["source_sha256"],
                runtime_sha256=raw["runtime_sha256"], toolchain_sha256=raw["toolchain_sha256"],
                request_schema_sha256=raw["request_schema_sha256"],
                result_schema_sha256=raw["result_schema_sha256"],
                launch_mode=raw["launch_mode"], cancel_mode=raw["cancel_mode"],
                resume_mode=raw["resume_mode"], schema_version=raw["schema_version"],
                protocol=raw["protocol"],
            )
        except ProjectLifecyclePreflightError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError):
            _fail("schema_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "producer_id": self.producer_id,
            "project_id": self.project_id,
            "entrypoint": self.entrypoint,
            "source_sha256": self.source_sha256,
            "runtime_sha256": self.runtime_sha256,
            "toolchain_sha256": self.toolchain_sha256,
            "request_schema_sha256": self.request_schema_sha256,
            "result_schema_sha256": self.result_schema_sha256,
            "launch_mode": self.launch_mode,
            "cancel_mode": self.cancel_mode,
            "resume_mode": self.resume_mode,
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict(), maximum=MAX_PROFILE_BYTES)).hexdigest()


def _read_profile(path: str | Path) -> tuple[ProjectLifecycleProfile, str]:
    try:
        selected = files.absolute_path(path)
        if selected.name == ".env" or selected.name.startswith(".env."):
            _fail("profile_invalid")
        raw = files.read_regular_file(selected, MAX_PROFILE_BYTES)
        value = strict_json(raw, maximum=MAX_PROFILE_BYTES)
        if canonical_json(value, maximum=MAX_PROFILE_BYTES) != raw:
            _fail("profile_noncanonical")
        profile = ProjectLifecycleProfile.from_dict(value)
    except ProjectLifecyclePreflightError:
        raise
    except files.BenchmarkFileError as exc:
        _fail("profile_missing" if exc.reason == "missing" else "profile_invalid")
    except (TypeError, ValueError, OSError, UnicodeError, RecursionError, OverflowError):
        _fail("profile_invalid")
    return profile, hashlib.sha256(raw).hexdigest()


def preflight_project_lifecycle(
    profile_path: str | Path, *, expected_profile_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate one detached profile and report the remaining runtime gates.

    A valid profile is intentionally *blocked*: this P1 slice proves only that the future
    launcher inputs are well-shaped.  It does not claim runtime acceptance or grant launch,
    cancellation, evaluator, admission, or publication authority.
    """
    if expected_profile_sha256 is not None:
        _digest(expected_profile_sha256)
    profile, profile_sha256 = _read_profile(profile_path)
    if expected_profile_sha256 is not None and profile_sha256 != expected_profile_sha256:
        _fail("profile_digest_drift")
    return {
        "status": "blocked",
        "reason": "runtime_acceptance_required",
        "protocol": PROJECT_LIFECYCLE_PROTOCOL,
        "schema_version": PROJECT_LIFECYCLE_SCHEMA_VERSION,
        "profile_sha256": profile_sha256,
        "producer_id": profile.producer_id,
        "project_id": profile.project_id,
        "entrypoint": profile.entrypoint,
        "launch_mode": profile.launch_mode,
        "cancel_mode": profile.cancel_mode,
        "resume_mode": profile.resume_mode,
        "missing_gates": [
            "accepted_runtime_profile", "trusted_project_entrypoint",
            "runtime_lifecycle_acceptance", "linux_acceptance_matrix",
        ],
        "execution_performed": False,
        "evaluator_invoked": False,
        "production_admission": False,
        "online_publication": False,
        "evidence_scope": "detached_profile_preflight",
    }


def diagnose_project_lifecycle(
    profile_path: str | Path, *, expected_profile_sha256: str | None = None,
) -> dict[str, Any]:
    """Return a path-free capability matrix for a detached project profile.

    This is intentionally a read-only companion to :func:`preflight_project_lifecycle`.
    It makes the production RSI CLI boundary inspectable without pretending that a valid
    profile is a runnable OpenEvolve/Shinka project.  No home, ledger, process, evaluator,
    network or project import is reachable from this function.
    """
    report = preflight_project_lifecycle(
        profile_path, expected_profile_sha256=expected_profile_sha256,
    )
    report["diagnostic_protocol"] = PROJECT_LIFECYCLE_DIAGNOSTIC_PROTOCOL
    report["capability_matrix"] = [
        {"capability": capability, "status": status, "gate": gate}
        for capability, status, gate in _DIAGNOSTIC_CAPABILITIES
    ]
    report["production_cli"] = {
        "status": "blocked",
        "reason": "runtime_acceptance_required",
        "execution_performed": False,
        "evaluator_invoked": False,
        "production_admission": False,
        "online_publication": False,
    }
    return report


__all__ = [
    "MAX_PROFILE_BYTES", "PROJECT_LIFECYCLE_DIAGNOSTIC_PROTOCOL",
    "PROJECT_LIFECYCLE_PROTOCOL", "PROJECT_LIFECYCLE_SCHEMA_VERSION",
    "ProjectLifecyclePreflightError", "ProjectLifecycleProfile", "diagnose_project_lifecycle",
    "preflight_project_lifecycle",
]
