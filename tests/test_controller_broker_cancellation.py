from __future__ import annotations

import signal
import time

import pytest
from test_controller_http_transport import assert_reaped, record_processes
from test_http_transport_deadline import clear_proxy_environment, local_http
from test_producer_request_transport import Clock, RecordingTransport, _identity

from lunar_evolution.controller_http_transport import ControllerHttpRequest, ControllerHttpTransport
from lunar_evolution.controller_request_broker import (
    ControllerOwnedRequestBroker,
    ControllerRequestBrokerError,
)
from lunar_evolution.producer_request_transport import (
    HostRequestJournal,
    HostRequestLedger,
    read_host_request_journal,
)


class PollingHandle:
    def __init__(self, clock, *, acknowledgement=True, terminal="cancelled", complete_after=None):
        self.clock = clock
        self.acknowledgement = acknowledgement
        self.terminal = terminal
        self.complete_after = complete_after
        self.waits = []
        self.cancel_calls = 0

    def wait(self, seconds):
        self.waits.append(seconds)
        if self.cancel_calls:
            return self.terminal
        self.clock.value += int(seconds * 1_000_000_000)
        if self.complete_after is not None and len(self.waits) >= self.complete_after:
            return "completed"
        return None

    def cancel(self):
        self.cancel_calls += 1
        return self.acknowledgement

    def result(self):
        return b"local-response"


def test_stop_before_admission_never_starts_or_spends_request():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    transport = RecordingTransport(lambda: pytest.fail("stopped request must not start"))
    with pytest.raises(ControllerRequestBrokerError) as caught:
        ControllerOwnedRequestBroker(ledger, transport, monotonic_ns=clock).execute(
            "request-001", None, cancelled=lambda: True,
        )
    assert caught.value.code == "producer_request_broker_cancelled"
    assert ledger.snapshot().admitted_count == 0
    assert transport.admissions == []


def test_stop_between_admission_and_start_retains_slot_without_io():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    transport = RecordingTransport(lambda: pytest.fail("stopped admission must not start"))
    observations = iter((False, True))
    result = ControllerOwnedRequestBroker(ledger, transport, monotonic_ns=clock).execute(
        "request-001", None, cancelled=lambda: next(observations),
    )
    assert result.event.status == "cancelled"
    assert result.cancellation_requested and not result.cancellation_acknowledged
    assert not result.host_timeout_enforced and result.response is None
    assert ledger.snapshot().admitted_count == 1 and ledger.snapshot().active_count == 0
    assert transport.admissions == []


def test_active_cancellation_uses_same_admission_and_confirms_stop():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    handle = PollingHandle(clock)
    transport = RecordingTransport(lambda: handle)
    result = ControllerOwnedRequestBroker(ledger, transport, monotonic_ns=clock).execute(
        "request-001", None, cancelled=lambda: bool(handle.waits),
    )
    assert result.admission is transport.admissions[0]
    assert result.admission.deadline_ns == 2_000_000_000
    assert handle.waits == [0.05, 0.1] and handle.cancel_calls == 1
    assert result.event.status == "cancelled" and result.event.duration_ms == 50
    assert result.cancellation_requested and result.cancellation_acknowledged
    assert not result.host_timeout_enforced and result.response is None
    assert ledger.snapshot().admitted_count == 1 and ledger.snapshot().active_count == 0


def test_polling_waits_continue_without_readmission_or_budget_reset():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    handle = PollingHandle(clock, complete_after=3)
    transport = RecordingTransport(lambda: handle)
    result = ControllerOwnedRequestBroker(ledger, transport, monotonic_ns=clock).execute(
        "request-001", None, cancelled=lambda: False,
    )
    assert handle.waits == [0.05] * 3 and handle.cancel_calls == 0
    assert len(transport.admissions) == 1 and result.admission.deadline_ns == 2_000_000_000
    assert result.event.status == "completed" and result.response == b"local-response"
    assert not result.cancellation_requested and not result.host_timeout_enforced


def test_polling_reaches_original_request_timeout_without_refresh():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    handle = PollingHandle(clock)
    transport = RecordingTransport(lambda: handle)
    result = ControllerOwnedRequestBroker(ledger, transport, monotonic_ns=clock).execute(
        "request-001", None, cancelled=lambda: False,
    )
    assert clock.value == result.admission.deadline_ns == 2_000_000_000
    assert len(transport.admissions) == 1 and handle.waits[:-1] == [0.05] * 20
    assert result.event.status == "timed_out" and result.host_timeout_enforced
    assert result.cancellation_requested and result.cancellation_acknowledged


