"""Real local subprocess cancellation with retained interruption/cleanup evidence."""

from __future__ import annotations

import hashlib
import json
import os
import time
from threading import Timer

import pytest
from test_candidate_evaluation import fixture as evaluation_fixture
from test_candidate_execution_evidence import fixture as candidate_fixture
from test_producer_bundle_transaction_control import _batch, _call, _fixture, _prefix

from lunar_evolution import candidate_execution_runner as runner
from lunar_evolution import producer_bundle_transaction
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.candidate_evaluation import evaluate_candidate_execution
from lunar_evolution.candidate_execution_evidence import (
    inspect_candidate_execution_record,
    run_candidate_execution_recorded,
)
from lunar_evolution.candidate_process_interruption import (
    CandidateProcessInterrupted,
    build_process_interruption_receipt,
)


def _absent(pid):
    try:
        os.killpg(pid, 0)
        return False
    except ProcessLookupError:
        return True


@pytest.mark.parametrize("reason", ["cancel", "deadline"])
def test_candidate_stop_during_execution_keeps_uncertain_bound_evidence(tmp_path, reason):
    admission, request = candidate_fixture(tmp_path, b"sleep 30 &\nwait\n")
    # Existing fixture plan is short: stop before its own timeout so the shared control owns it.
    control = SolveExecutionControl(0.06 if reason == "deadline" else 30)
    observed, released, timers = [], [], []
    def observe(pid, pgid):
        observed.append(pid)
        if reason == "cancel":
            timer = Timer(0.03, control.cancel)
            timers.append(timer)
            timer.start()
    expected = SolveExecutionBudgetExceeded if reason == "deadline" else SolveExecutionCancelled
    started = time.monotonic()
    with pytest.raises(expected):
        run_candidate_execution_recorded(
            admission, **request, remaining_timeout=control.check,
            process_observer=observe, process_released=lambda pid, _pgid: released.append(pid),
        )
    for timer in timers:
        timer.join()
    assert time.monotonic() - started < 1.5
    assert len(observed) == 1
    assert _absent(observed[0])
    receipt = json.loads((request["attempt_path"] / "interrupted.json").read_bytes())
    assert receipt["reason"] == ("cancelled" if reason == "cancel" else "timed_out")
    assert receipt["stage"] == "candidate_execution"
    assert receipt["request_sha256"] == hashlib.sha256((request["attempt_path"] / "launch-intent.json").read_bytes()).hexdigest()
    assert not (request["attempt_path"] / "completed.json").exists()
    assert not (request["attempt_path"] / "result.json").exists()
    assert inspect_candidate_execution_record(request["attempt_path"], plan=request["plan"], admission=admission).status == "uncertain"


@pytest.mark.parametrize("reason", ["cancel", "deadline"])
def test_evaluator_stop_retains_frozen_request_and_no_score(tmp_path, reason):
    admission, request = evaluation_fixture(tmp_path, harness=b"import time\ntime.sleep(30)\n")
    control = SolveExecutionControl(0.08 if reason == "deadline" else 30)
    observed, timers = [], []
    def observe(pid, _pgid):
        observed.append(pid)
        if reason == "cancel":
            timer = Timer(0.03, control.cancel)
            timers.append(timer)
            timer.start()
    expected = SolveExecutionBudgetExceeded if reason == "deadline" else SolveExecutionCancelled
    started = time.monotonic()
    with pytest.raises(expected):
        evaluate_candidate_execution(
            admission, **request, remaining_timeout=control.check,
            process_observer=observe, process_released=lambda _pid, _pgid: None,
        )
    for timer in timers:
        timer.join()
    assert time.monotonic() - started < 1.5
    assert len(observed) == 1 and _absent(observed[0])
    trees = list(request["evaluation_root"].iterdir())
    assert len(trees) == 1
    receipt = json.loads((trees[0] / "interrupted.json").read_bytes())
    assert receipt["request_sha256"] == hashlib.sha256((trees[0] / "request.json").read_bytes()).hexdigest()
    assert receipt["reason"] == ("cancelled" if reason == "cancel" else "timed_out")
    assert receipt["cleanup"] == "verified"
    assert not (trees[0] / "evaluation.json").exists()
    assert not (trees[0] / "report.json").exists()


