"""Live logs preserve request wire, failures and sensitive-data boundaries."""

import hashlib
import json
import logging

import pytest

import lunar_evolution.model_request_logging as logs
import lunar_evolution.runtime as rt
from lunar_evolution.http_transport import TransportFailure, TransportResponse

ENDPOINT_SECRET = "private-endpoint-path-and-query"
KEY_SECRET = "private-authorization-token"
MESSAGE_SECRET = "private-message-content"
ARGUMENT_SECRET = "private-tool-argument"
ERROR_SECRET = "private-error-body-and-exception"


def records(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records
            if record.name == logs.LOGGER_NAME]


def model():
    return rt.OpenAICompatibleRuntime(
        "http://fixture.invalid/" + ENDPOINT_SECRET, "fixture", KEY_SECRET,
    )


def waiting(phase="open_response", status=None):
    return {"phase": phase, "status": status, "last_milestone": "wait_response_headers",
            "http_exchange_index": 1, "milestone_elapsed_ms": 17, "elapsed_ms": 30000}


@pytest.mark.parametrize("outcome", ["success", "timeout", "invalid_json", "http_error"])
def test_correlated_live_logs_preserve_one_request_and_never_include_secrets(
    monkeypatch, caplog, outcome,
):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    calls = []

    def exchange(request, timeout, *, observer):
        calls.append((request, timeout))
        observer(waiting())
        if outcome == "timeout":
            raise TransportFailure(cause="timeout", reason="transport_timeout")
        if outcome == "http_error":
            raise TransportFailure("read_http_error_body", "http_error", 503,
                                   "http_error", ERROR_SECRET.encode())
        body = b"bad json" if outcome == "invalid_json" else json.dumps({
            "choices": [{"message": {"content": "done"}}],
        }).encode()
        return TransportResponse(200, body)

    monkeypatch.setattr(rt, "exchange", exchange)
    messages = [{"role": "user", "content": MESSAGE_SECRET}]
    tools = ({"type": "function", "function": {"name": "fixture_tool",
              "description": ARGUMENT_SECRET}},)
    if outcome == "success":
        def forbidden(_body):
            pytest.fail("successful requests must not hash their body")

        monkeypatch.setattr(rt, "_request_fingerprint", forbidden)
        assert model().complete(messages, tools, timeout=60) == rt.ModelTurn("done")
    else:
        with pytest.raises(rt.ModelRequestFailure) as caught:
            model().complete(messages, tools, timeout=60)
        assert caught.value.evidence.reason == {
            "timeout": "transport_timeout", "http_error": "http_error",
            "invalid_json": "invalid_json",
        }[outcome]
    assert len(calls) == 1 and calls[0][1] == 60
    request = calls[0][0]
    assert json.loads(request.data) == {
        "model": "fixture", "messages": messages, "tools": list(tools), "stream": False,
    }
    assert request.get_header("Authorization") == "Bearer " + KEY_SECRET
    events = records(caplog)
    assert [event["event"] for event in events] == [
        "model_request_started", "model_request_waiting",
        "model_request_completed" if outcome == "success" else "model_request_failed",
    ]
    assert len({event["request_id"] for event in events}) == 1
    assert len(events[0]["request_id"]) == 32
    assert events[1]["milestone_wait_ms"] == 29983
    if outcome != "success":
        assert events[-1]["request_fingerprint"] == {
            "body_bytes": len(request.data),
            "body_sha256": hashlib.sha256(request.data).hexdigest(),
        }
    else:
        assert all("request_fingerprint" not in event for event in events)
    raw = json.dumps(events)
    for secret in (ENDPOINT_SECRET, KEY_SECRET, MESSAGE_SECRET, ARGUMENT_SECRET, ERROR_SECRET):
        assert secret not in raw


def test_disabled_logging_preserves_existing_two_argument_exchange(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=logs.LOGGER_NAME)
    calls = []

    def exchange(request, timeout):
        calls.append((request, timeout))
        return TransportResponse(200, b'{"choices":[{"message":{"content":"done"}}]}')

    monkeypatch.setattr(rt, "exchange", exchange)
    assert model().complete([], timeout=1).text == "done"
    assert len(calls) == 1 and not records(caplog)


def test_unbounded_direct_request_has_no_invented_wait_observation(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self, _maximum):
            return b'{"choices":[{"message":{"content":"done"}}]}'

    monkeypatch.setattr(rt, "urlopen", lambda *_args, **_kwargs: Response())
    assert model().complete([]).text == "done"
    events = records(caplog)
    assert len(events) == 2
    assert all(event["transport"] == "direct" and event["request_timeout_ms"] is None
               for event in events)
    assert all("last_milestone" not in event for event in events)


