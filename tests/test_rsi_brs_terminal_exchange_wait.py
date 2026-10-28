"""Idle waits cannot authorize terminal stages or bypass their fresh gates."""

from __future__ import annotations

import threading

import pytest
from test_rsi_python_brs_result_delivery import _request_and_handoff, _response, _transaction

from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox
from lunar_evolution.rsi_python_brs_result_delivery import BRSOwnerResultDeliveryError
from lunar_evolution.rsi_python_brs_terminal_lifecycle import (
    _BRSWorkerTerminalEndpoint,
    _PrimitiveExchange,
)


class _GateStop(RuntimeError):
    pass


class _Cancelled(BaseException):
    pass


class _ForeignCondition:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        self.calls.append("enter")
        pytest.fail("foreign condition was entered")

    def __exit__(self, *_args):
        self.calls.append("exit")
        pytest.fail("foreign condition was exited")


def _exchange(monkeypatch, *, deadline=None):
    exchange = _PrimitiveExchange(deadline)
    monkeypatch.setattr(exchange.condition, "wait", lambda _timeout: None)
    return exchange


def _ack(exchange):
    with exchange.condition:
        exchange.acked = len(exchange.events)
        exchange.condition.notify_all()


def _endpoint(monkeypatch):
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff), request, handoff)
    mailbox = BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox)
    exchange = _exchange(monkeypatch)
    monkeypatch.setattr(BRSOwnerPublicationMailbox, "request", lambda *_args, **_kwargs: response)
    endpoint = _BRSWorkerTerminalEndpoint(
        mailbox, exchange, handoff.canonical_bytes, "a" * 64,
        threading.get_ident(), id(threading.current_thread()),
    )
    return endpoint, exchange, request


def test_pending_polls_use_hot_checks_between_distinct_entry_and_ack_cold_gates(monkeypatch):
    exchange, calls = _exchange(monkeypatch), []

    def cold():
        assert not exchange.condition._is_owned()
        calls.append(("cold", len(exchange.events), exchange.acked))

    def hot():
        assert not exchange.condition._is_owned()
        calls.append(("hot", len(exchange.events), exchange.acked))
        if sum(item[0] == "hot" for item in calls) == 3:
            _ack(exchange)

    exchange.submit(("callback_started",), cold, wait_check=hot)
    assert calls == [("cold", 0, 0), ("hot", 1, 0), ("hot", 1, 0),
                     ("hot", 1, 0), ("cold", 1, 1)]
    assert exchange.events == [("callback_started",)]
    assert not exchange.failed


def test_owner_ack_before_first_poll_still_requires_ack_cold_and_no_hot_check(monkeypatch):
    exchange, calls = _exchange(monkeypatch), []

    def acknowledge():
        exchange.acked = len(exchange.events)

    monkeypatch.setattr(exchange.condition, "notify_all", acknowledge)
    exchange.submit(("callback_started",), lambda: calls.append((len(exchange.events), exchange.acked)),
                    wait_check=lambda: pytest.fail("hot check ran after owner ACK"))
    assert calls == [(0, 0), (1, 1)]


@pytest.mark.parametrize("waiting", [False, 0, "check", object()])
def test_invalid_hot_callback_refuses_before_cold_or_enqueue(monkeypatch, waiting):
    exchange = _exchange(monkeypatch)
    with pytest.raises(RSILearningError, match="observation_drift"):
        exchange.submit(("callback_started",), lambda: pytest.fail("cold ran"), wait_check=waiting)
    assert not exchange.events and not exchange.failed


@pytest.mark.parametrize("explicit_none", [False, True])
def test_absent_hot_callback_retains_original_enqueued_cold_poll_order(monkeypatch, explicit_none):
    exchange, calls = _exchange(monkeypatch), []

    def cold():
        assert not exchange.condition._is_owned()
        calls.append((len(exchange.events), exchange.acked))
        if len(calls) == 2:
            _ack(exchange)

    kwargs = {"wait_check": None} if explicit_none else {}
    exchange.submit(("callback_started",), cold, **kwargs)
    assert calls == [(1, 0), (1, 0)]
    assert exchange.acked == 1 and not exchange.failed


