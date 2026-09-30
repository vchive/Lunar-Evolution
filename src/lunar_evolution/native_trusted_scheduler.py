"""Explicit one-shot scheduler entry point for native trusted producers.

The lower-level native trusted modules intentionally expose separate boundaries: process
execution, formal execution-receipt persistence, output preparation, and publication.  This
module is the small local scheduler entry point that joins those boundaries in that order.  It
does not discover a producer, start a background worker, retry an unknown attempt, or infer a
publication strategy.  A caller must supply the pinned bootstrap, launch attestation, broker,
and (when publication is requested) an already initialized local population strategy.

The default operation stops after strict output preparation.  Publication is opt-in by passing
``strategy``; this keeps the producer launch and the population transaction separately auditable
while giving the local fixture path one formal entry point for future scheduler callers.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .algorithm import AlgorithmProblemContract
from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_attempt import (
    NativeTrustedAttemptError,
    NativeTrustedAttemptObservation,
    run_native_trusted_attempt,
)
from .native_trusted_output import (
    NativeTrustedOutputError,
    NativeTrustedOutputPreparation,
    prepare_native_trusted_output,
)
from .native_trusted_receipt import (
    NativeTrustedReceiptError,
    persist_native_trusted_execution_receipt,
    recover_native_trusted_execution_receipt,
)
from .producer_broker_ipc import ProducerBrokerConfig
from .producer_bundle_handoff import BundleGroup
from .producer_bundle_transaction import (
    NativeProducerBundleTransactionResult,
    run_native_producer_bundle_publication_transaction,
)
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import ProducerExecutionReceipt


class NativeTrustedSchedulerError(ValueError):
    """Fixed-code failure at the explicit native scheduler boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NativeTrustedProducerRun:
    """Result of one native producer scheduling attempt.

    ``attempt`` is retained even when the lower-level runner reports
    ``recovery_required``: that status is the native process module's conservative observation
    while the formal receipt and output capture are projected.  ``receipt`` and ``output`` are
    present only after those projections have passed.  ``publication`` is ``None`` for the
    default preparation-only operation.
    """

    attempt: NativeTrustedAttemptObservation
    receipt: ProducerExecutionReceipt
    output: NativeTrustedOutputPreparation
    publication: NativeProducerBundleTransactionResult | None = None
    status: str = "prepared"


@dataclass(frozen=True, slots=True)
class NativeTrustedProducerRecovery:
    """Read-only recovery result for one durable native producer attempt.

    Recovery never invokes the producer, consumes a new attestation, or publishes a bundle.  The
    returned output is reconstructed from the retained evidence and can be passed to the normal
    publication transaction only after a caller has made that decision explicitly.
    """

    receipt: ProducerExecutionReceipt
    output: NativeTrustedOutputPreparation
    status: str = "recovered"


def _workspace_root(workspace: str | Path) -> Path:
    root = Path(workspace).expanduser().absolute()
    if not root.is_dir() or root.is_symlink():
        raise NativeTrustedSchedulerError("native_trusted_scheduler_workspace_invalid")
    return root


def _check_attempt(attempt: NativeTrustedAttemptObservation) -> None:
    # Native trusted attempts deliberately report recovery_required until the formal receipt
    # projection has consumed terminal, cleanup, stream, broker, and output evidence.  Do not
    # treat the status alone as a failure or as success.
    if (
        not isinstance(attempt.terminal_sha256, str)
        or not isinstance(attempt.output_capture_sha256, str)
        or attempt.exit_code != 0
        or attempt.cleanup_status not in {"cleaned", "already_exited"}
        or not attempt.gate_released
        or not attempt.target_started
    ):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_attempt_unpublishable")


