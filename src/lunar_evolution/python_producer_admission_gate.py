"""Provider-free, zero-side-effect composition gate for Feature191 evidence.

This module deliberately consumes already validated DTOs only.  It does not read a
workspace, inspect a process, call an evaluator, update a journal, or consume a
budget.  ``eligible`` means that the supplied local evidence is internally coherent;
it is never a production-admission decision (``production_admission`` is always
false).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from .producer_bundle_admission import ProducerBundleAdmissionPlan
from .producer_bundle_publication import (
    ProducerBundlePublicationJournal,
    parse_producer_bundle_publication_journal,
)
from .producer_handoff import (
    MAX_PRODUCER_ENVELOPE_BYTES,
    ProducerResultEnvelope,
    parse_producer_envelope,
)
from .producer_process import (
    ProducerEnvelopeEvidence,
    ProducerExecutionReceipt,
    ProducerStreamEvidence,
    parse_producer_execution_receipt,
)
from .python_producer_admission_handoff import (
    PythonProducerAdmissionHandoff,
    parse_python_producer_admission_handoff,
)
from .python_producer_binding import PythonProducerBinding, parse_python_producer_binding
from .python_producer_binding_store import PythonProducerBindingSidecar
from .python_producer_checkpoint import PythonProducerCheckpointBinding
from .python_producer_lifecycle import (
    PythonProducerRuntimeObservation,
    PythonProducerTerminal,
    parse_python_producer_runtime_observation,
    parse_python_producer_terminal,
)


class PythonProducerAdmissionGateError(ValueError):
    """Reserved for callers that need a fixed gate error code."""

    def __init__(self, code: str) -> None:
        self.code = "python_producer_admission_gate_" + code
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class PythonProducerAdmissionGateResult:
    """Read-only result of local evidence composition.

    The digest projections are retained even for a successful local check so a
    caller can bind the result to an audit record.  They do not grant publication
    or runtime protection authority.
    """

    eligible: bool
    reason_code: str | None
    handoff_sha256: str | None
    binding_sha256: str | None
    sidecar_raw_sha256: str | None
    sidecar_pin_sha256: str | None
    terminal_sha256: str | None
    runtime_observation_sha256: str | None
    native_execution_receipt_sha256: str | None
    envelope_sha256: str | None
    materials_sha256: str | None
    admission_plan_sha256: str | None
    journal_sha256: str | None
    production_admission: bool = False

    @property
    def accepted(self) -> bool:
        return self.eligible

    @property
    def refused(self) -> bool:
        return not self.eligible

    @property
    def status(self) -> str:
        return "accepted" if self.eligible else "refused"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _digest_pin(value: object) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _identity_digest(binding: PythonProducerBinding) -> str:
    interpreter = binding.interpreter
    return _sha({
        "sha256": interpreter.sha256,
        "size": interpreter.size,
        "device": interpreter.device,
        "inode": interpreter.inode,
        "mtime_ns": interpreter.mtime_ns,
        "ctime_ns": interpreter.ctime_ns,
    })


def _owner_digest(receipt: ProducerExecutionReceipt) -> str:
    return _sha(dict(receipt.owner_identity))


def _mapping_digest(value: Mapping[str, object] | None) -> str | None:
    """Digest one detached authority projection supplied by the caller.

    Feature190 keeps the live executable owner private to its acquisition context.  The
    provider-free gate therefore consumes the caller's retained, JSON-shaped projection and
    never treats the child process ``owner_identity`` as that authority.
    """
    if type(value) is not dict:
        return None
    try:
        detached = json.loads(_canonical(value))
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None
    if type(detached) is not dict:
        return None
    return _sha(detached)


def _materials_digest(envelope: ProducerResultEnvelope) -> str:
    """Return the canonical digest of the envelope's material descriptors."""
    return _sha([item.to_dict() for item in envelope.materials])


def _file_identity_digest(*, size: int, device: int, inode: int, mtime_ns: int, ctime_ns: int) -> str:
    """Match the native capture identity projection without touching the filesystem."""
    return _sha({
        "device": device,
        "inode": inode,
        "size": size,
        "mtime_ns": mtime_ns,
        "ctime_ns": ctime_ns,
    })