@pytest.mark.parametrize("boundary", ["entry", "hot", "ack"])
def test_gate_exception_stops_without_another_check_or_authorized_return(monkeypatch, boundary):
    exchange, calls = _exchange(monkeypatch), []

    def cold():
        calls.append("cold")
        if boundary == "entry" or boundary == "ack" and calls.count("cold") == 2:
            raise _GateStop("cold stopped")

    def hot():
        calls.append("hot")
        if boundary == "hot":
            raise _GateStop("hot stopped")
        _ack(exchange)

    with pytest.raises(_GateStop, match="stopped"):
        exchange.submit(("callback_started",), cold, wait_check=hot)
    assert calls == {"entry": ["cold"], "hot": ["cold", "hot"],
                     "ack": ["cold", "hot", "cold"]}[boundary]
    assert len(exchange.events) == (0 if boundary == "entry" else 1)


def test_hot_cancellation_propagates_without_ack_gate_or_retry(monkeypatch):
    exchange, calls = _exchange(monkeypatch), []

    def hot():
        calls.append("cancel")
        raise _Cancelled

    with pytest.raises(_Cancelled):
        exchange.submit(("callback_started",), lambda: calls.append("cold"), wait_check=hot)
    assert calls == ["cold", "cancel"]
    assert exchange.acked == 0


@pytest.mark.parametrize("pending_polls", [0, 1])
def test_original_deadline_expires_without_refresh_or_an_ack_gate(monkeypatch, pending_polls):
    exchange, calls = _exchange(monkeypatch, deadline=10.0), []
    clock = iter([9.0] * pending_polls + [11.0])
    monkeypatch.setattr("lunar_evolution.rsi_python_brs_terminal_lifecycle.time.monotonic", lambda: next(clock))
    with pytest.raises(RSILearningError, match="callback_unknown"):
        exchange.submit(("callback_started",), lambda: calls.append("cold"),
                        wait_check=lambda: calls.append("hot"))
    assert calls == ["cold"] + ["hot"] * pending_polls
    assert exchange.deadline == 10.0 and exchange.failed and exchange.acked == 0


@pytest.mark.parametrize("boundary", ["hot", "ack"])
@pytest.mark.parametrize("mutation", ["failed", "bool_ack", "events", "condition", "event", "deadline"])
def test_checks_cannot_replace_transport_or_revoke_ack_before_return(monkeypatch, boundary, mutation):
    exchange, calls = _exchange(monkeypatch, deadline=10.0), []
    # An unexpired clock isolates transport mutation from timeout behavior.
    monkeypatch.setattr("lunar_evolution.rsi_python_brs_terminal_lifecycle.time.monotonic", lambda: 1.0)
    foreign = _ForeignCondition()

    def mutate():
        if mutation == "failed":
            exchange.failed = True
        elif mutation == "bool_ack":
            exchange.acked = True
        elif mutation == "events":
            exchange.events = list(exchange.events)
        elif mutation == "condition":
            exchange.condition = foreign
        elif mutation == "event":
            # Keep equal primitives while replacing the original tuple object.
            exchange.events[-1] = tuple(iter(exchange.events[-1]))
        else:
            exchange.deadline = 20.0

    def cold():
        calls.append("cold")
        if boundary == "ack" and calls.count("cold") == 2:
            mutate()

    def hot():
        calls.append("hot")
        _ack(exchange)
        if boundary == "hot":
            mutate()

    with pytest.raises(RSILearningError, match="observation_drift|callback_unknown"):
        exchange.submit(("callback_started",), cold, wait_check=hot)
    assert calls == ["cold", "hot"] + (["cold"] if boundary == "ack" else [])
    assert not foreign.calls


