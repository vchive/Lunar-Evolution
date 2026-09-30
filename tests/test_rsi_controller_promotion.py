"""Controller-level composition for the provider-free memory promotion path."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver, RSIMemoryStore
from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot
from lunar_evolution.rsi_memory_governance import MemoryAdmissionRecord, MemoryGovernanceStore
from lunar_evolution.rsi_memory_promotion import MemoryPromotionError
from lunar_evolution.rsi_transfer_regression import TransferObservation, TransferTask


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def snapshot(name: str, memory_id: str) -> MemorySnapshot:
    return MemorySnapshot(
        name,
        None,
        (MemoryItem(
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
        ),),
    )


def manifest() -> tuple[TransferTask, ...]:
    return (
        TransferTask("seen", "family-a", "seen", "target-a", digest("seen")),
        TransferTask("unseen-a", "family-a", "unseen", "target-b", digest("unseen-a")),
        TransferTask("unseen-b", "family-b", "unseen", "target-c", digest("unseen-b")),
    )


def shadow_admission(
    tmp_path: Path, old: MemorySnapshot, current: MemorySnapshot,
) -> tuple[MemoryGovernanceStore, MemoryAdmissionRecord]:
    governance = MemoryGovernanceStore(tmp_path / "governance.sqlite3")
    record = governance.create(MemoryAdmissionRecord(
        admission_id="admission-controller",
        memory_snapshot_sha256=current.digest(),
        memory_item_sha256=digest("item"),
        source_episode_id="episode-controller",
        verifier_receipt_sha256=None,
        parent_snapshot_sha256=old.digest(),
        scope="fixture",
        compatibility={},
    ))
    record = governance.transition(
        record.admission_id, "verified", expected_record_sha256=record.record_sha256,
        verifier_receipt_sha256=digest("verifier"),
    )
    record = governance.transition(record.admission_id, "candidate", expected_record_sha256=record.record_sha256)
    return governance, governance.transition(record.admission_id, "shadow", expected_record_sha256=record.record_sha256)


def test_controller_runs_suite_and_promotes_only_after_explicit_activation(tmp_path: Path) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    controller = RSILearningController(
        DeterministicMockSolver(), memory_store=RSIMemoryStore(current),
    )
    governance, shadow = shadow_admission(tmp_path, old, current)
    calls = 0

    def runner(task, memory, repetition):
        nonlocal calls
        calls += 1
        score = 0.8 if memory.snapshot_id == "current" else (0.2 if memory.snapshot_id == "rsi-empty-memory-v1" else 0.5)
        if task.split == "seen" and memory.snapshot_id == "current":
            score = 0.7
        return TransferObservation(
            score >= 0.5, score, accessed_task_ids=(task.task_id,),
            memory_ids_used=tuple(item.memory_id for item in memory.items),
        )

    report, approved = controller.promote_transfer_regression(
        governance=governance,
        admission_id=shadow.admission_id,
        expected_record_sha256=shadow.record_sha256,
        old_memory=old,
        tasks=manifest(),
        runner=runner,
    )
    assert report is not None and report.promotion_eligible is True
    assert approved.state == "approved"
    assert calls == 18

    report_again, active = controller.promote_transfer_regression(
        governance=governance,
        admission_id=approved.admission_id,
        expected_record_sha256=approved.record_sha256,
        old_memory=old,
        tasks=manifest(),
        runner=runner,
        activate=True,
    )
    assert report_again is report
    assert active.state == "active"
    assert calls == 18
    assert [record.state for record in governance.history(shadow.admission_id)] == [
        "observed", "verified", "candidate", "shadow", "approved", "active",
    ]


def test_controller_resumes_approved_activation_without_in_memory_report(tmp_path: Path) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    controller = RSILearningController(
        DeterministicMockSolver(), memory_store=RSIMemoryStore(current),
    )
    governance, shadow = shadow_admission(tmp_path, old, current)

    def runner(task, memory, repetition):
        del repetition
        score = 0.8 if memory.snapshot_id == "current" else 0.5
        return TransferObservation(
            score >= 0.5, score, accessed_task_ids=(task.task_id,),
            memory_ids_used=tuple(item.memory_id for item in memory.items),
        )

    report, approved = controller.promote_transfer_regression(
        governance=governance, admission_id=shadow.admission_id,
        expected_record_sha256=shadow.record_sha256, old_memory=old,
        tasks=manifest(), runner=runner,
    )
    assert report is not None and approved.state == "approved"

    resumed = RSILearningController(
        DeterministicMockSolver(), memory_store=RSIMemoryStore(current),
    )
    report_again, active = resumed.promote_transfer_regression(
        governance=governance, admission_id=approved.admission_id,
        expected_record_sha256=approved.record_sha256, old_memory=old,
        tasks=manifest(), runner=lambda *_args: pytest.fail("regression must not replay"),
        activate=True,
    )
    assert report_again is None
    assert active.state == "active"


def test_controller_rejects_snapshot_drift_before_running_fixture(tmp_path: Path) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    other = snapshot("other", "other-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(other))
    governance, shadow = shadow_admission(tmp_path, old, current)
    with pytest.raises(MemoryPromotionError, match="snapshot_drift"):
        controller.promote_transfer_regression(
            governance=governance, admission_id=shadow.admission_id,
            expected_record_sha256=shadow.record_sha256, old_memory=old,
            tasks=manifest(), runner=lambda *_args: TransferObservation(True, 1.0),
        )
    assert governance.get(shadow.admission_id) == shadow


def test_controller_rejected_holdout_does_not_append_governance_revision(tmp_path: Path) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    governance, shadow = shadow_admission(tmp_path, old, current)
    with pytest.raises(MemoryPromotionError, match="report_rejected"):
        controller.promote_transfer_regression(
            governance=governance, admission_id=shadow.admission_id,
            expected_record_sha256=shadow.record_sha256, old_memory=old,
            tasks=manifest(), runner=lambda task, *_args: TransferObservation(
                task.split == "seen", 1.0 if task.split == "seen" else 0.0,
            ),
        )
    assert governance.get(shadow.admission_id) == shadow


def test_controller_fingerprint_binding_fails_closed(tmp_path: Path) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    governance = MemoryGovernanceStore(tmp_path / "governance.sqlite3")
    record = governance.create(MemoryAdmissionRecord(
        admission_id="fingerprint-admission", memory_snapshot_sha256=current.digest(),
        memory_item_sha256=digest("item"), source_episode_id="episode", verifier_receipt_sha256=None,
        parent_snapshot_sha256=old.digest(), scope="fixture", compatibility={"solver_fingerprint": "wrong"},
    ))
    record = governance.transition(record.admission_id, "verified", expected_record_sha256=record.record_sha256,
                                   verifier_receipt_sha256=digest("verifier"))
    record = governance.transition(record.admission_id, "candidate", expected_record_sha256=record.record_sha256)
    shadow = governance.transition(record.admission_id, "shadow", expected_record_sha256=record.record_sha256)
    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        controller.promote_transfer_regression(
            governance=governance, admission_id=shadow.admission_id,
            expected_record_sha256=shadow.record_sha256, old_memory=old,
            tasks=manifest(), runner=lambda *_args: TransferObservation(True, 1.0),
        )
    assert governance.get(shadow.admission_id) == shadow
