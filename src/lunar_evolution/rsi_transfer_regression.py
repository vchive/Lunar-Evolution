"""Provider-free frozen-memory transfer regression suite.

The suite compares three immutable memory arms (empty, previous, and candidate) over a
repeated, split task manifest.  It does not execute a solver or evaluator itself: callers
provide a deterministic fixture runner that returns :class:`TransferObservation`.  The
result is an auditable report suitable for the memory-governance promotion gate.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import EMPTY_MEMORY_SNAPSHOT, MemorySnapshot, RSILearningError

TransferSplit = Literal["seen", "unseen"]
TransferArm = Literal["no_memory", "old_memory", "current_memory"]


def _digest(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise TransferRegressionError(f"rsi_transfer_regression_{name}_invalid")
    return value


def _text(value: object, name: str, maximum: int = 256) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value or len(value.encode("utf-8")) > maximum:
        raise TransferRegressionError(f"rsi_transfer_regression_{name}_invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=128 * 1024)
    except Exception as exc:  # pragma: no cover - canonical_json already has focused tests
        raise TransferRegressionError("rsi_transfer_regression_record_invalid") from exc


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class TransferRegressionError(RSILearningError):
    """Fail-closed error raised for an invalid regression manifest or report."""


@dataclass(frozen=True)
class TransferTask:
    """One task in the frozen transfer manifest.

    ``input_sha256`` binds the task material without exposing hidden holdout bytes to the
    controller.  ``target_id`` makes multi-target holdout coverage explicit.
    """

    task_id: str
    task_family: str
    split: TransferSplit
    target_id: str
    input_sha256: str

    def __post_init__(self) -> None:
        _text(self.task_id, "task_id")
        _text(self.task_family, "task_family")
        _text(self.target_id, "target_id")
        _digest(self.input_sha256, "input_sha256")
        if self.split not in {"seen", "unseen"}:
            raise TransferRegressionError("rsi_transfer_regression_split_invalid")

    def to_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "task_family": self.task_family,
            "split": self.split,
            "target_id": self.target_id,
            "input_sha256": self.input_sha256,
        }


@dataclass(frozen=True)
class TransferObservation:
    """One provider-free evaluator observation returned by a fixture runner."""

    passed: bool
    score: float
    cost: float = 0.0
    accessed_task_ids: tuple[str, ...] = ()
    memory_ids_used: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.passed) is not bool:
            raise TransferRegressionError("rsi_transfer_regression_passed_invalid")
        if type(self.score) not in {int, float} or isinstance(self.score, bool) or not math.isfinite(self.score) or not 0 <= self.score <= 1:
            raise TransferRegressionError("rsi_transfer_regression_score_invalid")
        if type(self.cost) not in {int, float} or isinstance(self.cost, bool) or not math.isfinite(self.cost) or self.cost < 0:
            raise TransferRegressionError("rsi_transfer_regression_cost_invalid")
        if type(self.accessed_task_ids) is not tuple or any(type(item) is not str for item in self.accessed_task_ids):
            raise TransferRegressionError("rsi_transfer_regression_access_log_invalid")
        if len(set(self.accessed_task_ids)) != len(self.accessed_task_ids):
            raise TransferRegressionError("rsi_transfer_regression_access_log_invalid")
        if type(self.memory_ids_used) is not tuple or any(type(item) is not str for item in self.memory_ids_used):
            raise TransferRegressionError("rsi_transfer_regression_memory_access_invalid")
        if len(set(self.memory_ids_used)) != len(self.memory_ids_used):
            raise TransferRegressionError("rsi_transfer_regression_memory_access_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": float(self.score),
            "cost": float(self.cost),
            "accessed_task_ids": list(self.accessed_task_ids),
            "memory_ids_used": list(self.memory_ids_used),
        }


@dataclass(frozen=True)
class TransferTrial:
    arm: TransferArm
    task: TransferTask
    repetition: int
    observation: TransferObservation

    def __post_init__(self) -> None:
        if self.arm not in {"no_memory", "old_memory", "current_memory"}:
            raise TransferRegressionError("rsi_transfer_regression_arm_invalid")
        if type(self.repetition) is not int or self.repetition < 0:
            raise TransferRegressionError("rsi_transfer_regression_repetition_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "task": self.task.to_dict(),
            "repetition": self.repetition,
            "observation": self.observation.to_dict(),
        }


@dataclass(frozen=True)
class TransferArmSummary:
    arm: TransferArm
    trials: tuple[TransferTrial, ...]
    seen_score: float
    unseen_score: float
    seen_pass_rate: float
    unseen_pass_rate: float
    seen_variance: float
    unseen_variance: float
    score_variance: float
    mean_score: float
    pass_rate: float
    mean_cost: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "trial_count": len(self.trials),
            "seen_score": self.seen_score,
            "unseen_score": self.unseen_score,
            "seen_pass_rate": self.seen_pass_rate,
            "unseen_pass_rate": self.unseen_pass_rate,
            "seen_variance": self.seen_variance,
            "unseen_variance": self.unseen_variance,
            "score_variance": self.score_variance,
            "mean_score": self.mean_score,
            "pass_rate": self.pass_rate,
            "mean_cost": self.mean_cost,
        }


@dataclass(frozen=True)
class RegressionPolicy:
    """Promotion thresholds for the narrow provider-free suite."""

    repetitions: int = 2
    min_unseen_targets: int = 2
    min_task_families: int = 2
    require_unseen_improvement: bool = True
    max_unseen_regression: float = 0.0
    max_seen_regression: float = 0.0
    min_unseen_pass_rate: float = 1.0
    max_unseen_pass_rate_regression: float = 0.0
    max_seen_pass_rate_regression: float = 0.0

    def __post_init__(self) -> None:
        if type(self.repetitions) is not int or self.repetitions < 2:
            raise TransferRegressionError("rsi_transfer_regression_repetitions_invalid")
        if type(self.min_unseen_targets) is not int or self.min_unseen_targets < 2:
            raise TransferRegressionError("rsi_transfer_regression_target_coverage_invalid")
        if type(self.min_task_families) is not int or self.min_task_families < 1:
            raise TransferRegressionError("rsi_transfer_regression_family_coverage_invalid")
        if type(self.require_unseen_improvement) is not bool:
            raise TransferRegressionError("rsi_transfer_regression_policy_invalid")
        for value, name in ((self.max_unseen_regression, "max_unseen_regression"), (self.max_seen_regression, "max_seen_regression")):
            if type(value) not in {int, float} or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
                raise TransferRegressionError(f"rsi_transfer_regression_{name}_invalid")
        for name in ("min_unseen_pass_rate", "max_unseen_pass_rate_regression", "max_seen_pass_rate_regression"):
            value = getattr(self, name)
            if type(value) not in {int, float} or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
                raise TransferRegressionError(f"rsi_transfer_regression_{name}_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "repetitions": self.repetitions,
            "min_unseen_targets": self.min_unseen_targets,
            "min_task_families": self.min_task_families,
            "require_unseen_improvement": self.require_unseen_improvement,
            "max_unseen_regression": float(self.max_unseen_regression),
            "max_seen_regression": float(self.max_seen_regression),
            "min_unseen_pass_rate": float(self.min_unseen_pass_rate),
            "max_unseen_pass_rate_regression": float(self.max_unseen_pass_rate_regression),
            "max_seen_pass_rate_regression": float(self.max_seen_pass_rate_regression),
        }


@dataclass(frozen=True)
class TransferRegressionReport:
    tasks: tuple[TransferTask, ...]
    repetitions: int
    summaries: tuple[TransferArmSummary, ...]
    contamination: tuple[str, ...]
    promotion_eligible: bool
    rejection_reasons: tuple[str, ...]
    holdout_receipt_sha256: str
    baseline_receipt_sha256: str
    report_sha256: str
    old_memory_sha256: str = ""
    current_memory_sha256: str = ""
    policy: RegressionPolicy | None = None

    @property
    def by_arm(self) -> Mapping[str, TransferArmSummary]:
        return {summary.arm: summary for summary in self.summaries}

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "protocol": "lunar-rsi-transfer-regression-v1",
            "schema_version": "3" if self.policy is not None else "2",
            "tasks": [task.to_dict() for task in self.tasks],
            "repetitions": self.repetitions,
            "summaries": [summary.to_dict() for summary in self.summaries],
            "contamination": list(self.contamination),
            "promotion_eligible": self.promotion_eligible,
            "rejection_reasons": list(self.rejection_reasons),
            "holdout_receipt_sha256": self.holdout_receipt_sha256,
            "baseline_receipt_sha256": self.baseline_receipt_sha256,
            "report_sha256": self.report_sha256,
            "old_memory_sha256": self.old_memory_sha256,
            "current_memory_sha256": self.current_memory_sha256,
        }
        if self.policy is not None:
            payload["policy"] = self.policy.to_dict()
        return payload

    def assert_promotable(self) -> None:
        if not self.promotion_eligible:
            raise TransferRegressionError("rsi_transfer_regression_promotion_rejected")
        self.validate_policy_evidence()

    def validate_policy_evidence(self) -> None:
        """Require the report's own immutable policy, pass gates and receipt bindings."""
        if not isinstance(self.policy, RegressionPolicy):
            raise TransferRegressionError("rsi_transfer_regression_policy_evidence_missing")
        _digest(self.old_memory_sha256, "memory_sha256")
        _digest(self.current_memory_sha256, "memory_sha256")
        TransferRegressionSuite._validate_tasks(self.tasks, self.policy)
        if self.repetitions != self.policy.repetitions:
            raise TransferRegressionError("rsi_transfer_regression_policy_evidence_drift")
        by_arm = self.by_arm
        if len(self.summaries) != 3 or set(by_arm) != {"no_memory", "old_memory", "current_memory"}:
            raise TransferRegressionError("rsi_transfer_regression_policy_evidence_drift")
        task_map = {task.task_id: task for task in self.tasks}
        expected_trials = {(task.task_id, repetition) for task in self.tasks for repetition in range(self.repetitions)}
        inferred_contamination: set[str] = set()
        for arm, summary in by_arm.items():
            if (
                len(summary.trials) != len(expected_trials)
                or {(trial.task.task_id, trial.repetition) for trial in summary.trials} != expected_trials
                or any(trial.arm != arm or task_map.get(trial.task.task_id) != trial.task for trial in summary.trials)
                or TransferRegressionSuite._summary(arm, summary.trials).to_dict() != summary.to_dict()
            ):
                raise TransferRegressionError("rsi_transfer_regression_policy_evidence_drift")
            for trial in summary.trials:
                inferred_contamination.update(
                    f"{arm}:{trial.task.task_id}:unexpected_task:{task_id}"
                    for task_id in set(trial.observation.accessed_task_ids) - {trial.task.task_id}
                )
                # The empty arm's allowed memory IDs are independently known. Other arms only
                # retain their snapshot digests here; their material is checked by the runner.
                if arm == "no_memory":
                    inferred_contamination.update(
                        f"{arm}:{trial.task.task_id}:unexpected_memory:{memory_id}"
                        for memory_id in trial.observation.memory_ids_used
                    )
        if not inferred_contamination.issubset(self.contamination):
            raise TransferRegressionError("rsi_transfer_regression_policy_evidence_drift")
        reasons = _rejection_reasons(by_arm, self.policy, self.contamination)
        if reasons != self.rejection_reasons or self.promotion_eligible is not (not reasons):
            raise TransferRegressionError("rsi_transfer_regression_policy_evidence_drift")
        if (
            self.holdout_receipt_sha256 != _arm_receipt(
                by_arm["current_memory"], self.current_memory_sha256, self.tasks, self.policy,
            )
            or self.baseline_receipt_sha256 != _arm_receipt(
                by_arm["no_memory"], EMPTY_MEMORY_SNAPSHOT.digest(), self.tasks, self.policy,
            )
        ):
            raise TransferRegressionError("rsi_transfer_regression_receipt_drift")

    def promotion_evidence(self) -> dict[str, Any]:
        """Return fields accepted by ``MemoryGovernanceStore.transition``."""
        if self.promotion_eligible:
            self.validate_policy_evidence()
        return {
            "holdout_receipt_sha256": self.holdout_receipt_sha256,
            "baseline_receipt_sha256": self.baseline_receipt_sha256,
            "regression_passed": self.promotion_eligible,
        }


