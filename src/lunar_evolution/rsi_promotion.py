"""Read-only authority over host-pinned native practice and holdout panels."""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_budget import RSIRunBudget
from .rsi_learning import EMPTY_MEMORY_SNAPSHOT, MemorySnapshot, RSILearningError
from .rsi_memory_governance import MemoryPromotionRecord, PromotionGate
from .rsi_stage_accounting import (
    DurableSolverAccounting,
    DurableStageAccounting,
    validate_solver_state,
    validate_stage_state,
)
from .rsi_store import RSILedger
from .rsi_transfer import FrozenMemoryTransferBenchmark, NativeTransferTask, _read


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=2 * 1024 * 1024)).hexdigest()


@dataclass(frozen=True)
class NativePromotionEvidence:
    """Host configuration, never configuration reconstructed from an untrusted proof.

    This first promotion path compares exactly one candidate against empty memory. Hosts own
    the task split; disjoint IDs do not by themselves prove a statistically independent holdout.
    Raw scores stay in native receipts; the gate uses counts of strictly improved tasks so score
    precision and minimize/maximize orientation are preserved by the transfer evaluator.
    """

    benchmark: FrozenMemoryTransferBenchmark
    practice_tasks: tuple[NativeTransferTask, ...]
    holdout_tasks: tuple[NativeTransferTask, ...]
    snapshot: MemorySnapshot
    practice_comparison_id: str
    holdout_comparison_id: str
    practice_budget: tuple[tuple[str, Any], ...] | None = None
    holdout_budget: tuple[tuple[str, Any], ...] | None = None
    shared_ledger: RSILedger | None = None
    shared_run_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.benchmark, FrozenMemoryTransferBenchmark):
            raise RSILearningError("rsi_promotion_benchmark_invalid")
        for panel in (self.practice_tasks, self.holdout_tasks):
            if (type(panel) is not tuple or not 1 <= len(panel) <= 16
                    or any(not isinstance(task, NativeTransferTask) for task in panel)
                    or len({task.task_id for task in panel}) != len(panel)):
                raise RSILearningError("rsi_promotion_panels_invalid")
        if {t.task_id for t in self.practice_tasks} & {t.task_id for t in self.holdout_tasks}:
            raise RSILearningError("rsi_promotion_panels_overlap")
        for comparison_id in (self.practice_comparison_id, self.holdout_comparison_id):
            if type(comparison_id) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", comparison_id) is None:
                raise RSILearningError("rsi_promotion_comparison_id_invalid")
        if self.practice_comparison_id == self.holdout_comparison_id:
            raise RSILearningError("rsi_promotion_panels_overlap")
        if not isinstance(self.snapshot, MemorySnapshot) or len(self.snapshot.items) != 1:
            raise RSILearningError("rsi_promotion_snapshot_invalid")
        for budget in (self.practice_budget, self.holdout_budget):
            if budget is not None and (type(budget) is not tuple or len(dict(budget)) != len(budget)):
                raise RSILearningError("rsi_promotion_budget_invalid")
        if (self.shared_ledger is None) != (self.shared_run_id is None):
            raise RSILearningError("rsi_promotion_shared_binding_invalid")
        if self.shared_run_id is not None and (
            type(self.shared_run_id) is not str
            or not self.shared_run_id.strip()
            or any(char in self.shared_run_id for char in "\x00\r\n")
        ):
            raise RSILearningError("rsi_promotion_shared_binding_invalid")
        if self.shared_ledger is not None and not isinstance(self.shared_ledger, RSILedger):
            raise RSILearningError("rsi_promotion_shared_binding_invalid")
        if self.shared_ledger is not None and (self.practice_budget is not None or self.holdout_budget is not None):
            raise RSILearningError("rsi_promotion_shared_budget_conflict")

    def fingerprint(self) -> str:
        payload = {
            "protocol": "lunar-rsi-native-promotion-v1", "benchmark": self.benchmark.fingerprint(),
            "practice": [task.to_dict() for task in self.practice_tasks],
            "holdout": [task.to_dict() for task in self.holdout_tasks],
            "snapshot": self.snapshot.to_dict(), "practice_id": self.practice_comparison_id,
            "holdout_id": self.holdout_comparison_id,
            "practice_budget": self.practice_budget, "holdout_budget": self.holdout_budget,
        }
        # Preserve the historical standalone fingerprint.  Shared durable binding is an
        # explicit extension and must not invalidate existing standalone governance records.
        if self.shared_ledger is not None:
            payload["shared_run_id"] = self.shared_run_id
            payload["shared_ledger"] = str(self.shared_ledger.database)
        return _digest(payload)

    def _shared_state(self, comparison_id: str, identity: dict[str, Any]):
        if self.shared_ledger is None or self.shared_run_id is None:
            return None
        history = self.shared_ledger.controller_checkpoint_history(self.shared_run_id)
        if not history:
            raise RSILearningError("rsi_promotion_shared_checkpoint_missing")
        from .rsi_recovery import DurableLearningRun
        from .rsi_shared_transfer import validate_transfers

        state = history[-1][1]
        retained_run = SimpleNamespace(
            state=state, run_id=self.shared_run_id, ledger=self.shared_ledger, version=history[-1][0],
        )
        try:
            # These methods only inspect retained records; no controller/backend is built.
            DurableLearningRun._check_checkpoint_history(retained_run)
            for _version, checkpoint in history:
                config = checkpoint.get("config")
                if not isinstance(config, dict) or config.get("enable_transfer_accounting") is not True:
                    raise RSILearningError("rsi_promotion_shared_checkpoint_invalid")
                RSIRunBudget.load(checkpoint.get("budget_state")).assert_matches(config.get("budget"))
        except (KeyError, TypeError, RSILearningError) as exc:
            raise RSILearningError("rsi_promotion_shared_checkpoint_invalid") from exc
        if state.get("status") != "completed":
            raise RSILearningError("rsi_promotion_shared_run_incomplete")
        panels = state.get("transfer_panels")
        entry = panels.get(comparison_id) if isinstance(panels, dict) else None
        if not isinstance(entry, dict) or set(entry) != {"identity", "root", "stages", "solvers", "receipt_sha256"}:
            raise RSILearningError("rsi_promotion_shared_panel_missing")
        expected_binding = {"run_id": self.shared_run_id, "ledger_path": str(self.shared_ledger.database)}
        if identity.get("accounting_binding") != expected_binding or entry["identity"] != identity:
            raise RSILearningError("rsi_promotion_shared_panel_identity_mismatch")
        if type(entry["root"]) is not str:
            raise RSILearningError("rsi_promotion_shared_panel_root_invalid")
        root = Path(entry["root"])
        if not root.is_absolute() or root.is_symlink():
            raise RSILearningError("rsi_promotion_shared_panel_root_invalid")
        if str(root) != str(self.benchmark.workspace_root / "comparisons" / comparison_id):
            raise RSILearningError("rsi_promotion_shared_panel_root_mismatch")
        budget_state = state.get("budget_state")
        try:
            budget = RSIRunBudget.load(budget_state)
            budget.assert_matches(state.get("config", {}).get("budget"))
            stages = entry["stages"]
            solvers = entry["solvers"]
            validate_stage_state(stages)
            validate_solver_state(solvers)
        except RSILearningError as exc:
            raise RSILearningError("rsi_promotion_shared_budget_invalid") from exc
        # The durable budget is authoritative only when every retained controller and
        # transfer reservation is represented by its matching counter. This catches a
        # checkpoint that is internally well formed but has had work counters rolled back.
        try:
            global_counts = DurableLearningRun._check_external_stages(retained_run)
            episodes = state.get("episodes", {})
            if (not isinstance(episodes, dict) or any(
                not isinstance(value, dict) or type(value.get("budget_reserved")) is not bool
                or not isinstance(value.get("running_episode"), dict)
                or not isinstance(value.get("verifier_invocations"), list)
                for value in episodes.values()
            )):
                raise RSILearningError("rsi_promotion_shared_budget_invalid")
            episode_solver = sum(
                1 for value in episodes.values()
                if isinstance(value, dict) and value.get("budget_reserved") is True
            )
            episode_practice = sum(
                1 for value in episodes.values()
                if isinstance(value, dict) and value.get("budget_reserved") is True
                and isinstance(value.get("running_episode"), dict)
                and value["running_episode"].get("episode_kind") == "practice"
            )
            episode_unknown = sum(
                1 for value in episodes.values()
                if isinstance(value, dict) and value.get("reconciliation") is not None
            )
            episode_verifier = sum(
                len(value.get("verifier_invocations", []))
                for value in episodes.values() if isinstance(value, dict)
                and isinstance(value.get("verifier_invocations", []), list)
            )
            panels = state.get("transfer_panels", {})
            if not isinstance(panels, dict):
                raise RSILearningError("rsi_promotion_shared_budget_invalid")
            # Reuse the shared transfer validator for every retained panel. This validates
            # identity, roots, intents, receipts and per-panel stage/solver ownership,
            # while remaining read-only and never constructing a gateway/backend.
            panel_counts = validate_transfers(retained_run)
            consumed = budget.state["consumed"]
            expected = {
                "solver_invocations": episode_solver + panel_counts["solver_invocations"],
                "practice_episodes": episode_practice,
                "unknown_retries": episode_unknown,
                "evaluator_invocations": global_counts["evaluator"] + panel_counts["evaluator"],
                "verifier_invocations": episode_verifier + global_counts["verifier"] + panel_counts["verifier"],
                "transfer_invocations": global_counts["transfer"] + panel_counts["transfer"],
            }
            if any(consumed[name] != value for name, value in expected.items()):
                raise RSILearningError("rsi_promotion_shared_budget_invalid")
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            if isinstance(exc, RSILearningError) and str(exc) == "rsi_promotion_shared_budget_invalid":
                raise
            raise RSILearningError("rsi_promotion_shared_budget_invalid") from exc
        before_budget = deepcopy(budget.state)
        before_stages = deepcopy(stages)
        before_solvers = deepcopy(solvers)
        accounting = DurableStageAccounting(stages, budget.state, lambda: None)
        solver_accounting = DurableSolverAccounting(solvers, budget.state, lambda: None)
        return (root, accounting, solver_accounting, entry, before_budget, before_stages, before_solvers)

    def _panel(self, comparison_id, tasks, budget):
        root = self.benchmark.workspace_root / "comparisons" / comparison_id
        # Direct retained validation has no path to compare() or a gateway launch, even if
        # an intent/receipt disappears between the existence check and the bounded read.
        if not (root / "intent.json").is_file() or not (root / "comparison.json").is_file():
            raise RSILearningError("rsi_promotion_receipt_missing")
        identity = {
            "protocol": "lunar-rsi-native-transfer-v1", "comparison_id": comparison_id,
            "benchmark_fingerprint": self.benchmark.fingerprint(),
            "tasks": [task.to_dict() for task in tasks], "snapshot": self.snapshot.to_dict(),
            "baseline": EMPTY_MEMORY_SNAPSHOT.to_dict(),
        }
        if budget is not None:
            identity["stage_budget"] = dict(budget)
        if self.shared_ledger is not None:
            identity["accounting_binding"] = {
                "run_id": self.shared_run_id,
                "ledger_path": str(self.shared_ledger.database),
            }
        if _read(root / "intent.json") != identity:
            raise RSILearningError("rsi_promotion_panel_identity_mismatch")
        shared = self._shared_state(comparison_id, identity)
        before = _read(root / "comparison.json")
        if shared is None:
            result = self.benchmark._resume(root, identity, tasks, self.snapshot)
        else:
            shared_root, accounting, solver_accounting, entry, before_budget, before_stages, before_solvers = shared
            if shared_root != root or entry["root"] != str(root):
                raise RSILearningError("rsi_promotion_shared_panel_root_mismatch")
            result = self.benchmark._resume(
                root, identity, tasks, self.snapshot, accounting=accounting,
                solver_accounting=solver_accounting,
            )
            if (accounting.budget_state != before_budget or accounting.state != before_stages
                    or solver_accounting.state != before_solvers):
                raise RSILearningError("rsi_promotion_shared_validation_mutated")
        after = _read(root / "comparison.json")
        if before != after or result.receipt_sha256 != after["receipt_sha256"]:
            raise RSILearningError("rsi_promotion_receipt_changed")
        if shared is not None and shared[3]["receipt_sha256"] != after["receipt_sha256"]:
            raise RSILearningError("rsi_promotion_shared_receipt_mismatch")
        if (result.status != "completed" or result.baseline_verified != len(tasks)
                or result.frozen_verified != len(tasks)):
            raise RSILearningError("rsi_promotion_panel_unresolved")
        return after

    def validate_retained(self, record: MemoryPromotionRecord | None = None) -> dict[str, Any]:
        """Reopen actual native/verifier evidence and optionally bind a candidate authority."""
        if record is not None:
            source = record.authority
            memory = self.snapshot.items[0]
            if (source.memory_id != memory.memory_id or source.content_sha256 != _digest(memory.to_dict())
                    or source.parent_snapshot_sha256 != EMPTY_MEMORY_SNAPSHOT.digest()):
                raise RSILearningError("rsi_promotion_candidate_mismatch")
            compatibility = source.compatibility
            if compatibility.solver_id != "native_population":
                raise RSILearningError("rsi_promotion_solver_mismatch")
            if self.snapshot.parent_snapshot_sha256 != EMPTY_MEMORY_SNAPSHOT.digest():
                raise RSILearningError("rsi_promotion_empty_parent_required")
            for task in (*self.practice_tasks, *self.holdout_tasks):
                pins = task.to_dict()
                if any(pins[name] != getattr(compatibility, name) for name in (
                    "contract_sha256", "evaluator_sha256", "environment_sha256",
                )):
                    raise RSILearningError("rsi_promotion_compatibility_mismatch")
        practice = self._panel(self.practice_comparison_id, self.practice_tasks, self.practice_budget)
        holdout = self._panel(self.holdout_comparison_id, self.holdout_tasks, self.holdout_budget)
        for label, panel in (("practice", practice), ("holdout", holdout)):
            if any(row["outcome"]["effect"] not in {"improved", "unchanged"} for row in panel["rows"]):
                raise RSILearningError(f"rsi_promotion_{label}_regression")
        if not any(row["outcome"]["effect"] == "improved" for row in holdout["rows"]):
            raise RSILearningError("rsi_promotion_holdout_not_improved")
        return {"service_fingerprint": self.fingerprint(), "snapshot_sha256": self.snapshot.digest(),
                "practice": practice, "holdout": holdout}

    @staticmethod
    def derive_gate(record: MemoryPromotionRecord, retained: dict[str, Any]) -> PromotionGate:
        practice, holdout = retained["practice"]["rows"], retained["holdout"]["rows"]
        receipt = lambda row, arm: row[arm]["verifier"]["receipt_sha256"]
        return PromotionGate(
            record.authority.compatibility.digest(), record.authority.parent_snapshot_sha256,
            receipt(practice[0], "baseline"), receipt(practice[0], "frozen"),
            receipt(holdout[0], "baseline"), receipt(holdout[0], "frozen"),
            0, sum(row["outcome"]["effect"] == "improved" for row in practice),
            0, sum(row["outcome"]["effect"] == "improved" for row in holdout),
            tuple(dict.fromkeys((record.authority.source_receipt_sha256,
                                 *(receipt(row, "frozen") for row in practice)))),
            tuple(receipt(row, "frozen") for row in holdout),
        )


__all__ = ["NativePromotionEvidence"]
