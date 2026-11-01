"""Exact failed-request fingerprints with deterministic in-memory transports only."""

import copy
import hashlib
import io
import json
from dataclasses import FrozenInstanceError, asdict
from urllib.error import HTTPError, URLError

import pytest

import lunar_evolution.runtime as rt
from lunar_evolution.http_transport import TransportFailure, TransportResponse

SECRET = "REQUEST-FINGERPRINT-PRIVATE-SENTINEL"
ENDPOINT = "http://fixture.invalid/" + SECRET
MESSAGES = [{"role": "user", "content": "月球与调度 " + SECRET}]
TOOLS = ({"type": "function", "function": {"name": "read_file"}},)


def assert_fingerprint(error, body):
    fingerprint = error.request_fingerprint
    assert type(fingerprint) is rt.ModelRequestFingerprint
    assert asdict(fingerprint) == {
        "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
    }
    assert SECRET not in repr(fingerprint) and ENDPOINT not in repr(fingerprint)
    return fingerprint


def chat(content="done", **extra):
    return {"choices": [{"message": {"content": content}}], "model": "fixture", **extra}


class Response:
    def __init__(self, body=b"invalid json", status=200, read_error=None):
        self.body, self.status, self.read_error = body, status, read_error
        self.reads = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return self.status

    def read(self, maximum):
        self.reads.append(maximum)
        if self.read_error is not None:
            raise self.read_error
        return self.body


@pytest.mark.parametrize("response,reason", [
    (b"invalid json", "invalid_json"),
    (json.dumps(chat(None)).encode(), "empty_response"),
    (json.dumps({"choices": [{"message": {"content": None, "tool_calls": "bad"}}]}).encode(),
     "invalid_tool_calls"),
    (json.dumps(chat(model=42)).encode(), "invalid_model_identity"),
    (json.dumps(chat(usage=[])).encode(), "invalid_usage"),
])
def test_bounded_validation_failure_hashes_actual_unicode_request_without_wire_changes(
    monkeypatch, response, reason,
):
    calls = []

    def exchange(request, timeout):
        calls.append((request, timeout))
        return TransportResponse(200, response)

    monkeypatch.setattr(rt, "exchange", exchange)
    messages, tools = copy.deepcopy(MESSAGES), copy.deepcopy(TOOLS)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime(ENDPOINT, "fixture", SECRET).complete(
            messages, tools, timeout=1.2349,
        )
    assert len(calls) == 1 and calls[0][1] == 1.2349
    request = calls[0][0]
    assert json.loads(request.data) == {
        "model": "fixture", "messages": MESSAGES, "stream": False, "tools": list(TOOLS),
    }
    assert messages == MESSAGES and tools == TOOLS
    assert "月球".encode() in request.data
    assert request.get_header("Authorization") == "Bearer " + SECRET
    assert caught.value.evidence.reason == reason
    assert_fingerprint(caught.value, request.data)


@pytest.mark.parametrize("failure", [
    TransportFailure("open_response", "transport_timeout", None, "timeout"),
    TransportFailure("open_response", "transport_error", None, "url_error"),
    TransportFailure("read_http_error_body", "http_error", 503, "http_error", SECRET.encode()),
])
def test_bounded_transport_failure_preserves_classification_and_one_dispatch(monkeypatch, failure):
    calls = []

    def exchange(request, timeout):
        calls.append((request.data, timeout))
        raise failure

    monkeypatch.setattr(rt, "exchange", exchange)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime(ENDPOINT, "fixture", SECRET).complete(MESSAGES, timeout=2)
    assert len(calls) == 1 and calls[0][1] == 2
    assert caught.value.evidence.reason == failure.reason
    assert caught.value.evidence.response_status == failure.status
    assert caught.value.__cause__ is not None
    assert_fingerprint(caught.value, calls[0][0])


