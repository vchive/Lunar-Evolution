"""Failed-request phase/timing evidence without changing HTTP or result authority."""

import io
import json
from dataclasses import FrozenInstanceError, replace
from urllib.error import HTTPError, URLError

import pytest
from test_model_failure_evidence import SECRET, chat, local_model, observer_payload

import lunar_evolution.runtime as rt
from lunar_evolution.subject_diagnostics import normalize_diagnostic


class Response:
    def __init__(self, raw=b"bad json", status=200, read_error=None, close_error=None):
        self.raw, self.status = raw, status
        self.read_error, self.close_error = read_error, close_error
        self.reads = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.close_error is not None:
            raise self.close_error
        return False

    def getcode(self):
        return self.status

    def read(self, maximum):
        self.reads.append(maximum)
        if self.read_error is not None:
            raise self.read_error
        return self.raw


def clock(monkeypatch, readings=(10.0, 12.5)):
    iterator = iter(readings)

    def now():
        value = next(iterator)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(rt, "monotonic", now, raising=False)


def invoke(monkeypatch, response=None, open_error=None, timeout=1.2349):
    calls = []

    def open_response(request, *, timeout):
        calls.append((request, timeout))
        if open_error is not None:
            raise open_error
        return response

    monkeypatch.setattr(rt, "urlopen", open_response)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime("http://local.invalid/" + SECRET, "fixture", SECRET)._complete_direct(
            [{"role": "user", "content": SECRET}], timeout=timeout,
        )
    assert len(calls) == 1 and calls[0][1] is timeout
    return caught.value, calls


@pytest.mark.parametrize("at_body", [False, True])
@pytest.mark.parametrize("cause", [TimeoutError(SECRET), URLError(TimeoutError(SECRET)), OSError(SECRET)])
def test_transport_phase_timing_and_original_cause(tmp_path, monkeypatch, at_body, cause):
    clock(monkeypatch)
    response = Response(read_error=cause)
    error, _ = invoke(monkeypatch, response, None if at_body else cause)
    assert error.__cause__ is cause
    payload = observer_payload(tmp_path, error)
    assert payload["schema_version"] == "7"
    assert payload["request_observation"] == {
        "phase": "read_response_body" if at_body else "open_response",
        "elapsed_ms": 2500, "request_timeout_ms": 1234,
    }
    assert payload["model_failure"]["response_status"] == (200 if at_body else None)
    assert response.reads == ([8 * 1024 * 1024] if at_body else [])
    assert SECRET not in json.dumps(payload)


@pytest.mark.parametrize("body,reason", [
    (b"\xff", "invalid_json"), (b"bad json", "invalid_json"),
    ([], "invalid_response_shape"), (chat(None), "empty_response"),
    (chat(None, tool_calls="bad"), "invalid_tool_calls"),
    ({**chat(), "model": 42}, "invalid_model_identity"),
    ({**chat(), "usage": []}, "invalid_usage"),
])
def test_loopback_validation_phases_and_timeout_forwarding(tmp_path, monkeypatch, body, reason):
    clock(monkeypatch)
    with local_model((200, body)) as (endpoint, calls), pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime(endpoint, "fixture", SECRET).complete([], timeout=1.2349)
    payload = observer_payload(tmp_path, caught.value)
    assert len(calls) == 1
    assert payload["model_failure"] == {"reason": reason, "response_status": 200}
    assert payload["request_observation"] == {
        "phase": "validate_response", "elapsed_ms": 2500, "request_timeout_ms": 1234,
    }
    assert len(json.dumps(payload).encode()) <= 4096
    assert SECRET not in json.dumps(payload) and endpoint not in json.dumps(payload)


