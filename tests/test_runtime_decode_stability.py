"""Local decoder failures with fixture responses; no provider or tool process.

Recursion uses the isolated stdlib Python decoder at the existing loads seam;
it does not assume the default C decoder shares Python's recursion threshold.
Decimal conversion exercises the active default decoder limit unchanged.
"""

import hashlib
import json
import logging
import socket
import subprocess
import sys
from json.scanner import py_make_scanner

import pytest
from test_model_failure_evidence import observer_payload
from test_runtime_tool_call_validation import call

import lunar_evolution.candidate_execution_runner as candidate_runner
import lunar_evolution.model_request_logging as logs
import lunar_evolution.runtime as rt
from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.http_transport import TransportResponse
from lunar_evolution.profiles import ModelProfile
from lunar_evolution.tools import LocalToolRegistry, ToolResult

PRIVATE = "DECODE-STABILITY-PRIVATE-RESPONSE-ARGUMENT-AND-EXCEPTION"
ENDPOINT = "DECODE-STABILITY-PRIVATE-ENDPOINT"
KEY = "DECODE-STABILITY-PRIVATE-KEY"
MESSAGE = "DECODE-STABILITY-PRIVATE-PROMPT"


@pytest.fixture(autouse=True)
def no_real_execution(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("fixture decoder checks must not create network or tool processes")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(candidate_runner, "_bounded_process_bytes", forbidden)


def records(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records
            if record.name == logs.LOGGER_NAME]


def private_absent(value):
    encoded = json.dumps(value)
    assert all(secret not in encoded for secret in (PRIVATE, ENDPOINT, KEY, MESSAGE))


def fragment(monkeypatch, kind):
    """Exercise guarded stdlib decoding without changing interpreter settings."""
    if kind == "recursion":
        depth = sys.getrecursionlimit() + 100
        assert depth < 100_000, "fixture refuses an unexpectedly high recursion limit"
        damaged = '[' * depth + '0' + ']' * depth
        decoder = json.JSONDecoder()
        decoder.scan_once = py_make_scanner(decoder)
        # C and Python decoder recursion thresholds differ between CPython
        # versions. The stdlib Python scanner reaches the Python guard without
        # probing a native C-stack limit or changing any process-wide setting.
        with pytest.raises(RecursionError):
            decoder.decode(damaged)
        original_loads = json.loads

        def isolated_decode(value, *args, **kwargs):
            if type(value) is str and value == damaged:
                assert not args and not kwargs
                return decoder.decode(value)
            return original_loads(value, *args, **kwargs)

        # Only this exact fixture input uses the isolated Python decoder.
        # Valid response envelopes, requests and diagnostic JSON keep loads.
        monkeypatch.setattr(rt.json, "loads", isolated_decode)
        return damaged, RecursionError
    if kind == "integer":
        digits = sys.get_int_max_str_digits()
        if digits == 0:
            pytest.skip("CPython decimal conversion limit explicitly disabled; no limit to exercise")
        assert digits < 100_000, "fixture refuses an unexpectedly high integer conversion limit"
        return '{"value":' + '9' * (digits + 1) + '}', ValueError
    assert kind == "syntax"
    return '{"' + PRIVATE + '":', json.JSONDecodeError


def response(monkeypatch, point, kind):
    damaged, cause = fragment(monkeypatch, kind)
    if point == "body":
        # Encoding is ordinary UTF-8. json.loads itself must encounter the limit.
        return damaged.encode(), cause
    assert point == "arguments"
    return json.dumps({
        "choices": [{"message": {"content": None, "tool_calls": [
            call("side-effect-first", "write_file", {"path": "answer.txt", "content": PRIVATE}),
            call("rejected-second", "run_command", damaged),
        ]}}],
        "model": False,
        "usage": PRIVATE,
    }).encode(), cause


def provider(monkeypatch, *bodies):
    requests = []

    def next_body(request, timeout, **options):
        requests.append((request, timeout, options))
        assert len(requests) <= len(bodies), "no follow-up or retry after a rejected response"
        return bodies[len(requests) - 1]

    def exchange(request, timeout, **options):
        return TransportResponse(200, next_body(request, timeout, **options))

    class Response:
        def __init__(self, raw):
            self.raw = raw

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self, maximum):
            assert maximum == 8 * 1024 * 1024
            return self.raw

    def urlopen(request, timeout):
        return Response(next_body(request, timeout))

    monkeypatch.setattr(rt, "exchange", exchange)
    monkeypatch.setattr(rt, "urlopen", urlopen)
    runtime = rt.OpenAICompatibleRuntime("http://fixture.invalid/" + ENDPOINT, "fixture-model", KEY)
    return runtime, requests


