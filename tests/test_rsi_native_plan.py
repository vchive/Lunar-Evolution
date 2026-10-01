from __future__ import annotations

import json

import pytest

from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan, NativeRSIExecutionPlanError

HEX = "a" * 64


def _memory() -> MemorySnapshot:
    return MemorySnapshot("native-plan", HEX, (MemoryItem(
        memory_id="m1", problem_family="fixture", trigger="x", strategy="y", expected_result="z",
        failure_boundary="fixture", compatible_contracts=(HEX,), compatible_solvers=("native",),
        verifier_outcome="pass", receipt_sha256="b" * 64, episode_id="prior",
    ),))


def _request(memory: MemorySnapshot) -> SolverRequest:
    return SolverRequest.build(
        episode_id="episode", contract_sha256=HEX, evaluator_sha256=HEX,
        environment_sha256=HEX, memory_snapshot_sha256=memory.digest(), solver_id="native",
        solver_settings={"width": 2}, budget={"deadline_unix": 2_000_000_000},
        practice_charter={"trigger": "x"},
    )


def _plan() -> NativeRSIExecutionPlan:
    memory = _memory()
    return NativeRSIExecutionPlan.build(
        request=_request(memory), memory_snapshot=memory, journal_id="journal", launch_id="launch",
        run_id="run", parent_task_id="parent", task_id="task", intent_sha256=HEX,
        attestation_sha256=HEX, bootstrap_descriptor_sha256=HEX, bootstrap_artifact_sha256=HEX,
        manifest_sha256=HEX, candidate_selector_sha256=HEX, evaluator_kind="local",
        evaluator_fingerprint=HEX, deadline_unix=2_000_000_000,
    )


def test_plan_is_canonical_and_round_trips():
    plan = _plan()
    assert plan.plan_sha256 == plan.digest()
    assert NativeRSIExecutionPlan.from_dict(json.loads(json.dumps(plan.to_dict()))) == plan
    assert NativeRSIExecutionPlan.from_dict(plan.to_dict()).digest() == plan.digest()
    assert plan.request_relative_path == "../.rsi-input/request.json"


def test_plan_freezes_request_identity_and_memory_digest():
    memory = _memory()
    request = _request(memory)
    plan = NativeRSIExecutionPlan.build(
        request=request, memory_snapshot=memory, journal_id="journal", launch_id="launch",
        run_id="run", parent_task_id="parent", task_id="task", intent_sha256=HEX,
        attestation_sha256=HEX, bootstrap_descriptor_sha256=HEX, bootstrap_artifact_sha256=HEX,
        manifest_sha256=HEX, candidate_selector_sha256=HEX, evaluator_kind="local",
        evaluator_fingerprint=HEX,
    )
    plan.assert_request_memory(request, memory)
    with pytest.raises(NativeRSIExecutionPlanError, match="input_drift"):
        plan.assert_request_memory(request, MemorySnapshot("other", HEX, ()))


def test_plan_rejects_request_memory_and_plan_digest_drift():
    plan = _plan()
    value = plan.to_dict()
    value["request_sha256"] = "b" * 64
    with pytest.raises(NativeRSIExecutionPlanError, match="request_digest_mismatch"):
        NativeRSIExecutionPlan.from_dict(value)
    value = plan.to_dict()
    value["plan_sha256"] = "b" * 64
    with pytest.raises(NativeRSIExecutionPlanError, match="digest_mismatch"):
        NativeRSIExecutionPlan.from_dict(value)


def test_plan_rejects_unknown_fields_duplicate_wire_and_path_escape():
    plan = _plan()
    value = plan.to_dict()
    value["extra"] = True
    with pytest.raises(NativeRSIExecutionPlanError, match="wire_invalid"):
        NativeRSIExecutionPlan.from_dict(value)
    value = plan.to_dict()
    value["request_relative_path"] = "../../etc/passwd"
    value["plan_sha256"] = None
    with pytest.raises(NativeRSIExecutionPlanError, match="request_path_invalid"):
        NativeRSIExecutionPlan.from_dict(value)
    value = plan.to_dict()
    value["protocol"] = "wrong"
    with pytest.raises(NativeRSIExecutionPlanError, match="schema_invalid"):
        NativeRSIExecutionPlan.from_dict(value)


def test_plan_requires_selector_and_evaluator_fingerprints():
    memory = _memory()
    with pytest.raises(NativeRSIExecutionPlanError, match="candidate_selector_digest_invalid"):
        NativeRSIExecutionPlan.build(
            request=_request(memory), memory_snapshot=memory, journal_id="journal", launch_id="launch",
            run_id="run", parent_task_id="parent", task_id="task", intent_sha256=HEX,
            attestation_sha256=HEX, bootstrap_descriptor_sha256=HEX, bootstrap_artifact_sha256=HEX,
            manifest_sha256=HEX, candidate_selector_sha256="bad", evaluator_kind="local",
            evaluator_fingerprint=HEX,
        )
