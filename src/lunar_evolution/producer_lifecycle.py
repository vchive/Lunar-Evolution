"""One-shot cooperative producer preparation with explicit evidence limits.

This entry point joins the existing process and multi-file handoff boundaries. It is
supporting evidence only: a directly executed producer can act before its work gate,
and its request count is a declaration rather than controller-observed traffic.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import _benchmark_files as _files
from .algorithm import AlgorithmProblemContract
from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_scheduler import (
    NativeTrustedProducerRecovery,
    NativeTrustedProducerRun,
    NativeTrustedSchedulerError,
    recover_native_trusted_producer,
    run_native_trusted_producer,
)
from .producer_broker_ipc import ProducerBrokerConfig
from .producer_bundle_admission import (
    ProducerBundleAdmissionPlan,
    build_producer_bundle_admission_plan,
)
from .producer_bundle_handoff import (
    BundleGroup,
    VerifiedProducerBundle,
    prepare_producer_bundle_manifest,
)
from .producer_bundle_population import ProducerBundleDraft, prepare_producer_bundle_drafts
from .producer_handoff import ProducerHandoffError, ProducerResultEnvelope, parse_producer_envelope
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import (
    ProducerExecutionReceipt,
    recover_producer_process,
    run_producer_process,
)


class ProducerLifecycleError(ValueError):
    """Fixed-code preparation error without producer-controlled text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProducerLifecyclePreparation:
    receipt: ProducerExecutionReceipt
    envelope: ProducerResultEnvelope
    bundles: tuple[VerifiedProducerBundle, ...]
    drafts: tuple[ProducerBundleDraft, ...]
    admission_plan: ProducerBundleAdmissionPlan
    terminal_status: str
    cleanup_status: str
    execution_outcome: str
    deadline_scope: str
    request_coverage: str = "cooperative_declaration_only"
    broker_coverage: str = "not_integrated"
    publication_status: str = "not_started"
    # The native trusted path keeps the scheduler's complete observations available to callers
    # while reusing this preparation DTO for the existing bundle/publication boundary.  These
    # fields are optional so the cooperative path above remains byte-for-byte compatible.
    native_run: NativeTrustedProducerRun | NativeTrustedProducerRecovery | None = None
    publication: object | None = None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProducerLifecycleError("producer_lifecycle_envelope_invalid")
        result[key] = value
    return result


def _read_bound_envelope(
    workspace: str | Path, intent: ProducerLaunchIntent, receipt: ProducerExecutionReceipt,
) -> tuple[Path, ProducerResultEnvelope]:
    evidence = receipt.envelope_evidence
    if evidence is None or evidence.read_status != "stable" or evidence.relative_path != intent.envelope_path:
        raise ProducerLifecycleError("producer_lifecycle_envelope_unbound")
    output = (
        Path(workspace).expanduser().absolute() / "evolution" / "producer-batches"
        / intent.journal_id / intent.output_directory
    )
    path = output / "producer-result.json"
    try:
        raw = _files.read_regular_file(path, intent.output_max_bytes)
        info = path.lstat()
    except (_files.BenchmarkFileError, OSError) as exc:
        raise ProducerLifecycleError("producer_lifecycle_envelope_unbound") from exc
    if (
        len(raw) != evidence.bytes or hashlib.sha256(raw).hexdigest() != evidence.sha256
        or (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns)
        != (evidence.device, evidence.inode, evidence.mtime_ns, evidence.ctime_ns)
    ):
        raise ProducerLifecycleError("producer_lifecycle_envelope_changed")
    try:
        envelope = parse_producer_envelope(json.loads(raw, object_pairs_hook=_unique_object))
    except (ProducerHandoffError, UnicodeError, ValueError, TypeError) as exc:
        raise ProducerLifecycleError("producer_lifecycle_envelope_invalid") from exc
    if (
        envelope.producer_id != intent.producer_id
        or envelope.producer_fingerprint != intent.producer_fingerprint
        or envelope.contract_sha256 != intent.contract_sha256
        or envelope.budget.get("requests") != receipt.request_count
    ):
        raise ProducerLifecycleError("producer_lifecycle_envelope_mismatch")
    return output, envelope


