from __future__ import annotations

import hashlib
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.rsi_cleanroom import (
    CandidateArtifact,
    CleanRoomError,
    CleanRoomEvaluation,
    CleanRoomVerificationRequest,
    CleanRoomVerifier,
)
from lunar_evolution.rsi_identity import component_fingerprint

CONTRACT = "a" * 64
TASK = b"public task input"
TASK_DIGEST = hashlib.sha256(TASK).hexdigest()


def evaluator_pass(context):
    assert context.task_input == TASK
    assert context.source_path.read_bytes() == b"candidate-v1"
    assert (context.dependency_dir / "lock.txt").read_bytes() == b"dependency-v1"
    assert not (context.workspace / "private-input.bin").exists()
    return {"outcome": "pass", "evidence": {"checked": True}}


def evaluator_fail(context):
    del context
    return CleanRoomEvaluation("fail", {"reason": "candidate does not satisfy contract"})


def evaluator_mutates(context):
    context.source_path.chmod(0o600)
    context.source_path.write_bytes(b"tampered")
    return {"outcome": "pass", "evidence": {"checked": True}}


def evaluator_mutates_input(context):
    path = context.workspace / "input" / "task.bin"
    path.chmod(0o600)
    path.write_bytes(b"changed task")
    return {"outcome": "pass", "evidence": {"checked": True}}


def evaluator_raises(context):
    del context
    raise RuntimeError("private implementation detail")


def evaluator_slow(context):
    del context
    time.sleep(0.2)
    return {"outcome": "pass", "evidence": {"checked": True}}


def evaluator_untrusted(context):
    del context
    return {"outcome": "pass", "evidence": {"checked": True}, "solver_score": 999}


def make_request(evaluator=evaluator_pass, **kwargs):
    candidate = kwargs.pop(
        "candidate",
        CandidateArtifact(source=b"candidate-v1", dependencies={"lock.txt": b"dependency-v1"}),
    )
    return CleanRoomVerificationRequest(
        episode_id="episode-cleanroom-1",
        candidate=candidate,
        contract_sha256=CONTRACT,
        task_input=TASK,
        task_input_sha256=TASK_DIGEST,
        evaluator=evaluator,
        evaluator_sha256=component_fingerprint(evaluator),
        actor_evidence={"solver_score": 1.0, "actor_receipt": "not-authority"},
        **kwargs,
    )


def test_clean_room_rebuilds_candidate_and_passes_independent_evidence():
    verdict = CleanRoomVerifier().verify(make_request())

    assert verdict.outcome == "pass"
    assert verdict.contamination_reason == ""
    assert verdict.source_sha256 == hashlib.sha256(b"candidate-v1").hexdigest()
    assert verdict.dependency_sha256
    assert verdict.evidence_sha256 != verdict.actor_evidence_sha256
    assert len(verdict.receipt_sha256) == 64


def test_clean_room_well_formed_failure_is_failure():
    verdict = CleanRoomVerifier().verify(make_request(evaluator_fail))

    assert verdict.outcome == "fail"
    assert verdict.contamination_reason == ""


def test_actor_score_and_extra_evaluator_fields_cannot_authorize_pass():
    verdict = CleanRoomVerifier().verify(make_request(evaluator_untrusted))

    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "untrusted_evidence"


def test_evaluator_exception_is_unresolved_without_leaking_exception_text():
    verdict = CleanRoomVerifier().verify(make_request(evaluator_raises))

    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "evaluator_exception"
    assert "private" not in verdict.contamination_reason


def test_evaluator_timeout_is_unresolved():
    verdict = CleanRoomVerifier().verify(make_request(evaluator_slow, timeout_seconds=0.01))

    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "evaluator_timeout"


def test_candidate_workspace_mutation_is_unresolved():
    verdict = CleanRoomVerifier().verify(make_request(evaluator_mutates))

    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "candidate_workspace_mutated"


