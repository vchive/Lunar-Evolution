"""Scheduler-backed provider for the native RSI solver gateway.

The native gateway owns the durable episode claim and replay gate, while this module owns the
one-shot native launch.  Keeping the launch context explicit makes it possible to check every
identity again immediately before dispatch and prevents a caller from accidentally combining a
request with retained evidence from another producer batch.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from . import native_trusted_scheduler as _native_scheduler
from ._candidate_workspace_io import DirectoryChain
from .algorithm import AlgorithmProblemContract, EvaluationReport
from .automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from .bundle_evolution import derive_native_draft_run_id
from .candidate_evaluation_spec import canonical_json
from .native_bootstrap import NativeBootstrapArtifact
from .native_fixed_live_sink import (
    FixedPythonLiveSinkRequest,
    NativeFixedLiveSinkError,
    _FixedPythonLiveSinkPin,
    _pin_fixed_python_live_sink_request,
)
from .native_pycache_diagnostic import NativePycacheDiagnosticRequest
from .native_trusted_failure import NativeTrustedProducerFailure, recover_native_trusted_failure
from .native_trusted_output import NativeTrustedOutputPreparation, _native_output_envelope_pin
from .native_trusted_scheduler import (
    NativeTrustedProducerRecovery,
    NativeTrustedProducerRun,
    NativeTrustedSchedulerError,
    _native_handoff_evidence,
    _native_scope_deadline,
    _native_scope_profile_snapshot,
    _NativeSchedulerScopePin,
    _pin_native_scheduler_scope,
    _prepublication_evidence,
    _run_native_trusted_producer,
    recover_native_trusted_producer,
    run_native_trusted_producer,
    run_native_trusted_producer_outcome,
)
from .native_whole_scope import NativeWholeScopeOwner
from .official_evaluator_evidence import OfficialEvaluationReceipt, OfficialEvaluatorProfile
from .producer_broker_ipc import ProducerBrokerConfig
from .producer_bundle_handoff import BundleGroup
from .producer_bundle_intent import (
    verify_producer_bundle_prepared_intent,
    verify_producer_bundle_python_handoff_anchor,
)
from .producer_bundle_lineage_v2 import ProducerLineageRejectedTerminalV2
from .producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    ProducerBundlePublicationJournal,
    parse_producer_bundle_publication_journal,
)
from .producer_bundle_rejection import (
    VerifiedProducerBundleRejection,
    _verify_terminal_batch_rejection_evidence,
)
from .producer_bundle_transaction import NativeProducerBundleTransactionResult
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import ProducerExecutionReceipt
from .python_producer_admission_anchor import (
    project_python_producer_admission_attempt_anchor,
    read_python_producer_admission_attempt_anchor,
)
from .python_producer_admission_handoff import (
    PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME,
    PythonProducerAdmissionHandoffFilePin,
    PythonProducerAdmissionHandoffSidecar,
    parse_python_producer_admission_handoff_file_pin,
    read_python_producer_admission_handoff_pinned,
)
from .rsi_gateway import SolverRequest
from .rsi_identity import RSIIdentityError, component_fingerprint
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_candidate import (
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
    select_native_candidate,
)
from .rsi_native_failure import (
    NATIVE_RSI_FAILURE_PROVENANCE_NAME,
    NativeRSIFailureEvidence,
    persist_native_rsi_failure_provenance,
    read_native_rsi_failure_provenance,
)
from .rsi_native_gateway import NativeRSIReceiptBundle
from .rsi_native_inputs import (
    NativeRSIInputDescriptor,
    validate_native_rsi_launch_inputs,
)
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_native_provenance import (
    NATIVE_RSI_PROVENANCE_NAME,
    persist_native_rsi_provenance,
    read_native_rsi_provenance,
)
from .rsi_native_rejection import (
    NATIVE_RSI_REJECTION_PROVENANCE_NAME,
    NativeRSIRejectionEvidence,
    NativeRSIRejectionFilePin,
    RejectionLineageC1Binding,
    persist_native_rsi_rejection_provenance,
    read_native_rsi_rejection_provenance,
)
from .rsi_native_retained import NativeRetainedCandidateEvidence, read_native_retained_candidate
from .rsi_python_admission_bridge import (
    PythonAdmissionBridgeAdapter,
    build_python_admission_bridge_descriptor,
)
from .rsi_store import NativeEpisodeClaim, RSILedger


class NativeRSISchedulerProviderError(RSILearningError):
    """Fixed refusal codes for scheduler-backed native RSI composition."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise NativeRSISchedulerProviderError("rsi_native_scheduler_" + code)


