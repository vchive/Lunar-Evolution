"""Bind local Python publication to retained RSI admission evidence.

Existing-pin publication and recovery remain read-only with respect to controller state.
The active DRS entry pins on its owning thread. Publication mutation entries refuse
an already-established BRS worker scope before parsing caller material. The named
BRS worker entry remains a compatibility symbol with a fixed refusal until an owner
publication bridge is accepted. Read-only recovery remains available. No entry
launches a worker or grants production admission; original proof and complete
references remain required throughout publication.
"""

from __future__ import annotations

import re
import sqlite3
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .automatic_solve_lifecycle import SolveExecutionControl
from .evolution import PopulationStrategy
from .producer_bundle_admission import (
    ProducerBundleAdmissionItem,
    ProducerBundleAdmissionPlan,
    parse_producer_bundle_admission_plan,
)
from .producer_bundle_population import ProducerBundleDraft
from .producer_bundle_publication import (
    ProducerBundlePublicationJournal,
    parse_producer_bundle_publication_journal,
)
from .producer_bundle_recovery import (
    ProducerBundleRecoveryError,
    ProducerBundleRecoveryResult,
    resume_producer_bundle_publication,
)
from .producer_bundle_transaction import (
    NativeProducerBundleTransactionError,
    NativeProducerBundleTransactionResult,
    run_native_producer_bundle_publication_transaction,
)
from .rsi_controller import RSILearningController
from .rsi_learning import RSILearningError
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_python_admission import (
    parse_rsi_python_admission_references,
    validate_rsi_python_admission_reference_record,
    validate_rsi_python_admission_shapes,
)
from .rsi_store import RSILedger

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class RSIPythonPublicationError(NativeProducerBundleTransactionError):
    """Fixed-code refusal without paths, caller prose or worker output."""

    def __init__(self, code: str) -> None:
        super().__init__("rsi_python_publication_" + code)


def _refuse_active_brs_worker_publication(controller: object) -> None:
    """A live worker observation scope is never parent publication authority."""
    if (type(controller) is RSILearningController
            and getattr(controller._python_admission_brs_local, "active", None) is not None):
        raise RSIPythonPublicationError("brs_worker_publication_forbidden")


