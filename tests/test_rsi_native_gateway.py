from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from threading import Barrier, Event

import pytest

from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
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


def plan_factory(request: SolverRequest, memory):
    # Deterministic, read-only reconstruction of the caller-owned frozen launch identities.
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
    common = {
        "candidate_id": "candidate", "request_sha256": request.digest(), "contract_sha256": request.contract_sha256,
        "evaluator_sha256": request.evaluator_sha256, "environment_sha256": request.environment_sha256,
        "memory_snapshot_sha256": request.memory_snapshot_sha256,
    }
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


def synchronize_unclaimed_inspection(monkeypatch, ledgers, barrier) -> None:
    for ledger in ledgers:
        inspect = ledger.inspect_native_episode_claim

        def synchronized(request, *, plan_sha256, inspect=inspect):
            claim = inspect(request, plan_sha256=plan_sha256)
            assert claim is None
            barrier.wait(timeout=10)
            return claim

        monkeypatch.setattr(ledger, "inspect_native_episode_claim", synchronized)


def test_native_gateway_started_claim_race_runs_provider_once(tmp_path, monkeypatch) -> None:
    request = make_request()
    ledgers = [RSILedger(tmp_path / "ledger.sqlite") for _ in range(2)]
    synchronize_unclaimed_inspection(monkeypatch, ledgers, Barrier(2))
    release_provider = Event()
    provider_started = Event()
    provider_calls = []

    def provider(req, plan):
        provider_calls.append(req.digest())
        provider_started.set()
        assert release_provider.wait(timeout=10)
        return bundle(req, plan)

    gateways = [NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, plan_factory, provider))
                for ledger in ledgers]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(gateway.run, request, EMPTY_MEMORY_SNAPSHOT) for gateway in gateways]
        try:
            loser = next(as_completed(futures, timeout=10))
            with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"):
                loser.result()
            assert provider_started.wait(timeout=10)
            assert provider_calls == [request.digest()]
        finally:
            release_provider.set()
        winner = next(future for future in futures if future is not loser)
        assert winner.result(timeout=10).status == "completed"
    assert provider_calls == [request.digest()]


def test_native_gateway_terminal_claim_race_replays_without_provider(tmp_path, monkeypatch) -> None:
    request = make_request()
    winner_ledger = RSILedger(tmp_path / "ledger.sqlite")
    replay_ledger = RSILedger(tmp_path / "ledger.sqlite")
    synchronize_unclaimed_inspection(monkeypatch, [winner_ledger, replay_ledger], Barrier(2))
    winner_done = Event()
    original_claim = replay_ledger.claim_native_episode

    def delayed_claim(req, *, plan_sha256):
        assert winner_done.wait(timeout=10)
        return original_claim(req, plan_sha256=plan_sha256)

    monkeypatch.setattr(replay_ledger, "claim_native_episode", delayed_claim)
    provider_calls = []

    def provider(req, plan):
        provider_calls.append(req.digest())
        return bundle(req, plan)

    def unexpected_provider(*_):
        pytest.fail("a terminal claim must replay without invoking the provider")

    winner = NativeRSISolverGateway(NativeRSIExecutionConfig(winner_ledger, plan_factory, provider))
    replay = NativeRSISolverGateway(NativeRSIExecutionConfig(replay_ledger, plan_factory, unexpected_provider))

    def run_winner():
        try:
            return winner.run(request, EMPTY_MEMORY_SNAPSHOT)
        finally:
            winner_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        winner_future = pool.submit(run_winner)
        replay_future = pool.submit(replay.run, request, EMPTY_MEMORY_SNAPSHOT)
        result = winner_future.result(timeout=10)
        assert replay_future.result(timeout=10) == result
    assert provider_calls == [request.digest()]


def test_native_gateway_provider_failure_preserves_claim_and_refuses_retry(tmp_path) -> None:
    request = make_request()
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    calls = 0

    def provider(*_):
        nonlocal calls
        calls += 1
        raise RuntimeError("incomplete native evidence")

    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, plan_factory, provider))
    with pytest.raises(NativeRSISolverGatewayError, match="attempt_unknown"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert ledger.episode_result(request.episode_id) is None
    with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert calls == 1


@pytest.mark.parametrize("record", ["candidate", "execution", "evaluation", "publication"])
def test_native_gateway_receipt_drift_cannot_publish_or_retry(tmp_path, record) -> None:
    request = make_request()
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    calls = 0

    def provider(req, plan):
        nonlocal calls
        calls += 1
        receipts = bundle(req, plan)
        drifted = replace(getattr(receipts, record), environment_sha256=digest("drifted-environment"))
        return replace(receipts, **{record: drifted})

    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, plan_factory, provider))
    with pytest.raises(NativeRSISolverGatewayError, match="attempt_unknown"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert ledger.episode_result(request.episode_id) is None
    with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert calls == 1


@pytest.mark.parametrize("drift", ["request", "plan"])
def test_native_gateway_replay_rejects_request_or_plan_drift(tmp_path, drift) -> None:
    request = make_request()
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    calls = 0

    def provider(req, plan):
        nonlocal calls
        calls += 1
        return bundle(req, plan)

    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, plan_factory, provider))
    result = gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    if drift == "request":
        changed_request = replace(request, environment_sha256=digest("drifted-environment"))
        changed_factory = plan_factory
    else:
        changed_request = request

        def changed_factory(req, memory):
            return replace(plan_factory(req, memory), manifest_sha256=digest("drifted-manifest"), plan_sha256=None)

    replay = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, changed_factory, provider))
    with pytest.raises(NativeRSISolverGatewayError, match="claim_invalid"):
        replay.run(changed_request, EMPTY_MEMORY_SNAPSHOT)
    assert ledger.episode_result(request.episode_id) == (request, result)
    assert calls == 1
