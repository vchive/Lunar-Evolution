"""Provider-free seen/unseen frozen-memory transfer regression coverage."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot
from lunar_evolution.rsi_transfer_regression import (
    RegressionPolicy,
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


def test_high_score_cannot_replace_failing_holdout_pass_outcome() -> None:
    report = TransferRegressionSuite().run(
        tasks(), old_memory=snapshot("old", "old-item"), current_memory=snapshot("current", "new-item"),
        runner=lambda _task, memory, _repeat: TransferObservation(
            False, 0.9 if memory.snapshot_id == "current" else 0.2,
        ),
    )
    assert report.by_arm["current_memory"].unseen_pass_rate == 0.0
    assert report.promotion_eligible is False
    assert "unseen_pass_rate_below_minimum" in report.rejection_reasons
    with pytest.raises(TransferRegressionError, match="promotion_rejected"):
        report.assert_promotable()


def test_explicit_noise_policy_is_bounded_and_preserved_in_report() -> None:
    def runner(task, memory, repetition):
        current = memory.snapshot_id == "current"
        passed = not (current and task.task_id == "unseen-1" and repetition == 0)
        return TransferObservation(passed, 0.9 if current else 0.5)

    memories = {"old_memory": snapshot("old", "old-item"), "current_memory": snapshot("current", "new-item")}
    strict = TransferRegressionSuite().run(tasks(), runner=runner, **memories)
    assert strict.promotion_eligible is False
    assert "unseen_pass_rate_regression_vs_old_memory" in strict.rejection_reasons

    policy = RegressionPolicy(min_unseen_pass_rate=0.75, max_unseen_pass_rate_regression=0.25)
    report = TransferRegressionSuite(policy=policy).run(tasks(), runner=runner, **memories)
    assert report.promotion_eligible is True
    assert report.to_dict()["schema_version"] == "3"
    assert report.to_dict()["policy"] == policy.to_dict()
    report.assert_promotable()


def test_seen_pass_regression_blocks_promotion_despite_higher_scores() -> None:
    memories = {"old_memory": snapshot("old", "old-item"), "current_memory": snapshot("current", "new-item")}

    def runner(task, memory, _repeat):
        current = memory.snapshot_id == "current"
        return TransferObservation(not (current and task.split == "seen"), 0.9 if current else 0.5)

    strict = TransferRegressionSuite().run(tasks(), runner=runner, **memories)
    assert strict.promotion_eligible is False
    assert "seen_pass_rate_regression_vs_no_memory" in strict.rejection_reasons
    assert "seen_pass_rate_regression_vs_old_memory" in strict.rejection_reasons
    explicit = TransferRegressionSuite(policy=RegressionPolicy(max_seen_pass_rate_regression=1.0)).run(
        tasks(), runner=runner, **memories,
    )
    assert explicit.promotion_eligible is True
    explicit.assert_promotable()


@pytest.mark.parametrize("name", [
    "min_unseen_pass_rate", "max_unseen_pass_rate_regression", "max_seen_pass_rate_regression",
    "max_unseen_regression", "max_seen_regression",
])
@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), True, "0.5"])
def test_pass_policy_rejects_invalid_or_unbounded_threshold(name: str, value: object) -> None:
    with pytest.raises(TransferRegressionError, match=name + "_invalid"):
        RegressionPolicy(**{name: value})


def test_receipts_bind_task_inputs_and_policy_even_when_scores_match() -> None:
    memories = {"old_memory": snapshot("old", "old-item"), "current_memory": snapshot("current", "new-item")}
    runner = lambda _task, memory, _repeat: TransferObservation(True, 0.9 if memory.snapshot_id == "current" else 0.5)
    initial = TransferRegressionSuite().run(tasks(), runner=runner, **memories)
    changed_tasks = (tasks()[0], replace(tasks()[1], input_sha256=digest("changed-unseen-input")), tasks()[2])
    changed_input = TransferRegressionSuite().run(changed_tasks, runner=runner, **memories)
    changed_policy = TransferRegressionSuite(policy=RegressionPolicy(min_unseen_pass_rate=0.9)).run(
        tasks(), runner=runner, **memories,
    )
    for changed in (changed_input, changed_policy):
        assert [summary.to_dict() for summary in changed.summaries] == [summary.to_dict() for summary in initial.summaries]
        assert changed.holdout_receipt_sha256 != initial.holdout_receipt_sha256
        assert changed.baseline_receipt_sha256 != initial.baseline_receipt_sha256
        assert changed.report_sha256 != initial.report_sha256
        changed.assert_promotable()


@pytest.mark.parametrize("contaminated_snapshot", ["rsi-empty-memory-v1", "old", "current"])
def test_raw_foreign_task_access_cannot_be_hidden_by_cleaning_contamination(contaminated_snapshot: str) -> None:
    def runner(task, memory, _repeat):
        accessed = (task.task_id, "foreign-task") if memory.snapshot_id == contaminated_snapshot else (task.task_id,)
        return TransferObservation(True, 0.9 if memory.snapshot_id == "current" else 0.5, accessed_task_ids=accessed)

    contaminated = TransferRegressionSuite().run(
        tasks(), old_memory=snapshot("old", "old-item"), current_memory=snapshot("current", "current-item"),
        runner=runner,
    )
    contaminated.validate_policy_evidence()
    hidden = replace(contaminated, contamination=(), promotion_eligible=True, rejection_reasons=())
    with pytest.raises(TransferRegressionError, match="policy_evidence_drift"):
        hidden.promotion_evidence()


def test_raw_no_memory_access_cannot_be_hidden_by_cleaning_contamination() -> None:
    def runner(_task, memory, _repeat):
        used = ("foreign-memory",) if memory.snapshot_id == "rsi-empty-memory-v1" else ()
        return TransferObservation(True, 0.9 if memory.snapshot_id == "current" else 0.5, memory_ids_used=used)

    contaminated = TransferRegressionSuite().run(
        tasks(), old_memory=snapshot("old", "old-item"), current_memory=snapshot("current", "current-item"),
        runner=runner,
    )
    contaminated.validate_policy_evidence()
    hidden = replace(contaminated, contamination=(), promotion_eligible=True, rejection_reasons=())
    with pytest.raises(TransferRegressionError, match="policy_evidence_drift"):
        hidden.promotion_evidence()
