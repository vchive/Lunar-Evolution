from __future__ import annotations

import hashlib

import pytest

from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_native_candidate import (
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
)
from lunar_evolution.rsi_native_gateway import (
    NativeRSIExecutionConfig,
    NativeRSIReceiptBundle,
    NativeRSISolverGateway,
    NativeRSISolverGatewayError,
)
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_store import RSILedger


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def make_request() -> SolverRequest:
    return SolverRequest.build(
        episode_id="native-gateway-episode",
        contract_sha256=digest("contract"),
        evaluator_sha256=digest("evaluator"),
        environment_sha256=digest("environment"),
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="native_population",
    )


def make_plan(request: SolverRequest, memory) -> NativeRSIExecutionPlan:
    values = {"request": request, "memory": memory, "inputs": None}
    del values  # plan construction is injected by the fixture below
    return object()  # pragma: no cover


def plan_factory(request: SolverRequest, memory):
    # The gateway only needs a validated plan identity; use a small object built through the
    # existing constructor helper in the test fixture's fake native inputs.
    from dataclasses import replace
    from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan

    zeros = {"intent_sha256": digest("intent"), "attestation_sha256": digest("attestation"),
             "bootstrap_descriptor_sha256": digest("descriptor"), "bootstrap_artifact_sha256": digest("artifact"),
             "manifest_sha256": digest("manifest"), "candidate_selector_sha256": digest("selector"),
             "evaluator_fingerprint": digest("evaluator-fingerprint")}
    return NativeRSIExecutionPlan.build(
        request=request, memory_snapshot=memory, journal_id="journal", launch_id="launch", run_id="run",
        parent_task_id="parent", task_id="task", candidate_selector_id="selector",
        evaluator_kind="local", **zeros,
    )


def bundle(request: SolverRequest, plan: NativeRSIExecutionPlan) -> NativeRSIReceiptBundle:
    common = dict(
        candidate_id="candidate", request_sha256=request.digest(), contract_sha256=request.contract_sha256,
        evaluator_sha256=request.evaluator_sha256, environment_sha256=request.environment_sha256,
        memory_snapshot_sha256=request.memory_snapshot_sha256,
    )
    candidate = NativeCandidateRecord(
        **common, candidate_receipt_sha256=digest("candidate-receipt"),
        candidate_source_sha256=digest("candidate-source"),
    )
    return NativeRSIReceiptBundle(
        candidate=candidate,
        execution=NativeExecutionReceipt(**common, receipt_sha256=digest("execution"), trace_digest=digest("trace")),
        evaluation=NativeEvaluationReceipt(**common, receipt_sha256=digest("evaluation")),
        publication=NativePublicationReceipt(**common, receipt_sha256=digest("publication")),
    )


def test_native_gateway_composes_and_replays_without_second_provider_call(tmp_path) -> None:
    request = make_request()
    calls = 0

    def provider(req, plan):
        nonlocal calls
        calls += 1
        return bundle(req, plan)

    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(RSILedger(tmp_path / "ledger.sqlite"), plan_factory, provider))
    result = gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert result.status == "completed"
    assert calls == 1
    assert gateway.run(request, EMPTY_MEMORY_SNAPSHOT) == result
    assert calls == 1


def test_native_gateway_rejects_memory_drift_before_claim(tmp_path) -> None:
    request = make_request()
    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(RSILedger(tmp_path / "ledger.sqlite"), plan_factory, lambda *_: bundle(request, None)))
    drifted = type(EMPTY_MEMORY_SNAPSHOT)("drifted", None, ())
    with pytest.raises(NativeRSISolverGatewayError, match="memory_binding_mismatch"):
        gateway.run(request, drifted)


def test_native_gateway_started_claim_is_recovery_gate(tmp_path) -> None:
    request = make_request()
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    plan = plan_factory(request, EMPTY_MEMORY_SNAPSHOT)
    ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
    calls = 0

    def provider(*_):
        nonlocal calls
        calls += 1
        return bundle(request, plan)

    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, plan_factory, provider))
    with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert calls == 0
