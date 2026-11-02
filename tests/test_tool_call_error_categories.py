"""Fixed parser observations with fixture responses only; no model or tool execution."""

import copy
import hashlib
import json
import logging
from enum import Enum

import pytest
from test_model_failure_evidence import observer_payload
from test_runtime_tool_call_validation import call, without_id

import lunar_evolution.model_request_logging as logs
import lunar_evolution.runtime as rt
from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.http_transport import TransportResponse
from lunar_evolution.tools import LocalToolRegistry

PRIVATE = "TOOL-PARSE-PRIVATE-RESPONSE-AND-EXCEPTION"
ENDPOINT = "TOOL-PARSE-PRIVATE-ENDPOINT"
KEY = "TOOL-PARSE-PRIVATE-API-KEY"
MESSAGE = "TOOL-PARSE-PRIVATE-MESSAGE"
ARGUMENT = "TOOL-PARSE-PRIVATE-ARGUMENT"

CASES = [
    pytest.param(
        {PRIVATE: PRIVATE}, "BATCH_NOT_LIST", "model returned malformed tool calls",
        id="batch-not-list",
    ),
    pytest.param(
        [PRIVATE], "CALL_NOT_OBJECT", "model returned malformed tool call",
        id="call-not-object",
    ),
    pytest.param(
        [call(PRIVATE, "", {ARGUMENT: PRIVATE})], "FUNCTION_OR_NAME_INVALID",
        "model returned a tool call without a function name", id="function-or-name-invalid",
    ),
    pytest.param(
        [call(PRIVATE, PRIVATE, "{" + ARGUMENT)], "ARGUMENTS_INVALID_JSON",
        "model returned malformed tool arguments", id="arguments-invalid-json",
    ),
    pytest.param(
        [call(PRIVATE, PRIVATE, json.dumps([ARGUMENT]))], "ARGUMENTS_NOT_OBJECT",
        "model tool arguments must be a JSON object", id="arguments-not-object",
    ),
    pytest.param(
        [call(PRIVATE, PRIVATE), call(PRIVATE, PRIVATE)], "DUPLICATE_CALL_ID",
        "model returned duplicate tool call IDs", id="duplicate-call-id",
    ),
]


def records(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records
            if record.name == logs.LOGGER_NAME]


def private_absent(value):
    encoded = json.dumps(value)
    for secret in (PRIVATE, ENDPOINT, KEY, MESSAGE, ARGUMENT):
        assert secret not in encoded


def provider(monkeypatch, batch, *, extra=None):
    payload = {
        "choices": [{"message": {"content": None, "tool_calls": batch}}],
        "model": "fixture-model",
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        # Arbitrary provider metadata never supplies the observed category.
        "tool_call_error_category": PRIVATE,
        **(extra or {}),
    }
    raw = json.dumps(payload).encode()
    requests = []

    def exchange(request, timeout, **kwargs):
        requests.append((request, timeout, kwargs))
        assert len(requests) == 1, "a rejected batch must not cause a follow-up or retry"
        return TransportResponse(200, raw)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self, maximum):
            assert maximum == 8 * 1024 * 1024
            return raw

    def urlopen(request, timeout):
        requests.append((request, timeout, {}))
        assert len(requests) == 1, "a rejected batch must not cause a follow-up or retry"
        return Response()

    monkeypatch.setattr(rt, "exchange", exchange)
    monkeypatch.setattr(rt, "urlopen", urlopen)
    runtime = rt.OpenAICompatibleRuntime(
        "http://fixture.invalid/" + ENDPOINT, "fixture-model", KEY,
    )
    return runtime, requests


def test_category_inventory_is_six_owned_fixed_labels_and_legacy_failure_defaults():
    assert {item.value for item in rt.ToolCallErrorCategory} == {
        "batch_not_list", "call_not_object", "function_or_name_invalid",
        "arguments_invalid_json", "arguments_not_object", "duplicate_call_id",
    }
    failure = rt.ModelRequestFailure("original message", "invalid_tool_calls", 200)
    assert failure.args == ("original message",)
    assert failure.evidence == rt.ModelFailureEvidence("invalid_tool_calls", 200)
    assert failure.tool_call_error_category is None
    assert rt._tool_call_error_category_value(None) is None


