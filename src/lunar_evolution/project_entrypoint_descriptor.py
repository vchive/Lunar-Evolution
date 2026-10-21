"""Provider-free project entrypoint descriptor and lifecycle composition.

The project profile intentionally describes *what* a future OpenEvolve/Shinka
launcher would have to run, while retained lifecycle diagnostics describe
*what was observed*.  This module binds those two detached records without
starting a process, importing project code, opening the RSI ledger, or granting
production authority.  It is a small P1 seam for a later accepted runtime.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import NoReturn

from .candidate_evaluation_spec import canonical_json
from .producer_lifecycle_diagnostics import (
    parse_producer_lifecycle_diagnostic,
)
from .rsi_project_lifecycle import ProjectLifecycleProfile

PROJECT_ENTRYPOINT_DESCRIPTOR_PROTOCOL = "lunar-rsi-project-entrypoint-descriptor-v1"
PROJECT_ENTRYPOINT_DESCRIPTOR_SCHEMA_VERSION = "1"
PROJECT_ENTRYPOINT_ADAPTER_PROTOCOL = "lunar-rsi-project-entrypoint-adapter-v1"
PROJECT_ENTRYPOINT_ADAPTER_SCHEMA_VERSION = "1"
MAX_PROJECT_ENTRYPOINT_DESCRIPTOR_BYTES = 64 * 1024

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,4095}$")
_SHELLS = frozenset({"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh",
                     "cmd", "powershell", "pwsh"})
_DESCRIPTOR_FIELDS = frozenset({
    "schema_version", "protocol", "profile_sha256", "producer_id", "project_id",
    "entrypoint", "argv", "working_directory", "output_directory", "request_filename",
    "result_filename", "launch_mode", "cancel_mode", "resume_mode", "descriptor_sha256",
})
_ADAPTER_FIELDS = frozenset({
    "schema_version", "protocol", "profile_sha256", "descriptor_sha256",
    "lifecycle_diagnostic_sha256", "producer_id", "project_id", "entrypoint",
    "descriptor_verified", "lifecycle_status", "missing_gates", "status", "reason",
    "execution_performed", "evaluator_invoked", "production_admission", "online_publication",
    "evidence_scope", "adapter_sha256",
})


class ProjectEntrypointDescriptorError(ValueError):
    """Fixed-code refusal without paths, commands, or producer-controlled text."""

    def __init__(self, code: str) -> None:
        self.code = "rsi_project_entrypoint_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise ProjectEntrypointDescriptorError(code)


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=MAX_PROJECT_ENTRYPOINT_DESCRIPTOR_BYTES)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProjectEntrypointDescriptorError("json_invalid") from exc


def _digest(value: object, code: str = "digest_invalid") -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None or value in {"0" * 64, "f" * 64}:
        _fail(code)
    return value


def _identifier(value: object, code: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _relative(value: object, code: str, *, allow_dot: bool = False) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        _fail(code)
    if value == "." and allow_dot:
        return value
    if _PATH.fullmatch(value) is None:
        _fail(code)
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        _fail(code)
    return value


def _argv(value: object, entrypoint: str) -> tuple[str, ...]:
    if type(value) is not list or len(value) != 1 or any(type(item) is not str for item in value):
        _fail("argv_invalid")
    result = tuple(value)
    if result[0] != entrypoint:
        _fail("argv_entrypoint_mismatch")
    if PurePosixPath(result[0]).name.casefold() in _SHELLS:
        _fail("shell_unsupported")
    for item in result:
        if not item or "\x00" in item or len(item.encode("utf-8")) > 4096:
            _fail("argv_invalid")
        if any(char in item for char in ";&|`\n\r"):
            _fail("shell_unsupported")
    return result


def _digest_without(value: dict[str, object], field: str) -> str:
    body = dict(value)
    body.pop(field, None)
    return hashlib.sha256(_canonical(body)).hexdigest()


@dataclass(frozen=True, slots=True)
class ProjectEntrypointDescriptor:
    """Closed, detached launch declaration for one project entrypoint.

    ``profile_sha256`` is the independent byte pin produced by project
    preflight.  The descriptor does not prove that the referenced entrypoint
    exists or was executed; those claims require a separately accepted runtime.
    """

    profile_sha256: str
    producer_id: str
    project_id: str
    entrypoint: str
    argv: tuple[str, ...]
    working_directory: str
    output_directory: str
    request_filename: str
    result_filename: str
    launch_mode: str = "native_bootstrap"
    cancel_mode: str = "owner_group"
    resume_mode: str = "retained_read_only"
    descriptor_sha256: str | None = None
    schema_version: str = PROJECT_ENTRYPOINT_DESCRIPTOR_SCHEMA_VERSION
    protocol: str = PROJECT_ENTRYPOINT_DESCRIPTOR_PROTOCOL

    def __post_init__(self) -> None:
        if (type(self.schema_version) is not str
                or self.schema_version != PROJECT_ENTRYPOINT_DESCRIPTOR_SCHEMA_VERSION):
            _fail("schema_invalid")
        if type(self.protocol) is not str or self.protocol != PROJECT_ENTRYPOINT_DESCRIPTOR_PROTOCOL:
            _fail("protocol_invalid")
        _digest(self.profile_sha256, "profile_digest_invalid")
        _identifier(self.producer_id, "producer_invalid")
        _identifier(self.project_id, "project_invalid")
        _relative(self.entrypoint, "entrypoint_invalid")
        if type(self.argv) is not tuple:
            _fail("argv_invalid")
        _argv(list(self.argv), self.entrypoint)
        _relative(self.working_directory, "working_directory_invalid", allow_dot=True)
        _relative(self.output_directory, "output_directory_invalid")
        _relative(self.request_filename, "request_filename_invalid")
        _relative(self.result_filename, "result_filename_invalid")
        if "/" in self.request_filename or "/" in self.result_filename:
            _fail("result_filename_invalid")
        if self.request_filename == self.result_filename:
            _fail("result_filename_invalid")
        if type(self.launch_mode) is not str or self.launch_mode != "native_bootstrap":
            _fail("launch_mode_invalid")
        if type(self.cancel_mode) is not str or self.cancel_mode != "owner_group":
            _fail("cancel_mode_invalid")
        if type(self.resume_mode) is not str or self.resume_mode != "retained_read_only":
            _fail("resume_mode_invalid")
        if self.descriptor_sha256 is not None:
            _digest(self.descriptor_sha256, "descriptor_digest_invalid")
            if self.descriptor_sha256 != self.digest():
                _fail("descriptor_digest_mismatch")

    def _wire(self, *, include_digest: bool = True) -> dict[str, object]:
        wire: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "profile_sha256": self.profile_sha256,
            "producer_id": self.producer_id,
            "project_id": self.project_id,
            "entrypoint": self.entrypoint,
            "argv": list(self.argv),
            "working_directory": self.working_directory,
            "output_directory": self.output_directory,
            "request_filename": self.request_filename,
            "result_filename": self.result_filename,
            "launch_mode": self.launch_mode,
            "cancel_mode": self.cancel_mode,
            "resume_mode": self.resume_mode,
        }
        if include_digest:
            wire["descriptor_sha256"] = self.descriptor_sha256
        return wire

    def digest(self) -> str:
        return _digest_without(self._wire(include_digest=False), "descriptor_sha256")

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        wire = self._wire()
        wire["descriptor_sha256"] = self.descriptor_sha256 or self.digest()
        return wire

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> ProjectEntrypointDescriptor:
        if type(value) is not dict or set(value) != _DESCRIPTOR_FIELDS:
            _fail("descriptor_schema_invalid")
        if type(value.get("argv")) is not list:
            _fail("argv_invalid")
        try:
            return cls(
                profile_sha256=value["profile_sha256"], producer_id=value["producer_id"],
                project_id=value["project_id"], entrypoint=value["entrypoint"],
                argv=tuple(value["argv"]), working_directory=value["working_directory"],
                output_directory=value["output_directory"], request_filename=value["request_filename"],
                result_filename=value["result_filename"], launch_mode=value["launch_mode"],
                cancel_mode=value["cancel_mode"], resume_mode=value["resume_mode"],
                descriptor_sha256=value["descriptor_sha256"], schema_version=value["schema_version"],
                protocol=value["protocol"],
            )
        except ProjectEntrypointDescriptorError:
            raise
        except (KeyError, TypeError, ValueError):
            _fail("descriptor_schema_invalid")


def build_project_entrypoint_descriptor(
    profile: ProjectLifecycleProfile | dict[str, object],
    *,
    profile_sha256: str,
    argv: list[str] | tuple[str, ...] | None = None,
    working_directory: str = ".",
    output_directory: str = "outputs",
    request_filename: str = "request.json",
    result_filename: str = "result.json",
) -> ProjectEntrypointDescriptor:
    """Build a closed descriptor from an already validated lifecycle profile."""
    if type(profile) is dict:
        try:
            profile = ProjectLifecycleProfile.from_dict(profile)
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ProjectEntrypointDescriptorError):
                raise
            _fail("profile_invalid")
    if type(profile) is not ProjectLifecycleProfile:
        _fail("profile_invalid")
    _digest(profile_sha256, "profile_digest_invalid")
    if profile.digest() != profile_sha256:
        _fail("profile_digest_drift")
    if argv is not None and type(argv) not in {list, tuple}:
        _fail("argv_invalid")
    command = [profile.entrypoint] if argv is None else list(argv)
    descriptor = ProjectEntrypointDescriptor(
        profile_sha256=profile_sha256, producer_id=profile.producer_id,
        project_id=profile.project_id, entrypoint=profile.entrypoint, argv=tuple(command),
        working_directory=working_directory, output_directory=output_directory,
        request_filename=request_filename, result_filename=result_filename,
        launch_mode=profile.launch_mode, cancel_mode=profile.cancel_mode,
        resume_mode=profile.resume_mode,
    )
    return ProjectEntrypointDescriptor.from_dict(descriptor.to_dict())


def parse_project_entrypoint_descriptor(value: object) -> ProjectEntrypointDescriptor:
    """Validate a detached descriptor and return its immutable representation."""
    if type(value) is ProjectEntrypointDescriptor:
        value = value.to_dict()
    if type(value) in {bytes, str}:
        try:
            raw = value if isinstance(value, bytes) else value.encode("utf-8")
            if len(raw) > MAX_PROJECT_ENTRYPOINT_DESCRIPTOR_BYTES:
                _fail("record_too_large")

            def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
                result: dict[str, object] = {}
                for key, item in pairs:
                    if key in result:
                        _fail("duplicate_json_key")
                    result[key] = item
                return result

            parsed = json.loads(
                raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                parse_constant=lambda _: _fail("json_invalid"),
            )
        except ProjectEntrypointDescriptorError:
            raise
        except (UnicodeDecodeError, TypeError, ValueError, RecursionError) as exc:
            raise ProjectEntrypointDescriptorError("json_invalid") from exc
        if _canonical(parsed) != raw:
            _fail("noncanonical_json")
        value = parsed
    return ProjectEntrypointDescriptor.from_dict(value)


def compose_project_entrypoint_lifecycle(
    profile: ProjectLifecycleProfile | dict[str, object],
    descriptor: ProjectEntrypointDescriptor | dict[str, object] | bytes | str,
    lifecycle_report: dict[str, object],
) -> dict[str, object]:
    """Bind descriptor and retained lifecycle evidence into a blocked adapter report.

    The result is deliberately ``blocked`` even when all retained phases are
    offline-verified.  ``descriptor_verified`` means only that the detached
    declaration is internally consistent; it is not a trusted runtime claim.
    """
    if type(profile) is dict:
        try:
            profile = ProjectLifecycleProfile.from_dict(profile)
        except (TypeError, ValueError) as exc:
            raise ProjectEntrypointDescriptorError("profile_invalid") from exc
    if type(profile) is not ProjectLifecycleProfile:
        _fail("profile_invalid")
    parsed = parse_project_entrypoint_descriptor(descriptor)
    if (profile.digest() != parsed.profile_sha256
            or parsed.producer_id != profile.producer_id or parsed.project_id != profile.project_id
            or parsed.entrypoint != profile.entrypoint or parsed.launch_mode != profile.launch_mode
            or parsed.cancel_mode != profile.cancel_mode or parsed.resume_mode != profile.resume_mode):
        _fail("profile_descriptor_drift")
    try:
        if type(lifecycle_report) is not dict:
            _fail("lifecycle_invalid")
        lifecycle = parse_producer_lifecycle_diagnostic(lifecycle_report)
    except (TypeError, ValueError) as exc:
        raise ProjectEntrypointDescriptorError("lifecycle_invalid") from exc
    missing = ["accepted_runtime_profile", "trusted_project_entrypoint"]
    if lifecycle["status"] != "offline_verified":
        missing.append("runtime_lifecycle_acceptance")
    missing.append("linux_acceptance_matrix")
    body: dict[str, object] = {
        "schema_version": PROJECT_ENTRYPOINT_ADAPTER_SCHEMA_VERSION,
        "protocol": PROJECT_ENTRYPOINT_ADAPTER_PROTOCOL,
        "profile_sha256": parsed.profile_sha256,
        "descriptor_sha256": parsed.to_dict()["descriptor_sha256"],
        "lifecycle_diagnostic_sha256": lifecycle["diagnostic_sha256"],
        "producer_id": parsed.producer_id,
        "project_id": parsed.project_id,
        "entrypoint": parsed.entrypoint,
        "descriptor_verified": True,
        "lifecycle_status": lifecycle["status"],
        "missing_gates": list(dict.fromkeys(missing)),
        "status": "blocked",
        "reason": "runtime_acceptance_required",
        "execution_performed": lifecycle["execution_performed"],
        "evaluator_invoked": False,
        "production_admission": False,
        "online_publication": False,
        "evidence_scope": "detached_project_entrypoint_lifecycle",
        "adapter_sha256": "",
    }
    body["adapter_sha256"] = _digest_without(body, "adapter_sha256")
    return body


def parse_project_entrypoint_lifecycle(value: object) -> dict[str, object]:
    """Validate an adapter report, including the immutable digest and authority fence."""
    if type(value) is not dict or set(value) != _ADAPTER_FIELDS:
        _fail("adapter_schema_invalid")
    for field in ("schema_version", "protocol", "status", "reason", "evidence_scope"):
        if type(value[field]) is not str:
            _fail("adapter_contract_invalid")
    if (value["schema_version"] != PROJECT_ENTRYPOINT_ADAPTER_SCHEMA_VERSION
            or value["protocol"] != PROJECT_ENTRYPOINT_ADAPTER_PROTOCOL
            or value["status"] != "blocked" or value["reason"] != "runtime_acceptance_required"
            or value["evidence_scope"] != "detached_project_entrypoint_lifecycle"):
        _fail("adapter_contract_invalid")
    _identifier(value["producer_id"], "producer_invalid")
    _identifier(value["project_id"], "project_invalid")
    _relative(value["entrypoint"], "entrypoint_invalid")
    if value["descriptor_verified"] is not True:
        _fail("descriptor_unverified")
    if (type(value["lifecycle_status"]) is not str
            or value["lifecycle_status"] not in {"offline_verified", "blocked"}):
        _fail("lifecycle_status_invalid")
    expected_missing = ["accepted_runtime_profile", "trusted_project_entrypoint"]
    if value["lifecycle_status"] == "blocked":
        expected_missing.append("runtime_lifecycle_acceptance")
    expected_missing.append("linux_acceptance_matrix")
    if (type(value["missing_gates"]) is not list
            or any(type(item) is not str for item in value["missing_gates"])
            or value["missing_gates"] != expected_missing):
        _fail("missing_gates_invalid")
    for field in ("execution_performed", "evaluator_invoked", "production_admission", "online_publication"):
        if type(value[field]) is not bool:
            _fail("authority_invalid")
    if value["evaluator_invoked"] or value["production_admission"] or value["online_publication"]:
        _fail("authority_invalid")
    _digest(value["profile_sha256"], "profile_digest_invalid")
    _digest(value["descriptor_sha256"], "descriptor_digest_invalid")
    _digest(value["lifecycle_diagnostic_sha256"], "lifecycle_digest_invalid")
    _digest(value["adapter_sha256"], "adapter_digest_invalid")
    if value["adapter_sha256"] != _digest_without(value, "adapter_sha256"):
        _fail("adapter_digest_mismatch")
    return dict(value)


__all__ = [
    "MAX_PROJECT_ENTRYPOINT_DESCRIPTOR_BYTES",
    "PROJECT_ENTRYPOINT_ADAPTER_PROTOCOL",
    "PROJECT_ENTRYPOINT_ADAPTER_SCHEMA_VERSION",
    "PROJECT_ENTRYPOINT_DESCRIPTOR_PROTOCOL",
    "PROJECT_ENTRYPOINT_DESCRIPTOR_SCHEMA_VERSION",
    "ProjectEntrypointDescriptor",
    "ProjectEntrypointDescriptorError",
    "build_project_entrypoint_descriptor",
    "compose_project_entrypoint_lifecycle",
    "parse_project_entrypoint_descriptor",
    "parse_project_entrypoint_lifecycle",
]
