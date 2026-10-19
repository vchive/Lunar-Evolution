"""Original private BRS staging and read-only child inputs; nothing is launched."""

from __future__ import annotations

import subprocess
from copy import deepcopy
from dataclasses import replace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_producer_gateway import _fixture
from test_rsi_producer_staging_controller import ObservedAttestations

from lunar_evolution import DeterministicCurriculum, RSILearningController
from lunar_evolution.rsi_brs_reserved_reservation import read_reserved_brs_reservation
from lunar_evolution.rsi_brs_serial_driver import (
    read_reserved_brs_serial_observation,
    reserved_brs_staging_mode,
)
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import PracticeEpisode, RSILearningError
from lunar_evolution.rsi_producer_gateway import resolve_reserved_python_producer_episode_gateway
from lunar_evolution.rsi_producer_launch import (
    PythonProducerEpisodeStager,
    PythonProducerEpisodeStagingConfig,
)
from lunar_evolution.rsi_python_episode_inputs import (
    resolve_python_rsi_episode_input_context,
    resolve_reserved_python_rsi_episode_input_context,
)
from lunar_evolution.rsi_python_scheduler_inputs import PythonRSISchedulerPlanFactory


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("reserved input fixture attempted external execution")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


def _setup(tmp_path, monkeypatch, *, marker=True, count=2):
    # This existing inert runtime fixture has a binding larger than the production
    # stager cap. Its local cap adjustment tests wiring, not accepted toolchain size.
    import lunar_evolution.rsi_producer_launch as launch
    import lunar_evolution.rsi_producer_staging_capsule as capsule

    monkeypatch.setattr(launch, "MAX_STAGING_BINDING_BYTES", 64 * 1024)
    monkeypatch.setattr(capsule, "MAX_READY_BINDING_BYTES", 64 * 1024)
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    controller = RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.root, producer_child_execution=True,
        producer_multi_episode_publication=True,
        producer_known_rejection=True,
        producer_stager=PythonProducerEpisodeStager(PythonProducerEpisodeStagingConfig(
            workspace=value.root, root_sidecar=value.sidecar,
            artifact=value.native.artifact, attestation_supplier=supplier,
        )),
    )
    run_id = value.binding.run_id
    pins = {name: getattr(value.request, name) for name in (
        "contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id")}
    target = controller._target_episode(run_id, run_id + "-target", pins, 0)
    decisions = [DeterministicCurriculum().choose(target=target, diagnosis="inert gap", wave=0, ordinal=i)
                 for i in range(count)]
    plan = {"mode": "brs", "wave": 0, "max_workers": 1,
            "practices": [item.to_dict() for item in decisions]}
    if marker:
        plan["reserved_native_serial"] = True
    budget = {**dict(value.request.budget), "max_practice_rounds": count,
              "max_practice_episodes": count, "max_solver_invocations": count,
              "max_evaluator_invocations": count, "max_verifier_invocations": count}
    with value.ledger.controller_lock(run_id):
        record = controller._start_run(run_id=run_id, mode="brs", plan=plan, budget=budget,
            producer_checkpoint_binding=value.proof.to_dict(), **pins)
        state = controller._flow_state(record, run_id=run_id, plan=plan, pins=pins, budget=budget)
        controller._save_flow(record, state)
        for i, decision in enumerate(decisions):
            episode = PracticeEpisode(f"{run_id}-practice-0-{i}", run_id, pins["contract_sha256"],
                pins["evaluator_sha256"], pins["environment_sha256"], controller.snapshot.digest(),
                pins["solver_id"], "planned", wave=0, ordinal=i,
                parent_target_episode_id=run_id + "-target-seed")
            request = controller._request(episode, budget=state["budget_state"]["planned"],
                charter={**decision.to_dict(), "decision_sha256": decision.digest()})
            controller._prepare_intent(record, state, episode, request)
    value.controller, value.supplier, value.state = controller, supplier, state
    value.wave_memory = controller.snapshot
    value.ids = tuple(state["intents"])
    return value


