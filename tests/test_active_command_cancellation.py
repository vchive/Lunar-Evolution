"""Active command checks stop owned processes without changing boundary guards."""

from __future__ import annotations

import os
import signal
import sys
import time
from threading import Event, Thread, get_ident

import pytest

from lunar_evolution import candidate_execution_runner as runner
from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
)
from lunar_evolution.runtime import ModelTurn, ToolCall
from lunar_evolution.tools import LocalToolRegistry, ToolError, ToolResult


class ScriptedModel:
    name = "active-command-fixture"

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []
        self.cancel_threads = []

    def complete(self, messages, tools=(), timeout=None):
        self.requests.append(tuple(messages))
        assert self.turns, "unexpected additional model request"
        return self.turns.pop(0)

    def cancel(self):
        self.cancel_threads.append(get_ident())

    def process_info(self):
        return None, None

    def set_process_observer(self, observer):
        pass

    def set_process_released(self, released):
        pass


def command_call(identifier="command", command=None):
    return ToolCall(identifier, "run_command", {"command": command or ["fixture-command"]})


def active_failure(kind):
    if kind == "cancelled":
        return SolveExecutionCancelled("solve")
    if kind == "budget":
        return SolveExecutionBudgetExceeded("solve", started_at=1, deadline=2, observed_at=3)
    return {
        "runtime": RuntimeError,
        "tool": ToolError,
        "value": ValueError,
        "type": TypeError,
        "os": OSError,
    }[kind]("fixed active command failure")


def assert_process_released(observed, released):
    assert len(observed) == 1
    assert released == observed
    pid, pgid = observed[0]
    assert pgid == pid
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)


def test_runtime_wires_only_active_guard_into_command_polling(tmp_path, monkeypatch):
    polling = False
    boundary_calls = []
    active_calls = []

    def boundary_guard():
        assert not polling, "boundary guard was polled inside command execution"
        boundary_calls.append("boundary")

    def active_guard():
        assert polling, "active guard was called outside command execution"
        active_calls.append("active")

    def run(command, **kwargs):
        nonlocal polling
        polling = True
        try:
            guard = kwargs["continuation_guard"]
            assert callable(guard)
            for _ in range(3):
                guard()
        finally:
            polling = False
        return b"command complete", b"", "succeeded", 0, None

    monkeypatch.setattr(runner, "_bounded_process_bytes", run)
    model = ScriptedModel([ModelTurn("", (command_call(),)), ModelTurn("done")])
    runtime = AgentLoopRuntime(model, tools=LocalToolRegistry(allow_exec=True))
    runtime.set_continuation_guard(boundary_guard)
    runtime.set_active_continuation_guard(active_guard)

    assert runtime.run("run a command", tmp_path).text == "done"
    assert active_calls == ["active"] * 3
    assert boundary_calls
    assert len(model.requests) == 2


def test_active_guard_is_absent_from_model_and_noncommand_boundaries(tmp_path):
    model = ScriptedModel([
        ModelTurn("", (ToolCall("list", "list_dir", {}),)),
        ModelTurn("done"),
        ModelTurn("isolated"),
    ])
    runtime = AgentLoopRuntime(model)
    boundary_calls = []
    runtime.set_continuation_guard(lambda: boundary_calls.append("boundary"))
    runtime.set_active_continuation_guard(
        lambda: pytest.fail("active guard must only check commands"),
    )

    assert runtime.run("list files", tmp_path).text == "done"
    assert runtime.run_isolated("answer directly", tmp_path).text == "isolated"
    assert boundary_calls
    assert len(model.requests) == 3


def test_registry_active_guard_can_be_cleared_without_polling_boundary(tmp_path, monkeypatch):
    passed_guards = []
    active_calls = []

    def run(command, **kwargs):
        guard = kwargs.get("continuation_guard")
        passed_guards.append(guard)
        if guard is not None:
            guard()
        return b"ok", b"", "succeeded", 0, None

    monkeypatch.setattr(runner, "_bounded_process_bytes", run)
    tools = LocalToolRegistry(allow_exec=True)
    tools.set_continuation_guard(lambda: pytest.fail("boundary guard reached command runner"))
    tools.set_active_continuation_guard(lambda: active_calls.append("active"))
    assert tools.execute("run_command", {"command": ["fixture"]}, tmp_path).success

    tools.set_active_continuation_guard(None)
    assert tools.execute("run_command", {"command": ["fixture"]}, tmp_path).success
    assert active_calls == ["active"]
    assert callable(passed_guards[0])
    assert passed_guards[1] is None