@pytest.mark.parametrize("body_fails", [False, True])
def test_http_error_body_phase_does_not_replace_http_failure(tmp_path, monkeypatch, body_fails):
    clock(monkeypatch)
    reads = []

    class ErrorBody(io.BytesIO):
        def read(self, maximum):
            reads.append(maximum)
            if body_fails:
                raise TimeoutError(SECRET)
            return super().read(maximum)

    cause = HTTPError("http://local.invalid/" + SECRET, 503, SECRET, {}, ErrorBody(SECRET.encode()))
    error, _ = invoke(monkeypatch, open_error=cause)
    payload = observer_payload(tmp_path, error)
    assert error.__cause__ is cause and reads == [2000]
    assert payload["code"] == "model_http_failed" and payload["http_status"] == 503
    assert payload["model_failure"] == {"reason": "http_error", "response_status": 503}
    assert payload["request_observation"]["phase"] == "read_http_error_body"
    assert payload["request_observation"]["elapsed_ms"] == 2500
    assert SECRET not in json.dumps(payload)


def test_explicit_non_2xx_and_cleanup_keep_existing_boundaries(tmp_path, monkeypatch):
    clock(monkeypatch)
    error, _ = invoke(monkeypatch, Response(status=503))
    payload = observer_payload(tmp_path, error)
    assert payload["request_observation"]["phase"] == "validate_response"
    assert payload["http_status"] is None and error.__cause__ is None
    clock(monkeypatch)
    cause = OSError(SECRET)
    error, _ = invoke(monkeypatch, Response(close_error=cause))
    payload = observer_payload(tmp_path, error)
    assert payload["request_observation"]["phase"] == "read_response_body"
    assert error.__cause__ is cause


def test_validation_failure_is_same_object_and_cause_depth(tmp_path, monkeypatch):
    clock(monkeypatch)
    cause = ValueError(SECRET)
    original = rt.ModelRequestFailure("fixed message", "invalid_usage", 200)
    original.__cause__ = cause

    def reject(*args, **kwargs):
        raise original

    monkeypatch.setattr(rt.OpenAICompatibleRuntime, "_extract_turn", reject)
    error, _ = invoke(monkeypatch, Response(raw=b"{}"))
    assert error is original and error.__cause__ is cause and str(error) == "fixed message"
    assert observer_payload(tmp_path, error)["request_observation"]["phase"] == "validate_response"


@pytest.mark.parametrize("timeout,expected", [(None, None), (0.0009, 0), (1, 1000), (10**9, 10**12)])
def test_timeout_projection_none_submillisecond_and_boundary(tmp_path, monkeypatch, timeout, expected):
    clock(monkeypatch, (100.0, 100.0009))
    error, _ = invoke(monkeypatch, Response(), timeout=timeout)
    assert observer_payload(tmp_path, error)["request_observation"] == {
        "phase": "validate_response", "elapsed_ms": 0, "request_timeout_ms": expected,
    }


@pytest.mark.parametrize("timeout", [True, False, 0, -1, "1", float("nan"), float("inf"), 10**400, 10**9 + 1])
def test_invalid_timeout_discards_timing_without_changing_forwarded_value(tmp_path, monkeypatch, timeout):
    clock(monkeypatch)
    error, _ = invoke(monkeypatch, Response(), timeout=timeout)
    payload = observer_payload(tmp_path, error)
    assert payload["schema_version"] == "7" and "request_observation" not in payload
    assert payload["model_failure"] == {"reason": "invalid_json", "response_status": 200}


@pytest.mark.parametrize("readings", [
    (True, 2.0), (1.0, False), ("1", 2.0), (1.0, "2"),
    (float("nan"), 2.0), (1.0, float("nan")), (float("inf"), 2.0), (1.0, float("inf")),
    (2.0, 1.0), (0.0, 10**9 + 1), (10**400, 10**400), (0.0, 1e308), (-1e308, 1e308),
    (RuntimeError(SECRET), 2.0), (1.0, RuntimeError(SECRET)),
])
def test_invalid_clock_never_masks_failure_or_valid_v3(tmp_path, monkeypatch, readings):
    clock(monkeypatch, readings)
    error, _ = invoke(monkeypatch, Response())
    payload = observer_payload(tmp_path, error)
    assert payload["schema_version"] == "7" and "request_observation" not in payload
    assert payload["model_failure"]["reason"] == "invalid_json"
    assert SECRET not in json.dumps(payload)


