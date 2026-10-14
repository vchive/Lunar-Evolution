"""Read-only ready-child selection and owner binding over inert local fixtures."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_producer_gateway import _fixture
from test_rsi_producer_staging_controller import ObservedAttestations

import lunar_evolution.rsi_producer_launch as producer_launch
from lunar_evolution import RSILearningController, RSILearningError
from lunar_evolution.python_producer_checkpoint import PythonProducerCheckpointBinding
from lunar_evolution.rsi_child_gateway import resolve_python_producer_episode_gateway
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_learning import MemorySnapshot
from lunar_evolution.rsi_producer_gateway import (
    PythonProducerRSIGatewayError,
    PythonProducerRSISolverGateway,
)
from lunar_evolution.rsi_producer_launch import (
    PythonProducerEpisodeStager,
    PythonProducerEpisodeStagingConfig,
)


def _stop_at_ready(_self, _state, _episode, _request):
    raise RSILearningError("test_child_ready_stop")


def _ready_child(tmp_path, monkeypatch, producer="openevolve"):
    monkeypatch.setattr(producer_launch, "MAX_STAGING_BINDING_BYTES", 64 * 1024)
    monkeypatch.setattr(RSILearningController, "_execute_producer_child", _stop_at_ready)
    value = _fixture(tmp_path, monkeypatch, producer)
    supplier = ObservedAttestations(value.ledger)
    config = PythonProducerEpisodeStagingConfig(
        workspace=value.root, root_sidecar=value.sidecar,
        artifact=value.native.artifact, attestation_supplier=supplier,
    )
    controller = RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.root, producer_stager=PythonProducerEpisodeStager(config),
        producer_child_execution=True,
    )
    value.gateway.bind_python_admission_controller(controller)
    with pytest.raises(RSILearningError, match="test_child_ready_stop"):
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
    entry = state["producer_episode_staging"][state["current_episode_id"]]
    request = value.request.from_dict(entry["identity"]["intent"]["request"])
    memory = value.memory.from_dict(entry["identity"]["memory"])
    return value, controller, head, state, request, memory


def test_legacy_selection_returns_original_without_reading_evidence(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(value.ledger, "history", lambda *_a: pytest.fail("legacy evidence read"))
    assert resolve_python_producer_episode_gateway(value.controller, object(), object()) is value.gateway


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
def test_ready_selection_is_read_only_and_keeps_original_root(tmp_path, monkeypatch, producer):
    value, controller, head, state, request, memory = _ready_child(tmp_path, monkeypatch, producer)
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    fingerprint = component_fingerprint(value.gateway)
    child = resolve_python_producer_episode_gateway(controller, request, memory)
    assert child is not value.gateway
    assert child.ledger is value.ledger
    assert child.production_admission is False
    assert child.producer_config.inputs.native_context.intent.task_id == request.episode_id
    assert child.config.receipt_provider._python_admission_controller is None
    assert child._plan(request, memory).to_dict() == state["producer_episode_staging"][request.episode_id]["ready"]["plan"]
    assert controller.gateway is value.gateway
    assert component_fingerprint(value.gateway) == fingerprint
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert value.ledger.controller_checkpoint(value.binding.run_id)[0] == head
    assert value.ledger.get_episode(request.episode_id) is None
    assert _inventory(value.root) == before


@pytest.mark.parametrize("head", ["a" * 64, "0" * 64, True, "invalid"])
def test_selector_rejects_checkpoint_drift(tmp_path, monkeypatch, head):
    value, controller, _head, _state, request, memory = _ready_child(tmp_path, monkeypatch)
    with pytest.raises(PythonProducerRSIGatewayError, match="episode_checkpoint"):
        resolve_python_producer_episode_gateway(controller, request, memory, expected_checkpoint_sha256=head)
    assert value.ledger.episode_result(request.episode_id) is None


@pytest.mark.parametrize("which", ["original", "current"])
@pytest.mark.parametrize("flag", [None, False, 1])
def test_selector_requires_exact_original_and_current_opt_in(tmp_path, monkeypatch, which, flag):
    value, controller, head, state, request, memory = _ready_child(tmp_path, monkeypatch)
    if which == "original":
        history = value.ledger.history(value.binding.run_id)
        original = replace(history[0], payload={**history[0].payload, "producer_child_execution": flag})
        monkeypatch.setattr(value.ledger, "history", lambda *_a: (original, *history[1:]))
    else:
        monkeypatch.setattr(
            value.ledger, "controller_checkpoint",
            lambda *_a: (head, {**state, "producer_child_execution": flag}),
        )
    with pytest.raises(PythonProducerRSIGatewayError, match="episode_original_mode_mismatch"):
        resolve_python_producer_episode_gateway(controller, request, memory)


@pytest.mark.parametrize("drift", ["ledger", "root", "workspace", "proof"])
def test_selector_refuses_original_association_drift(tmp_path, monkeypatch, drift):
    value, controller, _head, _state, request, memory = _ready_child(tmp_path, monkeypatch)
    if drift == "ledger":
        controller.ledger = object()
    elif drift == "root":
        controller.gateway = PythonProducerRSISolverGateway(value.config)
    elif drift == "workspace":
        controller.producer_workspace = tmp_path / "foreign"
    else:
        child = resolve_python_producer_episode_gateway(controller, request, memory)
        controller.producer_sidecar = child.producer_config.inputs.producer_sidecar
    with pytest.raises(PythonProducerRSIGatewayError):
        resolve_python_producer_episode_gateway(controller, request, memory)
    assert value.ledger.get_episode(request.episode_id) is None


def test_selector_uses_request_historical_memory(tmp_path, monkeypatch):
    value, controller, _head, _state, request, memory = _ready_child(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "_native_historical_memory", lambda *_a: MemorySnapshot("different", None, ()))
    with pytest.raises(PythonProducerRSIGatewayError, match="episode_evidence_invalid"):
        resolve_python_producer_episode_gateway(controller, request, memory)
    assert value.ledger.get_episode(request.episode_id) is None


def test_selector_refuses_request_drift_and_missing_ready_evidence(tmp_path, monkeypatch):
    value, controller, head, state, request, memory = _ready_child(tmp_path, monkeypatch)
    with pytest.raises(PythonProducerRSIGatewayError):
        resolve_python_producer_episode_gateway(
            controller, replace(request, solver_settings=(("changed", True),)), memory,
        )
    changed = {**state, "producer_episode_staging": {}}
    monkeypatch.setattr(value.ledger, "controller_checkpoint", lambda *_a: (head, changed))
    with pytest.raises(PythonProducerRSIGatewayError):
        resolve_python_producer_episode_gateway(controller, request, memory)
    assert value.ledger.get_episode(request.episode_id) is None


@pytest.mark.parametrize("drift", ["flag", "policy"])
def test_intermediate_canonical_run_revision_cannot_hide_mode_drift(tmp_path, monkeypatch, drift):
    value, controller, head, state, request, memory = _ready_child(tmp_path, monkeypatch)
    original = value.ledger.get_run(value.binding.run_id)
    previous = value.ledger.history(value.binding.run_id)
    preserved = {
        "producer_child_execution": original.payload["producer_child_execution"],
        "producer_child_execution_policy": original.payload["producer_child_execution_policy"],
    }
    changed = (
        {"producer_child_execution": False}
        if drift == "flag" else
        {"producer_child_execution_policy": {**preserved["producer_child_execution_policy"], "protocol": "changed"}}
    )
    paused = value.ledger.transition(
        value.binding.run_id, state="paused", expected_record_sha256=original.record_sha256,
        payload_patch=changed,
    )
    restored = value.ledger.transition(
        value.binding.run_id, state="running", expected_record_sha256=paused.record_sha256,
        payload_patch=preserved,
    )
    history = value.ledger.history(value.binding.run_id)
    assert len(history) == len(previous) + 2
    assert [record.state for record in history[-3:]] == ["running", "paused", "running"]
    assert history[0].payload["producer_child_execution"] is True
    assert restored.payload["producer_child_execution"] is True
    assert restored.payload["producer_child_execution_policy"] == preserved["producer_child_execution_policy"]
    assert all(record.payload["producer_checkpoint_binding"] == original.payload["producer_checkpoint_binding"] for record in history)
    assert value.ledger.controller_checkpoint(value.binding.run_id) == (head, state)
    with pytest.raises(RSILearningError, match="producer_child_execution_original_mode_mismatch"):
        controller._validate_producer_checkpoint(value.binding.run_id, state)
    with pytest.raises(PythonProducerRSIGatewayError, match="episode_evidence_invalid"):
        resolve_python_producer_episode_gateway(controller, request, memory)
    assert value.ledger.get_episode(request.episode_id) is None


def test_selector_does_not_adopt_or_reclaim_started_attempt(tmp_path, monkeypatch):
    value, controller, head, _state, request, memory = _ready_child(tmp_path, monkeypatch)
    child = resolve_python_producer_episode_gateway(controller, request, memory)
    plan = child._plan(request, memory)
    claim = value.ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
    reconstructed = resolve_python_producer_episode_gateway(
        controller, request, memory, expected_checkpoint_sha256=head,
    )
    assert reconstructed.config.receipt_provider._python_admission_controller is None
    assert value.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256) == claim
    with pytest.raises(RSILearningError, match="recovery_required"):
        reconstructed.run(request, memory)
    assert value.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256) == claim


def test_child_binder_requires_owner_lock_and_active_flow(tmp_path, monkeypatch):
    value, controller, head, _state, request, memory = _ready_child(tmp_path, monkeypatch)
    child = resolve_python_producer_episode_gateway(controller, request, memory)
    with pytest.raises(PythonProducerRSIGatewayError, match="child_controller_lock_required"):
        child.bind_python_admission_child_controller(controller, expected_checkpoint_sha256=head)
    with value.ledger.controller_lock(value.binding.run_id), pytest.raises(
        PythonProducerRSIGatewayError, match="child_controller_evidence_invalid",
    ):
        child.bind_python_admission_child_controller(controller, expected_checkpoint_sha256=head)
    assert child.config.receipt_provider._python_admission_controller is None


def test_child_binder_retains_root_only_public_binder(tmp_path, monkeypatch):
    value, controller, head, state, request, memory = _ready_child(tmp_path, monkeypatch)
    child = resolve_python_producer_episode_gateway(controller, request, memory)
    fingerprint = component_fingerprint(child)
    with value.ledger.controller_lock(value.binding.run_id), controller._python_admission_flow_scope(state, request.episode_id):
        child.bind_python_admission_child_controller(controller, expected_checkpoint_sha256=head)
        child.bind_python_admission_child_controller(controller, expected_checkpoint_sha256=head)
        with pytest.raises(PythonProducerRSIGatewayError, match="controller_mismatch"):
            child.bind_python_admission_controller(controller)
    assert child.config.receipt_provider._python_admission_controller is controller
    assert value.gateway.config.receipt_provider._python_admission_controller is controller
    assert controller.gateway is value.gateway
    assert component_fingerprint(child) == fingerprint
    assert value.ledger.get_episode(request.episode_id) is None
    with pytest.raises(PythonProducerRSIGatewayError, match="controller_mismatch"):
        child.run(request, memory)
    assert value.ledger.get_episode(request.episode_id) is None
    assert value.ledger.inspect_native_episode_claim(
        request, plan_sha256=child._plan(request, memory).plan_sha256,
    ) is None
    replacement = RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.root, producer_stager=controller.producer_stager,
        producer_child_execution=True,
    )
    with (
        value.ledger.controller_lock(value.binding.run_id),
        replacement._python_admission_flow_scope(state, request.episode_id),
        pytest.raises(PythonProducerRSIGatewayError, match="child_controller_evidence_invalid"),
    ):
        child.bind_python_admission_child_controller(replacement, expected_checkpoint_sha256=head)
    assert child.config.receipt_provider._python_admission_controller is controller


def test_child_binder_refuses_wrong_active_head(tmp_path, monkeypatch):
    value, controller, _head, state, request, memory = _ready_child(tmp_path, monkeypatch)
    child = resolve_python_producer_episode_gateway(controller, request, memory)
    with (
        value.ledger.controller_lock(value.binding.run_id),
        controller._python_admission_flow_scope(state, request.episode_id),
        pytest.raises(PythonProducerRSIGatewayError, match="child_controller_checkpoint_conflict"),
    ):
        child.bind_python_admission_child_controller(controller, expected_checkpoint_sha256="a" * 64)
    assert child.config.receipt_provider._python_admission_controller is None


def test_child_binder_rechecks_full_execution_wiring(tmp_path, monkeypatch):
    value, controller, head, state, request, memory = _ready_child(tmp_path, monkeypatch)
    child = resolve_python_producer_episode_gateway(controller, request, memory)
    # A fresh child with a different hook can have an identical pure input plan.
    # Its native execution wiring must still fail the original-root comparison.
    changed_native = replace(child.producer_config.inputs.native_context, cancelled=lambda: False)
    changed_inputs = replace(
        child.producer_config.inputs, native_context=changed_native,
        original_producer_checkpoint=PythonProducerCheckpointBinding.from_dict(
            child.producer_config.inputs.original_producer_checkpoint.to_dict(),
        ),
    )
    changed = PythonProducerRSISolverGateway(replace(child.producer_config, inputs=changed_inputs))
    assert changed._plan(request, memory) == child._plan(request, memory)
    with (
        value.ledger.controller_lock(value.binding.run_id),
        controller._python_admission_flow_scope(state, request.episode_id),
        pytest.raises(PythonProducerRSIGatewayError, match="child_controller_context_mismatch"),
    ):
        changed.bind_python_admission_child_controller(controller, expected_checkpoint_sha256=head)
    assert changed.config.receipt_provider._python_admission_controller is None
