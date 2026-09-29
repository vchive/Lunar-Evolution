"""Paired native transfer checks run real local candidate/evaluator subprocesses."""
from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from test_bundle_population import build_context, draft_for_score

from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot
from lunar_evolution.rsi_native import (
    NativeEvaluationProfile,
    NativePopulationGateway,
    native_dependency_fingerprint,
    native_environment_fingerprint,
)
from lunar_evolution.rsi_transfer import FrozenMemoryTransferBenchmark, NativeTransferTask

HEX = "a" * 64


def profile(tmp_path: Path, *, problem_id=None):
    context = build_context(tmp_path / "fixture")
    pipeline = context.bundle_pipeline
    pipeline.environment_sha256 = native_environment_fingerprint(pipeline)
    pipeline.dependency_sha256 = native_dependency_fingerprint(tmp_path / "fixture", ())
    contract = context.contract
    if problem_id:
        contract = AlgorithmProblemContract.from_dict({
            **contract.to_dict(), "problem_id": problem_id,
            "statement": "Choose a permitted integer for another declared fixture task.",
        })
    return NativeEvaluationProfile(contract, pipeline, tmp_path / "fixture")


def snapshot(*contracts: str) -> MemorySnapshot:
    return MemorySnapshot("approved", None, (MemoryItem(
        "memory-1", "fixture", "gap", "use maximum", "score 7", "within bound",
        tuple(contracts), ("native_population",), "pass", HEX, "practice-1",
    ),))


def task(p: NativeEvaluationProfile, task_id="task-1"):
    return NativeTransferTask(task_id, p, budget=(("candidate_attempts", 1),), charter=(("goal", "fixture"),))


def block_run(monkeypatch):
    monkeypatch.setattr(NativePopulationGateway, "run", lambda *_: pytest.fail("terminal retry launched process"))


def rewrite_receipt(path, payload):
    body = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    payload["receipt_sha256"] = hashlib.sha256(canonical_json(body, maximum=128 * 1024)).hexdigest()
    path.write_bytes(canonical_json(payload, maximum=128 * 1024))


def test_frozen_transfer_compares_equal_settings_with_readonly_memory_and_replays(tmp_path, monkeypatch):
    p = profile(tmp_path)
    memory = snapshot(p.contract.digest())
    original_memory = memory.to_bytes()
    requests = []

    def generate(request, readonly):
        requests.append(request)
        with pytest.raises(AttributeError, match="immutable"):
            readonly.items = ()
        if readonly.items:
            with pytest.raises(FrozenInstanceError):
                readonly.items[0].strategy = "changed"
            assert readonly.get("memory-1").strategy == "use maximum"
        return draft_for_score(7 if readonly.items else 5)

    benchmark = FrozenMemoryTransferBenchmark(generate, tmp_path / "transfer", actor_fingerprint="b" * 64)
    result = benchmark.compare(comparison_id="comparison-1", tasks=(task(p),), snapshot=memory)
    assert result.status == "completed" and result.effect == "improved"
    assert result.baseline_verified == result.frozen_verified == 1
    assert result.receipt_path and result.receipt_path.is_file()
    assert memory.to_bytes() == original_memory
    assert len(requests) == 2
    baseline, frozen = requests
    assert baseline.budget == frozen.budget == (("candidate_attempts", 1),)
    assert baseline.practice_charter == frozen.practice_charter
    assert dict(baseline.practice_charter) == {
        "goal": "fixture", "curriculum_enabled": False, "memory_write_enabled": False,
    }
    assert baseline.memory_snapshot_sha256 != frozen.memory_snapshot_sha256
    assert baseline.episode_id != frozen.episode_id
    before = {str(path): path.read_bytes() for path in (tmp_path / "transfer").rglob("*") if path.is_file()}
    block_run(monkeypatch)
    assert benchmark.compare(comparison_id="comparison-1", tasks=(task(p),), snapshot=memory) == result
    assert before == {str(path): path.read_bytes() for path in (tmp_path / "transfer").rglob("*") if path.is_file()}