def timed_error():
    error = rt.ModelRequestFailure(SECRET, "invalid_json", 200)
    error.observation = rt.ModelRequestObservation("validate_response", 17, 1000)
    return error


def test_observation_is_frozen_and_manual_failure_remains_v3(tmp_path):
    error = timed_error()
    with pytest.raises(FrozenInstanceError):
        error.observation.elapsed_ms = 123
    assert observer_payload(tmp_path, error)["schema_version"] == "4"
    manual = rt.ModelRequestFailure("fixed", "invalid_json", 200)
    assert observer_payload(tmp_path, manual)["schema_version"] == "3"


@pytest.mark.parametrize("kind", ["missing", "foreign", "subtype", "phase", "phase_type", "elapsed_bool",
                                 "elapsed_large", "elapsed_negative", "timeout_bool", "timeout_large", "mismatch"])
def test_hostile_observation_falls_back_to_same_valid_v3(tmp_path, kind):
    error = timed_error()
    if kind == "missing":
        del error.observation
    elif kind == "foreign":
        error.observation = {"phase": "validate_response", "elapsed_ms": 1, "body": SECRET}
    elif kind == "subtype":
        class Foreign(rt.ModelRequestObservation):
            pass
        error.observation = Foreign("validate_response", 1, 1000)
    else:
        changes = {"phase": {"phase": SECRET}, "phase_type": {"phase": []},
                   "elapsed_bool": {"elapsed_ms": True}, "elapsed_large": {"elapsed_ms": 10**12 + 1},
                   "elapsed_negative": {"elapsed_ms": -1}, "timeout_bool": {"request_timeout_ms": True},
                   "timeout_large": {"request_timeout_ms": 10**12 + 1}, "mismatch": {"phase": "open_response"}}
        error.observation = replace(error.observation, **changes[kind])
    payload = observer_payload(tmp_path, error)
    assert payload["schema_version"] == "3" and "request_observation" not in payload
    assert payload["model_failure"] == {"reason": "invalid_json", "response_status": 200}
    assert SECRET not in json.dumps(payload)


@pytest.mark.parametrize("outer_valid", [False, True])
def test_observation_never_borrowed_from_different_exception_node(tmp_path, outer_valid):
    inner = timed_error()
    outer = rt.ModelRequestFailure("outer", "invalid_usage", 200)
    if not outer_valid:
        outer.evidence = {"reason": "invalid_usage", "response_status": 200}
    outer.__cause__ = inner
    payload = observer_payload(tmp_path, outer)
    assert payload["schema_version"] == ("3" if outer_valid else "1")
    assert "request_observation" not in payload
    if outer_valid:
        assert payload["model_failure"]["reason"] == "invalid_usage"


@pytest.mark.parametrize("depth", [0, 7, 8])
def test_timing_obeys_existing_eight_node_cause_boundary(tmp_path, depth):
    error = timed_error()
    for _ in range(depth):
        outer = rt.RuntimeExecutionError("fixed")
        outer.__cause__ = error
        error = outer
    payload = observer_payload(tmp_path, error)
    assert payload["schema_version"] == ("4" if depth <= 7 else "1")


@pytest.mark.parametrize("change", [
    {"request_observation": None}, {"request_observation": {}},
    {"request_observation": {"phase": "validate_response", "elapsed_ms": 1, "request_timeout_ms": 1, "body": SECRET}},
    {"request_observation": {"phase": "open_response", "elapsed_ms": 1, "request_timeout_ms": 1}},
    {"request_observation": {"phase": "validate_response", "elapsed_ms": True, "request_timeout_ms": 1}},
    {"request_observation": {"phase": "validate_response", "elapsed_ms": 1, "request_timeout_ms": -1}},
    {"stage": "runtime"}, {"budget": {}}, {"model_failure": None}, {"http_status": 429},
])
def test_v4_reader_is_strict_and_existing_v3_stays_accepted(tmp_path, change):
    legacy = observer_payload(tmp_path, rt.ModelRequestFailure("fixed", "invalid_json", 200))
    payload = {**legacy, "schema_version": "4", "request_observation": {
        "phase": "validate_response", "elapsed_ms": 17, "request_timeout_ms": 1000,
    }}
    assert normalize_diagnostic(payload) == payload
    assert normalize_diagnostic(legacy) == legacy
    with pytest.raises(ValueError):
        normalize_diagnostic({**payload, **change})


