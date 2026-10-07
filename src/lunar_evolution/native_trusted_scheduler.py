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

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .algorithm import AlgorithmProblemContract
from .automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_attempt import (
    NativeTrustedAttemptError,
    NativeTrustedAttemptObservation,
    run_native_trusted_attempt,
)
from .native_trusted_failure import (
    NativeTrustedFailureError,
    NativeTrustedProducerFailure,
    build_native_trusted_failure,
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
    deadline_scope: str = "native_attempt_only"


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


def _raise_attempt_wall_timeout(
    control: SolveExecutionControl | None, *, caller_limited: bool,
) -> NoReturn:
    if control is not None and caller_limited:
        # Native execution stops early to reserve cleanup inside this same caller deadline.
        # A quick cleanup may leave positive wall remainder; none admits another stage after
        # the lower-level runner has reported budget exhaustion. Preserve the exact deadline
        # and actual observation instead of waiting it out or fabricating an expired clock.
        raise SolveExecutionBudgetExceeded(
            "native_producer_attempt", started_at=control.started_at, deadline=control.deadline,
            observed_at=control._now(),
        )
    # An independently tighter intent ceiling is a native attempt timeout, not exhaustion of
    # a wider caller allowance. Neither classification projects a receipt or permits publish.
    raise NativeTrustedSchedulerError("native_trusted_scheduler_attempt_wall_timeout")


def _check_parent_deadline(parent_deadline: float | None) -> None:
    """Validate the scheduler's caller-owned deadline before consuming an attestation.

    The native attempt performs the same check at its lower boundary.  Keeping this
    validation at the scheduler boundary gives callers a stable, scheduler-scoped error
    and, more importantly, prevents a malformed deadline from entering the one-shot
    admission path (where the attestation would otherwise be consumed before the error is
    projected).
    """
    if parent_deadline is None:
        return
    if (
        type(parent_deadline) not in (int, float)
        or not math.isfinite(float(parent_deadline))
    ):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_parent_deadline_invalid")


def _lifecycle_control(
    execution_control: SolveExecutionControl | None,
    cancelled: Callable[[], bool] | None,
    parent_deadline: float | None,
) -> tuple[SolveExecutionControl | None, Callable[[str], None]]:
    """Compose caller controls once, without widening or mutating any parent budget."""
    if execution_control is not None and not isinstance(execution_control, SolveExecutionControl):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_control_invalid")

    def caller_cancelled() -> bool:
        if cancelled is None:
            return False
        try:
            observed = cancelled()
        except Exception as exc:
            raise NativeTrustedSchedulerError("native_trusted_scheduler_cancellation_unknown") from exc
        if type(observed) is not bool:
            raise NativeTrustedSchedulerError("native_trusted_scheduler_cancellation_invalid")
        return observed

    stage = "native_producer_admission"
    if caller_cancelled():
        raise SolveExecutionCancelled(stage)
    if execution_control is not None:
        execution_control.check(stage)
    control = execution_control
    if parent_deadline is not None or (execution_control is not None and cancelled is not None):
        clock = time.monotonic if execution_control is None else execution_control._clock
        started = clock() if execution_control is None else execution_control.started_at
        deadline = parent_deadline
        if execution_control is not None:
            deadline = min(execution_control.deadline, deadline) if deadline is not None else execution_control.deadline
        observed_at = clock()
        if deadline is None or deadline <= observed_at:
            raise SolveExecutionBudgetExceeded(
                stage, started_at=started, deadline=deadline or observed_at, observed_at=observed_at,
            )
        callbacks = [caller_cancelled]
        if execution_control is not None:
            callbacks.append(execution_control.is_cancelled)
        # Cancellation composition does not change a declared allowance. Reconstructing it
        # by deadline subtraction can drift across float boundaries and change durable budget
        # fingerprints even when the exact deadline is unchanged. Only a narrower parent
        # deadline derives a new allowance.
        allowance = (execution_control.timeout_seconds
                     if execution_control is not None and deadline == execution_control.deadline
                     else deadline - started)
        control = SolveExecutionControl(
            allowance, clock=clock, started_at=started,
            cancellation_callbacks=callbacks,
            observe_stage=(execution_control._observe_stage if execution_control is not None else None),
        )
        # Preserve the supplied absolute timestamp exactly instead of recomputing it after
        # floating-point subtraction/addition at a large monotonic start.
        control.deadline = deadline

    def check(stage: str) -> None:
        if control is not None:
            control.check(stage)
        elif caller_cancelled():
            raise SolveExecutionCancelled(stage)

    return control, check


def _run_native_trusted_producer(
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
    execution_control: SolveExecutionControl | None = None,
    cancelled: Callable[[], bool] | None = None,
    parent_deadline: float | None = None,
    known_failure: bool = False,
) -> NativeTrustedProducerRun | NativeTrustedProducerFailure:
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
    _check_parent_deadline(parent_deadline)
    control, checkpoint = _lifecycle_control(execution_control, cancelled, parent_deadline)
    root = _workspace_root(workspace)

    checkpoint("native_producer_attempt")
    caller_limited = control is not None and control.deadline <= control._now() + intent.wall_timeout_seconds
    try:
        attempt = run_native_trusted_attempt(
            root,
            producer_root=producer_root,
            intent=intent,
            attestation=attestation,
            artifact=artifact,
            broker_config=broker_config,
            cancelled=control.is_cancelled if control is not None else cancelled,
            parent_deadline=control.deadline if control is not None else None,
            monotonic=control._clock if control is not None else time.monotonic,
        )
    except NativeTrustedAttemptError as exc:
        if exc.code == "native_trusted_attempt_cancelled":
            raise SolveExecutionCancelled("native_producer_attempt") from exc
        checkpoint("native_producer_after_attempt_error")
        if exc.code == "native_trusted_attempt_wall_timeout":
            _raise_attempt_wall_timeout(control, caller_limited=caller_limited)
        raise NativeTrustedSchedulerError("native_trusted_scheduler_attempt_failed") from exc
    if known_failure and attempt.terminal_sha256 is not None and attempt.exit_code != 0:
        # Only the explicit outcome API records already-observed failure evidence. In
        # particular, a sticky active cancellation cannot authorize another production
        # stage, but need not discard a verified process-only cancellation terminal.
        try:
            return build_native_trusted_failure(
                root, intent=intent, attestation=attestation, artifact=artifact, attempt=attempt,
            )
        except NativeTrustedFailureError as exc:
            raise NativeTrustedSchedulerError("native_trusted_scheduler_failure_unverified") from exc
    checkpoint("native_producer_after_attempt")
    if attempt.reason == "native_trusted_attempt_wall_timeout":
        _raise_attempt_wall_timeout(control, caller_limited=caller_limited)
    _check_attempt(attempt)

    checkpoint("native_producer_receipt")
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
    checkpoint("native_producer_after_receipt")

    checkpoint("native_producer_output")
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
    checkpoint("native_producer_after_output")
    if output.execution_receipt_sha256 != receipt.receipt_sha256:
        raise NativeTrustedSchedulerError("native_trusted_scheduler_receipt_binding_mismatch")

    publication: NativeProducerBundleTransactionResult | None = None
    status = "prepared"
    if strategy is not None:
        checkpoint("native_producer_publication")
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
                execution_control=control,
                continuation_guard=checkpoint,
            )
        except (SolveExecutionCancelled, SolveExecutionBudgetExceeded):
            raise
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
        deadline_scope="caller_lifecycle" if control is not None else "native_attempt_only",
    )