def _stream_evidence_is_stable(stream: object, *, expected: str, limit: int) -> bool:
    if type(stream) is not ProducerStreamEvidence:
        return False
    if stream.stream != expected or type(stream.bytes_observed) is not int:
        return False
    if stream.bytes_observed < 0 or stream.bytes_observed > limit:
        return False
    if not _digest_pin(stream.sha256) or type(stream.truncated) is not bool:
        return False
    expected_status = "limit_exceeded" if stream.truncated else "complete"
    return stream.capture_status == expected_status and not stream.truncated


def _envelope_evidence_is_stable(
    evidence: object,
    *,
    expected_path: str,
    limit: int,
) -> bool:
    if type(evidence) is not ProducerEnvelopeEvidence:
        return False
    if evidence.relative_path != expected_path or evidence.read_status != "stable":
        return False
    if not _digest_pin(evidence.sha256) or type(evidence.bytes) is not int:
        return False
    if evidence.bytes < 0 or evidence.bytes > limit:
        return False
    if any(type(getattr(evidence, field)) is not int or getattr(evidence, field) < 0
           for field in ("device", "inode", "mtime_ns", "ctime_ns")):
        return False
    if not _digest_pin(evidence.identity_before) or evidence.identity_before != evidence.identity_after:
        return False
    return evidence.identity_before == _file_identity_digest(
        size=evidence.bytes,
        device=evidence.device,
        inode=evidence.inode,
        mtime_ns=evidence.mtime_ns,
        ctime_ns=evidence.ctime_ns,
    )


def _reject(code: str, *, values: dict[str, str | None] | None = None) -> PythonProducerAdmissionGateResult:
    values = values or {}
    return PythonProducerAdmissionGateResult(
        eligible=False,
        reason_code="python_producer_admission_gate_" + code,
        handoff_sha256=values.get("handoff_sha256"),
        binding_sha256=values.get("binding_sha256"),
        sidecar_raw_sha256=values.get("sidecar_raw_sha256"),
        sidecar_pin_sha256=values.get("sidecar_pin_sha256"),
        terminal_sha256=values.get("terminal_sha256"),
        runtime_observation_sha256=values.get("runtime_observation_sha256"),
        native_execution_receipt_sha256=values.get("native_execution_receipt_sha256"),
        envelope_sha256=values.get("envelope_sha256"),
        materials_sha256=values.get("materials_sha256"),
        admission_plan_sha256=values.get("admission_plan_sha256"),
        journal_sha256=values.get("journal_sha256"),
    )


def _ok(
    handoff: PythonProducerAdmissionHandoff,
    sidecar_pin_sha256: str,
    journal: ProducerBundlePublicationJournal | None,
) -> PythonProducerAdmissionGateResult:
    return PythonProducerAdmissionGateResult(
        eligible=True,
        reason_code=None,
        handoff_sha256=handoff.handoff_sha256,
        binding_sha256=handoff.binding_sha256,
        sidecar_raw_sha256=handoff.sidecar_raw_sha256,
        sidecar_pin_sha256=sidecar_pin_sha256,
        terminal_sha256=handoff.terminal_sha256,
        runtime_observation_sha256=handoff.runtime_observation_sha256,
        native_execution_receipt_sha256=handoff.native_execution_receipt_sha256,
        envelope_sha256=handoff.envelope_sha256,
        materials_sha256=handoff.materials_sha256,
        admission_plan_sha256=handoff.admission_plan_sha256,
        journal_sha256=None if journal is None else journal.journal_sha256,
    )


