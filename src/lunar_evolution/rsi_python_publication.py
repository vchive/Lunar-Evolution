"""Publish or inspect local Python material through an existing RSI admission pin.

This evidence-only composition never registers an admission, launches a worker, adopts
controller state or grants production admission. The original controller proof and complete
checkpoint reference remain required throughout the standalone publication transaction.
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
]
