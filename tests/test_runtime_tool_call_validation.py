"""Provider batch validation with synthetic responses only; no network or credentials."""

import copy
import json

import pytest
from test_model_failure_evidence import observer_payload

import lunar_evolution.runtime as rt
from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.http_transport import TransportResponse
from lunar_evolution.tools import LocalToolRegistry

SECRET = "TOOL-CALL-VALIDATION-PRIVATE-SENTINEL"


def call(identifier="call-a", name="read_file", arguments=None):
    return {
        "id": identifier,
        "type": "function",
        "function": {
            "name": name,
            "arguments": {"path": "answer.txt"} if arguments is None else arguments,
        },
    }


def without_id(name="read_file"):
    item = call(name=name)
    del item["id"]
    return item


def provider(monkeypatch, *batches):
    requests = []

    def exchange(request, timeout):
        requests.append((json.loads(request.data), timeout))
        assert len(requests) <= len(batches), "no unregistered follow-up request"
        batch = batches[len(requests) - 1]
        message = {"content": "done"} if batch is None else {
            "content": None, "tool_calls": batch,
        }
        body = {
            "choices": [{"message": message}],
            "model": "fixture-model",
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }
        return TransportResponse(200, json.dumps(body).encode())

    monkeypatch.setattr(rt, "exchange", exchange)
    return rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture-model", SECRET), requests


COLLIDING_BATCHES = [
    [call(SECRET), call(SECRET)],
    [without_id(), call("call-1")],
    [call("call-2"), without_id()],
    [call(None), call("call-1")],
    [call("first"), call("second"), call("first")],
]


@pytest.mark.parametrize("batch", COLLIDING_BATCHES)
def test_repeated_final_ids_are_typed_validation_failures(monkeypatch, tmp_path, batch):
    original = copy.deepcopy(batch)
    runtime, requests = provider(monkeypatch, batch)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete([{"role": "user", "content": "inspect"}], timeout=2)
    assert batch == original
    assert len(requests) == 1
    error = caught.value
    assert error.evidence.reason == "invalid_tool_calls"
    assert error.evidence.response_status == 200
    assert error.observation.phase == "validate_response"
    diagnostic = observer_payload(tmp_path, error)
    assert diagnostic["model_failure"] == {
        "reason": "invalid_tool_calls", "response_status": 200,
    }
    assert diagnostic["request_observation"]["phase"] == "validate_response"
    assert SECRET not in json.dumps(diagnostic)
    assert SECRET not in str(error)


@pytest.mark.parametrize("name", ["", None, False, 0, [], {}])
def test_empty_and_existing_invalid_name_types_are_rejected(monkeypatch, name):
    runtime, requests = provider(monkeypatch, [call(name=name)])
    with pytest.raises(rt.ModelRequestFailure) as caught:
        runtime.complete([], timeout=2)
    assert caught.value.evidence.reason == "invalid_tool_calls"
    assert caught.value.evidence.response_status == 200
    assert len(requests) == 1


@pytest.mark.parametrize("identifier", [None, False, 0, 42, [], {}, ""])
def test_existing_nonstring_and_empty_id_fallback_is_preserved(monkeypatch, identifier):
    runtime, _ = provider(monkeypatch, [call(identifier)])
    turn = runtime.complete([], timeout=2)
    assert turn.tool_calls == (rt.ToolCall("call-1", "read_file", {"path": "answer.txt"}),)


def test_missing_ids_keep_positional_defaults_and_argument_defaults(monkeypatch):
    batch = [without_id(), without_id()]
    del batch[0]["function"]["arguments"]
    batch[1]["function"]["arguments"] = '{"path":"other.txt"}'
    runtime, _ = provider(monkeypatch, batch)
    turn = runtime.complete([], timeout=2)
    assert turn == rt.ModelTurn(
        "", (
            rt.ToolCall("call-1", "read_file", {}),
            rt.ToolCall("call-2", "read_file", {"path": "other.txt"}),
        ),
        response_model="fixture-model",
        usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
    )


@pytest.mark.parametrize("name", ["read_file", "unknown_tool", " ", " read_file ", "函数"])
def test_nonempty_name_strings_are_not_stripped_or_allowlisted(monkeypatch, name):
    runtime, _ = provider(monkeypatch, [call(name=name)])
    assert runtime.complete([], timeout=2).tool_calls[0].name == name


def test_id_comparison_is_exact_and_scoped_to_one_response(monkeypatch):
    ids = ["a", " a ", "A", "a\t"]
    batch = [call(identifier) for identifier in ids]
    runtime, requests = provider(monkeypatch, batch, batch)
    for _ in range(2):
        assert [item.id for item in runtime.complete([], timeout=2).tool_calls] == ids
    assert len(requests) == 2


