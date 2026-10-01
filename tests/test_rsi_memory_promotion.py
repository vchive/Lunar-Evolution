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
    RegressionPolicy,
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


def test_quarantine_replay_cannot_hide_manual_or_different_report_revocation(tmp_path: Path) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    manually_revoked = governance.revoke(
        shadow.admission_id, expected_record_sha256=shadow.record_sha256, reason="manual rollback",
    )
    with pytest.raises(MemoryPromotionError) as conflict:
        MemoryPromotionAdapter(governance).quarantine_failed_report(
            manually_revoked.admission_id,
            report(eligible=False),
            expected_record_sha256=manually_revoked.record_sha256,
        )
    assert conflict.value.code == "rsi_memory_promotion_quarantine_report_conflict"
    assert governance.get(shadow.admission_id) == manually_revoked


def test_quarantine_report_drift_or_stale_cas_writes_no_revision(tmp_path: Path) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    adapter = MemoryPromotionAdapter(governance)
    rejected = report(eligible=False)
    with pytest.raises(MemoryPromotionError) as report_drift:
        adapter.quarantine_failed_report(
            shadow.admission_id,
            replace(rejected, rejection_reasons=("changed",)),
            expected_record_sha256=shadow.record_sha256,
        )
    assert report_drift.value.code == "rsi_memory_promotion_report_drift"
    with pytest.raises(MemoryGovernanceError) as cas:
        adapter.quarantine_failed_report(
            shadow.admission_id,
            rejected,
            expected_record_sha256="f" * 64,
        )
    assert cas.value.code == "rsi_memory_governance_cas_conflict"
    assert governance.get(shadow.admission_id) == shadow


def test_quarantine_replay_rejects_another_canonical_failed_report(tmp_path: Path) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    adapter = MemoryPromotionAdapter(governance)
    rejected = report(eligible=False)
    revoked = adapter.quarantine_failed_report(
        shadow.admission_id, rejected, expected_record_sha256=shadow.record_sha256,
    )
    other_report = TransferRegressionSuite().run(
        tasks(), old_memory=snapshot("old", "old-item"),
        current_memory=snapshot("current", "current-item"),
        runner=lambda *_args: TransferObservation(False, 0.0),
    )
    assert other_report.promotion_eligible is False
    assert other_report.report_sha256 != rejected.report_sha256
    with pytest.raises(MemoryPromotionError, match="quarantine_report_conflict"):
        adapter.quarantine_failed_report(
            revoked.admission_id, other_report, expected_record_sha256=revoked.record_sha256,
        )
    assert governance.get(shadow.admission_id) == revoked


def test_approved_activation_cannot_replace_approval_reason(tmp_path: Path) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    adapter = MemoryPromotionAdapter(governance)
    evidence = report()
    approved = adapter.approve(
        shadow.admission_id, evidence, expected_record_sha256=shadow.record_sha256,
        approval_reason="controller_transfer_promotion:" + digest("original-components"),
    )
    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        adapter.activate(
            approved.admission_id, evidence, expected_record_sha256=approved.record_sha256,
            approval_reason="controller_transfer_promotion:" + digest("changed-components"),
        )
    assert governance.get(approved.admission_id) == approved


def test_quarantine_reason_annotation_retains_report_binding(tmp_path: Path) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    adapter = MemoryPromotionAdapter(governance)
    rejected = report(eligible=False)
    revoked = adapter.quarantine_failed_report(
        shadow.admission_id, rejected, expected_record_sha256=shadow.record_sha256,
        reason="unseen task regression",
    )
    assert revoked.reason == "transfer_regression_rejected:" + rejected.report_sha256 + ";unseen task regression"
    assert adapter.quarantine_failed_report(
        revoked.admission_id, rejected, expected_record_sha256=revoked.record_sha256,
        reason="unseen task regression",
    ) == revoked


@pytest.mark.parametrize("reason", ["", "bad\nreason", object(), "x" * 513])
def test_quarantine_invalid_reason_annotation_does_not_revoke(tmp_path: Path, reason: object) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    with pytest.raises(MemoryPromotionError, match="quarantine_reason_invalid"):
        MemoryPromotionAdapter(governance).quarantine_failed_report(
            shadow.admission_id, report(eligible=False),
            expected_record_sha256=shadow.record_sha256, reason=reason,
        )
    assert governance.get(shadow.admission_id) == shadow


