from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from lunar_evolution.agents import AgentRequest
from lunar_evolution.automatic_solve_continuation import AutomaticSolveContinuation
from lunar_evolution.automatic_solve_worker_adapter import (
    AutomaticSolveAwaitingInput,
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
    @contextmanager
    def observation(_parent_id, observer, released, guard):
        assert callable(observer) and callable(released) and callable(guard)
        yield object()

    controller = SimpleNamespace(
        store=store, runtime=SimpleNamespace(name="fixture"),
        automatic_worker_observation=observation,
    )
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
    adapter.set_worker_context(SimpleNamespace(workspace=tmp_path / "service"), run.id, worker.id)
    return store, run, worker, attempt, adapter, controller, continuation


def _request(adapter=None, *, timeout=None):
    return AgentRequest(
        run_id="worker-run" if adapter is None else f"worker-run-{adapter._worker_id}",
        task_id="worker-attempt" if adapter is None else adapter._worker_attempt_id,
        role="automatic-solve",
        prompt="continue",
        workspace=(
            "/tmp" if adapter is None else str(
                adapter._worker_service.workspace / "workers" / adapter._worker_id / adapter._worker_attempt_id
            )
        ),
        timeout=timeout,
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
    store, run, worker, _attempt, adapter, _controller, _continuation = _fixture(tmp_path)

    def native(_config, _controller, _continuation, **_kwargs):
        store.cancel_run(run.id)
        return {"run_id": run.id, "status": "cancelled"}

    monkeypatch.setattr(
        "lunar_evolution.automatic_solve_worker_adapter.continue_automatic_solve", native,
    )
    monkeypatch.setattr(
        "lunar_evolution.automatic_solve_worker_adapter.capture_native_result",
        lambda _controller, binding: {
            "schema_version": "1", "kind": "lunar-native-result-reference",
            "binding": {"binding_id": binding.binding_id, "generation": binding.generation,
                         "run_id": binding.run_id, "worker_attempt_id": binding.worker_attempt_id},
            "outcome": "cancelled", "lifecycle_digest": binding.lifecycle_digest,
            "runtime_fingerprint": binding.runtime_fingerprint,
            "workspace": {"sha256": "a" * 64, "device": 1, "inode": 1},
            "native": {"status": "cancelled", "child_run_id": None, "contract_digest": None,
                        "terminal_event": "run_cancelled", "terminal_event_sha256": "b" * 64,
                        "artifact_manifest_sha256": "c" * 64, "artifact_count": 0, "delivery": None},
            "cleanup": {"native_attempt_processes": 0, "worker_processes": 0},
        },
    )
    result = adapter.run(_request(adapter))
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
        adapter.run(_request(adapter))
    binding = store.list_automatic_solve_worker_bindings(run.id)[0]
    assert binding.state.value == "awaiting_input"
    assert binding.result_ref_digest is None


def test_worker_timeout_preserves_absent_native_wall_policy(tmp_path):
    store, _run, _worker, _attempt, adapter, _controller, _continuation = _fixture(tmp_path)
    policy = json.loads(store.list_automatic_solve_worker_bindings(_run.id)[0].normalized_policy())
    assert policy["worker_active_timeout"] is None
    control = adapter._control(AgentRequest(
        run_id="worker-run", task_id="worker-attempt", role="automatic-solve",
        prompt="continue", workspace="/tmp", timeout=99,
    ))
    assert control.timeout_seconds == 99.0
    assert adapter._control(_request(adapter)) is None


def test_missing_observation_seam_is_recovery_required(tmp_path, monkeypatch):
    store, run, _worker, _attempt, adapter, controller, _continuation = _fixture(tmp_path)
    delattr(controller, "automatic_worker_observation")
    monkeypatch.setattr(
        "lunar_evolution.automatic_solve_worker_adapter.continue_automatic_solve",
        lambda *_args, **_kwargs: pytest.fail("native continuation must not run without observation"),
    )
    with pytest.raises(Exception) as exc_info:
        adapter.run(_request(adapter))
    assert getattr(exc_info.value, "worker_stop_reason", None) == "recovery_required"
    binding = store.list_automatic_solve_worker_bindings(run.id)[0]
    assert binding.state.value == "recovery_required"


def test_bridge_owner_and_read_api(tmp_path):
    _store, run, worker, _attempt, _adapter, controller, continuation = _fixture(tmp_path)
    bridge = AutomaticSolveWorkerBridge(object(), controller)
    with pytest.raises(PermissionError):
        bridge.dispatch("other-owner", continuation)
    assert bridge.read(run.id, worker.id) is None