@pytest.mark.parametrize("owner", ["registry", "runtime"])
def test_active_guard_rejects_noncallable_values(owner):
    target = (
        LocalToolRegistry()
        if owner == "registry" else AgentLoopRuntime(ScriptedModel([]))
    )
    with pytest.raises(TypeError, match="active continuation guard must be callable or None"):
        target.set_active_continuation_guard(object())


@pytest.mark.parametrize("owner", ["registry", "runtime"])
@pytest.mark.parametrize("kind", ["cancelled", "budget", "runtime", "tool", "value", "type", "os"])
def test_prelaunch_active_failure_preserves_identity_without_spawning(
    tmp_path, monkeypatch, owner, kind,
):
    failure = active_failure(kind)
    original_cause = LookupError("existing prelaunch guard cause")
    failure.__cause__ = original_cause
    guard_calls = []
    observed, released = [], []
    tools = LocalToolRegistry(allow_exec=True)
    model = ScriptedModel([ModelTurn("", (command_call(),))])
    target = tools if owner == "registry" else AgentLoopRuntime(model, tools=tools)
    target.set_process_observer(lambda pid, pgid: observed.append((pid, pgid)))
    target.set_process_released(lambda pid, pgid: released.append((pid, pgid)))

    def refuse():
        assert not guard_calls, "one-shot active failure was checked again"
        if owner == "runtime":
            assert len(model.requests) == 1
        guard_calls.append("refused")
        raise failure

    target.set_active_continuation_guard(refuse)
    monkeypatch.setattr(
        runner.subprocess, "Popen",
        lambda *_args, **_kwargs: pytest.fail("active refusal must prevent Popen"),
    )

    with pytest.raises(type(failure)) as caught:
        if owner == "registry":
            tools.execute("run_command", {"command": ["fixture"]}, tmp_path)
        else:
            target.run("run a command", tmp_path)

    assert caught.value is failure
    assert caught.value.__cause__ is original_cause
    assert guard_calls == ["refused"]
    assert observed == released == []
    if owner == "runtime":
        assert len(model.requests) == 1
        assert target.last_tool_steps == 1


@pytest.mark.parametrize("kind", ["cancelled", "budget", "runtime"])
def test_one_shot_active_failure_after_launch_cleans_before_propagating(tmp_path, kind):
    failure = active_failure(kind)
    original_cause = LookupError("existing active guard cause")
    failure.__cause__ = original_cause
    marker = tmp_path / "started"
    source = (
        'from pathlib import Path; import time; '
        'Path("started").write_text("started"); time.sleep(20)'
    )
    model = ScriptedModel([
        ModelTurn("", (command_call(command=[sys.executable, "-I", "-c", source]),)),
    ])
    runtime = AgentLoopRuntime(model, tools=LocalToolRegistry(allow_exec=True, command_timeout=5))
    observed, released = [], []
    raised = False
    runtime.set_process_observer(lambda pid, pgid: observed.append((pid, pgid)))
    runtime.set_process_released(lambda pid, pgid: released.append((pid, pgid)))

    def active_guard():
        nonlocal raised
        assert not raised, "one-shot failure was checked again during cleanup"
        if marker.exists():
            assert observed
            raised = True
            raise failure

    def boundary_guard():
        assert not observed or released == observed, "boundary guard polled a running command"

    runtime.set_continuation_guard(boundary_guard)
    runtime.set_active_continuation_guard(active_guard)
    started = time.monotonic()
    with pytest.raises(type(failure)) as caught:
        runtime.run("run until the active guard stops", tmp_path)

    assert caught.value is failure
    assert caught.value.__cause__ is original_cause
    assert raised
    assert time.monotonic() - started < 3
    assert_process_released(observed, released)
    assert len(model.requests) == 1
    assert runtime.last_tool_steps == 1