def test_public_input_mutation_cannot_authorize_pass():
    verdict = CleanRoomVerifier().verify(make_request(evaluator_mutates_input))
    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "candidate_workspace_mutated"


@pytest.mark.parametrize("evaluator", [evaluator_pass, evaluator_raises])
def test_contract_and_private_input_are_bound_to_verdict(evaluator):
    request = make_request(evaluator)
    verifier = CleanRoomVerifier()
    original = verifier.verify(request)
    changed_contract = verifier.verify(replace(
        request, contract_sha256="f" * 64, actor_evidence=dict(request.actor_evidence),
    ))
    changed_private_input = verifier.verify(replace(
        request, private_input_sha256="e" * 64, actor_evidence=dict(request.actor_evidence),
    ))
    assert len({verdict.receipt_sha256 for verdict in (
        original, changed_contract, changed_private_input,
    )}) == 3


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable")
def test_fifo_source_is_rejected_without_waiting_for_writer(tmp_path):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    verdict = CleanRoomVerifier().verify(make_request(candidate=CandidateArtifact(source_path=fifo)))
    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "source_path_invalid"


@pytest.mark.parametrize("name", [".", "a//b", "a/./b", "a/"])
def test_dependency_aliases_are_rejected_before_materialization(name):
    with pytest.raises(CleanRoomError, match="dependency_path_invalid"):
        CandidateArtifact(source=b"x", dependencies={name: b"dependency"})


def test_expected_artifact_digest_detects_changed_source():
    candidate = CandidateArtifact(
        source=b"candidate-v1",
        dependencies={"lock.txt": b"dependency-v1"},
        expected_source_sha256=hashlib.sha256(b"candidate-v2").hexdigest(),
    )

    verdict = CleanRoomVerifier().verify(make_request(candidate=candidate))

    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "source_digest_mismatch"


def test_source_path_is_copied_and_symlink_is_rejected(tmp_path: Path):
    source = tmp_path / "candidate.bin"
    source.write_bytes(b"candidate-v1")
    request = make_request(candidate=CandidateArtifact(source_path=source, dependencies={"lock.txt": b"dependency-v1"}))
    assert CleanRoomVerifier().verify(request).outcome == "pass"

    link = tmp_path / "link.bin"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlinks unavailable")
    verdict = CleanRoomVerifier().verify(
        make_request(candidate=CandidateArtifact(source_path=link, dependencies={"lock.txt": b"dependency-v1"}))
    )
    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "source_path_invalid"


def test_private_input_is_metadata_only_and_never_in_context():
    marker = hashlib.sha256(b"verifier-private").hexdigest()

    def evaluator(context):
        assert not (context.workspace / "private-input.bin").exists()
        return {"outcome": "pass", "evidence": {"private_digest": marker}}

    request = make_request(evaluator, private_input_sha256=marker)
    assert CleanRoomVerifier().verify(request).outcome == "pass"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source": b"x", "source_path": "/tmp/nope"},
        {"source": None, "source_path": None},
        {"source": b"x", "dependencies": {"../escape": b"x"}},
    ],
)
def test_candidate_input_validation_fails_closed(kwargs):
    with pytest.raises(CleanRoomError):
        CandidateArtifact(**kwargs)


def test_task_input_digest_and_evaluator_pin_are_required():
    with pytest.raises(CleanRoomError, match="task_input_invalid"):
        CleanRoomVerificationRequest(
            "episode",
            CandidateArtifact(source=b"x"),
            CONTRACT,
            TASK,
            "b" * 64,
            evaluator_pass,
            component_fingerprint(evaluator_pass),
        )
    request = make_request()
    drifted = CleanRoomVerificationRequest(
        request.episode_id,
        request.candidate,
        request.contract_sha256,
        request.task_input,
        request.task_input_sha256,
        request.evaluator,
        "b" * 64,
    )
    verdict = CleanRoomVerifier().verify(drifted)
    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "evaluator_fingerprint_mismatch"
