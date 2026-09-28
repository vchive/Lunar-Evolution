from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

import lunar_evolution.producer_request_transport as transport
from lunar_evolution import (
    ControllerOwnedRequestBroker,
    ControllerRequestBrokerError,
    HostRequestJournal,
    HostRequestJournalIdentity,
    HostRequestLedger,
    ProducerRequestTransportError,
    RequestAdmission,
    read_host_request_journal,
)


class Clock:
    def __init__(self) -> None:
        self.value = 1_000_000_000

    def __call__(self) -> int:
        return self.value


class ImmediateHandle:
    def __init__(self, status: str = "completed", response: object = None) -> None:
        self.status = status
        self.response = response
        self.waits: list[float] = []
        self.cancelled = False

    def wait(self, timeout_seconds: float) -> str:
        self.waits.append(timeout_seconds)
        return self.status

    def cancel(self) -> bool:
        self.cancelled = True
        return True

    def result(self) -> object:
        return self.response


class CancelOnDeadlineHandle:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.waits: list[float] = []
        self.cancelled = False

    def wait(self, timeout_seconds: float) -> str | None:
        self.waits.append(timeout_seconds)
        if not self.cancelled:
            self.clock.value += 1_000_000_000
            return None
        return "cancelled"

    def cancel(self) -> bool:
        self.cancelled = True
        return True


class NonCancellableHandle:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def wait(self, _timeout_seconds: float) -> None:
        self.clock.value += 1_000_000_000

    def cancel(self) -> bool:
        return False


class RecordingTransport:
    def __init__(self, handle_factory) -> None:
        self.handle_factory = handle_factory
        self.admissions: list[RequestAdmission] = []
        self.payloads: list[object] = []

    def start(self, admission: RequestAdmission, payload: object):
        self.admissions.append(admission)
        self.payloads.append(payload)
        return self.handle_factory()


def _identity() -> HostRequestJournalIdentity:
    return HostRequestJournalIdentity(
        launch_id="launch-001", journal_id="journal-001", run_id="run-001",
        parent_task_id="parent-001", task_id="task-001", intent_sha256="a" * 64,
        request_timeout_seconds=1, max_requests=2,
    )


def _error(code: str, operation) -> None:
    with pytest.raises(ProducerRequestTransportError) as exc:
        operation()
    assert exc.value.code == code


def test_admission_counts_before_io_and_denies_over_budget():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=2, max_requests=1, monotonic_ns=clock)
    admission = ledger.admit("request-001")
    assert admission.deadline_ns == clock.value + 2_000_000_000
    assert ledger.snapshot().admitted_count == 1
    assert ledger.snapshot().active_count == 1
    _error("producer_request_transport_budget_exceeded", lambda: ledger.admit("request-002"))
    clock.value += 1_250_000
    event = ledger.finish(admission, status="completed")
    assert (event.sequence, event.status, event.duration_ms) == (1, "completed", 2)
    assert ledger.snapshot().within_broker_limits
    assert ledger.snapshot().coverage == "brokered_requests_only"
    assert ledger.snapshot().clock_source == "controller_monotonic"


def test_host_clock_marks_late_completion_and_expiration():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, monotonic_ns=clock)
    first = ledger.admit("request-001")
    clock.value += 1_000_000_000
    event = ledger.finish(first, status="completed")
    assert (event.status, event.duration_ms) == ("timed_out", 1000)
    second = ledger.admit("request-002")
    clock.value += 1_000_000_001
    assert ledger.expire()[0].status == "timed_out"
    assert ledger.snapshot().active_count == 0
    assert not ledger.snapshot().within_broker_limits
    _error(
        "producer_request_transport_admission_invalid",
        lambda: ledger.finish(second, status="completed"),
    )


def test_out_of_order_completion_preserves_admission_sequence():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, monotonic_ns=clock)
    first = ledger.admit("request-001")
    second = ledger.admit("request-002")
    ledger.finish(second, status="failed")
    ledger.finish(first, status="completed")
    assert [(item.sequence, item.status) for item in ledger.snapshot().events] == [
        (1, "completed"), (2, "failed"),
    ]