def verify_python_producer_admission_gate(
    *,
    binding: PythonProducerBinding,
    sidecar: PythonProducerBindingSidecar,
    handoff: PythonProducerAdmissionHandoff,
    terminal: PythonProducerTerminal,
    runtime_observation: PythonProducerRuntimeObservation,
    native_receipt: ProducerExecutionReceipt,
    admission_plan: ProducerBundleAdmissionPlan,
    journal: ProducerBundlePublicationJournal | None = None,
    envelope: ProducerResultEnvelope | None = None,
    envelope_sha256: str | None = None,
    envelope_evidence_sha256: str | None = None,
    executable_owner_sha256: str | None = None,
    executable_owner_evidence: Mapping[str, object] | None = None,
    materials_sha256: str | None = None,
    broker_deadline_monotonic_ns: int | None = None,
) -> PythonProducerAdmissionGateResult:
    """Compose detached Feature191 evidence without any external side effect.

    Every DTO is reparsed from its canonical wire before comparison.  Deliberately
    mutated frozen instances therefore fail closed instead of being trusted by
    identity alone.  ``envelope`` and ``executable_owner_evidence`` are detached
    provider-free authority projections; the gate never reads their source files or
    treats a child process owner as the Feature190 executable owner.  The raw output
    file digest is supplied separately as ``envelope_evidence_sha256``. The caller
    separately supplies the retained native broker's absolute monotonic deadline;
    it cannot be reconstructed from the Unix deadline or a new clock sample.
    """
    values: dict[str, str | None] = {}
    try:
        if type(binding) is not PythonProducerBinding:
            return _reject("binding_type_invalid")
        parsed_binding = parse_python_producer_binding(binding.to_json())
        if parsed_binding != binding or parsed_binding.binding_sha256 is None:
            return _reject("binding_drift")
        values["binding_sha256"] = parsed_binding.binding_sha256

        if type(sidecar) is not PythonProducerBindingSidecar or sidecar.binding != parsed_binding:
            return _reject("sidecar_binding_mismatch", values=values)
        # The sidecar is the retained raw canonical binding and stat pin; this computes
        # both independently without touching its workspace path.
        raw = parsed_binding.to_json()
        raw_digest = hashlib.sha256(raw).hexdigest()
        if sidecar.raw_sha256 != raw_digest or sidecar.raw_size != len(raw):
            return _reject("sidecar_raw_mismatch", values={**values, "sidecar_raw_sha256": sidecar.raw_sha256})
        checkpoint = PythonProducerCheckpointBinding.from_sidecar(sidecar)
        sidecar_pin_digest = hashlib.sha256(_canonical(dict(checkpoint.sidecar_pin))).hexdigest()
        values.update(sidecar_raw_sha256=raw_digest, sidecar_pin_sha256=sidecar_pin_digest)

        parsed_handoff = parse_python_producer_admission_handoff(handoff)
        values["handoff_sha256"] = parsed_handoff.handoff_sha256
        if parsed_handoff.state != "prepared":
            return _reject("handoff_state_invalid", values=values)
        if parsed_handoff.binding_sha256 != parsed_binding.binding_sha256:
            return _reject("handoff_binding_mismatch", values=values)
        if parsed_handoff.sidecar_raw_sha256 != raw_digest or parsed_handoff.sidecar_pin_sha256 != sidecar_pin_digest:
            return _reject("handoff_sidecar_mismatch", values=values)

        parsed_terminal = parse_python_producer_terminal(terminal.to_json())
        parsed_observation = parse_python_producer_runtime_observation(runtime_observation.to_json())
        parsed_receipt = parse_producer_execution_receipt(native_receipt.to_dict())
        parsed_plan = admission_plan.from_dict(admission_plan.to_dict())
        if type(envelope) is not ProducerResultEnvelope:
            return _reject("envelope_unverified", values=values)
        parsed_envelope = parse_producer_envelope(envelope.to_dict())
        if parsed_envelope != envelope:
            return _reject("envelope_drift", values=values)
        envelope_digest = parsed_envelope.envelope_sha256
        material_digest = _materials_digest(parsed_envelope)
        values.update(envelope_sha256=envelope_digest, materials_sha256=material_digest)
        parsed_journal = None
        if journal is not None:
            parsed_journal = parse_producer_bundle_publication_journal(journal.to_dict())
        values.update(
            terminal_sha256=parsed_terminal.terminal_sha256,
            runtime_observation_sha256=parsed_observation.observation_sha256,
            native_execution_receipt_sha256=parsed_receipt.receipt_sha256,
            admission_plan_sha256=parsed_plan.digest(),
            journal_sha256=None if parsed_journal is None else parsed_journal.journal_sha256,
        )
        if parsed_terminal != terminal or parsed_observation != runtime_observation or parsed_receipt != native_receipt:
            return _reject("evidence_drift", values=values)

        ids = (parsed_binding.run_id, parsed_binding.intent.journal_id, parsed_binding.parent_task_id, parsed_binding.task_id)
        if (parsed_handoff.run_id, parsed_handoff.journal_id, parsed_handoff.parent_task_id, parsed_handoff.task_id) != ids:
            return _reject("handoff_identity_mismatch", values=values)
        if (parsed_terminal.run_id, parsed_terminal.journal_id) != ids[:2] or parsed_terminal.launch_id != parsed_binding.intent.launch_id:
            return _reject("terminal_identity_mismatch", values=values)
        if (parsed_terminal.binding_sha256 != parsed_binding.binding_sha256
                or parsed_terminal.deadline_unix != parsed_binding.deadline_unix):
            return _reject("terminal_binding_mismatch", values=values)
        if (parsed_receipt.run_id, parsed_receipt.journal_id, parsed_receipt.parent_task_id, parsed_receipt.task_id) != ids:
            return _reject("receipt_identity_mismatch", values=values)
        if parsed_observation.binding_sha256 != parsed_binding.binding_sha256:
            return _reject("observation_binding_mismatch", values=values)

        handoff_pairs = (
            ("launch_intent_sha256", parsed_binding.intent_sha256),
            ("attestation_sha256", parsed_binding.attestation_sha256),
            ("runtime_manifest_sha256", parsed_binding.runtime_manifest_sha256),
            ("runtime_tree_sha256", parsed_binding.runtime_tree_sha256),
            ("native_execution_receipt_sha256", parsed_receipt.receipt_sha256),
            ("terminal_sha256", parsed_terminal.terminal_sha256),
            ("runtime_observation_sha256", parsed_observation.observation_sha256),
            ("broker_transcript_sha256", parsed_observation.broker_transcript_sha256),
            ("contract_sha256", parsed_binding.contract_sha256),
            ("evaluator_sha256", parsed_binding.evaluator_fingerprint),
            ("runner_sha256", parsed_binding.intent.runner_fingerprint),
            ("dependency_sha256", parsed_binding.dependency_sha256),
            ("environment_sha256", parsed_binding.environment_sha256),
            ("admission_plan_sha256", parsed_plan.digest()),
        )
        for field, expected in handoff_pairs:
            if expected is None or getattr(parsed_handoff, field) != expected:
                return _reject("handoff_" + field.removesuffix("_sha256") + "_mismatch", values=values)
        if (parsed_handoff.request_budget != parsed_binding.request_budget
                or parsed_handoff.wall_timeout_seconds != parsed_binding.wall_timeout_seconds
                or parsed_handoff.deadline_unix != parsed_binding.deadline_unix):
            return _reject("handoff_budget_mismatch", values=values)

        if parsed_terminal.status != "completed" or parsed_terminal.exit_code != 0 or parsed_terminal.signal is not None:
            return _reject("terminal_not_successful", values=values)
        if parsed_terminal.cleanup_status not in {"cleaned", "already_exited"} or parsed_terminal.publication_eligible:
            return _reject("terminal_cleanup_or_claim_invalid", values=values)
        if parsed_terminal.exited_unix is None or parsed_terminal.exited_unix >= parsed_binding.deadline_unix:
            return _reject("terminal_deadline_invalid", values=values)
        interpreter = parsed_binding.interpreter
        if (parsed_terminal.executable_sha256 != interpreter.sha256
                or parsed_terminal.executable_size != interpreter.size
                or parsed_terminal.executable_device != interpreter.device
                or parsed_terminal.executable_inode != interpreter.inode
                or parsed_terminal.process_registration_sha256 != parsed_receipt.registration_sha256
                or parsed_terminal.owner_identity_sha256 != _owner_digest(parsed_receipt)
                or parsed_terminal.stdout_sha256 != parsed_receipt.stdout_evidence.sha256
                or parsed_terminal.stderr_sha256 != parsed_receipt.stderr_evidence.sha256
                or parsed_terminal.request_journal_sha256 != parsed_receipt.trusted_execution.get("broker_journal_sha256")
                or parsed_terminal.request_count != parsed_receipt.request_count
                or parsed_terminal.request_count > parsed_binding.request_budget):
            return _reject("terminal_receipt_mismatch", values=values)

        if (parsed_receipt.receipt_sha256 != parsed_handoff.native_execution_receipt_sha256
                or parsed_receipt.launch_id != parsed_binding.intent.launch_id
                or parsed_receipt.intent_sha256 != parsed_binding.intent_sha256
                or parsed_receipt.attestation_sha256 != parsed_binding.attestation_sha256
                or parsed_receipt.status != "completed" or parsed_receipt.exit_code != 0
                or parsed_receipt.gate_released is not True
                or parsed_receipt.cleanup_status not in {"cleaned", "already_exited"}
                or parsed_receipt.request_timeout_seconds != parsed_binding.intent.request_timeout_seconds
                or parsed_receipt.max_requests != parsed_binding.request_budget
                or parsed_receipt.output_max_bytes != parsed_binding.output_max_bytes
                or parsed_receipt.wall_timeout_seconds != parsed_binding.wall_timeout_seconds
                or parsed_receipt.execution_snapshot_sha256 != interpreter.sha256
                or parsed_receipt.execution_snapshot_size != interpreter.size
                or parsed_receipt.executable_identity != _identity_digest(parsed_binding)
                or parsed_receipt.trusted_execution is None
                or parsed_receipt.trusted_execution.get("broker_coverage") != "brokered_requests_only"):
            return _reject("native_receipt_mismatch", values=values)

        # A successful terminal must carry complete, bounded stream capture and a stable,
        # path-bound envelope observation.  The generic receipt DTO is transport-neutral;
        # these lifecycle semantics belong to the composition gate.
        if (not _stream_evidence_is_stable(
                parsed_receipt.stdout_evidence, expected="stdout", limit=parsed_binding.output_max_bytes)
                or not _stream_evidence_is_stable(
                    parsed_receipt.stderr_evidence, expected="stderr", limit=parsed_binding.output_max_bytes)
                or not _envelope_evidence_is_stable(
                    parsed_receipt.envelope_evidence,
                    expected_path=parsed_binding.envelope_path,
                    limit=min(parsed_binding.output_max_bytes, MAX_PRODUCER_ENVELOPE_BYTES),
                )):
            return _reject("output_evidence_invalid", values=values)

        trusted = parsed_receipt.trusted_execution
        assert trusted is not None
        broker_identity = trusted.get("broker_journal_identity")
        if type(broker_deadline_monotonic_ns) is not int or not 0 < broker_deadline_monotonic_ns < 2**63:
            return _reject("broker_deadline_unverified", values=values)
        expected_broker_identity = {
            "launch_id": parsed_binding.intent.launch_id,
            "journal_id": parsed_binding.intent.journal_id,
            "run_id": parsed_binding.run_id,
            "parent_task_id": parsed_binding.parent_task_id,
            "task_id": parsed_binding.task_id,
            "intent_sha256": parsed_binding.intent_sha256,
            "request_timeout_seconds": parsed_binding.intent.request_timeout_seconds,
            "max_requests": parsed_binding.request_budget,
            "wall_deadline_ns": broker_deadline_monotonic_ns,
        }
        if (broker_identity != expected_broker_identity
                or trusted.get("broker_journal_sha256") != parsed_terminal.request_journal_sha256
                or trusted.get("broker_admitted_count") != parsed_receipt.request_count
                or trusted.get("broker_declared_count_matches") is not True):
            return _reject("broker_journal_mismatch", values=values)

        if (parsed_observation.execution_performed is not True or parsed_observation.pycache_absent is not True
                or parsed_observation.broker_transcript_sha256 != parsed_handoff.broker_transcript_sha256
                or parsed_observation.runtime_load_protection is not False
                or parsed_observation.production_admission is not False
                or parsed_observation.general_code_origin_protection is not False):
            return _reject("runtime_observation_claim_invalid", values=values)
        target = parsed_binding.runtime_manifest.target
        major, minor = (int(part) for part in target.python_version.split(".", 1))
        expected_cache_tag = f"cpython-{major}{minor}"
        expected_flags = tuple(parsed_binding.runtime_manifest.to_dict()["policy"]["argv_flags"])
        if (parsed_observation.version_major != major
                or parsed_observation.version_minor != minor
                or parsed_observation.cache_tag != expected_cache_tag
                or not parsed_observation.abi_profile.startswith(target.abi_tag + "-")
                or tuple(parsed_observation.flags) != expected_flags
                or tuple(parsed_observation.argv) != tuple(parsed_binding.intent.argv)
                or tuple(parsed_observation.orig_argv) != tuple(parsed_binding.intent.argv)):
            return _reject("runtime_observation_target_mismatch", values=values)
        if not _digest_pin(envelope_sha256):
            return _reject("envelope_pin_unverified", values=values)
        if parsed_handoff.envelope_sha256 != envelope_sha256 or envelope_sha256 != envelope_digest:
            return _reject("envelope_pin_mismatch", values=values)
        if not _digest_pin(envelope_evidence_sha256):
            return _reject("envelope_evidence_pin_unverified", values=values)
        if (parsed_receipt.envelope_evidence is None
                or envelope_evidence_sha256 != parsed_receipt.envelope_evidence.sha256):
            return _reject("envelope_evidence_pin_mismatch", values=values)
        if not _digest_pin(executable_owner_sha256):
            return _reject("executable_owner_pin_unverified", values=values)
        owner_evidence_digest = _mapping_digest(executable_owner_evidence)
        if owner_evidence_digest is None:
            return _reject("executable_owner_evidence_unverified", values=values)
        if executable_owner_sha256 != owner_evidence_digest:
            return _reject("executable_owner_pin_mismatch", values=values)
        if parsed_handoff.executable_owner_sha256 != executable_owner_sha256:
            return _reject("executable_owner_pin_mismatch", values=values)
        if not _digest_pin(materials_sha256):
            return _reject("materials_pin_unverified", values=values)
        if parsed_handoff.materials_sha256 != materials_sha256:
            return _reject("materials_pin_mismatch", values=values)

        authority = (
            ("contract_sha256", parsed_binding.contract_sha256),
            ("evaluator_fingerprint", parsed_binding.evaluator_fingerprint),
            ("runner_fingerprint", parsed_binding.intent.runner_fingerprint),
            ("dependency_sha256", parsed_binding.dependency_sha256),
            ("environment_sha256", parsed_binding.environment_sha256),
        )
        if any(getattr(parsed_plan, field) != expected for field, expected in authority):
            return _reject("admission_plan_authority_mismatch", values=values)
        envelope_requests = parsed_envelope.budget.get("requests")
        if (parsed_envelope.status != "completed"
                or parsed_envelope.contract_sha256 != parsed_binding.contract_sha256
                or parsed_envelope.producer_id != parsed_binding.intent.producer_id
                or type(envelope_requests) is not int
                or envelope_requests != parsed_receipt.request_count
                or envelope_requests > parsed_binding.request_budget):
            return _reject("envelope_claim_invalid", values=values)
        if (parsed_envelope.producer_fingerprint != parsed_binding.intent.producer_fingerprint
                or parsed_envelope.producer_run_id != parsed_binding.run_id
                or tuple(sorted(item.path for item in parsed_envelope.materials)) != tuple(sorted(
                    path for bundle in parsed_plan.bundles for path in bundle.material_paths
                ))
                or material_digest != materials_sha256
                or parsed_handoff.materials_sha256 != materials_sha256):
            return _reject("materials_pin_mismatch", values=values)
        if parsed_plan.evaluator_kind != "local":
            return _reject("evaluator_kind_invalid", values=values)
        if parsed_journal is not None and (
                parsed_journal.state != "prepared"
                    or parsed_journal.python_handoff_sha256 != parsed_handoff.handoff_sha256
                    or parsed_journal.admission_sha256 != parsed_plan.digest()
                    or parsed_journal.native_execution_receipt_sha256 != parsed_receipt.receipt_sha256
                    or parsed_journal.evaluator_kind != parsed_plan.evaluator_kind
                    or (parsed_journal.run_id, parsed_journal.journal_id, parsed_journal.parent_task_id, parsed_journal.task_id) != ids
                    or any(getattr(parsed_journal, field) != expected for field, expected in authority)):
                return _reject("journal_authority_mismatch", values=values)
        return _ok(parsed_handoff, sidecar_pin_digest, parsed_journal)
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError, OverflowError) as exc:
        code = getattr(exc, "code", "evidence_invalid")
        if not isinstance(code, str) or not code:
            code = "evidence_invalid"
        return _reject(code.removeprefix("python_producer_"), values=values)


__all__ = [
    "PythonProducerAdmissionGateError",
    "PythonProducerAdmissionGateResult",
    "verify_python_producer_admission_gate",
]