def test_transfer_panel_with_two_contracts_reports_mixed(tmp_path):
    p1, p2 = profile(tmp_path / "one"), profile(tmp_path / "two", problem_id="fixture-two")
    memory = snapshot(p1.contract.digest(), p2.contract.digest())

    def generate(request, readonly):
        if request.contract_sha256 == p1.contract.digest():
            return draft_for_score(7 if readonly.items else 5)
        return draft_for_score(6 if readonly.items else 8)

    benchmark = FrozenMemoryTransferBenchmark(generate, tmp_path / "mixed", actor_fingerprint="b" * 64)
    result = benchmark.compare(comparison_id="panel", tasks=(task(p1, "one"), task(p2, "two")), snapshot=memory)
    assert result.effect == "mixed"
    assert result.task_count == result.baseline_verified == result.frozen_verified == 2
    payload = json.loads(result.receipt_path.read_text())
    assert [row["outcome"]["oriented_score_delta"] for row in payload["rows"]] == [2.0, -2.0]


@pytest.mark.parametrize(("baseline", "frozen", "direction", "effect", "delta"), [
    (7, 7, "maximize", "unchanged", 0.0),
    (7, 5, "maximize", "regressed", -2.0),
    (7, 5, "minimize", "improved", 2.0),
])
def test_transfer_measures_unchanged_regressed_and_minimization(tmp_path, baseline, frozen, direction, effect, delta):
    p = profile(tmp_path)
    memory = snapshot(p.contract.digest())

    def generate(request, readonly):
        return draft_for_score(frozen if readonly.items else baseline)

    benchmark = FrozenMemoryTransferBenchmark(generate, tmp_path / "transfer", actor_fingerprint="b" * 64)
    result = benchmark.compare(comparison_id="measurement", tasks=(replace(task(p), direction=direction),), snapshot=memory)
    assert result.effect == effect
    assert json.loads(result.receipt_path.read_text())["rows"][0]["outcome"]["oriented_score_delta"] == delta


def test_transfer_unverified_arm_cannot_produce_score_delta(tmp_path):
    p = profile(tmp_path)
    memory = snapshot(p.contract.digest())
    benchmark = FrozenMemoryTransferBenchmark(
        lambda request, readonly: draft_for_score(999 if readonly.items else 7),
        tmp_path / "transfer", actor_fingerprint="b" * 64,
    )
    result = benchmark.compare(comparison_id="invalid", tasks=(task(p),), snapshot=memory)
    assert result.effect == "unresolved"
    assert result.baseline_verified == 1 and result.frozen_verified == 0
    assert json.loads(result.receipt_path.read_text())["rows"][0]["outcome"]["oriented_score_delta"] is None


def test_transfer_rejects_incompatible_memory_and_reserved_charter(tmp_path):
    p = profile(tmp_path)
    benchmark = FrozenMemoryTransferBenchmark(lambda *_: draft_for_score(7), tmp_path / "x", actor_fingerprint="b" * 64)
    with pytest.raises(Exception, match="rsi_transfer_memory_contract_incompatible"):
        benchmark.compare(comparison_id="bad", tasks=(task(p),), snapshot=snapshot("c" * 64))
    memory = snapshot(p.contract.digest())
    incompatible = replace(memory, items=(replace(memory.items[0], compatible_solvers=("external",)),))
    with pytest.raises(Exception, match="rsi_transfer_memory_solver_incompatible"):
        benchmark.compare(comparison_id="bad", tasks=(task(p),), snapshot=incompatible)
    with pytest.raises(Exception, match="rsi_transfer_charter_reserved"):
        NativeTransferTask("bad", p, charter=(("memory_write_enabled", True),))