def test_forged_or_reused_admission_cannot_finish_a_request():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, monotonic_ns=clock)
    admission = ledger.admit("request-001")
    forged = RequestAdmission(1, "request-001", admission.started_ns, admission.deadline_ns)
    _error("producer_request_transport_admission_invalid", lambda: ledger.finish(forged, status="completed"))
    _error("producer_request_transport_request_id_duplicate", lambda: ledger.admit("request-001"))
    _error("producer_request_transport_status_invalid", lambda: ledger.finish(admission, status="timed_out"))
    _error("producer_request_transport_status_invalid", lambda: ledger.finish(admission, status=[]))
    assert ledger.snapshot().active_count == 1
    ledger.finish(admission, status="cancelled")
    _error("producer_request_transport_admission_invalid", lambda: ledger.finish(admission, status="completed"))


@pytest.mark.parametrize(
    ("timeout", "budget", "code"),
    [
        (True, 1, "producer_request_transport_timeout_invalid"),
        (0, 1, "producer_request_transport_timeout_invalid"),
        (1, True, "producer_request_transport_budget_invalid"),
        (1, 16_385, "producer_request_transport_budget_invalid"),
    ],
)
def test_invalid_limits_fail_closed(timeout, budget, code):
    _error(code, lambda: HostRequestLedger(request_timeout_seconds=timeout, max_requests=budget))


def test_untrusted_id_and_bad_clock_fail_closed():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, monotonic_ns=clock)
    _error("producer_request_transport_request_id_invalid", lambda: ledger.admit("a" * 129))
    _error("producer_request_transport_request_id_invalid", lambda: ledger.admit("bad/id"))
    clock.value = -1
    _error("producer_request_transport_clock_invalid", lambda: ledger.admit("request-001"))
    assert ledger.snapshot().admitted_count == 0


def test_clock_regression_and_callback_exception_preserve_active_request():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    admission = ledger.admit("request-001")
    clock.value -= 1
    _error("producer_request_transport_clock_invalid", lambda: ledger.finish(admission, status="completed"))
    assert ledger.snapshot().active_count == 1
    clock.value += 1
    ledger.finish(admission, status="completed")

    def broken_clock() -> int:
        raise RuntimeError("clock unavailable")

    broken = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=broken_clock)
    _error("producer_request_transport_clock_invalid", lambda: broken.admit("request-001"))
    assert broken.snapshot().admitted_count == 0


def test_durable_journal_replays_completed_and_uncertain_requests(tmp_path):
    path = tmp_path / "requests.log"
    identity = _identity()
    clock = Clock()
    with HostRequestJournal.create(path, identity) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )
        first = ledger.admit("request-001")
        ledger.admit("request-002")
        clock.value += 125_000_000
        ledger.finish(first, status="completed")
    assert os.stat(path).st_mode & 0o777 == 0o600
    recovery = read_host_request_journal(path, expected_identity=identity)
    assert recovery.journal_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert recovery.journal_bytes == path.stat().st_size
    assert recovery.snapshot.admitted_count == 2
    assert recovery.snapshot.active_count == 1
    assert [(event.sequence, event.status, event.duration_ms) for event in recovery.snapshot.events] == [
        (1, "completed", 125),
    ]
    assert recovery.uncertain_request_ids == ("request-002",)
    assert not recovery.snapshot.within_broker_limits
    _error(
        "producer_request_transport_wall_timeout",
        lambda: read_host_request_journal(
            path, expected_identity=identity, deadline=1.0, monotonic=lambda: 1.0,
        ),
    )


def test_journal_recovery_checks_identity_and_detects_tampering(tmp_path):
    path = tmp_path / "requests.log"
    identity = _identity()
    clock = Clock()
    with HostRequestJournal.create(path, identity) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )
        admission = ledger.admit("request-001")
        ledger.finish(admission, status="completed")
    wrong = HostRequestJournalIdentity(**{**identity.to_dict(), "task_id": "task-002"})
    _error(
        "producer_request_transport_journal_binding_mismatch",
        lambda: read_host_request_journal(path, expected_identity=wrong),
    )
    original = path.read_bytes()
    path.write_bytes(original.replace(b"request-001", b"request-999"))
    _error(
        "producer_request_transport_journal_invalid",
        lambda: read_host_request_journal(path, expected_identity=identity),
    )
    path.write_bytes(original[:-1])
    _error(
        "producer_request_transport_journal_invalid",
        lambda: read_host_request_journal(path, expected_identity=identity),
    )


