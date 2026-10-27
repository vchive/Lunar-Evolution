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

import json
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, NoReturn

from .algorithm import AlgorithmProblemContract
from .automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from .native_bootstrap import NativeBootstrapArtifact
from .native_fixed_live_sink import FixedPythonLiveSinkRequest
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
from .producer_bundle_publication import ProducerBundlePublicationJournal
from .producer_bundle_transaction import (
    NativeProducerBundleTransactionResult,
    run_native_producer_bundle_publication_transaction,
)
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import ProducerExecutionReceipt, parse_producer_execution_receipt
from .python_producer_admission_handoff import (
    PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME,
    PythonProducerAdmissionHandoff,
    PythonProducerAdmissionHandoffFilePin,
    PythonProducerAdmissionHandoffSidecar,
    parse_python_producer_admission_handoff_file_pin,
    read_python_producer_admission_handoff_pinned,
)


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


@dataclass(frozen=True, slots=True)
class _NativeTrustedPythonProducerPreparation:
    """Original execution evidence only; no owner/publication authority."""

    run: NativeTrustedProducerRun
    handoff: PythonProducerAdmissionHandoffSidecar


def _prepublication_evidence(receipt: ProducerExecutionReceipt, output: NativeTrustedOutputPreparation) -> bytes:
    # Only fresh lower-boundary DTOs enter this private path. Include the complete
    # nested payload: frozen dataclasses alone do not freeze maps or source files.
    if type(receipt) is not ProducerExecutionReceipt or type(output) is not NativeTrustedOutputPreparation:
        raise ValueError("original preparation DTO required")
    raw = json.dumps([asdict(receipt), asdict(output)], ensure_ascii=False,
                     sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    parse_producer_execution_receipt(json.loads(raw)[0])
    return raw


def _prepublication_control_pin(control: SolveExecutionControl | None) -> tuple | None:
    if control is None:
        return None
    if not isinstance(control, SolveExecutionControl):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_control_invalid")
    times = (control.started_at, control.deadline, control.timeout_seconds)
    try:
        valid = all(type(value) in (float, int) and math.isfinite(value) for value in times)
    except OverflowError:
        valid = False
    if not valid or type(control._cancellation_callbacks) is not list:
        raise NativeTrustedSchedulerError("native_trusted_scheduler_python_prepublication_control_changed")
    return (*times, id(control._clock), id(control._observe_stage), id(control._lock),
            tuple(id(callback) for callback in control._cancellation_callbacks))


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
    python_handoff_after_execution: Callable[
        [ProducerExecutionReceipt, NativeTrustedOutputPreparation], PythonProducerAdmissionHandoffSidecar,
    ] | None = None,
    prepared_observer: Callable[[ProducerBundlePublicationJournal], None] | None = None,
    evidence_revalidator: Callable[[str], None] | None = None,
    producer_multi_episode_publication: bool = False,
    lineage_owner: Any | None = None,
    _python_prepublication: bool = False,
    live_modules_sink: FixedPythonLiveSinkRequest | None = None,
) -> NativeTrustedProducerRun | NativeTrustedProducerFailure | _NativeTrustedPythonProducerPreparation:
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
    python_join = any(value is not None for value in (
        python_handoff_after_execution, prepared_observer, evidence_revalidator,
    ))
    if type(_python_prepublication) is not bool:
        raise NativeTrustedSchedulerError("native_trusted_scheduler_python_prepublication_invalid")
    if _python_prepublication and (
        strategy is not None or prepared_observer is not None or known_failure is not False
        or producer_multi_episode_publication is not False or lineage_owner is not None
        or not callable(python_handoff_after_execution) or not callable(evidence_revalidator)
    ):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_python_prepublication_invalid")
    if not _python_prepublication and python_join and (
        strategy is None or not all(callable(value) for value in (
            python_handoff_after_execution, prepared_observer, evidence_revalidator,
        ))
    ):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_python_join_invalid")
    if (type(producer_multi_episode_publication) is not bool
            or producer_multi_episode_publication != (lineage_owner is not None)
            or (producer_multi_episode_publication and not python_join)):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_multi_episode_configuration_invalid")
    if producer_multi_episode_publication:
        from .rsi_publication_lineage import RSIPublicationLineage

        if type(lineage_owner) is not RSIPublicationLineage:
            raise NativeTrustedSchedulerError("native_trusted_scheduler_multi_episode_configuration_invalid")
    _check_parent_deadline(parent_deadline)
    original_control_pin = _prepublication_control_pin(execution_control) if _python_prepublication else None
    control, checkpoint = _lifecycle_control(execution_control, cancelled, parent_deadline)
    if _python_prepublication:
        composed_control_pin = _prepublication_control_pin(control)
        raw_checkpoint = checkpoint

        def checkpoint(stage: str) -> None:
            def unchanged() -> None:
                if (_prepublication_control_pin(execution_control) != original_control_pin
                        or _prepublication_control_pin(control) != composed_control_pin):
                    raise NativeTrustedSchedulerError(
                        "native_trusted_scheduler_python_prepublication_control_changed",
                    )

            unchanged()
            raw_checkpoint(stage)
            unchanged()

    root = _workspace_root(workspace)
    if lineage_owner is not None:
        lineage_owner.validate_launch(workspace=root, intent=intent)
    if _python_prepublication:
        checkpoint("native_producer_prepublication_entry")
        evidence_revalidator("native_producer_prepublication_entry")

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
            **({"live_modules_sink": live_modules_sink} if live_modules_sink is not None else {}),
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

    publication_options: dict[str, Any] = {}
    if python_join:
        checkpoint("native_producer_python_handoff")
        try:
            original_evidence = _prepublication_evidence(receipt, output) if _python_prepublication else None
            original_receipt_sha256 = receipt.receipt_sha256
            original_admission_sha256 = output.admission_plan.digest()
            supplied = python_handoff_after_execution(receipt, output)
            # The callback supplies the independently retained creation pin. Never
            # discover a current pin from a filename or reconstruct late observations.
            if (type(supplied) is not PythonProducerAdmissionHandoffSidecar
                    or type(supplied.handoff) is not PythonProducerAdmissionHandoff
                    or type(supplied.file_pin) is not PythonProducerAdmissionHandoffFilePin):
                raise ValueError("original pinned handoff required")
            pin = parse_python_producer_admission_handoff_file_pin(supplied.file_pin)
            if (pin.run_id, pin.journal_id, pin.parent_task_id, pin.task_id) != (
                intent.run_id, intent.journal_id, intent.parent_task_id, intent.task_id,
            ):
                raise ValueError("handoff identity mismatch")
            checkpoint("native_producer_after_python_handoff")
            if (receipt.receipt_sha256 != original_receipt_sha256
                    or output.execution_receipt_sha256 != original_receipt_sha256
                    or output.admission_plan.digest() != original_admission_sha256
                    or (_python_prepublication
                        and _prepublication_evidence(receipt, output) != original_evidence)):
                raise ValueError("original execution evidence changed")
            retained = read_python_producer_admission_handoff_pinned(
                root / "evolution" / "producer-batches" / intent.journal_id
                / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME,
                expected_file_pin=pin,
            )
            handoff = retained.handoff
            if (retained != supplied or handoff.state != "prepared"
                    or handoff.native_execution_receipt_sha256 != original_receipt_sha256
                    or handoff.admission_plan_sha256 != original_admission_sha256
                    or handoff.launch_intent_sha256 != intent.digest()
                    or handoff.attestation_sha256 != attestation.digest()
                    or handoff.contract_sha256 != contract.digest()
                    or handoff.evaluator_sha256 != evaluator_fingerprint
                    or handoff.runner_sha256 != runner_fingerprint
                    or handoff.dependency_sha256 != dependency_sha256
                    or handoff.environment_sha256 != environment_sha256):
                raise ValueError("handoff execution binding mismatch")
            if _python_prepublication:
                # Hooks cannot refresh the original creator pin, execution or budget.
                # Re-read after the last hook, before returning any usable evidence.
                checkpoint("native_producer_prepublication_return")
                evidence_revalidator("native_producer_prepublication_return")
                checkpoint("native_producer_after_prepublication_return")
                reread = read_python_producer_admission_handoff_pinned(
                    root / "evolution" / "producer-batches" / intent.journal_id
                    / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME,
                    expected_file_pin=pin,
                )
                checkpoint("native_producer_prepublication_final")
                # A stage observer may touch the file without changing its DTO.
                # The last external continuation hook must precede the last pin read.
                final_read = read_python_producer_admission_handoff_pinned(
                    root / "evolution" / "producer-batches" / intent.journal_id
                    / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME,
                    expected_file_pin=pin,
                )
                if (reread != retained or reread != supplied
                        or final_read != reread
                        or receipt.receipt_sha256 != original_receipt_sha256
                        or output.execution_receipt_sha256 != original_receipt_sha256
                        or output.admission_plan.digest() != original_admission_sha256
                        or _prepublication_evidence(receipt, output) != original_evidence):
                    raise ValueError("original preparation evidence changed")
                return _NativeTrustedPythonProducerPreparation(
                    run=NativeTrustedProducerRun(
                        attempt=attempt, receipt=receipt, output=output,
                        deadline_scope=("caller_lifecycle" if control is not None else "native_attempt_only"),
                    ),
                    handoff=reread,
                )
            publication_options = {
                "python_handoff_sha256": handoff.handoff_sha256,
                "python_handoff_file_pin": pin,
                "prepared_observer": prepared_observer,
                "evidence_revalidator": evidence_revalidator,
            }
            if lineage_owner is not None:
                publication_options["producer_multi_episode_publication"] = True
                publication_options["lineage_owner"] = lineage_owner
        except (SolveExecutionCancelled, SolveExecutionBudgetExceeded):
            raise
        except Exception as exc:
            raise NativeTrustedSchedulerError(
                "native_trusted_scheduler_python_handoff_invalid",
            ) from exc

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
                **publication_options,
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