def run_producer_lifecycle(
    workspace: str | Path,
    *,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    producer_root: str | Path,
    contract: AlgorithmProblemContract,
    groups: tuple[BundleGroup, ...] | list[BundleGroup],
    evaluator_kind: str,
    evaluator_fingerprint: str,
    runner_fingerprint: str,
    dependency_sha256: str,
    environment_sha256: str,
    expected_run_id: str | None = None,
    expected_parent_task_id: str | None = None,
    expected_task_id: str | None = None,
) -> ProducerLifecyclePreparation:
    """Execute once, verify retained bytes, and prepare drafts without publication.

    This uses the cooperative direct-process path. It is deliberately not a
    production external-producer admission API until trusted bootstrap and a
    controller-owned request broker are integrated.
    """
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(contract, AlgorithmProblemContract):
        raise ProducerLifecycleError("producer_lifecycle_input_invalid")
    if contract.digest() != intent.contract_sha256 or (
        evaluator_kind != intent.evaluator_kind
        or evaluator_fingerprint != intent.evaluator_fingerprint
        or runner_fingerprint != intent.runner_fingerprint
        or dependency_sha256 != intent.dependency_sha256
        or environment_sha256 != intent.environment_sha256
    ):
        raise ProducerLifecycleError("producer_lifecycle_authority_mismatch")
    receipt = run_producer_process(
        workspace, intent=intent, attestation=attestation, producer_root=producer_root,
        expected_run_id=expected_run_id, expected_parent_task_id=expected_parent_task_id,
        expected_task_id=expected_task_id,
    )
    if receipt.status != "completed" or receipt.exit_code != 0 or not receipt.gate_released:
        raise ProducerLifecycleError("producer_lifecycle_process_incomplete")
    # A successful envelope alone is insufficient.  Keep the preparation stage
    # fail-closed unless the durable process receipt proves bounded completion and
    # verified owner cleanup under the same attempt deadline.
    if receipt.cleanup_status not in {"cleaned", "already_exited"}:
        raise ProducerLifecycleError("producer_lifecycle_cleanup_unverified")
    if receipt.envelope_evidence is None or receipt.envelope_evidence.read_status != "stable":
        raise ProducerLifecycleError("producer_lifecycle_envelope_unbound")
    try:
        observed = recover_producer_process(workspace, journal_id=intent.journal_id)
    except Exception as exc:
        raise ProducerLifecycleError("producer_lifecycle_receipt_unbound") from exc
    if observed.get("receipt_sha256") != receipt.receipt_sha256:
        raise ProducerLifecycleError("producer_lifecycle_receipt_unbound")
    output, envelope = _read_bound_envelope(workspace, intent, receipt)
    bundles = prepare_producer_bundle_manifest(
        output, envelope, groups, contract, intent.producer_fingerprint, intent.producer_id,
    )
    drafts = prepare_producer_bundle_drafts(output, bundles)
    plan = build_producer_bundle_admission_plan(
        drafts, contract_sha256=intent.contract_sha256,
        evaluator_kind=intent.evaluator_kind, evaluator_fingerprint=intent.evaluator_fingerprint,
        runner_fingerprint=intent.runner_fingerprint, dependency_sha256=intent.dependency_sha256,
        environment_sha256=intent.environment_sha256,
    )
    return ProducerLifecyclePreparation(
        receipt=receipt,
        envelope=envelope,
        bundles=bundles,
        drafts=drafts,
        admission_plan=plan,
        terminal_status=receipt.status,
        cleanup_status=receipt.cleanup_status,
        execution_outcome="completed",
        deadline_scope="process_attempt_only",
    )