def test_journal_rejects_existing_path_and_symbolic_links(tmp_path):
    identity = _identity()
    path = tmp_path / "requests.log"
    with HostRequestJournal.create(path, identity):
        pass
    _error(
        "producer_request_transport_journal_path_invalid",
        lambda: HostRequestJournal.create(path, identity),
    )
    alias = tmp_path / "alias.log"
    alias.symlink_to(path)
    _error(
        "producer_request_transport_journal_path_invalid",
        lambda: read_host_request_journal(alias, expected_identity=identity),
    )
    directory = tmp_path / "real"
    directory.mkdir()
    ancestor_link = tmp_path / "alias"
    ancestor_link.symlink_to(directory, target_is_directory=True)
    _error(
        "producer_request_transport_journal_path_invalid",
        lambda: HostRequestJournal.create(ancestor_link / "new.log", identity),
    )


def test_journal_requires_private_owner_directory_and_file(tmp_path):
    identity = _identity()
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    _error(
        "producer_request_transport_journal_path_invalid",
        lambda: HostRequestJournal.create(shared / "requests.log", identity),
    )
    assert not (shared / "requests.log").exists()

    path = tmp_path / "requests.log"
    with HostRequestJournal.create(path, identity):
        pass
    path.chmod(0o644)
    _error(
        "producer_request_transport_journal_path_invalid",
        lambda: read_host_request_journal(path, expected_identity=identity),
    )
    path.chmod(0o600)
    tmp_path.chmod(0o750)
    _error(
        "producer_request_transport_journal_path_invalid",
        lambda: read_host_request_journal(path, expected_identity=identity),
    )
    tmp_path.chmod(0o700)


@pytest.mark.parametrize("drift", ["file", "directory"])
def test_journal_permission_drift_poisoned_before_next_admission(tmp_path, drift):
    path = tmp_path / "requests.log"
    with HostRequestJournal.create(path, _identity()) as journal:
        ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, journal=journal)
        changed = path if drift == "file" else tmp_path
        changed.chmod(0o644 if drift == "file" else 0o755)
        _error(
            "producer_request_transport_journal_path_invalid",
            lambda: ledger.admit("request-001"),
        )
        assert ledger.snapshot().admitted_count == 0
        changed.chmod(0o600 if drift == "file" else 0o700)
        _error(
            "producer_request_transport_journal_unavailable",
            lambda: ledger.admit("request-001"),
        )


def test_journal_write_failure_poison_and_does_not_advance_ledger(tmp_path, monkeypatch):
    path = tmp_path / "requests.log"
    clock = Clock()
    with HostRequestJournal.create(path, _identity()) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )

        def fail_sync(_fd: int) -> None:
            raise OSError("fixture sync failure")

        monkeypatch.setattr(transport.os, "fsync", fail_sync)
        _error("producer_request_transport_journal_write_failed", lambda: ledger.admit("request-001"))
        assert ledger.snapshot().admitted_count == 0
        _error("producer_request_transport_journal_unavailable", lambda: ledger.admit("request-001"))


def test_terminal_write_failure_leaves_request_active(tmp_path, monkeypatch):
    clock = Clock()
    with HostRequestJournal.create(tmp_path / "requests.log", _identity()) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )
        admission = ledger.admit("request-001")

        def fail_sync(_fd: int) -> None:
            raise OSError("fixture sync failure")

        monkeypatch.setattr(transport.os, "fsync", fail_sync)
        _error(
            "producer_request_transport_journal_write_failed",
            lambda: ledger.finish(admission, status="completed"),
        )
        assert ledger.snapshot().active_count == 1
        assert ledger.snapshot().events == ()


def test_journal_size_limit_denies_admission_before_state_change(tmp_path, monkeypatch):
    path = tmp_path / "requests.log"
    with HostRequestJournal.create(path, _identity()) as journal:
        monkeypatch.setattr(transport, "MAX_HOST_REQUEST_JOURNAL_BYTES", journal._size + 1)
        ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, journal=journal)
        _error("producer_request_transport_journal_too_large", lambda: ledger.admit("request-001"))
        assert ledger.snapshot().admitted_count == 0


def test_journal_cannot_bind_to_two_ledgers(tmp_path):
    with HostRequestJournal.create(tmp_path / "requests.log", _identity()) as journal:
        HostRequestLedger(request_timeout_seconds=1, max_requests=2, journal=journal)
        _error(
            "producer_request_transport_journal_unavailable",
            lambda: HostRequestLedger(request_timeout_seconds=1, max_requests=2, journal=journal),
        )


