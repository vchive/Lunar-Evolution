"""Owned runtime and tool commands have independent groups and bounded cleanup."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
)
from lunar_evolution.runtime import MockRuntime, RuntimeExecutionError, SubprocessRuntime
from lunar_evolution.tools import LocalToolRegistry


@pytest.mark.parametrize("stop", ["guard", "cancel"])
def test_late_cancelled_model_response_cannot_write_or_request_again(tmp_path, stop):
    from test_agent_loop import FixtureModel

    from lunar_evolution.runtime import ModelTurn, ToolCall

    model = FixtureModel([
        ModelTurn("", (ToolCall("1", "write_file", {"path": "late.txt", "content": "late"}),)),
        ModelTurn("unexpected continuation"),
    ])
    runtime = AgentLoopRuntime(model)
    original = model.complete
    stopped = [False]

    def guard():
        if stopped[0]:
            raise SolveExecutionCancelled("candidate_generation")

    runtime.set_continuation_guard(guard)

    def complete(*args, **kwargs):
        turn = original(*args, **kwargs)
        if stop == "guard":
            stopped[0] = True
        else:
            runtime.cancel()
        return turn

    model.complete = complete
    with pytest.raises(SolveExecutionCancelled):
        runtime.run("fixture", tmp_path)
    assert len(model.requests) == 1
    assert not (tmp_path / "late.txt").exists()
    model.complete = original
    stopped[0] = False
    assert runtime.run("new invocation", tmp_path).text == "unexpected continuation"


@pytest.mark.parametrize("isolated", [True, False])
def test_late_final_response_discarded_after_cancellation(tmp_path, isolated):
    from test_agent_loop import FixtureModel

    from lunar_evolution.runtime import ModelTurn

    model = FixtureModel([ModelTurn("late final")])
    runtime = AgentLoopRuntime(model)
    original = model.complete

    def complete(*args, **kwargs):
        result = original(*args, **kwargs)
        runtime.cancel()
        return result

    model.complete = complete
    with pytest.raises(SolveExecutionCancelled):
        (runtime.run_isolated if isolated else runtime.run)("fixture", tmp_path)
    assert len(model.requests) == 1


@pytest.mark.parametrize("stop", ["guard", "cancel"])
def test_cancel_during_tool_blocks_remaining_tools_and_model_requests(tmp_path, stop):
    from test_agent_loop import FixtureModel

    from lunar_evolution.runtime import ModelTurn, ToolCall

    model = FixtureModel([ModelTurn("", tuple(
        ToolCall(str(index), "write_file", {"path": f"{index}.txt", "content": "fixture"})
        for index in (1, 2)
    )), ModelTurn("late")])
    runtime = AgentLoopRuntime(model)
    stopped = [False]

    def guard():
        if stopped[0]:
            raise SolveExecutionCancelled("candidate_generation")

    runtime.set_continuation_guard(guard)
    original = runtime.tools.execute

    def execute(*args, **kwargs):
        result = original(*args, **kwargs)
        if stop == "guard":
            stopped[0] = True
        else:
            runtime.cancel()
        return result

    runtime.tools.execute = execute
    with pytest.raises(SolveExecutionCancelled):
        runtime.run("fixture", tmp_path)
    assert (tmp_path / "1.txt").read_text() == "fixture"
    assert not (tmp_path / "2.txt").exists()
    assert len(model.requests) == 1


@pytest.mark.parametrize("isolated", [True, False])
def test_guard_budget_exception_preserved_before_request(tmp_path, isolated):
    from test_agent_loop import FixtureModel

    model = FixtureModel([])
    runtime = AgentLoopRuntime(model)
    error = SolveExecutionBudgetExceeded("preparation", started_at=0, deadline=1, observed_at=2)

    def guard():
        raise error

    runtime.set_continuation_guard(guard)
    with pytest.raises(SolveExecutionBudgetExceeded) as caught:
        (runtime.run_isolated if isolated else runtime.run)("fixture", tmp_path)
    assert caught.value is error
    assert model.requests == []


def _observe(target):
    events = []

    def observer(pid, pgid):
        assert pgid == pid == os.getpgid(pid)
        assert pgid != os.getpgrp()
        events.append(("started", pid, pgid))

    target.set_process_observer(observer)
    target.set_process_released(lambda pid, pgid: events.append(("released", pid, pgid)))
    return events


def _assert_released(events):
    assert len(events) == 2
    assert events[0][0] == "started"
    assert events[1] == ("released", *events[0][1:])
    with pytest.raises(ProcessLookupError):
        os.killpg(events[0][2], 0)


def test_subprocess_runtime_tracks_prompt_and_releases_success(tmp_path):
    runtime = SubprocessRuntime([sys.executable, "-c", "import sys; print(sys.stdin.read())"])
    events = _observe(runtime)
    assert runtime.run("fixture prompt", tmp_path, 3).text == "fixture prompt"
    _assert_released(events)
    assert runtime.process_info() == (None, None)


def test_subprocess_runtime_legacy_group_unchanged(tmp_path):
    runtime = SubprocessRuntime([sys.executable, "-c", "import os; print(os.getpgrp())"])
    assert int(runtime.run("fixture", tmp_path, 3).text) == os.getpgrp()


@pytest.mark.parametrize("stop", ["timeout", "cancel", "nonzero", "empty"])
def test_subprocess_runtime_releases_all_terminal_paths(tmp_path, stop):
    code = "import time; time.sleep(60)" if stop in {"timeout", "cancel"} else (
        "raise SystemExit(2)" if stop == "nonzero" else "pass"
    )
    runtime = SubprocessRuntime([sys.executable, "-c", code])
    events = _observe(runtime)
    registered = threading.Event()
    observer = runtime._process_observer

    def observe(pid, pgid):
        observer(pid, pgid)
        registered.set()

    runtime.set_process_observer(observe)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runtime.run, "fixture", tmp_path, 0.1 if stop == "timeout" else 3)
        assert registered.wait(2)
        if stop == "cancel":
            runtime.cancel()
        with pytest.raises(RuntimeExecutionError):
            future.result(timeout=4)
    _assert_released(events)


def test_cleanup_confirms_absent_group_while_another_thread_publishes_reaping(monkeypatch):
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True,
    )
    probe_started = threading.Event()
    reaped = threading.Event()
    publish_status = threading.Event()
    original_getpgid, original_killpg = os.getpgid, os.killpg
    original_status = process._handle_exitstatus
    signals = []

    def delayed_status(*args, **kwargs):
        # waitpid has removed the leader, but this thread still holds Popen's wait lock.
        reaped.set()
        assert publish_status.wait(5)
        return original_status(*args, **kwargs)

    def interleaved_getpgid(pid):
        if pid == process.pid:
            probe_started.set()
            assert reaped.wait(5)
        return original_getpgid(pid)

    def observe_signal(pgid, sig):
        signals.append(sig)
        return original_killpg(pgid, sig)

    monkeypatch.setattr(process, "_handle_exitstatus", delayed_status)
    monkeypatch.setattr(os, "getpgid", interleaved_getpgid)
    monkeypatch.setattr(os, "killpg", observe_signal)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            cleanup = executor.submit(SubprocessRuntime._cleanup_owned_process, process, process.pid)
            try:
                assert probe_started.wait(5)
                os.kill(process.pid, signal.SIGKILL)
                waiter = executor.submit(process.wait)
                assert reaped.wait(5)
                confirmed = cleanup.result(timeout=3)
                assert process.returncode is None
                with pytest.raises(ProcessLookupError):
                    original_killpg(process.pid, 0)
                assert confirmed
                assert signals and all(sig == 0 for sig in signals)
            finally:
                publish_status.set()
            waiter.result(timeout=3)
    finally:
        publish_status.set()
        if process.poll() is None:
            os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


@pytest.mark.parametrize("group_disappeared", [True, False])
def test_runtime_releases_reaped_leader_only_after_group_absence(tmp_path, monkeypatch, group_disappeared):
    # Deterministic OS observations at the same reaping/publication boundary. A leader's
    # disappearance alone does not authorize release of a group containing descendants.
    process = SimpleNamespace(
        pid=os.getpgrp() + 1, returncode=None, stdin=None, stdout=None, stderr=None,
        poll=lambda: None, communicate=lambda **kwargs: ("", ""),
    )
    signals = []

    def missing_leader(pid):
        assert pid == process.pid
        raise ProcessLookupError

    def observe_group(pgid, sig):
        assert pgid == process.pid
        signals.append(sig)
        assert sig == 0, "a missing leader must not grant new signal authority"
        if len(signals) > 1 and group_disappeared:
            raise ProcessLookupError

    monkeypatch.setattr("lunar_evolution.runtime.subprocess.Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(os, "getpgid", missing_leader)
    monkeypatch.setattr(os, "killpg", observe_group)
    runtime = SubprocessRuntime([sys.executable])
    events = []
    runtime.set_process_observer(lambda pid, pgid: events.append(("started", pid, pgid)))
    runtime.set_process_released(lambda pid, pgid: events.append(("released", pid, pgid)))
    with pytest.raises(RuntimeExecutionError):
        runtime.run("fixture", tmp_path, 3)
    assert events == [("started", process.pid, process.pid)] + (
        [("released", process.pid, process.pid)] if group_disappeared else []
    )
    assert signals and all(sig == 0 for sig in signals)


@pytest.mark.parametrize("resolution", ["absent", "denied", "live"])
def test_post_signal_probe_denial_preserves_bounded_cleanup(tmp_path, monkeypatch, resolution):
    ticks = 0
    polls = 0
    sent = []
    absence_observed = False
    process = SimpleNamespace(
        pid=os.getpgrp() + 1, returncode=None, stdin=None, stdout=None, stderr=None,
        communicate=lambda **kwargs: ("", ""),
    )

    def poll():
        nonlocal polls
        polls += 1
        if polls >= 2:
            process.returncode = -signal.SIGTERM
        return process.returncode

    def sleep(seconds):
        nonlocal ticks
        assert seconds == 0.01
        ticks += 1
        assert ticks <= 50, "a denied probe must never reset a cleanup deadline"

    def observe_group(pgid, sig):
        nonlocal absence_observed
        assert pgid == process.pid
        if sig:
            sent.append(sig)
            return
        if not sent:
            return
        if polls == 1 or resolution == "denied":
            raise PermissionError(1, "transient group probe denial")
        if resolution == "absent":
            assert process.returncode == -signal.SIGTERM
            absence_observed = True
            raise ProcessLookupError(3, "owned group absent")

    process.poll = poll
    monkeypatch.setattr("lunar_evolution.runtime.subprocess.Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr("lunar_evolution.runtime.monotonic", lambda: ticks / 100)
    monkeypatch.setattr("lunar_evolution.runtime.time.sleep", sleep)
    monkeypatch.setattr(os, "getpgid", lambda pid: process.pid)
    monkeypatch.setattr(os, "killpg", observe_group)
    runtime = SubprocessRuntime([sys.executable])
    events = []
    runtime.set_process_observer(lambda pid, pgid: events.append("started"))

    def release(pid, pgid):
        assert absence_observed, "a reaped leader or denied probe does not prove group absence"
        events.append("released")

    runtime.set_process_released(release)
    with pytest.raises(RuntimeExecutionError):
        runtime.run("fixture", tmp_path, 3)
    assert events == (["started", "released"] if resolution == "absent" else ["started"])
    assert ticks == {"absent": 1, "denied": 25, "live": 50}[resolution]
    assert sent == ([signal.SIGTERM, signal.SIGKILL] if resolution == "live" else [signal.SIGTERM])


@pytest.mark.parametrize("denied_at", ["initial_probe", "leader_identity", "term", "kill"])
def test_cleanup_permission_denial_never_grants_signal_authority(monkeypatch, denied_at):
    ticks = 0
    sent = []
    process = SimpleNamespace(pid=os.getpgrp() + 1, poll=lambda: None)

    def sleep(seconds):
        nonlocal ticks
        assert seconds == 0.01
        ticks += 1
        assert ticks <= 25

    def identity(pid):
        assert pid == process.pid
        if denied_at == "leader_identity":
            raise PermissionError(1, "leader identity unavailable")
        return process.pid

    def observe_group(pgid, sig):
        assert pgid == process.pid
        if not sig:
            if denied_at == "initial_probe":
                raise PermissionError(1, "group probe unavailable")
            return
        sent.append(sig)
        if (denied_at, sig) in {("term", signal.SIGTERM), ("kill", signal.SIGKILL)}:
            raise PermissionError(1, "signal denied")

    monkeypatch.setattr("lunar_evolution.runtime.monotonic", lambda: ticks / 100)
    monkeypatch.setattr("lunar_evolution.runtime.time.sleep", sleep)
    monkeypatch.setattr(os, "getpgid", identity)
    monkeypatch.setattr(os, "killpg", observe_group)
    assert not SubprocessRuntime._cleanup_owned_process(process, process.pid)
    assert ticks == (25 if denied_at == "kill" else 0)
    assert sent == {
        "initial_probe": [], "leader_identity": [],
        "term": [signal.SIGTERM], "kill": [signal.SIGTERM, signal.SIGKILL],
    }[denied_at]


@pytest.mark.parametrize("keep_pipes", [True, False])
def test_subprocess_runtime_cleans_descendants_after_leader_exit(tmp_path, keep_pipes):
    redirects = "" if keep_pipes else ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL"
    code = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']{redirects}); "
        "print('completed', flush=True)"
    )
    runtime = SubprocessRuntime([sys.executable, "-c", code])
    events = _observe(runtime)
    started = time.monotonic()
    assert runtime.run("fixture", tmp_path, 3).text == "completed"
    assert time.monotonic() - started < 2
    _assert_released(events)


def test_subprocess_runtime_start_failure_does_not_release(tmp_path):
    runtime = SubprocessRuntime([str(tmp_path / "missing")])
    events = _observe(runtime)
    with pytest.raises(RuntimeExecutionError):
        runtime.run("fixture", tmp_path, 3)
    assert events == []


def test_subprocess_runtime_cleanup_failure_retains_registration(tmp_path, monkeypatch):
    runtime = SubprocessRuntime([sys.executable, "-c", "print('done')"])
    events = _observe(runtime)
    monkeypatch.setattr(runtime, "_cleanup_owned_process", lambda *args: False)
    with pytest.raises(RuntimeExecutionError, match="cleanup"):
        runtime.run("fixture", tmp_path, 3)
    assert len(events) == 1


def test_subprocess_runtime_observer_errors_do_not_mask_result(tmp_path):
    runtime = SubprocessRuntime([sys.executable, "-c", "print('done')"])

    def broken(*args):
        raise RuntimeError("fixture callback")

    runtime.set_process_observer(broken)
    runtime.set_process_released(broken)
    assert runtime.run("fixture", tmp_path, 3).text == "done"


@pytest.mark.parametrize("stop", ["success", "timeout", "cancel", "nonzero"])
def test_tool_command_registers_and_releases_owned_process(tmp_path, stop):
    registry = LocalToolRegistry(allow_exec=True, command_timeout=0.1 if stop == "timeout" else 3)
    events = _observe(registry)
    if stop == "cancel":
        observer = registry._process_observer

        def cancel(pid, pgid):
            observer(pid, pgid)
            os.killpg(pgid, signal.SIGTERM)

        registry.set_process_observer(cancel)
    code = {"success": "print('done')", "timeout": "import time; time.sleep(60)",
            "cancel": "import time; time.sleep(60)", "nonzero": "raise SystemExit(2)"}[stop]
    result = registry.execute("run_command", {"command": [sys.executable, "-c", code]}, tmp_path)
    assert result.success is (stop == "success")
    _assert_released(events)


def test_tool_command_without_observer_uses_bounded_capture(tmp_path, monkeypatch):
    from lunar_evolution import candidate_execution_runner

    original = candidate_execution_runner._bounded_process_bytes
    captures = []

    def bounded(*args, **kwargs):
        captures.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", bounded)
    registry = LocalToolRegistry(allow_exec=True, command_timeout=3, max_output_bytes=512)
    result = registry.execute("run_command", {"command": [sys.executable, "-c", "print('done')"]}, tmp_path)
    assert result.success and result.output == "exit_code=0\nstdout:\ndone\n"
    assert len(captures) == 1
    assert captures[0]["process_observer"] is None
    assert captures[0]["process_released"] is None
    assert captures[0]["timeout"] == 3
    assert captures[0]["output_limit"] == captures[0]["capture_limit"] == 512


def test_tracked_tool_preserves_explicit_environment_and_shared_deadline(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNAR_PROCESS_FIXTURE", "ambient")
    registry = LocalToolRegistry(
        allow_exec=True, command_timeout=3, command_environment={"LUNAR_PROCESS_FIXTURE": "explicit"},
    )
    events = _observe(registry)
    result = registry.execute("run_command", {
        "command": [sys.executable, "-c", "import os; print(os.environ['LUNAR_PROCESS_FIXTURE'])"],
    }, tmp_path)
    assert result.success and "explicit" in result.output and "ambient" not in result.output
    _assert_released(events)
    events.clear()
    with registry.execution_deadline(time.monotonic() + 0.1):
        result = registry.execute("run_command", {
            "command": [sys.executable, "-c", "import time; time.sleep(60)"],
        }, tmp_path)
    assert not result.success and "timed out" in result.output
    assert registry.command_timeout == 3
    _assert_released(events)


@pytest.mark.parametrize("has_model_release", [True, False])
def test_agent_loop_forwards_process_hooks_to_model_and_tools(has_model_release):
    model = MockRuntime()
    model_observers, model_releases = [], []
    model.set_process_observer = model_observers.append
    if has_model_release:
        model.set_process_released = model_releases.append
    tools = LocalToolRegistry(allow_exec=True)
    runtime = AgentLoopRuntime(model, tools=tools)
    observer = lambda pid, pgid: None
    released = lambda pid, pgid: None
    runtime.set_process_observer(observer)
    runtime.set_process_released(released)
    assert model_observers == [observer]
    assert model_releases == ([released] if has_model_release else [])
    assert tools._process_observer is observer
    assert tools._process_released is released
    runtime.set_process_observer(None)
    runtime.set_process_released(None)
    assert tools._process_observer is tools._process_released is None