def _prepare_native_trusted_python_producer(
    workspace: str | Path, *, producer_root: str | Path, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
    broker_config: ProducerBrokerConfig, contract: AlgorithmProblemContract, groups: Sequence[BundleGroup],
    evaluator_kind: str, evaluator_fingerprint: str, runner_fingerprint: str,
    dependency_sha256: str, environment_sha256: str,
    python_handoff_after_execution: Callable[
        [ProducerExecutionReceipt, NativeTrustedOutputPreparation], PythonProducerAdmissionHandoffSidecar,
    ],
    evidence_revalidator: Callable[[str], None],
    execution_control: SolveExecutionControl | None = None, cancelled: Callable[[], bool] | None = None,
    parent_deadline: float | None = None,
    live_modules_sink: FixedPythonLiveSinkRequest | None = None,
) -> _NativeTrustedPythonProducerPreparation:
    """Stop after original receipt/output/handoff; never evaluate or publish.

    This private producer-only seam does not admit a BRS worker to the public RSI
    provider. The future owner must independently validate request and live scope.
    No prepared journal, admission pin, lineage owner or transaction is created.
    """
    return _run_native_trusted_producer(
        workspace, producer_root=producer_root, intent=intent, attestation=attestation,
        artifact=artifact, broker_config=broker_config, contract=contract, groups=groups,
        evaluator_kind=evaluator_kind, evaluator_fingerprint=evaluator_fingerprint,
        runner_fingerprint=runner_fingerprint, dependency_sha256=dependency_sha256,
        environment_sha256=environment_sha256, execution_control=execution_control,
        cancelled=cancelled, parent_deadline=parent_deadline,
        python_handoff_after_execution=python_handoff_after_execution,
        evidence_revalidator=evidence_revalidator, _python_prepublication=True,
        **({"live_modules_sink": live_modules_sink} if live_modules_sink is not None else {}),
    )


