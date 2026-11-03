"""Active command checks must not run controller stage-cleanup callbacks."""
from __future__ import annotations

import os
import sys
import threading
from types import SimpleNamespace

import pytest

from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.agents import AgentRegistry, AgentResult, RuntimeAgentAdapter
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.models import WorkerOutcome
from lunar_evolution.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from lunar_evolution.runtime import MockRuntime, ModelTurn, ToolCall
from lunar_evolution.store import Store
from lunar_evolution.tools import LocalToolRegistry
from lunar_evolution.workers import WorkerService


class _GuardRuntime(MockRuntime):
    def __init__(self):
        self.guard = None
        self.active_guard = None
        self.observer = None
        self.released = None

    def set_continuation_guard(self, guard):
        self.guard = guard

    def set_active_continuation_guard(self, guard):
        self.active_guard = guard

    def set_process_observer(self, observer):
        self.observer = observer

    def set_process_released(self, released):
        self.released = released


def _attempt(tmp_path, runtime=None):
    runtime = _GuardRuntime() if runtime is None else runtime
    controller = LocalController(Config(tmp_path / "home"), runtime)
    run = controller.create("check local command ownership")
    task = controller.store.list_tasks(run.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    assert attempt is not None
    return controller, runtime, run, attempt


def _assert_cleared(runtime):
    assert runtime.guard is runtime.active_guard is None
    assert runtime.observer is runtime.released is None


def test_controller_active_polling_keeps_current_process_and_boundary_cleans_stale(
    tmp_path, monkeypatch,
):
    controller, runtime, run, attempt = _attempt(tmp_path)
    cleaned = []

    def cleanup(registrations):
        return tuple(
            cleaned.append((item.pid, item.pgid)) or ProcessCleanupResult(
                item.label, item.pid, item.pgid, ProcessCleanupStatus.CLEANED,
            ) for item in registrations
        )

    monkeypatch.setattr("lunar_evolution.controller.cleanup_registered_processes", cleanup)
    with controller.observe_attempt_runtime(run.id, attempt.id):
        controller.store.set_attempt_process(attempt.id, 12345, 12345)
        assert runtime.guard is not runtime.active_guard
        for _ in range(3):
            runtime.active_guard()
        assert cleaned == []
        assert controller.store.get_attempt(attempt.id).pid == 12345
        runtime.guard()
        assert cleaned == [(12345, 12345)]
        assert controller.store.get_attempt(attempt.id).pid is None
    _assert_cleared(runtime)


def test_controller_boundary_still_blocks_unconfirmed_stale_cleanup(tmp_path, monkeypatch):
    controller, runtime, run, attempt = _attempt(tmp_path)
    monkeypatch.setattr(controller, "_cleanup_process_registrations", lambda _items: None)
    with controller.observe_attempt_runtime(run.id, attempt.id):
        controller.store.set_attempt_process(attempt.id, 12345, 12345)
        runtime.active_guard()
        with pytest.raises(SolveExecutionCancelled) as caught:
            runtime.guard()
        assert caught.value.stage == "process_cleanup"
        assert controller.store.get_attempt(attempt.id).pid == 12345
    _assert_cleared(runtime)


@pytest.mark.parametrize("target", ["run", "parent"])
def test_controller_active_guard_observes_stop_without_process_cleanup(
    tmp_path, monkeypatch, target,
):
    controller, runtime, run, attempt = _attempt(tmp_path)
    parent = controller.create("parent cancellation authority")
    monkeypatch.setattr(
        controller, "ensure_attempt_process_released",
        lambda *_args, **_kwargs: pytest.fail("active polling invoked stage cleanup"),
    )
    with controller.observe_attempt_runtime(run.id, attempt.id, parent_id=parent.id):
        runtime.active_guard()
        controller.store.cancel_run(run.id if target == "run" else parent.id)
        with pytest.raises(SolveExecutionCancelled) as caught:
            runtime.active_guard()
        assert caught.value.stage == "runtime"
    _assert_cleared(runtime)


def test_controller_context_clears_both_hooks_after_body_failure(tmp_path):
    controller, runtime, run, attempt = _attempt(tmp_path)
    failure = RuntimeError("inert body failure")
    with pytest.raises(RuntimeError) as caught, controller.observe_attempt_runtime(run.id, attempt.id):
        raise failure
    assert caught.value is failure
    _assert_cleared(runtime)
    assert attempt.id not in controller._active_runtimes


def test_controller_keeps_legacy_runtime_without_active_hook(tmp_path):
    controller, runtime, run, attempt = _attempt(tmp_path, MockRuntime())
    with controller.observe_attempt_runtime(run.id, attempt.id):
        assert controller._active_runtimes[attempt.id] is runtime
    assert attempt.id not in controller._active_runtimes


class _CommandFixtureModel(MockRuntime):
    def __init__(self):
        self.requests = []
        self.turns = [
            ModelTurn("", (ToolCall("command-1", "run_command", {
                "command": [sys.executable, "-I", "-c",
                            "import time; time.sleep(0.1); print('active-command-ready')"],
            }),)),
            ModelTurn("owned command completed"),
        ]

    def complete(self, messages, tools=(), timeout=None):
        self.requests.append((messages, tools, timeout))
        return self.turns.pop(0)


def test_controller_agent_loop_runs_one_owned_command_without_active_cleanup(
    tmp_path, monkeypatch,
):
    model = _CommandFixtureModel()
    runtime = AgentLoopRuntime(
        model, tools=LocalToolRegistry(allow_exec=True, command_timeout=3), max_steps=2,
    )
    controller, _, run, attempt = _attempt(tmp_path, runtime)
    registrations, releases, active_polls, cleanups = [], [], [], []
    register = controller.store.set_attempt_process
    release = controller.store.clear_attempt_process
    cleanup = controller._cleanup_process_registrations
    install_active = runtime.set_active_continuation_guard

    def record_register(attempt_id, pid, pgid):
        result = register(attempt_id, pid, pgid)
        current = controller.store.get_attempt(attempt_id)
        registrations.append((attempt_id, current.pid, current.pgid))
        return result

    def record_release(*args, **kwargs):
        result = release(*args, **kwargs)
        releases.append(args)
        return result

    def record_cleanup(registrations):
        cleanups.extend((item.pid, item.pgid) for item in registrations)
        return cleanup(registrations)

    def record_active(guard):
        if guard is None:
            install_active(None)
            return

        def poll():
            current = controller.store.get_attempt(attempt.id)
            if current.pid is not None:
                active_polls.append((current.pid, current.pgid))
            guard()

        install_active(poll)

    monkeypatch.setattr(controller.store, "set_attempt_process", record_register)
    monkeypatch.setattr(controller.store, "clear_attempt_process", record_release)
    monkeypatch.setattr(controller, "_cleanup_process_registrations", record_cleanup)
    monkeypatch.setattr(runtime, "set_active_continuation_guard", record_active)
    with controller.observe_attempt_runtime(run.id, attempt.id):
        result = runtime.run("run one local fixture command", tmp_path / "work", timeout=3)

    assert result.text == "owned command completed"
    assert len(model.requests) == 2 and runtime.last_tool_steps == 1
    assert len(registrations) == 1
    registered_attempt, pid, pgid = registrations[0]
    assert registered_attempt == attempt.id and pid == pgid
    assert releases == [(attempt.id, pid, pgid)]
    assert active_polls and set(active_polls) == {(pid, pgid)}
    assert cleanups == []
    assert controller.store.get_attempt(attempt.id).pid is None
    tool_messages = [item for item in model.requests[1][0] if item.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["content"] == "exit_code=0\nstdout:\nactive-command-ready\n"
    assert runtime._active_continuation_guard is runtime._continuation_guard is None
    assert attempt.id not in controller._active_runtimes
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)


def _compiler_setup(tmp_path, monkeypatch, compile_body):
    runtime = _GuardRuntime()
    controller = LocalController(Config(tmp_path / "home"), runtime)
    run = controller.create_conversational_run("compile a local fixture")
    monkeypatch.setattr(
        controller, "_automatic_cancel_targets", lambda _run_id: SimpleNamespace(verified=True),
    )
    compiler = SimpleNamespace(runtime=runtime, compile=compile_body)
    return controller, runtime, run, compiler


def test_compiler_active_checks_do_not_clean_registered_current_process(tmp_path, monkeypatch):
    checks = []

    def compile_body(*_args, **_kwargs):
        task = controller.store.list_tasks(run.id)[0]
        attempt = controller.store.active_attempt(task.id)
        controller.store.set_attempt_process(attempt.id, 12345, 12345)
        runtime.active_guard()
        runtime.active_guard()
        checks.append(("after-active", len(cleanups), controller.store.get_attempt(attempt.id).pid))
        runtime.guard()
        checks.append(("after-boundary", len(cleanups)))
        # The implicit invalid result finishes intake without generating or running a plan.

    controller, runtime, run, compiler = _compiler_setup(tmp_path, monkeypatch, compile_body)
    cleanups = []
    monkeypatch.setattr(
        controller, "ensure_attempt_process_released", lambda *args, **kwargs: cleanups.append(args),
    )
    settled = controller._compile_conversational_run(run, compiler, None, execute_plan=False)
    assert settled.status.value == "failed"
    assert checks == [("after-active", 0, 12345), ("after-boundary", 1)]
    assert len(cleanups) == 2  # The existing post-compile boundary is retained too.
    _assert_cleared(runtime)


@pytest.mark.parametrize("stop", ["run", "budget"])
def test_compiler_active_stop_preserves_control_failure_and_clears_hooks(
    tmp_path, monkeypatch, stop,
):
    now = [100.0]
    control = SolveExecutionControl(10, clock=lambda: now[0])

    def compile_body(*_args, **_kwargs):
        runtime.active_guard()
        if stop == "run":
            controller.store.cancel_run(run.id)
        else:
            now[0] = 110.0
        runtime.active_guard()
        pytest.fail("stopped compiler continued")

    controller, runtime, run, compiler = _compiler_setup(tmp_path, monkeypatch, compile_body)
    monkeypatch.setattr(
        controller, "ensure_attempt_process_released",
        lambda *_args, **_kwargs: pytest.fail("active stop invoked stage cleanup"),
    )
    expected = SolveExecutionCancelled if stop == "run" else SolveExecutionBudgetExceeded
    with pytest.raises(expected) as caught:
        controller._compile_conversational_run(
            run, compiler, None, execute_plan=False, solve_control=control,
        )
    assert caught.value.stage == "contract"
    _assert_cleared(runtime)


def test_runtime_adapter_forwards_active_hook_without_replacing_boundary_guard():
    runtime = _GuardRuntime()
    adapter = RuntimeAgentAdapter(runtime)
    boundary = lambda: None
    active = lambda: None
    adapter.set_continuation_guard(boundary)
    adapter.set_active_continuation_guard(active)
    assert runtime.guard is boundary and runtime.active_guard is active
    adapter.set_active_continuation_guard(None)
    assert runtime.guard is boundary and runtime.active_guard is None
    # Optional hook stays compatible with runtimes implementing only the original API.
    RuntimeAgentAdapter(MockRuntime()).set_active_continuation_guard(active)
    RuntimeAgentAdapter(MockRuntime()).set_active_continuation_guard(None)


@pytest.mark.parametrize("guard", [False, 1, "not-callable", object()])
def test_runtime_adapter_invalid_active_hook_cannot_replace_current_guard(guard):
    runtime = _GuardRuntime()
    adapter = RuntimeAgentAdapter(runtime)
    active = lambda: None
    adapter.set_active_continuation_guard(active)
    with pytest.raises(TypeError, match="active continuation guard must be callable or None"):
        adapter.set_active_continuation_guard(guard)
    assert runtime.active_guard is active


class _WorkerAdapter:
    name = "active-guard-fixture"
    roles = frozenset({"worker"})
    capabilities = frozenset()

    def __init__(self, ready, proceed, observations, *, fail=False):
        self.ready, self.proceed, self.observations = ready, proceed, observations
        self.fail = fail
        self.guard = self.active_guard = None
        self.hooks_cleared = threading.Event()

    def set_continuation_guard(self, guard):
        self.guard = guard

    def set_active_continuation_guard(self, guard):
        self.active_guard = guard
        if guard is None:
            self.hooks_cleared.set()

    def set_process_observer(self, observer):
        self.observer = observer

    def set_process_released(self, released):
        self.released = released

    def process_info(self):
        return None, None

    def cancel(self):
        self.proceed.set()

    def run(self, request):
        self.observations.append(("guards", self.guard is self.active_guard, callable(self.active_guard)))
        self.active_guard()
        self.ready.set()
        if not self.proceed.wait(5):
            raise RuntimeError("test did not release worker")
        self.active_guard()
        if self.fail:
            raise RuntimeError("inert worker fixture error")
        return AgentResult(self.name, request.role, "local fixture complete")


@pytest.mark.parametrize("stop", ["success", "cancel", "error"])
def test_worker_service_installs_live_guard_and_clears_both_hooks(tmp_path, stop):
    store = Store(tmp_path / "state.db")
    store.initialize()
    ready, proceed = threading.Event(), threading.Event()
    observations, instances = [], []

    def factory():
        adapter = _WorkerAdapter(ready, proceed, observations, fail=stop == "error")
        instances.append(adapter)
        return adapter

    registry = AgentRegistry()
    registry.register(
        _WorkerAdapter(ready, proceed, observations), execution_factory=factory,
    )
    service = WorkerService(store, registry, tmp_path / "sessions")
    try:
        worker = service.dispatch("owner", prompt="poll local state", role="worker")
        assert ready.wait(5)
        if stop == "cancel":
            service.cancel("owner", worker.id)
        else:
            proceed.set()
        settled = service.wait("owner", worker.id, timeout=5)
        assert settled.outcome is {
            "success": WorkerOutcome.SUCCESS, "cancel": WorkerOutcome.STOPPED,
            "error": WorkerOutcome.FAILURE,
        }[stop]
        assert observations == [("guards", True, True)]
        assert instances[0].hooks_cleared.wait(5)
        assert instances[0].guard is instances[0].active_guard is None
        assert instances[0].observer is instances[0].released is None
    finally:
        proceed.set()
        service.close()