def test_ack_cold_cannot_roll_back_the_observed_ack(monkeypatch):
    exchange, calls = _exchange(monkeypatch), []

    def cold():
        calls.append("cold")
        if len(calls) == 2:
            exchange.acked = 0

    with pytest.raises(RSILearningError, match="observation_drift"):
        exchange.submit(("callback_started",), cold, wait_check=lambda: _ack(exchange))
    assert calls == ["cold", "cold"]
    assert exchange.acked == 0 and exchange.events == [("callback_started",)]


def test_endpoint_uses_hot_waits_for_all_stages_and_cold_gates_before_callback_and_settled(monkeypatch):
    endpoint, exchange, request = _endpoint(monkeypatch)
    calls = []

    def cold():
        assert not exchange.condition._is_owned()
        calls.append(("cold", len(exchange.events), exchange.acked))
        assert endpoint.status == "inflight"

    def hot():
        assert not exchange.condition._is_owned()
        calls.append(("hot", len(exchange.events), exchange.acked))
        assert [event[0] for event in exchange.events] == [
            "delivery", "callback_started", "callback_finished",
        ][:len(exchange.events)]
        _ack(exchange)

    def callback(_delivery):
        assert exchange.acked == 2 and len(exchange.events) == 2
        assert calls[-1] == ("cold", 2, 2)
        calls.append(("callback", 2, 2))
        return "saved"

    assert endpoint.receive_and_settle(request, callback=callback, check=cold, wait_check=hot) == "saved"
    assert calls == [
        ("cold", 0, 0), ("cold", 0, 0), ("cold", 0, 0),
        ("hot", 1, 0), ("cold", 1, 1), ("cold", 1, 1),
        ("hot", 2, 1), ("cold", 2, 2), ("callback", 2, 2),
        ("cold", 2, 2), ("hot", 3, 2), ("cold", 3, 3),
    ]
    assert endpoint.status == "settled" and not exchange.failed


@pytest.mark.parametrize("cold_at", range(1, 9))
def test_each_cold_boundary_failure_prevents_later_stages_and_never_settles(monkeypatch, cold_at):
    endpoint, exchange, request = _endpoint(monkeypatch)
    cold_calls, callbacks = [], []

    def cold():
        cold_calls.append((len(exchange.events), exchange.acked))
        if len(cold_calls) == cold_at:
            raise _GateStop("cold stopped")

    with pytest.raises((_GateStop, BRSOwnerResultDeliveryError)):
        endpoint.receive_and_settle(request, callback=lambda delivery: callbacks.append(delivery),
                                    check=cold, wait_check=lambda: _ack(exchange))
    expected_stages = {1: 0, 2: 0, 3: 0, 4: 1, 5: 1, 6: 2, 7: 2, 8: 3}[cold_at]
    assert [event[0] for event in exchange.events] == [
        "delivery", "callback_started", "callback_finished",
    ][:expected_stages]
    assert len(cold_calls) == cold_at
    assert len(callbacks) == (1 if cold_at >= 7 else 0)
    assert endpoint.status == "unknown" and exchange.failed
    with pytest.raises(RSILearningError, match="worker_unavailable"):
        endpoint.receive_and_settle(request, callback=lambda _delivery: pytest.fail("callback retried"),
                                    check=lambda: pytest.fail("cold retried"), wait_check=lambda: None)


@pytest.mark.parametrize("stage", ["delivery", "callback_started", "callback_finished"])
@pytest.mark.parametrize("cancelled", [False, True])
def test_stage_hot_failure_stops_followup_and_keeps_callback_at_most_once(monkeypatch, stage, cancelled):
    endpoint, exchange, request = _endpoint(monkeypatch)
    callbacks, hots = [], []

    def hot():
        current = exchange.events[-1][0]
        hots.append(current)
        if current == stage:
            if cancelled:
                raise _Cancelled
            raise _GateStop("hot stopped")
        _ack(exchange)

    with pytest.raises((_GateStop, _Cancelled, BRSOwnerResultDeliveryError)):
        endpoint.receive_and_settle(request, callback=lambda delivery: callbacks.append(delivery),
                                    check=lambda: None, wait_check=hot)
    expected = ["delivery", "callback_started", "callback_finished"]
    assert hots == expected[:expected.index(stage) + 1]
    assert [event[0] for event in exchange.events] == hots
    assert len(callbacks) == (1 if stage == "callback_finished" else 0)
    assert endpoint.status == "unknown" and exchange.failed


