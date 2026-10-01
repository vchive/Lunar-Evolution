"""Controller-level composition for the provider-free memory promotion path."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution.rsi_controller import DeterministicCurriculum, RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver, LocalExactVerifier, RSIMemoryStore
from lunar_evolution.rsi_identity import component_fingerprint
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


def test_cached_reports_are_scoped_to_governance_and_receipts(tmp_path: Path) -> None:
    old, current = snapshot("old", "old-item"), snapshot("current", "current-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    retained = []
    for name, score in (("first", 0.8), ("second", 0.9)):
        directory = tmp_path / name
        directory.mkdir()
        governance, shadow = shadow_admission(directory, old, current)
        report, active = controller.promote_transfer_regression(
            governance=governance, admission_id=shadow.admission_id,
            expected_record_sha256=shadow.record_sha256, old_memory=old, tasks=manifest(),
            runner=lambda _task, memory, _repeat, score=score: TransferObservation(
                True, score if memory.snapshot_id == "current" else 0.5,
            ), activate=True,
        )
        retained.append((governance, active, report))
    assert retained[0][2].holdout_receipt_sha256 != retained[1][2].holdout_receipt_sha256
    for governance, active, expected_report in retained:
        replay, _active = controller.promote_transfer_regression(
            governance=governance, admission_id=active.admission_id,
            expected_record_sha256=active.record_sha256, old_memory=old, tasks=manifest(),
            runner=lambda *_args: pytest.fail("active regression must not repeat"),
        )
        assert replay is expected_report
        assert replay.holdout_receipt_sha256 == active.holdout_receipt_sha256


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


@pytest.mark.parametrize("key", [
    "memory_snapshot_sha256", "solver_fingerprint", "verifier_fingerprint",
    "curriculum_fingerprint", "target_judge_fingerprint",
])
def test_supplied_fingerprints_cannot_replace_controller_observations(tmp_path: Path, key: str) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    governance, shadow = shadow_admission(tmp_path, old, current)
    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        controller.promote_transfer_regression(
            governance=governance, admission_id=shadow.admission_id,
            expected_record_sha256=shadow.record_sha256, old_memory=old,
            tasks=manifest(), runner=lambda *_args: pytest.fail("invalid pins must stop evaluation"),
            fingerprints={key: digest("fabricated-component")},
        )
    assert governance.get(shadow.admission_id) == shadow


def test_matching_component_fingerprints_remain_valid(tmp_path: Path) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    governance, shadow = shadow_admission(tmp_path, old, current)
    report, approved = controller.promote_transfer_regression(
        governance=governance, admission_id=shadow.admission_id,
        expected_record_sha256=shadow.record_sha256, old_memory=old, tasks=manifest(),
        runner=lambda _task, memory, _repeat: TransferObservation(
            True, 0.9 if memory.snapshot_id == "current" else 0.5,
        ),
        fingerprints={"solver_fingerprint": component_fingerprint(controller.gateway)},
    )
    assert report.promotion_eligible is True
    assert approved.state == "approved"


def test_nested_external_fingerprint_mutation_cannot_promote(tmp_path: Path) -> None:
    old, current = snapshot("old", "old-item"), snapshot("current", "current-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    governance, shadow = shadow_admission(tmp_path, old, current)
    pins = {"external": {"mode": "frozen"}}

    def runner(_task, memory, _repeat):
        pins["external"]["mode"] = "changed"
        return TransferObservation(True, 0.9 if memory.snapshot_id == "current" else 0.5)

    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        controller.promote_transfer_regression(
            governance=governance, admission_id=shadow.admission_id,
            expected_record_sha256=shadow.record_sha256, old_memory=old, tasks=manifest(),
            runner=runner, fingerprints=pins,
        )
    assert governance.get(shadow.admission_id) == shadow


class AlternateVerifier(LocalExactVerifier):
    def rsi_fingerprint_config(self):
        return {"verifier": "changed-exact-v2"}


def alternate_judge(_execution):
    return True, "changed target policy"


@pytest.mark.parametrize("attribute,replacement", [
    ("gateway", DeterministicMockSolver(terminal_status="failed")),
    ("verifier", AlternateVerifier()),
    ("curriculum", DeterministicCurriculum(practice_family="changed-family")),
    ("target_judge", alternate_judge),
])
def test_component_drift_during_suite_cannot_promote(
    tmp_path: Path, attribute: str, replacement: object,
) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    governance, shadow = shadow_admission(tmp_path, old, current)

    def runner(_task, memory, _repetition):
        setattr(controller, attribute, replacement)
        return TransferObservation(True, 0.9 if memory.snapshot_id == "current" else 0.5)

    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        controller.promote_transfer_regression(
            governance=governance, admission_id=shadow.admission_id,
            expected_record_sha256=shadow.record_sha256, old_memory=old,
            tasks=manifest(), runner=runner,
        )
    assert governance.get(shadow.admission_id) == shadow


@pytest.mark.parametrize("state", ["candidate", "revoked"])
def test_ineligible_admission_state_does_not_start_regression(tmp_path: Path, state: str) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    governance, shadow = shadow_admission(tmp_path, old, current)
    if state == "revoked":
        record = governance.revoke(
            shadow.admission_id, expected_record_sha256=shadow.record_sha256, reason="manual rollback",
        )
    else:
        record = governance.create(MemoryAdmissionRecord(
            admission_id="unshadowed", memory_snapshot_sha256=current.digest(),
            memory_item_sha256=digest("item"), source_episode_id="episode",
            verifier_receipt_sha256=digest("verifier"), parent_snapshot_sha256=old.digest(),
            scope="fixture", compatibility={},
        ))
        record = governance.transition(record.admission_id, "verified", expected_record_sha256=record.record_sha256)
        record = governance.transition(record.admission_id, "candidate", expected_record_sha256=record.record_sha256)
    error = "governance_revoked" if state == "revoked" else "transition_invalid"
    with pytest.raises(MemoryPromotionError, match=error):
        controller.promote_transfer_regression(
            governance=governance, admission_id=record.admission_id,
            expected_record_sha256=record.record_sha256, old_memory=old, tasks=manifest(),
            runner=lambda *_args: pytest.fail("ineligible admission must stop evaluation"),
        )
    assert governance.get(record.admission_id) == record


@pytest.mark.parametrize("state", ["approved", "active"])
def test_durable_promotion_binding_rejects_restarted_component_drift(tmp_path: Path, state: str) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    governance, shadow = shadow_admission(tmp_path, old, current)
    _report, promoted = controller.promote_transfer_regression(
        governance=governance, admission_id=shadow.admission_id,
        expected_record_sha256=shadow.record_sha256, old_memory=old, tasks=manifest(),
        runner=lambda _task, memory, _repeat: TransferObservation(
            True, 0.9 if memory.snapshot_id == "current" else 0.5,
        ),
        activate=state == "active",
    )
    assert promoted.compatibility == {}
    assert promoted.reason.startswith("controller_transfer_promotion_v2:")
    reopened = MemoryGovernanceStore(governance.database)
    changed_controller = RSILearningController(
        DeterministicMockSolver(terminal_status="failed"), memory_store=RSIMemoryStore(current),
    )
    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        changed_controller.promote_transfer_regression(
            governance=reopened, admission_id=promoted.admission_id,
            expected_record_sha256=promoted.record_sha256, old_memory=old,
            tasks=manifest(), runner=lambda *_args: pytest.fail("drift must stop recovery"),
            activate=True,
        )
    assert reopened.get(promoted.admission_id) == promoted


@pytest.mark.parametrize("approval_reason", [None, "controller_transfer_promotion:" + digest("legacy-v1")])
def test_controller_cannot_invent_identity_for_unbound_approved_admission(tmp_path: Path, approval_reason: str | None) -> None:
    from lunar_evolution.rsi_memory_promotion import MemoryPromotionAdapter
    from lunar_evolution.rsi_transfer_regression import TransferRegressionSuite

    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    governance, shadow = shadow_admission(tmp_path, old, current)
    report = TransferRegressionSuite().run(
        manifest(), old_memory=old, current_memory=current,
        runner=lambda _task, memory, _repeat: TransferObservation(
            True, 0.9 if memory.snapshot_id == "current" else 0.5,
        ),
    )
    approved = MemoryPromotionAdapter(governance).approve(
        shadow.admission_id, report, expected_record_sha256=shadow.record_sha256,
        approval_reason=approval_reason,
    )
    assert approved.reason == approval_reason
    with pytest.raises(MemoryPromotionError, match="identity_missing"):
        controller.promote_transfer_regression(
            governance=governance, admission_id=approved.admission_id,
            expected_record_sha256=approved.record_sha256, old_memory=old,
            tasks=manifest(), runner=lambda *_args: pytest.fail("legacy identity cannot be inferred"),
            activate=True,
        )
    assert governance.get(approved.admission_id) == approved


def test_durable_promotion_binding_preserves_external_pins(tmp_path: Path) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    governance, shadow = shadow_admission(tmp_path, old, current)
    _report, approved = controller.promote_transfer_regression(
        governance=governance, admission_id=shadow.admission_id,
        expected_record_sha256=shadow.record_sha256, old_memory=old, tasks=manifest(),
        runner=lambda _task, memory, _repeat: TransferObservation(
            True, 0.9 if memory.snapshot_id == "current" else 0.5,
        ),
        fingerprints={"task_input_sha256": digest("original-input")},
    )
    restarted = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(current))
    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        restarted.promote_transfer_regression(
            governance=governance, admission_id=approved.admission_id,
            expected_record_sha256=approved.record_sha256, old_memory=old,
            tasks=manifest(), runner=lambda *_args: pytest.fail("input drift must stop activation"),
            activate=True, fingerprints={"task_input_sha256": digest("changed-input")},
        )
    assert governance.get(approved.admission_id) == approved


def test_transient_component_drift_stops_at_first_trial(tmp_path: Path) -> None:
    old = snapshot("old", "old-item")
    current = snapshot("current", "current-item")
    original = DeterministicMockSolver()
    controller = RSILearningController(original, memory_store=RSIMemoryStore(current))
    governance, shadow = shadow_admission(tmp_path, old, current)
    calls = 0

    def runner(_task, memory, _repeat):
        nonlocal calls
        calls += 1
        controller.gateway = DeterministicMockSolver(terminal_status="failed") if calls < 18 else original
        return TransferObservation(True, 0.9 if memory.snapshot_id == "current" else 0.5)

    with pytest.raises(MemoryPromotionError, match="fingerprint_drift"):
        controller.promote_transfer_regression(
            governance=governance, admission_id=shadow.admission_id,
            expected_record_sha256=shadow.record_sha256, old_memory=old,
            tasks=manifest(), runner=runner,
        )
    assert calls == 1
    assert governance.get(shadow.admission_id) == shadow