@pytest.mark.parametrize("change", ["task", "budget", "snapshot", "factory", "actor"])
def test_transfer_rejects_changed_comparison_identity(tmp_path, change, monkeypatch):
    p = profile(tmp_path)
    memory, tasks = snapshot(p.contract.digest()), (task(p),)
    benchmark = FrozenMemoryTransferBenchmark(lambda *_: draft_for_score(7), tmp_path / "transfer", actor_fingerprint="b" * 64)
    benchmark.compare(comparison_id="identity", tasks=tasks, snapshot=memory)
    if change == "task":
        tasks = (replace(tasks[0], task_id="new-task"),)
    elif change == "budget":
        tasks = (replace(tasks[0], budget=(("candidate_attempts", 2),)),)
    elif change == "snapshot":
        memory = replace(memory, snapshot_id="new-snapshot")
    elif change == "factory":
        benchmark.draft_factory = lambda *_: draft_for_score(1)
    else:
        benchmark.actor_fingerprint = "c" * 64
    block_run(monkeypatch)
    with pytest.raises(Exception, match="rsi_transfer_comparison_identity_changed"):
        benchmark.compare(comparison_id="identity", tasks=tasks, snapshot=memory)


@pytest.mark.parametrize("change", ["hash", "outcome", "summary", "episode", "native-result"])
def test_transfer_rejects_rehashed_semantic_tamper(tmp_path, change, monkeypatch):
    p = profile(tmp_path)
    memory = snapshot(p.contract.digest())
    benchmark = FrozenMemoryTransferBenchmark(lambda *_: draft_for_score(7), tmp_path / "transfer", actor_fingerprint="b" * 64)
    result = benchmark.compare(comparison_id="tamper", tasks=(task(p),), snapshot=memory)
    payload = json.loads(result.receipt_path.read_text())
    expected = "rsi_transfer_comparison"
    if change == "hash":
        payload["receipt_sha256"] = "0" * 64
        result.receipt_path.write_bytes(canonical_json(payload, maximum=128 * 1024))
    else:
        if change == "outcome":
            payload["rows"][0]["outcome"]["effect"] = "improved"
        elif change == "summary":
            payload["summary"]["effect"] = "regressed"
        elif change == "episode":
            from lunar_evolution.rsi_learning import PracticeEpisode
            arm = payload["rows"][0]["baseline"]
            episode = PracticeEpisode.from_dict(arm["episode"])
            arm["episode"] = replace(episode, actor_fingerprint="f" * 64).to_record_dict()
            expected = "rsi_transfer_execution_result_mismatch"
        else:
            episode = payload["rows"][0]["baseline"]["episode"]["episode_id"]
            native = result.receipt_path.parent / "tasks" / "task-1" / "episodes" / episode / "native-result.json"
            retained = json.loads(native.read_text())
            retained["result"]["actor_fingerprint"] = "f" * 64
            native.write_bytes(canonical_json(retained, maximum=128 * 1024))
        rewrite_receipt(result.receipt_path, payload)
    block_run(monkeypatch)
    with pytest.raises(Exception, match=expected):
        benchmark.compare(comparison_id="tamper", tasks=(task(p),), snapshot=memory)


@pytest.mark.parametrize("arm_root", ["original", "independent"])
def test_transfer_reopens_original_and_independent_source_bytes(tmp_path, arm_root, monkeypatch):
    p = profile(tmp_path)
    memory = snapshot(p.contract.digest())
    benchmark = FrozenMemoryTransferBenchmark(lambda *_: draft_for_score(7), tmp_path / "transfer", actor_fingerprint="b" * 64)
    result = benchmark.compare(comparison_id="bytes", tasks=(task(p),), snapshot=memory)
    task_root = result.receipt_path.parent / "tasks" / "task-1"
    if arm_root == "original":
        descriptor = next((task_root / "episodes").glob("*/native-candidate.json"))
    else:
        descriptor = next((task_root / "verifications").glob("verify-*/episodes/*/native-candidate.json"))
    source = descriptor.parent / json.loads(descriptor.read_text())["source_root"] / "solve/helper.py"
    source.write_bytes(source.read_bytes() + b"# tamper\n")
    block_run(monkeypatch)
    with pytest.raises(Exception, match="rsi_native_material_changed"):
        benchmark.compare(comparison_id="bytes", tasks=(task(p),), snapshot=memory)


