from __future__ import annotations

import hashlib
import multiprocessing
import time

from lunar_evolution.rsi_cleanroom import (
    CandidateArtifact,
    CleanRoomProcessVerifier,
    CleanRoomVerificationRequest,
    verify_in_subprocess,
)
from lunar_evolution.rsi_identity import component_fingerprint

_CONTRACT = "a" * 64
_TASK = b"process task"


def process_pass(context):
    return {"outcome": "pass", "evidence": {"source": context.source_sha256}}


def process_fail(context):
    del context
    return {"outcome": "fail", "evidence": {"reason": "fixture"}}


def process_slow(context):
    del context
    time.sleep(5)
    return {"outcome": "pass", "evidence": {"late": True}}


def process_raises(context):
    del context
    raise RuntimeError("fixture detail must not escape")


def process_mutates(context):
    context.source_path.chmod(0o600)
    context.source_path.write_bytes(b"tampered")
    return {"outcome": "pass", "evidence": {"mutated": True}}


def process_bytes(context):
    del context
    return {"outcome": "pass", "evidence": b"binary evidence"}


def process_large_valid_evidence(context):
    del context
    # Larger than a typical POSIX pipe buffer; the parent must drain before joining the child.
    return {"outcome": "pass", "evidence": {"payload": "x" * 100_000}}


def process_oversized_evidence(context):
    del context
    return {"outcome": "pass", "evidence": {"payload": "x" * 140_000}}


def _request(evaluator=process_pass, **kwargs):
    timeout_seconds = kwargs.pop("timeout_seconds", 0.5)
    return CleanRoomVerificationRequest(
        episode_id="process-episode",
        candidate=CandidateArtifact(source=b"candidate", dependencies={"lock": b"v1"}),
        contract_sha256=_CONTRACT,
        task_input=_TASK,
        task_input_sha256=hashlib.sha256(_TASK).hexdigest(),
        evaluator=evaluator,
        evaluator_sha256=component_fingerprint(evaluator),
        timeout_seconds=timeout_seconds,
        **kwargs,
    )


def test_process_verifier_passes_and_convenience_entrypoint():
    verdict = verify_in_subprocess(_request())
    assert verdict.outcome == "pass"
    assert verdict.contamination_reason == ""


def test_process_verifier_preserves_well_formed_failure():
    verdict = CleanRoomProcessVerifier().verify(_request(process_fail))
    assert verdict.outcome == "fail"


def test_process_verifier_hard_kills_timeout():
    started = time.monotonic()
    verdict = CleanRoomProcessVerifier().verify(_request(process_slow, timeout_seconds=0.05))
    assert time.monotonic() - started < 2
    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "evaluator_timeout"


def test_process_verifier_sanitizes_exception():
    verdict = CleanRoomProcessVerifier().verify(_request(process_raises))
    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "evaluator_exception"


def test_process_verifier_rechecks_workspace_after_child():
    verdict = CleanRoomProcessVerifier().verify(_request(process_mutates))
    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "candidate_workspace_mutated"


def test_process_verifier_round_trips_bytes_evidence():
    verdict = CleanRoomProcessVerifier().verify(_request(process_bytes))
    assert verdict.outcome == "pass"


def test_process_verifier_drains_large_valid_envelope_before_joining():
    verdict = CleanRoomProcessVerifier().verify(_request(process_large_valid_evidence, timeout_seconds=2))
    assert verdict.outcome == "pass"


def test_process_verifier_rejects_oversized_envelope():
    verdict = CleanRoomProcessVerifier().verify(_request(process_oversized_evidence, timeout_seconds=2))
    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "untrusted_evidence"


def test_process_verifier_timeout_leaves_no_live_child():
    verdict = CleanRoomProcessVerifier().verify(_request(process_slow, timeout_seconds=0.05))
    assert verdict.contamination_reason == "evaluator_timeout"
    assert not any(child.is_alive() and child.name == "lunar-cleanroom-evaluator"
                   for child in multiprocessing.active_children())


def test_process_verifier_rejects_non_importable_closure():
    marker = "closure"

    def local_evaluator(context):
        return {"outcome": "pass", "evidence": {"marker": marker, "path": str(context.workspace)}}

    verdict = CleanRoomProcessVerifier().verify(_request(local_evaluator))
    assert verdict.outcome == "unresolved"
    assert verdict.contamination_reason == "evaluator_not_importable"