@pytest.mark.parametrize("activate", [False, True])
def test_high_score_failed_holdout_cannot_approve_or_activate(tmp_path: Path, activate: bool) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    failed = TransferRegressionSuite().run(
        tasks(), old_memory=snapshot("old", "old-item"), current_memory=snapshot("current", "current-item"),
        runner=lambda _task, memory, _repeat: TransferObservation(
            False, 0.9 if memory.snapshot_id == "current" else 0.2,
        ),
    )
    with pytest.raises(MemoryPromotionError, match="report_rejected"):
        MemoryPromotionAdapter(governance).promote(
            shadow.admission_id, failed, expected_record_sha256=shadow.record_sha256, activate=activate,
        )
    assert governance.get(shadow.admission_id) == shadow


def _rehash_report(value):
    from lunar_evolution.candidate_evaluation_spec import canonical_json

    payload = value.to_dict()
    for field in ("protocol", "schema_version", "report_sha256"):
        payload.pop(field)
    return replace(value, report_sha256=hashlib.sha256(canonical_json(payload, maximum=128 * 1024)).hexdigest())


def test_legacy_policy_less_report_remains_inspectable_but_cannot_promote(tmp_path: Path) -> None:
    from lunar_evolution.rsi_transfer_regression import TransferRegressionError

    governance, shadow, _compatibility = shadow_admission(tmp_path)
    legacy = _rehash_report(replace(report(), policy=None))
    assert legacy.to_dict()["schema_version"] == "2"
    assert "policy" not in legacy.to_dict()
    with pytest.raises(TransferRegressionError, match="policy_evidence_missing"):
        legacy.promotion_evidence()
    with pytest.raises(MemoryPromotionError, match="policy_evidence_missing"):
        MemoryPromotionAdapter(governance).approve(
            shadow.admission_id, legacy, expected_record_sha256=shadow.record_sha256,
        )
    assert governance.get(shadow.admission_id) == shadow


def test_rejected_legacy_report_can_still_be_quarantined(tmp_path: Path) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    legacy = _rehash_report(replace(report(eligible=False), policy=None))
    assert legacy.to_dict()["schema_version"] == "2"
    revoked = MemoryPromotionAdapter(governance).quarantine_failed_report(
        shadow.admission_id, legacy, expected_record_sha256=shadow.record_sha256,
    )
    assert revoked.state == "revoked"


def test_canonical_policy_substitution_cannot_reuse_old_receipts(tmp_path: Path) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    substituted = _rehash_report(replace(report(), policy=RegressionPolicy(min_unseen_pass_rate=0.9)))
    with pytest.raises(MemoryPromotionError, match="policy_evidence_drift"):
        MemoryPromotionAdapter(governance).approve(
            shadow.admission_id, substituted, expected_record_sha256=shadow.record_sha256,
        )
    assert governance.get(shadow.admission_id) == shadow


def test_canonical_eligibility_substitution_cannot_hide_failing_pass_gate(tmp_path: Path) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)
    failed = TransferRegressionSuite().run(
        tasks(), old_memory=snapshot("old", "old-item"), current_memory=snapshot("current", "current-item"),
        runner=lambda _task, memory, _repeat: TransferObservation(False, 0.9 if memory.snapshot_id == "current" else 0.2),
    )
    substituted = _rehash_report(replace(failed, promotion_eligible=True, rejection_reasons=()))
    with pytest.raises(MemoryPromotionError, match="policy_evidence_drift"):
        MemoryPromotionAdapter(governance).approve(
            shadow.admission_id, substituted, expected_record_sha256=shadow.record_sha256,
        )
    assert governance.get(shadow.admission_id) == shadow


@pytest.mark.parametrize("access_kind", ["foreign_task", "no_memory"])
@pytest.mark.parametrize("activate", [False, True])
def test_rehashed_contamination_omission_cannot_promote(tmp_path: Path, access_kind: str, activate: bool) -> None:
    governance, shadow, _compatibility = shadow_admission(tmp_path)

    def runner(task, memory, _repeat):
        return TransferObservation(
            True, 0.9 if memory.snapshot_id == "current" else 0.5,
            accessed_task_ids=(task.task_id, "foreign-task") if access_kind == "foreign_task" else (task.task_id,),
            memory_ids_used=("foreign-memory",) if access_kind == "no_memory" and memory.snapshot_id == "rsi-empty-memory-v1" else (),
        )

    contaminated = TransferRegressionSuite().run(
        tasks(), old_memory=snapshot("old", "old-item"), current_memory=snapshot("current", "current-item"),
        runner=runner,
    )
    substituted = _rehash_report(replace(contaminated, contamination=(), promotion_eligible=True, rejection_reasons=()))
    with pytest.raises(MemoryPromotionError, match="policy_evidence_drift"):
        MemoryPromotionAdapter(governance).promote(
            shadow.admission_id, substituted, expected_record_sha256=shadow.record_sha256, activate=activate,
        )
    assert governance.get(shadow.admission_id) == shadow
    assert len(governance.history(shadow.admission_id)) == 4
