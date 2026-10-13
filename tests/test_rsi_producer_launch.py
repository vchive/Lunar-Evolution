"""Staging association, bounded shapes and inert child evidence; no execution."""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import replace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_producer_gateway import _fixture
from test_rsi_producer_staging_controller import ObservedAttestations, _controller, _run

from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemorySnapshot, PracticeEpisode, RSILearningError
from lunar_evolution.rsi_producer_launch import MAX_STAGING_CHECKPOINT_BYTES


def _planned(value):
    return PracticeEpisode(
        value.request.episode_id, value.binding.run_id, value.request.contract_sha256,
        value.request.evaluator_sha256, value.request.environment_sha256,
        value.memory.digest(), value.request.solver_id, "planned",
    )


def _ready(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    controller = _controller(value, supplier)
    with pytest.raises(RSILearningError, match="dispatch_not_accepted"):
        _run(controller, value)
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    entry = state["producer_episode_staging"][state["current_episode_id"]]
    return value, supplier, controller, state, entry


@pytest.mark.parametrize("dto", ["episode", "request", "memory"])
def test_shadowed_serializers_refuse_before_callbacks_or_files(tmp_path, monkeypatch, dto):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    stager = _controller(value, supplier).producer_stager
    episode, request, memory = _planned(value), replace(value.request), replace(value.memory)
    target = {"episode": episode, "request": request, "memory": memory}[dto]
    method = "to_record_dict" if dto == "episode" else "to_dict"
    object.__setattr__(target, method, lambda: pytest.fail("shadowed serializer executed"))
    before = _inventory(value.root)
    with pytest.raises(RSILearningError):
        stager.pure_preflight({"producer_episode_staging": {}, "intents": {}}, episode, request, memory)
    assert _inventory(value.root) == before
    assert supplier.observations == []


def test_hostile_episode_refuses_before_properties(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    stager = _controller(value, ObservedAttestations(value.ledger)).producer_stager

    class Hostile:
        @property
        def episode_id(self):
            pytest.fail("hostile episode property evaluated")

    with pytest.raises(RSILearningError, match="episode_invalid"):
        stager.pure_preflight({}, Hostile(), value.request, value.memory)


def test_capacity_and_input_size_refuse_without_staging(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    stager = _controller(value, supplier).producer_stager
    before = _inventory(value.root)
    state = {"producer_episode_staging": {}, "intents": {}, "padding": "x" * (MAX_STAGING_CHECKPOINT_BYTES - 1000)}
    with pytest.raises(RSILearningError, match="checkpoint_capacity_exhausted"):
        stager.pure_preflight(state, _planned(value), value.request, value.memory)
    large = replace(value.request, solver_settings=(("bounded", "x" * 9000),))
    with pytest.raises(RSILearningError, match="wire_invalid"):
        stager.pure_preflight({"producer_episode_staging": {}, "intents": {}}, _planned(value), large, value.memory)
    assert _inventory(value.root) == before
    assert supplier.observations == []
    assert value.ledger.get_run(value.binding.run_id) is None


@pytest.mark.parametrize("field", ["request_sha256", "memory_snapshot_sha256", "journal_id", "launch_id", "extra"])
def test_retained_identity_is_rederived_from_original_intent(tmp_path, monkeypatch, field):
    value, supplier, controller, state, entry = _ready(tmp_path, monkeypatch)
    history = deepcopy(value.ledger.controller_checkpoint_history(value.binding.run_id))
    for _, snapshot in history:
        for retained in snapshot.get("producer_episode_staging", {}).values():
            retained["identity"][field] = "different" if field in {"journal_id", "launch_id", "extra"} else "c" * 64
    changed = history[-1][1]
    before = _inventory(value.root)
    monkeypatch.setattr(value.ledger, "controller_checkpoint_history", lambda _: history)
    with pytest.raises(RSILearningError, match="history_identity_drift"):
        controller.producer_stager.validate_state(controller, changed)
    assert _inventory(value.root) == before
    assert len(supplier.observations) == 1
    assert state["producer_episode_staging"][state["current_episode_id"]] == entry


def test_preparing_must_immediately_follow_original_intent_checkpoint(tmp_path, monkeypatch):
    value, _, controller, state, entry = _ready(tmp_path, monkeypatch)
    history = deepcopy(value.ledger.controller_checkpoint_history(value.binding.run_id))
    index = next(index for index, (digest, _) in enumerate(history) if digest == entry["identity"]["origin_checkpoint_sha256"])
    history.insert(index + 1, ("c" * 64, deepcopy(history[index][1])))
    monkeypatch.setattr(value.ledger, "controller_checkpoint_history", lambda _: history)
    with pytest.raises(RSILearningError, match="history_origin_drift"):
        controller.producer_stager.validate_state(controller, state)


@pytest.mark.parametrize("mutation", ["remove", "ready_retrofit", "unknown_ready"])
def test_history_cannot_remove_retrofit_or_promote_unknown_proof(tmp_path, monkeypatch, mutation):
    value, _, controller, state, _ = _ready(tmp_path, monkeypatch)
    history = deepcopy(value.ledger.controller_checkpoint_history(value.binding.run_id))
    key = state["current_episode_id"]
    changed = deepcopy(state)
    if mutation == "remove":
        changed["producer_episode_staging"].clear()
    elif mutation == "ready_retrofit":
        history = [(digest, snapshot) for digest, snapshot in history if not any(
            item["state"] == "preparing" for item in snapshot.get("producer_episode_staging", {}).values()
        )]
    else:
        changed["producer_episode_staging"][key]["state"] = "unknown"
        changed["producer_episode_staging"][key]["failure_code"] = "staging_failed"
    monkeypatch.setattr(value.ledger, "controller_checkpoint_history", lambda _: history)
    with pytest.raises(RSILearningError):
        controller.producer_stager.validate_state(controller, changed)


def test_ready_retains_original_inode_pin_and_full_plan(tmp_path, monkeypatch):
    value, supplier, controller, _, entry = _ready(tmp_path, monkeypatch)
    stager = controller.producer_stager
    original = deepcopy(entry)
    stager.validate_ready(entry["identity"], entry["ready"])
    changed_plan = deepcopy(entry["ready"])
    changed_plan["plan"]["candidate_selector_sha256"] = "d" * 64
    with pytest.raises(RSILearningError, match="ready_plan_drift"):
        stager.validate_ready(entry["identity"], changed_plan)
    child = next(path for path in value.root.rglob("python-producer-binding.json") if "rsi-stage-" in str(path))
    stat = child.stat()
    os.utime(child, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    with pytest.raises(RSILearningError):
        stager.validate_ready(entry["identity"], entry["ready"])
    assert entry == original
    assert len(supplier.observations) == 1


class MutatingAttestations(ObservedAttestations):
    def __call__(self, intent):
        result = super().__call__(intent)
        object.__setattr__(intent, "producer_id", "shinka")
        return result


def test_attestation_callback_cannot_change_original_launch_policy(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = MutatingAttestations(value.ledger)
    assert _run(_controller(value, supplier), value).status == "unknown"
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    assert state["producer_episode_staging"][state["current_episode_id"]]["failure_code"] == "staging_failed"
    assert len(supplier.observations) == 1
    assert len(list(value.root.rglob("python-producer-binding.json"))) == 1


def test_direct_stage_requires_original_controller_and_durable_preparing(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    controller = _controller(value, supplier)
    before = _inventory(value.root)

    class Hostile:
        @property
        def ledger(self):
            pytest.fail("forged owner property evaluated")

    for owner in (Hostile(), controller):
        with pytest.raises(RSILearningError, match="owner_required"):
            controller.producer_stager.stage(
                owner, {"run_id": value.binding.run_id, "mode": "drs"},
                expected_checkpoint_sha256="c" * 64, request=value.request, memory=value.memory,
            )
    assert supplier.observations == []
    assert _inventory(value.root) == before


def test_config_artifact_and_supplier_drift_refuse_before_effects(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    stager = _controller(value, supplier).producer_stager
    before = _inventory(value.root)
    object.__setattr__(stager.config, "attestation_supplier", ObservedAttestations(value.ledger))
    with pytest.raises(RSILearningError, match="configuration_drift"):
        stager.pure_preflight({}, _planned(value), value.request, value.memory)
    object.__setattr__(stager.config, "attestation_supplier", supplier)
    object.__setattr__(stager.config.artifact, "compiler", "drifted")
    with pytest.raises(RSILearningError, match="configuration_drift"):
        stager.pure_preflight({}, _planned(value), value.request, value.memory)
    assert _inventory(value.root) == before
    assert supplier.observations == []


def test_reopened_preparing_and_original_lock_cannot_restage(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    original_write = value.ledger.write_controller_checkpoint

    def interrupt_after_preparing(run_id, state, **kwargs):
        if any(entry["state"] in {"ready", "unknown"} for entry in state.get("producer_episode_staging", {}).values()):
            raise OSError("fixture retains original preparing boundary")
        return original_write(run_id, state, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(value.ledger, "write_controller_checkpoint", interrupt_after_preparing)
        with pytest.raises(RSILearningError, match="staging_checkpoint_conflict"):
            _run(_controller(value, supplier), value)
    checkpoint_sha, state = value.ledger.controller_checkpoint(value.binding.run_id)
    entry = state["producer_episode_staging"][state["current_episode_id"]]
    assert entry["state"] == "preparing"
    restarted = _controller(value, supplier)
    before = _inventory(value.root)
    with value.ledger.controller_lock(value.binding.run_id), pytest.raises(RSILearningError, match="owner_required"):
        restarted.producer_stager.stage(
            restarted, state, expected_checkpoint_sha256=checkpoint_sha,
            request=SolverRequest.from_dict(entry["identity"]["intent"]["request"]),
            memory=MemorySnapshot.from_dict(entry["identity"]["memory"]),
        )
    assert _inventory(value.root) == before
    assert len(supplier.observations) == 1