def test_concurrent_admissions_reserve_unique_sequences_within_budget(tmp_path, monkeypatch):
    identity = HostRequestJournalIdentity(**{**_identity().to_dict(), "max_requests": 2})
    with HostRequestJournal.create(tmp_path / "requests.log", identity) as journal:
        ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, journal=journal)
        original = journal.record_admission

        def slow_record(admission):
            time.sleep(0.01)
            original(admission)

        monkeypatch.setattr(journal, "record_admission", slow_record)
        start = Barrier(12)

        def admit(index):
            start.wait(timeout=5)
            try:
                return ledger.admit(f"request-{index:03d}")
            except ProducerRequestTransportError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(admit, range(12)))
        successes = [result for result in results if isinstance(result, RequestAdmission)]
        assert sorted(item.sequence for item in successes) == [1, 2]
        assert results.count("producer_request_transport_budget_exceeded") == 10
        assert ledger.snapshot().admitted_count == 2
    recovery = read_host_request_journal(tmp_path / "requests.log", expected_identity=identity)
    assert recovery.snapshot.admitted_count == 2
    assert len(recovery.uncertain_request_ids) == 2


def test_concurrent_finish_records_only_one_terminal_event(tmp_path, monkeypatch):
    identity = _identity()
    with HostRequestJournal.create(tmp_path / "requests.log", identity) as journal:
        ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, journal=journal)
        admission = ledger.admit("request-001")
        original = journal.record_terminal

        def slow_record(event, ended_ns):
            time.sleep(0.01)
            original(event, ended_ns)

        monkeypatch.setattr(journal, "record_terminal", slow_record)
        start = Barrier(2)

        def finish(_index):
            start.wait(timeout=5)
            try:
                return ledger.finish(admission, status="completed")
            except ProducerRequestTransportError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(finish, range(2)))
        assert sum(isinstance(result, transport.HostRequestEvent) for result in results) == 1
        assert results.count("producer_request_transport_admission_invalid") == 1
        assert len(ledger.snapshot().events) == 1
    recovery = read_host_request_journal(tmp_path / "requests.log", expected_identity=identity)
    assert len(recovery.snapshot.events) == 1
    assert recovery.uncertain_request_ids == ()


def test_concurrent_finish_and_expire_record_one_terminal_event(tmp_path, monkeypatch):
    identity = _identity()
    clock = Clock()
    with HostRequestJournal.create(tmp_path / "requests.log", identity) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )
        admission = ledger.admit("request-001")
        clock.value = admission.deadline_ns
        original = journal.record_terminal

        def slow_record(event, ended_ns):
            time.sleep(0.01)
            original(event, ended_ns)

        monkeypatch.setattr(journal, "record_terminal", slow_record)
        start = Barrier(2)

        def finish():
            start.wait(timeout=5)
            try:
                return ledger.finish(admission, status="completed")
            except ProducerRequestTransportError as exc:
                return exc.code

        def expire():
            start.wait(timeout=5)
            try:
                return ledger.expire(admission=admission)
            except ProducerRequestTransportError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(finish), pool.submit(expire)]
            outcomes = [result.result() for result in results]
        assert outcomes.count("producer_request_transport_admission_invalid") == 1
        assert len(ledger.snapshot().events) == 1
        assert ledger.snapshot().events[0].status == "timed_out"
    recovery = read_host_request_journal(tmp_path / "requests.log", expected_identity=identity)
    assert len(recovery.snapshot.events) == 1
    assert recovery.uncertain_request_ids == ("request-001",)


def test_concurrent_journal_appends_preserve_ordinal_and_hash_chain(tmp_path, monkeypatch):
    path = tmp_path / "requests.log"
    with HostRequestJournal.create(path, _identity()) as journal:
        original = transport._record_line

        def slow_record_line(value):
            if value["kind"] == "probe":
                time.sleep(0.01)
            return original(value)

        monkeypatch.setattr(transport, "_record_line", slow_record_line)
        start = Barrier(12)

        def append(index):
            start.wait(timeout=5)
            journal._append("probe", {"value": index})

        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(append, range(12)))
        assert journal._ordinal == 12
    lines = path.read_bytes().splitlines(keepends=True)
    assert len(lines) == 13
    head = transport._ZERO_SHA
    for ordinal, line in enumerate(lines):
        record = transport._journal_record(line, ordinal, head)
        head = record["record_sha256"]


def test_controller_broker_admits_before_transport_and_forwards_deadline():
    clock = Clock()
    response = object()
    handle = ImmediateHandle(response=response)
    transport = RecordingTransport(lambda: handle)
    ledger = HostRequestLedger(request_timeout_seconds=2, max_requests=1, monotonic_ns=clock)
    result = ControllerOwnedRequestBroker(
        ledger, transport, monotonic_ns=clock, cancel_grace_seconds=0.1,
    ).execute("request-001", {"opaque": True})
    assert transport.payloads == [{"opaque": True}]
    assert transport.admissions[0].deadline_ns == clock.value + 2_000_000_000
    assert handle.waits == [2.0]
    assert result.event.status == "completed"
    assert result.response is response
    assert not result.host_timeout_enforced


