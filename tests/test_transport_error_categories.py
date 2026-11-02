"""Fixed transport categories across real loopback I/O, IPC and private logs."""

import base64
import errno
import http.client
import json
import logging
import socket
import socketserver
import ssl
import struct
import sys
import threading
from contextlib import contextmanager
from urllib.error import HTTPError, URLError

import pytest
from test_http_transport_deadline import (
    assert_closed,
    clear_proxy_environment,
    frames,
    spy_processes,
    success_frames,
)
from test_model_failure_evidence import observer_payload

import lunar_evolution.http_transport as transport
import lunar_evolution.model_request_logging as logs
from lunar_evolution import runtime

PRIVATE = "TRANSPORT-CATEGORY-PRIVATE-EXCEPTION"
ENDPOINT = "TRANSPORT-CATEGORY-PRIVATE-ENDPOINT"
API_KEY = "TRANSPORT-CATEGORY-PRIVATE-KEY"
MODEL = "TRANSPORT-CATEGORY-PRIVATE-MODEL"
PROMPT = "TRANSPORT-CATEGORY-PRIVATE-PROMPT"
TOOL = "TRANSPORT-CATEGORY-PRIVATE-TOOL"


@pytest.fixture(autouse=True)
def isolate_proxies(monkeypatch):
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def category(name):
    return getattr(transport.TransportErrorCategory, name)


def log_records(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records
            if record.name == logs.LOGGER_NAME]


def assert_private(values):
    encoded = json.dumps(values)
    for secret in (PRIVATE, ENDPOINT, API_KEY, MODEL, PROMPT, TOOL):
        assert secret not in encoded


@pytest.mark.parametrize("factory,name", [
    (http.client.RemoteDisconnected, "PEER_CLOSED"),
    (ConnectionResetError, "CONNECTION_RESET"),
    (ConnectionRefusedError, "CONNECTION_REFUSED"),
    (ConnectionAbortedError, "CONNECTION_ABORTED"),
    (BrokenPipeError, "BROKEN_PIPE"),
    (socket.gaierror, "DNS_ERROR"),
    (ssl.SSLError, "TLS_ERROR"),
    (ssl.SSLCertVerificationError, "TLS_ERROR"),
    (TimeoutError, "TIMEOUT"),
    (OSError, "OS_ERROR"),
])
@pytest.mark.parametrize("wrapped", [False, True])
def test_known_exception_types_survive_concrete_url_wrapping(factory, name, wrapped):
    error = factory(PRIVATE)
    if wrapped:
        error = URLError(error)
    observed = transport.classify_transport_error(error)
    assert observed is category(name)
    assert type(observed) is transport.TransportErrorCategory
    assert PRIVATE not in observed.value


@pytest.mark.parametrize("error", [
    URLError("connection reset timeout TLS " + PRIVATE),
    ValueError(PRIVATE),
    RuntimeError(PRIVATE),
    HTTPError("http://fixture.invalid/" + ENDPOINT, 503, PRIVATE, {}, None),
])
def test_strings_and_nontransport_errors_do_not_invent_categories(error):
    error.__context__ = ConnectionResetError(PRIVATE)
    assert transport.classify_transport_error(error) is None


def test_generic_os_fallback_waits_for_specific_cause_and_ignores_context():
    outer = OSError(PRIVATE)
    outer.__cause__ = URLError(socket.gaierror(PRIVATE))
    outer.__context__ = TimeoutError(PRIVATE)
    assert transport.classify_transport_error(outer) is category("DNS_ERROR")
    # Numeric errno alone is not an exception subtype or remote root cause.
    generic = OSError()
    generic.errno = errno.ECONNRESET
    assert type(generic) is OSError
    assert transport.classify_transport_error(generic) is category("OS_ERROR")


