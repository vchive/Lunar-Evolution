"""Provider-free WSI-02 typed continuation and shared solve control tests."""
from __future__ import annotations

import hashlib
from argparse import Namespace
from dataclasses import replace
from types import SimpleNamespace

import pytest

from lunar_evolution import automatic_solve_continuation as continuation_module
from lunar_evolution import cli
from lunar_evolution.automatic_solve_continuation import (
    AutomaticSolveContinuation,
    continue_automatic_solve,
)
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.evolution import EvolutionError


class Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _controller(run, request, runtime, *, pending_input=None):
    events = []

    class Store:
        def get_run(self, run_id):
            return run if run_id == run.id else None

        def list_events(self, _run_id):
            return [{"type": "evolution_requested", "payload": request}]

        def pending_input(self, _run_id):
            return pending_input

    return SimpleNamespace(store=Store(), runtime=runtime, events=events)


def _request():
    return {"automatic_lifecycle_version": 1, "bundle_mode": "compiled", "strategy": "population",
            "timeout": 3, "compile_evaluator": True, "evaluator_command_configured": False,
            "openevolve_command_configured": False}


def test_binder_preserves_supplied_control_and_composes_parent_across_clocks():
    parent_clock, child_clock = Clock(500.0), Clock(100.0)
    parent = SolveExecutionControl(10, clock=parent_clock)
    child = SolveExecutionControl(30, clock=child_clock)
    run = SimpleNamespace(id="run-1", status=SimpleNamespace(value="running"))
    controller = SimpleNamespace(store=SimpleNamespace(get_run=lambda _id: run))
    args = Namespace(_solve_execution_control=child, multi_file=True, solve_wall_timeout=20)
    seen = []
    cli._bind_solve_execution_control(args, controller, run, observe_stage=seen.append,
                                      parent_control=parent)
    assert args._solve_execution_control is child
    assert child.deadline == 110.0
    assert child.check("candidate_generation") == 10.0
    assert seen == ["contract", "candidate_generation"]
    parent_clock.value = 506.0
    with pytest.raises(SolveExecutionCancelled):
        parent.cancel()
        child.check("delivery")


def test_binder_rejects_expired_parent_before_narrowing_child():
    parent_clock = Clock(100.0)
    parent = SolveExecutionControl(5, clock=parent_clock)
    parent_clock.value = 105.0
    child = SolveExecutionControl(30, clock=Clock(10.0))
    run = SimpleNamespace(id="run-2", status=SimpleNamespace(value="running"))
    controller = SimpleNamespace(store=SimpleNamespace(get_run=lambda _id: run))
    args = Namespace(_solve_execution_control=child, multi_file=True, solve_wall_timeout=20)
    with pytest.raises(SolveExecutionBudgetExceeded):
        cli._bind_solve_execution_control(args, controller, run, parent_control=parent)
    assert child.deadline == 30.0


def test_parent_tightening_is_observed_during_child_poll():
    parent_clock, child_clock = Clock(0.0), Clock(100.0)
    parent = SolveExecutionControl(20, clock=parent_clock)
    child = SolveExecutionControl(60, clock=child_clock)
    child.add_parent_control(parent)
    assert child.remaining() == 20.0
    parent_clock.value = 5.0
    assert child.remaining() == 15.0


def test_parent_cycle_is_rejected():
    first = SolveExecutionControl(10, clock=Clock(0.0))
    second = SolveExecutionControl(10, clock=Clock(0.0))
    first.add_parent_control(second)
    with pytest.raises(ValueError, match="parent cycle"):
        second.add_parent_control(first)


def test_continuation_capture_and_verify_pin_request_runtime_and_manifest(monkeypatch, tmp_path):
    request = _request()
    run = SimpleNamespace(id="run-3", workspace=tmp_path)
    runtime = SimpleNamespace(name="fixture-runtime")
    controller = _controller(run, request, runtime)
    manifest = {"plan_kind": "role_dag", "schema_version": "1"}
    monkeypatch.setattr(cli, "_conversation_manifest", lambda _run: manifest)
    monkeypatch.setattr(cli, "_compiler_fingerprint", lambda _runtime: "a" * 64)
    continuation = AutomaticSolveContinuation.capture(controller, run)
    continuation.verify(controller, run)
    assert continuation.run_id == run.id
    assert continuation.request_sha256
    monkeypatch.setattr(cli, "_compiler_fingerprint", lambda _runtime: "b" * 64)
    with pytest.raises(ValueError, match="runtime changed"):
        continuation.verify(controller, run)


