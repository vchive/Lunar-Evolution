"""Fixed decode observations using local fixtures, never live providers or tools."""

import hashlib
import json
import logging
import socket
import subprocess

import pytest
from test_model_failure_evidence import observer_payload
from test_runtime_decode_stability import fragment, provider
from test_runtime_tool_call_validation import call

import lunar_evolution.candidate_execution_runner as candidate_runner
import lunar_evolution.model_request_logging as logs
import lunar_evolution.runtime as rt
from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.profiles import ModelProfile
from lunar_evolution.tools import LocalToolRegistry, ToolResult

PRIVATE = "ARGUMENT-DECODE-PRIVATE-CONTENT-AND-FINISH"
MISSING = object()


@pytest.fixture(autouse=True)
def no_real_execution(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("decode observation fixtures must not use network or tool processes")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(candidate_runner, "_bounded_process_bytes", forbidden)


def records(caplog):
    return [json.loads(item.getMessage()) for item in caplog.records
            if item.name == logs.LOGGER_NAME]


def assert_private_absent(value):
    encoded = json.dumps(value)
    assert PRIVATE not in encoded
    assert "DECODE-STABILITY-PRIVATE" not in encoded


def response(batch, *, finish="tool_calls", **extra):
    choice = {"message": {"content": None, "tool_calls": batch}}
    if finish is not MISSING:
        choice["finish_reason"] = finish
    return json.dumps({
        "choices": [choice], "model": "fixture-model",
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        **extra,
    }).encode()


def terminal(caplog, failure):
    log = logs.ModelRequestLog(timeout=2, bounded=True)
    log.finish("failed", failure=failure)
    return records(caplog)[-1]


@pytest.mark.parametrize("arguments,position,line,column", [
    ("{", 1, 1, 2),
    ('{"x": }', 6, 1, 7),
    ('{"🚀":\n}', 6, 2, 1),
    ('{"\ud800":', 5, 1, 6),
])
@pytest.mark.parametrize("bounded", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_syntax_unicode_and_eof_keep_wire_and_failure_with_optional_fixed_log(
    monkeypatch, caplog, tmp_path, arguments, position, line, column, bounded, enabled,
):
    caplog.set_level(logging.INFO if enabled else logging.WARNING, logger=logs.LOGGER_NAME)
    runtime, requests = provider(monkeypatch, response([call(PRIVATE, PRIVATE, arguments)]))
    messages = [{"role": "user", "content": PRIVATE}]
    tools = ({"type": "function", "function": {"name": PRIVATE}},)
    timeout = 2 if bounded else None
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete(messages, tools, timeout, max_completion_tokens=16384)
    failure = caught.value
    expected = {
        "decoder_category": "json_syntax", "argument_characters": len(arguments),
        "position": position, "line": line, "column": column,
        "finish_reason_category": "tool_calls",
    }
    assert type(failure) is rt.ModelRequestFailure
    assert failure.args == ("model returned malformed tool arguments",)
    assert failure.evidence == rt.ModelFailureEvidence("invalid_tool_calls", 200)
    assert failure.tool_call_error_category is rt.ToolCallErrorCategory.ARGUMENTS_INVALID_JSON
    assert type(failure.__cause__) is json.JSONDecodeError
    assert failure.__cause__.doc == arguments and failure.__cause__.pos == position
    observation = failure.tool_argument_observation
    assert type(observation) is rt.ToolArgumentDecodeObservation
    assert observation.decoder_category is rt.ToolArgumentDecoderCategory.JSON_SYNTAX
    assert observation.argument_characters == len(arguments)
    assert (observation.position, observation.line, observation.column) == (position, line, column)
    assert observation.finish_reason_category is rt.ToolArgumentFinishReasonCategory.TOOL_CALLS
    assert failure.observation.phase == "validate_response"
    assert failure.observation.request_timeout_ms == (2000 if bounded else None)
    assert len(requests) == 1
    request, observed_timeout, options = requests[0]
    assert observed_timeout == timeout
    assert set(options) == ({"observer"} if bounded and enabled else set())
    expected_wire = json.dumps({
        "model": "fixture-model", "messages": messages, "stream": False,
        "tools": list(tools), "max_completion_tokens": 16384,
    }, ensure_ascii=False).encode()
    assert request.data == expected_wire
    assert failure.request_fingerprint == rt.ModelRequestFingerprint(
        len(expected_wire), hashlib.sha256(expected_wire).hexdigest(),
    )
    receipt_evidence = observer_payload(tmp_path, failure)
    assert receipt_evidence["schema_version"] == "7"
    assert receipt_evidence["model_failure"] == {
        "reason": "invalid_tool_calls", "response_status": 200,
    }
    assert "tool_argument_decode" not in json.dumps(receipt_evidence)
    assert not (tmp_path / "receipt.json").exists()
    events = records(caplog)
    if enabled:
        assert [item["event"] for item in events] == [
            "model_request_started", "model_request_failed",
        ]
        assert events[-1]["tool_argument_decode"] == expected
        assert events[-1]["reason"] == "invalid_tool_calls"
        assert events[-1]["tool_call_error_category"] == "arguments_invalid_json"
        assert "tool_argument_decode" not in events[0]
    else:
        assert events == []
    assert_private_absent([events, receipt_evidence, str(failure)])


@pytest.mark.parametrize("kind,decoder_name", [
    ("integer", "value_error"), ("recursion", "recursion_error"),
])
@pytest.mark.parametrize("bounded", [False, True])
def test_real_guarded_stdlib_errors_observe_fixed_category_without_fake_position(
    monkeypatch, caplog, kind, decoder_name, bounded,
):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    arguments, cause = fragment(monkeypatch, kind)
    runtime, requests = provider(monkeypatch, response([call(PRIVATE, PRIVATE, arguments)]))
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete([], timeout=2 if bounded else None)
    failure = caught.value
    assert type(failure.__cause__) is cause
    assert failure.evidence == rt.ModelFailureEvidence("invalid_tool_calls", 200)
    assert failure.tool_argument_observation.decoder_category is getattr(
        rt.ToolArgumentDecoderCategory, decoder_name.upper(),
    )
    assert records(caplog)[-1]["tool_argument_decode"] == {
        "decoder_category": decoder_name, "argument_characters": len(arguments),
        "finish_reason_category": "tool_calls",
    }
    assert len(requests) == 1
    assert_private_absent(records(caplog))


@pytest.mark.parametrize("finish,label", [
    ("stop", "stop"), ("length", "length"), ("tool_calls", "tool_calls"),
    ("function_call", "function_call"), ("content_filter", "content_filter"),
    (None, "null"), (PRIVATE, "other_string"), ("", "other_string"),
    (17, "invalid_type"), (False, "invalid_type"), ({PRIVATE: PRIVATE}, "invalid_type"),
    ([PRIVATE], "invalid_type"), (MISSING, None),
])
def test_finish_reason_uses_only_fixed_categories_from_selected_message(caplog, finish, label):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    payload = json.loads(response([call(PRIVATE, PRIVATE, "{")], finish=finish))
    payload["choices"].append({"finish_reason": "stop", "message": {"content": "ignored"}})
    payload["finish_reason"] = "content_filter"
    payload["message"] = {"content": "ignored", "finish_reason": "function_call"}
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime._extract_turn(payload, response_status=200)
    fields = terminal(caplog, caught.value)["tool_argument_decode"]
    assert fields["decoder_category"] == "json_syntax"
    if label is None:
        assert "finish_reason_category" not in fields
    else:
        assert fields["finish_reason_category"] == label
    assert_private_absent(records(caplog))


@pytest.mark.parametrize("choices", [
    None, [], [{"finish_reason": "length"}],
    [{"finish_reason": "content_filter", "message": None}],
    [{"finish_reason": "stop", "text": ""}],
])
def test_top_level_fallback_cannot_borrow_unselected_finish_reason(caplog, choices):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    payload = {
        "choices": choices, "finish_reason": "length",
        "message": {"content": "fallback", "tool_calls": [call(PRIVATE, PRIVATE, "{")],
                    "finish_reason": "function_call"},
    }
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime._extract_turn(payload, response_status=200)
    fields = terminal(caplog, caught.value)["tool_argument_decode"]
    assert fields == {"decoder_category": "json_syntax", "argument_characters": 1,
                      "position": 1, "line": 1, "column": 2}
    assert caught.value.tool_argument_observation.finish_reason_category is None
    assert_private_absent(records(caplog))


@pytest.mark.parametrize("bounded", [False, True])
def test_explicit_completion_limit_still_rejects_length_before_tool_decode(
    monkeypatch, caplog, bounded,
):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    runtime, requests = provider(
        monkeypatch, response([call(PRIVATE, PRIVATE, "{")], finish="length"),
    )

    def forbidden(*_args, **_kwargs):
        pytest.fail("the existing explicit length refusal must precede tool parsing")

    monkeypatch.setattr(rt.OpenAICompatibleRuntime, "_parse_tool_calls", staticmethod(forbidden))
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete([], timeout=2 if bounded else None, max_completion_tokens=16384)
    assert caught.value.evidence == rt.ModelFailureEvidence("invalid_response_shape", 200)
    assert caught.value.args == ("model endpoint returned a truncated completion",)
    assert caught.value.__cause__ is None
    assert caught.value.tool_argument_observation is None
    assert "tool_argument_decode" not in records(caplog)[-1]
    assert len(requests) == 1


def test_later_invalid_batch_keeps_previous_usage_and_prevents_all_new_tool_effects(
    monkeypatch, caplog, tmp_path,
):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    accepted = response([call("accepted", "list_dir", {"path": "."})])
    rejected = response([
        call("must-not-write", "write_file", {"path": "answer.txt", "content": PRIVATE}),
        call("later-invalid", "run_command", "{"),
    ], model=False, usage=PRIVATE)
    runtime, requests = provider(monkeypatch, accepted, rejected)
    registry, executions, usage_calls = LocalToolRegistry(allow_exec=False), [], []
    original_usage = rt.OpenAICompatibleRuntime._parse_usage

    def only_accepted_tool(name, arguments, workspace):
        assert name == "list_dir" and arguments == {"path": "."}
        assert workspace == tmp_path and not executions
        executions.append(name)
        return ToolResult("fixture listing")

    def only_accepted_usage(value, **options):
        usage_calls.append(value)
        assert len(usage_calls) == 1
        return original_usage(value, **options)

    monkeypatch.setattr(registry, "execute", only_accepted_tool)
    monkeypatch.setattr(rt.OpenAICompatibleRuntime, "_parse_usage",
                        staticmethod(only_accepted_usage))
    profile = ModelProfile("decode-observation", "fixture-model", max_steps=4,
                           timeout_seconds=2, max_total_tokens=100)
    agent = AgentLoopRuntime(runtime, tools=registry, max_steps=4, profile=profile)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        agent.run(PRIVATE, tmp_path, timeout=2)
    assert caught.value.evidence == rt.ModelFailureEvidence("invalid_tool_calls", 200)
    assert len(requests) == 2 and len(usage_calls) == 1 and executions == ["list_dir"]
    assert agent.last_tool_steps == 1
    invocation = agent.last_invocation
    assert invocation.provider_requests == 2 and invocation.responses_received == 1
    assert invocation.accepted_usage.rounds == 1
    assert invocation.accepted_usage.total_tokens == 3
    assert not invocation.usage_complete and not invocation.transcript_complete
    assert not list(tmp_path.rglob("*"))
    assert records(caplog)[-1]["tool_argument_decode"]["position"] == 1
    assert_private_absent(records(caplog))


@pytest.mark.parametrize("batch,category", [
    ({PRIVATE: PRIVATE}, "BATCH_NOT_LIST"),
    ([PRIVATE], "CALL_NOT_OBJECT"),
    ([call(PRIVATE, "", "{")], "FUNCTION_OR_NAME_INVALID"),
    ([call(PRIVATE, PRIVATE, "[]")], "ARGUMENTS_NOT_OBJECT"),
    ([call(PRIVATE), call(PRIVATE)], "DUPLICATE_CALL_ID"),
])
def test_other_five_parser_rejections_cannot_acquire_decode_detail(
    monkeypatch, caplog, batch, category,
):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    runtime, requests = provider(monkeypatch, response(batch))
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete([], timeout=2)
    assert caught.value.tool_call_error_category is getattr(rt.ToolCallErrorCategory, category)
    assert caught.value.tool_argument_observation is None
    assert "tool_argument_decode" not in records(caplog)[-1]
    assert len(requests) == 1
    assert_private_absent(records(caplog))


@pytest.mark.parametrize("raw,reason", [
    (b"{", "invalid_json"),
    (json.dumps({"choices": [{"message": {"content": "done"}}],
                 "usage": PRIVATE}).encode(), "invalid_usage"),
    (json.dumps({"choices": [{"message": {"content": "done"}}],
                 "model": False}).encode(), "invalid_model_identity"),
])
def test_outer_response_failures_have_no_argument_observation(monkeypatch, caplog, raw, reason):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    runtime, requests = provider(monkeypatch, raw)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete([], timeout=2)
    assert caught.value.evidence == rt.ModelFailureEvidence(reason, 200)
    assert caught.value.tool_argument_observation is None
    assert "tool_argument_decode" not in records(caplog)[-1]
    assert len(requests) == 1
    assert_private_absent(records(caplog))