@pytest.mark.parametrize("at_body", [False, True])
@pytest.mark.parametrize("cause_type", [TimeoutError, URLError, OSError])
def test_direct_transport_failure_retains_original_cause_and_timeout(
    monkeypatch, at_body, cause_type,
):
    cause = cause_type(SECRET)
    response = Response(read_error=cause)
    calls = []

    def open_response(request, *, timeout):
        calls.append((request.data, timeout))
        if not at_body:
            raise cause
        return response

    monkeypatch.setattr(rt, "urlopen", open_response)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime(ENDPOINT, "fixture", SECRET)._complete_direct(
            MESSAGES, TOOLS, timeout=1.2349,
        )
    assert len(calls) == 1 and calls[0][1] == 1.2349
    assert caught.value.__cause__ is cause
    assert response.reads == ([8 * 1024 * 1024] if at_body else [])
    assert_fingerprint(caught.value, calls[0][0])


def test_direct_http_error_retains_original_error_body_behavior(monkeypatch):
    cause = HTTPError(ENDPOINT, 503, SECRET, {}, io.BytesIO(SECRET.encode()))
    calls = []

    def open_response(request, *, timeout):
        calls.append((request.data, timeout))
        raise cause

    monkeypatch.setattr(rt, "urlopen", open_response)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime(ENDPOINT, "fixture", SECRET)._complete_direct(MESSAGES)
    assert len(calls) == 1 and calls[0][1] is None
    assert caught.value.__cause__ is cause and caught.value.evidence.reason == "http_error"
    assert_fingerprint(caught.value, calls[0][0])


def test_fingerprint_bound_does_not_reject_or_change_direct_dispatch(monkeypatch):
    monkeypatch.setattr(rt, "MAX_REQUEST_BYTES", 1)
    cause = TimeoutError(SECRET)
    calls = []

    def open_response(request, *, timeout):
        calls.append((request.data, timeout))
        raise cause

    monkeypatch.setattr(rt, "urlopen", open_response)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime(ENDPOINT, "fixture", SECRET)._complete_direct(
            MESSAGES, TOOLS, timeout=1.2349,
        )
    assert len(calls) == 1 and len(calls[0][0]) > rt.MAX_REQUEST_BYTES
    assert calls[0][1] == 1.2349
    assert caught.value.__cause__ is cause
    assert caught.value.evidence.reason == "transport_timeout"
    assert caught.value.request_fingerprint is None


@pytest.mark.parametrize("clock_failure", ["missing_start", "invalid_start", "projection_error"])
def test_invalid_optional_timing_does_not_suppress_fingerprint(monkeypatch, clock_failure):
    calls = []

    def exchange(request, timeout):
        calls.append(request.data)
        raise TransportFailure("open_response", "transport_timeout", None, "timeout")

    monkeypatch.setattr(rt, "exchange", exchange)
    if clock_failure == "projection_error":
        def broken(*args):
            raise OSError(SECRET)
        monkeypatch.setattr(rt, "_request_observation", broken)
    else:
        monkeypatch.setattr(rt, "_request_clock", lambda: None if clock_failure == "missing_start" else float("nan"))
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime(ENDPOINT, "fixture", SECRET).complete(MESSAGES, timeout=2)
    assert caught.value.observation is None
    assert len(calls) == 1
    assert_fingerprint(caught.value, calls[0])


@pytest.mark.parametrize("fault", ["hash", "constructor"])
def test_optional_fingerprint_failure_preserves_same_failure_and_cause(monkeypatch, fault):
    cause = OSError(SECRET)
    original = rt.ModelRequestFailure("fixed failure", "invalid_json", 200)
    original.__cause__ = cause

    def fail_projection(*args):
        raise OSError(SECRET)

    if fault == "hash":
        monkeypatch.setattr(rt, "_request_fingerprint", fail_projection)
    else:
        monkeypatch.setattr(rt, "ModelRequestFingerprint", fail_projection)

    def exchange(request, timeout):
        raise original

    monkeypatch.setattr(rt, "exchange", exchange)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime(ENDPOINT, "fixture", SECRET).complete(MESSAGES, timeout=2)
    assert caught.value is original and caught.value.__cause__ is cause
    assert caught.value.request_fingerprint is None