def _arm_receipt(
    summary: TransferArmSummary,
    memory_snapshot_sha256: str,
    tasks: Sequence[TransferTask],
    policy: RegressionPolicy,
) -> str:
    """Bind the evaluated inputs, thresholds, immutable arm and observations."""
    return _hash({
        "arm": summary.arm,
        "manifest": [task.to_dict() for task in tasks],
        "policy": policy.to_dict(),
        "memory_snapshot_sha256": _digest(memory_snapshot_sha256, "memory_sha256"),
        "summary": summary.to_dict(),
        "trials_sha256": _hash([trial.to_dict() for trial in summary.trials]),
    })


def _rejection_reasons(
    by_arm: Mapping[str, TransferArmSummary], policy: RegressionPolicy, contamination: Sequence[str],
) -> tuple[str, ...]:
    baseline, old, current = by_arm["no_memory"], by_arm["old_memory"], by_arm["current_memory"]
    reasons: list[str] = []
    if contamination:
        reasons.append("contamination_detected")
    if current.unseen_score < baseline.unseen_score - policy.max_unseen_regression:
        reasons.append("unseen_regression_vs_no_memory")
    if current.unseen_score < old.unseen_score - policy.max_unseen_regression:
        reasons.append("unseen_regression_vs_old_memory")
    if current.seen_score < baseline.seen_score - policy.max_seen_regression:
        reasons.append("seen_regression_vs_no_memory")
    if current.seen_score < old.seen_score - policy.max_seen_regression:
        reasons.append("seen_regression_vs_old_memory")
    if policy.require_unseen_improvement and current.unseen_score - baseline.unseen_score <= policy.max_unseen_regression:
        reasons.append("unseen_no_improvement")
    if current.unseen_score - old.unseen_score < -policy.max_unseen_regression:
        reasons.append("current_regressed_vs_old_memory")
    if current.unseen_pass_rate < policy.min_unseen_pass_rate:
        reasons.append("unseen_pass_rate_below_minimum")
    for split in ("seen", "unseen"):
        tolerance = getattr(policy, f"max_{split}_pass_rate_regression")
        actual = getattr(current, f"{split}_pass_rate")
        for comparison, name in ((baseline, "no_memory"), (old, "old_memory")):
            if actual < getattr(comparison, f"{split}_pass_rate") - tolerance:
                reasons.append(f"{split}_pass_rate_regression_vs_{name}")
    return tuple(reasons)


