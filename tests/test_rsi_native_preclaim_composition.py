"""Fresh gateway to scheduler control composition using retained inert inputs."""

from __future__ import annotations

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_native_preclaim_control import _assert_no_effects, _prepared

from lunar_evolution.rsi_native_gateway import (
    NativeRSIExecutionConfig,
    NativeRSISolverGateway,
    NativeRSISolverGatewayError,
)


@pytest.mark.parametrize("reason", ["cancelled", "expired"])
def test_gateway_parent_control_refuses_without_claim(tmp_path, monkeypatch, reason):
    value, provider, plan, control, clock = _prepared(tmp_path, monkeypatch)
    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(value.ledger, provider.plan, provider))
    before = _inventory(value.root)
    if reason == "cancelled":
        control.cancel()
    else:
        clock[0] = control.deadline
    with pytest.raises(NativeRSISolverGatewayError, match="preclaim_failed") as caught:
        gateway.run(value.request, value.memory)
    expected = "preclaim_cancelled" if reason == "cancelled" else "preclaim_deadline_expired"
    assert expected in str(caught.value.__cause__)
    _assert_no_effects(value, plan, before)


def test_gateway_cancellation_at_final_scheduler_read_leaves_no_claim(tmp_path, monkeypatch):
    value, provider, plan, control, _clock = _prepared(tmp_path, monkeypatch)
    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(value.ledger, provider.plan, provider))
    before = _inventory(value.root)
    inspect = value.ledger.inspect_native_episode_claim
    observations = []

    def cancel_at_final_read(*args, **kwargs):
        result = inspect(*args, **kwargs)
        observations.append(result)
        # Gateway's initial read followed by scheduler's two preclaim reads.
        if len(observations) == 3:
            control.cancel()
        return result

    monkeypatch.setattr(value.ledger, "inspect_native_episode_claim", cancel_at_final_read)
    with pytest.raises(NativeRSISolverGatewayError, match="preclaim_failed") as caught:
        gateway.run(value.request, value.memory)
    assert "preclaim_cancelled" in str(caught.value.__cause__)
    assert len(observations) == 3
    monkeypatch.setattr(value.ledger, "inspect_native_episode_claim", inspect)
    _assert_no_effects(value, plan, before)
