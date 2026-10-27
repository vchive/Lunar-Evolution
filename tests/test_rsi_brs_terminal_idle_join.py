"""Real thread/control scheduling; no synthetic session is publication authority."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native_scheduler import NativeRSISchedulerContext
from lunar_evolution.rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox
from lunar_evolution.rsi_python_brs_terminal_lifecycle import (
    BRSOwnerTerminalLifecycle,
    _BRSWorkerTerminalEndpoint,
    _PrimitiveExchange,
)


@pytest.fixture
def component():
    """Exact handle graph only: intentionally lacks a real ledger/lineage owner."""
    release = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        thread = executor.submit(threading.current_thread).result(timeout=3)
        future = executor.submit(release.wait, 5)
        control = SolveExecutionControl(5)
        native = NativeRSISchedulerContext.__new__(NativeRSISchedulerContext)
        object.__setattr__(native, "execution_control", control)
        object.__setattr__(native, "cancelled", None)
        owner = _BRSLineageCheckpointOwner.__new__(_BRSLineageCheckpointOwner)
        owner._native, owner._before_control, owner._before_cancelled = native, control, None
        owner._before_control_pin = _BRSLineageCheckpointOwner._before_control_state(owner)
        owner._thread, owner._poisoned = threading.get_ident(), False
        owner._channel, owner._before_channel_condition = object(), threading.Condition()
        owner._plan = SimpleNamespace(deadline_unix=None)
        mailbox = BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox)
        mailbox._owner_thread, mailbox._worker_thread = owner._thread, thread.ident
        mailbox._terminal_lifecycle_opened = True
        exchange = _PrimitiveExchange(control.deadline)
        endpoint = _BRSWorkerTerminalEndpoint.__new__(_BRSWorkerTerminalEndpoint)
        endpoint._mailbox, endpoint._exchange = mailbox, exchange
        endpoint._worker_thread, endpoint._worker_object_id = thread.ident, id(thread)
        endpoint._admission_channel, endpoint._admission_condition = owner._channel, owner._before_channel_condition
        session = BRSOwnerTerminalLifecycle.__new__(BRSOwnerTerminalLifecycle)
        session._owner, session._mailbox = owner, mailbox
        session._future, session._executor, session._thread = future, executor, thread
        session._endpoint, session._exchange, session._poisoned = endpoint, exchange, False
        session._scope = (owner, mailbox, future, executor, thread, endpoint, exchange, exchange.condition)
        session._head, session._history = None, []
        try:
            yield SimpleNamespace(session=session, release=release, control=control, owner=owner, exchange=exchange)
        finally:
            release.set()


def _refuse_full(monkeypatch, calls):
    def reject(_owner, **_kwargs):
        calls.append("full")
        raise RSILearningError("component_full_drift")

    monkeypatch.setattr(_BRSLineageCheckpointOwner, "_identity", reject)


def test_empty_idle_wait_has_no_full_observation_or_ack_before_future_completion(component, monkeypatch):
    value, calls, checks = component, [], []
    _refuse_full(monkeypatch, calls)

    def hot():
        checks.append("idle")
        assert not calls and value.exchange.acked == 0 and value.session._history == []
        if len(checks) == 3:
            value.release.set()

    with pytest.raises(RSILearningError, match="component_full_drift"):
        value.session._join_worker(lambda: calls.append("check"), hot_check=hot)
    assert len(checks) >= 3 and calls == ["check", "full"]
    assert value.exchange.events == [] and value.exchange.acked == 0


@pytest.mark.parametrize("stage", ["delivery", "callback_started", "callback_finished"])
def test_pending_event_rebuilds_full_gate_before_any_ack(component, monkeypatch, stage):
    calls = []
    _refuse_full(monkeypatch, calls)

    def hot():
        with component.exchange.condition:
            component.exchange.events.append((stage,))

    with pytest.raises(RSILearningError, match="component_full_drift"):
        component.session._join_worker(lambda: calls.append("check"), hot_check=hot)
    assert calls == ["check", "full"]
    assert component.exchange.acked == 0 and component.session._history == []


@pytest.mark.parametrize("outcome", ["returned", "raised", "cancelled"])
def test_already_done_future_still_requires_full_gate(component, monkeypatch, outcome):
    future, calls = Future(), []
    if outcome == "cancelled":
        assert future.cancel()
    elif outcome == "raised":
        future.set_exception(RuntimeError("component worker failed"))
    else:
        future.set_result(None)
    component.session._future = future
    scope = component.session._scope
    component.session._scope = (*scope[:2], future, *scope[3:])
    _refuse_full(monkeypatch, calls)
    with pytest.raises(RSILearningError, match="component_full_drift"):
        component.session._join_worker(lambda: calls.append("check"), hot_check=lambda: None)
    assert calls == ["check", "full"] and component.exchange.acked == 0


@pytest.mark.parametrize("fault", ["cancelled", "expired", "unix_expired", "deadline_drift", "poisoned"])
def test_idle_keeps_original_control_and_deadline(component, fault):
    value = component
    error, match = RSILearningError, ".*"
    if fault == "cancelled":
        value.control.cancel()
        error = SolveExecutionCancelled
    elif fault == "expired":
        # Construct an originally expired component pin, without changing clocks.
        value.control.started_at = time.monotonic() - 10
        value.control.deadline = value.control.started_at + value.control.timeout_seconds
        value.owner._before_control_pin = _BRSLineageCheckpointOwner._before_control_state(value.owner)
        value.exchange.deadline = value.control.deadline
        error = SolveExecutionBudgetExceeded
    elif fault == "unix_expired":
        value.owner._plan.deadline_unix = time.time() - 1
        match = "session_expired"
    elif fault == "deadline_drift":
        value.exchange.deadline += 1
        match = "session_drift"
    else:
        value.owner._poisoned = True
        match = "session_drift"
    with pytest.raises(error, match=match):
        value.session._idle()
    assert value.exchange.acked == 0 and value.session._history == []


@pytest.mark.parametrize("fault", ["condition", "future", "exchange", "endpoint"])
def test_hot_callback_handle_replacement_refuses_before_using_foreign_handle(component, fault):
    class Foreign:
        def __enter__(self):
            pytest.fail("entered replacement condition")

        def done(self):
            pytest.fail("read replacement future")

    def hot():
        if fault == "condition":
            component.exchange.condition = Foreign()
        else:
            setattr(component.session, "_" + fault, Foreign())

    with pytest.raises(RSILearningError, match="session_drift"):
        component.session._join_worker(lambda: pytest.fail("full callback before local refusal"), hot_check=hot)


def test_hot_check_live_head_refusal_never_acknowledges(component):
    def stale():
        raise RSILearningError("component_live_head_drift")

    with pytest.raises(RSILearningError, match="component_live_head_drift"):
        component.session._join_worker(lambda: pytest.fail("full callback on idle"), hot_check=stale)
    assert component.exchange.acked == 0 and component.session._history == []


def test_default_join_preserves_full_check_on_empty_poll(component, monkeypatch):
    calls = []
    _refuse_full(monkeypatch, calls)
    with pytest.raises(RSILearningError, match="component_full_drift"):
        component.session._join_worker(lambda: calls.append("check"))
    assert calls == ["check", "full"]
