from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution.rsi_cleanroom import (
    CandidateArtifact,
    CleanRoomVerificationRequest,
    CleanRoomVerifier,
)
from lunar_evolution.rsi_cleanroom_admission import (
    CleanRoomAdmissionError,
    CleanRoomAdmissionGate,
    CleanRoomAdmissionRequest,
)
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_memory_governance import MemoryGovernanceStore

CONTRACT = "a" * 64
TASK = b"public task"
TASK_SHA256 = hashlib.sha256(TASK).hexdigest()
SOURCE_SHA256 = hashlib.sha256(b"candidate").hexdigest()
DEPENDENCY_SHA256 = hashlib.sha256(
    b'[{"path":"lock.txt","sha256":"' + hashlib.sha256(b"v1").hexdigest().encode() + b'","size":2}]'
).hexdigest()


def evaluator_pass(context):
    assert context.source_path.read_bytes() == b"candidate"
    assert (context.dependency_dir / "lock.txt").read_bytes() == b"v1"
    return {"outcome": "pass", "evidence": {"checked": True}}


def make_verdict():
    request = CleanRoomVerificationRequest(
        episode_id="episode-1",
        candidate=CandidateArtifact(source=b"candidate", dependencies={"lock.txt": b"v1"}),
        contract_sha256=CONTRACT,
        task_input=TASK,
        task_input_sha256=TASK_SHA256,
        evaluator=evaluator_pass,
        evaluator_sha256=component_fingerprint(evaluator_pass),
    )
    return CleanRoomVerifier().verify(request)


def make_request(verdict) -> CleanRoomAdmissionRequest:
    return CleanRoomAdmissionRequest(
        admission_id="admission-1",
        memory_snapshot_sha256="b" * 64,
        memory_item_sha256="c" * 64,
        source_episode_id=verdict.episode_id,
        parent_snapshot_sha256=None,
        scope="problem-family:test",
        compatibility={"solver": "cleanroom-fixture", "contract": CONTRACT},
        contract_sha256=CONTRACT,
        expected_source_sha256=verdict.source_sha256,
        expected_dependency_sha256=verdict.dependency_sha256,
        expected_task_input_sha256=verdict.task_input_sha256,
        expected_evaluator_sha256=verdict.evaluator_sha256,
    )


def test_cleanroom_pass_enters_verified_admission_and_replays(tmp_path: Path):
    verdict = make_verdict()
    request = make_request(verdict)
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")

    current = CleanRoomAdmissionGate(governance).admit(request, verdict)
    assert current.state == "verified"
    assert current.verifier_receipt_sha256 == verdict.receipt_sha256
    assert [record.state for record in governance.history(request.admission_id)] == [
        "observed",
        "verified",
    ]
    assert CleanRoomAdmissionGate(governance).admit(request, verdict) == current


def test_cleanroom_failure_never_creates_admission(tmp_path: Path):
    verdict = make_verdict()
    failed = type(verdict)(
        verdict.episode_id,
        "fail",
        verdict.source_sha256,
        verdict.dependency_sha256,
        verdict.task_input_sha256,
        verdict.evaluator_sha256,
        verdict.evidence_sha256,
        verdict.receipt_sha256,
        "",
        verdict.actor_evidence_sha256,
    )
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    with pytest.raises(CleanRoomAdmissionError, match="verdict_not_pass"):
        CleanRoomAdmissionGate(governance).admit(make_request(verdict), failed)
    assert governance.get("admission-1") is None


def test_provenance_drift_and_reused_admission_id_fail_closed(tmp_path: Path):
    verdict = make_verdict()
    request = make_request(verdict)
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    gate = CleanRoomAdmissionGate(governance)
    gate.admit(request, verdict)

    drifted = CleanRoomAdmissionRequest(**{**request.__dict__, "expected_source_sha256": "d" * 64})
    with pytest.raises(CleanRoomAdmissionError, match="provenance_drift"):
        gate.admit(drifted, verdict)

    conflict = CleanRoomAdmissionRequest(**{**request.__dict__, "memory_item_sha256": "e" * 64})
    with pytest.raises(CleanRoomAdmissionError, match="identity_conflict"):
        gate.admit(conflict, verdict)


def test_verdict_episode_mismatch_is_rejected_before_write(tmp_path: Path):
    verdict = make_verdict()
    request = CleanRoomAdmissionRequest(
        **{**make_request(verdict).__dict__, "source_episode_id": "episode-other"}
    )
    governance = MemoryGovernanceStore(tmp_path / "rsi.sqlite3")
    with pytest.raises(CleanRoomAdmissionError, match="provenance_drift"):
        CleanRoomAdmissionGate(governance).admit(request, verdict)
    assert governance.get(request.admission_id) is None
