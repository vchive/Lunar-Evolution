from __future__ import annotations

import threading
from pathlib import Path

import pytest

from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionCancelled
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.runtime import MockRuntime


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "observer-fixture", "problem_type": "routing",
        "statement": "Find a route.", "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "id"}}],
        "decision_variables": ["route"], "objective": {"name": "quality", "direction": "maximize"},
        "hard_constraints": [], "success_criteria": ["all items"], "deliverables": ["route"],
        "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
    })


def _fixture(tmp_path: Path, *, child: bool = False):
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    parent = controller.store.create_run("automatic parent", tmp_path / "parent")
    controller.store.append_event(parent.id, "evolution_requested", {
        "bundle_mode": "compiled", "automatic_lifecycle_version": 1,
    })
    child_run = None
    if child:
        child_run = controller.store.create_run("automatic child", tmp_path / "child")
        digest = _contract().digest()
        controller.store.append_event(parent.id, "evolution_linked", {
            "evolution_run_id": child_run.id, "contract_sha256": digest, "strategy": "population",
        })
        controller.store.append_event(child_run.id, "evolution_parent_linked", {
            "parent_run_id": parent.id, "contract_sha256": digest,
        })
        controller._algorithm_contract = lambda _run: _contract()  # type: ignore[method-assign]
    return controller, parent, child_run


