"""Explicit transfer-regression to memory-governance promotion wiring."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot
from lunar_evolution.rsi_memory_governance import (
    MemoryAdmissionRecord,
    MemoryGovernanceError,
    MemoryGovernanceStore,
)
from lunar_evolution.rsi_memory_promotion import MemoryPromotionAdapter, MemoryPromotionError
from lunar_evolution.rsi_transfer_regression import (
    TransferObservation,
    TransferRegressionSuite,
    TransferTask,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def snapshot(name: str, memory_id: str) -> MemorySnapshot:
    return MemorySnapshot(
        name,
        None,
        (
            MemoryItem(
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
            ),
        ),
    )


def tasks() -> tuple[TransferTask, ...]:
    return (
        TransferTask("seen-1", "family-a", "seen", "target-a", digest("seen-1")),
        TransferTask("unseen-1", "family-a", "unseen", "target-b", digest("unseen-1")),
        TransferTask("unseen-2", "family-b", "unseen", "target-c", digest("unseen-2")),
    )


def report(*, eligible: bool = True, old_name: str = "old", current_name: str = "current"):
    old = snapshot(old_name, old_name + "-item")
    current = snapshot(current_name, current_name + "-item")

    def runner(task, memory, repetition):
        if not eligible:
            score = 1.0 if task.split == "seen" else 0.0
        elif memory.snapshot_id == "rsi-empty-memory-v1":
            score = 0.2 if task.split == "seen" else 0.0
        elif memory.snapshot_id == old_name:
            score = 0.5
        else:
            score = 0.8 if task.split == "unseen" else 0.7
        return TransferObservation(
            passed=score >= 0.5,
            score=score,
            cost=1 + repetition,
            accessed_task_ids=(task.task_id,),
            memory_ids_used=tuple(item.memory_id for item in memory.items),
        )

    return TransferRegressionSuite().run(tasks(), old_memory=old, current_memory=current, runner=runner)


def observed(*, current_sha256: str, parent_sha256: str, compatibility: dict[str, str]) -> MemoryAdmissionRecord:
    return MemoryAdmissionRecord(
        admission_id="admission-1",
        memory_snapshot_sha256=current_sha256,
        memory_item_sha256="b" * 64,
        source_episode_id="episode-1",
        verifier_receipt_sha256=None,
        parent_snapshot_sha256=parent_sha256,
        scope="problem-family:test",
        compatibility=compatibility,
    )


def shadow_admission(tmp_path: Path) -> tuple[MemoryGovernanceStore, MemoryAdmissionRecord, dict[str, str]]:
    current = snapshot("current", "current-item")
    old = snapshot("old", "old-item")
    compatibility = {"solver": "fixture", "contract": digest("contract")}
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admission = governance.create(
        observed(current_sha256=current.digest(), parent_sha256=old.digest(), compatibility=compatibility)
    )
    admission = governance.transition(
        admission.admission_id,
        "verified",
        expected_record_sha256=admission.record_sha256,
        verifier_receipt_sha256="c" * 64,
    )
    admission = governance.transition(admission.admission_id, "candidate", expected_record_sha256=admission.record_sha256)
    admission = governance.transition(admission.admission_id, "shadow", expected_record_sha256=admission.record_sha256)
    return governance, admission, compatibility


def test_promotable_report_appends_approved_then_active(tmp_path: Path) -> None:
    governance, shadow, compatibility = shadow_admission(tmp_path)
    active = MemoryPromotionAdapter(governance).promote(
        shadow.admission_id,
        report(),
        expected_record_sha256=shadow.record_sha256,
        compatibility=compatibility,
        activate=True,
    )

    assert active.state == "active"
    assert active.regression_passed is True
    assert active.holdout_receipt_sha256
    assert active.baseline_receipt_sha256
    assert [record.state for record in governance.history(shadow.admission_id)] == [
        "observed", "verified", "candidate", "shadow", "approved", "active"
    ]


def test_rejected_report_writes_no_governance_revision(tmp_path: Path) -> None:
    governance, shadow, compatibility = shadow_admission(tmp_path)
    with pytest.raises(MemoryPromotionError) as rejected:
        MemoryPromotionAdapter(governance).approve(
            shadow.admission_id,
            report(eligible=False),
            expected_record_sha256=shadow.record_sha256,
            compatibility=compatibility,
        )
    assert rejected.value.code == "rsi_memory_promotion_report_rejected"
    assert governance.get(shadow.admission_id) == shadow


def test_report_or_cas_drift_fails_closed(tmp_path: Path) -> None:
    governance, shadow, compatibility = shadow_admission(tmp_path)
    valid = report()
    drifted = replace(valid, holdout_receipt_sha256="f" * 64)
    with pytest.raises(MemoryPromotionError) as drift:
        MemoryPromotionAdapter(governance).approve(
            shadow.admission_id,
            drifted,
            expected_record_sha256=shadow.record_sha256,
            compatibility=compatibility,
        )
    assert drift.value.code == "rsi_memory_promotion_report_drift"
    with pytest.raises(MemoryGovernanceError) as cas:
        MemoryPromotionAdapter(governance).approve(
            shadow.admission_id,
            valid,
            expected_record_sha256="e" * 64,
            compatibility=compatibility,
        )
    assert cas.value.code == "rsi_memory_governance_cas_conflict"
    assert governance.get(shadow.admission_id) == shadow


def test_report_for_another_memory_snapshot_is_rejected(tmp_path: Path) -> None:
    governance, shadow, compatibility = shadow_admission(tmp_path)
    with pytest.raises(MemoryPromotionError) as drift:
        MemoryPromotionAdapter(governance).approve(
            shadow.admission_id,
            report(old_name="other-old", current_name="other-current"),
            expected_record_sha256=shadow.record_sha256,
            compatibility=compatibility,
        )
    assert drift.value.code == "rsi_memory_promotion_snapshot_drift"
    assert governance.get(shadow.admission_id) == shadow


def test_compatibility_drift_is_delegated_to_governance(tmp_path: Path) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    with pytest.raises(MemoryGovernanceError) as drift:
        MemoryPromotionAdapter(governance).approve(
            shadow.admission_id,
            report(),
            expected_record_sha256=shadow.record_sha256,
            compatibility={"solver": "other", "contract": digest("contract")},
        )
    assert drift.value.code == "rsi_memory_governance_compatibility_drift"
    assert governance.get(shadow.admission_id) == shadow


def test_revoked_admission_cannot_be_promoted(tmp_path: Path) -> None:
    governance, shadow, compatibility = shadow_admission(tmp_path)
    revoked = governance.revoke(
        shadow.admission_id,
        expected_record_sha256=shadow.record_sha256,
        reason="fixture rollback",
    )
    with pytest.raises(MemoryGovernanceError) as rejected:
        MemoryPromotionAdapter(governance).promote(
            revoked.admission_id,
            report(),
            expected_record_sha256=revoked.record_sha256,
            compatibility=compatibility,
            activate=True,
        )
    assert rejected.value.code == "rsi_memory_governance_revoked"
    assert governance.get(revoked.admission_id).state == "revoked"


def test_failed_transfer_report_quarantines_active_memory_idempotently(tmp_path: Path) -> None:
    governance, shadow, compatibility = shadow_admission(tmp_path)
    adapter = MemoryPromotionAdapter(governance)
    active = adapter.promote(
        shadow.admission_id,
        report(),
        expected_record_sha256=shadow.record_sha256,
        compatibility=compatibility,
        activate=True,
    )
    rejected = report(eligible=False)

    revoked = adapter.quarantine_failed_report(
        active.admission_id,
        rejected,
        expected_record_sha256=active.record_sha256,
    )
    assert revoked.state == "revoked"
    assert governance.list_retrievable(scope="problem-family:test", compatibility={}) == ()
    assert [record.state for record in governance.history(active.admission_id)] == [
        "observed", "verified", "candidate", "shadow", "approved", "active", "revoked"
    ]

    replay = adapter.quarantine_failed_report(
        active.admission_id,
        rejected,
        expected_record_sha256=revoked.record_sha256,
    )
    assert replay == revoked
    assert len(governance.history(active.admission_id)) == 7


def test_quarantine_requires_rejected_bound_report(tmp_path: Path) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    adapter = MemoryPromotionAdapter(governance)
    with pytest.raises(MemoryPromotionError) as passed:
        adapter.quarantine_failed_report(
            shadow.admission_id,
            report(),
            expected_record_sha256=shadow.record_sha256,
        )
    assert passed.value.code == "rsi_memory_promotion_quarantine_requires_rejection"
    assert governance.get(shadow.admission_id) == shadow

    with pytest.raises(MemoryPromotionError) as drift:
        adapter.quarantine_failed_report(
            shadow.admission_id,
            report(eligible=False, old_name="other-old", current_name="other-current"),
            expected_record_sha256=shadow.record_sha256,
        )
    assert drift.value.code == "rsi_memory_promotion_snapshot_drift"
    assert governance.get(shadow.admission_id) == shadow