def test_current_failure_does_not_reuse_a_previous_fingerprint_when_projection_fails(monkeypatch):
    original = rt.ModelRequestFailure("fixed failure", "transport_error")
    original.request_fingerprint = rt.ModelRequestFingerprint(1, "0" * 64)

    def exchange(request, timeout):
        raise original

    def fail_projection(*args):
        raise ValueError("unavailable")

    monkeypatch.setattr(rt, "exchange", exchange)
    monkeypatch.setattr(rt, "_request_fingerprint", fail_projection)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime(ENDPOINT, "fixture").complete(MESSAGES, timeout=2)
    assert caught.value is original and original.request_fingerprint is None


@pytest.mark.parametrize("bounded", [False, True])
def test_success_never_computes_fingerprint_or_changes_result(monkeypatch, bounded):
    calls = []
    body = json.dumps(chat()).encode()

    def exchange(request, timeout):
        calls.append((request.data, timeout))
        return TransportResponse(200, body)

    def open_response(request, *, timeout):
        calls.append((request.data, timeout))
        return Response(body)

    def forbidden(*args):
        pytest.fail("successful requests must not compute a failure fingerprint")

    monkeypatch.setattr(rt, "exchange", exchange)
    monkeypatch.setattr(rt, "urlopen", open_response)
    monkeypatch.setattr(rt, "_request_fingerprint", forbidden)
    runtime = rt.OpenAICompatibleRuntime(ENDPOINT, "fixture", SECRET)
    result = runtime.complete(MESSAGES, TOOLS, timeout=2) if bounded else runtime._complete_direct(MESSAGES, TOOLS)
    assert result == rt.ModelTurn("done", response_model="fixture")
    assert len(calls) == 1 and calls[0][1] == (2 if bounded else None)
    assert not hasattr(runtime, "request_fingerprint")


def test_distinct_failed_messages_keep_per_request_fingerprints(monkeypatch):
    calls = []

    def exchange(request, timeout):
        calls.append(request.data)
        return TransportResponse(200, b"bad json")

    monkeypatch.setattr(rt, "exchange", exchange)
    runtime = rt.OpenAICompatibleRuntime(ENDPOINT, "fixture")
    failures = []
    for message in ("first", "second"):
        with pytest.raises(rt.ModelRequestFailure) as caught:
            runtime.complete([{"role": "user", "content": message}], timeout=2)
        failures.append(caught.value)
    assert len(calls) == 2
    first = assert_fingerprint(failures[0], calls[0])
    second = assert_fingerprint(failures[1], calls[1])
    assert first != second
    assert failures[0].request_fingerprint is first


def test_manual_and_foreign_failures_do_not_gain_automatic_fingerprints(monkeypatch):
    assert rt.ModelRequestFailure("manual", "transport_error").request_fingerprint is None

    class ForeignFailure(rt.ModelRequestFailure):
        pass

    original = ForeignFailure("foreign", "transport_error")

    def exchange(request, timeout):
        raise original

    def forbidden(*args):
        pytest.fail("foreign failure nodes must retain their existing boundary")

    monkeypatch.setattr(rt, "exchange", exchange)
    monkeypatch.setattr(rt, "_request_fingerprint", forbidden)
    with pytest.raises(ForeignFailure) as caught:
        rt.OpenAICompatibleRuntime(ENDPOINT, "fixture").complete(MESSAGES, timeout=2)
    assert caught.value is original and original.request_fingerprint is None


def test_fingerprint_is_frozen_and_helper_preserves_exact_bound(monkeypatch):
    assert rt.MAX_REQUEST_BYTES == 64 * 1024 * 1024
    monkeypatch.setattr(rt, "MAX_REQUEST_BYTES", 4)
    for body in (b"a", b"abcd"):
        fingerprint = rt._request_fingerprint(body)
        assert fingerprint == rt.ModelRequestFingerprint(len(body), hashlib.sha256(body).hexdigest())
        with pytest.raises(FrozenInstanceError):
            fingerprint.body_bytes = 2
    for body in (b"", b"abcde", "abcd", bytearray(b"a"), None):
        assert rt._request_fingerprint(body) is None