def test_url_reason_has_priority_over_cause_without_reclassifying_http_errors():
    error = URLError(socket.gaierror(PRIVATE))
    error.__cause__ = TimeoutError(PRIVATE)
    assert transport.classify_transport_error(error) is category("DNS_ERROR")
    http_error = HTTPError("http://fixture.invalid", 503, PRIVATE, {}, None)
    http_error.__cause__ = ConnectionResetError(PRIVATE)
    assert transport.classify_transport_error(http_error) is None


@pytest.mark.parametrize("layers,expected", [(7, "CONNECTION_RESET"), (8, None)])
def test_category_walk_has_an_eight_exception_bound(layers, expected):
    error = ConnectionResetError(PRIVATE)
    for _ in range(layers):
        outer = RuntimeError(PRIVATE)
        outer.__cause__ = error
        error = outer
    assert transport.classify_transport_error(error) is (
        category(expected) if expected is not None else None
    )


def test_cycle_and_unreadable_exception_metadata_never_escape_classifier():
    first, second = RuntimeError(PRIVATE), OSError(PRIVATE)
    first.__cause__, second.__cause__ = second, first
    assert transport.classify_transport_error(first) is category("OS_ERROR")

    class Unreadable(RuntimeError):
        def __getattribute__(self, name):
            if name == "__cause__":
                raise RuntimeError(PRIVATE)
            return super().__getattribute__(name)

    assert transport.classify_transport_error(Unreadable(PRIVATE)) is None


def failure_frames(*, cause="os_error", reason="transport_error", **extra):
    return [success_frames()[0], {
        "kind": "terminal", "outcome": "failure", "reason": reason,
        "cause": cause, "status": None, "body": "", **extra,
    }]


@pytest.mark.parametrize("cause,reason", [
    ("timeout", "transport_timeout"), ("url_timeout", "transport_timeout"),
    ("opaque_timeout", "transport_timeout"), ("cause_timeout", "transport_error"),
    ("url_error", "transport_error"), ("os_error", "transport_error"),
    ("local_error", "transport_error"), ("http_error", "http_error"),
])
def test_every_historical_failure_frame_keeps_its_exact_projection(cause, reason):
    values = failure_frames(cause=cause, reason=reason)
    if cause == "http_error":
        values.insert(1, {"kind": "phase", "phase": "read_http_error_body", "status": 503})
        values[-1].update(status=503, body=base64.b64encode(b"legacy body").decode())
    original = frames(*values)
    with pytest.raises(transport.TransportFailure) as caught:
        transport._decode_result(original)
    error = caught.value
    assert (error.reason, error.cause) == (reason, cause)
    assert error.transport_error_category is None
    assert error.observation is None
    assert error.status == (503 if cause == "http_error" else None)
    assert error.body == (b"legacy body" if cause == "http_error" else b"")


@pytest.mark.parametrize("name", [
    "PEER_CLOSED", "CONNECTION_RESET", "CONNECTION_REFUSED", "CONNECTION_ABORTED",
    "BROKEN_PIPE", "DNS_ERROR", "TLS_ERROR", "TIMEOUT", "OS_ERROR",
])
def test_new_fixed_terminal_category_crosses_ipc_without_replacing_legacy_reason(name):
    expected = category(name)
    raw = frames(*failure_frames(transport_error_category=expected.value))
    with pytest.raises(transport.TransportFailure) as caught:
        transport._decode_result(raw)
    assert caught.value.transport_error_category is expected
    assert caught.value.reason == "transport_error" and caught.value.cause == "os_error"
    assert caught.value.phase == "open_response" and caught.value.status is None


