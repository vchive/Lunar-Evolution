"""Immutable native RSI execution-plan contract.

The plan is the pre-launch composition boundary for Feature 160.  It binds the complete
``SolverRequest`` to an approved memory snapshot and the exact native launch identities.  The
plan carries no process, attestation-consumption, candidate-publication, or memory-write
authority; those remain owned by the controller and native scheduler.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .candidate_evaluation_spec import canonical_json, strict_json
from .rsi_gateway import SolverRequest
from .rsi_learning import MemorySnapshot

_PROTOCOL = "lunar-rsi-native-execution-plan-v1"
_SCHEMA_VERSION = "1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MAX_BYTES = 128 * 1024


class NativeRSIExecutionPlanError(ValueError):
    """Fixed-code refusal for malformed or drifted native execution plans."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise NativeRSIExecutionPlanError("rsi_native_plan_" + code)


def _id(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(f"{field}_invalid")
    return value


def _sha(value: object, field: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail(f"{field}_invalid")
    return value


def _digest(value: Mapping[str, object], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    try:
        return hashlib.sha256(canonical_json(payload, maximum=_MAX_BYTES)).hexdigest()
    except Exception as exc:  # pragma: no cover - canonical_json already fixes public code
        raise NativeRSIExecutionPlanError("rsi_native_plan_canonical_invalid") from exc


def _strict_mapping(value: object, fields: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields or any(type(key) is not str for key in value):
        _fail(code)
    try:
        encoded = canonical_json(value, maximum=_MAX_BYTES)
        parsed = strict_json(encoded, maximum=_MAX_BYTES)
    except Exception as exc:
        raise NativeRSIExecutionPlanError("rsi_native_plan_canonical_invalid") from exc
    if parsed != value or canonical_json(parsed, maximum=_MAX_BYTES) != encoded:
        _fail(code)
    return value


_TOP_FIELDS = {
    "schema_version", "protocol", "request", "request_sha256", "memory_snapshot_sha256",
    "journal_id", "launch_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
    "attestation_sha256", "bootstrap_descriptor_sha256", "bootstrap_artifact_sha256",
    "manifest_sha256", "request_relative_path", "memory_relative_path", "deadline_unix",
    "candidate_selector_id", "candidate_selector_sha256", "evaluator_kind",
    "evaluator_fingerprint", "plan_sha256",
}


@dataclass(frozen=True, slots=True)
class NativeRSIExecutionPlan:
    """Canonical, immutable identity for one native RSI attempt.

    ``request`` is copied through its canonical wire representation on construction.  The
    approved memory bytes themselves stay in the create-only native input files; this plan pins
    their digest and manifest.  A plan is therefore safe to persist and replay, but never acts as
    an execution or publication receipt.
    """

    request: SolverRequest
    request_sha256: str
    memory_snapshot_sha256: str
    journal_id: str
    launch_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    intent_sha256: str
    attestation_sha256: str
    bootstrap_descriptor_sha256: str
    bootstrap_artifact_sha256: str
    manifest_sha256: str
    request_relative_path: str
    memory_relative_path: str
    deadline_unix: float | None
    candidate_selector_id: str
    candidate_selector_sha256: str
    evaluator_kind: str
    evaluator_fingerprint: str
    plan_sha256: str | None = None
    schema_version: str = _SCHEMA_VERSION
    protocol: str = _PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION or self.protocol != _PROTOCOL:
            _fail("schema_invalid")
        if not isinstance(self.request, SolverRequest):
            _fail("request_invalid")
        # Reconstructing from canonical wire bytes prevents mutable nested mappings escaping
        # through a caller-owned SolverRequest object.
        try:
            frozen_request = SolverRequest.from_dict(strict_json(
                canonical_json(self.request.to_dict(), maximum=_MAX_BYTES), maximum=_MAX_BYTES,
            ))
        except Exception as exc:
            raise NativeRSIExecutionPlanError("rsi_native_plan_request_invalid") from exc
        if frozen_request != self.request:
            _fail("request_invalid")
        request_digest = frozen_request.digest()
        if self.request_sha256 != request_digest:
            _fail("request_digest_mismatch")
        _sha(self.memory_snapshot_sha256, "memory_snapshot")
        if frozen_request.memory_snapshot_sha256 != self.memory_snapshot_sha256:
            _fail("memory_digest_mismatch")
        for value, field in (
            (self.journal_id, "journal"), (self.launch_id, "launch"), (self.run_id, "run"),
            (self.parent_task_id, "parent_task"), (self.task_id, "task"),
            (self.candidate_selector_id, "candidate_selector"), (self.evaluator_kind, "evaluator_kind"),
        ):
            _id(value, field)
        for value, field in (
            (self.intent_sha256, "intent"), (self.attestation_sha256, "attestation"),
            (self.bootstrap_descriptor_sha256, "bootstrap_descriptor"),
            (self.bootstrap_artifact_sha256, "bootstrap_artifact"),
            (self.manifest_sha256, "manifest"), (self.candidate_selector_sha256, "candidate_selector_digest"),
            (self.evaluator_fingerprint, "evaluator"),
        ):
            _sha(value, field)
        for value, field in ((self.request_relative_path, "request_path"), (self.memory_relative_path, "memory_path")):
            if type(value) is not str or not value or "\x00" in value or value.startswith("/"):
                _fail(f"{field}_invalid")
            parts = value.split("/")
            if any(part in {"", "."} for part in parts) or parts.count("..") > 1 or (".." in parts and parts[0] != ".."):
                _fail(f"{field}_invalid")
        if (self.deadline_unix is not None and (
                type(self.deadline_unix) not in (int, float)
                or not math.isfinite(float(self.deadline_unix))
                or self.deadline_unix <= 0)):
            _fail("deadline_invalid")
        if self.plan_sha256 is not None and self.plan_sha256 != self.digest():
            _fail("digest_mismatch")
        if self.plan_sha256 is None:
            object.__setattr__(self, "plan_sha256", self.digest())

    @classmethod
    def build(
        cls,
        *,
        request: SolverRequest,
        memory_snapshot: MemorySnapshot | None = None,
        request_sha256: str | None = None,
        memory_snapshot_sha256: str | None = None,
        journal_id: str,
        launch_id: str,
        run_id: str,
        parent_task_id: str,
        task_id: str,
        intent_sha256: str,
        attestation_sha256: str,
        bootstrap_descriptor_sha256: str,
        bootstrap_artifact_sha256: str,
        manifest_sha256: str,
        request_relative_path: str = "../.rsi-input/request.json",
        memory_relative_path: str = "../.rsi-input/memory.json",
        deadline_unix: float | None = None,
        candidate_selector_id: str = "native-selector-v1",
        candidate_selector_sha256: str,
        evaluator_kind: str,
        evaluator_fingerprint: str,
    ) -> NativeRSIExecutionPlan:
        if not isinstance(request, SolverRequest):
            _fail("request_invalid")
        if memory_snapshot is not None:
            if not isinstance(memory_snapshot, MemorySnapshot) or memory_snapshot.digest() != request.memory_snapshot_sha256:
                _fail("memory_digest_mismatch")
            memory_snapshot_sha256 = memory_snapshot.digest()
        if memory_snapshot_sha256 is None:
            memory_snapshot_sha256 = request.memory_snapshot_sha256
        if request_sha256 is None:
            request_sha256 = request.digest()
        return cls(
            request=request, request_sha256=request_sha256, memory_snapshot_sha256=memory_snapshot_sha256,
            journal_id=journal_id, launch_id=launch_id, run_id=run_id, parent_task_id=parent_task_id,
            task_id=task_id, intent_sha256=intent_sha256, attestation_sha256=attestation_sha256,
            bootstrap_descriptor_sha256=bootstrap_descriptor_sha256, bootstrap_artifact_sha256=bootstrap_artifact_sha256,
            manifest_sha256=manifest_sha256, request_relative_path=request_relative_path,
            memory_relative_path=memory_relative_path, deadline_unix=deadline_unix,
            candidate_selector_id=candidate_selector_id, candidate_selector_sha256=candidate_selector_sha256,
            evaluator_kind=evaluator_kind, evaluator_fingerprint=evaluator_fingerprint,
        )

    @classmethod
    def from_native_inputs(
        cls, *, request: SolverRequest, memory: MemorySnapshot, inputs: Any, intent: Any,
        attestation: Any, artifact: Any, candidate_selector_id: str,
        candidate_selector_sha256: str, evaluator_kind: str, evaluator_fingerprint: str,
    ) -> NativeRSIExecutionPlan:
        """Construct a plan only from already validated native input/launch DTOs.

        This helper performs identity checks before copying values.  It intentionally does not
        validate or consume an attestation itself; callers must use
        ``validate_native_rsi_launch_inputs`` immediately before dispatch as well.
        """
        try:
            from .native_bootstrap import NativeBootstrapArtifact
            from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
            from .rsi_native_inputs import NativeRSIInputDescriptor
            if (not isinstance(inputs, NativeRSIInputDescriptor)
                    or not isinstance(intent, ProducerLaunchIntent)
                    or not isinstance(attestation, ProducerLaunchAttestation)
                    or not isinstance(artifact, NativeBootstrapArtifact)):
                _fail("binding_invalid")
            if inputs.request != request or inputs.memory != memory:
                _fail("input_drift")
            if intent.journal_id != inputs.journal_id or intent.contract_sha256 != request.contract_sha256:
                _fail("binding_mismatch")
            if intent.evaluator_fingerprint != request.evaluator_sha256 or intent.environment_sha256 != request.environment_sha256:
                _fail("binding_mismatch")
            return cls.build(
                request=request, memory_snapshot=memory, journal_id=intent.journal_id,
                launch_id=intent.launch_id, run_id=intent.run_id, parent_task_id=intent.parent_task_id,
                task_id=intent.task_id, intent_sha256=intent.digest(), attestation_sha256=attestation.digest(),
                bootstrap_descriptor_sha256=artifact.descriptor.digest(), bootstrap_artifact_sha256=artifact.artifact_sha256,
                manifest_sha256=inputs.manifest_sha256, deadline_unix=inputs.deadline_unix,
                candidate_selector_id=candidate_selector_id, candidate_selector_sha256=candidate_selector_sha256,
                evaluator_kind=evaluator_kind, evaluator_fingerprint=evaluator_fingerprint,
            )
        except NativeRSIExecutionPlanError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise NativeRSIExecutionPlanError("rsi_native_plan_binding_invalid") from exc

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "request": self.request.to_dict(), "request_sha256": self.request_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256, "journal_id": self.journal_id,
            "launch_id": self.launch_id, "run_id": self.run_id, "parent_task_id": self.parent_task_id,
            "task_id": self.task_id, "intent_sha256": self.intent_sha256,
            "attestation_sha256": self.attestation_sha256,
            "bootstrap_descriptor_sha256": self.bootstrap_descriptor_sha256,
            "bootstrap_artifact_sha256": self.bootstrap_artifact_sha256,
            "manifest_sha256": self.manifest_sha256, "request_relative_path": self.request_relative_path,
            "memory_relative_path": self.memory_relative_path, "deadline_unix": self.deadline_unix,
            "candidate_selector_id": self.candidate_selector_id,
            "candidate_selector_sha256": self.candidate_selector_sha256,
            "evaluator_kind": self.evaluator_kind, "evaluator_fingerprint": self.evaluator_fingerprint,
        }
        if include_digest:
            value["plan_sha256"] = self.plan_sha256
        return value

    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False), "plan_sha256")

    @classmethod
    def from_dict(cls, value: object) -> NativeRSIExecutionPlan:
        payload = _strict_mapping(value, _TOP_FIELDS, "wire_invalid")
        try:
            request = SolverRequest.from_dict(payload["request"])
            result = cls(
                request=request, request_sha256=payload["request_sha256"],
                memory_snapshot_sha256=payload["memory_snapshot_sha256"], journal_id=payload["journal_id"],
                launch_id=payload["launch_id"], run_id=payload["run_id"], parent_task_id=payload["parent_task_id"],
                task_id=payload["task_id"], intent_sha256=payload["intent_sha256"],
                attestation_sha256=payload["attestation_sha256"],
                bootstrap_descriptor_sha256=payload["bootstrap_descriptor_sha256"],
                bootstrap_artifact_sha256=payload["bootstrap_artifact_sha256"], manifest_sha256=payload["manifest_sha256"],
                request_relative_path=payload["request_relative_path"], memory_relative_path=payload["memory_relative_path"],
                deadline_unix=payload["deadline_unix"], candidate_selector_id=payload["candidate_selector_id"],
                candidate_selector_sha256=payload["candidate_selector_sha256"], evaluator_kind=payload["evaluator_kind"],
                evaluator_fingerprint=payload["evaluator_fingerprint"], plan_sha256=payload["plan_sha256"],
                schema_version=payload["schema_version"], protocol=payload["protocol"],
            )
        except NativeRSIExecutionPlanError:
            raise
        except Exception as exc:
            raise NativeRSIExecutionPlanError("rsi_native_plan_wire_invalid") from exc
        if canonical_json(result.to_dict(), maximum=_MAX_BYTES) != canonical_json(payload, maximum=_MAX_BYTES):
            _fail("wire_invalid")
        return result

    def assert_request_memory(self, request: SolverRequest, memory: MemorySnapshot) -> None:
        """Fail closed if caller inputs differ from the pre-launch plan."""
        if not isinstance(request, SolverRequest) or not isinstance(memory, MemorySnapshot):
            _fail("input_invalid")
        if request != self.request or request.digest() != self.request_sha256 or memory.digest() != self.memory_snapshot_sha256:
            _fail("input_drift")


__all__ = ["NativeRSIExecutionPlan", "NativeRSIExecutionPlanError"]
