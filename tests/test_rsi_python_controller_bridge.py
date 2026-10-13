"""Read-only controller/store/scheduler composition over inert staged bytes."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_producer_gateway import _fixture
from test_rsi_producer_staging_controller import ObservedAttestations

import lunar_evolution.rsi_native_inputs as native_inputs
import lunar_evolution.rsi_producer_launch as producer_launch
import lunar_evolution.rsi_python_controller_bridge as controller_bridge
from lunar_evolution import RSILearningController, RSILearningError
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_producer_gateway import PythonProducerRSISolverGateway
from lunar_evolution.rsi_producer_launch import (
    PythonProducerEpisodeStager,
    PythonProducerEpisodeStagingConfig,
)
from lunar_evolution.rsi_python_controller_bridge import (
    PythonProducerControllerBridgeError,
    resolve_python_producer_controller_child_preview,
)


def _ready(tmp_path, monkeypatch):
    monkeypatch.setattr(producer_launch, "MAX_STAGING_BINDING_BYTES", 64 * 1024)
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    config = PythonProducerEpisodeStagingConfig(
        workspace=value.root, root_sidecar=value.sidecar,
        artifact=value.native.artifact, attestation_supplier=supplier,
    )
    controller = RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.root, producer_stager=PythonProducerEpisodeStager(config),
    )
    value.gateway.bind_python_admission_controller(controller)
    with pytest.raises(RSILearningError, match="dispatch_not_accepted"):
        controller.run_drs(
            run_id=value.binding.run_id,
            contract_sha256=value.request.contract_sha256,
            evaluator_sha256=value.request.evaluator_sha256,
            environment_sha256=value.request.environment_sha256,
            solver_id=value.request.solver_id,
            max_practice_rounds=0, max_target_attempts=1,
            budget=dict(value.request.budget),
        )
    head, state = value.ledger.controller_checkpoint(value.binding.run_id)
    episode_id = state["current_episode_id"]
    entry = state["producer_episode_staging"][episode_id]
    request = value.request.from_dict(entry["identity"]["intent"]["request"])
    memory = value.memory.from_dict(entry["identity"]["memory"])
    return value, controller, head, state, entry, request, memory


def test_controller_bridge_reuses_ready_child_plan_without_writes(tmp_path, monkeypatch):
    value, controller, head, state, entry, request, memory = _ready(tmp_path, monkeypatch)
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    with value.ledger.controller_lock(value.binding.run_id):
        preview = resolve_python_producer_controller_child_preview(
            controller, run_id=value.binding.run_id, episode_id=state["current_episode_id"],
            request=request, memory=memory, expected_checkpoint_sha256=head,
        )
    assert preview.context.native_context.intent.task_id == request.episode_id
    assert preview.context.native_context.intent.journal_id == entry["identity"]["journal_id"]
    assert preview.plan.to_dict() == entry["ready"]["plan"]
    assert isinstance(controller.gateway, PythonProducerRSISolverGateway)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert value.ledger.get_episode(request.episode_id) is None
    assert value.ledger.episode_result(request.episode_id) is None
    assert _inventory(value.root) == before


def test_controller_bridge_snapshots_broker_headers_and_rejects_source_drift(tmp_path, monkeypatch):
    value, controller, head, state, _entry, request, memory = _ready(tmp_path, monkeypatch)
    root_context = controller.gateway.producer_config.inputs
    with value.ledger.controller_lock(value.binding.run_id):
        preview = resolve_python_producer_controller_child_preview(
            controller, run_id=value.binding.run_id, episode_id=state["current_episode_id"],
            request=request, memory=memory, expected_checkpoint_sha256=head,
        )
    assert preview.context.native_context.broker_config is not root_context.native_context.broker_config
    assert preview.context.native_context.broker_config.headers == root_context.native_context.broker_config.headers
    root_context.native_context.broker_config.headers["x-drift"] = "changed"
    with value.ledger.controller_lock(value.binding.run_id), pytest.raises(
        PythonProducerControllerBridgeError, match="evidence_invalid",
    ):
        resolve_python_producer_controller_child_preview(
            controller, run_id=value.binding.run_id, episode_id=state["current_episode_id"],
            request=request, memory=memory, expected_checkpoint_sha256=head,
        )


@pytest.mark.parametrize("mutation", ["checkpoint", "request", "memory"])
def test_controller_bridge_refuses_drift_before_scheduler_plan(tmp_path, monkeypatch, mutation):
    value, controller, head, state, _entry, request, memory = _ready(tmp_path, monkeypatch)
    if mutation == "checkpoint":
        head = "a" * 64
    elif mutation == "request":
        request = replace(request, solver_settings=(("changed", True),))
    else:
        memory = replace(memory, snapshot_id="changed")
    before = _inventory(value.root)
    with value.ledger.controller_lock(value.binding.run_id), pytest.raises(
        PythonProducerControllerBridgeError,
    ):
        resolve_python_producer_controller_child_preview(
            controller, run_id=value.binding.run_id, episode_id=state["current_episode_id"],
            request=request, memory=memory, expected_checkpoint_sha256=head,
        )
    assert _inventory(value.root) == before
    assert value.ledger.get_episode(request.episode_id) is None


def test_controller_bridge_requires_owner_lock_and_drs_ready_state(tmp_path, monkeypatch):
    value, controller, head, state, _entry, request, memory = _ready(tmp_path, monkeypatch)
    with pytest.raises(PythonProducerControllerBridgeError, match="controller_lock_required"):
        resolve_python_producer_controller_child_preview(
            controller, run_id=value.binding.run_id, episode_id=state["current_episode_id"],
            request=request, memory=memory, expected_checkpoint_sha256=head,
        )
    original = value.ledger.controller_checkpoint
    monkeypatch.setattr(
        value.ledger, "controller_checkpoint",
        lambda run_id: (head, {**state, "mode": "brs"}) if run_id == value.binding.run_id else original(run_id),
    )
    with value.ledger.controller_lock(value.binding.run_id), pytest.raises(
        PythonProducerControllerBridgeError, match="mode_invalid",
    ):
        resolve_python_producer_controller_child_preview(
            controller, run_id=value.binding.run_id, episode_id=state["current_episode_id"],
            request=request, memory=memory, expected_checkpoint_sha256=head,
        )


def test_controller_bridge_rejects_existing_claim_without_writing(tmp_path, monkeypatch):
    value, controller, head, state, entry, request, memory = _ready(tmp_path, monkeypatch)
    plan = NativeRSIExecutionPlan.from_dict(entry["ready"]["plan"])
    value.ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
    before = _inventory(value.root)
    with value.ledger.controller_lock(value.binding.run_id), pytest.raises(
        PythonProducerControllerBridgeError, match="episode_claim_exists",
    ):
        resolve_python_producer_controller_child_preview(
            controller, run_id=value.binding.run_id, episode_id=state["current_episode_id"],
            request=request, memory=memory, expected_checkpoint_sha256=head,
        )
    assert _inventory(value.root) == before
    assert value.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256) is not None
    assert entry["state"] == "ready"


def test_controller_bridge_preclaim_refuses_cancelled_child_without_writing(tmp_path, monkeypatch):
    value, controller, head, state, _entry, request, memory = _ready(tmp_path, monkeypatch)
    original = controller_bridge.resolve_python_rsi_episode_input_context

    def cancelled_child(*args, **kwargs):
        child = original(*args, **kwargs)
        object.__setattr__(child.native_context, "cancelled", lambda: True)
        return child

    monkeypatch.setattr(
        controller_bridge, "resolve_python_rsi_episode_input_context", cancelled_child,
    )
    before = _inventory(value.root)
    with value.ledger.controller_lock(value.binding.run_id), pytest.raises(
        PythonProducerControllerBridgeError, match="evidence_invalid",
    ):
        resolve_python_producer_controller_child_preview(
            controller, run_id=value.binding.run_id, episode_id=state["current_episode_id"],
            request=request, memory=memory, expected_checkpoint_sha256=head,
        )
    assert value.ledger.inspect_native_episode_claim(
        request, plan_sha256=_entry["ready"]["plan"]["plan_sha256"],
    ) is None
    assert _inventory(value.root) == before


def test_controller_bridge_preclaim_refuses_expired_child_before_claim(tmp_path, monkeypatch):
    value, controller, head, state, _entry, request, memory = _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(native_inputs.time, "time", lambda: 10**12)
    before = _inventory(value.root)
    with value.ledger.controller_lock(value.binding.run_id), pytest.raises(
        PythonProducerControllerBridgeError, match="evidence_invalid",
    ):
        resolve_python_producer_controller_child_preview(
            controller, run_id=value.binding.run_id, episode_id=state["current_episode_id"],
            request=request, memory=memory, expected_checkpoint_sha256=head,
        )
    assert value.ledger.inspect_native_episode_claim(
        request, plan_sha256=_entry["ready"]["plan"]["plan_sha256"],
    ) is None
    assert _inventory(value.root) == before


def test_controller_bridge_preclaim_rechecks_context_after_cancellation_callback(
    tmp_path, monkeypatch,
):
    value, controller, head, state, _entry, request, memory = _ready(tmp_path, monkeypatch)
    original = controller_bridge.resolve_python_rsi_episode_input_context

    def mutating_child(*args, **kwargs):
        child = original(*args, **kwargs)

        def cancel_and_mutate():
            child.native_context.broker_config.headers["x-preclaim-drift"] = "changed"
            return False

        object.__setattr__(child.native_context, "cancelled", cancel_and_mutate)
        return child

    monkeypatch.setattr(
        controller_bridge, "resolve_python_rsi_episode_input_context", mutating_child,
    )
    before = _inventory(value.root)
    with value.ledger.controller_lock(value.binding.run_id), pytest.raises(
        PythonProducerControllerBridgeError, match="evidence_invalid",
    ):
        resolve_python_producer_controller_child_preview(
            controller, run_id=value.binding.run_id, episode_id=state["current_episode_id"],
            request=request, memory=memory, expected_checkpoint_sha256=head,
        )
    assert value.ledger.inspect_native_episode_claim(
        request, plan_sha256=_entry["ready"]["plan"]["plan_sha256"],
    ) is None
    assert _inventory(value.root) == before