def test_runtime_cancel_from_another_thread_stops_command_and_later_work(tmp_path):
    source = "import time; time.sleep(20)"
    later_tool = ToolCall("later", "write_file", {"path": "later.txt", "content": "forbidden"})
    model = ScriptedModel([
        ModelTurn("", (
            command_call(command=[sys.executable, "-I", "-c", source]), later_tool,
        )),
        ModelTurn("unexpected final"),
    ])
    runtime = AgentLoopRuntime(model, tools=LocalToolRegistry(allow_exec=True, command_timeout=5))
    observed, released = [], []
    launched = Event()
    cancel_errors = []

    def observe(pid, pgid):
        observed.append((pid, pgid))
        launched.set()

    def cancel_after_launch():
        if not launched.wait(3):
            cancel_errors.append("command launch was not observed")
            return
        try:
            runtime.cancel()
        except Exception as exc:  # noqa: BLE001 - report cancellation errors in the test thread
            cancel_errors.append(exc)

    runtime.set_process_observer(observe)
    runtime.set_process_released(lambda pid, pgid: released.append((pid, pgid)))
    runtime.set_active_continuation_guard(lambda: pytest.fail("cleared external active guard"))
    runtime.set_active_continuation_guard(None)
    cancelling_thread = Thread(target=cancel_after_launch, name="cancel-active-command")
    started = time.monotonic()
    cancelling_thread.start()
    try:
        with pytest.raises(SolveExecutionCancelled):
            runtime.run("cancel the first command", tmp_path)
    finally:
        cancelling_thread.join(timeout=4)

    assert not cancelling_thread.is_alive()
    assert cancel_errors == []
    assert model.cancel_threads == [cancelling_thread.ident]
    assert cancelling_thread.ident != get_ident()
    assert time.monotonic() - started < 3
    assert_process_released(observed, released)
    assert not (tmp_path / "later.txt").exists()
    assert len(model.requests) == 1
    assert runtime.last_tool_steps == 1


@pytest.mark.parametrize("reuse_method", ["run", "run_isolated"])
def test_runtime_reuse_clears_cancel_event_and_external_hook(tmp_path, monkeypatch, reuse_method):
    turns = [ModelTurn("", (command_call(),))]
    if reuse_method == "run":
        turns.append(ModelTurn("", (command_call("second"),)))
    turns.append(ModelTurn("reused"))
    model = ScriptedModel(turns)
    runtime = AgentLoopRuntime(model, tools=LocalToolRegistry(allow_exec=True))
    command_calls = []

    def run(command, **kwargs):
        command_calls.append(command)
        guard = kwargs["continuation_guard"]
        assert callable(guard), "runtime's internal cancellation polling must remain installed"
        if len(command_calls) == 1:
            runtime.cancel()
        guard()
        return b"ok", b"", "succeeded", 0, None

    monkeypatch.setattr(runner, "_bounded_process_bytes", run)
    runtime.set_active_continuation_guard(
        lambda: pytest.fail("internal cancellation must precede the external hook"),
    )
    with pytest.raises(SolveExecutionCancelled):
        runtime.run("first invocation", tmp_path)

    runtime.set_active_continuation_guard(None)
    assert getattr(runtime, reuse_method)("next invocation", tmp_path).text == "reused"
    assert len(command_calls) == (2 if reuse_method == "run" else 1)
    assert len(model.cancel_threads) == 1


def test_short_natural_command_succeeds_without_guard_during_cleanup(tmp_path, monkeypatch):
    observed, released = [], []
    cleanup_groups = []
    active_calls = []
    original_kill_group = runner._kill_group

    def kill_group(process):
        cleanup_groups.append(process.pid)
        return original_kill_group(process)

    def guard():
        assert not cleanup_groups, "active guard was polled after bounded cleanup began"
        active_calls.append("active")

    monkeypatch.setattr(runner, "_kill_group", kill_group)
    tools = LocalToolRegistry(allow_exec=True, command_timeout=5)
    tools.set_process_observer(lambda pid, pgid: observed.append((pid, pgid)))
    tools.set_process_released(lambda pid, pgid: released.append((pid, pgid)))
    tools.set_active_continuation_guard(guard)

    result = tools.execute(
        "run_command", {"command": [sys.executable, "-I", "-c", 'print("natural success")']},
        tmp_path,
    )

    assert isinstance(result, ToolResult)
    assert result.success
    assert "exit_code=0" in result.output
    assert "natural success" in result.output
    assert active_calls
    assert_process_released(observed, released)
    assert cleanup_groups == [observed[0][1]]