@pytest.mark.parametrize("mutation", [
    "null", "unknown", "bool", "number", "object", "list", "extra",
    "missing_cause", "duplicate", "success", "http_error",
])
def test_malformed_or_inapplicable_category_frames_cannot_be_accepted(mutation):
    values = failure_frames(transport_error_category="connection_reset")
    if mutation in {"null", "unknown", "bool", "number", "object", "list"}:
        values[-1]["transport_error_category"] = {
            "null": None, "unknown": PRIVATE, "bool": True, "number": 1,
            "object": {"exception": PRIVATE}, "list": [PRIVATE],
        }[mutation]
    elif mutation == "extra":
        values[-1]["exception_text"] = PRIVATE
    elif mutation == "missing_cause":
        del values[-1]["cause"]
    elif mutation == "success":
        values = success_frames()
        values[-1]["transport_error_category"] = "connection_reset"
    elif mutation == "http_error":
        values.insert(1, {"kind": "phase", "phase": "read_http_error_body", "status": 503})
        values[-1].update(cause="http_error", reason="http_error", status=503)
    raw = frames(*values)
    if mutation == "duplicate":
        raw = raw.replace(b'"transport_error_category": "connection_reset"',
                          b'"transport_error_category":"connection_reset",'
                          b'"transport_error_category":"dns_error"')
    with pytest.raises(ValueError):
        transport._decode_result(raw)


def test_legacy_success_and_supervisor_deadline_have_no_inferred_category():
    response = transport._decode_result(frames(*success_frames()))
    assert response == transport.TransportResponse(200, b"{}")
    error = transport._deadline_failure(frames(success_frames()[0]))
    assert error.reason == "transport_timeout" and error.transport_error_category is None
    assert runtime.ModelRequestFailure(PRIVATE, "transport_error").transport_error_category is None


@pytest.mark.parametrize("invalid", ["connection_reset", True, 1, {"category": PRIVATE}])
def test_transport_failure_rejects_non_enum_metadata(invalid):
    with pytest.raises(ValueError):
        transport.TransportFailure(transport_error_category=invalid)


@contextmanager
def local_ending_server(mode):
    """Read the full POST before an intentional FIN or RST, never send headers."""
    calls, failures = [], []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                self.request.settimeout(3)
                raw = b""
                while b"\r\n\r\n" not in raw:
                    chunk = self.request.recv(4096)
                    if not chunk:
                        raise AssertionError("fixture request ended before complete headers")
                    raw += chunk
                    if len(raw) > 65536:
                        raise AssertionError("fixture headers too large")
                headers, body = raw.split(b"\r\n\r\n", 1)
                lines = headers.decode("iso-8859-1").split("\r\n")
                fields = dict(line.split(": ", 1) for line in lines[1:])
                length = int(next(value for key, value in fields.items()
                                  if key.lower() == "content-length"))
                while len(body) < length:
                    chunk = self.request.recv(length - len(body))
                    if not chunk:
                        raise AssertionError("fixture request ended before complete body")
                    body += chunk
                calls.append((lines[0], fields, body))
                if mode == "reset":
                    self.request.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                            struct.pack("ii", 1, 0))
                    self.request.close()
                else:
                    self.request.shutdown(socket.SHUT_WR)
            except Exception as error:  # noqa: BLE001 - fixture failures are surfaced below
                failures.append(type(error).__name__)

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}/{ENDPOINT}", calls
        finally:
            server.shutdown()
            thread.join(timeout=2)
            assert not thread.is_alive()
            assert not failures


def invoke_model(endpoint, *, bounded, timeout=3):
    model = runtime.OpenAICompatibleRuntime(endpoint, MODEL, API_KEY)
    messages = [{"role": "user", "content": PROMPT}]
    tools = ({"type": "function", "function": {"name": "fixture", "description": TOOL}},)
    invoke = model.complete if bounded else model._complete_direct
    with pytest.raises(runtime.ModelRequestFailure) as caught:
        invoke(messages, tools, timeout=timeout)
    return caught.value, {"model": MODEL, "messages": messages, "stream": False,
                          "tools": list(tools)}


