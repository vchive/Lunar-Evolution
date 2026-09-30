"""Provider-free seen/unseen frozen-memory transfer regression coverage."""

from __future__ import annotations

import hashlib

import pytest

from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot
from lunar_evolution.rsi_transfer_regression import (
    TransferObservation,
    TransferRegressionError,
    TransferRegressionSuite,
    TransferTask,
)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def snapshot(name: str, memory_id: str) -> MemorySnapshot:
    item = MemoryItem(
        memory_id=memory_id,
        problem_family="fixture",
        trigger="when fixture input",
        strategy="use bounded strategy",
        expected_result="pass",
        failure_boundary="fixture boundary",
        compatible_contracts=(digest("contract"),),
        compatible_solvers=("fixture",),
        verifier_outcome="pass",
        receipt_sha256=digest(name + ":receipt"),
        episode_id=name + ":episode",
    )
    return MemorySnapshot(name, None, (item,))


def tasks() -> tuple[TransferTask, ...]:
    return (
        TransferTask("seen-1", "family-a", "seen", "target-a", digest("seen-1")),
        TransferTask("unseen-1", "family-a", "unseen", "target-b", digest("unseen-1")),
        TransferTask("unseen-2", "family-b", "unseen", "target-c", digest("unseen-2")),
    )


def test_suite_compares_no_old_current_with_repeated_multi_target_holdout() -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")

    def runner(task, memory, repetition):
        if memory.snapshot_id == "rsi-empty-memory-v1":
            score = 0.2 if task.split == "seen" else 0.0
        elif memory.snapshot_id == "old":
            score = 0.5
        else:
            score = 0.8 if task.split == "unseen" else 0.7
        return TransferObservation(
            passed=score >= 0.5, score=score, cost=1 + repetition,
            accessed_task_ids=(task.task_id,), memory_ids_used=tuple(item.memory_id for item in memory.items),
        )

    report = TransferRegressionSuite().run(tasks(), old_memory=old, current_memory=current, runner=runner)

    assert report.promotion_eligible is True
    assert {summary.arm for summary in report.summaries} == {"no_memory", "old_memory", "current_memory"}
    assert all(len(summary.trials) == 6 for summary in report.summaries)
    assert report.by_arm["current_memory"].unseen_score > report.by_arm["no_memory"].unseen_score
    assert report.by_arm["current_memory"].unseen_score > report.by_arm["old_memory"].unseen_score
    assert report.contamination == ()
    assert report.promotion_evidence()["regression_passed"] is True
    assert len(report.holdout_receipt_sha256) == 64
    assert len(report.baseline_receipt_sha256) == 64
    assert len(report.report_sha256) == 64


def test_holdout_no_improvement_rejects_promotion() -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")

    def runner(task, memory, _repetition):
        return TransferObservation(
            passed=task.split == "seen", score=1.0 if task.split == "seen" else 0.0,
            memory_ids_used=tuple(item.memory_id for item in memory.items),
        )

    report = TransferRegressionSuite().run(tasks(), old_memory=old, current_memory=current, runner=runner)
    assert report.promotion_eligible is False
    assert "unseen_no_improvement" in report.rejection_reasons
    with pytest.raises(TransferRegressionError, match="promotion_rejected"):
        report.assert_promotable()


def test_contamination_is_visible_and_blocks_promotion() -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")

    def runner(task, memory, _repetition):
        return TransferObservation(
            passed=True, score=1.0,
            accessed_task_ids=(task.task_id, "hidden-task"),
            memory_ids_used=("foreign-memory",),
        )

    report = TransferRegressionSuite().run(tasks(), old_memory=old, current_memory=current, runner=runner)
    assert report.promotion_eligible is False
    assert "contamination_detected" in report.rejection_reasons
    assert any("unexpected_task:hidden-task" in reason for reason in report.contamination)
    assert any("unexpected_memory:foreign-memory" in reason for reason in report.contamination)


def test_manifest_rejects_cross_split_input_reuse() -> None:
    shared = digest("shared")
    manifest = (
        TransferTask("seen", "family", "seen", "target-a", shared),
        TransferTask("unseen-a", "family", "unseen", "target-b", shared),
        TransferTask("unseen-b", "family", "unseen", "target-c", digest("other")),
    )
    with pytest.raises(TransferRegressionError, match="split_contamination"):
        TransferRegressionSuite().run(
            manifest, old_memory=snapshot("old", "old-item"), current_memory=snapshot("current", "new-item"),
            runner=lambda *_args: TransferObservation(True, 1.0),
        )


def test_single_target_holdout_is_rejected() -> None:
    manifest = (
        TransferTask("seen", "family", "seen", "target-a", digest("seen")),
        TransferTask("unseen-a", "family", "unseen", "target-b", digest("u-a")),
        TransferTask("unseen-b", "family", "unseen", "target-b", digest("u-b")),
    )
    with pytest.raises(TransferRegressionError, match="holdout_targets_incomplete"):
        TransferRegressionSuite().run(
            manifest, old_memory=snapshot("old", "old-item"), current_memory=snapshot("current", "new-item"),
            runner=lambda *_args: TransferObservation(True, 1.0),
        )