def _plan_snapshot(plan: ProducerBundleAdmissionPlan) -> ProducerBundleAdmissionPlan:
    try:
        if type(plan) is not ProducerBundleAdmissionPlan:
            raise TypeError("exact admission plan required")
        validate_rsi_python_admission_shapes(
            plan, dto_types=(ProducerBundleAdmissionPlan, ProducerBundleAdmissionItem),
        )
        return parse_producer_bundle_admission_plan(plan.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise RSIPythonPublicationError("plan_invalid") from exc


def _require_database(database: Path) -> None:
    # The read-only connector separately prevents CREATE if this observation becomes
    # stale before SQLite opens the database.
    if not stat.S_ISREG(database.lstat().st_mode):
        raise RSIPythonPublicationError("ledger_invalid")


@dataclass(frozen=True, slots=True)
class _AdmissionBinding:
    controller: RSILearningController
    ledger: RSILedger
    run_id: str
    episode_id: str
    references: dict[str, dict[str, Any]]
    expected_record_sha256: str
    database: Path
    workspace: Path
    native_plan: NativeRSIExecutionPlan
    prepared_journal: ProducerBundlePublicationJournal

    def revalidate(self, _stage: str) -> None:
        """Read under the caller's ownership; never acquire a controller mutation lock."""
        try:
            if (self.controller.ledger is not self.ledger
                    or self.ledger.database != self.database
                    or self.controller.producer_workspace is None
                    or self.controller.producer_workspace.expanduser().absolute() != self.workspace):
                raise RSIPythonPublicationError("controller_drift")
            _require_database(self.database)
            with self.ledger.read_only_observations():
                self.controller._validate_python_admission_references(
                    self.run_id, {"python_admission_refs": self.references},
                )
                reference = self.references[self.episode_id]
                retained = self.ledger.python_admission_record(
                    self.run_id, self.episode_id, self.prepared_journal.journal_id,
                    expected_record_sha256=self.expected_record_sha256,
                )
                validate_rsi_python_admission_reference_record(
                    reference, retained, run_id=self.run_id, episode_id=self.episode_id,
                )
        except RSIPythonPublicationError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
            raise RSIPythonPublicationError("evidence_invalid") from exc


def _capture_admission(
    controller: RSILearningController, run_id: str, episode_id: str,
    expected_record_sha256: str, plan: ProducerBundleAdmissionPlan,
) -> _AdmissionBinding:
    # Validate scalar identities before any ledger/filesystem observation or callback.
    if type(controller) is not RSILearningController:
        raise RSIPythonPublicationError("controller_invalid")
    if any(type(value) is not str or _ID.fullmatch(value) is None
           for value in (run_id, episode_id)):
        raise RSIPythonPublicationError("identity_invalid")
    if (type(expected_record_sha256) is not str or _SHA.fullmatch(expected_record_sha256) is None
            or expected_record_sha256 == "0" * 64):
        raise RSIPythonPublicationError("admission_record_sha256_invalid")
    if controller.ledger is None or controller.producer_workspace is None:
        raise RSIPythonPublicationError("controller_binding_missing")
    try:
        database = controller.ledger.database
        _require_database(database)
        with controller.ledger.read_only_observations():
            checkpoint = controller.ledger.controller_checkpoint(run_id)
        if checkpoint is None:
            raise RSIPythonPublicationError("reference_missing")
        references = parse_rsi_python_admission_references(
            checkpoint[1].get("python_admission_refs", {}),
        )
        reference = references.get(episode_id)
        if reference is None:
            raise RSIPythonPublicationError("reference_missing")
        if reference["record_sha256"] != expected_record_sha256:
            raise RSIPythonPublicationError("record_identity_mismatch")
        journal = parse_producer_bundle_publication_journal(reference["prepared_journal"])
        native_plan = NativeRSIExecutionPlan.from_dict(reference["native_plan"])
        if plan.digest() != journal.admission_sha256:
            raise RSIPythonPublicationError("plan_mismatch")
        binding = _AdmissionBinding(
            controller, controller.ledger, run_id, episode_id, references,
            expected_record_sha256, database, controller.producer_workspace.expanduser().absolute(),
            native_plan, journal,
        )
        binding.revalidate("rsi_python_publication_entry")
        return binding
    except RSIPythonPublicationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        raise RSIPythonPublicationError("evidence_invalid") from exc


def run_rsi_python_bundle_publication(
    controller: RSILearningController,
    run_id: str,
    episode_id: str,
    strategy: PopulationStrategy,
    drafts: Sequence[ProducerBundleDraft],
    admission_plan: ProducerBundleAdmissionPlan,
    *,
    expected_admission_record_sha256: str,
    execution_control: SolveExecutionControl | None = None,
    continuation_guard: Callable[[str], None] | None = None,
) -> NativeProducerBundleTransactionResult:
    """Require an exact already-pinned RSI admission before each publication boundary.

    The optional caller guard cannot disable the mandatory read-only evidence checks.
    A committed/unknown publication remains durable when later evidence refuses success.
    """
    _refuse_active_brs_worker_publication(controller)
    plan = _plan_snapshot(admission_plan)
    binding = _capture_admission(
        controller, run_id, episode_id, expected_admission_record_sha256, plan,
    )
    journal = binding.prepared_journal
    try:
        result = run_native_producer_bundle_publication_transaction(
            binding.workspace, strategy, drafts, plan,
            journal_id=journal.journal_id, run_id=journal.run_id,
            parent_task_id=journal.parent_task_id, task_id=journal.task_id,
            budget_sha256=journal.budget_sha256,
            native_execution_receipt_sha256=journal.native_execution_receipt_sha256,
            python_handoff_sha256=journal.python_handoff_sha256,
            python_handoff_file_pin=journal.python_handoff_file_pin,
            execution_control=execution_control, continuation_guard=continuation_guard,
            evidence_revalidator=binding.revalidate,
        )
        binding.revalidate("rsi_python_publication_return")
        return result
    except NativeProducerBundleTransactionError as exc:
        # The standalone transaction preserves fixed codes while wrapping callback
        # failures. Keep the composed public refusal type stable at every boundary.
        prefix = "rsi_python_publication_"
        if type(exc) is not RSIPythonPublicationError and exc.code.startswith(prefix):
            raise RSIPythonPublicationError(exc.code[len(prefix):]) from exc
        raise


def run_rsi_python_bundle_publication_for_active_flow(
    controller: RSILearningController,
    run_id: str,
    episode_id: str,
    strategy: PopulationStrategy,
    drafts: Sequence[ProducerBundleDraft],
    admission_plan: ProducerBundleAdmissionPlan,
    *,
    native_plan: NativeRSIExecutionPlan,
    prepared_journal: ProducerBundlePublicationJournal,
    expected_anchor_sha256: str,
    execution_control: SolveExecutionControl | None = None,
    continuation_guard: Callable[[str], None] | None = None,
) -> NativeProducerBundleTransactionResult:
    """Pin prepared evidence on the active DRS owner before admitting evaluation.

    A fresh controller dispatch supplies the original scoped checkpoint. This entry
    cannot acquire an owner lock, adopt a newer state or reconstruct a missing pin.
    """
    _refuse_active_brs_worker_publication(controller)
    if type(controller) is not RSILearningController:
        raise RSIPythonPublicationError("controller_invalid")
    if any(type(value) is not str or _ID.fullmatch(value) is None
           for value in (run_id, episode_id)):
        raise RSIPythonPublicationError("identity_invalid")
    plan = _plan_snapshot(admission_plan)
    try:
        native, journal, producer = controller._python_admission_inputs(
            native_plan, prepared_journal, expected_anchor_sha256,
        )
    except RSILearningError as exc:
        raise RSIPythonPublicationError("evidence_invalid") from exc
    identity = (run_id, producer.intent.journal_id, producer.parent_task_id, producer.task_id)
    if (producer.run_id != run_id
            or (native.run_id, native.journal_id, native.parent_task_id, native.task_id) != identity
            or (journal.run_id, journal.journal_id, journal.parent_task_id, journal.task_id) != identity
            or native.request.episode_id != episode_id):
        raise RSIPythonPublicationError("identity_mismatch")
    if (native.launch_id != producer.intent.launch_id
            or native.intent_sha256 != producer.intent_sha256
            or native.attestation_sha256 != producer.attestation_sha256
            or native.deadline_unix != producer.deadline_unix
            or native.evaluator_kind != producer.evaluator_kind
            or native.evaluator_fingerprint != producer.evaluator_fingerprint):
        raise RSIPythonPublicationError("identity_mismatch")
    if any(getattr(journal, field) != expected for field, expected in (
        ("contract_sha256", producer.contract_sha256),
        ("evaluator_kind", producer.evaluator_kind),
        ("evaluator_fingerprint", producer.evaluator_fingerprint),
        ("runner_fingerprint", producer.intent.runner_fingerprint),
        ("dependency_sha256", producer.dependency_sha256),
        ("environment_sha256", producer.environment_sha256),
    )):
        raise RSIPythonPublicationError("plan_mismatch")
    if plan.digest() != journal.admission_sha256:
        raise RSIPythonPublicationError("plan_mismatch")
    ledger = controller.ledger
    workspace = controller.producer_workspace.expanduser().absolute()
    if ledger is None:
        raise RSIPythonPublicationError("controller_binding_missing")
    database = ledger.database
    admitted: _AdmissionBinding | None = None

    def revalidate(stage: str) -> None:
        try:
            if (controller.ledger is not ledger or ledger.database != database
                    or controller.producer_workspace is None
                    or controller.producer_workspace.expanduser().absolute() != workspace):
                raise RSIPythonPublicationError("controller_drift")
            _require_database(database)
            with ledger.read_only_observations():
                state, _head = controller._python_admission_active_flow(run_id, episode_id)
                if native.request.to_dict() != state["intents"][episode_id]["request"]:
                    raise RSIPythonPublicationError("request_mismatch")
                controller._validate_producer_checkpoint(run_id, state)
                # Recheck the scoped head after the proof/file observations.
                controller._python_admission_active_flow(run_id, episode_id)
            if admitted is not None:
                admitted.revalidate(stage)
                with ledger.read_only_observations():
                    controller._python_admission_active_flow(run_id, episode_id)
        except RSIPythonPublicationError:
            raise
        except RSILearningError as exc:
            raise RSIPythonPublicationError("owner_context_invalid") from exc
        except (AttributeError, KeyError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
            raise RSIPythonPublicationError("evidence_invalid") from exc

    def pin_prepared(observed: ProducerBundlePublicationJournal) -> None:
        nonlocal admitted
        if admitted is not None:
            raise RSIPythonPublicationError("prepared_observer_replayed")
        if (type(observed) is not ProducerBundlePublicationJournal
                or observed.to_dict() != journal.to_dict()):
            raise RSIPythonPublicationError("prepared_journal_mismatch")
        revalidate("rsi_python_publication_before_pin")
        try:
            retained = controller._pin_python_admission_for_active_flow(
                run_id, episode_id, native_plan=native, prepared_journal=journal,
                expected_anchor_sha256=expected_anchor_sha256,
            )
        except RSILearningError as exc:
            raise RSIPythonPublicationError("admission_pin_invalid") from exc
        admitted = _capture_admission(controller, run_id, episode_id, retained.record_sha256, plan)
        revalidate("rsi_python_publication_after_pin")

    revalidate("rsi_python_publication_owner_entry")
    try:
        result = run_native_producer_bundle_publication_transaction(
            workspace, strategy, drafts, plan,
            journal_id=journal.journal_id, run_id=journal.run_id,
            parent_task_id=journal.parent_task_id, task_id=journal.task_id,
            budget_sha256=journal.budget_sha256,
            native_execution_receipt_sha256=journal.native_execution_receipt_sha256,
            python_handoff_sha256=journal.python_handoff_sha256,
            python_handoff_file_pin=journal.python_handoff_file_pin,
            execution_control=execution_control, continuation_guard=continuation_guard,
            evidence_revalidator=revalidate, prepared_observer=pin_prepared,
        )
        if admitted is None:
            raise RSIPythonPublicationError("admission_missing")
        revalidate("rsi_python_publication_owner_return")
        return result
    except NativeProducerBundleTransactionError as exc:
        prefix = "rsi_python_publication_"
        if type(exc) is not RSIPythonPublicationError and exc.code.startswith(prefix):
            raise RSIPythonPublicationError(exc.code[len(prefix):]) from exc
        raise


def run_rsi_python_bundle_publication_for_active_brs_worker(
    controller: RSILearningController,
    run_id: str,
    episode_id: str,
    strategy: PopulationStrategy,
    drafts: Sequence[ProducerBundleDraft],
    admission_plan: ProducerBundleAdmissionPlan,
    *,
    native_plan: NativeRSIExecutionPlan,
    prepared_journal: ProducerBundlePublicationJournal,
    expected_anchor_sha256: str,
    execution_control: SolveExecutionControl | None = None,
    continuation_guard: Callable[[str], None] | None = None,
) -> NativeProducerBundleTransactionResult:
    """Refuse worker publication until an owner-side prepared bridge is accepted.

    Keep the original call signature/import symbol, but neither inspect caller
    objects nor enter transaction, evaluator, ready/ACK, ledger or workspace work.
    Prepared admission remains available through its separate existing bridge.
    """
    raise RSIPythonPublicationError("brs_worker_publication_forbidden")


def resume_rsi_python_bundle_publication(
    controller: RSILearningController,
    run_id: str,
    episode_id: str,
    admission_plan: ProducerBundleAdmissionPlan,
    *,
    expected_admission_record_sha256: str,
) -> ProducerBundleRecoveryResult:
    """Inspect original immutable publication authority without repairing or retrying it."""
    plan = _plan_snapshot(admission_plan)
    binding = _capture_admission(
        controller, run_id, episode_id, expected_admission_record_sha256, plan,
    )
    try:
        result = resume_producer_bundle_publication(binding.workspace, plan, binding.prepared_journal)
        binding.revalidate("rsi_python_publication_recovery_return")
        return result
    except ProducerBundleRecoveryError as exc:
        prefix = "producer_bundle_recovery_"
        code = exc.code[len(prefix):] if exc.code.startswith(prefix) else "evidence_invalid"
        raise RSIPythonPublicationError("recovery_" + code) from exc


__all__ = [
    "RSIPythonPublicationError",
    "resume_rsi_python_bundle_publication",
    "run_rsi_python_bundle_publication",
    "run_rsi_python_bundle_publication_for_active_brs_worker",
    "run_rsi_python_bundle_publication_for_active_flow",
]