@pytest.mark.parametrize("bounded", [False, True])
@pytest.mark.parametrize("mode,name", [("close", "PEER_CLOSED"), ("reset", "CONNECTION_RESET")])
def test_real_peer_close_and_reset_keep_one_exact_post_and_private_failed_log(
    tmp_path, monkeypatch, caplog, bounded, mode, name,
):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    processes, _ = spy_processes(monkeypatch)
    with local_ending_server(mode) as (endpoint, calls):
        error, expected = invoke_model(endpoint, bounded=bounded)
    assert len(calls) == 1
    request_line, headers, body = calls[0]
    assert request_line == f"POST /{ENDPOINT}/chat/completions HTTP/1.1"
    assert json.loads(body) == expected
    assert body == json.dumps(expected, ensure_ascii=False).encode("utf-8")
    assert headers["Authorization"] == "Bearer " + API_KEY
    assert headers["Content-Length"] == str(len(body))
    assert error.transport_error_category is category(name)
    assert error.evidence == runtime.ModelFailureEvidence("transport_error", None)
    assert error.observation.phase == "open_response"
    if bounded:
        assert len(processes) == 1
        assert_closed(processes)
        assert error.transport_observation.last_milestone == "wait_response_headers"
    else:
        assert not processes and error.transport_observation is None
    payload = observer_payload(tmp_path, error)
    original_category = error.transport_error_category
    error.transport_error_category = None
    assert observer_payload(tmp_path, error) == payload
    error.transport_error_category = original_category
    assert payload["schema_version"] == "7"
    assert payload["code"] == "model_failed"
    assert "transport_error_category" not in payload
    assert not (tmp_path / "receipt.json").exists()
    events = log_records(caplog)
    assert [event["event"] for event in events] == [
        "model_request_started", "model_request_failed",
    ]
    assert events[-1]["transport_error_category"] == category(name).value
    assert events[-1]["reason"] == "transport_error"
    assert events[-1]["request_timeout_ms"] == 3000
    assert len({event["request_id"] for event in events}) == 1
    assert_private([events, payload])


@pytest.mark.parametrize("bounded", [False, True])
def test_real_nonlistener_preserves_kernel_refusal_or_darwin_timeout(monkeypatch, caplog, bounded):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    processes, _ = spy_processes(monkeypatch)
    # Keep the port reserved throughout; there is no close/rebind allocation race.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
        reserved.bind(("127.0.0.1", 0))
        endpoint = f"http://127.0.0.1:{reserved.getsockname()[1]}/{ENDPOINT}"
        error, _ = invoke_model(endpoint, bounded=bounded, timeout=0.6)
    if sys.platform == "darwin":
        # Darwin drops SYNs to a bound, non-listening socket. Observe its real
        # timeout; the supervisor must not invent a ConnectionRefusedError.
        assert error.evidence == runtime.ModelFailureEvidence("transport_timeout", None)
        assert error.transport_error_category in (
            (None, category("TIMEOUT")) if bounded else (category("TIMEOUT"),)
        )
    else:
        assert error.transport_error_category is category("CONNECTION_REFUSED")
        assert error.evidence == runtime.ModelFailureEvidence("transport_error", None)
    assert error.observation.phase == "open_response"
    if bounded:
        assert len(processes) == 1
        assert_closed(processes)
        assert error.transport_observation.last_milestone == "connect"
    else:
        assert not processes
    events = log_records(caplog)
    assert [event["event"] for event in events] == [
        "model_request_started", "model_request_failed",
    ]
    if error.transport_error_category is None:
        assert "transport_error_category" not in events[-1]
    else:
        assert events[-1]["transport_error_category"] == error.transport_error_category.value
    assert events[-1]["reason"] == error.evidence.reason
    assert events[-1]["request_timeout_ms"] == 600
    assert_private(events)


@pytest.mark.parametrize("factory,name", [(socket.gaierror, "DNS_ERROR"),
                                          (ssl.SSLError, "TLS_ERROR")])