def run_native_trusted_producer(
    workspace: str | Path, *, producer_root: str | Path, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
    broker_config: ProducerBrokerConfig, contract: AlgorithmProblemContract, groups: Sequence[BundleGroup],
    evaluator_kind: str, evaluator_fingerprint: str, runner_fingerprint: str,
    dependency_sha256: str, environment_sha256: str, strategy: Any | None = None,
    execution_control: SolveExecutionControl | None = None, cancelled: Callable[[], bool] | None = None,
    parent_deadline: float | None = None,
    python_handoff_after_execution: Callable[
        [ProducerExecutionReceipt, NativeTrustedOutputPreparation], PythonProducerAdmissionHandoffSidecar,
    ] | None = None,
    prepared_observer: Callable[[ProducerBundlePublicationJournal], None] | None = None,
    evidence_revalidator: Callable[[str], None] | None = None,
    producer_multi_episode_publication: bool = False,
    lineage_owner: Any | None = None,
    live_modules_sink: FixedPythonLiveSinkRequest | None = None,
) -> NativeTrustedProducerRun:
    """Run the historical success-only receipt/output/publication entry point once."""
    return _run_native_trusted_producer(
        workspace, producer_root=producer_root, intent=intent, attestation=attestation,
        artifact=artifact, broker_config=broker_config, contract=contract, groups=groups,
        evaluator_kind=evaluator_kind, evaluator_fingerprint=evaluator_fingerprint,
        runner_fingerprint=runner_fingerprint, dependency_sha256=dependency_sha256,
        environment_sha256=environment_sha256, strategy=strategy, execution_control=execution_control,
        cancelled=cancelled, parent_deadline=parent_deadline, known_failure=False,
        python_handoff_after_execution=python_handoff_after_execution,
        prepared_observer=prepared_observer, evidence_revalidator=evidence_revalidator,
        producer_multi_episode_publication=producer_multi_episode_publication,
        lineage_owner=lineage_owner,
        **({"live_modules_sink": live_modules_sink} if live_modules_sink is not None else {}),
    )


def run_native_trusted_producer_outcome(
    workspace: str | Path, *, producer_root: str | Path, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
    broker_config: ProducerBrokerConfig, contract: AlgorithmProblemContract, groups: Sequence[BundleGroup],
    evaluator_kind: str, evaluator_fingerprint: str, runner_fingerprint: str,
    dependency_sha256: str, environment_sha256: str, strategy: Any | None = None,
    execution_control: SolveExecutionControl | None = None, cancelled: Callable[[], bool] | None = None,
    parent_deadline: float | None = None,
    python_handoff_after_execution: Callable[
        [ProducerExecutionReceipt, NativeTrustedOutputPreparation], PythonProducerAdmissionHandoffSidecar,
    ] | None = None,
    prepared_observer: Callable[[ProducerBundlePublicationJournal], None] | None = None,
    evidence_revalidator: Callable[[str], None] | None = None,
    producer_multi_episode_publication: bool = False,
    lineage_owner: Any | None = None,
    live_modules_sink: FixedPythonLiveSinkRequest | None = None,
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
        python_handoff_after_execution=python_handoff_after_execution,
        prepared_observer=prepared_observer, evidence_revalidator=evidence_revalidator,
        producer_multi_episode_publication=producer_multi_episode_publication,
        lineage_owner=lineage_owner,
        **({"live_modules_sink": live_modules_sink} if live_modules_sink is not None else {}),
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