def _stage(value, *, ordinal=0):
    intent = value.state["intents"][value.ids[ordinal]]
    episode = PracticeEpisode.from_dict(intent["episode"])
    request = SolverRequest.from_dict(intent["request"])
    head = value.controller._stage_producer_episode(value.state, episode, request)
    return head, request


def test_private_brs_staging_preserves_full_reservation_and_read_only_original_inputs(tmp_path, monkeypatch):
    value = _setup(tmp_path, monkeypatch)
    original = deepcopy(value.state)
    with value.ledger.controller_lock(value.binding.run_id):
        head, request = _stage(value)
        before = _inventory(value.root)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        original_observation = read_reserved_brs_reservation(value.ledger, run_id=value.binding.run_id,
            episode_ids=value.ids, expected_checkpoint_sha256=head)
        child = resolve_reserved_python_rsi_episode_input_context(value.context, value.ledger,
            request, value.wave_memory, expected_checkpoint_sha256=head)
        repeated = resolve_reserved_python_rsi_episode_input_context(value.context, value.ledger,
            request, value.wave_memory, expected_checkpoint_sha256=head)
    assert child is not repeated and child.native_context is not repeated.native_context
    assert child.native_context.intent.task_id == value.ids[0]
    assert child.native_context.attestation.nonce != value.context.native_context.attestation.nonce
    assert child.native_context.execution_control is value.context.native_context.execution_control
    assert child.native_context.python_handoff_after_execution is value.native.python_handoff_after_execution
    assert PythonRSISchedulerPlanFactory(child)(request, value.wave_memory) == PythonRSISchedulerPlanFactory(repeated)(request, value.wave_memory)
    assert original_observation.original_state() == original
    assert value.state["budget_state"] == original["budget_state"]
    assert _inventory(value.root) == before
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert value.ledger.get_episode(request.episode_id) is None
    assert len(value.supplier.observations) == 1
    assert value.ledger.get_episode(value.ids[1]) is None


def test_legacy_brs_without_private_original_plan_marker_still_refuses_staging(tmp_path, monkeypatch):
    value = _setup(tmp_path, monkeypatch, marker=False)
    before = _inventory(value.root)
    with value.ledger.controller_lock(value.binding.run_id), pytest.raises(RSILearningError, match="owner_required"):
        _stage(value)
    assert _inventory(value.root) == before
    assert value.supplier.observations == []


@pytest.mark.parametrize("fault", ["public-resolver", "no-lease", "head", "memory", "request"])
def test_reserved_input_drift_refuses_without_claim_or_new_attestation(tmp_path, monkeypatch, fault):
    value = _setup(tmp_path, monkeypatch)
    with value.ledger.controller_lock(value.binding.run_id):
        head, request = _stage(value)
    before = _inventory(value.root)
    memory = value.wave_memory
    resolver = resolve_reserved_python_rsi_episode_input_context
    if fault == "public-resolver":
        resolver = resolve_python_rsi_episode_input_context
    elif fault == "head":
        head = "a" * 64
    elif fault == "memory":
        memory = replace(memory, parent_snapshot_sha256="a" * 64)
    elif fault == "request":
        request = replace(request, episode_id=value.ids[1])
    from contextlib import nullcontext

    guard = nullcontext() if fault == "no-lease" else value.ledger.controller_lock(value.binding.run_id)
    with guard, pytest.raises(RSILearningError):
        resolver(value.context, value.ledger, request, memory, expected_checkpoint_sha256=head)
    assert _inventory(value.root) == before
    assert len(value.supplier.observations) == 1
    assert all(value.ledger.get_episode(key) is None for key in value.ids)


@pytest.mark.parametrize("field", ["marker", "workers", "policy", "child", "publication"])
def test_original_serial_staging_metadata_is_strict(field):
    state = {"mode": "brs", "plan": {"mode": "brs", "max_workers": 1, "reserved_native_serial": True},
        "producer_child_execution": True, "producer_multi_episode_publication": True,
        "producer_brs_checkpoint_policy": {"mode": "brs", "max_workers": 1,
            "production_admission": False, "online_publication": False}}
    assert reserved_brs_staging_mode(state)
    if field == "marker":
        state["plan"]["reserved_native_serial"] = 1
    elif field == "workers":
        state["plan"]["max_workers"] = True
    elif field == "policy":
        state["producer_brs_checkpoint_policy"]["online_publication"] = True
    elif field == "child":
        state["producer_child_execution"] = 1
    else:
        state["producer_multi_episode_publication"] = 1
    assert not reserved_brs_staging_mode(state)