def assert_failure(error, requests, tmp_path, *, reason, category, message, cause, bounded):
    assert type(error) is rt.ModelRequestFailure
    assert error.args == (message,)
    assert error.evidence == rt.ModelFailureEvidence(reason, 200)
    assert error.tool_call_error_category is category
    assert type(error.__cause__) is cause
    assert error.observation.phase == "validate_response"
    assert error.observation.request_timeout_ms == (2000 if bounded else None)
    request, timeout, _options = requests[-1]
    assert timeout == (2 if bounded else None)
    assert error.request_fingerprint == rt.ModelRequestFingerprint(
        len(request.data), hashlib.sha256(request.data).hexdigest(),
    )
    diagnostic = observer_payload(tmp_path, error)
    assert diagnostic["schema_version"] == "7"
    assert diagnostic["model_failure"] == {"reason": reason, "response_status": 200}
    assert diagnostic["request_observation"]["phase"] == "validate_response"
    assert diagnostic["code"] == "model_failed" and diagnostic["http_status"] is None
    assert not (tmp_path / "receipt.json").exists()
    private_absent([diagnostic, str(error)])


@pytest.mark.parametrize("point", ["body", "arguments"])
@pytest.mark.parametrize("kind", ["recursion", "integer", "syntax"])
@pytest.mark.parametrize("bounded", [False, True])
def test_decoder_failures_keep_existing_typed_rejection_and_diagnostics(
    monkeypatch, caplog, tmp_path, point, kind, bounded,
):
    raw, cause = response(monkeypatch, point, kind)
    runtime, requests = provider(monkeypatch, raw)
    # Cover both logging modes without duplicating every parser case.
    enabled = kind != "syntax"
    caplog.set_level(logging.INFO if enabled else logging.WARNING, logger=logs.LOGGER_NAME)

    def usage_forbidden(*_args, **_kwargs):
        pytest.fail("a rejected decoder response must not reach usage acceptance")

    monkeypatch.setattr(rt.OpenAICompatibleRuntime, "_parse_usage", staticmethod(usage_forbidden))
    messages = [{"role": "user", "content": MESSAGE}]
    tools = ({"type": "function", "function": {"name": "fixture_tool", "description": PRIVATE}},)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete(messages, tools, 2 if bounded else None, max_completion_tokens=16384)
    body_failure = point == "body"
    reason = "invalid_json" if body_failure else "invalid_tool_calls"
    category = None if body_failure else rt.ToolCallErrorCategory.ARGUMENTS_INVALID_JSON
    assert_failure(caught.value, requests, tmp_path, reason=reason, category=category,
                   message=("model endpoint returned malformed JSON" if body_failure
                            else "model returned malformed tool arguments"),
                   cause=cause, bounded=bounded)
    assert len(requests) == 1
    request, _timeout, options = requests[0]
    assert set(options) == ({"observer"} if bounded and enabled else set())
    expected = json.dumps({"model": "fixture-model", "messages": messages, "stream": False,
                           "tools": list(tools), "max_completion_tokens": 16384},
                          ensure_ascii=False).encode()
    assert request.data == expected
    assert request.full_url == "http://fixture.invalid/" + ENDPOINT + "/chat/completions"
    assert request.get_header("Authorization") == "Bearer " + KEY
    events = records(caplog)
    if enabled:
        assert [event["event"] for event in events] == [
            "model_request_started", "model_request_failed",
        ]
        assert len({event["request_id"] for event in events}) == 1
        assert events[-1]["reason"] == reason and events[-1]["response_status"] == 200
        if category is None:
            assert "tool_call_error_category" not in events[-1]
        else:
            assert events[-1]["tool_call_error_category"] == "arguments_invalid_json"
    else:
        assert events == []
    private_absent(events)


@pytest.mark.parametrize("model", [chr(0xD800), chr(0xDFFF), "prefix" + chr(0xD800) + "suffix"])
@pytest.mark.parametrize("bounded", [False, True])
def test_lone_surrogate_model_identity_is_fixed_rejection_before_usage(
    monkeypatch, caplog, tmp_path, model, bounded,
):
    raw = json.dumps({
        "choices": [{"message": {"content": None, "tool_calls": [
            call("pending-effect", "write_file", {"path": "answer.txt", "content": PRIVATE}),
        ]}}], "model": model, "usage": PRIVATE,
    }).encode()
    runtime, requests = provider(monkeypatch, raw)
    caplog.set_level(logging.INFO if bounded else logging.WARNING, logger=logs.LOGGER_NAME)

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid identity must not reach usage acceptance")

    monkeypatch.setattr(rt.OpenAICompatibleRuntime, "_parse_usage", staticmethod(forbidden))
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete([{"role": "user", "content": MESSAGE}], timeout=2 if bounded else None)
    assert_failure(caught.value, requests, tmp_path, reason="invalid_model_identity", category=None,
                   message="model endpoint returned an invalid model identity",
                   cause=UnicodeEncodeError, bounded=bounded)
    assert len(requests) == 1 and not (tmp_path / "answer.txt").exists()
    events = records(caplog)
    if bounded:
        assert [event["event"] for event in events] == [
            "model_request_started", "model_request_failed",
        ]
        assert events[-1]["reason"] == "invalid_model_identity"
        assert "tool_call_error_category" not in events[-1]
    else:
        assert events == []
    private_absent(events)