def run_native_trusted_producer(
    workspace: str | Path, *, producer_root: str | Path, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
    broker_config: ProducerBrokerConfig, contract: AlgorithmProblemContract, groups: Sequence[BundleGroup],
    evaluator_kind: str, evaluator_fingerprint: str, runner_fingerprint: str,
    dependency_sha256: str, environment_sha256: str, strategy: Any | None = None,
    execution_control: SolveExecutionControl | None = None, cancelled: Callable[[], bool] | None = None,
    parent_deadline: float | None = None,
) -> NativeTrustedProducerRun:
    """Run the historical success-only receipt/output/publication entry point once."""
    return _run_native_trusted_producer(
        workspace, producer_root=producer_root, intent=intent, attestation=attestation,
        artifact=artifact, broker_config=broker_config, contract=contract, groups=groups,
        evaluator_kind=evaluator_kind, evaluator_fingerprint=evaluator_fingerprint,
        runner_fingerprint=runner_fingerprint, dependency_sha256=dependency_sha256,
        environment_sha256=environment_sha256, strategy=strategy, execution_control=execution_control,
        cancelled=cancelled, parent_deadline=parent_deadline, known_failure=False,
    )


def run_native_trusted_producer_outcome(
    workspace: str | Path, *, producer_root: str | Path, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
    broker_config: ProducerBrokerConfig, contract: AlgorithmProblemContract, groups: Sequence[BundleGroup],
    evaluator_kind: str, evaluator_fingerprint: str, runner_fingerprint: str,
    dependency_sha256: str, environment_sha256: str, strategy: Any | None = None,
    execution_control: SolveExecutionControl | None = None, cancelled: Callable[[], bool] | None = None,
    parent_deadline: float | None = None,
) -> NativeTrustedProducerRun | NativeTrustedProducerFailure:
    """Run once, returning verified process failure or the unchanged success result.

    Failure proof is read under the original live broker pins before success-only admission
    checks. No exception, missing terminal or cancellation callback is mapped to failure.
    """
    return _run_native_trusted_producer(
        workspace, producer_root=producer_root, intent=intent, attestation=attestation,
        artifact=artifact, broker_config=broker_config, contract=contract, groups=groups,
        evaluator_kind=evaluator_kind, evaluator_fingerprint=evaluator_fingerprint,
        runner_fingerprint=runner_fingerprint, dependency_sha256=dependency_sha256,
        environment_sha256=environment_sha256, strategy=strategy, execution_control=execution_control,
        cancelled=cancelled, parent_deadline=parent_deadline, known_failure=True,
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
    "run_native_trusted_producer_outcome",
]