@pytest.mark.parametrize("snapshot", [
    {}, {**waiting(), "body": MESSAGE_SECRET},
    {**waiting(), "phase": MESSAGE_SECRET}, {**waiting(), "status": True},
    {**waiting(), "last_milestone": MESSAGE_SECRET},
    {**waiting(), "elapsed_ms": -1}, {**waiting(), "milestone_elapsed_ms": 30001},
    {**waiting(), "http_exchange_index": True},
])
def test_invalid_optional_snapshots_are_omitted(caplog, snapshot):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    log = logs.ModelRequestLog(timeout=1, bounded=True)
    log.wait(snapshot)
    log.finish("completed")
    assert [event["event"] for event in records(caplog)] == [
        "model_request_started", "model_request_completed",
    ]


@pytest.mark.parametrize("failure_site", ["id", "clock", "logger"])
def test_optional_logging_errors_preserve_original_failure(monkeypatch, caplog, failure_site):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)

    def fail(*_args, **_kwargs):
        raise RuntimeError(ERROR_SECRET)

    if failure_site == "id":
        monkeypatch.setattr(logs.secrets, "token_hex", fail)
    elif failure_site == "clock":
        monkeypatch.setattr(logs, "monotonic", fail)
    else:
        monkeypatch.setattr(logs._LOGGER, "info", fail)
    cause = TransportFailure(cause="timeout", reason="transport_timeout")
    calls = []

    def exchange(request, timeout, **_kwargs):
        calls.append((request, timeout))
        raise cause

    monkeypatch.setattr(rt, "exchange", exchange)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        model().complete([], timeout=1)
    assert caught.value.evidence.reason == "transport_timeout" and len(calls) == 1
    assert caught.value.__cause__.__class__ is TimeoutError
    assert ERROR_SECRET not in json.dumps(records(caplog))


def test_request_ids_are_distinct_and_terminal_is_written_only_once(caplog):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    first = logs.ModelRequestLog(timeout=1, bounded=True)
    second = logs.ModelRequestLog(timeout=1, bounded=True)
    first.finish("completed")
    first.finish("failed")
    first.wait(waiting())
    second.finish("failed")
    events = records(caplog)
    assert len(events) == 4
    assert events[0]["request_id"] != events[1]["request_id"]
    assert events[2]["request_id"] == events[0]["request_id"]
    assert events[3]["reason"] == "local_error"


class SpoofedText(str):
    def __hash__(self):
        return hash("open_response")

    def __eq__(self, other):
        return True


def test_hostile_string_subclasses_cannot_enter_fixed_log_fields(caplog):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    private = SpoofedText(MESSAGE_SECRET)
    log = logs.ModelRequestLog(timeout=1, bounded=True)
    log.wait({**waiting(), "phase": private})
    failure = rt.ModelRequestFailure(ERROR_SECRET, private)
    log.finish("failed", failure=failure)
    events = records(caplog)
    assert [event["event"] for event in events] == [
        "model_request_started", "model_request_failed",
    ]
    assert events[-1]["reason"] == "local_error"
    assert MESSAGE_SECRET not in json.dumps(events)
    other = logs.ModelRequestLog(timeout=1, bounded=True)
    other.finish(private)
    assert len(records(caplog)) == 3


def test_logger_setup_failure_preserves_command_and_restores_configuration(monkeypatch):
    logger = logs._LOGGER
    before = (logger.handlers[:], logger.level, logger.propagate, logger.disabled)

    def unavailable(_level):
        raise RuntimeError(ERROR_SECRET)

    monkeypatch.setattr(logger, "setLevel", unavailable)
    marker = []
    with logs.model_request_log_to_stderr(True):
        marker.append("adapter executed")
    assert marker == ["adapter executed"]
    assert (logger.handlers, logger.level, logger.propagate, logger.disabled) == before
    original = ValueError(MESSAGE_SECRET)
    with pytest.raises(ValueError) as caught, logs.model_request_log_to_stderr(True):
        raise original
    assert caught.value is original
    assert (logger.handlers, logger.level, logger.propagate, logger.disabled) == before


def test_hostile_dictionary_keys_cannot_bypass_log_field_whitelist(caplog):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)

    class PrivateKey(str):
        def __hash__(self):
            return hash("phase")

        def __eq__(self, other):
            return other == "phase"

    snapshot = {key: value for key, value in waiting().items() if key != "phase"}
    snapshot[PrivateKey(MESSAGE_SECRET)] = "open_response"
    log = logs.ModelRequestLog(timeout=1, bounded=True)
    log.wait(snapshot)
    log.finish("completed")
    assert [event["event"] for event in records(caplog)] == [
        "model_request_started", "model_request_completed",
    ]
    assert MESSAGE_SECRET not in json.dumps(records(caplog))


def test_waiting_log_limit_is_bounded_without_suppressing_terminal(caplog):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    log = logs.ModelRequestLog(timeout=86400, bounded=True)
    for _ in range(2882):
        log.wait(waiting())
    log.finish("completed")
    events = records(caplog)
    assert len(events) == 2882
    assert sum(event["event"] == "model_request_waiting" for event in events) == 2880
    assert events[-1]["event"] == "model_request_completed"