def test_typed_dispatch_reuses_existing_cli_orchestration(monkeypatch, tmp_path):
    request = _request()
    run = SimpleNamespace(id="run-4", workspace=tmp_path, status=SimpleNamespace(value="running"))
    controller = _controller(run, request, SimpleNamespace(name="fixture"))
    monkeypatch.setattr(cli, "_conversation_manifest", lambda _run: None)
    monkeypatch.setattr(cli, "_compiler_fingerprint", lambda _runtime: "c" * 64)
    continuation = AutomaticSolveContinuation.capture(controller, run)
    control = SolveExecutionControl(10, clock=Clock(20.0))
    observed = {}

    def existing(config, args, supplied_controller, supplied_run, manifest=None):
        observed.update({"controller": supplied_controller, "run": supplied_run,
                         "control": args._solve_execution_control, "owner": args._automatic_owner})
        return {"status": "awaiting_input"}

    monkeypatch.setattr(cli, "_continue_automatic_solve", existing)
    result = continue_automatic_solve(
        object(), controller, continuation, execution_control=control,
    )
    assert result == {"status": "awaiting_input"}
    assert observed["controller"] is controller
    assert observed["run"] is run
    assert observed["control"] is control
    assert observed["owner"].parent_id == run.id


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled", "awaiting_input"])
@pytest.mark.parametrize("control_state", ["expired", "cancelled"])
def test_read_only_continuation_returns_before_lock_or_control_admission(
    monkeypatch, tmp_path, status, control_state,
):
    run = SimpleNamespace(id="read-only", workspace=tmp_path, status=SimpleNamespace(value=status))
    pending = {"question": "Choose a candidate"} if status == "awaiting_input" else None
    controller = _controller(run, _request(), SimpleNamespace(), pending_input=pending)
    monkeypatch.setattr(cli, "_conversation_manifest", lambda _run: None)
    monkeypatch.setattr(cli, "_compiler_fingerprint", lambda _runtime: "c" * 64)
    continuation = AutomaticSolveContinuation.capture(controller, run)
    clock = Clock(0.0)
    control = SolveExecutionControl(1, clock=clock)
    if control_state == "expired":
        clock.value = 1.0
    else:
        control.cancel()
    monkeypatch.setattr(control, "check", lambda *_: pytest.fail("control admission"))
    monkeypatch.setattr(continuation_module, "own_automatic_solve", lambda *_: pytest.fail("lock acquisition"))
    monkeypatch.setattr(cli, "_continue_automatic_solve", lambda *_: pytest.fail("continuation execution"))
    monkeypatch.setattr(cli, "_solve_payload", lambda supplied, current: {
        "run_id": current.id, "status": current.status.value,
    })

    result = continue_automatic_solve(
        object(), controller, continuation,
        execution_control=control, parent_control=control, owner=object(),
    )

    assert result == {"run_id": run.id, "status": status}
    assert not (tmp_path / ".automatic-solve.lock").exists()


@pytest.mark.parametrize("changes", [
    {"compile_evaluator": False},
    {"compile_evaluator": 1},
    {"evaluator_command_configured": True},
    {"openevolve_command_configured": True},
    {"bundle_profile_sha256": "d" * 64},
    {"strategy": "openevolve"},
    {"timeout": False},
    {"evaluator_preparation_wall_timeout": 1},
    {"solve_wall_timeout": 1, "solve_wall_timeout_source": "default"},
])
def test_invalid_persisted_request_is_rejected_before_owner_or_control_admission(
    monkeypatch, tmp_path, changes,
):
    request = {**_request(), **changes}
    run = SimpleNamespace(id="invalid-policy", workspace=tmp_path, status=SimpleNamespace(value="running"))
    controller = _controller(run, request, SimpleNamespace())
    monkeypatch.setattr(cli, "_conversation_manifest", lambda _run: None)
    monkeypatch.setattr(cli, "_compiler_fingerprint", lambda _runtime: "c" * 64)
    continuation = AutomaticSolveContinuation.capture(controller, run)
    control = SolveExecutionControl(1, clock=Clock(0.0))
    monkeypatch.setattr(control, "check", lambda *_: pytest.fail("control admission"))
    monkeypatch.setattr(continuation_module, "own_automatic_solve", lambda *_: pytest.fail("lock acquisition"))
    monkeypatch.setattr(cli, "_continue_automatic_solve", lambda *_: pytest.fail("continuation execution"))

    with pytest.raises(EvolutionError):
        continue_automatic_solve(object(), controller, continuation, execution_control=control, owner=object())

    assert not (tmp_path / ".automatic-solve.lock").exists()


def test_mutated_request_is_rejected_before_owner_or_control_admission(monkeypatch, tmp_path):
    request = _request()
    run = SimpleNamespace(id="changed-policy", workspace=tmp_path, status=SimpleNamespace(value="running"))
    controller = _controller(run, request, SimpleNamespace())
    monkeypatch.setattr(cli, "_conversation_manifest", lambda _run: None)
    monkeypatch.setattr(cli, "_compiler_fingerprint", lambda _runtime: "c" * 64)
    continuation = AutomaticSolveContinuation.capture(controller, run)
    request["compile_evaluator"] = False
    control = SolveExecutionControl(1, clock=Clock(0.0))
    monkeypatch.setattr(control, "check", lambda *_: pytest.fail("control admission"))
    monkeypatch.setattr(continuation_module, "own_automatic_solve", lambda *_: pytest.fail("lock acquisition"))

    with pytest.raises(ValueError, match="request changed"):
        continue_automatic_solve(object(), controller, continuation, execution_control=control, owner=object())


def test_continuation_rejects_boolean_lifecycle_marker_and_duplicate_json(monkeypatch, tmp_path):
    request = _request()
    run = SimpleNamespace(id="invalid-shape", workspace=tmp_path)
    controller = _controller(run, request, SimpleNamespace())
    monkeypatch.setattr(cli, "_conversation_manifest", lambda _run: None)
    monkeypatch.setattr(cli, "_compiler_fingerprint", lambda _runtime: "c" * 64)
    continuation = AutomaticSolveContinuation.capture(controller, run)
    malformed = {**request, "automatic_lifecycle_version": True}
    content = canonical_json(malformed)
    with pytest.raises(ValueError, match="not lifecycle-enabled"):
        replace(continuation, request_json=content.decode(), request_sha256=hashlib.sha256(content).hexdigest())
    request["automatic_lifecycle_version"] = True
    with pytest.raises(ValueError, match="not lifecycle-enabled"):
        AutomaticSolveContinuation.capture(controller, run)
    duplicate_json = continuation.request_json[:-1] + ',"automatic_lifecycle_version":1}'
    with pytest.raises(ValueError):
        replace(continuation, request_json=duplicate_json)