def run_native_trusted_producer(
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
    strategy: Any | None = None,
    execution_control: Any | None = None,
    cancelled: Callable[[], bool] | None = None,
    parent_deadline: float | None = None,
) -> NativeTrustedProducerRun:
    """Run one pinned native producer through the formal local boundaries.

    The operation is intentionally one-shot.  It consumes the supplied attestation exactly once
    through :func:`run_native_trusted_attempt`; unknown or incomplete attempts raise and are left
    for the explicit recovery APIs.  A formal receipt and strict same-attempt output capture are
    required before returning.  Passing ``strategy`` opts into the existing atomic local bundle
    transaction; omitting it returns prepared drafts without publication.
    """

    if (
        not isinstance(intent, ProducerLaunchIntent)
        or not isinstance(attestation, ProducerLaunchAttestation)
        or not isinstance(artifact, NativeBootstrapArtifact)
        or not isinstance(broker_config, ProducerBrokerConfig)
        or not isinstance(contract, AlgorithmProblemContract)
    ):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_input_invalid")
    if isinstance(groups, (str, bytes)) or not isinstance(groups, Sequence):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_groups_invalid")
    if cancelled is not None and not callable(cancelled):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_cancellation_invalid")
    root = _workspace_root(workspace)

    try:
        attempt = run_native_trusted_attempt(
            root,
            producer_root=producer_root,
            intent=intent,
            attestation=attestation,
            artifact=artifact,
            broker_config=broker_config,
            cancelled=cancelled,
            parent_deadline=parent_deadline,
        )
    except NativeTrustedAttemptError as exc:
        raise NativeTrustedSchedulerError("native_trusted_scheduler_attempt_failed") from exc
    _check_attempt(attempt)

    try:
        receipt = persist_native_trusted_execution_receipt(
            root,
            intent=intent,
            attestation=attestation,
            artifact=artifact,
            require_broker=True,
        )
    except NativeTrustedReceiptError as exc:
        raise NativeTrustedSchedulerError("native_trusted_scheduler_receipt_unverified") from exc

    try:
        output = prepare_native_trusted_output(
            root,
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
            require_same_attempt_capture=True,
            require_execution_receipt=True,
        )
    except NativeTrustedOutputError as exc:
        raise NativeTrustedSchedulerError("native_trusted_scheduler_output_unverified") from exc
    if output.execution_receipt_sha256 != receipt.receipt_sha256:
        raise NativeTrustedSchedulerError("native_trusted_scheduler_receipt_binding_mismatch")

    publication: NativeProducerBundleTransactionResult | None = None
    status = "prepared"
    if strategy is not None:
        try:
            publication = run_native_producer_bundle_publication_transaction(
                root,
                strategy,
                output.drafts,
                output.admission_plan,
                journal_id=intent.journal_id,
                run_id=intent.run_id,
                parent_task_id=intent.parent_task_id,
                task_id=intent.task_id,
                native_execution_receipt_sha256=receipt.receipt_sha256,
                execution_control=execution_control,
            )
        except Exception as exc:  # transaction exposes fixed local ``code`` values
            raise NativeTrustedSchedulerError(
                "native_trusted_scheduler_publication_failed"
            ) from exc
        status = publication.publication_status
    return NativeTrustedProducerRun(
        attempt=attempt,
        receipt=receipt,
        output=output,
        publication=publication,
        status=status,
    )


def recover_native_trusted_producer(
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
) -> NativeTrustedProducerRecovery:
    """Recover a durable native attempt without starting or retrying any process.

    The receipt projection revalidates terminal, stream, envelope, broker, cleanup, execution
    binding, and create-only receipt bytes.  Strict output preparation then rereads the same
    receipt and output capture.  Any missing, changed, or unknown evidence fails closed.
    """

    if (
        not isinstance(intent, ProducerLaunchIntent)
        or not isinstance(attestation, ProducerLaunchAttestation)
        or not isinstance(artifact, NativeBootstrapArtifact)
        or not isinstance(contract, AlgorithmProblemContract)
        or type(require_broker) is not bool
    ):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_recovery_input_invalid")
    if isinstance(groups, (str, bytes)) or not isinstance(groups, Sequence):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_recovery_groups_invalid")
    root = _workspace_root(workspace)
    try:
        receipt = recover_native_trusted_execution_receipt(
            root,
            intent=intent,
            attestation=attestation,
            artifact=artifact,
            require_broker=require_broker,
        )
    except NativeTrustedReceiptError as exc:
        raise NativeTrustedSchedulerError("native_trusted_scheduler_recovery_receipt_invalid") from exc
    try:
        output = prepare_native_trusted_output(
            root,
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
            require_same_attempt_capture=True,
            require_execution_receipt=True,
        )
    except NativeTrustedOutputError as exc:
        raise NativeTrustedSchedulerError("native_trusted_scheduler_recovery_output_invalid") from exc
    if output.execution_receipt_sha256 != receipt.receipt_sha256:
        raise NativeTrustedSchedulerError("native_trusted_scheduler_recovery_receipt_binding_mismatch")
    return NativeTrustedProducerRecovery(receipt=receipt, output=output)


__all__ = [
    "NativeTrustedProducerRecovery",
    "NativeTrustedProducerRun",
    "NativeTrustedSchedulerError",
    "recover_native_trusted_producer",
    "run_native_trusted_producer",
]