def _project_native_preparation(
    run: NativeTrustedProducerRun | NativeTrustedProducerRecovery,
) -> ProducerLifecyclePreparation:
    """Project the native trusted scheduler result into the lifecycle DTO.

    The scheduler has already performed terminal, receipt, capture, envelope, and authority
    checks.  This projection only copies those verified objects into the established preparation
    shape; it does not reinterpret an unknown result or grant publication authority.
    """
    try:
        receipt = run.receipt
        output = run.output
        publication = getattr(run, "publication", None)
        status = getattr(run, "status", "recovered")
        trusted = receipt.trusted_execution or {}
        broker_coverage = str(trusted.get("broker_coverage", "none"))
        publication_status = status if publication is not None else "not_started"
        return ProducerLifecyclePreparation(
            receipt=receipt,
            envelope=output.envelope,
            bundles=output.bundles,
            drafts=output.drafts,
            admission_plan=output.admission_plan,
            terminal_status=receipt.status,
            cleanup_status=receipt.cleanup_status,
            execution_outcome="completed",
            # The scheduler's preparation and optional publication are outside the producer's
            # one-shot native attempt deadline; callers must not treat this as a renewed budget.
            deadline_scope="native_attempt_only",
            request_coverage=output.request_coverage,
            broker_coverage=broker_coverage,
            publication_status=publication_status,
            native_run=run,
            publication=publication,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProducerLifecycleError("producer_lifecycle_native_projection_invalid") from exc


def run_native_trusted_lifecycle(
    workspace: str | Path,
    *,
    producer_root: str | Path,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact,
    broker_config: ProducerBrokerConfig,
    contract: AlgorithmProblemContract,
    groups: Sequence[BundleGroup],
    evaluator_kind: str,
    evaluator_fingerprint: str,
    runner_fingerprint: str,
    dependency_sha256: str,
    environment_sha256: str,
    strategy: object | None = None,
    execution_control: object | None = None,
    cancelled: Callable[[], bool] | None = None,
    parent_deadline: float | None = None,
) -> ProducerLifecyclePreparation:
    """Run one formal native trusted lifecycle and project its prepared bundles.

    This is the producer lifecycle's production-facing composition point.  It delegates process,
    broker, receipt, and strict output verification to ``native_trusted_scheduler`` and keeps
    publication explicit through the existing optional ``strategy`` argument.  Omitting the
    strategy returns a prepared, publication-free result; supplying it runs the existing atomic
    publication transaction after the formal receipt is bound.
    """
    try:
        run = run_native_trusted_producer(
            workspace,
            producer_root=producer_root,
            intent=intent,
            attestation=attestation,
            artifact=artifact,
            broker_config=broker_config,
            contract=contract,
            groups=groups,
            evaluator_kind=evaluator_kind,
            evaluator_fingerprint=evaluator_fingerprint,
            runner_fingerprint=runner_fingerprint,
            dependency_sha256=dependency_sha256,
            environment_sha256=environment_sha256,
            strategy=strategy,
            execution_control=execution_control,
            cancelled=cancelled,
            parent_deadline=parent_deadline,
        )
    except NativeTrustedSchedulerError as exc:
        # Preserve the fixed scheduler code under the lifecycle namespace without exposing
        # arbitrary producer/provider text.
        raise ProducerLifecycleError(f"producer_lifecycle_{exc.code}") from exc
    return _project_native_preparation(run)


def recover_native_trusted_lifecycle(
    workspace: str | Path,
    *,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact,
    contract: AlgorithmProblemContract,
    groups: Sequence[BundleGroup],
    evaluator_kind: str,
    evaluator_fingerprint: str,
    runner_fingerprint: str,
    dependency_sha256: str,
    environment_sha256: str,
    require_broker: bool = True,
) -> ProducerLifecyclePreparation:
    """Read-only project of a durable native trusted lifecycle.

    Recovery never relaunches a producer, consumes another attestation, or publishes a bundle.
    The returned preparation can be handed to the explicit publication transaction only after a
    caller makes that decision separately.
    """
    try:
        recovered = recover_native_trusted_producer(
            workspace,
            intent=intent,
            attestation=attestation,
            artifact=artifact,
            contract=contract,
            groups=groups,
            evaluator_kind=evaluator_kind,
            evaluator_fingerprint=evaluator_fingerprint,
            runner_fingerprint=runner_fingerprint,
            dependency_sha256=dependency_sha256,
            environment_sha256=environment_sha256,
            require_broker=require_broker,
        )
    except NativeTrustedSchedulerError as exc:
        raise ProducerLifecycleError(f"producer_lifecycle_{exc.code}") from exc
    return _project_native_preparation(recovered)


__all__ = [
    "ProducerLifecycleError",
    "ProducerLifecyclePreparation",
    "recover_native_trusted_lifecycle",
    "run_native_trusted_lifecycle",
    "run_producer_lifecycle",
]
