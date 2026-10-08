"""Actual isolated-worker destination checks use only disposable loopback servers."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_controller_http_transport import admission, assert_reaped, record_processes
from test_http_transport_deadline import clear_proxy_environment
from test_http_transport_tls import local_certificate, local_https, project_trust
from test_producer_launcher import _intent

from lunar_evolution import http_transport
from lunar_evolution.controller_http_transport import ControllerHttpRequest, ControllerHttpTransport
from lunar_evolution.controller_request_broker import ControllerOwnedRequestBroker
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig, serve_producer_broker
from lunar_evolution.producer_request_transport import HostRequestLedger


@pytest.fixture(autouse=True)
def local_configuration(monkeypatch):
    clear_proxy_environment(monkeypatch)
    monkeypatch.setattr(http_transport, "getproxies", dict)


@pytest.fixture(scope="module")
def destination_certificate(tmp_path_factory):
    return local_certificate.__wrapped__(tmp_path_factory)


@contextmanager
def loopback(*, status=200, location=None, location_header="Location", body=b"origin-response",
             slow=False, block_headers=False):
    calls = []
    received, stop = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append((self.command, self.path, data, dict(self.headers)))
            received.set()
            if block_headers:
                stop.wait(3)
            try:
                self.send_response(status)
                if location is not None:
                    self.send_header(location_header, location)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if slow:
                    for index in range(0, len(body), 4):
                        if stop.wait(0.03):
                            return
                        self.wfile.write(body[index:index + 4])
                        self.wfile.flush()
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        do_GET = do_POST = respond

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, received
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def request(endpoint):
    return ControllerHttpRequest(endpoint, {"X-Inert-Fixture": "local-only"}, b"inert-request")


@pytest.mark.parametrize("status", [300, 301, 302, 303, 304, 305, 306, 307, 308, 399])
def test_fixed_mode_never_follows_3xx_and_keeps_bounded_original_failure(monkeypatch, status):
    processes, _ = record_processes(monkeypatch)
    body = b"inert-origin-error" * 300
    with loopback(body=b"redirect-trap") as (trap, trap_calls, _), \
            loopback(status=status, location=trap + "/redirected", body=body) as (origin, calls, _):
        handle = ControllerHttpTransport(fixed_destination=True).start(admission(), request(origin + "/post"))
        assert handle.wait(2) == "failed"
        assert handle.response is None and handle.failure.reason == "http_error"
        assert handle.failure.status == status
        assert handle.failure.body == (b"" if status == 304 else body[:http_transport.MAX_ERROR_BYTES])
        assert handle.failure.observation.http_exchange_index == 1
        assert calls[0][:3] == ("POST", "/post", b"inert-request")
        assert calls[0][3]["X-Inert-Fixture"] == "local-only"
        assert len(calls) == 1 and trap_calls == []
    assert_reaped(processes)


@pytest.mark.parametrize("header,location", [
    ("Location", None), ("Location", "http://[malformed"), ("Location", "/same-origin"),
    ("Location", "file:///inert-unreachable"), ("URI", "http://[malformed"),
])
def test_fixed_302_refuses_before_parsing_location_or_uri(monkeypatch, header, location):
    processes, _ = record_processes(monkeypatch)
    with loopback(status=302, location=location, location_header=header, body=b"original-302") as (origin, calls, _):
        handle = ControllerHttpTransport(fixed_destination=True).start(admission(), request(origin))
        assert handle.wait(2) == "failed"
        assert (handle.failure.status, handle.failure.reason, handle.failure.body) == (302, "http_error", b"original-302")
        assert len(calls) == 1
    assert_reaped(processes)


def test_generic_default_still_follows_local_redirect(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    with loopback(body=b"legacy-redirect-response") as (trap, trap_calls, _), \
            loopback(status=302, location=trap + "/second") as (origin, calls, _):
        handle = ControllerHttpTransport().start(admission(), request(origin + "/first"))
        assert handle.wait(2) == "completed"
        assert handle.result().body == b"legacy-redirect-response"
        assert calls[0][:3] == ("POST", "/first", b"inert-request")
        assert len(calls) == len(trap_calls) == 1
        assert trap_calls[0][:3] == ("GET", "/second", b"")
    assert_reaped(processes)


@pytest.mark.parametrize("source", ["environment", "system"])
@pytest.mark.parametrize("fixed", [False, True], ids=["legacy", "fixed"])
def test_fixed_mode_bypasses_proxy_trap_while_generic_keeps_defaults(monkeypatch, source, fixed):
    processes, _ = record_processes(monkeypatch)
    with loopback(body=b"proxy-response") as (proxy, proxy_calls, _), \
            loopback(body=b"origin-response") as (origin, origin_calls, _):
        if source == "environment":
            monkeypatch.setenv("http_proxy", proxy)
            monkeypatch.setenv("no_proxy", "no-bypass.invalid")
        else:
            monkeypatch.setattr(http_transport, "getproxies", lambda: {"http": proxy})
            # Platform system bypass preferences are separate trusted input.
            # Disable them in this worker fixture so the configured proxy trap
            # is deterministic on Darwin as well as Linux.
            code = ("import runpy,urllib.request;urllib.request.proxy_bypass=lambda *_:False;"
                    f"runpy.run_path({http_transport.__file__!r},run_name='__main__')")
            monkeypatch.setattr(http_transport, "_worker_command",
                                lambda fd: [sys.executable, "-I", "-S", "-B", "-c", code, str(fd)])
        handle = ControllerHttpTransport(fixed_destination=fixed).start(admission(), request(origin + "/post"))
        assert handle.wait(2) == "completed"
        assert handle.result().body == (b"origin-response" if fixed else b"proxy-response")
        selected = origin_calls if fixed else proxy_calls
        assert len(selected) == 1 and selected[0][0] == "POST"
        assert selected[0][2] == b"inert-request"
        assert (proxy_calls if fixed else origin_calls) == []
    assert_reaped(processes)


def test_fixed_configuration_never_discovers_environment_or_system_proxies(monkeypatch):
    monkeypatch.setattr(http_transport, "getproxies_environment", lambda: pytest.fail("fixed mode proxy discovery"))
    monkeypatch.setattr(http_transport, "getproxies", lambda: pytest.fail("fixed mode system proxy discovery"))
    monkeypatch.setenv("SSL_CERT_FILE", "/inert/local-ca.pem")
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    assert http_transport._configuration(fixed_destination=True) == {
        "proxies": {}, "proxy_source": "direct", "trust": {"SSL_CERT_FILE": "/inert/local-ca.pem"},
        "policy": "fixed-direct-no-redirect-v1",
    }


@pytest.mark.parametrize("value", [None, 0, 1, "fixed", {}, []])
def test_transport_policy_requires_exact_bool(value):
    with pytest.raises(ValueError, match="controller_http_policy_invalid"):
        ControllerHttpTransport(fixed_destination=value)


@pytest.mark.parametrize("endpoint", [
    "http://", "http:///missing", "http://user@localhost", "http://user:inert@localhost",
    "http://localhost/#fragment", "http://localhost/#", "http://localhost:\n80/",
    "\thttp://localhost", "http://localhost/path\r", "http://localhost/\x00", "http://localhost/\x7f",
    "http://localhost:", "http://localhost:0", "http://localhost:65536", "http://localhost:-1",
    "http://localhost:abc", "http://localhost:８０", "http://[::1]suffix:80/", "http://[::1]:/",
    "http://localhost%3a80/", "http://local%40host/", "http://localhost\\other/",
    "http://bad..host/", "http://-bad/", "http://bad-/", "http://.bad/",
])
def test_fixed_invalid_endpoint_rejected_before_spawn(monkeypatch, endpoint):
    from lunar_evolution import controller_http_transport

    monkeypatch.setattr(controller_http_transport, "Popen", lambda *_a, **_kw: pytest.fail("invalid endpoint spawn"))
    with pytest.raises(ValueError, match="fixed_http_endpoint_invalid"):
        http_transport._validate_fixed_destination_endpoint(endpoint)
    with pytest.raises(ValueError):
        ControllerHttpTransport(fixed_destination=True).start(admission(), request(endpoint))


@pytest.mark.parametrize("endpoint", ["http://user:inert@localhost/", "http://localhost/#inert"])
def test_generic_broker_dto_retains_historical_light_validation(endpoint):
    # The generic DTO preserves its historical light validation and lets the
    # execution layer return broker_endpoint_invalid. Fixed mode validates
    # immediately before worker spawn.
    ProducerBrokerConfig(endpoint, {})


@pytest.mark.parametrize("endpoint", [
    "http://localhost", "https://localhost:443/post?item=one", "http://127.0.0.1:80/",
    "http://[::1]:8080/", "https://example.test./", "https://例子.test/", "https://İ.test:443/",
])
def test_fixed_endpoint_accepts_valid_http_authorities(endpoint):
    http_transport._validate_fixed_destination_endpoint(endpoint)


@pytest.mark.parametrize("endpoint", ["http://inert@127.0.0.1:1/", "http://127.0.0.1:1/#inert"])
def test_broker_invalid_endpoint_refused_before_journal_ready_or_http_spawn(tmp_path, monkeypatch, endpoint):
    from lunar_evolution import controller_http_transport
    from lunar_evolution.producer_broker_ipc import ProducerBrokerIpcError

    _, intent = _intent(tmp_path)
    config = ProducerBrokerConfig(endpoint, {})
    ready = threading.Event()
    journal = tmp_path / "invalid-endpoint-journal"
    monkeypatch.setattr(controller_http_transport, "Popen", lambda *_a, **_kw: pytest.fail("invalid endpoint spawn"))
    with pytest.raises(ProducerBrokerIpcError, match="producer_broker_endpoint_invalid"):
        serve_producer_broker(
            -1, -1, intent=intent, journal_dir=journal, config=config,
            deadline_ns=time.monotonic_ns() + 2_000_000_000, ready=ready,
        )
    assert not ready.is_set() and not journal.exists()


@pytest.mark.parametrize("endpoint", ["http://inert@127.0.0.1:1/", "http://127.0.0.1:1/#inert"])
def test_native_invalid_endpoint_refused_before_budget_nonce_inputs_or_spawn(tmp_path, monkeypatch, endpoint):
    from test_native_trusted_attempt import _attempt

    from lunar_evolution import native_trusted_attempt as native

    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path)
    before = sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*"))

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid broker endpoint must be rejected before native effects")

    for name in ("_compose_attempt_budget", "_native_launch_inputs", "_observe_cancellation",
                 "consume_trusted_bootstrap_attestation"):
        monkeypatch.setattr(native, name, forbidden)
    monkeypatch.setattr(native.subprocess, "Popen", forbidden)
    with pytest.raises(native.NativeTrustedAttemptError, match="native_trusted_attempt_broker_endpoint_invalid"):
        native.run_native_trusted_attempt(
            workspace=workspace, producer_root=producer, intent=intent,
            attestation=attestation, artifact=artifact,
            broker_config=ProducerBrokerConfig(endpoint, {}),
        )
    assert sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*")) == before
    assert not (batch / "native-trusted-deadline.json").exists()


def raw_worker(config, endpoint):
    deadline = time.monotonic() + 2
    payload = {"endpoint": endpoint, "method": "POST", "headers": {}, "body": "",
               "timeout": 2, "deadline": deadline, "configuration": config}
    reader, writer = os.pipe()
    process = None
    try:
        process = subprocess.Popen(http_transport._worker_command(reader), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={}, close_fds=True,
                                   pass_fds=(reader,))
        os.close(reader)
        reader = None
        output, error = process.communicate(json.dumps(payload).encode(), timeout=3)
        return process.returncode, output, error
    finally:
        if reader is not None:
            os.close(reader)
        os.close(writer)
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                if not stream.closed:
                    stream.close()


@pytest.mark.parametrize("changes", [
    {"policy": None}, {"policy": False}, {"policy": []}, {"policy": {}},
    {"policy": "unknown"}, {"policy": "fixed-direct-no-redirect-v2"},
    {"proxy_source": "environment"}, {"proxy_source": "system"},
    {"proxies": {"http": "http://127.0.0.1:1"}}, {"extra": "inert"},
    {"trust": {"unexpected": "inert"}}, {"policy": 1},
])
def test_worker_unknown_or_inconsistent_fixed_policy_fails_before_network(changes):
    config = {"policy": "fixed-direct-no-redirect-v1", "proxy_source": "direct", "proxies": {}, "trust": {}}
    config.update(changes)
    with loopback() as (origin, calls, _):
        assert raw_worker(config, origin) == (70, b"", b"")
        assert calls == []


def test_worker_missing_policy_never_accepts_direct_configuration():
    with loopback() as (origin, calls, _):
        assert raw_worker({"proxy_source": "direct", "proxies": {}, "trust": {}}, origin) == (70, b"", b"")
        assert calls == []


@pytest.mark.parametrize("suffix", ["#", "/bad\npath"])
def test_worker_revalidates_fixed_endpoint_before_network(suffix):
    config = {"policy": "fixed-direct-no-redirect-v1", "proxy_source": "direct", "proxies": {}, "trust": {}}
    with loopback() as (origin, calls, _):
        assert raw_worker(config, origin + suffix) == (70, b"", b"")
        assert calls == []


@pytest.mark.parametrize("trusted", [False, True], ids=["untrusted", "trusted"])
def test_fixed_https_preserves_projected_tls_trust(monkeypatch, destination_certificate, trusted):
    certificate, key, _directory = destination_certificate
    project_trust(monkeypatch, certificate if trusted else None)
    processes, _ = record_processes(monkeypatch)
    with local_https(certificate, key) as (origin, calls):
        handle = ControllerHttpTransport(fixed_destination=True).start(admission(), request(origin))
        assert handle.wait(2) == ("completed" if trusted else "failed")
        assert calls == (["/chat/completions"] if trusted else [])
        if trusted:
            assert handle.result().status == 200
        else:
            assert handle.failure.reason == "transport_error"
    assert_reaped(processes)


def test_slow_fixed_3xx_body_keeps_original_deadline_and_exact_reap(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    with loopback() as (trap, trap_calls, _), \
            loopback(status=302, location=trap, body=b"slow-error" * 1000, slow=True) as (origin, calls, _):
        began = time.monotonic()
        handle = ControllerHttpTransport(fixed_destination=True).start(admission(0.2), request(origin))
        assert handle.wait(2) is None
        assert handle.cancel() is True
        assert time.monotonic() - began < 0.8
        assert len(calls) == 1 and trap_calls == []
    assert_reaped(processes)


def test_fixed_active_request_cancellation_preserves_broker_accounting(monkeypatch):
    processes, _ = record_processes(monkeypatch)
    with loopback(block_headers=True) as (origin, calls, received):
        ledger = HostRequestLedger(request_timeout_seconds=2, max_requests=1)
        result = ControllerOwnedRequestBroker(ledger, ControllerHttpTransport(fixed_destination=True)).execute(
            "local-request", request(origin), cancelled=received.is_set,
        )
        assert result.event.status == "cancelled"
        assert result.cancellation_acknowledged and not result.host_timeout_enforced
        assert result.response is None and len(calls) == 1
    assert_reaped(processes)


@pytest.mark.parametrize("status", [200, 302])
def test_actual_producer_pipe_broker_selects_fixed_destination(tmp_path, monkeypatch, status):
    _, intent = _intent(tmp_path)
    processes, _ = record_processes(monkeypatch)
    with loopback(body=b"trap") as (proxy, proxy_calls, _), \
            loopback(body=b"redirect-trap") as (trap, trap_calls, _), \
            loopback(status=status, location=trap, body=b"origin") as (origin, calls, _):
        monkeypatch.setenv("http_proxy", proxy)
        monkeypatch.setenv("no_proxy", "no-bypass.invalid")
        request_read, request_write = os.pipe()
        response_read, response_write = os.pipe()
        try:
            frame = {"protocol": "lunar-producer-broker-ipc-v1", "request_id": "req-1",
                     "body_base64": base64.b64encode(b"inert-request").decode("ascii")}
            os.write(request_write, json.dumps(frame).encode() + b"\n")
            os.close(request_write)
            request_write = None
            observation = serve_producer_broker(
                request_read, response_write, intent=intent, journal_dir=tmp_path / "journal",
                config=ProducerBrokerConfig(origin, {"X-Inert-Fixture": "local-only"}),
                deadline_ns=time.monotonic_ns() + 3_000_000_000,
            )
            response = json.loads(os.read(response_read, 65536))
        finally:
            for fd in (request_read, request_write, response_read, response_write):
                if fd is not None:
                    os.close(fd)
        assert observation.complete and observation.snapshot.admitted_count == 1
        assert [event.status for event in observation.snapshot.events] == ["completed" if status == 200 else "failed"]
        assert set(response) == {"protocol", "request_id", "status", "http_status", "body_base64"}
        assert response["status"] == ("completed" if status == 200 else "failed")
        assert (response["http_status"], response["body_base64"]) == ((200, "b3JpZ2lu") if status == 200 else (None, None))
        assert len(calls) == 1 and calls[0][:3] == ("POST", "/", b"inert-request")
        assert proxy_calls == trap_calls == []
    assert_reaped(processes)
