"""Scheduler-backed provider for the native RSI solver gateway.

The native gateway owns the durable episode claim and replay gate, while this module owns the
one-shot native launch.  Keeping the launch context explicit makes it possible to check every
identity again immediately before dispatch and prevents a caller from accidentally combining a
request with retained evidence from another producer batch.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .algorithm import AlgorithmProblemContract
from .candidate_evaluation_spec import canonical_json
from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_scheduler import (
    NativeTrustedProducerRun,
    run_native_trusted_producer,
)
from .producer_broker_ipc import ProducerBrokerConfig
from .producer_bundle_handoff import BundleGroup
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .rsi_gateway import SolverRequest
from .rsi_identity import RSIIdentityError, component_fingerprint
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_candidate import (
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
)
from .rsi_native_gateway import NativeRSIReceiptBundle
from .rsi_native_inputs import (
    NativeRSIInputDescriptor,
    validate_native_rsi_launch_inputs,
)
from .rsi_native_plan import NativeRSIExecutionPlan


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


def _trace_digest(value: object) -> str:
    try:
        return hashlib.sha256(canonical_json(value, maximum=256 * 1024)).hexdigest()
    except Exception as exc:
        raise NativeRSISchedulerProviderError("rsi_native_scheduler_trace_invalid") from exc


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

    The context is immutable and contains no execution state.  It can therefore be captured by a
    plan factory and reused for a replay check, while the provider still validates the retained
    launch files and all plan identities before consuming an attestation.
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

    def __post_init__(self) -> None:
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
        or getattr(evaluated, "run_id", None) != journal.run_id
        or getattr(evaluated, "journal_sha256", None) != journal.digest()
    ):
        _fail("evaluation_binding_mismatch")
    report = getattr(evaluated.evaluation, "report", None)
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
        or execution_evidence.get("candidate_id") != candidate_id
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
            source_digest = entry.bundle_sha256
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
    return NativeRSIReceiptBundle(candidate, execution, evaluation, publication_receipt)


class NativeRSISchedulerProvider:
    """Callable provider that launches exactly one validated native scheduler attempt."""

    def __init__(self, context: NativeRSISchedulerContext) -> None:
        if not isinstance(context, NativeRSISchedulerContext):
            _fail("context_invalid")
        self.context = context

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        """Expose immutable launch wiring for controller run fingerprints.

        The provider carries an attestation and launch context, but mutable invocation state is
        held by the scheduler and never enters this projection.  The context's content digests
        bind every retained input; strategy and broker are explicitly fingerprinted so resume
        cannot silently switch publication or request destinations.
        """
        context = self.context
        strategy_fingerprint = _strategy_fingerprint(context.strategy)
        try:
            broker_headers_sha256 = hashlib.sha256(
                canonical_json(context.broker_config.headers, maximum=64 * 1024),
            ).hexdigest()
        except Exception as exc:
            raise NativeRSISchedulerProviderError(
                "rsi_native_scheduler_broker_fingerprint_invalid",
            ) from exc
        return {
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
        }

    def __call__(self, request: SolverRequest, plan: NativeRSIExecutionPlan) -> NativeRSIReceiptBundle:
        if not isinstance(request, SolverRequest) or not isinstance(plan, NativeRSIExecutionPlan):
            _fail("input_invalid")
        context = self.context
        try:
            inputs = validate_native_rsi_launch_inputs(
                context.workspace,
                intent=context.intent,
                attestation=context.attestation,
                artifact=context.artifact,
                require_unexpired=True,
            )
        except Exception as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_launch_invalid") from exc
        if not isinstance(inputs, NativeRSIInputDescriptor):
            _fail("native_inputs_missing")
        memory = _memory_from_request_inputs(inputs, request)
        _assert_plan_binding(request, memory, plan, context, inputs)
        parent_deadline = None
        if inputs.deadline_unix is not None:
            remaining = inputs.deadline_unix - time.time()
            if remaining <= 0:
                _fail("deadline_expired")
            # Native scheduler controls use monotonic timestamps.  Convert the retained Unix
            # deadline once, immediately before dispatch, without widening the request budget.
            parent_deadline = time.monotonic() + remaining
        try:
            run = run_native_trusted_producer(
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
            )
        except NativeRSISchedulerProviderError:
            raise
        except Exception as exc:
            raise NativeRSISchedulerProviderError("rsi_native_scheduler_attempt_failed") from exc
        return _build_receipts(request, context, run)


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