@pytest.mark.parametrize("bad_call", [call("same"), call(name="")])
def test_invalid_batch_has_no_tool_side_effect_or_followup(monkeypatch, tmp_path, bad_call):
    first = call("same", "write_file", {"path": "answer.txt", "content": SECRET})
    runtime, requests = provider(monkeypatch, [first, bad_call])
    tools = LocalToolRegistry(allow_exec=False)

    def forbidden(*args, **kwargs):
        pytest.fail("an invalid batch must be rejected before any tool executes")

    monkeypatch.setattr(tools, "execute", forbidden)
    agent = AgentLoopRuntime(runtime, tools=tools, max_steps=2)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        agent.run("write an answer", tmp_path, timeout=2)
    assert caught.value.evidence.reason == "invalid_tool_calls"
    assert len(requests) == 1
    assert agent.last_tool_steps == 0
    assert agent.last_invocation.responses_received == 0
    assert not (tmp_path / "answer.txt").exists()


def test_valid_mixed_ids_keep_next_request_pairing_and_wire_fields(monkeypatch, tmp_path):
    batch = [without_id("list_dir"), call("explicit", "list_dir", {"path": "."})]
    batch[0]["function"]["arguments"] = {"path": "."}
    runtime, requests = provider(monkeypatch, batch, None)
    tools = LocalToolRegistry(allow_exec=False)
    result = AgentLoopRuntime(runtime, tools=tools, max_steps=2).run(
        "inspect", tmp_path, timeout=2,
    )
    assert result.text == "done"
    assert len(requests) == 2
    body = requests[1][0]
    assert set(body) == {"model", "messages", "stream", "tools"}
    assert body["model"] == "fixture-model" and body["stream"] is False
    assert body["tools"] == list(tools.schemas())
    assistant, *results = body["messages"][-3:]
    assert assistant["role"] == "assistant" and assistant["content"] is None
    assert [item["id"] for item in assistant["tool_calls"]] == ["call-1", "explicit"]
    assert [item["tool_call_id"] for item in results] == ["call-1", "explicit"]
    assert all(item["role"] == "tool" for item in results)
    assert all(0 < timeout <= 2 for _, timeout in requests)


@pytest.mark.parametrize("name", ["unknown_tool", " "])
def test_nonempty_unknown_tool_still_recovers_through_tool_result(monkeypatch, tmp_path, name):
    runtime, requests = provider(monkeypatch, [call(name=name)], None)
    result = AgentLoopRuntime(runtime, tools=LocalToolRegistry(allow_exec=False)).run(
        "inspect", tmp_path, timeout=2,
    )
    assert result.text == "done" and len(requests) == 2
    tool_result = requests[1][0]["messages"][-1]
    assert tool_result["role"] == "tool"
    assert tool_result["tool_call_id"] == "call-a"
    assert "unknown tool:" in tool_result["content"]


class ForeignID(str):
    def __hash__(self):
        raise AssertionError("deduplication must not call a foreign ID hash")

    def __eq__(self, other):
        raise AssertionError("deduplication must not call foreign ID equality")

    def __str__(self):
        raise AssertionError("deduplication must not call foreign ID string conversion")


def test_direct_helper_preserves_unique_subclass_id_objects_without_callbacks():
    identifiers = [ForeignID("first"), ForeignID("second")]
    parsed = rt.OpenAICompatibleRuntime._parse_tool_calls([call(item) for item in identifiers])
    assert parsed[0].id is identifiers[0]
    assert parsed[1].id is identifiers[1]
    assert [str.__str__(item.id) for item in parsed] == ["first", "second"]


@pytest.mark.parametrize("batch", [
    [call(ForeignID("same")), call(ForeignID("same"))],
    [call(ForeignID("same")), call("same")],
    [call("same"), call(ForeignID("same"))],
    [call(ForeignID("call-2")), without_id()],
    [without_id(), call(ForeignID("call-1"))],
])
def test_direct_helper_rejects_subclass_duplicate_text_without_callbacks(batch):
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime._parse_tool_calls(batch, response_status=200)
    assert caught.value.evidence.reason == "invalid_tool_calls"
    assert caught.value.evidence.response_status == 200


def test_direct_helper_preserves_empty_subclass_fallback_without_callbacks():
    empty = ForeignID("")
    parsed = rt.OpenAICompatibleRuntime._parse_tool_calls([call(empty)])
    assert type(parsed[0].id) is str
    assert parsed[0].id == "call-1"