@pytest.mark.parametrize("failure", ["body_recursion", "arguments_recursion", "arguments_integer", "identity"])
def test_rejected_second_response_keeps_only_previous_usage_and_no_batch_effects(
    monkeypatch, tmp_path, failure,
):
    first = json.dumps({
        "choices": [{"message": {"content": None, "tool_calls": [
            call("accepted-first", "list_dir", {"path": "."}),
        ]}}], "model": "fixture-model",
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }).encode()
    if failure == "identity":
        rejected = json.dumps({
            "choices": [{"message": {"content": None, "tool_calls": [
                call("must-not-write", "write_file", {"path": "answer.txt", "content": PRIVATE}),
            ]}}], "model": "\ud800", "usage": PRIVATE,
        }).encode()
        reason, category = "invalid_model_identity", None
    else:
        point, kind = failure.split("_", 1)
        rejected, _cause = response(monkeypatch, point, kind)
        reason = "invalid_json" if point == "body" else "invalid_tool_calls"
        category = None if point == "body" else rt.ToolCallErrorCategory.ARGUMENTS_INVALID_JSON
    runtime, requests = provider(monkeypatch, first, rejected)
    registry, tool_calls = LocalToolRegistry(allow_exec=False), []

    def only_first_tool(name, arguments, workspace):
        del workspace
        assert name == "list_dir" and arguments == {"path": "."}
        assert not tool_calls, "no tool in the rejected response may execute"
        tool_calls.append((name, arguments))
        return ToolResult("fixture listing; no filesystem operation")

    monkeypatch.setattr(registry, "execute", only_first_tool)
    usage_calls, original_parse_usage = [], rt.OpenAICompatibleRuntime._parse_usage

    def only_first_usage(raw, **options):
        usage_calls.append(raw)
        assert len(usage_calls) == 1, "rejected response usage must remain unaccepted"
        return original_parse_usage(raw, **options)

    monkeypatch.setattr(rt.OpenAICompatibleRuntime, "_parse_usage", staticmethod(only_first_usage))
    profile = ModelProfile("decode-fixture", "fixture-model", max_steps=4,
                           timeout_seconds=2, max_total_tokens=100)
    agent = AgentLoopRuntime(runtime, tools=registry, max_steps=4, profile=profile)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        agent.run(MESSAGE, tmp_path, timeout=2)
    assert caught.value.evidence == rt.ModelFailureEvidence(reason, 200)
    assert caught.value.tool_call_error_category is category
    assert len(requests) == 2 and len(usage_calls) == 1 and len(tool_calls) == 1
    assert agent.last_tool_steps == 1
    diagnostic = agent.last_invocation
    assert diagnostic.provider_requests == 2 and diagnostic.responses_received == 1
    assert diagnostic.accepted_usage.rounds == 1 and diagnostic.accepted_usage.total_tokens == 3
    assert not diagnostic.usage_complete and not diagnostic.transcript_complete
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("bounded", [False, True])
@pytest.mark.parametrize("control", ["ordinary", "nested", "unicode_pair", "utf8_boundary"])
def test_valid_decoder_and_unicode_controls_keep_original_turn_usage_and_wire(
    monkeypatch, caplog, control, bounded,
):
    value = {"n": 123456789, "text": "fixture"}
    for _index in range(24 if control == "nested" else 1):
        value = {"nested": value}
    model = {"ordinary": " fixture-model ", "nested": "fixture-model",
             "unicode_pair": "model-\U0001f680", "utf8_boundary": "é" * 256}[control]
    batch = [call("accepted", "fixture_tool", json.dumps(value))]
    raw = json.dumps({
        "choices": [{"message": {"content": " ready ", "tool_calls": batch}}],
        "model": model, "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }).encode()
    runtime, requests = provider(monkeypatch, raw)
    caplog.set_level(logging.WARNING, logger=logs.LOGGER_NAME)
    messages = [{"role": "user", "content": MESSAGE}]
    turn = runtime.complete(messages, timeout=2 if bounded else None)
    assert turn == rt.ModelTurn("ready", (rt.ToolCall("accepted", "fixture_tool", value),),
                               response_model=model.strip(),
                               usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
    assert len(requests) == 1
    assert requests[0][0].data == json.dumps({
        "model": "fixture-model", "messages": messages, "stream": False,
    }, ensure_ascii=False).encode()
    assert records(caplog) == []