def _sha(value: object, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail(f"{field}_invalid")
    return value


def _strategy_fingerprint(strategy: object) -> str:
    """Fingerprint publication strategy without hashing process-local archive state."""
    try:
        return component_fingerprint(strategy)
    except RSIIdentityError as exc:
        config = getattr(strategy, "config", None)
        to_dict = getattr(config, "to_dict", None)
        if not callable(to_dict):
            raise NativeRSISchedulerProviderError(
                "rsi_native_scheduler_strategy_fingerprint_invalid",
            ) from exc
        try:
            return component_fingerprint(type(strategy), config={"config": to_dict()})
        except RSIIdentityError as config_exc:
            raise NativeRSISchedulerProviderError(
                "rsi_native_scheduler_strategy_fingerprint_invalid",
            ) from config_exc


@dataclass(frozen=True, slots=True)
class NativeRSISchedulerContext:
    """All caller-owned launch dependencies for one native RSI request.

    Optional installed scope and diagnostic objects are borrowed originals. The
    context never creates, closes or reconstructs them. The provider validates
    retained launch files and plan identities before consuming an attestation.
    """

    workspace: str | Path
    producer_root: str | Path
    intent: ProducerLaunchIntent
    attestation: ProducerLaunchAttestation
    artifact: NativeBootstrapArtifact
    broker_config: ProducerBrokerConfig
    contract: AlgorithmProblemContract
    groups: tuple[BundleGroup, ...]
    evaluator_kind: str
    evaluator_fingerprint: str
    runner_fingerprint: str
    dependency_sha256: str
    environment_sha256: str
    strategy: Any
    execution_control: SolveExecutionControl | None = None
    cancelled: Callable[[], bool] | None = None
    failure_ledger: RSILedger | None = None
    python_handoff_after_execution: Callable[
        [ProducerExecutionReceipt, NativeTrustedOutputPreparation], PythonProducerAdmissionHandoffSidecar,
    ] | None = None
    live_modules_sink: FixedPythonLiveSinkRequest | None = None
    python_handoff_after_native_execution: Callable[
        [NativeTrustedProducerRun], PythonProducerAdmissionHandoffSidecar,
    ] | None = None
    whole_scope: NativeWholeScopeOwner | None = None
    pycache_diagnostic: NativePycacheDiagnosticRequest | None = None
    _live_modules_sink_pin: _FixedPythonLiveSinkPin | None = dataclass_field(init=False, repr=False, compare=False)
    _native_scope_pin: _NativeSchedulerScopePin | None = dataclass_field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        NativeRSISchedulerContext._python_handoff_suppliers(self)
        if not isinstance(self.intent, ProducerLaunchIntent):
            _fail("intent_invalid")
        if not isinstance(self.attestation, ProducerLaunchAttestation):
            _fail("attestation_invalid")
        if not isinstance(self.artifact, NativeBootstrapArtifact):
            _fail("artifact_invalid")
        if not isinstance(self.broker_config, ProducerBrokerConfig):
            _fail("broker_invalid")
        if not isinstance(self.contract, AlgorithmProblemContract):
            _fail("contract_invalid")
        if isinstance(self.groups, (str, bytes)) or not isinstance(self.groups, Sequence):
            _fail("groups_invalid")
        try:
            groups = tuple(self.groups)
        except (TypeError, RecursionError) as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_groups_invalid") from exc
        if not groups or any(not isinstance(group, BundleGroup) for group in groups):
            _fail("groups_invalid")
        object.__setattr__(self, "groups", groups)
        if type(self.evaluator_kind) is not str or not self.evaluator_kind.strip():
            _fail("evaluator_kind_invalid")
        for value, field in (
            (self.evaluator_fingerprint, "evaluator_fingerprint"),
            (self.dependency_sha256, "dependency"),
            (self.environment_sha256, "environment"),
        ):
            _sha(value, field)
        if self.strategy is None:
            _fail("strategy_missing")
        if self.execution_control is not None and not isinstance(self.execution_control, SolveExecutionControl):
            _fail("control_invalid")
        if self.cancelled is not None and not callable(self.cancelled):
            _fail("cancellation_invalid")
        if self.failure_ledger is not None and not isinstance(self.failure_ledger, RSILedger):
            _fail("failure_ledger_invalid")
        if hasattr(self, "_native_scope_pin"):
            NativeRSISchedulerContext._native_scope_options(self)
        else:
            try:
                scope_pin = _pin_native_scheduler_scope(
                    self.whole_scope, self.pycache_diagnostic,
                    intent=self.intent, artifact=self.artifact,
                )
            except NativeTrustedSchedulerError as exc:
                raise NativeRSISchedulerProviderError("rsi_native_scheduler_native_scope_invalid") from exc
            object.__setattr__(self, "_native_scope_pin", scope_pin)
        # A repeated validation must never refresh the original request pin.
        if hasattr(self, "_live_modules_sink_pin"):
            NativeRSISchedulerContext._assert_live_modules_sink(self)
        else:
            try:
                pin = (None if self.live_modules_sink is None else _pin_fixed_python_live_sink_request(
                    self.live_modules_sink, target_sha256=self.intent.executable_sha256,
                ))
            except NativeFixedLiveSinkError as exc:
                raise NativeRSISchedulerProviderError("rsi_native_scheduler_live_modules_sink_invalid") from exc
            object.__setattr__(self, "_live_modules_sink_pin", pin)

    def _python_handoff_suppliers(self) -> tuple:
        legacy = getattr(self, "python_handoff_after_execution", None)
        native = getattr(self, "python_handoff_after_native_execution", None)
        if legacy is not None and native is not None:
            _fail("python_handoff_supplier_conflict")
        if any(value is not None and (not callable(value) or self.strategy is None)
               for value in (legacy, native)):
            _fail("python_handoff_supplier_invalid")
        if native is not None and self.live_modules_sink is None:
            _fail("python_native_sink_required")
        return legacy, native

    def _assert_live_modules_sink(self) -> FixedPythonLiveSinkRequest | None:
        NativeRSISchedulerContext._native_scope_options(self)
        pin = self._live_modules_sink_pin
        if pin is None:
            if self.live_modules_sink is not None:
                _fail("live_modules_sink_changed")
        else:
            try:
                _FixedPythonLiveSinkPin.assert_current(
                    pin, self.live_modules_sink, target_sha256=self.intent.executable_sha256,
                )
            except (NativeFixedLiveSinkError, AttributeError, TypeError, ValueError) as exc:
                raise NativeRSISchedulerProviderError("rsi_native_scheduler_live_modules_sink_changed") from exc
        return self.live_modules_sink

    def _native_scope_options(self, *, require_unexpired=False) -> dict[str, Any]:
        """Borrow the exact original selections; never refresh their pins."""
        pin = getattr(self, "_native_scope_pin", None)
        scope = getattr(self, "whole_scope", None)
        diagnostic = getattr(self, "pycache_diagnostic", None)
        try:
            if pin is None:
                if scope is not None or diagnostic is not None:
                    raise ValueError
                return {}
            if (type(pin) is not _NativeSchedulerScopePin or pin.whole_scope is not scope
                    or pin.pycache_diagnostic is not diagnostic):
                raise ValueError
            return pin.options(self.intent, self.artifact, require_unexpired=require_unexpired)
        except (NativeTrustedSchedulerError, ValueError, AttributeError, TypeError) as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_native_scope_changed") from exc

    def _native_scope_projection(self) -> dict[str, Any] | None:
        if not NativeRSISchedulerContext._native_scope_options(self):
            return None
        pin = self._native_scope_pin
        projection = {"protocol": "lunar-native-rsi-original-scope-input-v1"}
        if pin.whole_scope is not None:
            profile, _raw, journal, deadline = pin.scope_fields
            projection["whole_scope"] = {
                "profile_sha256": profile, "journal_id": journal,
                "original_deadline_upper_bound_ns": deadline,
            }
        if pin.pycache_diagnostic is not None:
            observer, profile, working, output = pin.diagnostic_fields
            projection["pycache_diagnostic"] = {
                "observer_sha256": component_fingerprint(observer), "profile": profile,
                "working_directories": list(working), "output_directories": list(output),
            }
        projection["code_dependencies"] = {
            "pin": component_fingerprint(_NativeSchedulerScopePin),
            "pin_scope": component_fingerprint(_pin_native_scheduler_scope),
            "deadline_guard": component_fingerprint(_native_scope_deadline),
            "profile_snapshot": component_fingerprint(_native_scope_profile_snapshot),
            "context_options": component_fingerprint(NativeRSISchedulerContext._native_scope_options),
        }
        return projection

    def _live_modules_sink_projection(self) -> dict[str, Any] | None:
        if NativeRSISchedulerContext._assert_live_modules_sink(self) is None:
            return None
        projection = _FixedPythonLiveSinkPin.to_dict(self._live_modules_sink_pin)
        projection["code_dependencies"] = {
            "request": component_fingerprint(FixedPythonLiveSinkRequest),
            "pin": component_fingerprint(_FixedPythonLiveSinkPin),
            "pin_request": component_fingerprint(_pin_fixed_python_live_sink_request),
            "assert_context": component_fingerprint(NativeRSISchedulerContext._assert_live_modules_sink),
            "context_projection": component_fingerprint(NativeRSISchedulerContext._live_modules_sink_projection),
        }
        return projection


def _assert_plan_binding(
    request: SolverRequest,
    memory: MemorySnapshot,
    plan: NativeRSIExecutionPlan,
    context: NativeRSISchedulerContext,
    inputs: NativeRSIInputDescriptor,
) -> None:
    """Check every plan and retained input identity before scheduler dispatch."""
    try:
        plan.assert_request_memory(request, memory)
    except Exception as exc:
        raise NativeRSISchedulerProviderError("rsi_native_scheduler_plan_input_mismatch") from exc
    expected = {
        "request_sha256": request.digest(),
        "memory_snapshot_sha256": memory.digest(),
        "journal_id": context.intent.journal_id,
        "launch_id": context.intent.launch_id,
        "run_id": context.intent.run_id,
        "parent_task_id": context.intent.parent_task_id,
        "task_id": context.intent.task_id,
        "intent_sha256": context.intent.digest(),
        "attestation_sha256": context.attestation.digest(),
        "bootstrap_descriptor_sha256": context.artifact.descriptor.digest(),
        "bootstrap_artifact_sha256": context.artifact.artifact_sha256,
        "manifest_sha256": inputs.manifest_sha256,
        "request_relative_path": "../.rsi-input/request.json",
        "memory_relative_path": "../.rsi-input/memory.json",
        "evaluator_kind": context.evaluator_kind,
        "evaluator_fingerprint": context.evaluator_fingerprint,
    }
    for field, value in expected.items():
        if getattr(plan, field) != value:
            _fail(f"plan_{field}_mismatch")
    if plan.deadline_unix != inputs.deadline_unix:
        _fail("plan_deadline_mismatch")
    if isinstance(plan, NativeRSIExecutionPlan) and (
        plan.candidate_selector_id != "native-selector-v1"
        or plan.candidate_selector_sha256 != component_fingerprint(select_native_candidate)
    ):
        _fail("plan_candidate_selector_mismatch")
    if request.contract_sha256 != context.contract.digest():
        _fail("contract_mismatch")
    if request.evaluator_sha256 != context.evaluator_fingerprint:
        _fail("evaluator_mismatch")
    if request.environment_sha256 != context.environment_sha256:
        _fail("environment_mismatch")
    if context.intent.contract_sha256 != request.contract_sha256:
        _fail("intent_contract_mismatch")
    if context.intent.evaluator_fingerprint != request.evaluator_sha256:
        _fail("intent_evaluator_mismatch")
    if context.intent.environment_sha256 != request.environment_sha256:
        _fail("intent_environment_mismatch")
    if (context.intent.evaluator_kind != context.evaluator_kind
            or context.intent.runner_fingerprint != context.runner_fingerprint
            or context.intent.dependency_sha256 != context.dependency_sha256):
        _fail("intent_runtime_mismatch")
    if inputs.request != request or inputs.memory != memory:
        _fail("input_drift")


def _journal_for_published_run(run: NativeTrustedProducerRun):
    publication = run.publication
    if publication is None or run.status != "published" or publication.publication_status != "published":
        _fail("publication_incomplete")
    journal = publication.terminal_journal or publication.published_journal
    if journal is None or journal.state != "published":
        _fail("publication_journal_missing")
    return publication, journal


def _official_evaluator_receipt(request: SolverRequest, source: str, execution: str, publication: str, evaluation: str) -> OfficialEvaluationReceipt:
    return OfficialEvaluationReceipt(
        OfficialEvaluatorProfile(
            "native-local-evaluator", "1", request.evaluator_sha256,
            hashlib.sha256(b"native-local-evaluator-config-v1").hexdigest(),
            request.contract_sha256, hashlib.sha256(request.digest().encode()).hexdigest(),
            hashlib.sha256(b"native-local-holdout-v1").hexdigest(), hashlib.sha256(b"native-local-seed-v1").hexdigest(),
        ), request.digest(), source, execution, publication, "pass", evaluation,
    )


def _build_receipts(
    request: SolverRequest,
    context: NativeRSISchedulerContext,
    run: NativeTrustedProducerRun,
) -> NativeRSIReceiptBundle:
    publication, journal = _journal_for_published_run(run)
    if (
        journal.journal_id != context.intent.journal_id
        or journal.run_id != context.intent.run_id
        or journal.parent_task_id != context.intent.parent_task_id
        or journal.task_id != context.intent.task_id
        or journal.contract_sha256 != request.contract_sha256
        or journal.evaluator_fingerprint != request.evaluator_sha256
        or journal.runner_fingerprint != context.runner_fingerprint
        or journal.dependency_sha256 != context.dependency_sha256
        or journal.environment_sha256 != request.environment_sha256
        or journal.native_execution_receipt_sha256 != run.receipt.receipt_sha256
    ):
        _fail("publication_binding_mismatch")
    if tuple(publication.admitted_candidate_ids) != tuple(
        item.candidate_id for item in journal.candidates if item.status == "admitted"
    ) or len(publication.admitted_candidate_ids) != 1:
        _fail("candidate_selection_invalid")
    candidate_id = publication.admitted_candidate_ids[0]
    entries = [item for item in journal.candidates if item.candidate_id == candidate_id]
    if len(entries) != 1:
        _fail("candidate_missing")
    entry = entries[0]
    if entry.status != "admitted" or any(
        value is None for value in (
            entry.preparation_receipt_sha256,
            entry.execution_receipt_sha256,
            entry.evaluation_receipt_sha256,
            entry.publication_receipt_sha256,
        )
    ):
        _fail("candidate_receipts_missing")
    evaluations = [item for item in publication.evaluations if item.candidate_id == candidate_id]
    if len(evaluations) != 1:
        _fail("evaluation_missing")
    evaluated = evaluations[0]
    if (
        getattr(evaluated, "journal_id", None) != journal.journal_id
        or getattr(evaluated, "run_id", None) != derive_native_draft_run_id(
            journal.journal_id, candidate_id, entry.bundle_sha256,
        )
        or getattr(evaluated, "journal_sha256", None) != publication.journal.digest()
    ):
        _fail("evaluation_binding_mismatch")
    report = getattr(evaluated.evaluation, "report", None)
    if isinstance(report, EvaluationReport):
        report = report.to_dict()
    if not isinstance(report, dict) or report.get("validity") != 1:
        _fail("evaluation_not_valid")
    # The execution evidence digest is computed from the retained execution record itself.  It
    # does not trust a producer score or a journal field that is not tied to the current attempt.
    try:
        execution_evidence = evaluated.execution.to_dict()
    except Exception as exc:
        raise NativeRSISchedulerProviderError("rsi_native_scheduler_execution_missing") from exc
    if (
        not isinstance(execution_evidence, dict)
        or execution_evidence.get("candidate_id", candidate_id) != candidate_id
        or not isinstance(execution_evidence.get("runner_result"), dict)
        or execution_evidence["runner_result"].get("status") != "succeeded"
    ):
        _fail("execution_incomplete")
    # Native output capture is retained by this scheduler attempt and is the trace authority.
    # Hashing only the evaluator DTO would allow detached evaluation evidence to masquerade as
    # process execution.
    trace_digest = _sha(getattr(run.output, "output_capture_sha256", None), "output_capture")
    common = {
        "candidate_id": candidate_id,
        "request_sha256": request.digest(),
        "contract_sha256": request.contract_sha256,
        "evaluator_sha256": request.evaluator_sha256,
        "environment_sha256": request.environment_sha256,
        "memory_snapshot_sha256": request.memory_snapshot_sha256,
    }
    try:
        source_digest = None
        bundle = getattr(evaluated, "bundle", None)
        entrypoint = getattr(bundle, "entrypoint", None)
        for source in getattr(bundle, "files", ()):
            if getattr(source, "path", None) == entrypoint:
                source_digest = getattr(source, "sha256", None)
                break
        if source_digest is None:
            _fail("candidate_source_missing")
        candidate = NativeCandidateRecord(
            **common,
            candidate_receipt_sha256=_sha(entry.preparation_receipt_sha256, "candidate_receipt"),
            candidate_source_sha256=_sha(source_digest, "candidate_source"),
        )
        execution = NativeExecutionReceipt(
            **common,
            receipt_sha256=_sha(entry.execution_receipt_sha256, "execution_receipt"),
            trace_digest=trace_digest,
        )
        evaluation = NativeEvaluationReceipt(
            **common,
            receipt_sha256=_sha(entry.evaluation_receipt_sha256, "evaluation_receipt"),
        )
        publication_receipt = NativePublicationReceipt(
            **common,
            receipt_sha256=_sha(entry.publication_receipt_sha256, "publication_receipt"),
        )
    except RSILearningError:
        raise
    except Exception as exc:
        raise NativeRSISchedulerProviderError("rsi_native_scheduler_receipt_invalid") from exc
    return NativeRSIReceiptBundle(candidate, execution, evaluation, publication_receipt, worker_terminal_status="completed", official_evaluator_receipt=_official_evaluator_receipt(request, candidate.candidate_source_sha256, execution.receipt_sha256, publication_receipt.receipt_sha256, evaluation.receipt_sha256))


def _bundle_wire(bundle: NativeRSIReceiptBundle) -> dict[str, Any]:
    return {name: getattr(bundle, name).to_dict() for name in (
        "candidate", "execution", "evaluation", "publication",
    )}


def _retained_bundle(
    request: SolverRequest, evidence: NativeRetainedCandidateEvidence, preparation_sha256: str,
) -> NativeRSIReceiptBundle:
    # The reader remains detached evidence. RSI attribution is granted only by the provider's
    # separate input/launch/plan revalidation and the exact persisted provenance comparison.
    report = json.loads(evidence.evaluation_report_json)
    if not isinstance(report, dict) or report.get("validity") != 1:
        _fail("evaluation_not_valid")
    common = {
        "candidate_id": evidence.candidate_id, "request_sha256": request.digest(),
        "contract_sha256": request.contract_sha256, "evaluator_sha256": request.evaluator_sha256,
        "environment_sha256": request.environment_sha256,
        "memory_snapshot_sha256": request.memory_snapshot_sha256,
    }
    return NativeRSIReceiptBundle(
        NativeCandidateRecord(
            **common, candidate_receipt_sha256=preparation_sha256,
            candidate_source_sha256=evidence.entrypoint_source_sha256,
        ),
        NativeExecutionReceipt(
            **common, receipt_sha256=evidence.candidate_execution_receipt_sha256,
            trace_digest=evidence.output_capture_sha256,
        ),
        NativeEvaluationReceipt(**common, receipt_sha256=evidence.candidate_evaluation_receipt_sha256),
        NativePublicationReceipt(**common, receipt_sha256=evidence.candidate_publication_receipt_sha256),
        worker_terminal_status="completed",
        official_evaluator_receipt=_official_evaluator_receipt(
            request, evidence.entrypoint_source_sha256, evidence.candidate_execution_receipt_sha256,
            evidence.candidate_publication_receipt_sha256, evidence.candidate_evaluation_receipt_sha256,
        ),
    )


def _preparation_receipt(context: NativeRSISchedulerContext, evidence: NativeRetainedCandidateEvidence) -> str:
    batch = Path(context.workspace).expanduser().absolute() / "evolution" / "producer-batches" / context.intent.journal_id
    journal = parse_producer_bundle_publication_journal(batch / "journal.published.json")
    if journal.digest() != evidence.publication_journal_sha256:
        _fail("publication_changed")
    slots = [slot for slot in journal.candidates if slot.candidate_id == evidence.candidate_id]
    if len(slots) != 1 or slots[0].status != "admitted":
        _fail("candidate_missing")
    return slots[0].preparation_receipt_sha256


def _read_retained(
    context: NativeRSISchedulerContext, *, candidate_id: str, journal_sha256: str,
    producer_receipt_sha256: str,
    lineage_inspection: object | None = None,
) -> NativeRetainedCandidateEvidence:
    try:
        options = {} if lineage_inspection is None else {"lineage_inspection": lineage_inspection}
        return read_native_retained_candidate(
            context.workspace, candidate_id=candidate_id,
            expected_journal_sha256=journal_sha256,
            expected_producer_execution_receipt_sha256=producer_receipt_sha256,
            intent=context.intent, attestation=context.attestation, artifact=context.artifact,
            contract=context.contract, groups=context.groups, evaluator_kind=context.evaluator_kind,
            evaluator_fingerprint=context.evaluator_fingerprint,
            runner_fingerprint=context.runner_fingerprint, dependency_sha256=context.dependency_sha256,
            environment_sha256=context.environment_sha256, require_broker=True,
            **options,
        )
    except Exception as exc:
        raise NativeRSISchedulerProviderError("rsi_native_scheduler_retained_invalid") from exc


def _provenance_payload(
    plan: NativeRSIExecutionPlan, inputs: NativeRSIInputDescriptor,
    evidence: NativeRetainedCandidateEvidence, bundle: NativeRSIReceiptBundle,
) -> dict[str, Any]:
    return {
        "schema_version": "1", "protocol": "lunar-native-rsi-provenance-v1",
        "plan": plan.to_dict(), "input_binding_sha256": inputs.launch_binding_sha256,
        "retained_evidence_sha256": evidence.digest(),
        "publication_journal_sha256": evidence.publication_journal_sha256,
        "producer_execution_receipt_sha256": evidence.producer_execution_receipt_sha256,
        "bundle": _bundle_wire(bundle),
    }


def _rejection_native_shapes(value: object) -> None:
    """Inspect only exact native DTO fields before comparisons or serialization.

    The live receipt/output must agree with original native readback. Refusing
    nested callback values first keeps that comparison from invoking a caller's
    equality or serializer. The original native reader still supplies authority.
    """
    from .candidate_bundle import CandidateSourceBundle, CandidateSourceFile
    from .evolution import CandidateDraft
    from .producer_bundle_admission import ProducerBundleAdmissionItem, ProducerBundleAdmissionPlan
    from .producer_bundle_handoff import VerifiedProducerBundle
    from .producer_bundle_population import ProducerBundleDraft
    from .producer_handoff import ProducerMaterial, ProducerResultEnvelope
    from .producer_process import ProducerEnvelopeEvidence, ProducerStreamEvidence
    from .rsi_python_admission import validate_rsi_python_admission_shapes

    validate_rsi_python_admission_shapes(value, dto_types=(
        NativeTrustedProducerRecovery, ProducerExecutionReceipt, NativeTrustedOutputPreparation,
        ProducerStreamEvidence, ProducerEnvelopeEvidence, ProducerResultEnvelope, ProducerMaterial,
        VerifiedProducerBundle, CandidateSourceBundle, CandidateSourceFile, ProducerBundleDraft,
        CandidateDraft, ProducerBundleAdmissionPlan, ProducerBundleAdmissionItem,
    ))


def _rejected_descriptor(binding: RejectionLineageC1Binding) -> ProducerLineageRejectedTerminalV2:
    """Project the original owner's complete C1 binding, never a discovered file."""
    if type(binding) is not RejectionLineageC1Binding:
        _fail("rejection_lineage_invalid")
    binding = RejectionLineageC1Binding.from_dict(binding.to_dict())
    rejected = ProducerLineageRejectedTerminalV2(**{
        name: getattr(binding, name) for name in (
            "run_id", "journal_id", "episode_id", "ordinal", "before_sha256",
            "prepared_journal_sha256", "terminal_journal_sha256", "rejection_manifest_sha256",
            "terminal_marker_sha256", "candidate_ids", "archive_sha256", "state_sha256",
        )
    })
    if rejected.digest() != binding.rejected_sha256:
        _fail("rejection_lineage_changed")
    return rejected


def _rejection_live_run_shape(run: object) -> None:
    from .rsi_python_admission import validate_rsi_python_admission_shapes

    if (type(run) is not NativeTrustedProducerRun
            or type(run.publication) is not NativeProducerBundleTransactionResult
            or type(run.publication.terminal_journal) is not ProducerBundlePublicationJournal
            or type(run.publication.journal) is not ProducerBundlePublicationJournal):
        _fail("rejection_run_invalid")
    _rejection_native_shapes(run.receipt)
    _rejection_native_shapes(run.output)
    validate_rsi_python_admission_shapes(
        (run.status, run.publication.publication_status, run.publication.journal,
         run.publication.terminal_journal, run.publication.admitted_candidate_ids,
         run.publication.rejected_candidate_ids, run.publication.artifacts),
        dto_types=(ProducerBundlePublicationJournal, ProducerBundlePublicationCandidate,
                   PythonProducerAdmissionHandoffFilePin),
    )


class NativeRSISchedulerProvider:
    """Callable provider that launches exactly one validated native scheduler attempt."""

    def __init__(self, context: NativeRSISchedulerContext) -> None:
        if not isinstance(context, NativeRSISchedulerContext):
            _fail("context_invalid")
        self.context = context
        # The controller is attached after construction by the explicit
        # producer-sidecar path.  Keeping it out of the immutable context and
        # fingerprint avoids hashing thread locals or mutable controller state.
        self._python_admission_controller: Any | None = None
        self._python_admission_replay_controller: Any | None = None
        # This observation belongs only to the original active dispatch stack.
        # Restart and historical inspection cannot populate or refresh it.
        self._live_rejection: tuple[Any, ...] | None = None
        # Private original-worker preparation binding. Public BRS dispatch keeps
        # its old refusal; this transient object never enters configuration.
        self._brs_native_binding: object | None = None
        # Freeze before any launch. Recovery compares this prepared pin to the durable sidecar;
        # neither provider checks nor restart may silently pin a replacement database.
        self._failure_ledger_identity = (
            None if context.failure_ledger is None
            else MappingProxyType(_read_ledger_identity(context.failure_ledger))
        )

    def bind_python_admission_controller(self, controller: Any) -> None:
        """Attach one controller for an explicit prepared-boundary bridge.

        Binding alone does not make :meth:`__call__` read Python evidence or invoke
        a bridge. The immutable context's explicit post-execution supplier opts
        into the late join, retaining its original handoff/file pin.

        This is intentionally a one-way local binding.  Rebinding a provider after
        it has been used could route an in-flight native claim to another controller,
        so a different object is rejected and the original binding is retained.
        """
        if controller is None:
            _fail("python_admission_controller_invalid")
        existing = self._python_admission_controller
        if existing is not None and existing is not controller:
            _fail("python_admission_controller_changed")
        self._python_admission_controller = controller

    def bind_python_admission_replay_controller(self, controller: Any) -> None:
        """Associate read-only lineage inspection without enabling fresh dispatch."""
        from .rsi_controller import RSILearningController

        if (type(controller) is not RSILearningController
                or controller.producer_multi_episode_publication is not True
                or controller.producer_child_execution is not True
                or controller.ledger is not self.context.failure_ledger
                or controller.producer_workspace is None
                or Path(controller.producer_workspace).expanduser().absolute()
                != Path(self.context.workspace).expanduser().absolute()):
            _fail("python_replay_controller_invalid")
        existing = self._python_admission_replay_controller
        if existing is not None and existing is not controller:
            _fail("python_replay_controller_changed")
        self._python_admission_replay_controller = controller

    def _retained_lineage_options(
        self, request: SolverRequest, memory: MemorySnapshot, plan: NativeRSIExecutionPlan,
    ) -> dict[str, Any]:
        controller = self._python_admission_replay_controller
        if controller is None:
            return {}
        self.bind_python_admission_replay_controller(controller)
        with controller.ledger.read_only_observations():
            claim = controller.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
        # Before the mapper saves the native result, the fresh publication must
        # still satisfy the original current-head gate. Never catch that gate's
        # refusal to adopt a historical proof for a started attempt.
        if claim is None or claim.status == "started":
            return {}
        from .rsi_publication_lineage import (
            RSIPublicationLineageInspection,
            RSIPublicationLineageV2Inspection,
        )

        flag = controller.producer_known_rejection
        if type(flag) is not bool:
            _fail("rejection_configuration_invalid")
        inspection_type = RSIPublicationLineageV2Inspection if flag else RSIPublicationLineageInspection
        return {"lineage_inspection": inspection_type(
            controller, request=request, memory=memory, native_plan=plan,
        )}

    def _python_admission_descriptor(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan,
    ):
        """Read fixed prepared evidence for an explicit bridge call.

        The evidence includes post-execution/runtime fields and therefore must
        only be read at the later prepared/publication boundary.  The native
        provider never calls this helper from :meth:`__call__`; the opt-in join
        receives its journal from the transaction's later durable notification.
        """
        controller = self._python_admission_controller
        if controller is None:
            return None
        # The controller binding is the opt-in gate.  Do not infer Python authority
        # from a filename when a caller supplied no retained sidecar.
        if getattr(controller, "producer_sidecar", None) is None:
            _fail("python_admission_sidecar_missing")
        controller_workspace = getattr(controller, "producer_workspace", None)
        if controller_workspace is None or Path(controller_workspace).expanduser().absolute() != Path(
            self.context.workspace,
        ).expanduser().absolute():
            _fail("python_admission_workspace_mismatch")
        batch = self.provenance_batch
        try:
            journal = parse_producer_bundle_publication_journal(batch / "journal.prepared.json")
            anchor = read_python_producer_admission_attempt_anchor(
                batch / "python-producer-admission-anchor.json",
            )
            return build_python_admission_bridge_descriptor(
                run_id=plan.run_id,
                episode_id=request.episode_id,
                native_plan=plan,
                prepared_journal=journal,
                expected_anchor_sha256=anchor.anchor_sha256,
            )
        except NativeRSISchedulerProviderError:
            raise
        except Exception as exc:
            raise NativeRSISchedulerProviderError(
                "rsi_native_scheduler_python_admission_evidence_invalid",
            ) from exc

    def _pin_python_admission_before_dispatch(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan,
    ) -> None:
        """Pin an already prepared bridge when an explicit caller requests it.

        The historical method name is retained for compatibility.  It is not
        part of native provider dispatch: callers must establish the prepared
        observer/publication boundary and retain the original Python handoff
        before invoking this helper.
        """
        controller = self._python_admission_controller
        if controller is None:
            return
        descriptor = self._python_admission_descriptor(request, plan)
        if descriptor is None:  # pragma: no cover - defensive binding guard
            _fail("python_admission_descriptor_missing")
        wait_check = getattr(controller, "_python_admission_bridge_wait_check", None)
        if not callable(wait_check):
            _fail("python_admission_wait_check_missing")
        try:
            bridge = PythonAdmissionBridgeAdapter(controller, descriptor, wait_check=wait_check)
            result = bridge.pin_live(descriptor)
        except NativeRSISchedulerProviderError:
            raise
        except Exception as exc:
            raise NativeRSISchedulerProviderError(
                "rsi_native_scheduler_python_admission_failed",
            ) from exc
        if type(result) is not str or len(result) != 64 or any(
            char not in "0123456789abcdef" for char in result
        ):
            _fail("python_admission_record_invalid")

    def pin_python_admission_at_prepared_boundary(
        self,
        request: SolverRequest,
        plan: NativeRSIExecutionPlan,
        *,
        prepared_journal: ProducerBundlePublicationJournal,
        python_handoff_sha256: str,
        python_handoff_file_pin: PythonProducerAdmissionHandoffFilePin,
        expected_anchor_sha256: str,
    ) -> str:
        """Explicitly bridge one already-persisted prepared Python attempt.

        This hook is intended for a producer transaction's ``prepared_observer``.
        It receives the immutable journal and the original handoff/file pin from
        that transaction, rereads both retained files, then maps the fixed bridge
        descriptor to the controller's DRS/BRS owner. The opt-in native join only
        invokes it from the later transaction observer before evaluation.
        """
        if not isinstance(request, SolverRequest) or not isinstance(plan, NativeRSIExecutionPlan):
            _fail("python_admission_prepared_input_invalid")
        controller = self._python_admission_controller
        if controller is None:
            _fail("python_admission_controller_missing")
        if not isinstance(prepared_journal, ProducerBundlePublicationJournal):
            _fail("python_admission_prepared_journal_invalid")
        controller_workspace = getattr(controller, "producer_workspace", None)
        if getattr(controller, "producer_sidecar", None) is None:
            _fail("python_admission_sidecar_missing")
        if (
            controller_workspace is None
            or Path(controller_workspace).expanduser().absolute()
            != Path(self.context.workspace).expanduser().absolute()
        ):
            _fail("python_admission_workspace_mismatch")
        context = self.context
        try:
            # The prepared journal is late evidence, never a source of native plan
            # authority.  Reuse the same validated launch-input snapshot and complete
            # plan/request binding that protects normal dispatch before touching any
            # prepared-journal or handoff path.
            inputs = self._inputs(require_unexpired=False)
            memory = _memory_from_request_inputs(inputs, request)
            _assert_plan_binding(request, memory, plan, context, inputs)
            pin = parse_python_producer_admission_handoff_file_pin(python_handoff_file_pin)
            _sha(python_handoff_sha256, "python_admission_handoff")
            _sha(expected_anchor_sha256, "python_admission_anchor")
            if pin.handoff_sha256 != python_handoff_sha256:
                _fail("python_admission_handoff_pin_mismatch")
            intent = context.intent
            identity = {
                "journal_id": intent.journal_id,
                "run_id": intent.run_id,
                "parent_task_id": intent.parent_task_id,
                "task_id": intent.task_id,
            }
            if any(getattr(prepared_journal, field) != value for field, value in identity.items()):
                _fail("python_admission_prepared_identity_mismatch")
            if prepared_journal.python_handoff_sha256 != python_handoff_sha256:
                _fail("python_admission_handoff_mismatch")
            if prepared_journal.python_handoff_file_pin != pin:
                _fail("python_admission_handoff_pin_mismatch")
            if plan.run_id != intent.run_id or plan.journal_id != intent.journal_id:
                _fail("python_admission_plan_identity_mismatch")
            if any(getattr(prepared_journal, field) != expected for field, expected in (
                ("contract_sha256", request.contract_sha256),
                ("evaluator_kind", context.evaluator_kind),
                ("evaluator_fingerprint", request.evaluator_sha256),
                ("runner_fingerprint", context.runner_fingerprint),
                ("dependency_sha256", context.dependency_sha256),
                ("environment_sha256", request.environment_sha256),
            )):
                _fail("python_admission_prepared_binding_mismatch")
            batch = self.provenance_batch
            persisted_journal = parse_producer_bundle_publication_journal(
                batch / "journal.prepared.json",
            )
            if persisted_journal != prepared_journal:
                _fail("python_admission_prepared_journal_drift")
            verify_producer_bundle_prepared_intent(context.workspace, prepared_journal)
            verify_producer_bundle_python_handoff_anchor(context.workspace, prepared_journal)

            def reread_prepared_evidence():
                """Revalidate immutable handoff and anchor bytes at each bridge boundary."""
                persisted = parse_producer_bundle_publication_journal(
                    batch / "journal.prepared.json",
                )
                if persisted != prepared_journal:
                    _fail("python_admission_prepared_journal_drift")
                verify_producer_bundle_prepared_intent(context.workspace, prepared_journal)
                verify_producer_bundle_python_handoff_anchor(context.workspace, prepared_journal)
                retained_sidecar = read_python_producer_admission_handoff_pinned(
                    batch / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME,
                    expected_file_pin=pin,
                )
                retained_handoff = retained_sidecar.handoff
                if (
                    retained_sidecar.file_pin != pin
                    or retained_handoff.handoff_sha256 != python_handoff_sha256
                    or retained_handoff.state != "prepared"
                    or any(getattr(retained_handoff, field) != value for field, value in identity.items())
                    or retained_handoff.native_execution_receipt_sha256
                    != prepared_journal.native_execution_receipt_sha256
                    or retained_handoff.admission_plan_sha256 != prepared_journal.admission_sha256
                    or retained_handoff.contract_sha256 != request.contract_sha256
                    or retained_handoff.evaluator_sha256 != request.evaluator_sha256
                    or retained_handoff.environment_sha256 != request.environment_sha256
                ):
                    _fail("python_admission_handoff_mismatch")
                retained_anchor = read_python_producer_admission_attempt_anchor(
                    batch / "python-producer-admission-anchor.json",
                    expected_anchor_sha256=expected_anchor_sha256,
                )
                if (
                    retained_anchor.handoff_sha256 != retained_handoff.handoff_sha256
                    or retained_anchor.run_id != intent.run_id
                    or retained_anchor.journal_id != intent.journal_id
                    or retained_anchor.native_execution_receipt_sha256
                    != prepared_journal.native_execution_receipt_sha256
                    or retained_anchor != project_python_producer_admission_attempt_anchor(retained_handoff)
                ):
                    _fail("python_admission_anchor_mismatch")
                return retained_sidecar, retained_anchor

            _, anchor = reread_prepared_evidence()
            descriptor = build_python_admission_bridge_descriptor(
                run_id=plan.run_id,
                episode_id=request.episode_id,
                native_plan=plan,
                prepared_journal=prepared_journal,
                expected_anchor_sha256=anchor.anchor_sha256,
            )
            wait_check = getattr(controller, "_python_admission_bridge_wait_check", None)
            if not callable(wait_check):
                _fail("python_admission_wait_check_missing")
            bridge = PythonAdmissionBridgeAdapter(controller, descriptor, wait_check=wait_check)
            result = bridge.pin_live(descriptor)
            # The bridge may synchronously invoke owner callbacks.  Re-read after it
            # returns so a callback cannot replace the trusted prepared evidence while
            # still yielding an apparently valid admission record.
            reread_prepared_evidence()
        except NativeRSISchedulerProviderError:
            raise
        except Exception as exc:
            raise NativeRSISchedulerProviderError(
                "rsi_native_scheduler_prepared_bridge_failed",
            ) from exc
        if type(result) is not str or len(result) != 64 or any(
            char not in "0123456789abcdef" for char in result
        ):
            _fail("python_admission_record_invalid")
        return result

    def _refuse_brs_worker_publication(self) -> None:
        # This provider executes the complete publication transaction on its calling
        # thread. A ready/ACK pin cannot authorize that transaction on a BRS worker.
        # Keep the existing pin-only bridge available; a future owner bridge must
        # move the whole transaction (and rejection provenance) before enabling this.
        from .rsi_python_publication import (
            RSIPythonPublicationError,
            _refuse_active_brs_worker_publication,
        )

        try:
            _refuse_active_brs_worker_publication(self._python_admission_controller)
        except RSIPythonPublicationError as exc:
            raise NativeRSISchedulerProviderError(
                "rsi_native_scheduler_brs_owner_publication_required",
            ) from exc

    def _python_publication_join(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan, inputs: NativeRSIInputDescriptor,
    ) -> dict[str, Any]:
        """Build lazy local hooks without reading post-execution evidence.

        The context supplier was fingerprinted before the controller froze its run.
        Its returned creation pin, prepared notification and first record digest
        stay scoped to this single dispatch; no restart or legacy adoption occurs.
        """
        self._refuse_brs_worker_publication()
        supplier, native_supplier = NativeRSISchedulerContext._python_handoff_suppliers(self.context)
        if supplier is None and native_supplier is None:
            return {}
        controller = self._python_admission_controller
        if controller is None:
            _fail("python_admission_controller_missing")
        if (getattr(controller, "producer_sidecar", None) is None
                or getattr(controller, "producer_workspace", None) is None):
            _fail("python_admission_sidecar_missing")
        if Path(controller.producer_workspace).expanduser().absolute() != Path(
            self.context.workspace,
        ).expanduser().absolute():
            _fail("python_admission_workspace_mismatch")
        wait_check = getattr(controller, "_python_admission_bridge_wait_check", None)
        if not callable(wait_check):
            _fail("python_admission_wait_check_missing")
        lineage_owner = None
        publication_flag = getattr(controller, "producer_multi_episode_publication", False)
        if type(publication_flag) is not bool:
            _fail("multi_episode_configuration_invalid")
        if publication_flag:
            from .rsi_publication_lineage import RSIPublicationLineage

            lineage_owner = RSIPublicationLineage(
                controller, request=request,
                memory=_memory_from_request_inputs(inputs, request), native_plan=plan,
            )
        supplied: PythonProducerAdmissionHandoffSidecar | None = None
        output_plan = None
        admitted = None
        supplier_called = False
        observer_called = False

        def revalidate(stage: str) -> None:
            current_suppliers = NativeRSISchedulerContext._python_handoff_suppliers(self.context)
            if current_suppliers[0] is not supplier or current_suppliers[1] is not native_supplier:
                _fail("python_handoff_supplier_changed")
            if self._python_admission_controller is not controller:
                _fail("python_admission_controller_changed")
            if stage == "rsi_native_python_scheduler_return" and admitted is None:
                _fail("python_admission_missing")
            # This is the observation lock, not ownership. It is never held while
            # the BRS bridge waits for the owner to pin/ack.
            with controller._python_admission_brs_observations():
                wait_check()
                current = self._inputs(require_unexpired=False)
                if current != inputs:
                    _fail("python_admission_input_changed")
                _assert_plan_binding(
                    request, _memory_from_request_inputs(current, request), plan, self.context, current,
                )
                if admitted is not None:
                    admitted.revalidate(stage)

        def obtain_handoff(receipt, output, native_run=None):
            nonlocal supplied, output_plan, supplier_called
            if supplier_called:
                _fail("python_handoff_supplier_replayed")
            supplier_called = True
            revalidate("rsi_native_python_handoff")
            value = (supplier(receipt, output) if native_supplier is None else native_supplier(native_run))
            if type(value) is not PythonProducerAdmissionHandoffSidecar:
                _fail("python_handoff_supplier_invalid")
            supplied = value
            output_plan = output.admission_plan
            revalidate("rsi_native_after_python_handoff")
            return value

        def obtain_native_handoff(run):
            if type(run) is not NativeTrustedProducerRun:
                _fail("python_native_run_invalid")
            return obtain_handoff(run.receipt, run.output, run)

        def pin_prepared(journal: ProducerBundlePublicationJournal) -> None:
            nonlocal admitted, observer_called
            if observer_called:
                _fail("python_admission_prepared_observer_replayed")
            observer_called = True
            if supplied is None or output_plan is None:
                _fail("python_handoff_supplier_missing")
            revalidate("rsi_native_before_python_pin")
            expected_anchor = project_python_producer_admission_attempt_anchor(supplied.handoff)
            record_sha256 = self.pin_python_admission_at_prepared_boundary(
                request, plan, prepared_journal=journal,
                python_handoff_sha256=supplied.handoff.handoff_sha256,
                python_handoff_file_pin=supplied.file_pin,
                expected_anchor_sha256=expected_anchor.anchor_sha256,
            )
            # Reuse complete reference/row validation without duplicating its
            # authority contract. Import late to avoid module initialization cycles.
            from .rsi_python_publication import _capture_admission

            with controller._python_admission_brs_observations():
                admitted = _capture_admission(
                    controller, plan.run_id, request.episode_id, record_sha256, output_plan,
                )
                if admitted.native_plan != plan or admitted.prepared_journal != journal:
                    _fail("python_admission_reference_mismatch")
                if lineage_owner is not None:
                    lineage_owner.acknowledge_prepared(journal, record_sha256)
                revalidate("rsi_native_after_python_pin")

        hooks = {
            "prepared_observer": pin_prepared,
            "evidence_revalidator": revalidate,
        }
        if native_supplier is None:
            hooks["python_handoff_after_execution"] = obtain_handoff
        else:
            hooks["python_handoff_after_native_execution"] = obtain_native_handoff
        if lineage_owner is not None:
            hooks["producer_multi_episode_publication"] = True
            hooks["lineage_owner"] = lineage_owner
        return hooks

    def assert_failure_ledger(self, ledger: RSILedger) -> None:
        """Verify explicit failure wiring against the original database, never repin it."""
        if self._failure_ledger_identity is None:
            return
        if (self.context.failure_ledger is None
                or _read_ledger_identity(self.context.failure_ledger) != self._failure_ledger_identity
                or _read_ledger_identity(ledger) != self._failure_ledger_identity):
            _fail("failure_ledger_changed")

    def assert_rejection_ledger(self, ledger: RSILedger) -> None:
        """Require the explicit original ledger and constructor inode pin."""
        if (type(ledger) is not RSILedger or ledger is not self.context.failure_ledger
                or self._failure_ledger_identity is None):
            _fail("rejection_ledger_missing")
        self.assert_failure_ledger(ledger)

    def _rejection_claim(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan, *, live: bool,
        expected: NativeEpisodeClaim | None = None,
    ) -> NativeEpisodeClaim:
        ledger = self.context.failure_ledger
        self.assert_rejection_ledger(ledger)
        with ledger.read_only_observations():
            claim = ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
        self.assert_rejection_ledger(ledger)
        if type(claim) is not NativeEpisodeClaim or claim.status != ("started" if live else "failed"):
            _fail("rejection_claim_missing")
        original = replace(claim, status="started")
        if expected is not None and original != expected:
            _fail("rejection_claim_changed")
        return original

    def _failure_claim(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan, *, live: bool,
        expected: NativeEpisodeClaim | None = None,
    ) -> NativeEpisodeClaim:
        ledger = self.context.failure_ledger
        if ledger is None or self._failure_ledger_identity is None:
            _fail("failure_ledger_missing")
        self.assert_failure_ledger(ledger)
        try:
            claim = ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
        except Exception as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_failure_claim_invalid") from exc
        self.assert_failure_ledger(ledger)
        if (claim is None or claim.status not in {"started", "failed", "cancelled"}
                or (live and claim.status != "started")):
            _fail("failure_claim_missing")
        original = replace(claim, status="started")
        if expected is not None and original != expected:
            _fail("failure_claim_changed")
        return original

    def _provenance_kind(self) -> str:
        """All three terminal names are inventoried under a no-follow directory chain."""
        chain = None
        try:
            chain = DirectoryChain(self.provenance_batch, "rsi_native_scheduler_provenance_invalid")
            present = []
            for name in (
                NATIVE_RSI_PROVENANCE_NAME, NATIVE_RSI_FAILURE_PROVENANCE_NAME,
                NATIVE_RSI_REJECTION_PROVENANCE_NAME,
            ):
                try:
                    os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
                    present.append(name)
                except FileNotFoundError:
                    pass
            chain.check()
            if len(present) > 1:
                _fail("conflicting_provenance")
            if NATIVE_RSI_REJECTION_PROVENANCE_NAME in present:
                return "rejection"
            return "failure" if NATIVE_RSI_FAILURE_PROVENANCE_NAME in present else "success"
        except NativeRSISchedulerProviderError:
            raise
        except Exception as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_provenance_invalid") from exc
        finally:
            if chain is not None:
                chain.close()

    @property
    def provenance_batch(self) -> Path:
        return Path(self.context.workspace).expanduser().absolute() / "evolution" / "producer-batches" / self.context.intent.journal_id

    def _inputs(self, *, require_unexpired: bool) -> NativeRSIInputDescriptor:
        context = self.context
        NativeRSISchedulerContext._assert_live_modules_sink(context)
        try:
            scope_options = NativeRSISchedulerContext._native_scope_options(
                context, require_unexpired=require_unexpired,
            )
            scope = scope_options.get("whole_scope")
            fixed_u_owner = None if scope is None else context._native_scope_pin.scope_children[0]
            inputs = validate_native_rsi_launch_inputs(
                context.workspace, intent=context.intent, attestation=context.attestation,
                artifact=context.artifact, require_unexpired=require_unexpired,
                **({"fixed_u_owner": fixed_u_owner} if fixed_u_owner is not None else {}),
            )
        except Exception as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_launch_invalid") from exc
        if not isinstance(inputs, NativeRSIInputDescriptor):
            _fail("native_inputs_missing")
        return inputs

    def plan(self, request: SolverRequest, memory: MemorySnapshot) -> NativeRSIExecutionPlan:
        """Rebuild the fixed selector plan from original input files without staging or launch."""
        inputs = self._inputs(require_unexpired=False)
        context = self.context
        if context.failure_ledger is not None:
            self.assert_failure_ledger(context.failure_ledger)
        plan = NativeRSIExecutionPlan.from_native_inputs(
            request=request, memory=memory, inputs=inputs, intent=context.intent,
            attestation=context.attestation, artifact=context.artifact,
            candidate_selector_id="native-selector-v1",
            candidate_selector_sha256=component_fingerprint(select_native_candidate),
            evaluator_kind=context.evaluator_kind, evaluator_fingerprint=context.evaluator_fingerprint,
        )
        _assert_plan_binding(request, memory, plan, context, inputs)
        if context.failure_ledger is not None:
            self.assert_failure_ledger(context.failure_ledger)
        return plan

    def validate_preclaim(
        self,
        request: SolverRequest,
        plan: NativeRSIExecutionPlan,
        *,
        claim_ledger: RSILedger | None = None,
    ) -> None:
        """Validate the native launch boundary before a gateway creates a claim.

        This is intentionally a read-only bridge for controller-owned child previews.  It
        re-reads the sealed native inputs, checks the complete request/plan binding, observes
        cancellation, the original shared monotonic control and the original absolute deadline,
        and verifies that the episode has no existing native claim. It never creates, settles,
        or publishes a claim and never calls
        the producer scheduler.  A started or terminal claim is a recovery/replay boundary and
        therefore refuses a fresh dispatch rather than allowing a second effect.

        A context with a failure ledger requires that exact original ledger object and its
        constructor pin. A legacy native context with no failure ledger may observe the gateway's
        exact ``RSILedger`` with a local inode pin for this call only; it acquires no persistent
        failure authority. Neither path rebinds the provider or creates a database.
        """
        if type(request) is not SolverRequest or type(plan) is not NativeRSIExecutionPlan:
            _fail("preclaim_input_invalid")
        context = self.context
        bound_ledger = context.failure_ledger
        original_failure_pin = self._failure_ledger_identity
        if bound_ledger is not None:
            if claim_ledger is not bound_ledger:
                _fail("preclaim_ledger_mismatch")
            if original_failure_pin is None:
                _fail("preclaim_context_changed")
            ledger = bound_ledger
            ledger_identity = dict(original_failure_pin)
        else:
            # An originally bound provider cannot discard its durable failure authority and
            # borrow the compatibility path. Truly unbound native contexts may only observe a
            # gateway-supplied exact ledger; never store this temporary pin on the provider.
            if original_failure_pin is not None:
                _fail("preclaim_context_changed")
            if type(claim_ledger) is not RSILedger:
                _fail("preclaim_ledger_mismatch")
            ledger = claim_ledger
            ledger_identity = _read_ledger_identity(ledger)

        def inspect_ledger_identity() -> None:
            if (self.context is not context or context.failure_ledger is not bound_ledger
                    or self._failure_ledger_identity is not original_failure_pin):
                _fail("preclaim_context_changed")
            if _read_ledger_identity(ledger) != ledger_identity:
                _fail("preclaim_ledger_changed")
            if bound_ledger is not None:
                self.assert_failure_ledger(ledger)

        inspect_ledger_identity()
        context_fingerprint = self.rsi_fingerprint_config()
        cancellation = self.context.cancelled
        execution_control = self.context.execution_control

        def inspect_execution_control() -> None:
            if (self.context.cancelled is not cancellation
                    or self.context.execution_control is not execution_control):
                _fail("preclaim_context_changed")
            try:
                if cancellation is not None and bool(cancellation()):
                    _fail("preclaim_cancelled")
            except NativeRSISchedulerProviderError:
                raise
            except Exception as exc:
                raise NativeRSISchedulerProviderError(
                    "rsi_native_scheduler_preclaim_cancellation_invalid",
                ) from exc
            if execution_control is not None:
                try:
                    execution_control.check("rsi_native_preclaim")
                except SolveExecutionCancelled as exc:
                    raise NativeRSISchedulerProviderError(
                        "rsi_native_scheduler_preclaim_cancelled",
                    ) from exc
                except SolveExecutionBudgetExceeded as exc:
                    raise NativeRSISchedulerProviderError(
                        "rsi_native_scheduler_preclaim_deadline_expired",
                    ) from exc
                except Exception as exc:
                    raise NativeRSISchedulerProviderError(
                        "rsi_native_scheduler_preclaim_control_invalid",
                    ) from exc
            if (self.context.cancelled is not cancellation
                    or self.context.execution_control is not execution_control):
                _fail("preclaim_context_changed")

        # Check the original shared monotonic control as well as the explicit callback before
        # observing launch files or claims. Neither gate constructs a control or resets its
        # start/deadline; an earlier parent ceiling continues to constrain this child.
        inspect_execution_control()
        inputs = self._inputs(require_unexpired=True)
        memory = _memory_from_request_inputs(inputs, request)
        _assert_plan_binding(request, memory, plan, self.context, inputs)

        def inspect_claim() -> None:
            inspect_ledger_identity()
            try:
                with ledger.read_only_observations():
                    claim = ledger.inspect_native_episode_claim(
                        request, plan_sha256=plan.plan_sha256,
                    )
            except Exception as exc:
                raise NativeRSISchedulerProviderError(
                    "rsi_native_scheduler_preclaim_claim_invalid",
                ) from exc
            inspect_ledger_identity()
            if claim is not None:
                # This includes ``started``/unknown and every terminal result.  Both cases
                # require the gateway's explicit recovery/replay path and cannot become a
                # fresh dispatch.
                _fail("preclaim_claim_exists")

        inspect_claim()
        # The callback and ledger read above are untrusted observation boundaries. Re-read every
        # launch input and the complete provider fingerprint before accepting the preview. This
        # catches a callback that mutates intent, broker headers, strategy, hooks, or deadline
        # while the preflight is in progress; requiring an unexpired second read also catches a
        # deadline crossed during the callback/ledger operation.
        repeated_inputs = self._inputs(require_unexpired=True)
        if repeated_inputs != inputs:
            _fail("preclaim_input_changed")
        repeated_memory = _memory_from_request_inputs(repeated_inputs, request)
        _assert_plan_binding(request, repeated_memory, plan, self.context, repeated_inputs)
        if self.context.cancelled is not cancellation:
            _fail("preclaim_context_changed")
        if self.rsi_fingerprint_config() != context_fingerprint:
            _fail("preclaim_context_changed")
        inspect_claim()
        # The second ledger observation can cross a parent deadline or observe cancellation.
        # Sample both authorities again, then reread the original absolute deadline and context
        # pins because callbacks within either control are observation boundaries themselves.
        inspect_execution_control()
        inspect_ledger_identity()
        final_inputs = self._inputs(require_unexpired=True)
        if final_inputs != inputs:
            _fail("preclaim_input_changed")
        final_memory = _memory_from_request_inputs(final_inputs, request)
        _assert_plan_binding(request, final_memory, plan, self.context, final_inputs)
        if self.rsi_fingerprint_config() != context_fingerprint:
            _fail("preclaim_context_changed")
        inspect_ledger_identity()

    def _native_rejection_snapshot(
        self, plan: NativeRSIExecutionPlan, binding: RejectionLineageC1Binding, *,
        inspection: object | None = None,
        live_run: NativeTrustedProducerRun | None = None,
    ) -> tuple[NativeTrustedProducerRecovery, VerifiedProducerBundleRejection]:
        """Reconstruct original producer output and every native rejected candidate.

        The immutable native verifier deliberately has no current population
        prefix fallback. The exact original owner or sealed inspection checks
        that separate lineage authority before and after this reader.
        """
        if live_run is not None:
            _rejection_live_run_shape(live_run)
        context = self.context
        root = Path(context.workspace).expanduser().absolute()
        batch = self.provenance_batch
        pins = {
            "intent": context.intent, "attestation": context.attestation, "artifact": context.artifact,
            "contract": context.contract, "groups": context.groups, "evaluator_kind": context.evaluator_kind,
            "evaluator_fingerprint": context.evaluator_fingerprint,
            "runner_fingerprint": context.runner_fingerprint, "dependency_sha256": context.dependency_sha256,
            "environment_sha256": context.environment_sha256, "require_broker": True,
        }

        def native() -> NativeTrustedProducerRecovery:
            recovered = recover_native_trusted_producer(root, **pins)
            if type(recovered) is not NativeTrustedProducerRecovery:
                _fail("rejection_native_invalid")
            _rejection_native_shapes(recovered)
            receipt, output = recovered.receipt, recovered.output
            if (recovered.status != "recovered" or receipt.status != "completed"
                    or receipt.receipt_sha256 != receipt.digest()
                    or output.execution_receipt_sha256 != receipt.receipt_sha256
                    or type(output.publication_eligible) is not bool
                    or output.request_coverage != "brokered_requests_only"):
                _fail("rejection_native_invalid")
            _sha(output.output_capture_sha256, "rejection_output")
            if any(getattr(receipt, field) != getattr(plan, field) for field in (
                "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
                "intent_sha256", "attestation_sha256",
            )):
                _fail("rejection_native_binding_mismatch")
            return recovered

        def observe(recovered: NativeTrustedProducerRecovery) -> VerifiedProducerBundleRejection:
            prepared = parse_producer_bundle_publication_journal(batch / "journal.prepared.json")
            terminal = parse_producer_bundle_publication_journal(batch / "journal.json")
            if (prepared.digest() != binding.prepared_journal_sha256
                    or terminal.digest() != binding.terminal_journal_sha256
                    or prepared.admission_sha256 != recovered.output.admission_plan.digest()
                    or terminal.native_execution_receipt_sha256 != recovered.receipt.receipt_sha256
                    or tuple((item.bundle_id, item.bundle_sha256) for item in terminal.candidates)
                    != tuple((item.bundle_id, item.bundle_sha256)
                             for item in recovered.output.admission_plan.bundles)):
                _fail("rejection_native_binding_mismatch")
            authority = {
                "journal_id": plan.journal_id, "run_id": plan.run_id,
                "parent_task_id": plan.parent_task_id, "task_id": plan.task_id,
                "contract_sha256": plan.request.contract_sha256,
                "evaluator_kind": context.evaluator_kind, "evaluator_fingerprint": context.evaluator_fingerprint,
                "runner_fingerprint": context.runner_fingerprint, "dependency_sha256": context.dependency_sha256,
                "environment_sha256": context.environment_sha256,
            }
            if any(getattr(terminal, field) != expected for field, expected in authority.items()):
                _fail("rejection_native_binding_mismatch")
            if live_run is not None and (
                        type(live_run.status) is not str or live_run.status != "all_rejected"
                        or type(live_run.publication.publication_status) is not str
                        or live_run.publication.publication_status != "all_rejected"
                        or live_run.publication.journal != prepared
                        or live_run.publication.terminal_journal != terminal
                        or type(live_run.publication.admitted_candidate_ids) is not tuple
                        or live_run.publication.admitted_candidate_ids != ()
                        or type(live_run.publication.rejected_candidate_ids) is not tuple
                        or live_run.publication.rejected_candidate_ids != binding.candidate_ids
                        or type(live_run.publication.artifacts) is not tuple
                        or live_run.publication.artifacts != () or live_run.publication.manifest is not None
                        or live_run.publication.published_journal is not None
                        or live_run.receipt != recovered.receipt or live_run.output != recovered.output):
                _fail("rejection_run_changed")
            if inspection is None:
                observed = _verify_terminal_batch_rejection_evidence(root, batch, prepared, terminal=terminal)
            else:
                from .rsi_publication_lineage import (
                    RSIPublicationLineageV2Inspection,
                    StartedRSIRejectionInspection,
                )

                inspection_type = type(inspection)
                if inspection_type not in {RSIPublicationLineageV2Inspection, StartedRSIRejectionInspection}:
                    _fail("rejection_inspection_invalid")
                observed = inspection_type.inspect_rejection(
                    inspection, root, recovered.output.admission_plan, terminal,
                )
            if type(observed) is not VerifiedProducerBundleRejection:
                _fail("rejection_native_invalid")
            VerifiedProducerBundleRejection.__post_init__(observed)
            if (observed.terminal != terminal or observed.manifest_sha256 != binding.rejection_manifest_sha256
                    or observed.candidate_ids != binding.candidate_ids):
                _fail("rejection_native_binding_mismatch")
            return observed

        before = native()
        evidence = observe(before)
        after = native()
        repeated = observe(after)
        if after != before or repeated != evidence:
            _fail("rejection_native_changed")
        return after, repeated

    def _read_rejection(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan, inputs: NativeRSIInputDescriptor, *,
        authority: object, live: bool, expected_binding: RejectionLineageC1Binding | None = None,
        expected_file_pin: NativeRSIRejectionFilePin | None = None,
        expected_config: dict[str, Any] | None = None,
    ) -> NativeRSIRejectionEvidence:
        """Read P only through independently held original C1/C2 authority."""
        from .rsi_publication_lineage import (
            RSIPublicationLineage,
            RSIPublicationLineageV2Inspection,
            StartedRSIRejectionInspection,
        )

        authority_type = type(authority)
        allowed = {RSIPublicationLineage, StartedRSIRejectionInspection} if live else {RSIPublicationLineageV2Inspection}
        if authority_type not in allowed:
            _fail("rejection_inspection_invalid")

        def held() -> tuple[RejectionLineageC1Binding, NativeRSIRejectionFilePin]:
            binding = authority_type.rejection_provenance_binding(authority)
            pin = authority_type.rejection_provenance_file_pin(authority)
            if type(binding) is not RejectionLineageC1Binding or type(pin) is not NativeRSIRejectionFilePin:
                _fail("rejection_inspection_invalid")
            binding = RejectionLineageC1Binding.from_dict(binding.to_dict())
            pin = NativeRSIRejectionFilePin.from_dict(pin.to_dict())
            if (binding.run_id != plan.run_id or binding.episode_id != request.episode_id
                    or binding.journal_id != plan.journal_id
                    or expected_binding is not None and binding != expected_binding
                    or expected_file_pin is not None and pin != expected_file_pin):
                _fail("rejection_lineage_changed")
            return binding, pin

        try:
            config = self.rsi_fingerprint_config()
            if expected_config is not None and config != expected_config:
                _fail("rejection_context_changed")
            binding, file_pin = held()
            saved = read_native_rsi_rejection_provenance(self.provenance_batch, expected_file_pin=file_pin)
            if (saved.plan != plan or saved.input_binding_sha256 != inputs.launch_binding_sha256
                    or dict(saved.ledger_identity) != self._failure_ledger_identity or saved.lineage != binding
                    or saved.rejected != _rejected_descriptor(binding)):
                _fail("rejection_provenance_drift")
            self._rejection_claim(request, plan, live=live, expected=saved.claim)
            recovery, observation = self._native_rejection_snapshot(
                plan, binding, inspection=None if authority_type is RSIPublicationLineage else authority,
            )
            reconstructed = NativeRSIRejectionEvidence(
                plan=plan, input_binding_sha256=inputs.launch_binding_sha256,
                ledger_identity=self._failure_ledger_identity, claim=saved.claim,
                lineage=binding, rejected=_rejected_descriptor(binding), terminal=observation.terminal,
                producer_execution_receipt_sha256=recovery.receipt.receipt_sha256,
                producer_output_sha256=recovery.output.output_capture_sha256,
                execution_receipt_sha256s=observation.execution_receipt_sha256s,
                evaluation_receipt_sha256s=observation.evaluation_receipt_sha256s,
                retained_evidence_sha256s=observation.retained_evidence_sha256s,
            )
            if reconstructed.to_dict() != saved.to_dict():
                _fail("rejection_provenance_drift")
            if (self._inputs(require_unexpired=False) != inputs or self.rsi_fingerprint_config() != config
                    or held() != (binding, file_pin)
                    or read_native_rsi_rejection_provenance(self.provenance_batch, expected_file_pin=file_pin) != saved
                    or self._provenance_kind() != "rejection"):
                _fail("rejection_provenance_changed")
            self._rejection_claim(request, plan, live=live, expected=saved.claim)
            if held() != (binding, file_pin):
                _fail("rejection_lineage_changed")
            return saved
        except NativeRSISchedulerProviderError:
            raise
        except Exception as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_rejection_provenance_invalid") from exc

    def recover_rejection(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan, *, inspection: object,
    ) -> NativeRSIRejectionEvidence:
        """Read an explicitly selected C2-complete started claim without settlement."""
        from .rsi_publication_lineage import StartedRSIRejectionInspection

        if (type(inspection) is not StartedRSIRejectionInspection
                or type(request) is not SolverRequest or type(plan) is not NativeRSIExecutionPlan):
            _fail("rejection_inspection_invalid")
        inputs = self._inputs(require_unexpired=False)
        _assert_plan_binding(request, _memory_from_request_inputs(inputs, request), plan, self.context, inputs)
        self._rejection_claim(request, plan, live=True)
        if self._provenance_kind() != "rejection":
            _fail("rejection_provenance_missing")
        return self._read_rejection(request, plan, inputs, authority=inspection, live=True)

    def recover_live_rejection(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan,
    ) -> NativeRSIRejectionEvidence:
        """Repeat original active owner/C2 observation inside the fresh dispatch stack."""
        if self._brs_native_binding is not None:
            from .rsi_brs_native_provider import recover_brs_native_rejection

            return recover_brs_native_rejection(self, request, plan)
        from .rsi_controller import RSILearningController
        from .rsi_publication_lineage import RSIPublicationLineage

        saved = self._live_rejection
        if type(saved) is not tuple or len(saved) != 8:
            _fail("rejection_live_owner_missing")
        owner, controller, original_request, original_plan, inputs, config, binding, pin = saved
        if (type(owner) is not RSIPublicationLineage or type(controller) is not RSILearningController
                or self._python_admission_controller is not controller or controller.producer_known_rejection is not True
                or type(request) is not SolverRequest or type(plan) is not NativeRSIExecutionPlan
                or request != original_request or plan != original_plan):
            _fail("rejection_live_owner_changed")
        repeated_inputs = self._inputs(require_unexpired=False)
        if repeated_inputs != inputs:
            _fail("rejection_input_changed")
        _assert_plan_binding(request, _memory_from_request_inputs(inputs, request), plan, self.context, inputs)
        return self._read_rejection(
            request, plan, inputs, authority=owner, live=True,
            expected_binding=binding, expected_file_pin=pin, expected_config=config,
        )

    def _persist_live_rejection(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan, inputs: NativeRSIInputDescriptor, *,
        run: NativeTrustedProducerRun, owner: object, claim: NativeEpisodeClaim | None,
        config: dict[str, Any],
    ) -> NativeRSIRejectionEvidence:
        """Original live C1 -> fresh publishing-FD P pin -> same-owner C2."""
        from .rsi_publication_lineage import RSIPublicationLineage

        if type(owner) is not RSIPublicationLineage or claim is None:
            _fail("rejection_live_owner_missing")
        controller = self._python_admission_controller
        try:
            self._rejection_claim(request, plan, live=True, expected=claim)
            binding = RSIPublicationLineage.rejection_provenance_binding(owner)
            rejected = _rejected_descriptor(binding)
            recovery, observation = self._native_rejection_snapshot(plan, binding, live_run=run)
            evidence = NativeRSIRejectionEvidence(
                plan=plan, input_binding_sha256=inputs.launch_binding_sha256,
                ledger_identity=self._failure_ledger_identity, claim=claim,
                lineage=binding, rejected=rejected, terminal=observation.terminal,
                producer_execution_receipt_sha256=recovery.receipt.receipt_sha256,
                producer_output_sha256=recovery.output.output_capture_sha256,
                execution_receipt_sha256s=observation.execution_receipt_sha256s,
                evaluation_receipt_sha256s=observation.evaluation_receipt_sha256s,
                retained_evidence_sha256s=observation.retained_evidence_sha256s,
            )
            if (self._inputs(require_unexpired=False) != inputs or self.rsi_fingerprint_config() != config
                    or self._python_admission_controller is not controller
                    or RSIPublicationLineage.rejection_provenance_binding(owner) != binding):
                _fail("rejection_input_changed")
            self._rejection_claim(request, plan, live=True, expected=claim)
            digest, file_pin = persist_native_rsi_rejection_provenance(
                self.provenance_batch, evidence, retained_bytes=binding.retained_bytes,
            )
            readback = read_native_rsi_rejection_provenance(self.provenance_batch, expected_file_pin=file_pin)
            if readback.to_dict() != evidence.to_dict() or readback.provenance_sha256 != digest:
                _fail("rejection_provenance_changed")
            if (self._inputs(require_unexpired=False) != inputs or self.rsi_fingerprint_config() != config
                    or self._python_admission_controller is not controller
                    or RSIPublicationLineage.rejection_provenance_binding(owner) != binding):
                _fail("rejection_input_changed")
            self._rejection_claim(request, plan, live=True, expected=claim)
            RSIPublicationLineage.acknowledge_rejection_provenance(owner, readback, file_pin)
            if RSIPublicationLineage.rejection_provenance_file_pin(owner) != file_pin:
                _fail("rejection_lineage_changed")
            self._live_rejection = (
                owner, controller, request, plan, inputs, config, binding, file_pin,
            )
            return self.recover_live_rejection(request, plan)
        except NativeRSISchedulerProviderError:
            raise
        except Exception as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_rejection_provenance_invalid") from exc

    def recover(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan,
    ) -> NativeRSIReceiptBundle | NativeRSIFailureEvidence | NativeRSIRejectionEvidence:
        """Revalidate existing provenance and artifacts; never launch or settle a started claim."""
        inputs = self._inputs(require_unexpired=False)
        memory = _memory_from_request_inputs(inputs, request)
        _assert_plan_binding(request, memory, plan, self.context, inputs)
        if self.context.failure_ledger is not None:
            self.assert_failure_ledger(self.context.failure_ledger)
        kind = self._provenance_kind()
        if kind == "failure":
            return self._recover_failure(request, plan, inputs)
        if kind == "rejection":
            self._rejection_claim(request, plan, live=False)
            options = self._retained_lineage_options(request, memory, plan)
            from .rsi_publication_lineage import RSIPublicationLineageV2Inspection

            inspection = options.get("lineage_inspection")
            if type(inspection) is not RSIPublicationLineageV2Inspection:
                _fail("rejection_inspection_invalid")
            return self._read_rejection(request, plan, inputs, authority=inspection, live=False)
        try:
            saved = read_native_rsi_provenance(self.provenance_batch)
            candidate = NativeCandidateRecord.from_dict(saved["bundle"]["candidate"])
            evidence = _read_retained(
                self.context, candidate_id=candidate.candidate_id,
                journal_sha256=saved["publication_journal_sha256"],
                producer_receipt_sha256=saved["producer_execution_receipt_sha256"],
                **self._retained_lineage_options(request, memory, plan),
            )
            bundle = _retained_bundle(request, evidence, _preparation_receipt(self.context, evidence))
            expected = _provenance_payload(plan, inputs, evidence, bundle)
            if {key: value for key, value in saved.items() if key not in {"file_identity", "provenance_sha256"}} != expected:
                _fail("provenance_drift")
            if self._inputs(require_unexpired=False) != inputs or read_native_rsi_provenance(self.provenance_batch) != saved:
                _fail("provenance_changed")
            if self._provenance_kind() != "success":
                _fail("conflicting_provenance")
            if self.context.failure_ledger is not None:
                self.assert_failure_ledger(self.context.failure_ledger)
            return replace(bundle, provenance_sha256=saved["provenance_sha256"])
        except NativeRSISchedulerProviderError:
            raise
        except Exception as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_provenance_invalid") from exc

    def _recover_failure(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan, inputs: NativeRSIInputDescriptor,
    ) -> NativeRSIFailureEvidence:
        """Reread original failure proof without launch, cleanup, HTTP or evaluator calls."""
        context = self.context
        try:
            saved = read_native_rsi_failure_provenance(self.provenance_batch)
            if (saved.plan != plan or saved.input_binding_sha256 != inputs.launch_binding_sha256
                    or dict(saved.ledger_identity) != self._failure_ledger_identity):
                _fail("failure_provenance_drift")
            self._failure_claim(request, plan, live=False, expected=saved.claim)
            recovered = recover_native_trusted_failure(
                context.workspace, intent=context.intent, attestation=context.attestation,
                artifact=context.artifact, expected=saved.failure,
            )
            if recovered != saved.failure:
                _fail("failure_evidence_changed")
            if (self._inputs(require_unexpired=False) != inputs
                    or read_native_rsi_failure_provenance(self.provenance_batch) != saved
                    or self._provenance_kind() != "failure"):
                _fail("failure_provenance_changed")
            self._failure_claim(request, plan, live=False, expected=saved.claim)
            return saved
        except NativeRSISchedulerProviderError:
            raise
        except Exception as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_failure_provenance_invalid") from exc

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        """Expose immutable launch wiring for controller run fingerprints.

        The provider carries an attestation and launch context, but mutable invocation state is
        held by the scheduler and never enters this projection.  The context's content digests
        bind every retained input; strategy and broker are explicitly fingerprinted so resume
        cannot silently switch publication or request destinations.
        """
        context = self.context
        supplier, native_supplier = NativeRSISchedulerContext._python_handoff_suppliers(context)
        sink_projection = NativeRSISchedulerContext._live_modules_sink_projection(context)
        scope_projection = NativeRSISchedulerContext._native_scope_projection(context)
        strategy_fingerprint = _strategy_fingerprint(context.strategy)
        try:
            broker_headers_sha256 = hashlib.sha256(
                canonical_json(context.broker_config.headers, maximum=64 * 1024),
            ).hexdigest()
        except Exception as exc:
            raise NativeRSISchedulerProviderError(
                "rsi_native_scheduler_broker_fingerprint_invalid",
            ) from exc
        projection = {
            "protocol": "lunar-native-rsi-scheduler-provider-v1",
            "workspace": str(Path(context.workspace).expanduser().absolute()),
            "producer_root": str(Path(context.producer_root).expanduser().absolute()),
            "intent_sha256": context.intent.digest(),
            "attestation_sha256": context.attestation.digest(),
            "bootstrap_descriptor_sha256": context.artifact.descriptor.digest(),
            "bootstrap_artifact_sha256": context.artifact.artifact_sha256,
            "broker_endpoint": context.broker_config.endpoint,
            "broker_headers_sha256": broker_headers_sha256,
            "contract_sha256": context.contract.digest(),
            "groups": [group.to_dict() for group in context.groups],
            "evaluator_kind": context.evaluator_kind,
            "evaluator_fingerprint": context.evaluator_fingerprint,
            "runner_fingerprint": context.runner_fingerprint,
            "dependency_sha256": context.dependency_sha256,
            "environment_sha256": context.environment_sha256,
            "strategy_sha256": strategy_fingerprint,
            "execution_control": None if context.execution_control is None else {
                "started_at": context.execution_control.started_at,
                "deadline": context.execution_control.deadline,
                "timeout_seconds": context.execution_control.timeout_seconds,
            },
            "cancelled_sha256": None if context.cancelled is None else component_fingerprint(context.cancelled),
        }
        if sink_projection is not None:
            projection["live_modules_sink"] = sink_projection
        if scope_projection is not None:
            projection["native_scope"] = scope_projection
        if context.failure_ledger is not None:
            self.assert_failure_ledger(context.failure_ledger)
            projection["failure_ledger"] = dict(self._failure_ledger_identity)
        if supplier is not None:
            projection["python_handoff_after_execution_sha256"] = component_fingerprint(
                supplier,
            )
        if native_supplier is not None:
            if any(getattr(_native_scheduler, name) is not original for name, original in (
                ("_native_handoff_evidence", _native_handoff_evidence),
                ("_prepublication_evidence", _prepublication_evidence),
                ("_native_output_envelope_pin", _native_output_envelope_pin),
                ("_run_native_trusted_producer", _run_native_trusted_producer),
            )):
                _fail("python_native_handoff_policy_changed")
            projection["python_handoff_after_native_execution_sha256"] = component_fingerprint(native_supplier)
            projection["python_native_handoff_dependencies"] = {
                "evidence": component_fingerprint(_native_handoff_evidence),
                "preparation_evidence": component_fingerprint(_prepublication_evidence),
                "output_envelope_acquisition": component_fingerprint(_native_output_envelope_pin),
                "scheduler": component_fingerprint(_run_native_trusted_producer),
                "supplier_selection": component_fingerprint(NativeRSISchedulerContext._python_handoff_suppliers),
                "late_join": component_fingerprint(NativeRSISchedulerProvider._python_publication_join),
            }
        return projection

    def __call__(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan,
    ) -> NativeRSIReceiptBundle | NativeRSIFailureEvidence | NativeRSIRejectionEvidence:
        if self._brs_native_binding is not None:
            from .rsi_brs_native_provider import run_brs_native_provider

            return run_brs_native_provider(self, request, plan)
        self._refuse_brs_worker_publication()
        if not isinstance(request, SolverRequest) or not isinstance(plan, NativeRSIExecutionPlan):
            _fail("input_invalid")
        context = self.context
        inputs = self._inputs(require_unexpired=True)
        memory = _memory_from_request_inputs(inputs, request)
        _assert_plan_binding(request, memory, plan, context, inputs)
        controller = self._python_admission_controller
        rejection_flag = getattr(controller, "producer_known_rejection", False)
        if type(rejection_flag) is not bool:
            _fail("rejection_configuration_invalid")
        rejection_config = None
        if rejection_flag:
            if self._python_admission_controller is not controller:
                _fail("python_admission_controller_changed")
            from .rsi_controller import RSILearningController

            if (type(controller) is not RSILearningController
                    or controller.producer_multi_episode_publication is not True
                    or controller.producer_child_execution is not True
                    or not any(value is not None for value in
                               NativeRSISchedulerContext._python_handoff_suppliers(context))
                    or controller.ledger is not context.failure_ledger):
                _fail("rejection_configuration_invalid")
            self.assert_rejection_ledger(context.failure_ledger)
            rejection_config = self.rsi_fingerprint_config()
        python_join = self._python_publication_join(request, plan, inputs)
        claim = None
        if context.failure_ledger is not None:
            claim = self._failure_claim(request, plan, live=True)
            kind = self._provenance_kind()
            if kind == "failure":
                _fail("failure_recovery_required")
            if kind == "rejection":
                _fail("rejection_recovery_required")
        parent_deadline = None
        if inputs.deadline_unix is not None:
            mapped_start = time.monotonic()
            remaining = inputs.deadline_unix - time.time()
            if remaining <= 0:
                _fail("deadline_expired")
            # Native scheduler controls use monotonic timestamps.  Convert the retained Unix
            # deadline once, immediately before dispatch, without widening the request budget.
            parent_deadline = mapped_start + remaining
        try:
            scheduler = (run_native_trusted_producer if context.failure_ledger is None
                         else run_native_trusted_producer_outcome)
            run = scheduler(
                context.workspace,
                producer_root=context.producer_root,
                intent=context.intent,
                attestation=context.attestation,
                artifact=context.artifact,
                broker_config=context.broker_config,
                contract=context.contract,
                groups=context.groups,
                evaluator_kind=context.evaluator_kind,
                evaluator_fingerprint=context.evaluator_fingerprint,
                runner_fingerprint=context.runner_fingerprint,
                dependency_sha256=context.dependency_sha256,
                environment_sha256=context.environment_sha256,
                strategy=context.strategy,
                parent_deadline=parent_deadline,
                execution_control=context.execution_control,
                cancelled=context.cancelled,
                **({"live_modules_sink": NativeRSISchedulerContext._assert_live_modules_sink(context)}
                   if getattr(context, "live_modules_sink", None) is not None else {}),
                **NativeRSISchedulerContext._native_scope_options(context, require_unexpired=True),
                **python_join,
            )
        except NativeRSISchedulerProviderError:
            raise
        except Exception as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_attempt_failed") from exc
        if isinstance(run, NativeTrustedProducerFailure):
            if claim is None or self._failure_ledger_identity is None:
                _fail("failure_ledger_missing")
            self._failure_claim(request, plan, live=True, expected=claim)
            if self._inputs(require_unexpired=False) != inputs:
                _fail("failure_input_changed")
            evidence = NativeRSIFailureEvidence(
                plan=plan, failure=run, input_binding_sha256=inputs.launch_binding_sha256,
                ledger_identity=self._failure_ledger_identity, claim=claim,
            )
            persisted_sha256 = persist_native_rsi_failure_provenance(self.provenance_batch, evidence)
            self._failure_claim(request, plan, live=True, expected=claim)
            recovered = self.recover(request, plan)
            if (not isinstance(recovered, NativeRSIFailureEvidence)
                    or recovered.to_dict() != evidence.to_dict()
                    or recovered.provenance_sha256 != persisted_sha256):
                _fail("failure_provenance_changed")
            return recovered
        if python_join:
            python_join["evidence_revalidator"]("rsi_native_python_scheduler_return")
        if rejection_flag:
            if self._python_admission_controller is not controller:
                _fail("python_admission_controller_changed")
            if type(run) is not NativeTrustedProducerRun or type(run.status) is not str:
                _fail("rejection_run_invalid")
            if run.status == "all_rejected":
                return self._persist_live_rejection(
                    request, plan, inputs, run=run, owner=python_join.get("lineage_owner"),
                    claim=claim, config=rejection_config,
                )
        projected = _build_receipts(request, context, run)
        _publication, journal = _journal_for_published_run(run)
        evidence = _read_retained(
            context, candidate_id=projected.candidate.candidate_id,
            journal_sha256=journal.digest(), producer_receipt_sha256=run.receipt.receipt_sha256,
            **self._retained_lineage_options(request, _memory_from_request_inputs(inputs, request), plan),
        )
        bundle = _retained_bundle(request, evidence, projected.candidate.candidate_receipt_sha256)
        if bundle != projected or self._inputs(require_unexpired=False) != inputs:
            _fail("receipt_projection_drift")
        persist_native_rsi_provenance(
            self.provenance_batch, _provenance_payload(plan, inputs, evidence, bundle),
        )
        return self.recover(request, plan)


def _read_ledger_identity(ledger: RSILedger) -> dict[str, Any]:
    """Read one original SQLite inode without following named files or ancestor symlinks.

    SQLite bytes, timestamps and WAL contents remain mutable; only path/device/inode and the
    immutable original claim are frozen. This does not infer authority from a database digest.
    """
    if not isinstance(ledger, RSILedger):
        _fail("failure_ledger_invalid")
    path = ledger.database
    chain = None
    descriptor = None
    try:
        chain = DirectoryChain(path.parent, "rsi_native_scheduler_failure_ledger_invalid")
        before = os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail("failure_ledger_invalid")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=chain.fd)
        opened = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False)
        identities = {(info.st_dev, info.st_ino) for info in (before, opened, named)}
        if (len(identities) != 1 or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or not stat.S_ISREG(named.st_mode) or named.st_nlink != 1):
            _fail("failure_ledger_changed")
        chain.check()
        return {"database": str(path), "device": opened.st_dev, "inode": opened.st_ino}
    except NativeRSISchedulerProviderError:
        raise
    except Exception as exc:
        raise NativeRSISchedulerProviderError("rsi_native_scheduler_failure_ledger_invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if chain is not None:
            chain.close()


def _memory_from_request_inputs(
    inputs: NativeRSIInputDescriptor, request: SolverRequest,
) -> MemorySnapshot:
    if inputs.request != request:
        _fail("request_input_mismatch")
    if inputs.memory.digest() != request.memory_snapshot_sha256:
        _fail("memory_input_mismatch")
    return inputs.memory


def make_native_rsi_scheduler_provider(context: NativeRSISchedulerContext) -> NativeRSISchedulerProvider:
    """Construct the gateway-compatible scheduler provider."""
    return NativeRSISchedulerProvider(context)


__all__ = [
    "NativeRSISchedulerContext",
    "NativeRSISchedulerProvider",
    "NativeRSISchedulerProviderError",
    "make_native_rsi_scheduler_provider",
]
