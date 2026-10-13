"""Read-only staged child context resolution over inert local files."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_producer_gateway import _fixture
from test_rsi_store_child_proof import _store_ready

import lunar_evolution.rsi_producer_launch as producer_launch
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemorySnapshot, RSILearningError
from lunar_evolution.rsi_python_episode_inputs import resolve_python_rsi_episode_input_context
from lunar_evolution.rsi_python_scheduler_inputs import (
    PythonRSISchedulerInputContext,
    PythonRSISchedulerPlanFactory,
)


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


def test_ready_child_context_preserves_cancellation_and_deadline_binding_read_only(tmp_path, monkeypatch):
    """Recovery input inspection never turns cancellation/deadline into launch authority."""
    value, supplier, controller, head, request, memory, entry = _case(tmp_path, monkeypatch)
    cancelled = lambda: True
    native = replace(value.native, cancelled=cancelled)
    value.context = PythonRSISchedulerInputContext(native, value.sidecar, value.proof)
    expired = replace(request, budget=(("deadline_unix", 1.0),))
    # The staged proof binds the original request/deadline, so a changed caller deadline
    # must refuse before the resolver can silently refresh or widen it.
    with pytest.raises(RSILearningError):
        resolve_python_rsi_episode_input_context(
            value.context, value.ledger, expired, memory, expected_checkpoint_sha256=head,
        )
    child = resolve_python_rsi_episode_input_context(
        value.context, value.ledger, request, memory, expected_checkpoint_sha256=head,
    )
    assert child.native_context.cancelled is cancelled
    assert child.native_context.execution_control is value.native.execution_control
    assert child.producer_sidecar.binding.deadline_unix == value.sidecar.binding.deadline_unix
    assert child.producer_sidecar.binding.deadline_unix == entry["ready"]["binding"]["deadline_unix"]
    assert len(supplier.observations) == 1
    assert controller.producer_sidecar is value.sidecar
    assert value.ledger.get_episode(request.episode_id) is None


def test_unknown_child_context_cannot_be_recovered_from_root_sidecar(tmp_path, monkeypatch):
    """A staging unknown remains quarantined even when the root sidecar is intact."""
    from test_rsi_producer_staging_controller import ObservedAttestations, _controller, _run

    monkeypatch.setattr(producer_launch, "MAX_STAGING_BINDING_BYTES", 64 * 1024)
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger, failure=True)
    controller = _controller(value, supplier)
    result = _run(controller, value)
    assert result.status == "unknown"
    head = value.ledger.controller_checkpoint(value.binding.run_id)[0]
    request = value.request
    memory = value.memory
    with pytest.raises(RSILearningError, match="episode_evidence_invalid"):
        resolve_python_rsi_episode_input_context(
            value.context, value.ledger, request, memory, expected_checkpoint_sha256=head,
        )
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