def _attempt(controller, run):
    task = controller.store.list_tasks(run.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    assert attempt is not None
    return attempt


def test_worker_observation_fans_out_and_releases_native_after_outer_release(tmp_path):
    controller, parent, _ = _fixture(tmp_path)
    attempt = _attempt(controller, parent)
    observed, released = [], []
    with controller.automatic_worker_observation(
        parent.id,
        lambda *args: observed.append(args),
        lambda *args: released.append(args),
        lambda: None,
    ):
        observe, release = controller.attempt_process_observers(parent.id, attempt.id)
        observe(501, 601)
        assert controller.store.get_attempt(attempt.id).pid == 501
        release(501, 601)
        assert controller.store.get_attempt(attempt.id).pid is None
    assert observed == [(parent.id, attempt.id, 501, 601)]
    assert released == [(parent.id, attempt.id, 501, 601)]


def test_outer_release_failure_retains_native_registration(tmp_path):
    controller, parent, _ = _fixture(tmp_path)
    attempt = _attempt(controller, parent)
    with pytest.raises(SolveExecutionCancelled), controller.automatic_worker_observation(
        parent.id, lambda *_: None, lambda *_: (_ for _ in ()).throw(RuntimeError("worker down")), lambda: None,
    ):
        observe, release = controller.attempt_process_observers(parent.id, attempt.id)
        observe(501, 601)
        with pytest.raises(RuntimeError, match="worker down"):
            release(501, 601)
        retained = controller.store.get_attempt(attempt.id)
        assert (retained.pid, retained.pgid) == (501, 601)
    retained = controller.store.get_attempt(attempt.id)
    assert (retained.pid, retained.pgid) == (501, 601)


def test_nested_native_scope_restores_outer_worker_callbacks(tmp_path):
    controller, parent, _ = _fixture(tmp_path)
    outer_attempt = _attempt(controller, parent)
    child = controller.store.create_run("automatic child", tmp_path / "child")
    digest = _contract().digest()
    controller.store.append_event(parent.id, "evolution_linked", {
        "evolution_run_id": child.id, "contract_sha256": digest, "strategy": "population",
    })
    controller.store.append_event(child.id, "evolution_parent_linked", {
        "parent_run_id": parent.id, "contract_sha256": digest,
    })
    controller._algorithm_contract = lambda _run: _contract()  # type: ignore[method-assign]
    child_attempt = _attempt(controller, child)
    events = []
    with controller.automatic_worker_observation(
        parent.id, lambda *args: events.append(("outer-observe", args)),
        lambda *args: events.append(("outer-release", args)), lambda: None,
    ):
        outer_observe, outer_release = controller.attempt_process_observers(parent.id, outer_attempt.id)
        outer_observe(501, 601)
        with controller.observe_attempt_runtime(child.id, child_attempt.id, parent_id=parent.id) as (inner_observe, inner_release):
            inner_observe(502, 602)
            inner_release(502, 602)
        outer_release(501, 601)
    assert [name for name, _ in events] == ["outer-observe", "outer-observe", "outer-release", "outer-release"]
    assert controller.store.get_attempt(outer_attempt.id).pid is None
    assert controller.store.get_attempt(child_attempt.id).pid is None


def test_second_thread_cannot_replace_worker_observation_scope(tmp_path):
    controller, parent, _ = _fixture(tmp_path)
    entered = threading.Event()
    proceed = threading.Event()
    errors = []

    def owner():
        with controller.automatic_worker_observation(parent.id, lambda *_: None, lambda *_: None, lambda: None):
            entered.set()
            proceed.wait(timeout=5)

    thread = threading.Thread(target=owner)
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(RuntimeError, match="owned by another thread"), controller.automatic_worker_observation(
        parent.id, lambda *_: None, lambda *_: None, lambda: None,
    ):
        pass
    proceed.set()
    thread.join(timeout=5)
    assert not errors


def test_stale_callbacks_are_rejected_after_scope_exit(tmp_path):
    controller, parent, _ = _fixture(tmp_path)
    attempt = _attempt(controller, parent)
    with controller.automatic_worker_observation(parent.id, lambda *_: None, lambda *_: None, lambda: None):
        observe, release = controller.attempt_process_observers(parent.id, attempt.id)
    with pytest.raises(ValueError, match="no longer active"):
        observe(501, 601)
    with pytest.raises(ValueError, match="no longer active"):
        release(501, 601)


def test_registration_failure_cleans_exact_native_identity(tmp_path, monkeypatch):
    controller, parent, _ = _fixture(tmp_path)
    attempt = _attempt(controller, parent)
    cleaned = []

    def cleanup(registrations):
        cleaned.extend((item.pid, item.pgid) for item in registrations)
        controller.store.clear_attempt_process(attempt.id, 501, 601)
        return ()

    monkeypatch.setattr(controller, "_cleanup_process_registrations", cleanup)
    with pytest.raises(SolveExecutionCancelled), controller.automatic_worker_observation(
        parent.id, lambda *_: (_ for _ in ()).throw(RuntimeError("registration refused")),
        lambda *_: None, lambda: None,
    ):
        observe, _ = controller.attempt_process_observers(parent.id, attempt.id)
        with pytest.raises(RuntimeError, match="registration refused"):
            observe(501, 601)
    assert cleaned == [(501, 601)]
    assert controller.store.get_attempt(attempt.id).pid is None


def test_child_observation_requires_reciprocal_link(tmp_path):
    controller, parent, child = _fixture(tmp_path, child=True)
    attempt = _attempt(controller, child)
    with controller.automatic_worker_observation(parent.id, lambda *_: None, lambda *_: None, lambda: None):
        observe, release = controller.attempt_process_observers(child.id, attempt.id, parent_id=parent.id)
        observe(501, 601)
        release(501, 601)
    with controller.automatic_worker_observation(parent.id, lambda *_: None, lambda *_: None, lambda: None), pytest.raises(
        ValueError, match="child ownership",
    ):
        controller.attempt_process_observers(parent.id, attempt.id, parent_id=parent.id)


def test_guard_is_called_before_native_continuation(tmp_path):
    controller, parent, _ = _fixture(tmp_path)
    calls = []
    with controller.automatic_worker_observation(
        parent.id, lambda *_: None, lambda *_: None, lambda: calls.append("guard"),
    ):
        controller._automatic_worker_guard(parent.id)
    assert calls == ["guard"]