def test_controller_broker_keeps_response_out_of_host_journal(tmp_path):
    clock = Clock()
    identity = _identity()
    path = tmp_path / "requests.log"
    response = b"private-provider-response"
    with HostRequestJournal.create(path, identity) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )
        result = ControllerOwnedRequestBroker(
            ledger, RecordingTransport(lambda: ImmediateHandle(response=response)),
            monotonic_ns=clock,
        ).execute("request-001", b"private-provider-payload")
    assert result.response is response
    assert b"private-provider" not in path.read_bytes()
    assert read_host_request_journal(path, expected_identity=identity).uncertain_request_ids == ()


def test_controller_broker_rejects_response_access_failure():
    class FailedResult(ImmediateHandle):
        def result(self) -> object:
            raise RuntimeError("private-provider-error")

    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    with pytest.raises(ControllerRequestBrokerError) as exc:
        ControllerOwnedRequestBroker(
            ledger, RecordingTransport(FailedResult), monotonic_ns=clock,
        ).execute("request-001", None)
    assert exc.value.code == "producer_request_broker_result_failed"
    assert exc.value.event is not None and exc.value.event.status == "failed"
    assert ledger.snapshot().active_count == 0


def test_controller_broker_discards_response_when_result_crosses_deadline():
    class LateResult(ImmediateHandle):
        def result(self) -> object:
            clock.value += 1_000_000_000
            return b"late-response"

    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    result = ControllerOwnedRequestBroker(
        ledger, RecordingTransport(LateResult), monotonic_ns=clock,
    ).execute("request-001", None)
    assert result.event.status == "timed_out"
    assert result.response is None
    assert not result.host_timeout_enforced


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_controller_broker_does_not_read_response_without_completion(status):
    class UnexpectedResult(ImmediateHandle):
        def result(self) -> object:
            raise AssertionError("response is not available")

    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    result = ControllerOwnedRequestBroker(
        ledger, RecordingTransport(lambda: UnexpectedResult(status)), monotonic_ns=clock,
    ).execute("request-001", None)
    assert result.event.status == status
    assert result.response is None


def test_controller_broker_requires_cancel_ack_and_terminal_confirmation():
    clock = Clock()
    handle = CancelOnDeadlineHandle(clock)
    transport = RecordingTransport(lambda: handle)
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    result = ControllerOwnedRequestBroker(
        ledger, transport, monotonic_ns=clock, cancel_grace_seconds=0.1,
    ).execute("request-001", None)
    assert result.event.status == "timed_out"
    assert result.cancellation_requested and result.cancellation_acknowledged
    assert result.host_timeout_enforced
    assert result.response is None
    assert ledger.snapshot().active_count == 0


def test_controller_broker_keeps_unconfirmed_timeout_fail_closed():
    clock = Clock()
    transport = RecordingTransport(lambda: NonCancellableHandle(clock))
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    with pytest.raises(ControllerRequestBrokerError) as exc:
        ControllerOwnedRequestBroker(
            ledger, transport, monotonic_ns=clock, cancel_grace_seconds=0.1,
        ).execute("request-001", None)
    assert exc.value.code == "producer_request_broker_timeout_unconfirmed"
    assert exc.value.event is None
    assert ledger.snapshot().active_count == 1
    assert not ledger.snapshot().within_broker_limits


def test_controller_broker_rejects_handle_without_cancellation():
    class WaitOnly:
        def wait(self, _timeout_seconds: float) -> str:
            return "completed"

    clock = Clock()
    transport = RecordingTransport(WaitOnly)
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    with pytest.raises(ControllerRequestBrokerError) as exc:
        ControllerOwnedRequestBroker(ledger, transport, monotonic_ns=clock).execute("request-001", None)
    assert exc.value.code == "producer_request_broker_handle_invalid"
    assert exc.value.event is None
    assert ledger.snapshot().active_count == 1
    assert not ledger.snapshot().within_broker_limits


