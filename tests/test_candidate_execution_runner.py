from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from lunar_evolution import (
    CANDIDATE_INPUT_ROOT_ENV,
    CandidateEvaluatorPin,
    CandidateExecutionBudget,
    CandidateExecutionInput,
    CandidateSourceBundle,
    CandidateSourceFile,
    build_candidate_execution_admission,
    build_candidate_workspace_plan,
    run_candidate_execution,
)
from lunar_evolution.candidate_execution_runner import CandidateExecutionRunnerError


def _setup(tmp_path: Path, script: bytes = b"#!/bin/sh\ncat \"$LUNAR_CANDIDATE_INPUT_ROOT/in.txt\"\n"):
    root = tmp_path.resolve()
    workspace, inputs = root / "workspace", root / "inputs"
    workspace.mkdir(parents=True); inputs.mkdir()
    (workspace / "run.sh").write_bytes(script)
    (inputs / "in.txt").write_bytes(b"hello")
    digest = hashlib.sha256(script).hexdigest()
    bundle = CandidateSourceBundle("a" * 64, "run.sh", (CandidateSourceFile("run.sh", len(script), digest),))
    plan = build_candidate_workspace_plan(bundle, command=(str(Path("/bin/sh").resolve(strict=True)),), contract_sha256="a" * 64, timeout_seconds=2, max_output_bytes=1024)
    item = CandidateExecutionInput("in.txt", "fixture", 5, hashlib.sha256(b"hello").hexdigest())
    budget = CandidateExecutionBudget(2, 1024, 1024, 1)
    admission = build_candidate_execution_admission(
        plan, inputs=[item], dependency_sha256="b" * 64, environment_sha256="c" * 64,
        evaluator=CandidateEvaluatorPin("source-only", "d" * 64), budget=budget,
    )
    return admission, plan, workspace, inputs


def test_runs_multifile_workspace_and_input_namespace(tmp_path: Path):
    admission, plan, workspace, inputs = _setup(tmp_path)
    result = run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=inputs)
    assert result.execution.status == "succeeded"
    assert result.execution.stdout == "hello"
    assert result.entrypoint == "run.sh"
    assert CANDIDATE_INPUT_ROOT_ENV == "LUNAR_CANDIDATE_INPUT_ROOT"
    assert not (workspace / "execution.json").exists()
    assert "stdout" not in result.to_dict()["execution"]


def test_relative_workspace_and_input_paths_are_supported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    admission, plan, workspace, inputs = _setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = run_candidate_execution(
        admission, plan=plan, workspace_path=workspace.name, input_path=inputs.name,
    )
    assert result.execution.status == "succeeded"
    assert result.execution.stdout == "hello"


def test_plan_pin_rejected_before_process(tmp_path: Path):
    admission, plan, workspace, inputs = _setup(tmp_path)
    with pytest.raises(CandidateExecutionRunnerError) as error:
        run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=inputs, expected_plan_sha256="0" * 64)
    assert error.value.code.endswith("plan_mismatch")


def test_nonzero_and_timeout_are_bounded(tmp_path: Path):
    admission, plan, workspace, inputs = _setup(tmp_path, b"#!/bin/sh\nexit 7\n")
    result = run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=inputs)
    assert result.execution.status == "failed"
    assert result.execution.error == "process_failed"

    admission, plan, workspace, inputs = _setup(tmp_path / "timeout", b"#!/bin/sh\nsleep 1\n")
    short_plan = build_candidate_workspace_plan(plan.bundle, command=plan.command, contract_sha256="a" * 64, timeout_seconds=0.1, max_output_bytes=1024)
    short_admission = build_candidate_execution_admission(
        short_plan, inputs=admission.inputs, dependency_sha256="b" * 64, environment_sha256="c" * 64,
        evaluator=admission.evaluator, budget=CandidateExecutionBudget(0.1, 1024, 1024, 1),
    )
    started = time.monotonic(); result = run_candidate_execution(short_admission, plan=short_plan, workspace_path=workspace, input_path=inputs)
    assert time.monotonic() - started < 1
    assert result.execution.status == "timed_out"


def test_output_overflow_is_detected_without_unbounded_capture(tmp_path: Path):
    admission, plan, workspace, inputs = _setup(tmp_path, b"#!/bin/sh\nprintf '%2048s' ''\n")
    result = run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=inputs)
    assert result.execution.status == "failed"
    assert result.execution.error == "output_limit_exceeded"
    assert result.execution.stdout_bytes <= plan.max_output_bytes


def test_timeout_does_not_wait_for_background_descendant_pipe(tmp_path: Path):
    admission, plan, workspace, inputs = _setup(tmp_path, b"#!/bin/sh\nsleep 5 &\nwait\n")
    short_plan = build_candidate_workspace_plan(
        plan.bundle, command=plan.command, contract_sha256="a" * 64,
        timeout_seconds=0.1, max_output_bytes=1024,
    )
    short_admission = build_candidate_execution_admission(
        short_plan, inputs=admission.inputs, dependency_sha256="b" * 64,
        environment_sha256="c" * 64, evaluator=admission.evaluator,
        budget=CandidateExecutionBudget(0.1, 1024, 1024, 1),
    )
    started = time.monotonic()
    result = run_candidate_execution(
        short_admission, plan=short_plan, workspace_path=workspace, input_path=inputs,
    )
    assert time.monotonic() - started < 1
    assert result.execution.status == "timed_out"


def test_small_timeout_is_not_increased_above_admission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import lunar_evolution.candidate_execution_runner as runner

    admission, plan, workspace, inputs = _setup(tmp_path, b"#!/bin/sh\nsleep 1\n")
    short_plan = build_candidate_workspace_plan(
        plan.bundle, command=plan.command, contract_sha256="a" * 64,
        timeout_seconds=0.005, max_output_bytes=1024,
    )
    short_admission = build_candidate_execution_admission(
        short_plan, inputs=admission.inputs, dependency_sha256="b" * 64,
        environment_sha256="c" * 64, evaluator=admission.evaluator,
        budget=CandidateExecutionBudget(0.005, 1024, 1024, 1),
    )
    process_runner = runner._bounded_process
    timeouts: list[float] = []

    def observe(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return process_runner(*args, **kwargs)

    monkeypatch.setattr(runner, "_bounded_process", observe)
    result = run_candidate_execution(short_admission, plan=short_plan, workspace_path=workspace, input_path=inputs)
    assert timeouts == [short_admission.budget.timeout_seconds]
    assert result.execution.status == "timed_out", (
        result.execution.status, result.execution.error, result.execution.exit_code,
    )
