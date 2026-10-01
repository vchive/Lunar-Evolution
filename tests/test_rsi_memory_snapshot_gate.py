"""Local fixtures for governed frozen-memory eligibility before solver execution."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot
from lunar_evolution.rsi_memory_governance import MemoryAdmissionRecord, MemoryGovernanceStore
from lunar_evolution.rsi_memory_snapshot_gate import (
    GovernedMemorySnapshotGate,
    MemorySnapshotAdmissionError,
)

SCOPE = "problem-family:fixture"
PINS = {"solver": "fixture", "contract": "a" * 64}
STATES = ("observed", "verified", "candidate", "shadow", "approved", "active", "deprecated")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def frozen_snapshot(*, count: int = 1, legacy: bool = False) -> MemorySnapshot:
    items = []
    for index in range(count):
        item = MemoryItem(
            memory_id=f"memory-{index}",
            problem_family="fixture",
            trigger="when fixture input",
            strategy="use bounded strategy",
            expected_result="pass",
            failure_boundary="fixture boundary",
            compatible_contracts=(PINS["contract"],),
            compatible_solvers=("fixture",),
            verifier_outcome="pass",
            receipt_sha256=digest(f"receipt-{index}"),
            episode_id=f"episode-{index}",
        )
        if legacy:
            payload = item.to_dict()
            for key in ("condition", "action", "observed_result", "applicability"):
                payload.pop(key)
            item = MemoryItem.from_dict(payload)
        items.append(item)
    return MemorySnapshot("frozen-fixture", digest("parent"), tuple(items))


def mapping(snapshot: MemorySnapshot) -> dict[str, str]:
    return {item.memory_id: f"admission-{item.memory_id}" for item in snapshot.items}


def admit(
    governance: MemoryGovernanceStore,
    snapshot: MemorySnapshot,
    *,
    index: int = 0,
    state: str = "active",
    overrides: dict[str, object] | None = None,
) -> MemoryAdmissionRecord:
    item = snapshot.items[index]
    record = MemoryAdmissionRecord(
        admission_id=mapping(snapshot)[item.memory_id],
        memory_snapshot_sha256=snapshot.digest(),
        memory_item_sha256=hashlib.sha256(canonical_json(item.to_dict(), maximum=128 * 1024)).hexdigest(),
        source_episode_id=item.episode_id,
        verifier_receipt_sha256=None,
        parent_snapshot_sha256=snapshot.parent_snapshot_sha256,
        scope=SCOPE,
        compatibility=PINS,
    )
    current = governance.create(replace(record, **(overrides or {})))
    for target in STATES[1:]:
        if current.state == state:
            return current
        kwargs = {}
        if target == "verified":
            kwargs["verifier_receipt_sha256"] = current.verifier_receipt_sha256 or item.receipt_sha256
        if target == "approved":
            kwargs.update(
                holdout_receipt_sha256=digest("holdout"),
                baseline_receipt_sha256=digest("baseline"),
                regression_passed=True,
            )
        current = governance.transition(
            current.admission_id, target, expected_record_sha256=current.record_sha256, **kwargs,
        )
    if state == "revoked":
        current = governance.revoke(
            current.admission_id, expected_record_sha256=current.record_sha256, reason="fixture revocation",
        )
    assert current.state == state
    return current


def gate(
    governance: MemoryGovernanceStore,
    snapshot: MemorySnapshot,
    **kwargs: object,
) -> GovernedMemorySnapshotGate:
    config = {
        "snapshot_sha256": snapshot.digest(),
        "admissions": mapping(snapshot),
        "scope": SCOPE,
        "compatibility": PINS,
    }
    config.update(kwargs)
    return GovernedMemorySnapshotGate(governance, **config)


def refused(gate_: GovernedMemorySnapshotGate, snapshot: MemorySnapshot, code: str) -> None:
    with pytest.raises(MemorySnapshotAdmissionError) as error:
        gate_.validate(snapshot)
    assert error.value.code == "rsi_memory_snapshot_gate_" + code


@pytest.mark.parametrize("legacy", [False, True])
def test_active_snapshot_validation_is_read_only_and_preserves_wire_bytes(tmp_path: Path, legacy: bool):
    snapshot = frozen_snapshot(count=2, legacy=legacy)
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    records = [admit(governance, snapshot, index=index) for index in range(2)]
    before = snapshot.to_bytes()
    histories = [governance.history(record.admission_id) for record in records]
    gate_ = gate(governance, snapshot)

    gate_.validate(snapshot)
    gate_.validate(MemorySnapshot.from_dict(snapshot.to_dict()))

    assert snapshot.to_bytes() == before
    assert [governance.history(record.admission_id) for record in records] == histories


def test_empty_snapshot_accepts_only_empty_mapping(tmp_path: Path):
    snapshot = frozen_snapshot(count=0)
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    gate(governance, snapshot).validate(snapshot)
    refused(gate(governance, snapshot, admissions={"extra": "unknown"}), snapshot, "mapping_incomplete")


@pytest.mark.parametrize("state", ["observed", "verified", "candidate", "shadow", "approved", "deprecated", "revoked"])
def test_every_nonactive_lifecycle_state_refuses_the_entire_snapshot(tmp_path: Path, state: str):
    snapshot = frozen_snapshot(count=2)
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot)
    admit(governance, snapshot, index=1, state=state)
    before = snapshot.to_bytes()

    refused(gate(governance, snapshot), snapshot, "revoked" if state == "revoked" else "inactive")

    assert snapshot.to_bytes() == before
    assert len(snapshot.items) == 2


def test_revocation_blocks_next_use_without_changing_component_identity(tmp_path: Path):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    active = admit(governance, snapshot)
    gate_ = gate(governance, snapshot)
    before = component_fingerprint(gate_)
    gate_.validate(snapshot)
    revoked = governance.revoke(
        active.admission_id, expected_record_sha256=active.record_sha256, reason="fixture revoked",
    )

    refused(gate_, snapshot, "revoked")

    assert component_fingerprint(gate_) == before
    assert governance.get(active.admission_id) == revoked


@pytest.mark.parametrize("extra", [False, True])
def test_missing_or_extra_mapping_refuses_exact_snapshot(tmp_path: Path, extra: bool):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot)
    admissions = mapping(snapshot) | {"extra": "extra-admission"} if extra else {}
    refused(gate(governance, snapshot, admissions=admissions), snapshot, "mapping_incomplete")


def test_mapping_to_missing_head_refuses_whole_snapshot(tmp_path: Path):
    snapshot = frozen_snapshot(count=2)
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot)
    refused(gate(governance, snapshot), snapshot, "admission_missing")


def test_duplicate_admission_mapping_is_invalid_configuration(tmp_path: Path):
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    with pytest.raises(MemorySnapshotAdmissionError) as error:
        gate(governance, frozen_snapshot(count=2), admissions={"memory-0": "same", "memory-1": "same"})
    assert error.value.code == "rsi_memory_snapshot_gate_mapping_invalid"


@pytest.mark.parametrize("overrides", [
    {"memory_snapshot_sha256": digest("other snapshot")},
    {"memory_item_sha256": digest("other item")},
    {"source_episode_id": "other-episode"},
    {"verifier_receipt_sha256": digest("other verifier")},
    {"parent_snapshot_sha256": None},
    {"scope": "problem-family:other"},
    {"compatibility": {"solver": "other", "contract": PINS["contract"]}},
])
def test_active_admission_requires_exact_source_and_compatibility(tmp_path: Path, overrides: dict):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot, overrides=overrides)
    refused(gate(governance, snapshot), snapshot, "admission_drift")


@pytest.mark.parametrize("compatibility", [
    {"solver": "fixture"},
    PINS | {"extra": "pin"},
    {},
])
def test_compatibility_is_complete_match_not_subset(tmp_path: Path, compatibility: dict):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot)
    refused(gate(governance, snapshot, compatibility=compatibility), snapshot, "admission_drift")


def test_gate_cannot_authorize_different_snapshot_even_with_identical_items(tmp_path: Path):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot)
    other = replace(snapshot, snapshot_id="different")
    refused(gate(governance, snapshot), other, "snapshot_drift")


def test_inherited_item_requires_new_snapshot_admission(tmp_path: Path):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot)
    child = MemorySnapshot("child", snapshot.digest(), snapshot.items)
    refused(gate(governance, child), child, "admission_drift")


def test_unrelated_revoked_admission_does_not_change_configured_eligibility(tmp_path: Path):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot)
    other = replace(snapshot, items=(replace(snapshot.items[0], memory_id="unrelated"),))
    admit(governance, other, state="revoked")
    gate(governance, snapshot).validate(snapshot)


def test_mutable_input_configuration_and_export_do_not_change_frozen_gate(tmp_path: Path):
    snapshot = frozen_snapshot()
    pins = PINS | {"nested": {"version": 1}}
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot, overrides={"compatibility": pins})
    admissions = mapping(snapshot)
    gate_ = gate(governance, snapshot, admissions=admissions, compatibility=pins)
    before = component_fingerprint(gate_)
    admissions.clear()
    pins["nested"]["version"] = 2
    exported = gate_.rsi_fingerprint_config()
    exported["admissions"].clear()
    exported["compatibility"]["nested"]["version"] = 3

    gate_.validate(snapshot)

    assert component_fingerprint(gate_) == before


def test_database_replacement_with_same_admissions_is_refused(tmp_path: Path):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot)
    gate_ = gate(governance, snapshot)
    replacement = MemoryGovernanceStore(tmp_path / "replacement.sqlite3")
    admit(replacement, snapshot)
    replacement.database.replace(governance.database)
    refused(gate_, snapshot, "database_changed")


def test_database_path_mutation_is_refused(tmp_path: Path):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot)
    gate_ = gate(governance, snapshot)
    governance.database = tmp_path / "other.sqlite3"
    refused(gate_, snapshot, "database_changed")


@pytest.mark.parametrize("replacement", ["symlink", "hardlink", "missing"])
def test_invalid_database_identity_is_refused(tmp_path: Path, replacement: str):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot)
    gate_ = gate(governance, snapshot)
    displaced = tmp_path / "displaced.sqlite3"
    governance.database.rename(displaced)
    if replacement == "symlink":
        governance.database.symlink_to(displaced)
    elif replacement == "hardlink":
        governance.database.hardlink_to(displaced)
    refused(gate_, snapshot, "database_invalid")


def test_readonly_sqlite_uri_handles_reserved_path_characters(tmp_path: Path):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "path?#%.sqlite3")
    admit(governance, snapshot)
    gate(governance, snapshot).validate(snapshot)


@pytest.mark.parametrize("column,value", [
    ("payload", "invalid json"),
    ("state", "revoked"),
    ("record_sha256", digest("different record")),
    ("revision", 50),
    ("parent_record_sha256", digest("different parent")),
    ("created_at", "different timestamp"),
])
def test_corrupt_latest_head_is_refused(tmp_path: Path, column: str, value: object):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    active = admit(governance, snapshot)
    gate_ = gate(governance, snapshot)
    with sqlite3.connect(governance.database) as connection:
        connection.execute(
            f"UPDATE rsi_memory_governance SET {column} = ? WHERE admission_id = ? AND revision = ?",
            (value, active.admission_id, active.revision),
        )
    refused(gate_, snapshot, "storage_invalid")


@pytest.mark.parametrize("overrides", [
    {"episode_outcome": "fail"},
    {"regression_passed": False},
    {"holdout_receipt_sha256": None},
    {"baseline_receipt_sha256": None},
])
def test_active_head_without_required_evidence_is_refused(tmp_path: Path, overrides: dict):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    active = admit(governance, snapshot)
    gate_ = gate(governance, snapshot)
    corrupt = replace(active, record_sha256=None, **overrides)
    payload = json.dumps(corrupt.to_dict(), sort_keys=True, separators=(",", ":"))
    with sqlite3.connect(governance.database) as connection:
        connection.execute(
            "UPDATE rsi_memory_governance SET payload = ?, record_sha256 = ? "
            "WHERE admission_id = ? AND revision = ?",
            (payload, corrupt.digest(), active.admission_id, active.revision),
        )
    refused(gate_, snapshot, "evidence_missing")


def test_missing_governance_schema_refuses_without_recreating_table(tmp_path: Path):
    snapshot = frozen_snapshot()
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    admit(governance, snapshot)
    gate_ = gate(governance, snapshot)
    with sqlite3.connect(governance.database) as connection:
        connection.execute("DROP TABLE rsi_memory_governance")
    refused(gate_, snapshot, "storage_invalid")
    with sqlite3.connect(governance.database) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'rsi_memory_governance'",
        ).fetchone() is None
