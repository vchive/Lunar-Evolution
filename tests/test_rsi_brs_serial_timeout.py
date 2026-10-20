"""Reserved serial cleanup never waits past the retained child deadline."""
from __future__ import annotations

import math

import pytest

from lunar_evolution import rsi_brs_serial_driver as driver
from lunar_evolution.rsi_learning import RSILearningError


class _Pool:
    def __init__(self) -> None:
        self.calls: list[tuple[bool, bool]] = []

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        self.calls.append((wait, cancel_futures))


class _PendingFuture:
    def __init__(self, *, completes: bool = False) -> None:
        self.done_state = False
        self.completes = completes
        self.timeouts: list[float] = []

    def done(self) -> bool:
        return self.done_state

    def exception(self, *, timeout: float) -> object:
        self.timeouts.append(timeout)
        if self.completes:
            self.done_state = True
            return object()
        raise TimeoutError("fixture worker did not exit")


def test_pending_worker_is_cancelled_without_waiting_past_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(driver.time, "monotonic", lambda: 8.0)
    pool, future = _Pool(), _PendingFuture()

    assert driver._shutdown_reserved_serial_executor(pool, future, deadline=10.0) is True
    assert future.timeouts == [2.0]
    assert pool.calls == [(False, True)]


def test_worker_that_exits_within_budget_gets_joined(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(driver.time, "monotonic", lambda: 8.0)
    pool, future = _Pool(), _PendingFuture(completes=True)

    assert driver._shutdown_reserved_serial_executor(pool, future, deadline=10.0) is False
    assert future.timeouts and future.timeouts[0] > 0
    assert pool.calls == [(True, True)]


def test_finished_worker_uses_normal_join_without_clock_read() -> None:
    pool, future = _Pool(), _PendingFuture()
    future.done_state = True

    assert driver._shutdown_reserved_serial_executor(pool, future, deadline=10.0) is False
    assert future.timeouts == []
    assert pool.calls == [(True, True)]


@pytest.mark.parametrize("deadline", [math.nan, math.inf, True, "10"])
def test_invalid_deadline_is_rejected_before_shutdown(deadline: object) -> None:
    with pytest.raises(RSILearningError, match="rsi_brs_reserved_serial_deadline_invalid"):
        driver._shutdown_reserved_serial_executor(_Pool(), _PendingFuture(), deadline=deadline)