@pytest.mark.parametrize("bounded", [False, True])
def test_synthetic_dns_and_tls_survive_runtime_and_opt_in_log(
    monkeypatch, caplog, factory, name, bounded,
):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    calls = []
    original = URLError(factory(PRIVATE))

    def fail(*args, **kwargs):
        calls.append((args, kwargs))
        if bounded:
            raise transport.TransportFailure(
                cause="url_error", transport_error_category=category(name),
            )
        raise original

    monkeypatch.setattr(runtime, "exchange" if bounded else "urlopen", fail)
    error, _ = invoke_model("http://fixture.invalid/" + ENDPOINT, bounded=bounded)
    assert len(calls) == 1
    assert error.transport_error_category is category(name)
    assert error.evidence.reason == "transport_error"
    if not bounded:
        assert error.__cause__ is original
    assert log_records(caplog)[-1]["transport_error_category"] == category(name).value
    assert_private(log_records(caplog))


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("bounded", [False, True])
def test_synthetic_refusal_preserves_concrete_and_url_error_paths(
    monkeypatch, caplog, wrapped, bounded,
):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    calls = []
    original = ConnectionRefusedError(PRIVATE)
    if wrapped:
        original = URLError(original)

    def fail(*args, **kwargs):
        calls.append((args, kwargs))
        if bounded:
            raise transport.TransportFailure(
                cause="url_error" if wrapped else "os_error",
                transport_error_category=category("CONNECTION_REFUSED"),
            )
        raise original

    monkeypatch.setattr(runtime, "exchange" if bounded else "urlopen", fail)
    error, _ = invoke_model("http://fixture.invalid/" + ENDPOINT, bounded=bounded)
    assert len(calls) == 1
    assert error.transport_error_category is category("CONNECTION_REFUSED")
    assert error.evidence == runtime.ModelFailureEvidence("transport_error", None)
    if not bounded:
        assert error.__cause__ is original
    events = log_records(caplog)
    assert [event["event"] for event in events] == [
        "model_request_started", "model_request_failed",
    ]
    assert events[-1]["transport_error_category"] == "connection_refused"
    assert_private(events)


@pytest.mark.parametrize("mutation", [
    "missing", "null", "string", "bool", "mapping", "hostile_string",
    "property", "foreign_failure", "foreign_evidence", "nontransport_reason",
])
def test_malformed_category_omits_only_optional_log_detail(monkeypatch, caplog, mutation):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    error = runtime.ModelRequestFailure(PRIVATE, "transport_error")
    error.transport_error_category = category("CONNECTION_RESET")
    if mutation == "missing":
        del error.transport_error_category
    elif mutation in {"null", "string", "bool", "mapping"}:
        error.transport_error_category = {
            "null": None, "string": "connection_reset", "bool": True,
            "mapping": {"category": PRIVATE},
        }[mutation]
    elif mutation == "hostile_string":
        class Hostile(str):
            def __eq__(self, _other):
                return True

            def __hash__(self):
                return hash("connection_reset")

        error.transport_error_category = Hostile(PRIVATE)
    elif mutation == "property":
        def unreadable(_self):
            raise RuntimeError(PRIVATE)

        monkeypatch.setattr(runtime.ModelRequestFailure, "transport_error_category",
                            property(unreadable), raising=False)
    elif mutation == "foreign_failure":
        class Foreign(runtime.ModelRequestFailure):
            pass

        error.__class__ = Foreign
    elif mutation == "foreign_evidence":
        class ForeignEvidence(runtime.ModelFailureEvidence):
            pass

        error.evidence = ForeignEvidence("transport_error", None)
    else:
        error.evidence = runtime.ModelFailureEvidence("invalid_json", 200)
    log = logs.ModelRequestLog(timeout=1, bounded=True)
    log.finish("failed", failure=error)
    events = log_records(caplog)
    assert [event["event"] for event in events] == [
        "model_request_started", "model_request_failed",
    ]
    assert "transport_error_category" not in events[-1]
    assert events[-1]["reason"] == (
        "local_error" if mutation in {"foreign_failure", "foreign_evidence"}
        else "invalid_json" if mutation == "nontransport_reason" else "transport_error"
    )
    assert_private(events)
