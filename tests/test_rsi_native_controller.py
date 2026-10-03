"""Controller integration coverage for the durable native RSI gateway seam."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution.official_evaluator_evidence import (
    OfficialEvaluationReceipt,
    OfficialEvaluatorProfile,
)
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import LocalExactVerifier, SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, MemorySnapshot, RSILearningError
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

CONTRACT = hashlib.sha256(b"native-controller-contract").hexdigest()
EVALUATOR = hashlib.sha256(b"native-controller-evaluator").hexdigest()
ENVIRONMENT = hashlib.sha256(b"native-controller-environment").hexdigest()


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def plan_factory(request: SolverRequest, memory: MemorySnapshot) -> NativeRSIExecutionPlan:
    values = {
        "intent_sha256": digest("intent:" + request.episode_id),
        "attestation_sha256": digest("attestation:" + request.episode_id),
        "bootstrap_descriptor_sha256": digest("descriptor"),
        "bootstrap_artifact_sha256": digest("artifact"),
        "manifest_sha256": digest("manifest"),
        "candidate_selector_sha256": digest("selector"),
        "evaluator_fingerprint": request.evaluator_sha256,
    }
    return NativeRSIExecutionPlan.build(
        request=request,
        memory_snapshot=memory,
        journal_id="journal",
        launch_id="launch",
        run_id="run",
        parent_task_id="parent",
        task_id=request.episode_id,
        candidate_selector_id="selector",
        evaluator_kind="local",
        **values,
    )


def receipt_bundle(request: SolverRequest, _plan: NativeRSIExecutionPlan) -> NativeRSIReceiptBundle:
    common = {
        "candidate_id": "candidate-1",
        "request_sha256": request.digest(),
        "contract_sha256": request.contract_sha256,
        "evaluator_sha256": request.evaluator_sha256,
        "environment_sha256": request.environment_sha256,
        "memory_snapshot_sha256": request.memory_snapshot_sha256,
    }
    return NativeRSIReceiptBundle(
        candidate=NativeCandidateRecord(
            **common,
            candidate_receipt_sha256=digest("candidate-receipt:" + request.episode_id),
            candidate_source_sha256=digest("candidate-source:" + request.episode_id),
        ),
        execution=NativeExecutionReceipt(
            **common,
            receipt_sha256=digest("execution-receipt:" + request.episode_id),
            trace_digest=digest("trace:" + request.episode_id),
        ),
        evaluation=NativeEvaluationReceipt(
            **common, receipt_sha256=digest("evaluation-receipt:" + request.episode_id),
        ),
        publication=NativePublicationReceipt(
            **common, receipt_sha256=digest("publication-receipt:" + request.episode_id),
        ),
        worker_terminal_status="completed",
        official_evaluator_receipt=OfficialEvaluationReceipt(
            OfficialEvaluatorProfile("fixture", "1", request.evaluator_sha256, digest("config"),
                                     request.contract_sha256, digest("task"), digest("holdout"), digest("seed")),
            request.digest(), digest("candidate-source:" + request.episode_id),
            digest("execution-receipt:" + request.episode_id), digest("publication-receipt:" + request.episode_id),
            "pass", digest("raw-verdict" + request.episode_id),
        ),
    )


class RecordingProvider:
    """Stable callable fixture whose mutable call log is excluded from its identity."""

    def __init__(self, *, interrupt: bool = False) -> None:
        self.calls: list[str] = []
        self.interrupt = interrupt

    def rsi_fingerprint_config(self) -> dict[str, object]:
        return {"protocol": "native-controller-provider-v1", "interrupt": self.interrupt}

    def __call__(self, request: SolverRequest, plan: NativeRSIExecutionPlan) -> NativeRSIReceiptBundle:
        self.calls.append(request.episode_id)
        if self.interrupt:
            raise RuntimeError("native provider interrupted")
        return receipt_bundle(request, plan)


def make_controller(path: Path, provider, *, memory_snapshot: MemorySnapshot | None = None):
    ledger = RSILedger(path)
    gateway = NativeRSISolverGateway(
        NativeRSIExecutionConfig(ledger, plan_factory, provider),
    )
    controller = RSILearningController(
        gateway,
        verifier=LocalExactVerifier(),
        ledger=ledger,
        # Native gateways require the controller and gateway to share this exact ledger.  The
        # snapshot is selected by the controller's memory store and is therefore empty here.
        memory_store=None,
    )
    if memory_snapshot is not None:
        # This helper is only used to construct drift tests before any launch.
        from lunar_evolution.rsi_gateway import RSIMemoryStore

        controller.memory_store = RSIMemoryStore(memory_snapshot)
    return controller, gateway, ledger


def run_target(controller: RSILearningController, run_id: str):
    return controller.run_drs(
        run_id=run_id,
        contract_sha256=CONTRACT,
        evaluator_sha256=EVALUATOR,
        environment_sha256=ENVIRONMENT,
        solver_id="native_population",
        max_practice_rounds=0,
        max_target_attempts=1,
    )


def test_native_controller_drs_completes_and_replays_after_restart(tmp_path: Path, monkeypatch):
    provider = RecordingProvider()

    controller, _gateway, ledger = make_controller(tmp_path / "rsi.sqlite", provider)
    first = run_target(controller, "native-drs")
    assert first.status == "completed"
    assert len(first.target_attempts) == 1
    assert first.target_attempts[0].passed
    assert provider.calls == [first.target_attempts[0].episode.episode_id]

    restarted, restarted_gateway, _ = make_controller(tmp_path / "rsi.sqlite", provider)
    monkeypatch.setattr(restarted_gateway, "run", lambda *_: pytest.fail("native replay must not invoke gateway"))
    replay = restarted.resume("native-drs")
    assert replay.status == "completed"
    assert replay.target_attempts == first.target_attempts
    assert ledger.controller_checkpoint_history("native-drs")


def test_native_controller_provider_interrupt_keeps_recovery_gate(tmp_path: Path):
    provider = RecordingProvider(interrupt=True)

    controller, gateway, ledger = make_controller(tmp_path / "rsi.sqlite", provider)
    with pytest.raises(NativeRSISolverGatewayError, match="attempt_unknown"):
        run_target(controller, "native-interrupt")
    assert len(provider.calls) == 1
    with pytest.raises(RSILearningError, match="unknown_reconcile_required|recovery_required"):
        controller.resume("native-interrupt")
    # The native claim remains started, so a direct gateway retry is also fail-closed.
    episode_id = "native-interrupt-target-0"
    request = ledger.episode_result(episode_id)
    assert request is None
    # A differently reconstructed request is a binding-drift attempt, which is fail-closed
    # before the started claim can be inspected as recoverable evidence.
    with pytest.raises(NativeRSISolverGatewayError, match="claim_invalid"):
        gateway.run(
            SolverRequest.build(
                episode_id=episode_id,
                contract_sha256=CONTRACT,
                evaluator_sha256=EVALUATOR,
                environment_sha256=ENVIRONMENT,
                memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
                solver_id="native_population",
            ),
            EMPTY_MEMORY_SNAPSHOT,
        )
    assert provider.calls == [episode_id]


def test_native_controller_rejects_snapshot_and_ledger_drift_before_launch(tmp_path: Path):
    provider = RecordingProvider()

    ledger = RSILedger(tmp_path / "native.sqlite")
    gateway = NativeRSISolverGateway(
        NativeRSIExecutionConfig(ledger, plan_factory, provider),
    )
    with pytest.raises(RSILearningError, match="ledger_mismatch"):
        RSILearningController(gateway, ledger=RSILedger(tmp_path / "other.sqlite"))

    drifted = MemorySnapshot("drifted", None, ())
    drift_controller, _gateway, _ledger = make_controller(
        tmp_path / "drift.sqlite", provider, memory_snapshot=drifted,
    )
    # The request generated by the controller is bound to the drifted snapshot.  The native
    # gateway receives the same immutable snapshot, so no provider call is made for a mismatch
    # injected at the gateway boundary.
    request = SolverRequest.build(
        episode_id="drift-episode",
        contract_sha256=CONTRACT,
        evaluator_sha256=EVALUATOR,
        environment_sha256=ENVIRONMENT,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="native_population",
    )
    with pytest.raises(NativeRSISolverGatewayError, match="memory_binding_mismatch"):
        drift_controller.gateway.run(request, drifted)
    assert provider.calls == []


def test_native_gateway_fingerprint_pins_ledger_and_callable_dependencies(tmp_path: Path):
    ledger = RSILedger(tmp_path / "native.sqlite")
    provider = RecordingProvider()
    gateway = NativeRSISolverGateway(
        NativeRSIExecutionConfig(ledger, plan_factory, provider),
    )
    config = gateway.rsi_fingerprint_config()
    assert config["protocol"] == "lunar-native-rsi-gateway-v1"
    assert config["ledger"] == {
        "database": str(ledger.database),
        "device": ledger.database.stat().st_dev,
        "inode": ledger.database.stat().st_ino,
    }
    assert len(config["plan_factory_sha256"]) == 64
    assert len(config["receipt_provider_sha256"]) == 64
    assert config == gateway.rsi_fingerprint_config()
