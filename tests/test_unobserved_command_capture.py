"""Ordinary command tools must bound capture before a process exits."""

import sys
import time

import pytest

from lunar_evolution.tools import LocalToolRegistry


def invoke(tmp_path, source, *, limit=512, timeout=3):
    return LocalToolRegistry(
        allow_exec=True, command_timeout=timeout, max_output_bytes=limit,
    ).execute("run_command", {"command": [sys.executable, "-u", "-c", source]}, tmp_path)


@pytest.mark.parametrize("returncode", [0, 7])
def test_unobserved_real_process_preserves_small_output_and_status(tmp_path, returncode):
    result = invoke(tmp_path, (
        "import os; print('ordinary-stdout'); os.write(2, b'ordinary-stderr'); "
        f"raise SystemExit({returncode})"
    ))
    assert result.success is (returncode == 0)
    assert result.output.startswith(f"exit_code={returncode}\nstdout:\nordinary-stdout\n")
    assert "stderr:\nordinary-stderr" in result.output
    assert ("error=process_failed" in result.output) is (returncode != 0)


@pytest.mark.parametrize("fd", [1, 2])
def test_unobserved_real_flood_uses_bounded_byte_capture(tmp_path, monkeypatch, fd):
    from lunar_evolution import candidate_execution_runner

    captures = []
    original = candidate_execution_runner._bounded_process_bytes

    def observe(*args, **kwargs):
        assert kwargs["process_observer"] is None
        assert kwargs["capture_limit"] == kwargs["output_limit"] == 512
        result = original(*args, **kwargs)
        captures.append(result)
        return result

    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", observe)
    result = invoke(tmp_path, f"import os; os.write({fd}, b'x' * (8 * 1024 * 1024))")
    assert not result.success and "error=output_limit_exceeded" in result.output
    assert len(captures) == 1
    stdout, stderr, status, _, error = captures[0]
    assert status == "failed" and error == "output_limit_exceeded"
    assert len(stdout) <= 512 and len(stderr) <= 512
    assert len((stdout, stderr)[fd - 1]) == 512
    assert len(result.output.encode()) < 2 * 512 + 128


def test_unobserved_output_limit_is_bytes_even_for_multibyte_text(tmp_path):
    # Two codepoints would fit a five-character truncator, but occupy eight bytes.
    result = invoke(tmp_path, "import os; os.write(1, '\U0001f600\U0001f600'.encode())", limit=5)
    assert not result.success and "error=output_limit_exceeded" in result.output


def test_unobserved_exact_byte_limit_can_complete(tmp_path):
    result = invoke(tmp_path, "import os; os.write(1, b'x' * 512); os.write(2, b'y' * 512)")
    assert result.success
    assert result.output == "exit_code=0\nstdout:\n" + "x" * 512 + "\nstderr:\n" + "y" * 512


@pytest.mark.parametrize("fd", [1, 2])
def test_unobserved_timeout_keeps_partial_stream_and_candidate(tmp_path, fd):
    result = invoke(tmp_path, (
        "from pathlib import Path; import os, time; Path('candidate.json').write_text('{}'); "
        f"os.write({fd}, b'checkpoint-ready'); time.sleep(5)"
    ), timeout=0.5)
    assert not result.success
    assert result.output.startswith("command timed out after 0.5s\n")
    assert "checkpoint-ready" in result.output
    assert (tmp_path / "candidate.json").read_text() == "{}"


def test_unobserved_parent_exit_does_not_wait_for_inherited_pipe_until_child_finishes(tmp_path):
    started = time.monotonic()
    result = invoke(tmp_path, (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)']); "
        "print('parent-finished', flush=True)"
    ), timeout=3)
    assert time.monotonic() - started < 4.5
    assert "parent-finished" in result.output
    # This checks bounded return, not independently observed descendant ownership.


def test_unobserved_command_keeps_explicit_environment_argv_and_no_shell(tmp_path):
    result = LocalToolRegistry(
        allow_exec=True, command_environment={"TASK_SENTINEL": "only-this-value"},
    ).execute("run_command", {"command": [sys.executable, "-c", (
        "import json, os, sys; print(json.dumps([os.environ['TASK_SENTINEL'], sys.argv[1:]]))"
    ), "literal;$(not-a-shell)", "two words"]}, tmp_path)
    assert result.success
    assert '["only-this-value", ["literal;$(not-a-shell)", "two words"]]' in result.output
    assert not (tmp_path / "not-a-shell").exists()


def test_command_schema_exposes_stream_limit_with_or_without_observer():
    registry = LocalToolRegistry(allow_exec=True, max_output_bytes=512)
    first = registry.schemas()
    registry.set_process_observer(lambda *_: None)
    assert registry.schemas() == first
    command = next(item for item in first if item["function"]["name"] == "run_command")
    description = command["function"]["parameters"]["properties"]["command"]["description"]
    assert "512 bytes in either output stream" in description
    assert len(description.encode()) <= 512
