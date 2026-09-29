"""Contract tests for the minimal no-new-side-effect controller resume path."""

from __future__ import annotations

import pytest

from lunar_evolution import RSILearningError


@pytest.mark.xfail(
    reason="Controller resume implementation is owned by the controller workstream",
    strict=False,
)
def test_resume_replays_persisted_completed_result_without_gateway_call():
    """The implementation must reconcile a stored result and return a terminal replay."""
    raise RSILearningError("rsi_resume_not_implemented")


@pytest.mark.xfail(
    reason="Controller resume implementation is owned by the controller workstream",
    strict=False,
)
def test_resume_unknown_without_result_stays_quarantined():
    """An unknown episode with no result cannot be guessed into failed/completed."""
    raise RSILearningError("rsi_unknown_reconcile_required")


@pytest.mark.xfail(
    reason="Controller resume implementation is owned by the controller workstream",
    strict=False,
)
def test_resume_does_not_create_a_second_episode_or_expand_budget():
    """Repeated resume must preserve episode identity and the persisted budget/deadline."""
    raise RSILearningError("rsi_resume_not_implemented")
