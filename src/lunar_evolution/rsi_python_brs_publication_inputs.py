"""Project retained producer preparation into non-authorizing mailbox evidence.

No file, ledger, recovery or transaction operation occurs here. The original owner
must independently reread durable execution/output/handoff and validate its live
scope; worker-held drafts and bundles never become transaction inputs here.
"""

from __future__ import annotations

from dataclasses import fields

from .candidate_evaluation_spec import canonical_json, strict_json
from .native_trusted_output import NativeTrustedOutputPreparation
from .native_trusted_scheduler import (
    NativeTrustedProducerRun,
    _NativeTrustedPythonProducerPreparation,
)
from .producer_bundle_admission import (
    MAX_PRODUCER_BUNDLE_ADMISSION_BYTES,
    ProducerBundleAdmissionItem,
    ProducerBundleAdmissionPlan,
    parse_producer_bundle_admission_plan,
)
from .producer_handoff import (
    MAX_PRODUCER_ENVELOPE_BYTES,
    ProducerHandoffError,
    ProducerMaterial,
    ProducerResultEnvelope,
    parse_producer_envelope,
)
from .producer_process import (
    _MAX_RECEIPT_BYTES,
    ProducerEnvelopeEvidence,
    ProducerExecutionReceipt,
    ProducerStreamEvidence,
    parse_producer_execution_receipt,
)
from .python_producer_admission_handoff import (
    PythonProducerAdmissionHandoff,
    PythonProducerAdmissionHandoffFilePin,
    PythonProducerAdmissionHandoffSidecar,
    parse_python_producer_admission_handoff,
    parse_python_producer_admission_handoff_file_pin,
)
from .rsi_gateway import SolverRequest
from .rsi_learning import RSILearningError
from .rsi_native_plan import _MAX_BYTES as _MAX_NATIVE_PLAN_BYTES
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_python_admission import validate_rsi_python_admission_shapes
from .rsi_python_brs_handoff import BRSSelectedChildHandoff
from .rsi_python_brs_publication_mailbox import (
    MAX_BRS_PUBLICATION_MESSAGE_BYTES,
    BRSOwnerPublicationRequest,
    build_brs_owner_publication_request,
)


def _fail(code: str) -> None:
    raise RSILearningError("rsi_python_brs_publication_inputs_" + code)


def _detached(value: object, maximum: int) -> object:
    return strict_json(canonical_json(value, maximum=maximum), maximum=maximum)