@pytest.mark.parametrize("boundary", ["entry", "response", "hot", "ack"])
@pytest.mark.parametrize("mutation", ["condition", "exchange"])
def test_endpoint_drift_cleanup_wakes_original_owner_without_touching_foreign_transport(monkeypatch, boundary, mutation):
    endpoint, exchange, request = _endpoint(monkeypatch)
    condition, foreign = exchange.condition, _ForeignCondition()
    callbacks, notifications, cold_calls = [], [], []
    original_notify = condition.notify_all

    def notify():
        notifications.append(exchange.failed)
        original_notify()

    monkeypatch.setattr(condition, "notify_all", notify)

    def mutate():
        if mutation == "condition":
            exchange.condition = foreign
        else:
            other = _PrimitiveExchange(None)
            other.condition = foreign
            endpoint._exchange = other

    def cold():
        cold_calls.append(None)
        if len(cold_calls) == {"entry": 1, "response": 2, "ack": 4}.get(boundary):
            mutate()

    def hot():
        _ack(exchange)
        if boundary == "hot":
            mutate()

    with pytest.raises(RSILearningError, match="observation_drift|worker_invalid"):
        endpoint.receive_and_settle(request, callback=lambda delivery: callbacks.append(delivery),
                                    check=cold, wait_check=hot)
    assert not callbacks and not foreign.calls
    assert endpoint.status == "unknown" and exchange.failed
    assert notifications[-1] is True
    assert [event[0] for event in exchange.events] == ([] if boundary in {"entry", "response"} else ["delivery"])


@pytest.mark.parametrize("mutation", ["condition", "exchange"])
def test_mailbox_hot_drift_is_refused_before_wait_check_enters_foreign_transport(monkeypatch, mutation):
    endpoint, exchange, request = _endpoint(monkeypatch)
    foreign, callbacks, waits = _ForeignCondition(), [], []

    def request_from_mailbox(*_args, **kwargs):
        kwargs["check"]()
        pytest.fail("mailbox continued after transport drift")

    monkeypatch.setattr(BRSOwnerPublicationMailbox, "request", request_from_mailbox)

    def hot():
        waits.append(None)
        if mutation == "condition":
            exchange.condition = foreign
        else:
            other = _PrimitiveExchange(None)
            other.condition = foreign
            endpoint._exchange = other

    with pytest.raises(RSILearningError, match="observation_drift|worker_invalid"):
        endpoint.receive_and_settle(request, callback=lambda delivery: callbacks.append(delivery),
                                    check=lambda: None, wait_check=hot)
    assert len(waits) == 1 and not callbacks and not foreign.calls
    assert not exchange.events and exchange.failed and endpoint.status == "unknown"


def test_actual_callback_failure_reports_one_unknown_finished_stage_and_never_settles(monkeypatch):
    endpoint, exchange, request = _endpoint(monkeypatch)
    callbacks, cold_calls, hots = [], [], []

    def callback(delivery):
        callbacks.append(delivery)
        raise _GateStop("callback stopped")

    def hot():
        hots.append(exchange.events[-1][0])
        _ack(exchange)

    with pytest.raises(BRSOwnerResultDeliveryError, match="settlement_unknown"):
        endpoint.receive_and_settle(request, callback=callback,
                                    check=lambda: cold_calls.append(None), wait_check=hot)
    assert len(callbacks) == 1 and len(cold_calls) == 8
    assert hots == ["delivery", "callback_started", "callback_finished"]
    assert exchange.events[1:] == [("callback_started",), ("callback_finished", "unknown")]
    assert exchange.acked == 3 and exchange.failed and endpoint.status == "unknown"
