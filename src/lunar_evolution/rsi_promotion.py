"""Read-only authority over host-pinned native practice and holdout panels."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import EMPTY_MEMORY_SNAPSHOT, MemorySnapshot, RSILearningError
from .rsi_memory_governance import MemoryPromotionRecord, PromotionGate
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

    def fingerprint(self) -> str:
        return _digest({
            "protocol": "lunar-rsi-native-promotion-v1", "benchmark": self.benchmark.fingerprint(),
            "practice": [task.to_dict() for task in self.practice_tasks],
            "holdout": [task.to_dict() for task in self.holdout_tasks],
            "snapshot": self.snapshot.to_dict(), "practice_id": self.practice_comparison_id,
            "holdout_id": self.holdout_comparison_id,
            "practice_budget": self.practice_budget, "holdout_budget": self.holdout_budget,
        })

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
        if _read(root / "intent.json") != identity:
            raise RSILearningError("rsi_promotion_panel_identity_mismatch")
        before = _read(root / "comparison.json")
        result = self.benchmark._resume(root, identity, tasks, self.snapshot)
        after = _read(root / "comparison.json")
        if before != after or result.receipt_sha256 != after["receipt_sha256"]:
            raise RSILearningError("rsi_promotion_receipt_changed")
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
