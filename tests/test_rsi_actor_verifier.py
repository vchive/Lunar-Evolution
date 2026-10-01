"""Local fixture Actor candidates are independently evaluated in a spawn process."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_actor import AgentLoopActorGateway
from lunar_evolution.rsi_actor_verifier import AgentLoopCleanRoomVerifier
from lunar_evolution.rsi_controller import PracticeEpisodeRunner
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT_SHA256,
    PracticeEpisode,
    RSILearningError,
)
from lunar_evolution.runtime import RuntimeResult

SOURCE = b"def solve(value):\n    return value + 1\n"
CONTRACT = "a" * 64
ENVIRONMENT = "b" * 64


def trusted_evaluator(context):
    # This deterministic local wrapper is the authority; the Actor's score is unused.
    namespace = {}
    exec(compile(context.source_path.read_bytes(), str(context.source_path), "exec"), namespace)  # noqa: S102 - intentionally evaluate the fixed local candidate fixture
    value = int(context.task_input)
    passed = namespace["solve"](value) == value + 1
    return {"outcome": "pass" if passed else "fail", "evidence": {
        "source_sha256": context.source_sha256, "input_sha256": context.task_input_sha256,
        "isolated": not (context.workspace / "actor-private.txt").exists(),
    }}


def failing_evaluator(context):
    return {"outcome": "fail", "evidence": {"source_sha256": context.source_sha256}}


def slow_evaluator(context):
    time.sleep(5)
    return {"outcome": "pass", "evidence": {"late": True}}


def raising_evaluator(context):
    raise RuntimeError("private evaluator detail must not escape")


def mutating_evaluator(context):
    context.source_path.chmod(0o600)
    context.source_path.write_bytes(b"mutated")
    return {"outcome": "pass", "evidence": {"claimed": True}}


class RuntimeFixture:
    name = "actor-cleanroom-fixture"

    def __init__(self, source: bytes = SOURCE, candidate_path="candidate.py", dependencies=None):
        self.source = source
        self.candidate_path = candidate_path
        self.dependencies = {"requirements.txt": b"fixture==1\n"} if dependencies is None else dependencies

    def run(self, prompt, workspace, timeout=None, **kwargs):
        destination = workspace / self.candidate_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.source)
        for name, data in self.dependencies.items():
            dependency = workspace / name
            dependency.parent.mkdir(parents=True, exist_ok=True)
            dependency.write_bytes(data)
        (workspace / "actor-private.txt").write_text("private Actor response")
        return RuntimeResult("private Actor final response", (self.candidate_path,), {})


def actor_receipts(request, workspace, result, trace):
    return {"candidate_receipt_sha256": "1" * 64, "execution_receipt_sha256": "2" * 64,
            "official_evaluation_receipt_sha256": "3" * 64, "solver_score": 999.0}


def fixture(tmp_path: Path, evaluator=trusted_evaluator, **kwargs):
    task = kwargs.pop("task_input", b"5")
    bridge = AgentLoopCleanRoomVerifier(
        tmp_path, task_input=task, evaluator=evaluator, evaluator_sha256=component_fingerprint(evaluator),
        contract_sha256=CONTRACT, environment_sha256=ENVIRONMENT, **kwargs,
    )
    request = SolverRequest.build(
        episode_id="practice-1", contract_sha256=CONTRACT,
        evaluator_sha256=component_fingerprint(evaluator), environment_sha256=ENVIRONMENT,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT_SHA256, solver_id="lunar-agent-loop",
    )
    episode = PracticeEpisode(
        request.episode_id, "local-run", request.contract_sha256, request.evaluator_sha256,
        request.environment_sha256, request.memory_snapshot_sha256, request.solver_id, "planned",
    )
    return bridge, episode, request


def completed(tmp_path: Path, evaluator=trusted_evaluator, *, runtime=None, **kwargs):
    bridge, episode, request = fixture(tmp_path, evaluator, **kwargs)
    runtime = runtime or RuntimeFixture(candidate_path=bridge.candidate_path,
                                        dependencies={name: b"fixture==1\n" for name in bridge.dependency_paths})
    gateway = AgentLoopActorGateway(lambda: runtime, tmp_path, candidate_paths=(bridge.candidate_path,),
                                   dependency_paths=bridge.dependency_paths, receipt_builder=actor_receipts)
    result = gateway.run(request)
    finished = episode.transition("running", request_sha256=request.digest()).transition(
        "completed", **{key: getattr(result, key) for key in (
            "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256",
            "trace_digest", "candidate_source_sha256", "dependency_sha256", "actor_fingerprint", "trace_events",
        )},
    )
    return bridge, finished, request, result


def forbid_evaluation(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("invalid input must fail before any clean-room evaluation")

    monkeypatch.setattr("lunar_evolution.rsi_actor_verifier.CleanRoomProcessVerifier.verify", unexpected)


def test_practice_runner_accepts_independent_fixture_pass_and_separates_raw_manifest_digests(tmp_path: Path):
    bridge, episode, request = fixture(tmp_path)
    gateway = AgentLoopActorGateway(lambda: RuntimeFixture(), tmp_path, receipt_builder=actor_receipts)
    before = component_fingerprint(bridge)
    execution = PracticeEpisodeRunner(gateway, bridge).run(episode, request)
    assert execution.passed
    assert execution.episode.to_record_dict()["verifier"]["outcome"] == "pass"
    assert execution.verifier.independent_of_actor
    assert execution.verifier.official_evaluation_receipt_sha256 == "3" * 64
    assert {check.name for check in execution.verifier.checks} == {
        "actor_cleanroom_evidence", "cleanroom_evaluator", "official_evaluator",
    }
    decision, evidence = bridge.verify_with_evidence(execution.episode, request, execution.result)
    assert decision.outcome == "pass"
    assert evidence.verdict.outcome == "pass"
    raw_source = hashlib.sha256(SOURCE).hexdigest()
    actor_manifest = hashlib.sha256(canonical_json([("candidate.py", raw_source)])).hexdigest()
    assert evidence.source_sha256 == raw_source
    assert evidence.candidate_manifest_sha256 == actor_manifest == execution.result.candidate_source_sha256
    assert actor_manifest != raw_source
    assert evidence.dependency_sha256 != evidence.dependency_manifest_sha256
    assert evidence.verdict.source_sha256 == raw_source
    assert evidence.verdict.dependency_sha256 == evidence.dependency_sha256
    assert decision.checks[0].receipt_sha256 == evidence.digest()
    assert decision.checks[1].receipt_sha256 == evidence.verdict.receipt_sha256
    assert decision.receipt_sha256 != execution.result.official_evaluation_receipt_sha256
    assert "private Actor" not in str(evidence.to_dict()) + str(decision.to_dict())
    assert component_fingerprint(bridge) == before


def test_independent_failure_overrules_actor_success_and_score(tmp_path: Path):
    bridge, episode, request, result = completed(tmp_path, failing_evaluator)
    assert result.status == "completed" and result.solver_score == 999.0
    decision, evidence = bridge.verify_with_evidence(episode, request, result)
    assert decision.outcome == "fail"
    assert evidence.verdict.outcome == "fail"
    assert episode.attach_verifier(decision).verifier.outcome == "fail"


@pytest.mark.parametrize("evaluator,reason", [
    (slow_evaluator, "evaluator_timeout"), (raising_evaluator, "evaluator_exception"),
    (mutating_evaluator, "candidate_workspace_mutated"),
])
def test_process_failure_timeout_and_mutation_are_unresolved(tmp_path: Path, evaluator, reason):
    bridge, episode, request, result = completed(
        tmp_path, evaluator, timeout_seconds=0.05 if evaluator is slow_evaluator else 2,
    )
    decision, evidence = bridge.verify_with_evidence(episode, request, result)
    assert decision.outcome == "unresolved"
    assert evidence.verdict.contamination_reason == reason
    assert "private evaluator detail" not in str(decision.to_dict()) + str(evidence.to_dict())
    assert not any(child.is_alive() and child.name == "lunar-cleanroom-evaluator"
                   for child in multiprocessing.active_children())


@pytest.mark.parametrize("change", [
    "failed", "unknown", "missing_receipt", "request", "contract", "environment",
    "evaluator", "actor_fingerprint", "manifest", "episode_request",
])
def test_identity_status_receipt_and_pin_gates_precede_evaluator(tmp_path: Path, monkeypatch, change: str):
    bridge, episode, request, result = completed(tmp_path)
    if change in {"failed", "unknown"}:
        result = replace(result, status=change)
    elif change == "missing_receipt":
        result = replace(result, execution_receipt_sha256=None)
    elif change == "request":
        result = replace(result, request_sha256="9" * 64)
    elif change in {"contract", "environment", "evaluator"}:
        request = replace(request, **{change + "_sha256": "9" * 64})
    elif change == "actor_fingerprint":
        result = replace(result, actor_fingerprint="9" * 64)
    elif change == "manifest":
        result = replace(result, candidate_source_sha256="9" * 64)
        episode = replace(episode, candidate_source_sha256="9" * 64)
    else:
        episode = replace(episode, request_sha256="9" * 64)
    forbid_evaluation(monkeypatch)
    decision, evidence = bridge.verify_with_evidence(episode, request, result)
    assert decision.outcome == "unresolved"
    assert evidence.verdict is None


@pytest.mark.parametrize("artifact", ["candidate.py", "requirements.txt"])
def test_actor_artifact_tampering_fails_before_evaluation(tmp_path: Path, monkeypatch, artifact: str):
    bridge, episode, request, result = completed(tmp_path)
    (tmp_path / "episodes" / episode.episode_id / artifact).write_bytes(b"changed artifact")
    forbid_evaluation(monkeypatch)
    decision, evidence = bridge.verify_with_evidence(episode, request, result)
    assert decision.outcome == "unresolved"
    assert decision.diagnosis == "rsi_actor_cleanroom_artifact_manifest_drift"
    assert evidence.verdict is None


@pytest.mark.parametrize("kind", ["source_symlink", "dependency_symlink", "episode_symlink", "episodes_symlink", "parent_symlink", "missing", "directory", "fifo"])
def test_actor_workspace_reads_are_nofollow_and_regular(tmp_path: Path, monkeypatch, kind: str):
    candidate_path = "src/candidate.py" if kind == "parent_symlink" else "candidate.py"
    bridge, episode, request, result = completed(tmp_path, candidate_path=candidate_path)
    workspace = tmp_path / "episodes" / episode.episode_id
    if kind in {"source_symlink", "dependency_symlink"}:
        path = workspace / (candidate_path if kind == "source_symlink" else "requirements.txt")
        copy = workspace / "copy"
        path.rename(copy)
        path.symlink_to(copy)
    elif kind == "parent_symlink":
        (workspace / "src").rename(workspace / "real-src")
        (workspace / "src").symlink_to(workspace / "real-src", target_is_directory=True)
    elif kind in {"episode_symlink", "episodes_symlink"}:
        path = workspace if kind == "episode_symlink" else tmp_path / "episodes"
        destination = tmp_path / "retained"
        path.rename(destination)
        path.symlink_to(destination, target_is_directory=True)
    else:
        path = workspace / candidate_path
        path.unlink()
        if kind == "directory":
            path.mkdir()
        elif kind == "fifo":
            os.mkfifo(path)
    forbid_evaluation(monkeypatch)
    decision, evidence = bridge.verify_with_evidence(episode, request, result)
    assert decision.outcome == "unresolved"
    assert evidence.verdict is None


def test_byte_limits_are_enforced_before_evaluation(tmp_path: Path, monkeypatch):
    bridge, episode, request, result = completed(tmp_path)
    monkeypatch.setattr("lunar_evolution.rsi_actor_verifier.MAX_SOURCE_BYTES", 4)
    forbid_evaluation(monkeypatch)
    assert bridge.verify(episode, request, result).outcome == "unresolved"


def test_dependency_aggregate_budget_is_checked_before_reading_the_next_file(tmp_path: Path, monkeypatch):
    bridge, episode, request, result = completed(
        tmp_path, dependency_paths=("first.lock", "second.lock"),
        runtime=RuntimeFixture(dependencies={"first.lock": b"x" * 9, "second.lock": b"y" * 9}),
    )
    monkeypatch.setattr("lunar_evolution.rsi_actor_verifier.MAX_DEPENDENCY_BYTES", 16)
    forbid_evaluation(monkeypatch)
    assert bridge.verify(episode, request, result).outcome == "unresolved"


@pytest.mark.parametrize("replacement", ["file", "parent", "workspace", "episodes", "root"])
def test_same_content_path_replacement_during_read_is_rejected(tmp_path: Path, monkeypatch, replacement: str):
    root = tmp_path / "root"
    candidate_path = "src/candidate.py" if replacement == "parent" else "candidate.py"
    bridge, episode, request, result = completed(root, candidate_path=candidate_path)
    workspace = root / "episodes" / episode.episode_id
    original_read = os.read
    swapped = False

    def replace_after_read(descriptor, size):
        nonlocal swapped
        data = original_read(descriptor, size)
        if size > 1 and not swapped:
            swapped = True
            path = {
                "file": workspace / candidate_path, "parent": workspace / "src",
                "workspace": workspace, "episodes": root / "episodes", "root": root,
            }[replacement]
            retained = path.with_name(path.name + "-original")
            path.rename(retained)
            if replacement == "file":
                path.write_bytes(SOURCE)
            else:
                path.mkdir()
                if replacement == "parent":
                    (path / "candidate.py").write_bytes(SOURCE)
        return data

    monkeypatch.setattr("lunar_evolution.rsi_actor_verifier.os.read", replace_after_read)
    forbid_evaluation(monkeypatch)
    decision = bridge.verify(episode, request, result)
    assert swapped and decision.outcome == "unresolved"
    assert decision.diagnosis == "rsi_actor_cleanroom_artifact_drift"


def test_final_workspace_root_symlink_is_not_resolved_away(tmp_path: Path, monkeypatch):
    root = tmp_path / "actual"
    _, episode, request, result = completed(root)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    bridge, _, _ = fixture(alias)
    assert bridge.workspace_root == alias
    forbid_evaluation(monkeypatch)
    assert bridge.verify(episode, request, result).outcome == "unresolved"


def test_cleanroom_verdict_binding_is_checked_before_accepting_pass(tmp_path: Path, monkeypatch):
    bridge, episode, request, result = completed(tmp_path)
    from lunar_evolution.rsi_cleanroom import CleanRoomVerdict

    def forged_verdict(self, verification):
        return CleanRoomVerdict(
            episode.episode_id, "pass", "9" * 64, "9" * 64,
            verification.task_input_sha256, verification.evaluator_sha256,
            "9" * 64, "9" * 64, actor_evidence_sha256=verification.actor_evidence_sha256,
        )

    monkeypatch.setattr("lunar_evolution.rsi_actor_verifier.CleanRoomProcessVerifier.verify", forged_verdict)
    decision, evidence = bridge.verify_with_evidence(episode, request, result)
    assert decision.outcome == "unresolved"
    assert decision.diagnosis == "rsi_actor_cleanroom_verdict_binding_drift"
    assert evidence.verdict is None


def test_frozen_task_input_and_live_evaluator_drift_gate(tmp_path: Path, monkeypatch):
    task = bytearray(b"5")
    bridge, episode, request, result = completed(tmp_path, task_input=task)
    task[0] = ord("8")
    assert bridge.task_input == b"5"
    fingerprint = component_fingerprint(bridge)
    bridge.evaluator = failing_evaluator
    assert component_fingerprint(bridge) != fingerprint
    forbid_evaluation(monkeypatch)
    assert bridge.verify(episode, request, result).outcome == "unresolved"


def test_explicit_empty_dependencies_are_supported_with_distinct_cleanroom_digest(tmp_path: Path):
    bridge, episode, request, result = completed(tmp_path, dependency_paths=())
    assert result.dependency_sha256 is None
    decision, evidence = bridge.verify_with_evidence(episode, request, result)
    assert decision.outcome == "pass"
    assert evidence.dependency_manifest_sha256 is None
    assert evidence.dependency_sha256 == hashlib.sha256(canonical_json([])).hexdigest()


@pytest.mark.parametrize("config", [
    {"candidate_path": "../candidate.py"}, {"candidate_path": "."},
    {"dependency_paths": ("requirements.txt", "requirements.txt")},
    {"dependency_paths": ("candidate.py",)}, {"timeout_seconds": float("nan")},
    {"evaluator_sha256": "9" * 64},
])
def test_invalid_configuration_fails_closed(tmp_path: Path, config):
    options = {"task_input": b"5", "evaluator": trusted_evaluator,
               "evaluator_sha256": component_fingerprint(trusted_evaluator),
               "contract_sha256": CONTRACT, "environment_sha256": ENVIRONMENT, **config}
    with pytest.raises(RSILearningError):
        AgentLoopCleanRoomVerifier(tmp_path, **options)


def test_closure_evaluator_is_rejected_before_any_actor_work(tmp_path: Path):
    def evaluator(context):
        return {"outcome": "pass", "evidence": {}}

    with pytest.raises(RSILearningError, match="evaluator_not_importable"):
        AgentLoopCleanRoomVerifier(
            tmp_path, task_input=b"5", evaluator=evaluator, evaluator_sha256=component_fingerprint(evaluator),
            contract_sha256=CONTRACT, environment_sha256=ENVIRONMENT,
        )
    assert list(tmp_path.iterdir()) == []
