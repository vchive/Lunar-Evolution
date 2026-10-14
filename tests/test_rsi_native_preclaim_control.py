"""Preclaim control checks over retained inert bytes; no executable or provider runs."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_producer_gateway import _fixture

from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerProvider,
    NativeRSISchedulerProviderError,
)


def _observed_callback(callback):
    # Counter/clock state is a test observation, not a changing callback configuration.
    callback.rsi_fingerprint_config = lambda: {"fixture": "preclaim-control-observer-v1"}
    return callback


def _prepared(tmp_path, monkeypatch, *, cancelled=None, observe_stage=None):
    value = _fixture(tmp_path, monkeypatch)
    clock = [1.0]
    control = SolveExecutionControl(
        10.0, started_at=0.0, clock=lambda: clock[0], observe_stage=observe_stage,
    )
    value.native = replace(
        value.native, execution_control=control,
        cancelled=None if cancelled is None else _observed_callback(cancelled),
    )
    provider = NativeRSISchedulerProvider(value.native)
    plan = provider.plan(value.request, value.memory)
    for name in ("run_native_trusted_producer", "run_native_trusted_producer_outcome"):
        monkeypatch.setattr(
            f"lunar_evolution.rsi_native_scheduler.{name}",
            lambda *_a, **_k: pytest.fail("preclaim dispatched an inert producer"),
        )
    return value, provider, plan, control, clock


def _assert_no_effects(value, plan, before):
    assert value.ledger.inspect_native_episode_claim(
        value.request, plan_sha256=plan.plan_sha256,
    ) is None
    assert value.ledger.get_episode(value.request.episode_id) is None
    assert value.ledger.episode_result(value.request.episode_id) is None
    assert _inventory(value.root) == before


def test_live_parent_control_is_checked_twice_without_extending_deadlines(tmp_path, monkeypatch):
    stages = []
    value, provider, plan, control, clock = _prepared(
        tmp_path, monkeypatch, observe_stage=stages.append,
    )
    before = _inventory(value.root)
    expected = (control.started_at, control.deadline, control.timeout_seconds)
    for observed in (1.0, 4.0, 9.5):
        clock[0] = observed
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
        assert (control.started_at, control.deadline, control.timeout_seconds) == expected
        assert provider.context.execution_control is control
        assert provider._inputs(require_unexpired=True).deadline_unix == plan.deadline_unix
    assert stages == ["rsi_native_preclaim"] * 6
    _assert_no_effects(value, plan, before)


@pytest.mark.parametrize("reason", ["cancelled", "expired", "callback_cancelled"])
def test_parent_control_refuses_before_launch_or_claim_observations(
    tmp_path, monkeypatch, reason,
):
    value, provider, plan, control, clock = _prepared(tmp_path, monkeypatch)
    before = _inventory(value.root)
    if reason == "cancelled":
        control.cancel()
    elif reason == "callback_cancelled":
        control.add_cancellation_callback(lambda: True)
    else:
        clock[0] = control.deadline
    monkeypatch.setattr(provider, "_inputs", lambda **_k: pytest.fail("stopped control read inputs"))
    original = value.ledger.inspect_native_episode_claim
    monkeypatch.setattr(
        value.ledger, "inspect_native_episode_claim",
        lambda *_a, **_k: pytest.fail("stopped control observed claims"),
    )
    code = "preclaim_deadline_expired" if reason == "expired" else "preclaim_cancelled"
    with pytest.raises(NativeRSISchedulerProviderError, match=code):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    monkeypatch.setattr(value.ledger, "inspect_native_episode_claim", original)
    _assert_no_effects(value, plan, before)


@pytest.mark.parametrize("boundary", [1, 2])
@pytest.mark.parametrize("reason", ["cancelled", "expired", "callback_cancelled"])
def test_parent_control_rechecks_after_each_claim_observation(
    tmp_path, monkeypatch, boundary, reason,
):
    callback_state = [False]
    value, provider, plan, control, clock = _prepared(tmp_path, monkeypatch)
    control.add_cancellation_callback(lambda: callback_state[0])
    before = _inventory(value.root)
    observed = []
    original = value.ledger.inspect_native_episode_claim

    def inspect(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append(result)
        if len(observed) == boundary:
            if reason == "cancelled":
                control.cancel()
            elif reason == "expired":
                clock[0] = control.deadline
            else:
                callback_state[0] = True
        return result

    monkeypatch.setattr(value.ledger, "inspect_native_episode_claim", inspect)
    code = "preclaim_deadline_expired" if reason == "expired" else "preclaim_cancelled"
    with pytest.raises(NativeRSISchedulerProviderError, match=code):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    assert len(observed) == 2
    monkeypatch.setattr(value.ledger, "inspect_native_episode_claim", original)
    _assert_no_effects(value, plan, before)


def test_explicit_cancellation_rechecks_after_second_claim_observation(tmp_path, monkeypatch):
    callback_state = [False]
    sampled = []

    def cancelled():
        sampled.append(callback_state[0])
        return callback_state[0]

    value, provider, plan, _control, _clock = _prepared(
        tmp_path, monkeypatch, cancelled=cancelled,
    )
    before = _inventory(value.root)
    observed = []
    original = value.ledger.inspect_native_episode_claim

    def inspect(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append(result)
        if len(observed) == 2:
            callback_state[0] = True
        return result

    monkeypatch.setattr(value.ledger, "inspect_native_episode_claim", inspect)
    with pytest.raises(NativeRSISchedulerProviderError, match="preclaim_cancelled"):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    assert sampled == [False, True]
    monkeypatch.setattr(value.ledger, "inspect_native_episode_claim", original)
    _assert_no_effects(value, plan, before)


def test_final_callback_cannot_extend_parent_control_deadline(tmp_path, monkeypatch):
    value, provider, plan, control, _clock = _prepared(tmp_path, monkeypatch)
    before = _inventory(value.root)
    original_deadline = control.deadline
    observed = []

    def extend_on_final_check(_stage):
        observed.append(_stage)
        if len(observed) == 2:
            control.deadline += 100.0

    control._observe_stage = extend_on_final_check
    with pytest.raises(NativeRSISchedulerProviderError, match="preclaim_context_changed"):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    assert len(observed) == 2
    assert plan.deadline_unix == provider._inputs(require_unexpired=True).deadline_unix
    # The caller's mutation is preserved as evidence, but cannot authorize the preview.
    assert control.deadline == original_deadline + 100.0
    _assert_no_effects(value, plan, before)


def test_final_callback_cannot_replace_parent_control_with_equivalent_deadline(tmp_path, monkeypatch):
    value, provider, plan, _control, _clock = _prepared(tmp_path, monkeypatch)
    before = _inventory(value.root)
    calls = []

    def replace_on_final_check():
        calls.append(None)
        if len(calls) == 2:
            replacement = SolveExecutionControl(10.0, started_at=0.0, clock=lambda: 1.0)
            object.__setattr__(provider.context, "execution_control", replacement)
        return False

    object.__setattr__(provider.context, "cancelled", _observed_callback(replace_on_final_check))
    with pytest.raises(NativeRSISchedulerProviderError, match="preclaim_context_changed"):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    assert len(calls) == 2
    _assert_no_effects(value, plan, before)


def test_retained_absolute_deadline_expired_during_final_callback_is_not_remapped(
    tmp_path, monkeypatch,
):
    value, provider, plan, control, _clock = _prepared(tmp_path, monkeypatch)
    before = _inventory(value.root)
    wall_clock = [plan.deadline_unix - 1.0]
    calls = []
    expected = (control.started_at, control.deadline, control.timeout_seconds)

    def expire_on_final_check():
        calls.append(None)
        if len(calls) == 2:
            wall_clock[0] = plan.deadline_unix
        return False

    object.__setattr__(provider.context, "cancelled", _observed_callback(expire_on_final_check))
    monkeypatch.setattr("lunar_evolution.rsi_native_inputs.time.time", lambda: wall_clock[0])
    with pytest.raises(NativeRSISchedulerProviderError, match="launch_invalid"):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    assert len(calls) == 2
    assert (control.started_at, control.deadline, control.timeout_seconds) == expected
    assert provider._inputs(require_unexpired=False).deadline_unix == plan.deadline_unix
    _assert_no_effects(value, plan, before)


@pytest.mark.parametrize("source", ["callback", "control"])
def test_control_observation_failures_refuse_without_effects(tmp_path, monkeypatch, source):
    value, provider, plan, control, _clock = _prepared(tmp_path, monkeypatch)
    before = _inventory(value.root)

    def broken(*_args):
        raise ValueError("inert observer unavailable")

    if source == "callback":
        object.__setattr__(provider.context, "cancelled", _observed_callback(broken))
    else:
        control.add_cancellation_callback(broken)
    code = "preclaim_cancellation_invalid" if source == "callback" else "preclaim_control_invalid"
    with pytest.raises(NativeRSISchedulerProviderError, match=code):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    _assert_no_effects(value, plan, before)