def test_observer_time_is_deducted_before_transport_wait():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    handle = PollingHandle(clock)
    observations = []

    def cancelled():
        observations.append(True)
        if len(observations) == 3:
            clock.value += 980_000_000
        return False

    result = ControllerOwnedRequestBroker(
        ledger, RecordingTransport(lambda: handle), monotonic_ns=clock,
    ).execute("request-001", None, cancelled=cancelled)
    assert handle.waits == [0.02, 0.1]
    assert clock.value == result.admission.deadline_ns == 2_000_000_000
    assert result.event.status == "timed_out" and result.host_timeout_enforced


@pytest.mark.parametrize(
    ("acknowledgement", "terminal"),
    [(False, "cancelled"), (1, "cancelled"), (True, "completed"), (True, "failed"),
     (True, None), (True, [])],
)
def test_unconfirmed_active_stop_retains_uncertain_admission(tmp_path, acknowledgement, terminal):
    clock = Clock()
    handle = PollingHandle(clock, acknowledgement=acknowledgement, terminal=terminal)
    path = tmp_path / "requests"
    with HostRequestJournal.create(path, _identity()) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )
        with pytest.raises(ControllerRequestBrokerError) as caught:
            ControllerOwnedRequestBroker(
                ledger, RecordingTransport(lambda: handle), monotonic_ns=clock,
            ).execute("request-001", None, cancelled=lambda: bool(handle.waits))
    assert caught.value.code == "producer_request_broker_cancellation_unconfirmed"
    assert caught.value.event is None and ledger.snapshot().active_count == 1
    assert read_host_request_journal(path, expected_identity=_identity()).uncertain_request_ids == (
        "request-001",
    )


@pytest.mark.parametrize("failure", ["exception", "non_boolean"])
def test_invalid_active_observer_cleans_transport_but_retains_unknown(tmp_path, failure):
    clock = Clock()
    handle = PollingHandle(clock)
    path = tmp_path / "requests"

    def cancelled():
        if not handle.waits:
            return False
        if failure == "exception":
            raise RuntimeError("private callback detail")
        return 1

    with HostRequestJournal.create(path, _identity()) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )
        with pytest.raises(ControllerRequestBrokerError) as caught:
            ControllerOwnedRequestBroker(
                ledger, RecordingTransport(lambda: handle), monotonic_ns=clock,
            ).execute("request-001", None, cancelled=cancelled)
    assert caught.value.code == (
        "producer_request_broker_cancellation_unknown" if failure == "exception"
        else "producer_request_broker_cancellation_invalid"
    )
    assert "private callback detail" not in str(caught.value)
    assert handle.cancel_calls == 1 and caught.value.event is None
    assert ledger.snapshot().active_count == 1 and ledger.snapshot().events == ()
    assert read_host_request_journal(path, expected_identity=_identity()).uncertain_request_ids == (
        "request-001",
    )


@pytest.mark.parametrize("observer", [1, lambda: 1, lambda: None])
def test_invalid_observer_before_admission_denies_io(observer):
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    transport = RecordingTransport(lambda: pytest.fail("invalid observer must not start"))
    with pytest.raises(ControllerRequestBrokerError) as caught:
        ControllerOwnedRequestBroker(ledger, transport, monotonic_ns=clock).execute(
            "request-001", None, cancelled=observer,
        )
    assert caught.value.code == "producer_request_broker_cancellation_invalid"
    assert ledger.snapshot().admitted_count == 0 and transport.admissions == []


def test_loopback_blocked_request_is_cancelled_and_exact_worker_reaped(monkeypatch):
    clear_proxy_environment(monkeypatch)
    processes, _ = record_processes(monkeypatch)
    ledger = HostRequestLedger(request_timeout_seconds=5, max_requests=1)
    with local_http("headers") as (endpoint, calls):
        observed_cancel = []

        def cancelled():
            if calls and not observed_cancel:
                observed_cancel.append(time.monotonic())
            return bool(calls)

        result = ControllerOwnedRequestBroker(ledger, ControllerHttpTransport()).execute(
            "request-001", ControllerHttpRequest(endpoint, {}, b"fixture"),
            cancelled=cancelled,
        )
        elapsed = time.monotonic() - observed_cancel[0]
    assert len(calls) == 1 and elapsed < 1.5
    assert result.event.status == "cancelled" and not result.host_timeout_enforced
    assert result.cancellation_requested and result.cancellation_acknowledged
    assert result.response is None and ledger.snapshot().active_count == 0
    assert_reaped(processes)
    assert [process.returncode for process in processes] == [-signal.SIGKILL]
