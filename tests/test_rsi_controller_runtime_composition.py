"""Controller compositions stay local and preserve the existing durable execution protocol."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_actor import AgentLoopActorGateway
from lunar_evolution.rsi_actor_verifier import AgentLoopCleanRoomVerifier
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver, RSIMemoryStore
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot, RSILearningError
from lunar_evolution.rsi_memory_governance import MemoryAdmissionRecord, MemoryGovernanceStore
from lunar_evolution.rsi_memory_snapshot_gate import (
    GovernedMemorySnapshotGate,
    MemorySnapshotAdmissionError,
)
from lunar_evolution.rsi_store import RSILedger
from lunar_evolution.runtime import RuntimeResult

CONTRACT, ENVIRONMENT = "a" * 64, "b" * 64


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class PublicRuntime:
    name = "controller-local-fixture"

    def run(self, prompt, workspace, timeout=None, **kwargs):
        (workspace / "candidate.py").write_text("def solve(value):\n    return value + 1\n")
        (workspace / "requirements.txt").write_text("fixture==1\n")
        return RuntimeResult("private fixture response", ("candidate.py",), {})


def runtime_factory():
    return PublicRuntime()


def actor_receipts(request, workspace, result, trace):
    return {"candidate_receipt_sha256": digest("candidate:" + request.episode_id),
            "execution_receipt_sha256": digest("execution:" + request.episode_id),
            "official_evaluation_receipt_sha256": digest("evaluation:" + request.episode_id), "solver_score": 10}


def evaluator(context):
    namespace = {}
    exec(compile(context.source_path.read_bytes(), str(context.source_path), "exec"), namespace)  # noqa: S102 - execute the fixed local candidate in the independent fixture process
    value = int(context.task_input)
    return {"outcome": "pass" if namespace["solve"](value) == value + 1 else "fail",
            "evidence": {"public_input": context.task_input_sha256}}


def failed_evaluator(context):
    return {"outcome": "fail", "evidence": {"candidate": context.source_sha256}}


def judge_after_practice(execution):
    return execution.episode.wave > 0, "needs independently verified practice"


def actor_controller(tmp_path: Path, *, verification=evaluator):
    gateway = AgentLoopActorGateway(runtime_factory, tmp_path, receipt_builder=actor_receipts)
    bridge = AgentLoopCleanRoomVerifier(
        tmp_path, task_input=b"5", evaluator=verification, evaluator_sha256=component_fingerprint(verification),
        contract_sha256=CONTRACT, environment_sha256=ENVIRONMENT,
    )
    return RSILearningController(gateway, verifier=bridge, target_judge=judge_after_practice,
                                ledger=RSILedger(tmp_path / "rsi.sqlite3"))


def test_drs_actor_independent_verification_memory_retry_and_durable_replay(tmp_path: Path, monkeypatch):
    controller = actor_controller(tmp_path)
    result = controller.run_drs(
        run_id="actor-drs", contract_sha256=CONTRACT, evaluator_sha256=component_fingerprint(evaluator),
        environment_sha256=ENVIRONMENT, solver_id="lunar-agent-loop", max_practice_rounds=1, max_target_attempts=2,
    )
    assert result.status == "completed"
    assert len(result.practice_episodes) == 1 and len(result.target_attempts) == 2
    assert len(result.memory_snapshot.items) == 1
    assert result.memory_snapshot.items[0].receipt_sha256 == result.practice_episodes[0].verifier.receipt_sha256
    assert result.target_attempts[1].request.memory_snapshot_sha256 == result.memory_snapshot.digest()
    for execution in (*result.target_attempts, *result.practice_episodes):
        assert execution.passed and execution.verifier.independent_of_actor
        assert "cleanroom_evaluator" in {check.name for check in execution.verifier.checks}
        assert controller.callback_checkpoint("actor-drs", "verifier:" + execution.episode.episode_id)[1]["status"] == "completed"
    resumed = actor_controller(tmp_path)
    monkeypatch.setattr(resumed.gateway, "run", lambda *_args: pytest.fail("solver replay forbidden"))
    monkeypatch.setattr(resumed.verifier, "verify", lambda *_args: pytest.fail("independent evaluator replay forbidden"))
    replay = resumed.resume("actor-drs")
    assert replay.status == result.status and replay.memory_snapshot == result.memory_snapshot
    assert len(replay.practice_episodes) == 1 and len(replay.target_attempts) == 2


def test_failed_independent_verifier_prevents_memory_commit(tmp_path: Path):
    controller = actor_controller(tmp_path, verification=failed_evaluator)
    result = controller.run_drs(
        run_id="actor-failure", contract_sha256=CONTRACT, evaluator_sha256=component_fingerprint(failed_evaluator),
        environment_sha256=ENVIRONMENT, solver_id="lunar-agent-loop", max_practice_rounds=1, max_target_attempts=2,
    )
    assert not result.memory_snapshot.items
    assert all(not episode.passed for episode in (*result.target_attempts, *result.practice_episodes))


def governed_controller(tmp_path: Path):
    item = MemoryItem(
        memory_id="item", problem_family="fixture", trigger="public", strategy="local",
        expected_result="pass", failure_boundary="fixture", compatible_contracts=(CONTRACT,),
        compatible_solvers=("mock",), verifier_outcome="pass", receipt_sha256=digest("verifier"), episode_id="source",
    )
    snapshot = MemorySnapshot("frozen", None, (item,))
    governance = MemoryGovernanceStore(tmp_path / "governance.sqlite3")
    record = governance.create(MemoryAdmissionRecord(
        admission_id="admission", memory_snapshot_sha256=snapshot.digest(),
        memory_item_sha256=hashlib.sha256(canonical_json(item.to_dict())).hexdigest(),
        source_episode_id=item.episode_id, verifier_receipt_sha256=item.receipt_sha256,
        parent_snapshot_sha256=None, scope="fixture", compatibility={},
    ))
    for state in ("verified", "candidate", "shadow", "approved", "active"):
        kwargs = {"holdout_receipt_sha256": digest("holdout"), "baseline_receipt_sha256": digest("baseline"),
                  "regression_passed": True} if state == "approved" else {}
        record = governance.transition(record.admission_id, state, expected_record_sha256=record.record_sha256, **kwargs)
    gate = GovernedMemorySnapshotGate(governance, snapshot_sha256=snapshot.digest(),
                                     admissions={item.memory_id: record.admission_id}, scope="fixture", compatibility={})
    controller = RSILearningController(DeterministicMockSolver(), memory_store=RSIMemoryStore(snapshot),
                                      ledger=RSILedger(tmp_path / "rsi.sqlite3"), memory_admission_gate=gate)
    return controller, governance, record


def run_governed(controller, run_id):
    return controller.run_drs(run_id=run_id, contract_sha256=CONTRACT, evaluator_sha256=CONTRACT,
                              environment_sha256=ENVIRONMENT, solver_id="mock", max_practice_rounds=0,
                              max_target_attempts=1)


def test_revoked_memory_blocks_next_episode_but_completed_replay_is_read_only(tmp_path: Path, monkeypatch):
    controller, governance, active = governed_controller(tmp_path)
    result = run_governed(controller, "first")
    assert result.status == "completed"
    governance.revoke(active.admission_id, expected_record_sha256=active.record_sha256, reason="failed regression")
    monkeypatch.setattr(controller.gateway, "run", lambda *_args: pytest.fail("revoked memory must stop solver"))
    assert controller.resume("first").memory_snapshot == result.memory_snapshot
    with pytest.raises(MemorySnapshotAdmissionError, match="revoked"):
        run_governed(controller, "second")
    assert controller.ledger.episode_ids_for_run("second") == ()
    assert controller.ledger.controller_checkpoint("second")[1]["budget_state"]["consumed"]["solver_invocations"] == 0


def test_removing_gate_on_resume_is_fingerprint_drift(tmp_path: Path):
    controller, _governance, _active = governed_controller(tmp_path)
    run_governed(controller, "governed")
    changed = RSILearningController(DeterministicMockSolver(), memory_store=controller.memory_store, ledger=controller.ledger)
    with pytest.raises(RSILearningError, match="fingerprint_drift"):
        changed.resume("governed")


def test_governance_wait_cannot_dispatch_after_run_deadline(tmp_path: Path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: now[0])
    controller, _governance, _active = governed_controller(tmp_path)
    original = GovernedMemorySnapshotGate.validate
    calls = 0

    def delayed_gate(gate, snapshot):
        nonlocal calls
        calls += 1
        original(gate, snapshot)
        if calls == 2:
            now[0] = 102.0

    monkeypatch.setattr(GovernedMemorySnapshotGate, "validate", delayed_gate)
    monkeypatch.setattr(controller.gateway, "run", lambda *_args: pytest.fail("deadline must stop dispatch"))
    result = controller.run_drs(
        run_id="late-gate", contract_sha256=CONTRACT, evaluator_sha256=CONTRACT,
        environment_sha256=ENVIRONMENT, solver_id="mock", max_practice_rounds=0,
        max_target_attempts=1, budget={"deadline_unix": 101},
    )
    assert result.status == "budget_exhausted" and calls == 2
    assert controller.ledger.episode_ids_for_run("late-gate") == ()
