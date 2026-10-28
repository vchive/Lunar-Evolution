"""Explicit expanded startup/native evidence inspection, never runtime admission.

The original native call can supply a startup snapshot, receipt and prepared
output. It cannot currently supply an original computation or pycache observer.
This separate protocol joins what exists and exports those missing boundaries;
it never converts startup facts to the legacy completed-runtime observation.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType

from . import native_fixed_live_sink as sink
from . import native_trusted_output as native_output
from . import native_trusted_scheduler as native
from . import openevolve_handoff as openevolve
from . import producer_bundle_admission as admission
from . import producer_handoff as handoff
from . import producer_launcher as launcher
from . import shinka_handoff as shinka
from . import static_python_fixed_runtime_observation as runtime
from .producer_handoff import ProducerMaterial, ProducerResultEnvelope
from .producer_request_transport import HostRequestJournalIdentity, HostRequestSnapshot
from .rsi_identity import component_fingerprint
from .static_python_fixed_live_modules import FIXED_LIVE_RUNTIME_SINK_PROFILE

PROTOCOL = "lunar-fixed-python-producer-evidence-inspection-v1"
MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
MISSING_EVIDENCE = (
    "original_computation_observation", "original_pycache_observation",
    "original_captured_envelope_semantic_join",
    "accepted_build_input_custody", "accepted_runtime_authority_root",
)


class FixedPythonProducerEvidenceError(ValueError):
    """A finite refusal without producer-controlled content or paths."""

    def __init__(self) -> None:
        super().__init__("fixed_python_producer_evidence_refused")


def _canonical(value: object) -> bytes:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    if not 0 < len(raw) <= MAX_EVIDENCE_BYTES:
        raise ValueError
    return raw


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _capture_pin(value: object, depth: int = 0) -> tuple:
    """Keep bounded strong identity and immutable content snapshots of captures."""
    if depth > 8:
        raise ValueError
    if type(value) in {type(None), bool, int, float, str, bytes}:
        return (type(value), id(value), value)
    if value is dataclasses._HAS_DEFAULT_FACTORY:
        return (type(value), id(value), value)
    if type(value) in {tuple, list}:
        if len(value) > 128:
            raise ValueError
        return (type(value), id(value), value, tuple(_capture_pin(item, depth + 1) for item in value))
    if type(value) is dict:
        if len(value) > 128 or any(type(key) is not str for key in value):
            raise ValueError
        return (dict, id(value), value,
                tuple((key, _capture_pin(value[key], depth + 1)) for key in sorted(value)))
    if isinstance(value, type):
        # Generated frozen dataclass constructors capture builtins.object.
        # This local strong identity pin does not broaden RSI identity policy.
        return (type, id(value), value)
    if type(value) is FunctionType:
        return (FunctionType, id(value), value, id(value.__code__), value.__code__)
    raise ValueError


def _function_pin(helper: object) -> tuple:
    if type(helper) is not FunctionType:
        raise ValueError
    closure = helper.__closure__
    cells = () if closure is None else tuple((id(cell), cell, _capture_pin(cell.cell_contents)) for cell in closure)
    return (helper, helper.__code__, id(helper), id(helper.__code__),
            _capture_pin(helper.__defaults__), _capture_pin(helper.__kwdefaults__),
            id(closure), closure, cells, component_fingerprint(helper, config={}))


def _implementation_pin() -> tuple:
    # Re-resolve actual dependencies, not just imported aliases. Retain the
    # callable and its code strongly as well as their fingerprint and identities.
    helpers = (
        _canonical, _sha, _join, _compare, _source_result, _implementation_pin, _original_objects,
        _validated_wire, _capture_pin, _function_pin,
        compose_fixed_python_producer_evidence, read_fixed_python_producer_evidence_export,
        vars(FixedPythonProducerEvidence)["to_json"], vars(FixedPythonProducerEvidence)["to_dict"],
        component_fingerprint, native._native_handoff_evidence, native._native_output_envelope_pin,
        native._prepublication_evidence, native_output._native_output_envelope_pin,
        native_output._unique_object, native_output.parse_producer_envelope,
        native_output._NativeTrustedEnvelopeAcquisition.__init__,
        native_output._NativeTrustedEnvelopeAcquisition.__copy__,
        native_output._NativeTrustedEnvelopeAcquisition.__deepcopy__,
        sink._pin_fixed_python_live_sink_request,
        sink._FixedPythonLiveSinkPin.assert_current,
        sink.FixedPythonLiveSinkRequest.validate, sink.FixedPythonLiveSinkRequest.compare,
        runtime.validate_fixed_python_runtime_observation_policy,
        runtime.map_fixed_python_runtime_observation, runtime._runtime_facts,
        launcher.parse_producer_launch_intent, launcher.parse_producer_launch_attestation,
        launcher.verify_producer_launch_attestation,
        openevolve._read_openevolve_snapshot, shinka._read_shinka_snapshot,
        *(getattr(openevolve, name) for name in (
            "_external_root", "_relative_to_root", "_open_flags", "_read_confined_regular",
            "_parse_result", "_reject_duplicate_json_keys", "_validate_evaluation_tree",
        )),
        *(getattr(shinka, name) for name in (
            "_root", "_database_path", "_database_signature", "_open_database", "_check_schema",
            "_select_rows", "_row_from_sql", "_lineage", "_candidate_source", "_read_regular",
            "_relative_path", "_open_flags",
        )),
        runtime.live.compare_fixed_python_bound_live_modules,
        *(getattr(runtime.profile, name) for name in (
            "_reparse", "_json", "_canonical", "_object", "_vector", "_digest",
        )),
        native.parse_producer_execution_receipt,
        native.ProducerExecutionReceipt.__init__, native.ProducerExecutionReceipt.to_dict,
        native.ProducerExecutionReceipt.digest, ProducerMaterial.__init__, ProducerMaterial.to_dict,
        ProducerResultEnvelope.__init__, ProducerResultEnvelope.to_dict,
        vars(ProducerResultEnvelope)["from_dict"].__func__,
        admission.ProducerBundleAdmissionPlan.__init__, admission.ProducerBundleAdmissionPlan.to_dict,
        vars(admission.ProducerBundleAdmissionPlan)["from_dict"].__func__,
        admission.ProducerBundleAdmissionPlan.digest, admission.parse_producer_bundle_admission_plan,
        HostRequestJournalIdentity.to_dict,
    )
    classes = (
        FixedPythonProducerEvidence, native.NativeTrustedProducerRun, native.NativeTrustedAttemptObservation,
        native.NativeTrustedOutputPreparation, native.ProducerExecutionReceipt, native.ProducerBrokerObservation,
        sink.FixedPythonLiveSinkRequest, sink._FixedPythonLiveSinkPin, runtime.FixedPythonRuntimeFacts,
        runtime.live.FixedPythonBoundLiveModules, runtime.profile.FixedPythonInstallation,
        launcher.ProducerLaunchIntent, launcher.ProducerLaunchAttestation, ProducerMaterial, ProducerResultEnvelope,
        handoff.ProducerMaterial, handoff.ProducerResultEnvelope, HostRequestJournalIdentity, HostRequestSnapshot,
        admission.ProducerBundleAdmissionPlan, native_output._NativeTrustedOutputOriginal,
        native_output._NativeTrustedEnvelopeAcquisition, native_output.ProducerEnvelopeEvidence,
    )
    return ((dataclasses._HAS_DEFAULT_FACTORY, id(dataclasses._HAS_DEFAULT_FACTORY)),
            tuple((klass, id(klass)) for klass in classes), tuple(_function_pin(helper) for helper in helpers))


def _join(run: native.NativeTrustedProducerRun, intent: launcher.ProducerLaunchIntent,
          attestation: launcher.ProducerLaunchAttestation,
          request: sink.FixedPythonLiveSinkRequest, facts: runtime.FixedPythonRuntimeFacts) -> dict:
    receipt, attempt, output = run.receipt, run.attempt, run.output
    observed, broker = facts.live_modules_observation, attempt.broker_observation
    if (launcher.parse_producer_launch_intent(intent.to_dict()) != intent
            or launcher.parse_producer_launch_attestation(attestation.to_dict()) != attestation
            or intent.producer_id not in {"openevolve", "shinka"}
            or request.installation.profile_version != f"fixed-{intent.producer_id}-v1"):
        raise ValueError
    launcher.verify_producer_launch_attestation(intent, attestation)
    identity = {name: getattr(intent, name) for name in (
        "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
    )}
    if (any(getattr(receipt, name) != value for name, value in identity.items())
            or attempt.launch_id != intent.launch_id or attempt.journal_id != intent.journal_id
            or receipt.intent_sha256 != intent.intent_sha256
            or receipt.attestation_sha256 != attestation.attestation_sha256
            or receipt.pid != observed.target_pid
            or (intent.executable_device, intent.executable_inode) != (observed.image_device, observed.image_inode)
            or receipt.execution_snapshot_sha256 != intent.executable_sha256
            or receipt.execution_snapshot_size != intent.executable_size
            or receipt.executable_identity != _sha({
                "sha256": intent.executable_sha256, "size": intent.executable_size,
                "device": intent.executable_device, "inode": intent.executable_inode,
                "mtime_ns": intent.executable_mtime_ns, "ctime_ns": intent.executable_ctime_ns,
            })
            or intent.executable_sha256 != hashlib.sha256(request.image).hexdigest()
            or intent.executable_size != len(request.image)
            or receipt.status != "completed" or receipt.exit_code != 0
            or receipt.gate_released is not True or attempt.gate_released is not True
            or attempt.target_started is not True or attempt.exit_code != 0
            or receipt.cleanup_status not in {"cleaned", "already_exited"}
            or attempt.cleanup_status != receipt.cleanup_status
            or attempt.registration_sha256 != receipt.registration_sha256
            or any(getattr(receipt, name) != getattr(intent, name) for name in (
                "request_timeout_seconds", "output_max_bytes", "wall_timeout_seconds"))
            or receipt.max_requests != intent.max_requests
            or type(receipt.request_count) is not int or not 0 <= receipt.request_count <= intent.max_requests):
        raise ValueError
    trusted = receipt.trusted_execution
    if (type(trusted) is not dict or type(broker) is not native.ProducerBrokerObservation
            or type(broker.journal_identity) is not HostRequestJournalIdentity
            or type(broker.snapshot) is not HostRequestSnapshot
            or type(broker.journal_path) is not type(Path())
            or broker.complete is not True or broker.reason != "completed"
            or broker.snapshot.active_count != 0 or not broker.snapshot.within_broker_limits
            or broker.snapshot.admitted_count != receipt.request_count
            or broker.snapshot.request_timeout_seconds != intent.request_timeout_seconds
            or broker.snapshot.max_requests != intent.max_requests
            or broker.snapshot.coverage != "brokered_requests_only"
            or broker.snapshot.clock_source != "controller_monotonic"
            or broker.journal_identity.wall_deadline_ns is None
            or trusted.get("broker_journal_identity") != broker.journal_identity.to_dict()
            or any(getattr(broker.journal_identity, name) != value for name, value in identity.items())
            or broker.journal_identity.intent_sha256 != intent.intent_sha256
            or broker.journal_identity.max_requests != intent.max_requests
            or broker.journal_identity.request_timeout_seconds != intent.request_timeout_seconds
            or trusted.get("broker_journal_sha256") != broker.journal_sha256
            or trusted.get("broker_journal_bytes") != broker.journal_bytes
            or type(broker.journal_file_identity) is not tuple
            or trusted.get("broker_journal_file_identity") != list(broker.journal_file_identity)
            or trusted.get("broker_admitted_count") != receipt.request_count
            or trusted.get("broker_declared_count_matches") is not True
            or trusted.get("broker_coverage") != "brokered_requests_only"
            or trusted.get("terminal_sha256") != attempt.terminal_sha256
            or trusted.get("stream_capture_sha256") != attempt.stream_capture_sha256
            or trusted.get("output_capture_sha256") != attempt.output_capture_sha256
            or output.process_terminal_sha256 != attempt.terminal_sha256
            or output.output_capture_sha256 != attempt.output_capture_sha256
            or output.execution_receipt_sha256 != receipt.receipt_sha256
            or output.publication_eligible is not False
            or output.request_coverage != "brokered_requests_only"):
        raise ValueError
    for stream, name in ((receipt.stdout_evidence, "stdout"), (receipt.stderr_evidence, "stderr")):
        if (stream.stream != name or stream.truncated is not False or stream.capture_status != "complete"
                or type(stream.bytes_observed) is not int
                or not 0 <= stream.bytes_observed <= intent.output_max_bytes):
            raise ValueError
    result = ProducerResultEnvelope.from_dict(output.envelope.to_dict())
    if (type(output.envelope) is not ProducerResultEnvelope or result != output.envelope
            or result.status != "completed" or result.producer_id != intent.producer_id
            or result.producer_fingerprint != intent.producer_fingerprint
            or result.producer_run_id != intent.run_id or result.contract_sha256 != intent.contract_sha256
            or type(result.budget.get("requests")) is not int
            or result.budget["requests"] != receipt.request_count
            or receipt.envelope_evidence is None
            or output.envelope_bytes_sha256 != receipt.envelope_evidence.sha256):
        raise ValueError
    acquired = native_output._native_output_envelope_pin(output)
    if acquired is not None and receipt.envelope_evidence.bytes != len(acquired[2]):
        raise ValueError
    plan = output.admission_plan.from_dict(output.admission_plan.to_dict())
    if any(getattr(plan, name) != getattr(intent, name) for name in (
        "contract_sha256", "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint",
        "dependency_sha256", "environment_sha256",
    )):
        raise ValueError
    return {
        "schema_version": "1", "protocol": PROTOCOL, "status": "incomplete",
        **identity, "producer_id": intent.producer_id,
        "intent_sha256": intent.intent_sha256, "attestation_sha256": attestation.attestation_sha256,
        "installation_sha256": request.expected_installation_sha256,
        "startup_observation": json.loads(observed.canonical_bytes),
        "startup_observation_sha256": observed.observation_sha256,
        "process_terminal_sha256": attempt.terminal_sha256,
        "execution_receipt_sha256": receipt.receipt_sha256,
        "broker_journal_sha256": broker.journal_sha256,
        "broker_journal_identity": broker.journal_identity.to_dict(),
        "envelope_sha256": result.envelope_sha256,
        "envelope_bytes_sha256": output.envelope_bytes_sha256,
        "admission_plan_sha256": plan.digest(),
        "captured_envelope_semantic_join_verified": acquired is not None,
        "missing_evidence": [name for name in MISSING_EVIDENCE
                             if acquired is None or name != "original_captured_envelope_semantic_join"],
        "live_runtime_authenticated": False, "immutable_custody_verified": False,
        "production_admission": False, "online_publication": False,
    }


def _compare(run, intent, attestation, request, request_pin):
    if (type(run) is not native.NativeTrustedProducerRun
            or type(intent) is not launcher.ProducerLaunchIntent
            or type(attestation) is not launcher.ProducerLaunchAttestation
            or type(request) is not sink.FixedPythonLiveSinkRequest
            or request.source_profile != FIXED_LIVE_RUNTIME_SINK_PROFILE):
        raise ValueError
    native_pin = native._native_handoff_evidence(run, request_pin)
    observed = run.attempt.live_modules_observation
    facts = runtime.validate_fixed_python_runtime_observation_policy(
        request.installation, observed, image=request.image,
        runtime_main_source=request.runtime_main_source,
        expected_installation_sha256=request.expected_installation_sha256,
        expected_observation_sha256=observed.observation_sha256,
    )
    report = _join(run, intent, attestation, request, facts)
    report["evidence_sha256"] = _sha(report)
    return native_pin, facts, _canonical(report)


def _original_objects(run, intent, attestation, request, facts, wire) -> tuple:
    return (run, intent, attestation, request, facts, wire, run.attempt, run.receipt, run.output,
            run.attempt.live_modules_observation, run.attempt.broker_observation)


@dataclass(frozen=True, slots=True, repr=False)
class FixedPythonProducerEvidence:
    """Retained original comparison inputs; exported bytes never reconstruct authority."""

    run: native.NativeTrustedProducerRun
    intent: launcher.ProducerLaunchIntent
    attestation: launcher.ProducerLaunchAttestation
    request: sink.FixedPythonLiveSinkRequest
    facts: runtime.FixedPythonRuntimeFacts
    _request_pin: sink._FixedPythonLiveSinkPin
    _native_pin: tuple
    _implementation: tuple
    _originals: tuple
    _wire: bytes

    def to_json(self) -> bytes:
        """Revalidate current original inputs before exporting a bounded inspection."""
        return _validated_wire(self)

    def to_dict(self) -> dict:
        return json.loads(_validated_wire(self))


def _validated_wire(value: FixedPythonProducerEvidence) -> bytes:
    try:
        if (type(value) is not FixedPythonProducerEvidence
                or type(value._originals) is not tuple or len(value._originals) != 12
                or value._originals[0] is not value
                or any(current is not original for current, original in zip(
                    _original_objects(value.run, value.intent, value.attestation,
                                      value.request, value.facts, value._wire),
                    value._originals[1:], strict=True))
                or _implementation_pin() != value._implementation):
            raise ValueError
        pin, facts, wire = _compare(value.run, value.intent, value.attestation, value.request, value._request_pin)
        if pin != value._native_pin or facts != value.facts or wire != value._wire:
            raise ValueError
        if _implementation_pin() != value._implementation:
            raise ValueError
        return wire
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, UnicodeError,
            OverflowError, RecursionError):
        raise FixedPythonProducerEvidenceError() from None


def compose_fixed_python_producer_evidence(
    run: native.NativeTrustedProducerRun, *, intent: launcher.ProducerLaunchIntent,
    attestation: launcher.ProducerLaunchAttestation, request: sink.FixedPythonLiveSinkRequest,
) -> FixedPythonProducerEvidence:
    """Inspect explicitly supplied original native objects without product I/O or process effects.

    Same-value replacement after composition is drift. The optional private
    preparation acquisition joins its original bounded read to the parsed DTO;
    supplied DTOs alone do not. This never accepts a runtime, observes completed
    computation/pycache or admits a candidate.
    """
    try:
        implementation = _implementation_pin()
        if type(intent) is not launcher.ProducerLaunchIntent:
            raise ValueError
        request_pin = sink._pin_fixed_python_live_sink_request(request, target_sha256=intent.executable_sha256)
        native_pin, facts, wire = _compare(run, intent, attestation, request, request_pin)
        result = FixedPythonProducerEvidence(
            run, intent, attestation, request, facts, request_pin, native_pin, implementation,
            (), wire,
        )
        object.__setattr__(result, "_originals", (result, *_original_objects(run, intent, attestation, request, facts, wire)))
        _validated_wire(result)
        return result
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, UnicodeError,
            OverflowError, RecursionError):
        raise FixedPythonProducerEvidenceError() from None


def _source_result(evidence: FixedPythonProducerEvidence, source_root: str | Path, result_path: str,
                   top_k: int | None, program_ids: tuple[str, ...] | None) -> ProducerResultEnvelope:
    original = evidence.run.output.envelope
    if original.producer_id == "openevolve":
        if top_k is not None or program_ids is not None or len(original.materials) != 1:
            raise ValueError
        _, path, source, present, score_present, evaluation_sha256 = openevolve._read_openevolve_snapshot(
            source_root, result_path,
        )
        materials = (ProducerMaterial(
            kind="candidate_source", path=path, size=len(source), sha256=hashlib.sha256(source).hexdigest(),
            lineage=original.materials[0].lineage,
            external_evidence={"present": present, "score_present": score_present,
                               "payload_sha256": evaluation_sha256},
        ),)
    else:
        if (result_path != "result.json" or (top_k is not None and
                (type(top_k) is not int or not 1 <= top_k <= shinka.MAX_SHINKA_TOP_K))
                or (program_ids is not None and (type(program_ids) is not tuple
                    or not 1 <= len(program_ids) <= shinka.MAX_SHINKA_TOP_K
                    or any(type(item) is not str for item in program_ids)))):
            raise ValueError
        root = shinka._root(source_root, shinka.SHINKA_ROOT_UNSAFE)
        prepared = shinka._read_shinka_snapshot(root, top_k, program_ids)
        selected = []
        for row, lineage, source, path in prepared:
            external = {"correct": row.correct, "generation": row.generation, "program_id": row.program_id}
            if row.combined_score is not None:
                external["combined_score"] = row.combined_score
            selected.append(ProducerMaterial(
                kind="candidate_source", path=path, size=len(source),
                sha256=hashlib.sha256(source).hexdigest(), lineage=lineage, external_evidence=external,
            ))
        materials = tuple(selected)
    return ProducerResultEnvelope(
        schema_version="1", producer_id=original.producer_id,
        producer_fingerprint=original.producer_fingerprint, producer_run_id=original.producer_run_id,
        status="completed", contract_sha256=original.contract_sha256, budget=dict(original.budget),
        materials=materials,
    )


def read_fixed_python_producer_evidence_export(
    evidence: FixedPythonProducerEvidence, source_root: str | Path, *, result_path: str = "result.json",
    top_k: int | None = None, program_ids: tuple[str, ...] | None = None,
) -> bytes:
    """Read an explicit producer snapshot and compare its materials before export.

    No writes, evaluation or admission occur. Missing lifecycle/acceptance fields
    remain missing even when source materials match the retained native result.
    """
    try:
        if (type(evidence) is not FixedPythonProducerEvidence
                or _implementation_pin() != evidence._implementation):
            raise ValueError
        original = _validated_wire(evidence)
        imported = _source_result(evidence, source_root, result_path, top_k, program_ids)
        if (_canonical(imported.to_dict()) != _canonical(evidence.run.output.envelope.to_dict())
                or _validated_wire(evidence) != original):
            raise ValueError
        return original
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, UnicodeError,
            OverflowError, RecursionError, OSError):
        raise FixedPythonProducerEvidenceError() from None
