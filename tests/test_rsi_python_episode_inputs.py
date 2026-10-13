"""Read-only staged child context resolution over inert local files."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_store_child_proof import _store_ready

from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemorySnapshot, RSILearningError
from lunar_evolution.rsi_python_episode_inputs import resolve_python_rsi_episode_input_context
from lunar_evolution.rsi_python_scheduler_inputs import PythonRSISchedulerPlanFactory


def _case(tmp_path, monkeypatch):
    value, supplier, controller, _state, entry = _store_ready(tmp_path, monkeypatch)
    head = value.ledger.controller_checkpoint(value.binding.run_id)[0]
    request = SolverRequest.from_dict(entry["identity"]["intent"]["request"])
    memory = MemorySnapshot.from_dict(entry["identity"]["memory"])
    return value, supplier, controller, head, request, memory, entry


def test_ready_child_context_has_exact_plan_preserves_root_and_performs_no_writes(tmp_path, monkeypatch):
    value, supplier, controller, head, request, memory, entry = _case(tmp_path, monkeypatch)
    inventory = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    root = value.context._projection_json
    child = resolve_python_rsi_episode_input_context(
        value.context, value.ledger, request, memory, expected_checkpoint_sha256=head,
    )
    assert child.native_context.intent.journal_id == entry["identity"]["journal_id"]
    assert child.native_context.intent.task_id == request.episode_id
    assert child.native_context.python_handoff_after_execution is value.native.python_handoff_after_execution
    assert PythonRSISchedulerPlanFactory(child)(request, memory).to_dict() == entry["ready"]["plan"]
    assert value.context._projection_json == root
    assert controller.producer_sidecar is value.sidecar
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert _inventory(value.root) == inventory
    assert len(supplier.observations) == 1
    assert value.ledger.get_episode(request.episode_id) is None
    assert value.ledger.episode_result(request.episode_id) is None


@pytest.mark.parametrize("mutation", ["checkpoint", "request", "memory"])
def test_input_drift_refuses_without_new_claim_or_staging(tmp_path, monkeypatch, mutation):
    value, supplier, _controller, head, request, memory, _entry = _case(tmp_path, monkeypatch)
    before = _inventory(value.root)
    if mutation == "checkpoint":
        head = "a" * 64
    elif mutation == "request":
        request = replace(request, solver_settings=(("different", True),))
    else:
        memory = MemorySnapshot("different", None, ())
    with pytest.raises(RSILearningError):
        resolve_python_rsi_episode_input_context(
            value.context, value.ledger, request, memory, expected_checkpoint_sha256=head,
        )
    assert _inventory(value.root) == before
    assert len(supplier.observations) == 1
    assert value.ledger.get_episode(request.episode_id) is None
