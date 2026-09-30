from pathlib import Path

import pytest

from lunar_evolution.rsi_memory_governance import (
    MemoryAdmissionRecord,
    MemoryGovernanceError,
    MemoryGovernanceStore,
)

HEX = "a" * 64
ITEM = "b" * 64
VERIFIER = "c" * 64
HOLDOUT = "d" * 64
BASELINE = "e" * 64


def store(tmp_path: Path) -> MemoryGovernanceStore:
    return MemoryGovernanceStore(tmp_path / "rsi.sqlite3")


def observed(*, outcome: str = "pass") -> MemoryAdmissionRecord:
    return MemoryAdmissionRecord(
        admission_id="admission-1",
        memory_snapshot_sha256=HEX,
        memory_item_sha256=ITEM,
        source_episode_id="episode-1",
        verifier_receipt_sha256=None,
        parent_snapshot_sha256=None,
        scope="problem-family:test",
        compatibility={"solver": "mock", "contract": HEX},
        episode_outcome=outcome,
    )


def to_candidate(store_: MemoryGovernanceStore, *, outcome: str = "pass") -> object:
    current = store_.create(observed(outcome=outcome))
    current = store_.transition(
        current.admission_id,
        "verified",
        expected_record_sha256=current.record_sha256,
        verifier_receipt_sha256=VERIFIER,
    )
    return store_.transition(
        current.admission_id,
        "candidate",
        expected_record_sha256=current.record_sha256,
    )


def test_lifecycle_requires_each_gate_and_persists_across_reopen(tmp_path: Path):
    governance = store(tmp_path)
    current = governance.create(observed())
    assert current.state == "observed"
    with pytest.raises(MemoryGovernanceError) as skipped:
        governance.transition("admission-1", "approved", expected_record_sha256=current.record_sha256)
    assert skipped.value.code == "rsi_memory_governance_transition_invalid"

    current = governance.transition(
        "admission-1", "verified", expected_record_sha256=current.record_sha256,
        verifier_receipt_sha256=VERIFIER,
    )
    current = governance.transition("admission-1", "candidate", expected_record_sha256=current.record_sha256)
    current = governance.transition("admission-1", "shadow", expected_record_sha256=current.record_sha256)
    with pytest.raises(MemoryGovernanceError) as missing_gate:
        governance.transition("admission-1", "approved", expected_record_sha256=current.record_sha256)
    assert missing_gate.value.code == "rsi_memory_governance_regression_gate"

    current = governance.transition(
        "admission-1", "approved", expected_record_sha256=current.record_sha256,
        holdout_receipt_sha256=HOLDOUT, baseline_receipt_sha256=BASELINE, regression_passed=True,
    )
    current = governance.transition("admission-1", "active", expected_record_sha256=current.record_sha256)
    reopened = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    loaded = reopened.get("admission-1")
    assert loaded == current
    assert [record.state for record in reopened.history("admission-1")] == [
        "observed", "verified", "candidate", "shadow", "approved", "active"
    ]


def test_only_passing_episode_with_verifier_can_be_candidate(tmp_path: Path):
    governance = store(tmp_path)
    failed = governance.create(observed(outcome="fail"))
    with pytest.raises(MemoryGovernanceError) as rejected:
        governance.transition(
            "admission-1", "verified", expected_record_sha256=failed.record_sha256,
            verifier_receipt_sha256=VERIFIER,
        )
    assert rejected.value.code == "rsi_memory_governance_episode_not_pass"

    governance = store(tmp_path / "pass")
    initial = governance.create(observed())
    with pytest.raises(MemoryGovernanceError) as missing:
        governance.transition("admission-1", "verified", expected_record_sha256=initial.record_sha256)
    assert missing.value.code == "rsi_memory_governance_verifier_missing"


def test_compare_and_swap_conflict_does_not_append(tmp_path: Path):
    governance = store(tmp_path)
    current = governance.create(observed())
    with pytest.raises(MemoryGovernanceError) as conflict:
        governance.transition(
            "admission-1", "verified", expected_record_sha256="f" * 64,
            verifier_receipt_sha256=VERIFIER,
        )
    assert conflict.value.code == "rsi_memory_governance_cas_conflict"
    assert len(governance.history("admission-1")) == 1
    assert governance.get("admission-1") == current


def test_compatibility_drift_fails_closed(tmp_path: Path):
    governance = store(tmp_path)
    candidate = to_candidate(governance)
    shadow = governance.transition("admission-1", "shadow", expected_record_sha256=candidate.record_sha256)
    with pytest.raises(MemoryGovernanceError) as drift:
        governance.transition(
            "admission-1", "approved", expected_record_sha256=shadow.record_sha256,
            holdout_receipt_sha256=HOLDOUT, baseline_receipt_sha256=BASELINE,
            regression_passed=True, compatibility={"solver": "different", "contract": HEX},
        )
    assert drift.value.code == "rsi_memory_governance_compatibility_drift"
    assert governance.get("admission-1").state == "shadow"


def test_revoke_is_terminal_and_never_retrievable(tmp_path: Path):
    governance = store(tmp_path)
    candidate = to_candidate(governance)
    revoked = governance.revoke(
        "admission-1", expected_record_sha256=candidate.record_sha256, reason="rollback after drift"
    )
    assert revoked.state == "revoked"
    with pytest.raises(MemoryGovernanceError) as restart:
        governance.transition("admission-1", "shadow", expected_record_sha256=revoked.record_sha256)
    assert restart.value.code == "rsi_memory_governance_revoked"
    assert governance.list_retrievable(scope="problem-family:test", compatibility={}) == ()


def test_active_retrieval_requires_scope_and_compatible_fingerprint(tmp_path: Path):
    governance = store(tmp_path)
    candidate = to_candidate(governance)
    shadow = governance.transition("admission-1", "shadow", expected_record_sha256=candidate.record_sha256)
    approved = governance.transition(
        "admission-1", "approved", expected_record_sha256=shadow.record_sha256,
        holdout_receipt_sha256=HOLDOUT, baseline_receipt_sha256=BASELINE, regression_passed=True,
    )
    governance.transition("admission-1", "active", expected_record_sha256=approved.record_sha256)
    assert len(governance.list_retrievable(scope="problem-family:test", compatibility={"solver": "mock"})) == 1
    assert governance.list_retrievable(scope="problem-family:other", compatibility={}) == ()
    assert governance.list_retrievable(scope="problem-family:test", compatibility={"solver": "other"}) == ()


def test_duplicate_admission_and_invalid_revoke_are_rejected(tmp_path: Path):
    governance = store(tmp_path)
    current = governance.create(observed())
    with pytest.raises(MemoryGovernanceError) as duplicate:
        governance.create(observed())
    assert duplicate.value.code == "rsi_memory_governance_exists"
    with pytest.raises(MemoryGovernanceError) as no_reason:
        governance.revoke("admission-1", expected_record_sha256=current.record_sha256, reason="")
    assert no_reason.value.code == "rsi_memory_governance_revoke_reason_missing"
