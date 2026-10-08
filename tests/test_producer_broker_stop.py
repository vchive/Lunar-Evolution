from __future__ import annotations

import os
import threading
import time

import pytest
from test_producer_launcher import _intent

import lunar_evolution.producer_broker_ipc as ipc
from lunar_evolution.producer_request_transport import read_host_request_journal


@pytest.mark.parametrize("operation", ["read", "write"])
def test_stop_wakes_blocked_pipe_without_closing_owned_descriptors(operation):
    read_fd, write_fd = os.pipe()
    stop = threading.Event()
    entered = threading.Event()
    state = {}
    initial = [os.fstat(fd) for fd in (read_fd, write_fd)]
    try:
        if operation == "write":
            os.set_blocking(write_fd, False)
            while True:
                try:
                    os.write(write_fd, b"x" * 4096)
                except BlockingIOError:
                    break

        def blocked():
            entered.set()
            try:
                deadline = time.monotonic_ns() + 2_000_000_000
                if operation == "read":
                    ipc._read_line(read_fd, deadline, 4096, stop=stop)
                else:
                    ipc._write_line(write_fd, b"must-not-write", deadline, stop=stop)
            except ipc.ProducerBrokerIpcError as exc:
                state["reason"] = exc.code

        thread = threading.Thread(target=blocked)
        thread.start()
        assert entered.wait(1)
        stop.set()
        thread.join(timeout=1)
        assert not thread.is_alive() and state == {"reason": "producer_broker_cancelled"}
        for fd, original in zip((read_fd, write_fd), initial, strict=True):
            current = os.fstat(fd)
            assert (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino)
        if operation == "write":
            os.set_blocking(read_fd, False)
            while True:
                try:
                    assert set(os.read(read_fd, 65536)) <= {ord("x")}
                except BlockingIOError:
                    break
    finally:
        stop.set()
        os.close(read_fd)
        os.close(write_fd)


def _request_frame(fd):
    os.write(fd, b'{"protocol":"lunar-producer-broker-ipc-v1","request_id":"req-1",'
             b'"body_base64":"aGVsbG8="}\n')


def test_stopped_bridge_keeps_empty_journal_and_never_admits(tmp_path, monkeypatch):
    _, intent = _intent(tmp_path)
    stop = threading.Event()
    stop.set()
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    monkeypatch.setattr(
        ipc.ControllerHttpTransport, "start",
        lambda *_: pytest.fail("stopped bridge must not perform I/O"),
    )
    try:
        _request_frame(request_write)
        observation = ipc.serve_producer_broker(
            request_read, response_write, intent=intent,
            journal_dir=tmp_path / "journal", config=ipc.ProducerBrokerConfig("http://fixture", {}),
            deadline_ns=time.monotonic_ns() + 2_000_000_000, stop=stop,
        )
    finally:
        for fd in (request_read, request_write, response_read, response_write):
            os.close(fd)
    assert observation.reason == "cancelled" and not observation.complete
    assert observation.snapshot.admitted_count == 0
    recovered = read_host_request_journal(
        observation.journal_path, expected_identity=observation.journal_identity,
        expected_file_identity=observation.journal_file_identity,
    )
    assert recovered.snapshot == observation.snapshot


@pytest.mark.parametrize("acknowledged", [True, False])
def test_bridge_active_stop_never_writes_response_or_upgrades_uncertain_io(
    tmp_path, monkeypatch, acknowledged,
):
    _, intent = _intent(tmp_path)
    stop = threading.Event()
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    started = []
    cancelled = []

    class Handle:
        def cancel(self):
            cancelled.append(True)
            return acknowledged

        def wait(self, _seconds):
            return "cancelled"

    class Transport:
        def __init__(self, *, fixed_destination):
            assert fixed_destination is True

        def start(self, admission, payload):
            started.append((admission, payload))
            stop.set()
            return Handle()

    monkeypatch.setattr(ipc, "ControllerHttpTransport", Transport)
    monkeypatch.setattr(ipc, "_write_line", lambda *_args, **_kwargs: pytest.fail("no stop response"))
    try:
        _request_frame(request_write)
        observation = ipc.serve_producer_broker(
            request_read, response_write, intent=intent,
            journal_dir=tmp_path / "journal", config=ipc.ProducerBrokerConfig("http://fixture", {}),
            deadline_ns=time.monotonic_ns() + 2_000_000_000, stop=stop,
        )
    finally:
        for fd in (request_read, request_write, response_read, response_write):
            os.close(fd)
    assert len(started) == 1 and cancelled == [True]
    assert not observation.complete and observation.snapshot.admitted_count == 1
    recovered = read_host_request_journal(
        observation.journal_path, expected_identity=observation.journal_identity,
    )
    if acknowledged:
        assert observation.reason == "cancelled"
        assert observation.snapshot.active_count == 0
        assert [event.status for event in observation.snapshot.events] == ["cancelled"]
        assert recovered.uncertain_request_ids == ()
    else:
        assert observation.reason == "request_boundary_unknown"
        assert observation.snapshot.active_count == 1 and observation.snapshot.events == ()
        assert recovered.uncertain_request_ids == ("req-1",)
