"""Result-backed recovery for one retained shared transfer panel."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .rsi_learning import RSILearningError
from .rsi_shared_transfer import validate_transfers
from .rsi_stage_accounting import DurableSolverAccounting, DurableStageAccounting, digest
from .rsi_transfer import FrozenMemoryTransferBenchmark, FrozenTransferResult, _read


def reconcile_transfer_panel(
    run: Any,
    *,
    benchmark: FrozenMemoryTransferBenchmark,
    comparison_id: str,
    tasks,
    snapshot,
    expected_record_sha256: str,
    expected_intent_sha256: str,
    expected_receipt_sha256: str,
) -> FrozenTransferResult:
    """Adopt a fully retained panel without launching or reserving any work."""
    if not isinstance(benchmark, FrozenMemoryTransferBenchmark):
        raise RSILearningError("rsi_transfer_benchmark_invalid")
    if any(type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
           for value in (expected_record_sha256, expected_intent_sha256, expected_receipt_sha256)):
        raise RSILearningError("rsi_transfer_reconcile_pin_invalid")
    tasks = tuple(tasks)
    binding = {"run_id": run.run_id, "ledger_path": str(run.ledger.database)}
    identity = benchmark.comparison_identity(comparison_id=comparison_id, tasks=tasks,
                                              snapshot=snapshot, accounting_binding=binding)
    with run.ledger.controller_lock(run.run_id):
        run._load()
        current_version, current_state = run.version, run.state
        audit = {
            "checkpoint_sha256": expected_record_sha256,
            "intent_sha256": expected_intent_sha256,
            "receipt_sha256": expected_receipt_sha256,
        }
        previous_audit = current_state.get("transfer_reconciliations", {}).get(comparison_id)
        if current_version != expected_record_sha256 and previous_audit != audit:
            raise RSILearningError("rsi_transfer_reconcile_record_conflict")
        if current_state.get("status") != "completed":
            raise RSILearningError("rsi_transfer_learning_run_incomplete")
        panels = current_state.get("transfer_panels")
        entry = panels.get(comparison_id) if isinstance(panels, dict) else None
        if not isinstance(entry, dict) or set(entry) != {"identity", "root", "stages", "solvers", "receipt_sha256"}:
            raise RSILearningError("rsi_transfer_reconcile_panel_missing")
        if entry["identity"] != identity:
            raise RSILearningError("rsi_transfer_reconcile_identity_changed")
        root = Path(entry["root"])
        expected_root = benchmark.workspace_root / "comparisons" / comparison_id
        if root != expected_root or not root.is_absolute() or root.is_symlink():
            raise RSILearningError("rsi_transfer_reconcile_root_invalid")
        transfer_rows = [row for row in entry["stages"]["invocations"] if row["stage"] == "transfer"]
        if len(transfer_rows) != 1:
            raise RSILearningError("rsi_transfer_reconcile_intent_missing")
        transfer_row = transfer_rows[0]
        if transfer_row["intent_sha256"] != expected_intent_sha256:
            raise RSILearningError("rsi_transfer_reconcile_intent_conflict")
        receipt_path = root / "comparison.json"
        if not receipt_path.is_file() or receipt_path.is_symlink():
            return FrozenTransferResult(comparison_id, "unknown", "unresolved", None, None, len(tasks))
        payload = _read(receipt_path)
        if payload.get("receipt_sha256") != expected_receipt_sha256:
            raise RSILearningError("rsi_transfer_reconcile_receipt_conflict")
        if payload.get("intent_sha256") != digest(identity):
            raise RSILearningError("rsi_transfer_reconcile_identity_changed")
        # A repeated call after the completion checkpoint is a read-only idempotent open.
        settled = entry["receipt_sha256"]
        if settled is not None and settled != expected_receipt_sha256:
            raise RSILearningError("rsi_transfer_reconcile_receipt_conflict")
        if settled is not None:
            if transfer_row["evidence"] != {"receipt_sha256": settled}:
                raise RSILearningError("rsi_transfer_reconcile_checkpoint_invalid")
        elif transfer_row["evidence"] not in (None, {"receipt_sha256": expected_receipt_sha256}):
            raise RSILearningError("rsi_transfer_reconcile_checkpoint_invalid")
        if (any(row["stage"] != "transfer" and row["evidence"] is None
                for row in entry["stages"]["invocations"])
                or any(row["result_sha256"] is None for row in entry["solvers"]["invocations"])):
            raise RSILearningError("rsi_transfer_reconcile_inner_work_pending")
        # Validate the complete retained panel through the normal read-only validator.  The
        # temporary copy supplies only the missing transfer evidence and never touches the run.
        validate_transfers(run)
        prospective = deepcopy(current_state)
        prospective_entry = prospective["transfer_panels"][comparison_id]
        stages = prospective_entry["stages"]
        solvers = prospective_entry["solvers"]
        budget_state = prospective["budget_state"]
        temp_transfer = next(row for row in stages["invocations"] if row["stage"] == "transfer")
        temp_transfer["evidence"] = {"receipt_sha256": expected_receipt_sha256}
        prospective_entry["receipt_sha256"] = expected_receipt_sha256
        if settled is None:
            prospective.setdefault("transfer_reconciliations", {})[comparison_id] = audit
        validate_transfers(SimpleNamespace(state=prospective, run_id=run.run_id, ledger=run.ledger))
        stage_accounting = DurableStageAccounting(stages, budget_state, lambda: None)
        solver_accounting = DurableSolverAccounting(solvers, budget_state, lambda: None)
        result = benchmark._resume(root, identity, tasks, snapshot,
                                   accounting=stage_accounting, solver_accounting=solver_accounting)
        if (result.receipt_sha256 != expected_receipt_sha256 or _read(receipt_path) != payload
                or benchmark.comparison_identity(comparison_id=comparison_id, tasks=tasks,
                    snapshot=snapshot, accounting_binding=binding) != identity):
            raise RSILearningError("rsi_transfer_reconcile_receipt_conflict")
        if settled is None:
            transfer_row["evidence"] = {"receipt_sha256": expected_receipt_sha256}
            entry["receipt_sha256"] = expected_receipt_sha256
            current_state.setdefault("transfer_reconciliations", {})[comparison_id] = audit
            run._save()
        return result


__all__ = ["reconcile_transfer_panel"]
