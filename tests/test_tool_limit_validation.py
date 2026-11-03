"""Reject unbounded tool limits before dispatch and preserve valid command limits."""
from __future__ import annotations

from pathlib import Path

import pytest

from lunar_evolution import candidate_execution_runner
from lunar_evolution.tools import LocalToolRegistry


def _forbid_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("invalid registry limits must not dispatch a command")

    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", forbidden)
    monkeypatch.setattr(candidate_execution_runner.subprocess, "Popen", forbidden)


@pytest.mark.parametrize(
    "timeout",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(10 ** 1000, id="integer-float-overflow"),
        pytest.param(True, id="true"),
        pytest.param(False, id="false"),
        pytest.param(0, id="zero-int"),
        pytest.param(0.0, id="zero-float"),
        pytest.param(-1, id="negative-int"),
        pytest.param(-0.5, id="negative-float"),
        pytest.param("1", id="string"),
        pytest.param(None, id="none"),
        pytest.param([], id="list"),
    ],
)
def test_invalid_timeout_refuses_before_command_dispatch(monkeypatch, timeout):
    _forbid_dispatch(monkeypatch)

    with pytest.raises(ValueError, match="command_timeout must be finite and positive"):
        LocalToolRegistry(allow_exec=True, command_timeout=timeout)


@pytest.mark.parametrize(
    "limit",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(1.0, id="integer-valued-float"),
        pytest.param(1.5, id="fractional-float"),
        pytest.param(True, id="true"),
        pytest.param(False, id="false"),
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param("1", id="string"),
        pytest.param(None, id="none"),
        pytest.param([], id="list"),
    ],
)
def test_invalid_output_limit_refuses_before_command_dispatch(monkeypatch, limit):
    _forbid_dispatch(monkeypatch)

    with pytest.raises(ValueError, match="max_output_bytes must be a positive integer"):
        LocalToolRegistry(allow_exec=True, max_output_bytes=limit)


@pytest.mark.parametrize(
    "options,timeout,limit",
    [
        pytest.param({}, 30.0, 20_000, id="defaults"),
        pytest.param({"command_timeout": 2, "max_output_bytes": 1}, 2, 1, id="integers"),
        pytest.param(
            {"command_timeout": 0.125, "max_output_bytes": 7}, 0.125, 7, id="fractional-timeout",
        ),
        pytest.param(
            {"command_timeout": 10 ** 300, "max_output_bytes": 10 ** 300},
            10 ** 300, 10 ** 300, id="large-finite-no-new-cap",
        ),
    ],
)
def test_valid_limits_reach_original_command_seam_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, options, timeout, limit,
):
    calls = []
    environment = {"PATH": "/fixture-bin", "FIXTURE": "registered"}

    def observe(command, **kwargs):
        calls.append((command, kwargs))
        return b"", b"", "succeeded", 0, None

    def forbidden(*args, **kwargs):
        pytest.fail("valid-limit check must use only the fake process seam")

    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", observe)
    monkeypatch.setattr(candidate_execution_runner.subprocess, "Popen", forbidden)
    registry = LocalToolRegistry(allow_exec=True, command_environment=environment, **options)
    result = registry.execute("run_command", {"command": ["fixture", "--literal"]}, tmp_path)

    assert result.success and result.output == "exit_code=0\nstdout:\n"
    assert registry.command_timeout == timeout and type(registry.command_timeout) is type(timeout)
    assert registry.max_output_bytes == limit and type(registry.max_output_bytes) is int
    assert len(calls) == 1
    command, actual = calls[0]
    assert command == ["fixture", "--literal"]
    assert actual["cwd"] == str(tmp_path)
    assert actual["environment"] == environment
    assert actual["timeout"] == timeout and type(actual["timeout"]) is type(timeout)
    assert actual["output_limit"] == actual["capture_limit"] == limit


@pytest.mark.parametrize("timeout,expected", [(2, 1.5), (0.125, 0.125)])
def test_finite_deadline_still_narrows_only_current_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timeout, expected,
):
    observed = []

    def observe(command, **kwargs):
        observed.append(kwargs)
        return b"", b"", "succeeded", 0, None

    def forbidden(*args, **kwargs):
        pytest.fail("deadline check must not create a real process")

    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", observe)
    monkeypatch.setattr(candidate_execution_runner.subprocess, "Popen", forbidden)
    monkeypatch.setattr("lunar_evolution.tools.time.monotonic", lambda: 10.0)
    registry = LocalToolRegistry(allow_exec=True, command_timeout=timeout, max_output_bytes=7)
    with registry.execution_deadline(11.5):
        assert registry.execute("run_command", {"command": ["fixture"]}, tmp_path).success
    assert registry.execute("run_command", {"command": ["fixture"]}, tmp_path).success

    assert [call["timeout"] for call in observed] == [expected, timeout]
    assert all(call["output_limit"] == call["capture_limit"] == 7 for call in observed)
    assert registry.command_timeout == timeout
