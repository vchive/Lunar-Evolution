"""Invocation budgets must reach tools without becoming stale session state."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest

from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.model_profile import UsageLedger
from lunar_evolution.profiles import ModelProfile
from lunar_evolution.runtime import ModelTurn, RuntimeExecutionError, ToolCall
from lunar_evolution.tools import LocalToolRegistry
from lunar_evolution.transcript import SessionTranscript


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now


class Model:
    api_key = "PRIVATE-KEY-NEVER-IN-BUDGET"

    def __init__(self, turns, clock=None):
        self.turns = iter(turns)
        self.clock = clock
        self.requests = []

    def complete(self, messages, tools=(), timeout=None):
        self.requests.append(deepcopy(messages))
        if self.clock:
            self.clock.now += 1
        return next(self.turns)


def sample(total):
    return {"input_tokens": total - 1, "output_tokens": 1, "total_tokens": total}


def snapshot(messages):
    system = next(message["content"] for message in messages if message["role"] == "system")
    assert system.count("<lunar_runtime_budget>") == 1
    return json.loads(system.split("<lunar_runtime_budget>\n")[1].split("\n</")[0])


def test_profile_snapshot_tracks_time_steps_spend_and_does_not_persist(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr("lunar_evolution.agent_loop.time.monotonic", clock.monotonic)
    transcript = SessionTranscript(tmp_path / "transcript.jsonl")
    profile = ModelProfile(
        "bounded", "fixture", timeout_seconds=10, max_steps=5, max_total_tokens=50,
        max_cost_micros=100, input_cost_per_1k_micros=1000,
        output_cost_per_1k_micros=1000,
    )
    calls = tuple(ToolCall(str(i), "list_dir", {}) for i in range(2))
    model = Model([
        ModelTurn("", calls, usage=sample(7)), ModelTurn("done", usage=sample(3)),
        ModelTurn("new run", usage=sample(2)), ModelTurn("isolated", usage=sample(2)),
    ], clock)
    runtime = AgentLoopRuntime(model, profile=profile, transcript=transcript)
    runtime.run("solve", tmp_path / "work")
    first, second = map(snapshot, model.requests[:2])
    assert first == {
        "schema_version": "1", "remaining_seconds": 10.0, "tool_steps_remaining": 5,
        "command_timeout_seconds": None, "tokens_remaining": 50, "cost_micros_remaining": 100,
    }
    assert second == first | {
        "remaining_seconds": 9.0, "tool_steps_remaining": 3,
        "tokens_remaining": 43, "cost_micros_remaining": 93,
    }
    assert [message["role"] for message in model.requests[1]][-3:] == [
        "assistant", "tool", "tool",
    ]
    assert "lunar_runtime_budget" not in transcript.path.read_text()
    assert model.api_key not in str(model.requests)
    runtime.run("again", tmp_path / "work")
    assert snapshot(model.requests[2]) == first
    runtime.run_isolated("protocol", tmp_path / "work")
    assert "lunar_runtime_budget" not in str(model.requests[3])
    assert len(model.requests[3]) == 2


def test_snapshot_has_null_spend_without_ceilings_and_unprofiled_steps_time(
    tmp_path, monkeypatch,
):
    clock = Clock()
    monkeypatch.setattr("lunar_evolution.agent_loop.time.monotonic", clock.monotonic)
    tools = LocalToolRegistry(allow_exec=True, command_timeout=3)
    transcript = SessionTranscript(tmp_path / "transcript.jsonl")
    model = Model([
        ModelTurn("", (ToolCall("1", "list_dir", {}),)),
        ModelTurn("done"),
    ], clock)
    AgentLoopRuntime(model, tools=tools, max_steps=3, transcript=transcript).run(
        "solve", tmp_path / "finite", timeout=10, tool_steps_offset=1,
    )

    first, second = map(snapshot, model.requests)
    assert first == {
        "schema_version": "1", "remaining_seconds": 10.0,
        "tool_steps_remaining": 2, "command_timeout_seconds": 3,
        "tokens_remaining": None, "cost_micros_remaining": None,
    }
    assert second == first | {"remaining_seconds": 9.0, "tool_steps_remaining": 1}

    # Each provider request receives one fresh envelope; snapshots are not accumulated.
    for request in model.requests:
        system = next(message["content"] for message in request if message["role"] == "system")
        assert system.count("<lunar_runtime_budget>") == 1
    assert "lunar_runtime_budget" not in transcript.path.read_text()

    legacy = Model([ModelTurn("done")])
    AgentLoopRuntime(legacy, tools=tools).run("legacy", tmp_path / "unbounded")
    unbounded = snapshot(legacy.requests[0])
    assert unbounded["remaining_seconds"] is None
    assert unbounded["tool_steps_remaining"] == 40
    assert unbounded["command_timeout_seconds"] is None
    assert unbounded["tokens_remaining"] is None
    assert unbounded["cost_micros_remaining"] is None


def test_explicit_ledger_carries_usage_across_staged_invocations(tmp_path):
    profile = ModelProfile("staged", "fixture", max_total_tokens=20)
    model = Model([ModelTurn("first", usage=sample(7)), ModelTurn("second", usage=sample(5))])
    runtime = AgentLoopRuntime(model, profile=profile)
    ledger = UsageLedger(profile)

    first = runtime.run("build", tmp_path, usage_ledger=ledger)
    second = runtime.run("resume", tmp_path, usage_ledger=ledger)

    assert first.text == "first" and second.text == "second"
    assert ledger.snapshot.total_tokens == 12
    assert snapshot(model.requests[1])["tokens_remaining"] == 13

    other = ModelProfile("other", "fixture", max_total_tokens=20)
    with pytest.raises(ValueError, match="does not match"):
        runtime.run("wrong", tmp_path, usage_ledger=UsageLedger(other))


def test_profile_commands_recompute_deadline_without_mutating_registry(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr("lunar_evolution.agent_loop.time.monotonic", clock.monotonic)
    observed = []

    def run(command, **kwargs):
        observed.append(kwargs["timeout"])
        clock.now += 2
        return b"ok", b"", "succeeded", 0, None

    monkeypatch.setattr("lunar_evolution.candidate_execution_runner._bounded_process_bytes", run)
    tools = LocalToolRegistry(allow_exec=True, command_timeout=30)
    calls = tuple(ToolCall(str(i), "run_command", {"command": ["fixture"]}) for i in range(2))
    model = Model([ModelTurn("", calls), ModelTurn("done")], clock)
    runtime = AgentLoopRuntime(model, tools=tools, profile=ModelProfile("p", "fixture", timeout_seconds=10))
    runtime.run("run commands", tmp_path)
    assert observed == [9.0, 7.0]
    assert snapshot(model.requests[0])["command_timeout_seconds"] == 10
    assert snapshot(model.requests[1])["command_timeout_seconds"] == 5
    assert tools.command_timeout == 30
    tools.execute("run_command", {"command": ["fixture"]}, tmp_path)
    assert observed[-1] == 30


def test_expired_profile_does_not_spawn_later_command_or_accept_final(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr("lunar_evolution.agent_loop.time.monotonic", clock.monotonic)
    spawned = []

    def run(command, **kwargs):
        spawned.append(kwargs["timeout"])
        clock.now = 10
        return b"saved", b"", "timed_out", None, "process_timed_out"

    monkeypatch.setattr("lunar_evolution.candidate_execution_runner._bounded_process_bytes", run)
    calls = tuple(ToolCall(str(i), "run_command", {"command": ["fixture"]}) for i in range(2))
    tools = LocalToolRegistry(allow_exec=True)
    model = Model([ModelTurn("", calls), ModelTurn("forbidden success")], clock)
    runtime = AgentLoopRuntime(model, tools=tools, profile=ModelProfile("p", "fixture", timeout_seconds=10))
    with pytest.raises(RuntimeExecutionError, match="timed out"):
        runtime.run("run", tmp_path)
    assert spawned == [9.0]
    assert len(model.requests) == 1
    assert tools.command_timeout == 30


def test_deadline_scope_rejects_expired_and_restores_nested_exception(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr("lunar_evolution.tools.time.monotonic", clock.monotonic)
    observed = []

    def run(command, **kwargs):
        observed.append(kwargs["timeout"])
        return b"", b"", "succeeded", 0, None

    monkeypatch.setattr("lunar_evolution.candidate_execution_runner._bounded_process_bytes", run)
    tools = LocalToolRegistry(allow_exec=True, command_timeout=3)
    with tools.execution_deadline(2):
        with pytest.raises(RuntimeError), tools.execution_deadline(5):
            tools.execute("run_command", {"command": ["fixture"]}, tmp_path)
            raise RuntimeError("exit inner")
        tools.execute("run_command", {"command": ["fixture"]}, tmp_path)
        clock.now = 2
        result = tools.execute("run_command", {"command": ["fixture"]}, tmp_path)
        assert not result.success
    tools.execute("run_command", {"command": ["fixture"]}, tmp_path)
    assert observed == [2, 2, 3]


def test_deadlines_are_context_local_for_shared_registry(tmp_path, monkeypatch):
    monkeypatch.setattr("lunar_evolution.tools.time.monotonic", lambda: 0)
    barrier = Barrier(2)

    def run(command, **kwargs):
        return str(kwargs["timeout"]).encode(), b"", "succeeded", 0, None

    monkeypatch.setattr("lunar_evolution.candidate_execution_runner._bounded_process_bytes", run)
    tools = LocalToolRegistry(allow_exec=True)

    def invoke(limit):
        with tools.execution_deadline(limit):
            barrier.wait(timeout=2)
            return tools.execute("run_command", {"command": ["fixture"]}, tmp_path).output

    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(invoke, (2, 7)))
    assert "stdout:\n2" in outputs[0] and "stdout:\n7" in outputs[1]


@pytest.mark.parametrize("stdout,stderr", [
    (b"checkpoint-ready", None), (None, b"checkpoint-ready"),
    (b"check", b"point-ready"), (b"checkpoint", b"-ready"), (None, None),
])
def test_command_timeout_preserves_available_streams(tmp_path, monkeypatch, stdout, stderr):
    def run(command, **kwargs):
        return stdout or b"", stderr or b"", "timed_out", None, "process_timed_out"

    monkeypatch.setattr("lunar_evolution.candidate_execution_runner._bounded_process_bytes", run)
    result = LocalToolRegistry(allow_exec=True).execute("run_command", {"command": ["fixture"]}, tmp_path)
    assert not result.success
    assert result.output.startswith("command timed out")
    if stdout or stderr:
        assert "checkpoint-ready" in result.output


def test_real_timeout_keeps_saved_candidate_and_partial_output(tmp_path: Path):
    result = LocalToolRegistry(allow_exec=True, command_timeout=0.5).execute(
        "run_command", {"command": [sys.executable, "-u", "-c",
            ("from pathlib import Path; import time; "
            "Path('candidate.json').write_text('{}'); "
            "print('checkpoint-ready', flush=True); time.sleep(5)")]}, tmp_path,
    )
    assert not result.success
    assert "command timed out" in result.output and "checkpoint-ready" in result.output
    assert (tmp_path / "candidate.json").read_text() == "{}"