Runner = Callable[[TransferTask, MemorySnapshot, int], TransferObservation]


class TransferRegressionSuite:
    """Run a deterministic no/old/current memory comparison over a task split."""

    def __init__(self, *, policy: RegressionPolicy | None = None) -> None:
        if policy is not None and not isinstance(policy, RegressionPolicy):
            raise TransferRegressionError("rsi_transfer_regression_policy_invalid")
        self.policy = policy or RegressionPolicy()

    @staticmethod
    def _validate_tasks(tasks: Sequence[TransferTask], policy: RegressionPolicy) -> tuple[TransferTask, ...]:
        if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes)):
            raise TransferRegressionError("rsi_transfer_regression_tasks_invalid")
        parsed = tuple(tasks)
        if not parsed or any(not isinstance(task, TransferTask) for task in parsed):
            raise TransferRegressionError("rsi_transfer_regression_tasks_invalid")
        if len({task.task_id for task in parsed}) != len(parsed):
            raise TransferRegressionError("rsi_transfer_regression_duplicate_task")
        by_input: dict[str, str] = {}
        for task in parsed:
            previous = by_input.get(task.input_sha256)
            if previous is not None and previous != task.split:
                raise TransferRegressionError("rsi_transfer_regression_split_contamination")
            by_input[task.input_sha256] = task.split
        seen = [task for task in parsed if task.split == "seen"]
        unseen = [task for task in parsed if task.split == "unseen"]
        if not seen or not unseen:
            raise TransferRegressionError("rsi_transfer_regression_split_incomplete")
        if len({task.target_id for task in unseen}) < policy.min_unseen_targets:
            raise TransferRegressionError("rsi_transfer_regression_holdout_targets_incomplete")
        if len({task.task_family for task in parsed}) < policy.min_task_families:
            raise TransferRegressionError("rsi_transfer_regression_family_coverage_incomplete")
        return parsed

    @staticmethod
    def _normalise_observation(value: object) -> TransferObservation:
        if isinstance(value, TransferObservation):
            return value
        if type(value) is bool:
            return TransferObservation(value, 1.0 if value else 0.0)
        if type(value) in {int, float} and not isinstance(value, bool):
            return TransferObservation(float(value) >= 1.0, float(value))
        if isinstance(value, Mapping):
            allowed = {"passed", "score", "cost", "accessed_task_ids", "memory_ids_used"}
            if set(value) - allowed or "passed" not in value or "score" not in value:
                raise TransferRegressionError("rsi_transfer_regression_observation_invalid")
            try:
                return TransferObservation(
                    value["passed"], value["score"], value.get("cost", 0.0),
                    tuple(value.get("accessed_task_ids", ())), tuple(value.get("memory_ids_used", ())),
                )
            except (TypeError, ValueError) as exc:
                raise TransferRegressionError("rsi_transfer_regression_observation_invalid") from exc
        raise TransferRegressionError("rsi_transfer_regression_observation_invalid")

    @staticmethod
    def _summary(arm: TransferArm, trials: tuple[TransferTrial, ...]) -> TransferArmSummary:
        by_split = {split: [trial for trial in trials if trial.task.split == split] for split in ("seen", "unseen")}
        if not by_split["seen"] or not by_split["unseen"]:
            raise TransferRegressionError("rsi_transfer_regression_split_incomplete")
        score = lambda rows: sum(float(row.observation.score) for row in rows) / len(rows)
        passed = lambda rows: sum(row.observation.passed for row in rows) / len(rows)
        def variance(rows):
            mean = score(rows)
            return sum((float(row.observation.score) - mean) ** 2 for row in rows) / len(rows)
        return TransferArmSummary(
            arm, trials, score(by_split["seen"]), score(by_split["unseen"]),
            passed(by_split["seen"]), passed(by_split["unseen"]), variance(by_split["seen"]),
            variance(by_split["unseen"]), variance(trials), score(trials), passed(trials),
            sum(float(row.observation.cost) for row in trials) / len(trials),
        )

    def run(
        self,
        tasks: Sequence[TransferTask],
        *,
        old_memory: MemorySnapshot,
        current_memory: MemorySnapshot,
        runner: Runner,
    ) -> TransferRegressionReport:
        manifest = self._validate_tasks(tasks, self.policy)
        if not isinstance(old_memory, MemorySnapshot) or not isinstance(current_memory, MemorySnapshot):
            raise TransferRegressionError("rsi_transfer_regression_memory_invalid")
        if not callable(runner):
            raise TransferRegressionError("rsi_transfer_regression_runner_invalid")
        arms: tuple[tuple[TransferArm, MemorySnapshot], ...] = (
            ("no_memory", EMPTY_MEMORY_SNAPSHOT), ("old_memory", old_memory), ("current_memory", current_memory),
        )
        all_trials: list[TransferTrial] = []
        contamination: list[str] = []
        for arm, snapshot in arms:
            allowed_memory_ids = {item.memory_id for item in snapshot.items}
            for repetition in range(self.policy.repetitions):
                for task in manifest:
                    observation = self._normalise_observation(runner(task, snapshot, repetition))
                    unexpected_tasks = sorted(set(observation.accessed_task_ids) - {task.task_id})
                    unexpected_memory = sorted(set(observation.memory_ids_used) - allowed_memory_ids)
                    contamination.extend(
                        f"{arm}:{task.task_id}:unexpected_task:{item}" for item in unexpected_tasks
                    )
                    contamination.extend(
                        f"{arm}:{task.task_id}:unexpected_memory:{item}" for item in unexpected_memory
                    )
                    all_trials.append(TransferTrial(arm, task, repetition, observation))
        summaries = tuple(self._summary(arm, tuple(trial for trial in all_trials if trial.arm == arm)) for arm, _snapshot in arms)
        by_arm = {summary.arm: summary for summary in summaries}
        reasons = _rejection_reasons(by_arm, self.policy, contamination)
        holdout_receipt = _arm_receipt(by_arm["current_memory"], current_memory.digest(), manifest, self.policy)
        baseline_receipt = _arm_receipt(by_arm["no_memory"], EMPTY_MEMORY_SNAPSHOT.digest(), manifest, self.policy)
        payload = {
            "tasks": [task.to_dict() for task in manifest], "repetitions": self.policy.repetitions,
            "summaries": [summary.to_dict() for summary in summaries], "contamination": contamination,
            "promotion_eligible": not reasons, "rejection_reasons": list(reasons),
            "holdout_receipt_sha256": holdout_receipt, "baseline_receipt_sha256": baseline_receipt,
            "old_memory_sha256": old_memory.digest(), "current_memory_sha256": current_memory.digest(),
            "policy": self.policy.to_dict(),
        }
        report_digest = _hash(payload)
        return TransferRegressionReport(
            manifest, self.policy.repetitions, summaries, tuple(contamination), not reasons,
            tuple(reasons), holdout_receipt, baseline_receipt, report_digest,
            old_memory.digest(), current_memory.digest(), self.policy,
        )

    def evaluate(
        self,
        tasks: Sequence[TransferTask],
        *,
        old_memory: MemorySnapshot,
        current_memory: MemorySnapshot,
        runner: Runner,
    ) -> TransferRegressionReport:
        """Alias for callers that name a regression pass an evaluation."""
        return self.run(tasks, old_memory=old_memory, current_memory=current_memory, runner=runner)


__all__ = [
    "RegressionPolicy", "TransferArmSummary", "TransferObservation", "TransferRegressionError",
    "TransferRegressionReport", "TransferRegressionSuite", "TransferTask", "TransferTrial",
]
