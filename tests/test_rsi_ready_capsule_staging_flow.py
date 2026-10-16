"""Capacity and orphan semantics at the original controller staging CAS."""

from __future__ import annotations

import subprocess

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_multi_episode_policy import _controller
from test_rsi_producer_gateway import _fixture
from test_rsi_producer_launch import _planned
from test_rsi_producer_staging_controller import _run

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_producer_launch import MAX_STAGING_CHECKPOINT_BYTES


@pytest.fixture(autouse=True)
def _no_process(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("capsule staging regression must not launch a process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


def test_capsule_preflight_reserves_reference_without_raising_original_ceiling(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value, publication=True)
    stager = controller.producer_stager
    state = {"producer_multi_episode_publication": True, "producer_episode_staging": {},
             "intents": {}, "padding": "x" * 70_000}
    before = _inventory(value.root)
    growth = stager.pure_preflight(state, _planned(value), value.request, value.memory)
    assert len(canonical_json(state)) + growth < MAX_STAGING_CHECKPOINT_BYTES == 112 * 1024
    legacy = dict(state)
    legacy.pop("producer_multi_episode_publication")
    with pytest.raises(RSILearningError, match="checkpoint_capacity_exhausted"):
        stager.pure_preflight(legacy, _planned(value), value.request, value.memory)
    state["padding"] = "x" * (MAX_STAGING_CHECKPOINT_BYTES - 1000)
    with pytest.raises(RSILearningError, match="checkpoint_capacity_exhausted"):
        stager.pure_preflight(state, _planned(value), value.request, value.memory)
    assert _inventory(value.root) == before
    assert supplier.observations == []
    assert value.ledger.get_run(value.binding.run_id) is None


class _InterruptedReadyCAS(BaseException):
    pass


def test_capsule_written_without_ready_cas_remains_an_unadoptable_obligation(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value, publication=True)
    original_write = value.ledger.write_controller_checkpoint

    def interrupted(run_id, state, **kwargs):
        if any(entry["state"] == "ready" for entry in state.get("producer_episode_staging", {}).values()):
            raise _InterruptedReadyCAS()
        return original_write(run_id, state, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(value.ledger, "write_controller_checkpoint", interrupted)
        with pytest.raises(_InterruptedReadyCAS):
            _run(controller, value)
    checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)
    state = checkpoint[1]
    entry = state["producer_episode_staging"][state["current_episode_id"]]
    assert entry["state"] == "preparing" and entry["ready"] is None
    assert len(list(value.root.glob("evolution/producer-batches/*/lineage/rsi-ready.snapshot"))) == 1
    assert len(supplier.observations) == 1
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    restarted, restarted_supplier = _controller(value, publication=True)
    with pytest.raises(RSILearningError):
        restarted.resume(value.binding.run_id)
    assert restarted_supplier.observations == []
    assert value.ledger.controller_checkpoint(value.binding.run_id) == checkpoint
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert _inventory(value.root) == before