def test_cleanup_uncertainty_cannot_be_labeled_verified(tmp_path, monkeypatch):
    control = SolveExecutionControl(30)
    monkeypatch.setattr(runner, "_wait_owned_group_exit", lambda *_args: False)
    with pytest.raises(CandidateProcessInterrupted) as caught:
        runner._bounded_process_bytes(
            ["/bin/sh", "-c", "sleep 30"], cwd=str(tmp_path), environment={},
            timeout=20, output_limit=1024, capture_limit=1024,
            continuation=lambda: control.check("candidate_execution"),
            process_observer=lambda *_args: control.cancel(),
            process_released=lambda *_args: None,
        )
    assert caught.value.observation["cleanup"] == "unknown"
    assert caught.value.observation["ownership_release"] == "not_observed"


def test_failed_control_callback_kills_owned_work_and_keeps_fixed_reason(tmp_path):
    def failed():
        raise ValueError("private control detail")
    with pytest.raises(CandidateProcessInterrupted) as caught:
        runner._bounded_process_bytes(
            ["/bin/sh", "-c", "sleep 30"], cwd=str(tmp_path), environment={},
            timeout=20, output_limit=1024, capture_limit=1024,
            continuation=failed, process_released=lambda *_args: None,
        )
    receipt = build_process_interruption_receipt(
        caught.value.observation, request_sha256="a" * 64, stage="candidate_execution",
    )
    assert receipt["reason"] == "control_failed"
    assert "private" not in json.dumps(receipt)
    assert _absent(receipt["pid"])


def test_active_cancelled_producer_cannot_publish_or_replay_attempt(tmp_path, monkeypatch):
    import test_producer_bundle_transaction as fixture_module

    original = fixture_module._candidate_source
    def source(value):
        prefix = "import time\ntime.sleep(30)\n" if value == 9 else ""
        return prefix + original(value)
    monkeypatch.setattr(fixture_module, "_candidate_source", source)
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    control, timers, observed = SolveExecutionControl(30), [], []
    before = _prefix(context)
    def observer(pid, _pgid):
        observed.append(pid)
        timer = Timer(0.03, control.cancel)
        timers.append(timer)
        timer.start()
    context.bundle_pipeline._process_observer = observer
    context.bundle_pipeline._process_released = lambda *_args: None
    with pytest.raises(SolveExecutionCancelled):
        _call(fixture, control)
    for timer in timers:
        timer.join()
    assert len(observed) == 1 and _absent(observed[0])
    deadline_path = _batch(context, journal_id) / "execution.deadline.json"
    original_deadline = deadline_path.read_bytes()
    assert _prefix(context) == before
    assert not (_batch(context, journal_id) / "stage").exists()
    assert len(list(context.workspace.rglob("interrupted.json"))) == 1
    with pytest.raises(producer_bundle_transaction.NativeProducerBundleTransactionError):
        _call(fixture, SolveExecutionControl(30))
    assert observed and len(observed) == 1
    assert deadline_path.read_bytes() == original_deadline
    assert _prefix(context) == before


def test_interruption_receipt_cannot_coexist_with_completion_files(tmp_path):
    admission, request = candidate_fixture(tmp_path, b"sleep 30\n")
    control = SolveExecutionControl(0.05)
    with pytest.raises(SolveExecutionBudgetExceeded):
        run_candidate_execution_recorded(admission, **request, remaining_timeout=control.check)
    attempt = request["attempt_path"]
    assert (attempt / "interrupted.json").exists()
    (attempt / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(Exception, match="record_changed"):
        inspect_candidate_execution_record(attempt, plan=request["plan"], admission=admission)