@pytest.mark.parametrize("batch,name,message", CASES)
@pytest.mark.parametrize("bounded", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_all_six_labels_preserve_wire_failure_and_default_log_silence(
    monkeypatch, caplog, tmp_path, batch, name, message, bounded, enabled,
):
    caplog.set_level(logging.INFO if enabled else logging.WARNING, logger=logs.LOGGER_NAME)
    original = copy.deepcopy(batch)
    runtime, requests = provider(monkeypatch, batch)
    messages = [{"role": "user", "content": MESSAGE}]
    tools = ({"type": "function", "function": {"name": PRIVATE,
              "description": ARGUMENT}},)
    timeout = 2 if bounded else None
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete(messages, tools, timeout, max_completion_tokens=16384)
    error = caught.value
    assert type(error) is rt.ModelRequestFailure
    assert error.args == (message,)
    assert error.evidence == rt.ModelFailureEvidence("invalid_tool_calls", 200)
    assert error.tool_call_error_category is getattr(rt.ToolCallErrorCategory, name)
    assert error.observation.phase == "validate_response"
    assert error.observation.request_timeout_ms == (2000 if bounded else None)
    assert batch == original
    if name == "ARGUMENTS_INVALID_JSON":
        assert type(error.__cause__) is json.JSONDecodeError
    else:
        assert error.__cause__ is None
    assert len(requests) == 1
    request, observed_timeout, kwargs = requests[0]
    assert observed_timeout == timeout
    assert set(kwargs) == ({"observer"} if bounded and enabled else set())
    expected_body = json.dumps({
        "model": "fixture-model", "messages": messages, "stream": False,
        "tools": list(tools), "max_completion_tokens": 16384,
    }, ensure_ascii=False).encode("utf-8")
    assert request.data == expected_body
    assert request.full_url == "http://fixture.invalid/" + ENDPOINT + "/chat/completions"
    assert request.get_header("Authorization") == "Bearer " + KEY
    assert error.request_fingerprint == rt.ModelRequestFingerprint(
        len(expected_body), hashlib.sha256(expected_body).hexdigest(),
    )
    diagnostic = observer_payload(tmp_path, error)
    error.tool_call_error_category = None
    assert observer_payload(tmp_path, error) == diagnostic
    assert diagnostic["schema_version"] == "7"
    assert diagnostic["model_failure"] == {
        "reason": "invalid_tool_calls", "response_status": 200,
    }
    assert "tool_call_error_category" not in json.dumps(diagnostic)
    assert not (tmp_path / "receipt.json").exists()
    events = records(caplog)
    if enabled:
        assert [event["event"] for event in events] == [
            "model_request_started", "model_request_failed",
        ]
        assert events[-1]["tool_call_error_category"] == name.lower()
        assert events[-1]["reason"] == "invalid_tool_calls"
        assert "tool_call_error_category" not in events[0]
        assert len({event["request_id"] for event in events}) == 1
    else:
        assert events == []
    private_absent([events, diagnostic, str(error)])


@pytest.mark.parametrize("batch,name,message", CASES)
def test_rejected_batch_precedes_usage_identity_and_all_tool_effects(
    monkeypatch, tmp_path, batch, name, message,
):
    del message
    if isinstance(batch, list):
        batch = [call("side-effect-first", "write_file", {
            "path": "answer.txt", "content": PRIVATE,
        }), *batch]
    runtime, requests = provider(monkeypatch, batch, extra={"model": False, "usage": PRIVATE})
    tools = LocalToolRegistry(allow_exec=False)

    def forbidden(*_args, **_kwargs):
        pytest.fail("the rejected response must not reach usage parsing or tool execution")

    monkeypatch.setattr(rt.OpenAICompatibleRuntime, "_parse_usage", staticmethod(forbidden))
    monkeypatch.setattr(tools, "execute", forbidden)
    agent = AgentLoopRuntime(runtime, tools=tools, max_steps=2)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        agent.run("inspect " + MESSAGE, tmp_path, timeout=2)
    assert caught.value.evidence.reason == "invalid_tool_calls"
    assert caught.value.tool_call_error_category is getattr(rt.ToolCallErrorCategory, name)
    assert len(requests) == 1
    assert agent.last_tool_steps == 0
    assert agent.last_invocation.provider_requests == 1
    assert agent.last_invocation.responses_received == 0
    assert agent.last_invocation.accepted_usage is None
    assert not agent.last_invocation.usage_complete
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("batch,name", [
    ([call("same"), call("same", "", "{" + PRIVATE)], "FUNCTION_OR_NAME_INVALID"),
    ([call("same"), call("same", PRIVATE, "{" + PRIVATE)], "ARGUMENTS_INVALID_JSON"),
    ([call("same"), call("same", PRIVATE, "[]")], "ARGUMENTS_NOT_OBJECT"),
    ([call("same"), call("same"), PRIVATE], "DUPLICATE_CALL_ID"),
])
def test_overlapping_faults_keep_the_original_first_rejection(batch, name):
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime._parse_tool_calls(batch, response_status=200)
    assert caught.value.evidence.reason == "invalid_tool_calls"
    assert caught.value.tool_call_error_category is getattr(rt.ToolCallErrorCategory, name)


class ForeignCategory(Enum):
    DUPLICATE_CALL_ID = "duplicate_call_id"


@pytest.mark.parametrize("mutation", [
    "missing", "null", "string", "bool", "mapping", "list", "foreign_enum",
    "hostile_object", "hostile_string", "unregistered_owned", "foreign_failure",
    "foreign_evidence", "wrong_reason", "foreign_reason", "property",
    "dictionary_subclass", "foreign_dictionary_key", "unbounded_metadata",
])
def test_malformed_optional_metadata_omits_only_detail_without_remote_callbacks(
    monkeypatch, caplog, mutation,
):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    error = rt.ModelRequestFailure(
        PRIVATE, "invalid_tool_calls", 200,
        tool_call_error_category=rt.ToolCallErrorCategory.DUPLICATE_CALL_ID,
    )
    callbacks = []

    class Hostile:
        @property
        def value(self):
            callbacks.append("value")
            raise AssertionError(PRIVATE)

        def __str__(self):
            callbacks.append("str")
            raise AssertionError(PRIVATE)

        def __eq__(self, _other):
            callbacks.append("eq")
            raise AssertionError(PRIVATE)

        def __hash__(self):
            callbacks.append("hash")
            raise AssertionError(PRIVATE)

    class HostileText(str):
        def __eq__(self, _other):
            callbacks.append("text_eq")
            raise AssertionError(PRIVATE)

        def __hash__(self):
            callbacks.append("text_hash")
            return hash("tool_call_error_category")

    if mutation == "missing":
        del error.tool_call_error_category
    elif mutation in {"null", "string", "bool", "mapping", "list"}:
        error.tool_call_error_category = {
            "null": None, "string": "duplicate_call_id", "bool": True,
            "mapping": {"value": PRIVATE}, "list": [PRIVATE],
        }[mutation]
    elif mutation == "foreign_enum":
        error.tool_call_error_category = ForeignCategory.DUPLICATE_CALL_ID
    elif mutation == "hostile_object":
        error.tool_call_error_category = Hostile()
    elif mutation == "hostile_string":
        error.tool_call_error_category = HostileText(PRIVATE)
    elif mutation == "unregistered_owned":
        error.tool_call_error_category = object.__new__(rt.ToolCallErrorCategory)
    elif mutation == "foreign_failure":
        class ForeignFailure(rt.ModelRequestFailure):
            pass

        error.__class__ = ForeignFailure
    elif mutation == "foreign_evidence":
        class ForeignEvidence(rt.ModelFailureEvidence):
            pass

        error.evidence = ForeignEvidence("invalid_tool_calls", 200)
    elif mutation == "wrong_reason":
        error.evidence = rt.ModelFailureEvidence("invalid_json", 200)
    elif mutation == "foreign_reason":
        error.evidence = rt.ModelFailureEvidence(HostileText(PRIVATE), 200)
    elif mutation == "property":
        del error.tool_call_error_category

        def unreadable(_self):
            callbacks.append("property")
            raise AssertionError(PRIVATE)

        monkeypatch.setattr(rt.ModelRequestFailure, "tool_call_error_category",
                            property(unreadable), raising=False)
    elif mutation == "dictionary_subclass":
        class ForeignDict(dict):
            def get(self, *_args):
                callbacks.append("dict_get")
                raise AssertionError(PRIVATE)

        error.__dict__ = ForeignDict(error.__dict__)
    elif mutation == "foreign_dictionary_key":
        value = error.__dict__.pop("tool_call_error_category")
        error.__dict__[HostileText(PRIVATE)] = value
        callbacks.clear()  # Only the fixture insertion was permitted to hash the key.
    elif mutation == "unbounded_metadata":
        error.__dict__.update({f"extra-{index}": PRIVATE for index in range(17)})
    log = logs.ModelRequestLog(timeout=2, bounded=True)
    log.finish("failed", failure=error)
    events = records(caplog)
    assert [event["event"] for event in events] == [
        "model_request_started", "model_request_failed",
    ]
    terminal = events[-1]
    assert "tool_call_error_category" not in terminal
    assert terminal["reason"] == (
        "local_error" if mutation in {"foreign_failure", "foreign_evidence", "foreign_reason"}
        else "invalid_json" if mutation == "wrong_reason" else "invalid_tool_calls"
    )
    assert callbacks == []
    private_absent(events)


def test_projection_uses_registered_identity_without_reading_mutable_enum_value(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    category = rt.ToolCallErrorCategory.DUPLICATE_CALL_ID
    monkeypatch.setattr(category, "_value_", PRIVATE)
    failure = rt.ModelRequestFailure(
        PRIVATE, "invalid_tool_calls", 200, tool_call_error_category=category,
    )
    assert rt._tool_call_error_category_value(category) == "duplicate_call_id"
    log = logs.ModelRequestLog(timeout=2, bounded=True)
    log.finish("failed", failure=failure)
    assert records(caplog)[-1]["tool_call_error_category"] == "duplicate_call_id"
    log.finish("failed", failure=failure)
    log.finish("completed", failure=failure)
    assert len(records(caplog)) == 2
    completed = logs.ModelRequestLog(timeout=2, bounded=True)
    completed.finish("completed", failure=failure)
    assert records(caplog)[-1]["event"] == "model_request_completed"
    assert "tool_call_error_category" not in records(caplog)[-1]
    private_absent(records(caplog))


def test_projection_failure_preserves_terminal_reason_and_one_request(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)

    def unavailable(_value):
        raise RuntimeError(PRIVATE)

    monkeypatch.setattr(rt, "_tool_call_error_category_value", unavailable)
    runtime, requests = provider(monkeypatch, [call("same"), call("same")])
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete([], timeout=2)
    assert caught.value.tool_call_error_category is rt.ToolCallErrorCategory.DUPLICATE_CALL_ID
    assert caught.value.evidence.reason == "invalid_tool_calls"
    assert len(requests) == 1
    assert records(caplog)[-1]["reason"] == "invalid_tool_calls"
    assert "tool_call_error_category" not in records(caplog)[-1]
    private_absent(records(caplog))


def test_disabled_logs_never_attempt_optional_category_projection(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=logs.LOGGER_NAME)

    def forbidden(_value):
        pytest.fail("disabled logs must not project optional metadata")

    monkeypatch.setattr(rt, "_tool_call_error_category_value", forbidden)
    runtime, requests = provider(monkeypatch, [call("same"), call("same")])
    with pytest.raises(rt.ModelRequestFailure):
        runtime.complete([], timeout=2)
    assert len(requests) == 1
    assert records(caplog) == []


@pytest.mark.parametrize("reason", ["invalid_json", "invalid_usage", "invalid_model_identity"])
def test_nonparser_failures_never_receive_or_log_a_remote_category(monkeypatch, caplog, reason):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    extra = {
        "invalid_usage": {"usage": PRIVATE},
        "invalid_model_identity": {"model": False},
    }.get(reason)
    runtime, requests = provider(monkeypatch, [], extra=extra)
    if reason == "invalid_json":
        def exchange(request, timeout, **kwargs):
            requests.append((request, timeout, kwargs))
            return TransportResponse(200, PRIVATE.encode())

        monkeypatch.setattr(rt, "exchange", exchange)
    else:
        # A nonempty legacy text result reaches the existing identity/usage gates.
        payload = {"choices": [{"message": {"content": "done"}}],
                   "tool_call_error_category": "duplicate_call_id", **extra}

        def exchange(request, timeout, **kwargs):
            requests.append((request, timeout, kwargs))
            return TransportResponse(200, json.dumps(payload).encode())

        monkeypatch.setattr(rt, "exchange", exchange)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete([], timeout=2)
    assert caught.value.evidence.reason == reason
    assert caught.value.tool_call_error_category is None
    assert len(requests) == 1
    assert "tool_call_error_category" not in records(caplog)[-1]
    private_absent(records(caplog))


def test_accepted_quirks_and_legacy_extraction_remain_unchanged(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=logs.LOGGER_NAME)
    batch = [without_id(" "), call("explicit", "unknown_tool", '{"path":"other.txt"}')]
    del batch[0]["function"]["arguments"]
    original = copy.deepcopy(batch)
    runtime, requests = provider(monkeypatch, batch)
    assert runtime.complete([], timeout=2) == rt.ModelTurn(
        "", (rt.ToolCall("call-1", " ", {}),
             rt.ToolCall("explicit", "unknown_tool", {"path": "other.txt"})),
        response_model="fixture-model",
        usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
    )
    assert batch == original and len(requests) == 1
    assert records(caplog)[-1]["event"] == "model_request_completed"
    assert all("tool_call_error_category" not in event for event in records(caplog))
    assert rt.OpenAICompatibleRuntime._parse_tool_calls(None) == ()
    assert rt.OpenAICompatibleRuntime._parse_tool_calls([]) == ()
    assert rt.OpenAICompatibleRuntime._extract_turn({"response": " fallback "}) == ("fallback", ())
    private_absent(records(caplog))