def test_transfer_intent_after_crash_is_unknown_and_never_replays(tmp_path, monkeypatch):
    p = profile(tmp_path)
    memory = snapshot(p.contract.digest())
    benchmark = FrozenMemoryTransferBenchmark(lambda *_: draft_for_score(7), tmp_path / "transfer", actor_fingerprint="b" * 64)

    def crash(*_):
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(NativePopulationGateway, "run", crash)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        benchmark.compare(comparison_id="crash", tasks=(task(p),), snapshot=memory)
    block_run(monkeypatch)
    result = benchmark.compare(comparison_id="crash", tasks=(task(p),), snapshot=memory)
    assert result.status == "unknown" and result.effect == "unresolved"
    assert result.receipt_path is None


def test_transfer_unknown_arm_retains_terminal_evidence(tmp_path, monkeypatch):
    p = profile(tmp_path)
    memory = snapshot(p.contract.digest())

    def invalid_factory(*_):
        raise RuntimeError("actor produced no candidate")

    benchmark = FrozenMemoryTransferBenchmark(invalid_factory, tmp_path / "transfer", actor_fingerprint="b" * 64)
    result = benchmark.compare(comparison_id="unknown", tasks=(task(p),), snapshot=memory)
    assert result.status == "completed" and result.effect == "unresolved"
    block_run(monkeypatch)
    assert benchmark.compare(comparison_id="unknown", tasks=(task(p),), snapshot=memory) == result
    native = next((result.receipt_path.parent / "tasks").glob("*/episodes/*/native-result.json"))
    retained = json.loads(native.read_text())
    retained["result"]["terminal_reason"] = "changed_reason"
    native.write_bytes(canonical_json(retained, maximum=128 * 1024))
    with pytest.raises(Exception, match="rsi_transfer_comparison_native_record_mismatch"):
        benchmark.compare(comparison_id="unknown", tasks=(task(p),), snapshot=memory)


def test_transfer_stage_budget_is_reserved_before_local_panel(tmp_path):
    p = profile(tmp_path)
    memory = snapshot(p.contract.digest())
    result = FrozenMemoryTransferBenchmark(
        lambda request, readonly: draft_for_score(7 if readonly.items else 5),
        tmp_path / "budget-transfer", actor_fingerprint="b" * 64,
    ).compare(
        comparison_id="budgeted", tasks=(task(p),), snapshot=memory,
        budget={"max_transfer_invocations": 1, "max_evaluator_invocations": 4},
    )
    assert result.status == "completed" and result.effect == "improved"
    state = json.loads((tmp_path / "budget-transfer" / "comparisons" / "budgeted" / "stage-accounting.json").read_text())
    assert state["budget"]["consumed"]["transfer_invocations"] == 1
    assert state["budget"]["consumed"]["evaluator_invocations"] == 4
    assert all(row["evidence"] is not None for row in state["stages"]["invocations"])


def test_transfer_stage_sidecar_tamper_and_missing_evidence_are_rejected(tmp_path):
    p = profile(tmp_path)
    memory = snapshot(p.contract.digest())
    root = tmp_path / "budget-transfer" / "comparisons" / "budgeted"
    benchmark = FrozenMemoryTransferBenchmark(
        lambda request, readonly: draft_for_score(7 if readonly.items else 5),
        tmp_path / "budget-transfer", actor_fingerprint="b" * 64,
    )
    benchmark.compare(comparison_id="budgeted", tasks=(task(p),), snapshot=memory,
                     budget={"max_transfer_invocations": 1, "max_evaluator_invocations": 4})
    sidecar = json.loads((root / "stage-accounting.json").read_text())
    sidecar["stages"]["invocations"][0]["identity"]["comparison_id"] = "other"
    (root / "stage-accounting.json").write_text(json.dumps(sidecar, sort_keys=True, separators=(",", ":")))
    with pytest.raises(Exception, match="stage_accounting_invalid"):
        benchmark.compare(comparison_id="budgeted", tasks=(task(p),), snapshot=memory,
                          budget={"max_transfer_invocations": 1, "max_evaluator_invocations": 4})