@pytest.mark.parametrize("kind", ["runtime", "tool", "value", "type", "os"])
def test_ordinary_runner_errors_remain_unsuccessful_tool_results(tmp_path, monkeypatch, kind):
    failure = active_failure(kind)

    def run(command, **kwargs):
        kwargs["continuation_guard"]()
        raise failure

    monkeypatch.setattr(runner, "_bounded_process_bytes", run)
    tools = LocalToolRegistry(allow_exec=True)
    tools.set_active_continuation_guard(lambda: None)

    result = tools.execute("run_command", {"command": ["fixture"]}, tmp_path)

    assert isinstance(result, ToolResult)
    assert not result.success
    assert f"tool_error: {type(failure).__name__}:" in result.output


def test_nonzero_command_exit_remains_an_unsuccessful_tool_result(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner, "_bounded_process_bytes",
        lambda command, **kwargs: (
            b"ordinary output", b"ordinary error", "failed", 2, "process_failed",
        ),
    )
    tools = LocalToolRegistry(allow_exec=True)

    result = tools.execute("run_command", {"command": ["fixture"]}, tmp_path)

    assert isinstance(result, ToolResult)
    assert not result.success
    assert "exit_code=2" in result.output
    assert "ordinary output" in result.output
    assert "ordinary error" in result.output
    assert "error=process_failed" in result.output


@pytest.mark.parametrize("with_observer", [False, True], ids=["unobserved", "observed"])
def test_guard_failure_after_leader_exit_still_kills_exact_private_group(
    tmp_path, monkeypatch, with_observer,
):
    failure = RuntimeError("one-shot stop after leader exit")
    fake_pid = 42_424_242
    observed, released = [], []
    signals = []
    killed_processes = []
    group_alive = True
    guard_calls = 0
    stdout_read, stdout_write = os.pipe()
    stderr_read, stderr_write = os.pipe()

    class ExitedProcess:
        pid = fake_pid
        returncode = 0

        def __init__(self):
            self.stdout = os.fdopen(stdout_read, "rb")
            self.stderr = os.fdopen(stderr_read, "rb")

        def poll(self):
            return self.returncode

    class IdleSelector:
        def __init__(self):
            self.streams = {}
            self.closed = False

        def register(self, stream, events, data):
            self.streams[stream] = data

        def get_map(self):
            return self.streams

        def select(self, timeout):
            pytest.fail("one-shot guard should stop before selector polling")

        def close(self):
            self.closed = True

    process = ExitedProcess()
    selector = IdleSelector()

    def popen(command, **kwargs):
        assert kwargs["start_new_session"] is True
        assert kwargs["text"] is False
        return process

    def killpg(pgid, sig):
        nonlocal group_alive
        assert pgid == fake_pid
        signals.append((pgid, sig))
        if sig == signal.SIGKILL:
            group_alive = False
        elif sig == 0 and not group_alive:
            raise ProcessLookupError
        else:
            pytest.fail("unexpected group signal")

    original_kill_group = runner._kill_group

    def kill_group(target):
        assert target is process
        killed_processes.append(target)
        return original_kill_group(target)

    def guard():
        nonlocal guard_calls
        guard_calls += 1
        assert guard_calls <= 2, "guard was retried after the one-shot failure"
        if guard_calls == 2:
            assert process.poll() == 0
            assert group_alive
            assert len(selector.get_map()) == 2
            assert not process.stdout.closed and not process.stderr.closed
            raise failure

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(runner.os, "killpg", killpg)
    monkeypatch.setattr(runner, "_kill_group", kill_group)
    try:
        with pytest.raises(RuntimeError) as caught:
            runner._bounded_process_bytes(
                ["fixture"], cwd=str(tmp_path), environment={}, timeout=5,
                output_limit=1024, capture_limit=1024, continuation_guard=guard,
                process_observer=(
                    (lambda pid, pgid: observed.append((pid, pgid))) if with_observer else None
                ),
                process_released=lambda pid, pgid: released.append((pid, pgid)),
            )
    finally:
        os.close(stdout_write)
        os.close(stderr_write)
        process.stdout.close()
        process.stderr.close()

    assert caught.value is failure
    assert guard_calls == 2
    assert killed_processes == [process]
    assert signals == [(fake_pid, signal.SIGKILL)] + ([(fake_pid, 0)] if with_observer else [])
    assert not group_alive
    assert selector.closed
    assert process.stdout.closed and process.stderr.closed
    assert observed == ([(fake_pid, fake_pid)] if with_observer else [])
    assert released == [(fake_pid, fake_pid)]
