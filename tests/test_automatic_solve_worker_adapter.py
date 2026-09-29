from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from lunar_evolution.agents import AgentRequest
from lunar_evolution.automatic_solve_continuation import AutomaticSolveContinuation
from lunar_evolution.automatic_solve_worker_adapter import (
    AutomaticSolveAwaitingInput,
    AutomaticSolveRecoveryRequired,
    AutomaticSolveWorkerAdapter,
    AutomaticSolveWorkerBridge,
)
from lunar_evolution.store import Store


def _fixture(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("bridge", tmp_path / "run")
    request = {"automatic_lifecycle_version": 1, "bundle_mode": "compiled", "timeout": 5}
    store.append_event(run.id, "evolution_requested", request)
    controller = SimpleNamespace(store=store, runtime=SimpleNamespace(name="fixture"))
    continuation = AutomaticSolveContinuation(
        run_id=run.id,
        workspace=str(run.workspace),
        request_json=json.dumps(request),
        request_sha256=hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        runtime_fingerprint="a" * 64,
    )
    worker = store.create_worker(run.id, "automatic-solve", "bridge", agent_type="automatic-solve")
    attempt = store.start_worker_attempt(worker.id, run.id, "continue", service_owner_id="service")
    adapter = AutomaticSolveWorkerAdapter(object(), controller, continuation)
    adapter.admit(worker, attempt, "service")
    return store, run, worker, attempt, adapter, controller, continuation


def _request():
    return AgentRequest(
        run_id="worker-run",
        task_id="worker-attempt",
        role="automatic-solve",
        prompt="continue",
        workspace="/tmp",
    )


def test_adapter_requires_explicit_admission(monkeypatch, tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("bridge", tmp_path / "run")
    request = {"automatic_lifecycle_version": 1, "bundle_mode": "compiled", "timeout": 5}
    store.append_event(run.id, "evolution_requested", request)
    controller = SimpleNamespace(store=store, runtime=SimpleNamespace(name="fixture"))
    continuation = AutomaticSolveContinuation(
        run_id=run.id, workspace=str(run.workspace), request_json=json.dumps(request),
        request_sha256=hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        runtime_fingerprint="a" * 64,
    )
    adapter = AutomaticSolveWorkerAdapter(object(), controller, continuation)
    with pytest.raises(ValueError, match="explicit admission"):
        adapter.run(_request())


def test_adapter_records_terminal_native_reference_without_second_execution(monkeypatch, tmp_path):
    store, run, worker, _attempt, adapter, controller, continuation = _fixture(tmp_path)

    def native(_config, _controller, _continuation, **_kwargs):
        store.cancel_run(run.id)
        return {"run_id": run.id, "status": "cancelled"}

    monkeypatch.setattr(
        "lunar_evolution.automatic_solve_worker_adapter.continue_automatic_solve", native,
    )
    result = adapter.run(_request())
    assert result.status == "cancelled"
    assert result.metadata["binding_id"]
    binding = store.list_automatic_solve_worker_bindings(run.id)[0]
    reference = store.get_automatic_solve_worker_result_reference(
        binding.binding_id, owner_id=run.id, generation=binding.generation,
    )
    assert reference is not None and reference.outcome == "cancelled"
    assert store.list_worker_attempts(worker.id, run.id)[0].id


def test_awaiting_input_is_typed_and_does_not_publish_result(monkeypatch, tmp_path):
    store, run, _worker, _attempt, adapter, _controller, _continuation = _fixture(tmp_path)
    monkeypatch.setattr(
        "lunar_evolution.automatic_solve_worker_adapter.continue_automatic_solve",
        lambda *_args, **_kwargs: {"run_id": run.id, "status": "awaiting_input"},
    )
    with pytest.raises(AutomaticSolveAwaitingInput):
        adapter.run(_request())
    binding = store.list_automatic_solve_worker_bindings(run.id)[0]
    assert binding.state.value == "awaiting_input"
    assert binding.result_ref_digest is None


def test_bridge_owner_and_read_api(tmp_path):
    store, run, worker, _attempt, _adapter, controller, continuation = _fixture(tmp_path)
    bridge = AutomaticSolveWorkerBridge(object(), controller)
    with pytest.raises(PermissionError):
        bridge.dispatch("other-owner", continuation)
    assert bridge.read(run.id, worker.id) is None
