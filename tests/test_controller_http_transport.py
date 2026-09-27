"""Concrete controller HTTP transport uses loopback fixtures, never a provider."""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_http_transport_deadline import clear_proxy_environment, local_http

from lunar_evolution import http_transport
from lunar_evolution.controller_http_transport import (
    ControllerHttpRequest,
    ControllerHttpTransport,
)
from lunar_evolution.controller_request_broker import ControllerOwnedRequestBroker
from lunar_evolution.producer_request_transport import HostRequestLedger, RequestAdmission


@pytest.fixture(autouse=True)
def no_proxy(monkeypatch):
    clear_proxy_environment(monkeypatch)


def admission(seconds=2.0):
    started = time.monotonic_ns()
    return RequestAdmission(1, "local-request", started, started + int(seconds * 1_000_000_000))


def record_processes(monkeypatch):
    from lunar_evolution import controller_http_transport as transport

    original = transport.Popen
    processes, options = [], []

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        options.append((args, kwargs))
        return process

    monkeypatch.setattr(transport, "Popen", spawn)
    return processes, options


def assert_reaped(processes):
    assert processes
    for process in processes:
        assert process.returncode is not None
        assert process.poll() is not None
        assert process.stdin.closed and process.stdout.closed


def test_success_response_is_local_and_worker_has_no_secret_arguments(monkeypatch):
    processes, options = record_processes(monkeypatch)
    secret = "controller-transport-secret"
    monkeypatch.setenv("UNRELATED_SECRET", secret)
    with local_http() as (endpoint, calls):
        request = ControllerHttpRequest(endpoint + "/post", {"Authorization": secret}, b"request")
        issued = admission()
        handle = ControllerHttpTransport().start(issued, request)
        assert handle.admission is issued
        assert handle.response is None
        assert handle.wait(2.0) == "completed"
        assert handle.wait(0.0) == "completed"
        assert handle.response.status == 200
        assert handle.result() is handle.response
        assert json.loads(handle.response.body)["choices"][0]["message"]["content"] == "done"
        assert handle.failure is None
        assert handle.cancel() is False
    assert len(calls) == 1 and calls[0][1] == b"request"
    assert calls[0][2]["Authorization"] == secret
    args, kwargs = options[0]
    assert endpoint not in repr(args) and secret not in repr(args)
    assert kwargs["env"] == {} and kwargs["close_fds"] is True
    assert len(kwargs["pass_fds"]) == 1 and not kwargs.get("start_new_session", False)
    assert_reaped(processes)


def test_broker_returns_typed_success_response_without_journal(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    ledger = HostRequestLedger(request_timeout_seconds=2, max_requests=1)
    with local_http() as (endpoint, calls):
        result = ControllerOwnedRequestBroker(ledger, ControllerHttpTransport()).execute(
            "local-request", ControllerHttpRequest(endpoint, {}, b"payload"),
        )
    assert result.event.status == "completed"
    assert result.response.status == 200
    assert json.loads(result.response.body)["choices"][0]["message"]["content"] == "done"
    assert len(calls) == 1 and calls[0][1] == b"payload"
    assert ledger.snapshot().coverage == "brokered_requests_only"
    assert_reaped(processes)


@pytest.mark.parametrize("mode,status", [("headers", 200), ("error", 503)])
def test_broker_deadline_cancels_and_reaps_blocked_io(monkeypatch, mode, status):
    processes, _ = record_processes(monkeypatch)
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1)
    with local_http(mode, status) as (endpoint, calls):
        began = time.monotonic()
        result = ControllerOwnedRequestBroker(ledger, ControllerHttpTransport()).execute(
            "local-request", ControllerHttpRequest(endpoint, {}, b"request"),
        )
        elapsed = time.monotonic() - began
    assert elapsed < 1.4
    assert len(calls) == 1
    assert result.event.status == "timed_out"
    assert result.cancellation_acknowledged and result.host_timeout_enforced
    assert ledger.snapshot().active_count == 0
    assert ledger.snapshot().coverage == "brokered_requests_only"
    assert_reaped(processes)


@pytest.mark.parametrize("mode", ["headers", "body"])
def test_existing_admission_budget_is_not_restarted(monkeypatch, mode):
    processes, _ = record_processes(monkeypatch)
    issued = admission(0.35)
    time.sleep(0.2)
    with local_http(mode) as (endpoint, calls):
        began = time.monotonic()
        handle = ControllerHttpTransport().start(issued, ControllerHttpRequest(endpoint, {}, b""))
        assert handle.wait(3.0) is None
        assert handle.cancel() is True
        assert handle.wait(0.0) == "cancelled"
        elapsed = time.monotonic() - began
    assert elapsed < 0.3 and len(calls) <= 1
    assert handle.response is None
    with pytest.raises(ValueError, match="controller_http_response_unavailable"):
        handle.result()
    assert_reaped(processes)


