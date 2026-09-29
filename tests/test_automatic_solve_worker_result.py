"""Provider-free, read-only native WorkerService result references."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_bundle_parent_delivery import _completed

from lunar_evolution.automatic_solve_worker_binding import AutomaticSolveWorkerBinding
from lunar_evolution.automatic_solve_worker_result import (
    NativeResultReferenceError,
    capture_native_result,
    validate_native_result,
)
from lunar_evolution.cli import _compiler_fingerprint
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.runtime import MockRuntime
from lunar_evolution.store import Store


def _request() -> dict[str, object]:
    return {"automatic_lifecycle_version": 1, "bundle_mode": "compiled", "strategy": "population", "timeout": 3}


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _binding(store, run, *, child_id=None, contract_digest=None, runtime=None, append_request=True):
    request = _request()
    if append_request:
        store.append_event(run.id, "evolution_requested", request)
    worker = store.create_worker(run.id, "solver", "native bridge", agent_type="fixture")
    attempt = store.start_worker_attempt(worker.id, run.id, "native bridge", service_owner_id="service-owner")
    runtime = runtime or MockRuntime()
    return (
        AutomaticSolveWorkerBinding(
            binding_id="automatic-binding-result",
            owner_id=run.id,
            run_id=run.id,
            workspace_identity=str(run.workspace),
            worker_id=worker.id,
            worker_attempt_id=attempt.id,
            service_owner_id="service-owner",
            lifecycle_digest=_digest(request),
            runtime_fingerprint=_compiler_fingerprint(runtime),
            budget_policy=request,
            contract_digest=contract_digest,
            child_run_id=child_id,
        ),
        runtime,
    )


def test_cancelled_native_result_is_bounded_and_read_only(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    workspace = tmp_path / "run"
    workspace.mkdir()
    run = store.create_run("cancel", workspace)
    runtime = MockRuntime()
    binding, _ = _binding(store, run, runtime=runtime)
    controller = LocalController(Config(tmp_path / "home"), runtime, store=store)
    store.cancel_run(run.id)
    before = (store.list_events(run.id), store.list_artifacts(run.id), sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*")))
    reference = capture_native_result(controller, binding)
    assert reference["kind"] == "lunar-native-result-reference"
    assert reference["outcome"] == "cancelled"
    assert reference["native"]["delivery"] is None
    assert "workspace" in reference and "inode" in reference["workspace"]
    assert validate_native_result(controller, binding, reference) == reference
    after = (store.list_events(run.id), store.list_artifacts(run.id), sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*")))
    assert after == before


def test_failed_native_result_accepts_budget_terminal_without_delivery(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    workspace = tmp_path / "run"
    workspace.mkdir()
    run = store.create_run("failed", workspace)
    runtime = MockRuntime()
    binding, _ = _binding(store, run, runtime=runtime)
    controller = LocalController(Config(tmp_path / "home"), runtime, store=store)
    assert store.fail_budget(run.id, "solve_wall_timeout", 3, 3, "expired")
    reference = capture_native_result(controller, binding)
    assert reference["outcome"] == "failed"
    assert reference["native"]["terminal_event"] == "budget_exceeded"
    assert reference["native"]["delivery"] is None


def test_successful_native_result_reopens_reciprocal_delivery_without_side_effects(tmp_path, monkeypatch):
    context, controller, parent, child, _result = _completed(tmp_path)
    monkeypatch.setattr("lunar_evolution.automatic_solve_bundle.validate_automatic_solve_bundle", lambda *_: None)
    controller.store.append_event(parent.id, "evolution_requested", _request())
    from lunar_evolution.bundle_parent_delivery import finish_bundle_parent_delivery
    finish_bundle_parent_delivery(controller, parent.id, child.id, context.contract, _result)
    runtime = controller.runtime
    binding, _ = _binding(
        controller.store, parent, child_id=child.id, contract_digest=context.contract.digest(), runtime=runtime,
        append_request=False,
    )
    before_events = controller.store.list_events(parent.id)
    before_artifacts = controller.store.list_artifacts(parent.id)
    before_files = {
        path.relative_to(parent.workspace).as_posix(): path.read_bytes()
        for path in parent.workspace.rglob("*") if path.is_file()
    }
    reference = capture_native_result(controller, binding)
    assert reference["outcome"] == "succeeded"
    assert reference["native"]["child_run_id"] == child.id
    assert reference["native"]["delivery"]["outputs_count"] == 1
    assert validate_native_result(controller, binding, reference) == reference
    assert controller.store.list_events(parent.id) == before_events
    assert controller.store.list_artifacts(parent.id) == before_artifacts
    assert {
        path.relative_to(parent.workspace).as_posix(): path.read_bytes()
        for path in parent.workspace.rglob("*") if path.is_file()
    } == before_files


def test_missing_success_evidence_fails_closed_before_result_reference(tmp_path, monkeypatch):
    context, controller, parent, child, _result = _completed(tmp_path)
    monkeypatch.setattr("lunar_evolution.automatic_solve_bundle.validate_automatic_solve_bundle", lambda *_: None)
    controller.store.append_event(parent.id, "evolution_requested", _request())
    runtime = controller.runtime
    binding, _ = _binding(
        controller.store, parent, child_id=child.id, contract_digest=context.contract.digest(), runtime=runtime,
        append_request=False,
    )
    from lunar_evolution.bundle_parent_delivery import finish_bundle_parent_delivery
    finish_bundle_parent_delivery(controller, parent.id, child.id, context.contract, _result)
    (Path(parent.workspace) / ".bundle-deliveries").rename(Path(parent.workspace) / ".bundle-deliveries.hidden")
    with pytest.raises(NativeResultReferenceError, match="automatic_solve_native_result_delivery"):
        capture_native_result(controller, binding)


def test_changed_runtime_or_cleanup_never_validates_old_reference(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    workspace = tmp_path / "run"
    workspace.mkdir()
    run = store.create_run("cancel", workspace)
    runtime = MockRuntime()
    binding, _ = _binding(store, run, runtime=runtime)
    controller = LocalController(Config(tmp_path / "home"), runtime, store=store)
    store.cancel_run(run.id)
    reference = capture_native_result(controller, binding)
    controller.runtime = SimpleNamespace(name="changed-runtime")
    with pytest.raises(NativeResultReferenceError, match="automatic_solve_native_result_runtime"):
        validate_native_result(controller, binding, reference)