def _request_from_native_preparation(
    preparation: _NativeTrustedPythonProducerPreparation,
    handoff: BRSSelectedChildHandoff,
    *,
    native_plan: NativeRSIExecutionPlan,
    expected_head_sha256: str,
    expected_state_sha256: str,
) -> BRSOwnerPublicationRequest:
    """Copy exact retained evidence, without granting or refreshing authority."""
    if (type(preparation) is not _NativeTrustedPythonProducerPreparation
            or type(handoff) is not BRSSelectedChildHandoff
            or type(native_plan) is not NativeRSIExecutionPlan):
        _fail("shape_invalid")
    run, supplied = preparation.run, preparation.handoff
    if type(run) is not NativeTrustedProducerRun or type(supplied) is not PythonProducerAdmissionHandoffSidecar:
        _fail("shape_invalid")
    receipt, output = run.receipt, run.output
    if (type(receipt) is not ProducerExecutionReceipt or type(output) is not NativeTrustedOutputPreparation
            or type(output.admission_plan) is not ProducerBundleAdmissionPlan
            or type(output.envelope) is not ProducerResultEnvelope
            or type(supplied.handoff) is not PythonProducerAdmissionHandoff
            or type(supplied.file_pin) is not PythonProducerAdmissionHandoffFilePin):
        _fail("shape_invalid")
    # Validate every consumed field before serializers, equality or digest methods.
    # Unused attempt/draft/bundle objects are deliberately not traversed or invoked.
    run_state = (run.status, run.publication, run.deadline_scope)
    output_values = {name: getattr(output, name) for name in (
        "process_terminal_sha256", "output_capture_sha256", "envelope_bytes_sha256",
        "execution_receipt_sha256", "request_coverage", "publication_eligible",
    )}
    admission_plan, result_envelope = output.admission_plan, output.envelope
    consumed = (
        run_state, receipt, admission_plan, result_envelope, output_values,
        supplied, handoff, native_plan, expected_head_sha256, expected_state_sha256,
    )
    try:
        # Check this before dataclasses.fields(instance) in the recursive shape
        # reader: a non-slotted request can also shadow __dataclass_fields__.
        if type(native_plan.request) is not SolverRequest:
            _fail("shape_invalid")
        attributes = object.__getattribute__(native_plan.request, "__dict__")
        if (type(attributes) is not dict or any(type(key) is not str for key in attributes)
                or set(attributes) != {field.name for field in fields(SolverRequest)}):
            _fail("shape_invalid")
        validate_rsi_python_admission_shapes(consumed, dto_types=(
            ProducerExecutionReceipt, ProducerStreamEvidence, ProducerEnvelopeEvidence,
            ProducerBundleAdmissionPlan, ProducerBundleAdmissionItem,
            ProducerResultEnvelope, ProducerMaterial, PythonProducerAdmissionHandoff,
            PythonProducerAdmissionHandoffFilePin, PythonProducerAdmissionHandoffSidecar,
            BRSSelectedChildHandoff, NativeRSIExecutionPlan, SolverRequest,
        ))
        parsed_receipt = parse_producer_execution_receipt(_detached(
            ProducerExecutionReceipt.to_dict(receipt), _MAX_RECEIPT_BYTES,
        ))
        plan = NativeRSIExecutionPlan.from_dict(_detached(
            NativeRSIExecutionPlan.to_dict(native_plan), _MAX_NATIVE_PLAN_BYTES,
        ))
        admission = parse_producer_bundle_admission_plan(_detached(
            ProducerBundleAdmissionPlan.to_dict(admission_plan), MAX_PRODUCER_BUNDLE_ADMISSION_BYTES,
        ))
        selected = BRSSelectedChildHandoff(**BRSSelectedChildHandoff.to_dict(handoff))
        sidecar = PythonProducerAdmissionHandoffSidecar(
            parse_python_producer_admission_handoff(PythonProducerAdmissionHandoff.to_dict(supplied.handoff)),
            parse_python_producer_admission_handoff_file_pin(
                PythonProducerAdmissionHandoffFilePin.to_dict(supplied.file_pin),
            ),
        )
        envelope = parse_producer_envelope(_detached(
            ProducerResultEnvelope.to_dict(result_envelope), MAX_PRODUCER_ENVELOPE_BYTES,
        ))
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError, ProducerHandoffError) as exc:
        raise RSILearningError("rsi_python_brs_publication_inputs_evidence_invalid") from exc
    retained = sidecar.handoff
    if (run_state[0] != "prepared" or run_state[1] is not None
            or type(run_state[2]) is not str or run_state[2] not in {"native_attempt_only", "caller_lifecycle"}
            or parsed_receipt.status != "completed" or type(parsed_receipt.exit_code) is not int
            or parsed_receipt.exit_code != 0 or type(parsed_receipt.request_count) is not int
            or parsed_receipt.gate_released is not True
            or type(parsed_receipt.cleanup_status) is not str
            or parsed_receipt.cleanup_status not in {"cleaned", "already_exited"}
            or output_values["publication_eligible"] is not True
            or output_values["request_coverage"] != "brokered_requests_only" or retained.state != "prepared"
            or envelope.status != "completed"):
        _fail("state_invalid")
    if ((plan.run_id, plan.request.episode_id, plan.request_sha256, plan.memory_snapshot_sha256)
            != (selected.run_id, selected.episode_id, selected.request_sha256, selected.root_snapshot_sha256)):
        _fail("selection_mismatch")
    for name in ("run_id", "journal_id", "parent_task_id", "task_id"):
        if getattr(plan, name) != getattr(parsed_receipt, name) or getattr(plan, name) != getattr(retained, name):
            _fail("launch_mismatch")
    if (plan.launch_id != parsed_receipt.launch_id
            or plan.intent_sha256 != parsed_receipt.intent_sha256
            or plan.intent_sha256 != retained.launch_intent_sha256
            or plan.attestation_sha256 != parsed_receipt.attestation_sha256
            or plan.attestation_sha256 != retained.attestation_sha256):
        _fail("launch_mismatch")
    if (parsed_receipt.receipt_sha256 != output_values["execution_receipt_sha256"]
            or parsed_receipt.receipt_sha256 != retained.native_execution_receipt_sha256
            or admission.digest() != retained.admission_plan_sha256
            or plan.request.contract_sha256 != admission.contract_sha256
            or envelope.contract_sha256 != admission.contract_sha256
            or retained.contract_sha256 != admission.contract_sha256
            or retained.envelope_sha256 != envelope.envelope_sha256
            or plan.evaluator_kind != admission.evaluator_kind
            or plan.evaluator_fingerprint != admission.evaluator_fingerprint
            or plan.request.evaluator_sha256 != admission.evaluator_fingerprint
            or retained.evaluator_sha256 != admission.evaluator_fingerprint
            or plan.request.environment_sha256 != admission.environment_sha256
            or any(getattr(retained, field) != getattr(admission, other) for field, other in (
                ("runner_sha256", "runner_fingerprint"), ("dependency_sha256", "dependency_sha256"),
                ("environment_sha256", "environment_sha256"),
            ))):
        _fail("output_mismatch")
    trusted = parsed_receipt.trusted_execution
    if (type(trusted) is not dict or trusted.get("broker_coverage") != "brokered_requests_only"
            or trusted.get("terminal_sha256") != output_values["process_terminal_sha256"]
            or trusted.get("output_capture_sha256") != output_values["output_capture_sha256"]
            or parsed_receipt.envelope_evidence is None
            or parsed_receipt.envelope_evidence.sha256 != output_values["envelope_bytes_sha256"]
            or type(envelope.budget.get("requests")) is not int
            or envelope.budget["requests"] != parsed_receipt.request_count):
        _fail("capture_mismatch")
    payload = {
        "native_plan_sha256": plan.plan_sha256,
        "expected_head_sha256": expected_head_sha256,
        "expected_state_sha256": expected_state_sha256,
        "native_execution_receipt_sha256": parsed_receipt.receipt_sha256,
        "output": {
            "process_terminal_sha256": output_values["process_terminal_sha256"],
            "output_capture_sha256": output_values["output_capture_sha256"],
            "envelope_bytes_sha256": output_values["envelope_bytes_sha256"],
            "execution_receipt_sha256": parsed_receipt.receipt_sha256,
            "admission_plan_sha256": admission.digest(),
            "request_coverage": output_values["request_coverage"],
        },
        "python_handoff_file_pin": sidecar.file_pin.to_dict(),
    }
    return build_brs_owner_publication_request(
        selected, canonical_json(payload, maximum=MAX_BRS_PUBLICATION_MESSAGE_BYTES),
    )