def test_failed_observation_construction_preserves_original_failure(tmp_path, monkeypatch):
    clock(monkeypatch)
    real_type = getattr(rt, "ModelRequestObservation", None)

    def fail(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(rt, "ModelRequestObservation", fail, raising=False)
    error, _ = invoke(monkeypatch, Response())
    if real_type is not None:
        monkeypatch.setattr(rt, "ModelRequestObservation", real_type)
    assert observer_payload(tmp_path, error)["schema_version"] == "7"


def test_success_has_identical_wire_fields_and_no_end_clock_or_state(monkeypatch):
    clock(monkeypatch, (10.0, RuntimeError("success must not capture failure time")))
    response = Response(raw=json.dumps(chat("done")).encode())
    calls = []

    def open_response(request, *, timeout):
        calls.append((request, timeout))
        return response

    monkeypatch.setattr(rt, "urlopen", open_response)
    model = rt.OpenAICompatibleRuntime("http://local.invalid", "fixture", SECRET)
    messages = [{"role": "user", "content": "hello"}]
    tool = {"type": "function", "function": {"name": "read_file"}}
    assert model._complete_direct(messages, (tool,), timeout=1.2349) == rt.ModelTurn("done")
    request, timeout = calls[0]
    assert len(calls) == 1 and timeout == 1.2349
    assert response.reads == [8 * 1024 * 1024]
    assert json.loads(request.data) == {"model": "fixture", "messages": messages, "stream": False, "tools": [tool]}
    assert request.get_header("Authorization") == "Bearer " + SECRET
    assert request.get_header("Accept") == "application/json"
    assert not hasattr(model, "observation")


def test_same_runtime_never_reuses_timing_across_successes_and_failures(tmp_path, monkeypatch):
    clock(monkeypatch, (10.0, 20.0, 22.0, 30.0, 40.0, 40.125))
    responses = [Response(json.dumps(chat()).encode()), Response(),
                 Response(json.dumps(chat()).encode()), Response()]
    calls = []

    def open_response(request, *, timeout):
        calls.append(timeout)
        return responses[len(calls) - 1]

    monkeypatch.setattr(rt, "urlopen", open_response)
    model = rt.OpenAICompatibleRuntime("http://local.invalid", "fixture")
    assert model._complete_direct([], timeout=1) == rt.ModelTurn("done")
    with pytest.raises(rt.ModelRequestFailure) as first:
        model._complete_direct([], timeout=2)
    before = observer_payload(tmp_path, first.value)
    assert model._complete_direct([], timeout=3) == rt.ModelTurn("done")
    with pytest.raises(rt.ModelRequestFailure) as second:
        model._complete_direct([], timeout=None)
    assert first.value is not second.value
    assert observer_payload(tmp_path, first.value) == before
    assert before["request_observation"] == {
        "phase": "validate_response", "elapsed_ms": 2000, "request_timeout_ms": 2000,
    }
    assert observer_payload(tmp_path, second.value)["request_observation"] == {
        "phase": "validate_response", "elapsed_ms": 125, "request_timeout_ms": None,
    }
    assert calls == [1, 2, 3, None] and all(r.reads == [8 * 1024 * 1024] for r in responses)


def test_foreign_typed_failure_is_rethrown_without_added_timing(tmp_path, monkeypatch):
    clock(monkeypatch, (10.0, RuntimeError("foreign failures are not instrumented")))

    class ForeignFailure(rt.ModelRequestFailure):
        pass

    original = ForeignFailure(SECRET, "invalid_json", 200)
    error, _ = invoke(monkeypatch, open_error=original)
    assert error is original and error.observation is None
    assert observer_payload(tmp_path, error)["schema_version"] == "1"
