"""Focused tests for the public bounded RSI clean-room verifier facade."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from test_bundle_population import build_context, draft_for_score

from lunar_evolution.rsi_clean_room import CleanRoomRSIVerifier
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import PracticeEpisode
from lunar_evolution.rsi_native import (
    NativeEvaluationProfile,
    NativePopulationGateway,
    native_dependency_fingerprint,
    native_environment_fingerprint,
)


def _run(tmp_path: Path):
    prototype = build_context(tmp_path / "prototype")
    pipeline = prototype.bundle_pipeline
    pipeline.environment_sha256 = native_environment_fingerprint(pipeline)
    pipeline.dependency_sha256 = native_dependency_fingerprint(tmp_path, ())
    profile = NativeEvaluationProfile(prototype.contract, pipeline, tmp_path)
    request = SolverRequest.build(
        episode_id="clean-room-1",
        contract_sha256=prototype.contract.digest(),
        evaluator_sha256=pipeline.evaluator.digest(),
        environment_sha256=pipeline.environment_sha256,
        memory_snapshot_sha256="a" * 64,
        solver_id="native_population",
        solver_settings={"dependency_sha256": pipeline.dependency_sha256},
        budget={"candidate_attempts": 1},
    )
    gateway = NativePopulationGateway(profile, lambda _: draft_for_score(7), tmp_path / "gateway")
    result = gateway.run(request)
    episode = PracticeEpisode(
        episode_id=request.episode_id,
        run_id="run-clean-room",
        contract_sha256=request.contract_sha256,
        evaluator_sha256=request.evaluator_sha256,
        environment_sha256=request.environment_sha256,
        memory_snapshot_sha256=request.memory_snapshot_sha256,
        solver_id=request.solver_id,
        status=result.status,
        request_sha256=request.digest(),
        candidate_receipt_sha256=result.candidate_receipt_sha256,
        execution_receipt_sha256=result.execution_receipt_sha256,
        official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
        candidate_source_sha256=result.candidate_source_sha256,
        dependency_sha256=result.dependency_sha256,
        trace_digest=result.trace_digest,
        terminal_reason=result.terminal_reason,
    )
    return profile, request, result, episode, gateway


def test_clean_room_recomputes_pins_and_replays(tmp_path: Path):
    profile, request, result, episode, gateway = _run(tmp_path)
    verifier = CleanRoomRSIVerifier(profile, gateway.workspace_root, verification_root=tmp_path / "verify")

    pins = verifier.reopen_fingerprints(episode, request, result)
    assert pins.source_sha256 == result.candidate_source_sha256
    assert pins.dependency_sha256 == result.dependency_sha256
    assert pins.contract_sha256 == request.contract_sha256
    assert pins.evaluator_sha256 == request.evaluator_sha256
    assert pins.environment_sha256 == request.environment_sha256

    decision = verifier.verify(episode, request, result)
    assert decision.outcome == "pass"
    assert {check.name for check in decision.checks} >= {
        "source_fingerprint",
        "dependency_fingerprint",
        "contract_fingerprint",
        "environment_fingerprint",
        "independent_rerun",
    }
    verifier.validate_retained(episode, request, result, decision)


def test_clean_room_fingerprint_is_wrapper_specific(tmp_path: Path):
    profile, request, result, episode, gateway = _run(tmp_path)
    verifier = CleanRoomRSIVerifier(profile, gateway.workspace_root, verification_root=tmp_path / "verify")
    assert verifier.fingerprint() != verifier._delegate.fingerprint()
    decision = verifier.verify(episode, request, result)
    verifier.validate_retained(episode, request, result, decision)


def test_clean_room_reopen_failure_cannot_fall_back_to_delegate_pass(tmp_path: Path, monkeypatch):
    profile, request, result, episode, gateway = _run(tmp_path)
    verifier = CleanRoomRSIVerifier(profile, gateway.workspace_root, verification_root=tmp_path / "verify")
    approved = verifier.verify(episode, request, result)
    assert approved.outcome == "pass"

    def fail_reopen(*_args, **_kwargs):
        raise RuntimeError("reopen failed")

    monkeypatch.setattr(verifier, "reopen_fingerprints", fail_reopen)
    monkeypatch.setattr(verifier._delegate, "verify", lambda *_args, **_kwargs: approved)
    decision = verifier.verify(episode, request, result)
    assert decision.outcome == "unresolved"
    assert decision.verifier_fingerprint == verifier.fingerprint()


def test_clean_room_rejects_profile_environment_drift(tmp_path: Path):
    profile, request, result, episode, gateway = _run(tmp_path)
    profile.pipeline.environment = (("RSI_CLEAN_ROOM_DRIFT", "1"),)
    verifier = CleanRoomRSIVerifier(profile, gateway.workspace_root, verification_root=tmp_path / "verify")

    decision = verifier.verify(episode, request, result)
    assert decision.outcome == "unresolved"
    assert all(check.outcome != "pass" for check in decision.checks)


def test_clean_room_does_not_accept_forged_source_digest(tmp_path: Path):
    profile, request, result, episode, gateway = _run(tmp_path)
    forged = replace(result, candidate_source_sha256="b" * 64)
    verifier = CleanRoomRSIVerifier(profile, gateway.workspace_root, verification_root=tmp_path / "verify")

    decision = verifier.verify(episode, request, forged)
    assert decision.outcome == "unresolved"
