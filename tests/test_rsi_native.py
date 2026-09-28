"""Bounded native RSI gateway and clean-room verifier tests."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from test_bundle_population import build_context, draft_for_score

from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import PracticeEpisode
from lunar_evolution.rsi_native import (
    NativeEvaluationProfile,
    NativeIndependentVerifier,
    NativePopulationGateway,
    native_dependency_fingerprint,
    native_environment_fingerprint,
)

HEX = "a" * 64


def make_request(root: Path, episode_id: str = "episode-1"):
    prototype = build_context(root / "prototype")
    pipeline = prototype.bundle_pipeline
    pipeline.environment_sha256 = native_environment_fingerprint(pipeline)
    pipeline.dependency_sha256 = native_dependency_fingerprint(root, ())
    profile = NativeEvaluationProfile(prototype.contract, pipeline, root)
    request = SolverRequest.build(
        episode_id=episode_id,
        contract_sha256=prototype.contract.digest(),
        evaluator_sha256=pipeline.evaluator.digest(),
        environment_sha256=pipeline.environment_sha256,
        memory_snapshot_sha256=HEX,
        solver_id="native_population",
        solver_settings={"dependency_sha256": pipeline.dependency_sha256},
        budget={"candidate_attempts": 1},
        practice_charter={"goal": "maximize fixture value"},
    )
    return prototype, profile, request


def episode_for(request, result):
    return PracticeEpisode(
        episode_id=request.episode_id,
        run_id="run-" + request.episode_id,
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


def test_native_gateway_and_independent_verifier_rerun(tmp_path):
    _prototype, factory, request = make_request(tmp_path)
    gateway = NativePopulationGateway(factory, lambda _: draft_for_score(7), tmp_path / "gateway")
    result = gateway.run(request)
    assert result.status == "completed"
    assert result.candidate_receipt_sha256
    assert result.execution_receipt_sha256
    assert result.official_evaluation_receipt_sha256

    episode = episode_for(request, result)
    verifier = NativeIndependentVerifier(factory, tmp_path / "gateway")
    decision = verifier.verify(episode, request, result)
    assert decision.outcome == "pass"
    assert {check.name for check in decision.checks} >= {"retained_native_evidence", "independent_rerun"}

    # A completed request is read-only on retry: no new native candidate is generated.
    second = gateway.run(request)
    assert second.to_dict() == result.to_dict()


def test_native_verifier_rejects_changed_result_receipt(tmp_path):
    _prototype, factory, request = make_request(tmp_path)
    gateway = NativePopulationGateway(factory, lambda _: draft_for_score(7), tmp_path / "gateway")
    result = gateway.run(request)
    episode = episode_for(request, result)
    forged = replace(result, official_evaluation_receipt_sha256=hashlib.sha256(b"forged").hexdigest())
    decision = NativeIndependentVerifier(factory, tmp_path / "gateway").verify(episode, request, forged)
    assert decision.outcome == "unresolved"
    assert any(check.outcome == "unresolved" for check in decision.checks)


def test_native_gateway_rejects_reused_episode_with_changed_request(tmp_path):
    _prototype, factory, request = make_request(tmp_path)
    gateway = NativePopulationGateway(factory, lambda _: draft_for_score(7), tmp_path / "gateway")
    gateway.run(request)
    changed = SolverRequest.build(
        episode_id=request.episode_id,
        contract_sha256=request.contract_sha256,
        evaluator_sha256=request.evaluator_sha256,
        environment_sha256=request.environment_sha256,
        memory_snapshot_sha256=HEX,
        solver_id=request.solver_id,
        solver_settings={"dependency_sha256": request.solver_settings[0][1], "changed": True},
        practice_charter=dict(request.practice_charter),
    )
    with pytest.raises(Exception, match="rsi_native_request_reuse"):
        gateway.run(changed)


def native_run(tmp_path, *, score=7, source=None):
    _prototype, profile, request = make_request(tmp_path)
    factory = lambda _: draft_for_score(score) if source is None else source
    gateway = NativePopulationGateway(profile, factory, tmp_path / "gateway")
    result = gateway.run(request)
    assert result.status == "completed"
    return profile, request, gateway, result, episode_for(request, result)


@pytest.mark.parametrize("material", ["helper", "receipt", "execution", "evaluation", "plan", "harness", "input"])
def test_verifier_rejects_changed_retained_material(tmp_path, material):
    import json
    profile, request, gateway, result, episode = native_run(tmp_path)
    root = gateway.workspace_root / "episodes" / request.episode_id
    receipt = json.loads((root / "native-candidate.json").read_text())
    paths = {
        "helper": root / receipt["source_root"] / "solve/helper.py",
        "receipt": root / "native-candidate.json",
        "execution": root / receipt["run_root"] / "attempt/completed.json",
        "evaluation": root / receipt["evaluation_path"] / "report.json",
        "plan": root / receipt["run_root"] / "plan.json",
        "harness": profile.pipeline.harness_path,
        "input": profile.pipeline.input_root / "value",
    }
    path = paths[material]
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b" ")
    decision = NativeIndependentVerifier(profile, gateway.workspace_root).verify(episode, request, result)
    assert decision.outcome == "unresolved"
    assert not (gateway.workspace_root / "verifications").exists()


@pytest.mark.parametrize("material", ["source", "receipt", "execution", "evaluation"])
def test_verifier_rejects_same_bytes_inode_replacement(tmp_path, material):
    import json
    profile, request, gateway, result, episode = native_run(tmp_path)
    root = gateway.workspace_root / "episodes" / request.episode_id
    receipt = json.loads((root / "native-candidate.json").read_text())
    paths = {
        "source": root / receipt["source_root"] / "solve/helper.py",
        "receipt": root / "native-candidate.json",
        "execution": root / receipt["run_root"] / "attempt/result.json",
        "evaluation": root / receipt["evaluation_path"] / "report.json",
    }
    path = paths[material]
    before = path.stat().st_ino
    path.rename(path.with_suffix(".old"))
    path.write_bytes(path.with_suffix(".old").read_bytes())
    assert path.stat().st_ino != before
    decision = NativeIndependentVerifier(profile, gateway.workspace_root).verify(episode, request, result)
    assert decision.outcome == "unresolved"


def test_invalid_official_candidate_fails_without_rerun(tmp_path):
    profile, request, gateway, result, episode = native_run(tmp_path, score=999)
    decision = NativeIndependentVerifier(profile, gateway.workspace_root).verify(episode, request, result)
    assert decision.outcome == "fail"
    assert not (gateway.workspace_root / "verifications").exists()


def test_missing_native_receipt_and_fake_fixture_digests_cannot_pass(tmp_path):
    from lunar_evolution.rsi_gateway import DeterministicMockSolver
    _prototype, profile, request = make_request(tmp_path)
    result = DeterministicMockSolver().run(request)
    decision = NativeIndependentVerifier(profile, tmp_path / "gateway").verify(episode_for(request, result), request, result)
    assert decision.outcome == "unresolved"


def test_dependency_bytes_and_environment_are_rechecked(tmp_path):
    _prototype, profile, request = make_request(tmp_path)
    lockfile = tmp_path / "requirements.lock"
    lockfile.write_text("local-only==1\n")
    profile = replace(profile, dependency_paths=("requirements.lock",))
    profile.pipeline.dependency_sha256 = native_dependency_fingerprint(tmp_path, profile.dependency_paths)
    request = replace(request, solver_settings=(("dependency_sha256", profile.pipeline.dependency_sha256),))
    gateway = NativePopulationGateway(profile, lambda _: draft_for_score(7), tmp_path / "gateway")
    result = gateway.run(request)
    episode = episode_for(request, result)
    lockfile.write_text("local-only==2\n")
    assert NativeIndependentVerifier(profile, gateway.workspace_root).verify(episode, request, result).outcome == "unresolved"
    lockfile.write_text("local-only==1\n")
    profile.pipeline.environment = (("CHANGED", "1"),)
    assert NativeIndependentVerifier(profile, gateway.workspace_root).verify(episode, request, result).outcome == "unresolved"


def test_intent_interruption_remains_unknown_without_new_candidate(tmp_path):
    from lunar_evolution.candidate_evaluation_spec import canonical_json
    _prototype, profile, request = make_request(tmp_path)
    root = tmp_path / "gateway/episodes" / request.episode_id
    root.mkdir(parents=True)
    (root / "native-intent.json").write_bytes(canonical_json({"protocol": "lunar-rsi-native-v1", "request": request.to_dict()}))
    gateway = NativePopulationGateway(profile, lambda _: pytest.fail("must not replay"), tmp_path / "gateway")
    assert gateway.run(request).status == "unknown"
    assert not (root / "native-result.json").exists()


def test_failed_candidate_is_terminal_unknown_and_retry_never_reexecutes(tmp_path):
    from lunar_evolution.evolution import CandidateDraft
    _prototype, profile, request = make_request(tmp_path)
    calls = []

    def fail_candidate(_request):
        calls.append(1)
        return CandidateDraft("raise RuntimeError('failed')\n", "main.py")

    gateway = NativePopulationGateway(profile, fail_candidate, tmp_path / "gateway")
    result = gateway.run(request)
    assert result.status == "unknown"
    assert gateway.run(request) == result
    assert calls == [1]
    decision = NativeIndependentVerifier(profile, gateway.workspace_root).verify(episode_for(request, result), request, result)
    assert decision.outcome == "unresolved"


def test_shared_wall_budget_stops_slow_candidate(tmp_path):
    from lunar_evolution.evolution import CandidateDraft
    _prototype, profile, request = make_request(tmp_path)
    request = replace(request, budget=(("wall_timeout_seconds", 0.02),))
    gateway = NativePopulationGateway(profile, lambda _: CandidateDraft("import time\ntime.sleep(10)\n", "main.py"), tmp_path / "gateway")
    result = gateway.run(request)
    assert result.status == "timed_out"
    assert gateway.run(request) == result


def test_clean_room_detects_nonrepeatable_candidate(tmp_path):
    from lunar_evolution.evolution import CandidateDraft
    _prototype, profile, request = make_request(tmp_path)
    actor_path = str(tmp_path / "gateway")
    source = f'''import json
from pathlib import Path
Path("output").mkdir()
value = 7 if {actor_path!r} in str(Path.cwd()) else 8
Path("output/result.json").write_text(json.dumps({{"value": value}}))
'''
    # A distinct verifier root makes any behavior coupled to the actor workspace observable.
    gateway = NativePopulationGateway(profile, lambda _: CandidateDraft(source, "main.py"), tmp_path / "gateway")
    result = gateway.run(request)
    verifier = NativeIndependentVerifier(profile, gateway.workspace_root, verification_root=tmp_path / "independent")
    decision = verifier.verify(episode_for(request, result), request, result)
    assert decision.outcome == "unresolved"
    assert list((tmp_path / "independent").rglob("verifier-receipt.json"))


def test_verified_rerun_is_retained_and_original_files_are_read_only(tmp_path):
    profile, request, gateway, result, episode = native_run(tmp_path)
    root = gateway.workspace_root / "episodes" / request.episode_id
    original = {p.relative_to(root): (p.read_bytes(), p.stat().st_ino) for p in root.rglob("*") if p.is_file()}
    verifier = NativeIndependentVerifier(profile, gateway.workspace_root)
    assert verifier.verify(episode, request, result).outcome == "pass"
    assert original == {p.relative_to(root): (p.read_bytes(), p.stat().st_ino) for p in root.rglob("*") if p.is_file()}
    receipts = list(verifier.verification_root.rglob("verifier-receipt.json"))
    assert len(receipts) == 1
    assert list(verifier.verification_root.rglob("evaluation.json"))


def test_native_controller_integration_uses_explicit_independent_verifier(tmp_path):
    from lunar_evolution.rsi_controller import RSILearningController
    _prototype, profile, request = make_request(tmp_path)
    gateway = NativePopulationGateway(profile, lambda _: draft_for_score(7), tmp_path / "gateway")
    verifier = NativeIndependentVerifier(profile, gateway.workspace_root)
    controller = RSILearningController(gateway, verifier=verifier)
    result = controller.run_drs(
        run_id="native-controller", contract_sha256=request.contract_sha256,
        evaluator_sha256=request.evaluator_sha256, environment_sha256=request.environment_sha256,
        solver_id="native_population", max_target_attempts=1,
    )
    assert result.status == "completed"
    assert result.target_attempts[0].episode.verifier.outcome == "pass"
