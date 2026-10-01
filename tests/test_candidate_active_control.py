"""Active caller-control failures clean owned groups without returning process results."""

from __future__ import annotations

import os
import sys
import time

import pytest
from test_bundle_population import build_context

from lunar_evolution import candidate_execution_runner as runner
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
)
from lunar_evolution.evolution import PopulationStrategy
from lunar_evolution.producer_bundle_control import bind_native_producer_bundle_checkpoint


def invoke(tmp_path, guard, observed, released):
    return runner._bounded_process_bytes(
        [sys.executable, "-I", "-c",
         'from pathlib import Path; import time; Path("started").write_text("started"); time.sleep(10)'],
        cwd=str(tmp_path), environment={}, timeout=12, output_limit=1024, capture_limit=1024,
        continuation_guard=guard,
        process_observer=lambda pid, pgid: observed.append((pid, pgid)),
        process_released=lambda pid, pgid: released.append((pid, pgid)),
    )


@pytest.mark.parametrize("reason", ["cancelled", "budget", "callback"])
def test_guard_failure_while_running_cleans_group_and_propagates_original(tmp_path, reason):
    observed, released = [], []
    errors = {
        "cancelled": SolveExecutionCancelled("evaluation"),
        "budget": SolveExecutionBudgetExceeded("evaluation", started_at=1, deadline=2, observed_at=3),
        "callback": RuntimeError("fixed local guard fixture"),
    }
    failure = errors[reason]

    def guard():
        if (tmp_path / "started").exists():
            raise failure

    started = time.monotonic()
    with pytest.raises(type(failure)) as caught:
        invoke(tmp_path, guard, observed, released)
    assert caught.value is failure
    assert time.monotonic() - started < 1.5
    assert len(observed) == 1 and observed == released
    with pytest.raises(ProcessLookupError):
        os.killpg(observed[0][1], 0)


def test_guard_failure_before_launch_has_no_process_or_release(tmp_path, monkeypatch):
    observed, released = [], []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("guard denied launch"))

    def guard():
        raise SolveExecutionCancelled("candidate_execution")

    with pytest.raises(SolveExecutionCancelled):
        invoke(tmp_path, guard, observed, released)
    assert observed == released == []


def test_active_guard_keeps_owner_when_group_cleanup_is_unconfirmed(tmp_path, monkeypatch):
    observed, released = [], []
    monkeypatch.setattr(runner, "_wait_owned_group_exit", lambda *_args: False)

    def guard():
        if (tmp_path / "started").exists():
            raise SolveExecutionCancelled("candidate_execution")

    with pytest.raises(SolveExecutionCancelled):
        invoke(tmp_path, guard, observed, released)
    assert len(observed) == 1 and released == []
    # The local test child is actually cleaned; the injected failed proof retains ownership.
    with pytest.raises(ProcessLookupError):
        os.killpg(observed[0][1], 0)


def test_cancellation_only_binding_keeps_existing_parent_hooks_and_restores_on_error(tmp_path):
    strategy = PopulationStrategy(build_context(tmp_path))
    pipeline = strategy.context.bundle_pipeline
    observations = []
    parent = lambda stage: 0.5
    guard = lambda: observations.append("parent")
    pipeline.set_remaining_timeout(parent)
    pipeline.set_continuation_guard(guard)

    def checkpoint(stage):
        observations.append(stage)
        if stage == "cancelled":
            raise SolveExecutionCancelled(stage)

    with bind_native_producer_bundle_checkpoint(strategy, checkpoint), pytest.raises(SolveExecutionCancelled):
        assert 0 < pipeline._remaining_timeout("evaluation") <= 0.5
        assert "parent" in observations
        pipeline._remaining_timeout("cancelled")
    assert pipeline._remaining_timeout is parent and pipeline._continuation_guard is guard
