"""One monotonic control narrows all native producer-publication stages."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_bundle_population import build_context

from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.evolution import PopulationStrategy
from lunar_evolution.producer_bundle_control import (
    ProducerBundleControlError,
    bind_native_producer_bundle_control,
    native_producer_bundle_budget_sha256,
)


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


def test_shared_control_expires_across_stages_and_in_process_retry(tmp_path) -> None:
    strategy = PopulationStrategy(build_context(tmp_path))
    clock = FakeClock()
    control = SolveExecutionControl(10, clock=clock)
    pipeline = strategy.context.bundle_pipeline
    with bind_native_producer_bundle_control(strategy, control) as check:
        assert check("preparation") == 10
        clock.value += 4
        assert check("candidate_execution") == 6
        clock.value += 5
        assert pipeline._effective_timeout("evaluation") == 1
    assert pipeline._remaining_timeout is None
    clock.value += 1
    with bind_native_producer_bundle_control(strategy, control) as check, pytest.raises(
        SolveExecutionBudgetExceeded,
    ) as error:
        check("publication")
    assert error.value.stage == "publication"
    assert control.deadline == 110


def test_existing_parent_deadline_and_guard_are_preserved_and_restored(tmp_path) -> None:
    context = build_context(tmp_path)
    clock = FakeClock()
    parent = SolveExecutionControl(4, clock=clock)
    guard_calls = []
    guard = lambda: guard_calls.append("checked")
    callback = parent.check
    strategy = PopulationStrategy(replace(context, remaining_timeout=callback, continuation_guard=guard))
    pipeline = strategy.context.bundle_pipeline
    with bind_native_producer_bundle_control(strategy, SolveExecutionControl(30, clock=clock)) as check:
        assert check("preparation") == 4
        assert len(guard_calls) == 1
        clock.value += 4
        with pytest.raises(SolveExecutionBudgetExceeded):
            pipeline._effective_timeout("evaluation")
    assert pipeline._remaining_timeout is callback
    assert pipeline._continuation_guard is guard


@pytest.mark.parametrize("origin", ["strategy", "control", "callback_failure"])
def test_cancellation_stops_later_stages_and_restores_hooks(tmp_path, origin) -> None:
    cancelled = False

    def is_cancelled():
        if origin == "callback_failure" and cancelled:
            raise RuntimeError("fixture")
        return cancelled and origin == "strategy"

    context = replace(build_context(tmp_path), cancelled=is_cancelled)
    strategy = PopulationStrategy(context)
    control = SolveExecutionControl(30, clock=FakeClock())
    with bind_native_producer_bundle_control(strategy, control) as check:
        assert check("preparation") == 30
        cancelled = True
        if origin == "control":
            control.cancel()
        with pytest.raises(SolveExecutionCancelled):
            check("commit")
    assert context.bundle_pipeline._remaining_timeout is None


def test_parent_callback_consumption_is_counted_before_admission(tmp_path) -> None:
    clock = FakeClock()

    def consuming_callback(stage):
        del stage
        clock.value += 10
        return 30

    strategy = PopulationStrategy(replace(build_context(tmp_path), remaining_timeout=consuming_callback))
    with bind_native_producer_bundle_control(strategy, SolveExecutionControl(10, clock=clock)) as check, pytest.raises(
        SolveExecutionBudgetExceeded,
    ):
        check("preparation")


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), "10"])
def test_invalid_parent_budget_never_admits_work(tmp_path, value) -> None:
    strategy = PopulationStrategy(replace(build_context(tmp_path), remaining_timeout=lambda stage: value))
    with bind_native_producer_bundle_control(strategy, SolveExecutionControl(30)) as check, pytest.raises(
        ProducerBundleControlError,
        match="parent_budget_invalid",
    ):
        check("stage")


def test_policy_digest_pins_limits_but_not_portable_start_time(tmp_path) -> None:
    strategy = PopulationStrategy(build_context(tmp_path))
    clock = FakeClock()
    before = native_producer_bundle_budget_sha256(strategy, SolveExecutionControl(10, clock=clock))
    clock.value += 100
    assert native_producer_bundle_budget_sha256(strategy, SolveExecutionControl(10, clock=clock)) == before
    assert native_producer_bundle_budget_sha256(strategy, SolveExecutionControl(11, clock=clock)) != before


def test_exception_restores_hooks_for_later_native_population_work(tmp_path) -> None:
    strategy = PopulationStrategy(build_context(tmp_path))
    pipeline = strategy.context.bundle_pipeline
    with pytest.raises(RuntimeError, match="fixture"), bind_native_producer_bundle_control(
        strategy, SolveExecutionControl(30),
    ):
        raise RuntimeError("fixture")
    assert pipeline._remaining_timeout is None
    assert pipeline._continuation_guard is None


@pytest.mark.parametrize("field", ["remaining_timeout", "continuation_guard"])
def test_invalid_parent_callback_type_is_rejected_before_binding(tmp_path, field) -> None:
    strategy = PopulationStrategy(build_context(tmp_path))
    strategy.context = replace(strategy.context, **{field: 42})
    pipeline = strategy.context.bundle_pipeline
    with pytest.raises(ProducerBundleControlError, match="parent_control_invalid"), bind_native_producer_bundle_control(
        strategy, SolveExecutionControl(30),
    ):
        raise AssertionError("invalid parent callback cannot admit work")
    assert pipeline._remaining_timeout is None
    assert pipeline._continuation_guard is None


def test_nested_controls_preserve_both_deadlines_without_recursion(tmp_path) -> None:
    strategy = PopulationStrategy(build_context(tmp_path))
    pipeline = strategy.context.bundle_pipeline
    clock = FakeClock()
    with bind_native_producer_bundle_control(strategy, SolveExecutionControl(5, clock=clock)) as outer:
        assert pipeline._remaining_timeout is outer
        with bind_native_producer_bundle_control(strategy, SolveExecutionControl(30, clock=clock)) as inner:
            assert inner("preparation") == 5
            assert pipeline._effective_timeout("candidate_execution") <= 5
        assert pipeline._remaining_timeout is outer
        clock.value += 5
        with pytest.raises(SolveExecutionBudgetExceeded):
            outer("commit")
    assert pipeline._remaining_timeout is None


@pytest.mark.parametrize("consumed", [2, 5])
def test_later_parent_callback_consumption_reduces_earlier_parent_remainder(tmp_path, consumed) -> None:
    clock = FakeClock()
    parent = SolveExecutionControl(4, clock=clock)
    calls = []

    def consume_time(stage):
        calls.append(stage)
        clock.value += consumed
        return 30

    strategy = PopulationStrategy(replace(build_context(tmp_path), remaining_timeout=consume_time))
    strategy.context.bundle_pipeline.set_remaining_timeout(parent.check)
    control = SolveExecutionControl(30, clock=clock)
    with bind_native_producer_bundle_control(strategy, control) as check:
        if consumed < 4:
            assert check("preparation") == 4 - consumed
        else:
            with pytest.raises(SolveExecutionBudgetExceeded) as error:
                check("preparation")
            assert error.value.stage == "preparation"
    assert calls == ["preparation"]