def test_reserved_gateway_resolution_is_fresh_read_only_and_keeps_root_gateway(tmp_path, monkeypatch):
    value = _setup(tmp_path, monkeypatch)
    with value.ledger.controller_lock(value.binding.run_id):
        head, request = _stage(value)
        before = _inventory(value.root)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        first = resolve_reserved_python_producer_episode_gateway(value.controller, request,
            value.wave_memory, expected_checkpoint_sha256=head)
        second = resolve_reserved_python_producer_episode_gateway(value.controller, request,
            value.wave_memory, expected_checkpoint_sha256=head)
    assert first is not second and first is not value.gateway
    assert value.controller.gateway is value.gateway
    assert first.config.receipt_provider is not second.config.receipt_provider
    assert first.config.receipt_provider._python_admission_controller is None
    assert first.config.receipt_provider._brs_native_binding is None
    assert first._plan(request, value.wave_memory) == second._plan(request, value.wave_memory)
    assert _inventory(value.root) == before
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert len(value.supplier.observations) == 1
    assert all(value.ledger.get_episode(key) is None for key in value.ids)


@pytest.mark.parametrize("stage_ready", [False, True])
def test_whole_original_observation_keeps_reservations_and_counts_ready_materials(tmp_path, monkeypatch, stage_ready):
    value = _setup(tmp_path, monkeypatch)
    with value.ledger.controller_lock(value.binding.run_id):
        if stage_ready:
            _stage(value)
        before, budget = _inventory(value.root), deepcopy(value.state["budget_state"])
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        observed = read_reserved_brs_serial_observation(value.controller, value.state)
    assert observed.projection.reservation_count == 2
    assert observed.projection.completion_count == 0
    assert observed.projection.next_ordinal == 0
    assert observed.projection.retained_materials if stage_ready else not observed.projection.retained_materials
    assert value.state["budget_state"] == budget
    assert _inventory(value.root) == before
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history


@pytest.mark.parametrize("trace", ["orphan-batch", "native-receipt", "lineage-before"])
def test_any_untouched_suffix_native_trace_blocks_selection_without_sql_claim(tmp_path, monkeypatch, trace):
    value = _setup(tmp_path, monkeypatch)
    with value.ledger.controller_lock(value.binding.run_id):
        ordinal = 1 if trace == "orphan-batch" else 0
        if trace != "orphan-batch":
            _stage(value)
        request = SolverRequest.from_dict(value.state["intents"][value.ids[ordinal]]["request"])
        identity = value.controller.producer_stager.identity(value.controller, value.state, request, value.wave_memory)
        batch = value.root / "evolution/producer-batches" / identity["journal_id"]
        if trace == "orphan-batch":
            batch.mkdir(mode=0o700)
        elif trace == "native-receipt":
            (batch / "execution-receipt.json").write_text("{}")
        else:
            (batch / "lineage/before.json").write_text("{}")
        before = _inventory(value.root)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises(RSILearningError, match="untouched_native_trace"):
            read_reserved_brs_serial_observation(value.controller, value.state)
    assert _inventory(value.root) == before
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert all(value.ledger.get_episode(key) is None for key in value.ids)


def test_original_plan_marker_cannot_be_retrofitted_into_latest_checkpoint(tmp_path, monkeypatch):
    value = _setup(tmp_path, monkeypatch, marker=False)
    with value.ledger.controller_lock(value.binding.run_id):
        before = value.ledger.controller_checkpoint_history(value.binding.run_id)
        proposed = deepcopy(value.state)
        proposed["plan"]["reserved_native_serial"] = True
        with pytest.raises(RSILearningError):
            value.controller._save_flow(value.ledger.get_run(value.binding.run_id), proposed)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == before
    assert value.supplier.observations == []