def test_controller_broker_rejects_unhashable_transport_status():
    class BadStatus:
        def wait(self, _timeout_seconds: float):
            return []

        def cancel(self) -> bool:
            return True

    clock = Clock()
    transport = RecordingTransport(BadStatus)
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    with pytest.raises(ControllerRequestBrokerError) as exc:
        ControllerOwnedRequestBroker(ledger, transport, monotonic_ns=clock).execute("request-001", None)
    assert exc.value.code == "producer_request_broker_status_invalid"
    assert exc.value.event is None
    assert ledger.snapshot().active_count == 1
    assert not ledger.snapshot().within_broker_limits


@pytest.mark.parametrize("terminal", ["completed", "failed", []])
def test_controller_broker_never_confirms_timeout_when_cancelled_io_is_unproven(terminal):
    class LateTerminal:
        def __init__(self) -> None:
            self.waits = 0

        def wait(self, _timeout_seconds: float):
            self.waits += 1
            if self.waits == 1:
                clock.value += 1_000_000_000
                return None
            return terminal

        def cancel(self) -> bool:
            return True

    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    with pytest.raises(ControllerRequestBrokerError) as exc:
        ControllerOwnedRequestBroker(
            ledger, RecordingTransport(LateTerminal), monotonic_ns=clock,
        ).execute("request-001", None)
    assert exc.value.code == "producer_request_broker_timeout_unconfirmed"
    assert exc.value.event is None
    assert ledger.snapshot().active_count == 1
    assert not ledger.snapshot().within_broker_limits


@pytest.mark.parametrize("first_status", [None, []])
def test_controller_broker_retains_early_unconfirmed_io(first_status):
    class EarlyUnconfirmed:
        def wait(self, _timeout_seconds: float):
            return first_status

        def cancel(self) -> bool:
            return False

    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    with pytest.raises(ControllerRequestBrokerError) as exc:
        ControllerOwnedRequestBroker(
            ledger, RecordingTransport(EarlyUnconfirmed), monotonic_ns=clock,
        ).execute("request-001", None)
    assert exc.value.code == (
        "producer_request_broker_timeout_unconfirmed" if first_status is None
        else "producer_request_broker_status_invalid"
    )
    assert exc.value.event is None
    assert ledger.snapshot().active_count == 1
    assert not ledger.snapshot().within_broker_limits


def test_controller_broker_cancels_after_wait_failure():
    class FailedWait:
        def __init__(self) -> None:
            self.cancelled = False

        def wait(self, _timeout_seconds: float):
            if not self.cancelled:
                raise RuntimeError("transport failed")
            return "cancelled"

        def cancel(self) -> bool:
            self.cancelled = True
            return True

    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    with pytest.raises(ControllerRequestBrokerError) as exc:
        ControllerOwnedRequestBroker(
            ledger, RecordingTransport(FailedWait), monotonic_ns=clock,
        ).execute("request-001", None)
    assert exc.value.code == "producer_request_broker_wait_failed"
    assert exc.value.event is not None and exc.value.event.status == "cancelled"
    assert ledger.snapshot().active_count == 0


def test_controller_broker_retains_invalid_wait_even_if_cleanup_completes(tmp_path):
    class InvalidThenCompleted:
        def __init__(self) -> None:
            self.waits = 0

        def wait(self, _timeout_seconds: float):
            self.waits += 1
            return [] if self.waits == 1 else "completed"

        def cancel(self) -> bool:
            return True

    clock = Clock()
    identity = _identity()
    path = tmp_path / "requests.log"
    with HostRequestJournal.create(path, identity) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )
        with pytest.raises(ControllerRequestBrokerError) as exc:
            ControllerOwnedRequestBroker(
                ledger, RecordingTransport(InvalidThenCompleted), monotonic_ns=clock,
            ).execute("request-001", None)
    assert exc.value.code == "producer_request_broker_status_invalid"
    assert exc.value.event is None
    assert ledger.snapshot().active_count == 1
    assert not ledger.snapshot().within_broker_limits
    recovery = read_host_request_journal(path, expected_identity=identity)
    assert recovery.uncertain_request_ids == ("request-001",)


def test_controller_broker_retains_admission_when_start_fails():
    class FailedStart:
        def start(self, _admission: RequestAdmission, _payload: object):
            raise RuntimeError("transport startup failed")

    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    with pytest.raises(ControllerRequestBrokerError) as exc:
        ControllerOwnedRequestBroker(ledger, FailedStart(), monotonic_ns=clock).execute(
            "request-001", None,
        )
    assert exc.value.code == "producer_request_broker_transport_start_failed"
    assert exc.value.event is None
    assert ledger.snapshot().active_count == 1