def test_short_wait_can_resume_without_resubmitting(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    with local_http("body") as (endpoint, calls):
        handle = ControllerHttpTransport().start(admission(3), ControllerHttpRequest(endpoint, {}, b"once"))
        assert handle.wait(0.08) is None
        assert handle.wait(2.0) == "completed"
        assert handle.response.status == 200
    assert len(calls) == 1 and calls[0][1] == b"once"
    assert_reaped(processes)


def test_expired_admission_never_starts_worker_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("expired admission must not spawn")

    from lunar_evolution import controller_http_transport as transport

    monkeypatch.setattr(transport, "Popen", forbidden)
    issued = admission(0.01)
    time.sleep(0.02)
    with local_http() as (endpoint, calls):
        handle = ControllerHttpTransport().start(issued, ControllerHttpRequest(endpoint, {}, b""))
        assert handle.wait(1.0) is None
        assert handle.cancel() is True
        assert handle.wait(0.0) == "cancelled"
    assert calls == []


def test_worker_startup_stall_is_bounded_and_reaped(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    code = f"import runpy,time;time.sleep(5);runpy.run_path({http_transport.__file__!r},run_name='__main__')"
    monkeypatch.setattr(
        http_transport, "_worker_command",
        lambda fd: [sys.executable, "-I", "-S", "-B", "-c", code, str(fd)],
    )
    with local_http() as (endpoint, calls):
        began = time.monotonic()
        handle = ControllerHttpTransport().start(admission(0.2), ControllerHttpRequest(endpoint, {}, b""))
        assert handle.wait(3.0) is None
        assert handle.cancel() is True
    assert time.monotonic() - began < 0.6 and calls == []
    assert_reaped(processes)


def test_dns_stall_is_cancelled_and_worker_reaped(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    helper = http_transport.__file__
    code = (
        "import runpy,socket,time;"
        "socket.getaddrinfo=lambda *a,**kw: time.sleep(5);"
        f"runpy.run_path({helper!r},run_name='__main__')"
    )
    monkeypatch.setattr(
        http_transport, "_worker_command",
        lambda fd: [sys.executable, "-I", "-S", "-B", "-c", code, str(fd)],
    )
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1)
    began = time.monotonic()
    result = ControllerOwnedRequestBroker(ledger, ControllerHttpTransport()).execute(
        "local-request", ControllerHttpRequest("http://fixture.invalid", {}, b""),
    )
    assert time.monotonic() - began < 1.4
    assert result.event.status == "timed_out"
    assert result.host_timeout_enforced and result.response is None
    assert_reaped(processes)


def test_full_stdin_pipe_does_not_escape_admission_deadline(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    monkeypatch.setattr(
        http_transport, "_worker_command",
        lambda fd: [sys.executable, "-I", "-S", "-B", "-c", "import time;time.sleep(5)", str(fd)],
    )
    request = ControllerHttpRequest("http://127.0.0.1:1", {}, b"x" * (2 * 1024 * 1024))
    began = time.monotonic()
    handle = ControllerHttpTransport().start(admission(0.2), request)
    assert handle.wait(3.0) is None
    assert handle.cancel() is True
    assert time.monotonic() - began < 0.6
    assert_reaped(processes)


def test_child_timeout_error_before_deadline_is_failed_not_cancellation(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    with local_http(status=503) as (endpoint, calls):
        handle = ControllerHttpTransport().start(admission(), ControllerHttpRequest(endpoint, {}, b""))
        assert handle.wait(2.0) == "failed"
        assert handle.response is None
        assert handle.failure.reason == "http_error"
        assert handle.failure.status == 503
        assert handle.cancel() is False
    assert len(calls) == 1
    assert_reaped(processes)


def test_concurrent_handles_own_only_their_exact_child(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    with local_http("headers") as (slow, _), local_http() as (fast, fast_calls):
        transport = ControllerHttpTransport()
        slow_handle = transport.start(admission(0.2), ControllerHttpRequest(slow, {}, b"slow"))
        fast_handle = transport.start(admission(2), ControllerHttpRequest(fast, {}, b"fast"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            slow_wait = pool.submit(slow_handle.wait, 2.0)
            fast_wait = pool.submit(fast_handle.wait, 2.0)
            assert fast_wait.result(timeout=3) == "completed"
            assert slow_wait.result(timeout=3) is None
        assert slow_handle.cancel() is True
        assert fast_handle.response.status == 200
    assert len(fast_calls) == 1
    assert_reaped(processes)


def test_cancel_does_not_acknowledge_unreaped_child(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    monkeypatch.setattr(
        http_transport, "_worker_command",
        lambda fd: [sys.executable, "-I", "-S", "-B", "-c", "import time;time.sleep(5)", str(fd)],
    )
    handle = ControllerHttpTransport().start(admission(), ControllerHttpRequest("http://127.0.0.1:1", {}, b""))
    process = processes[0]
    original_wait = process.wait

    def unconfirmed_wait(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", kwargs.get("timeout"))

    monkeypatch.setattr(process, "wait", unconfirmed_wait)
    assert handle.cancel() is False
    assert handle.response is None
    monkeypatch.setattr(process, "wait", original_wait)
    assert handle.cancel() is True
    assert_reaped(processes)


def test_cancel_does_not_claim_previously_exited_worker(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    monkeypatch.setattr(
        http_transport, "_worker_command",
        lambda fd: [sys.executable, "-I", "-S", "-B", "-c", "pass", str(fd)],
    )
    handle = ControllerHttpTransport().start(
        admission(), ControllerHttpRequest("http://127.0.0.1:1", {}, b""),
    )
    assert handle.wait(0.0) is None
    assert processes[0].wait(timeout=2) == 0
    assert handle.cancel() is False
    assert handle.wait(0.0) == "failed"
    with pytest.raises(ValueError, match="controller_http_response_unavailable"):
        handle.result()
    assert_reaped(processes)


def test_spawn_failure_closes_both_lifeline_fds(monkeypatch):
    from lunar_evolution import controller_http_transport as transport

    actual_pipe = os.pipe
    descriptors = []

    def pipe():
        result = actual_pipe()
        descriptors.extend(result)
        return result

    def fail(*args, **kwargs):
        raise OSError("fixed fixture failure")

    monkeypatch.setattr(transport.os, "pipe", pipe)
    monkeypatch.setattr(transport, "Popen", fail)
    with pytest.raises(OSError):
        ControllerHttpTransport().start(admission(), ControllerHttpRequest("http://127.0.0.1:1", {}, b""))
    assert len(descriptors) == 2
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_oversized_worker_stdout_is_rejected_and_child_reaped(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    maximum = http_transport.MAX_RESULT_BYTES
    code = f"import sys,time;sys.stdout.buffer.write(b'x'*{maximum + 1});sys.stdout.buffer.flush();time.sleep(5)"
    monkeypatch.setattr(
        http_transport, "_worker_command",
        lambda fd: [sys.executable, "-I", "-S", "-B", "-c", code, str(fd)],
    )
    handle = ControllerHttpTransport().start(admission(), ControllerHttpRequest("http://127.0.0.1:1", {}, b""))
    assert handle.wait(2.0) == "failed"
    assert handle.response is None and handle.failure.reason == "transport_error"
    assert len(handle._output) == 0
    assert_reaped(processes)


def test_slow_result_decode_cannot_deliver_late_success(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    original = http_transport._decode_result

    def decode(raw):
        time.sleep(0.2)
        return original(raw)

    monkeypatch.setattr(http_transport, "_decode_result", decode)
    with local_http() as (endpoint, _):
        handle = ControllerHttpTransport().start(admission(0.15), ControllerHttpRequest(endpoint, {}, b""))
        assert handle.wait(1.0) is None
        assert handle.response is None
        assert handle.cancel() is False
        assert handle.wait(0.0) == "failed"
    assert_reaped(processes)


@pytest.mark.parametrize("timeout", [True, -1, float("inf"), float("nan"), 10**400])
def test_invalid_wait_budget_does_not_dispatch(monkeypatch, timeout):
    processes, _ = record_processes(monkeypatch)
    with local_http() as (endpoint, calls):
        handle = ControllerHttpTransport().start(admission(), ControllerHttpRequest(endpoint, {}, b""))
        try:
            with pytest.raises(ValueError, match="controller_http_wait_invalid"):
                handle.wait(timeout)
            assert calls == []
        finally:
            assert handle.cancel() is True
    assert_reaped(processes)
