"""Opt-in completion limits with local fixtures, never a live model or evaluator."""

import hashlib
import json
import threading
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_effect_adapters import _subject_request

import lunar_evolution.runtime as rt
from lunar_evolution.acceptance_request_budget import (
    AcceptanceRequestBudget,
    own_request_budget,
)
from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.effect_adapters import EffectAdapterError, run_subject_adapter
from lunar_evolution.http_transport import TransportResponse
from lunar_evolution.model_profile import UsageLedger
from lunar_evolution.model_request_logging import model_request_log_to_stderr
from lunar_evolution.profiles import ModelProfile
from lunar_evolution.tools import LocalToolRegistry

SECRET = "COMPLETION-LIMIT-PRIVATE-SENTINEL"
INVALID_LIMITS = [True, False, 1.5, 0, -1, 1_000_001, "4096", [], {}]
USAGE = {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}


def canonical(profile):
    return json.dumps(
        profile.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()


def response(content="done", *, reason="stop", tool_calls=None):
    message = {"content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message, "finish_reason": reason}],
        "usage": dict(USAGE),
    }


def tool(name="write_file", arguments=None):
    return {
        "id": "call-fixture", "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(
                {"path": "answer.txt", "content": SECRET} if arguments is None else arguments,
            ),
        },
    }


@contextmanager
def local_model(*responses):
    """Retain only synthetic HTTP payloads; forbid an unregistered follow-up request."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append({
                "path": self.path, "body": json.loads(raw),
                "authorization": self.headers.get("Authorization"),
            })
            status, payload = responses[min(len(calls) - 1, len(responses) - 1)]
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert len(calls) <= len(responses), "no retry or fallback is allowed"


@pytest.mark.parametrize("legacy,expected,digest", [
    (
        {"name": "fixture-profile", "model": "fixture-model"},
        (
            '{"input_cost_per_1k_micros":null,"max_cost_micros":null,"max_steps":40,'
            '"max_total_tokens":null,"model":"fixture-model","name":"fixture-profile",'
            '"output_cost_per_1k_micros":null,"thinking_budget":0,"timeout_seconds":900.0}'
        ),
        "fc0a1800552733a27264d2841ec6b68abc4a83c28140d4a2376420c052864995",
    ),
    (
        {
            "name": "旧边界", "model": "fixture-model", "thinking_budget": 7,
            "max_steps": 9, "timeout_seconds": 10, "max_total_tokens": 200,
            "max_cost_micros": 500, "input_cost_per_1k_micros": 10,
            "output_cost_per_1k_micros": 20,
        },
        (
            '{"input_cost_per_1k_micros":10,"max_cost_micros":500,"max_steps":9,'
            '"max_total_tokens":200,"model":"fixture-model","name":"旧边界",'
            '"output_cost_per_1k_micros":20,"thinking_budget":7,"timeout_seconds":10.0}'
        ),
        "77e77c73f322fe552cd08aa8ccf5681a8df641c4154a175d7a1fbd41d69cf325",
    ),
])
def test_legacy_profile_canonical_bytes_and_digest_are_unchanged(legacy, expected, digest):
    for profile in (
        ModelProfile(**legacy),
        ModelProfile.from_dict(legacy),
        ModelProfile.from_dict({**legacy, "max_completion_tokens": None}),
    ):
        raw = canonical(profile)
        assert profile.max_completion_tokens is None
        assert "max_completion_tokens" not in profile.to_dict()
        assert raw == expected.encode()
        assert hashlib.sha256(raw).hexdigest() == digest


@pytest.mark.parametrize("limit", [1, 4096, 1_000_000])
def test_configured_limit_changes_identity_and_round_trips(limit):
    legacy = ModelProfile("fixture", "fixture-model", max_total_tokens=20)
    profile = replace(legacy, max_completion_tokens=limit)
    assert profile.to_dict() == {**legacy.to_dict(), "max_completion_tokens": limit}
    assert ModelProfile.from_dict(profile.to_dict()) == profile
    assert canonical(profile) != canonical(legacy)
    assert hashlib.sha256(canonical(profile)).digest() != hashlib.sha256(canonical(legacy)).digest()
    # The per-response policy does not replace or constrain the existing aggregate ceiling.
    assert profile.max_total_tokens == 20


@pytest.mark.parametrize("limit", INVALID_LIMITS)
def test_profile_rejects_invalid_completion_limit(limit):
    for make in (
        lambda: ModelProfile("fixture", "fixture-model", max_completion_tokens=limit),
        lambda: ModelProfile.from_dict({
            "name": "fixture", "model": "fixture-model", "max_completion_tokens": limit,
        }),
    ):
        with pytest.raises(ValueError, match="max_completion_tokens"):
            make()


@pytest.mark.parametrize("limit", INVALID_LIMITS)
def test_invalid_runtime_limit_precedes_http_and_request_budget(monkeypatch, limit):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid policy must not reach either HTTP transport")

    monkeypatch.setattr(rt, "urlopen", forbidden)
    monkeypatch.setattr(rt, "exchange", forbidden)
    runtime = rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture-model", SECRET)
    budget = AcceptanceRequestBudget(max_requests=1, max_observed_tokens=100)
    before = budget.snapshot()
    with own_request_budget(budget):
        for timeout in (None, 2):
            with pytest.raises(ValueError, match="max_completion_tokens"):
                runtime.complete([], timeout=timeout, max_completion_tokens=limit)
        with pytest.raises(ValueError, match="max_completion_tokens"):
            runtime._complete_direct([], max_completion_tokens=limit)
    assert budget.snapshot() == before


@pytest.mark.parametrize("timeout,option", [
    (None, "omitted"), (None, None), (None, 4096), (2, 4096), (2, "omitted"),
])
def test_localhost_exact_wire_limit_is_opt_in_for_direct_and_bounded(timeout, option):
    messages = [{"role": "user", "content": "fixture prompt"}]
    tools = ({"type": "function", "function": {"name": "read_file"}},)
    options = {} if option == "omitted" else {"max_completion_tokens": option}
    with local_model((200, response())) as (endpoint, calls):
        actual = rt.OpenAICompatibleRuntime(endpoint, "fixture-model", SECRET).complete(
            messages, tools, timeout, **options,
        )
    expected = {
        "model": "fixture-model", "messages": messages, "stream": False,
        "tools": list(tools),
    }
    if option not in (None, "omitted"):
        expected["max_completion_tokens"] = option
    assert calls == [{
        "path": "/chat/completions", "body": expected,
        "authorization": f"Bearer {SECRET}",
    }]
    assert actual == rt.ModelTurn(
        "done", usage={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
    )


def test_gateway_rejection_has_one_request_and_no_max_tokens_fallback():
    with local_model((400, {"error": SECRET})) as (endpoint, calls):
        runtime = rt.OpenAICompatibleRuntime(endpoint, "fixture-model", SECRET)
        with pytest.raises(rt.ModelRequestFailure) as caught:
            runtime.complete([], max_completion_tokens=32)
    assert caught.value.evidence == rt.ModelFailureEvidence("http_error", 400)
    assert len(calls) == 1
    assert calls[0]["body"] == {
        "model": "fixture-model", "messages": [], "stream": False, "max_completion_tokens": 32,
    }
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("kind", ["text", "tools", "legacy_text"])
def test_capped_length_rejects_before_extraction_and_emits_fixed_failure(capsys, kind):
    payload = response(
        SECRET, reason="length", tool_calls=[tool()] if kind == "tools" else None,
    )
    if kind == "legacy_text":
        payload["choices"][0] = {"text": SECRET, "finish_reason": "length"}
    # The cap failure wins before extracting tools, provider identity or usage.
    payload["model"], payload["usage"] = {}, SECRET
    with (
        local_model((200, payload)) as (endpoint, calls),
        model_request_log_to_stderr(True),
        pytest.raises(rt.ModelRequestFailure) as caught,
    ):
        rt.OpenAICompatibleRuntime(endpoint, "fixture-model", SECRET).complete(
            [{"role": "user", "content": SECRET}], max_completion_tokens=32,
        )
    error = caught.value
    assert error.evidence == rt.ModelFailureEvidence("invalid_response_shape", 200)
    assert error.observation.phase == "validate_response"
    assert error.request_fingerprint is not None
    assert SECRET not in str(error)
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [event["event"] for event in events] == [
        "model_request_started", "model_request_failed",
    ]
    assert events[-1]["reason"] == "invalid_response_shape"
    assert SECRET not in json.dumps(events)
    assert endpoint not in json.dumps(events)
    assert "fixture-model" not in json.dumps(events)
    assert len(calls) == 1


@pytest.mark.parametrize("payload,limit", [
    (response(reason="length"), None),
    ({"choices": [{"message": {"content": "done"}}]}, 32),
    (response(reason="stop"), 32),
    ({"response": "done", "finish_reason": "length"}, 32),
    ({"message": {"content": "done"}, "finish_reason": "length"}, 32),
    ({"choices": [response()["choices"][0], {"finish_reason": "length"}]}, 32),
])
def test_uncapped_length_and_existing_response_compatibility_remain(payload, limit):
    with local_model((200, payload)) as (endpoint, calls):
        actual = rt.OpenAICompatibleRuntime(endpoint, "fixture-model", SECRET).complete(
            [], max_completion_tokens=limit,
        )
    assert actual.text == "done"
    assert len(calls) == 1


def test_rejected_completion_preserves_only_prior_usage_and_has_no_tool_effect(
    tmp_path, monkeypatch,
):
    bodies = [
        response(None, tool_calls=[tool("list_dir", {"path": "."})]),
        response(SECRET, reason="length", tool_calls=[tool()]),
    ]
    requests = []

    def exchange(request, timeout):
        requests.append(json.loads(request.data))
        assert len(requests) <= 2
        return TransportResponse(200, json.dumps(bodies[len(requests) - 1]).encode())

    monkeypatch.setattr(rt, "exchange", exchange)
    profile = ModelProfile(
        "capped", "fixture-model", max_total_tokens=100, max_completion_tokens=32,
    )
    ledger = UsageLedger(profile)
    budget = AcceptanceRequestBudget(max_requests=2, max_observed_tokens=100)
    registry = LocalToolRegistry(allow_exec=False)
    execute = registry.execute
    effects = []

    def guarded_execute(name, *args, **kwargs):
        effects.append(name)
        assert name == "list_dir", "truncated tool call must not execute"
        return execute(name, *args, **kwargs)

    monkeypatch.setattr(registry, "execute", guarded_execute)
    agent = AgentLoopRuntime(
        rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture-model", SECRET),
        profile=profile, tools=registry,
    )
    with own_request_budget(budget), pytest.raises(rt.ModelRequestFailure) as caught:
        agent.run("fixture task", tmp_path, timeout=2, usage_ledger=ledger)
    assert caught.value.evidence.reason == "invalid_response_shape"
    assert len(requests) == 2
    assert [item["max_completion_tokens"] for item in requests] == [32, 32]
    assert effects == ["list_dir"]
    assert not (tmp_path / "answer.txt").exists()
    assert agent.last_tool_steps == 1
    assert agent.last_invocation.responses_received == 1
    assert agent.last_invocation.accepted_usage.total_tokens == 5
    assert not agent.last_invocation.usage_complete
    assert ledger.snapshot.rounds == 1 and ledger.snapshot.total_tokens == 5
    assert not ledger.usage_complete
    assert budget.snapshot() == {
        "request_count": 2, "observed_tokens": 5, "usage_unknown": True,
    }


class LegacyModel:
    name = "fixture-model"

    def __init__(self):
        self.requests = []

    def complete(self, messages, tools=(), timeout=None):
        self.requests.append((messages, tools, timeout))
        return rt.ModelTurn("done", usage={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5})


@pytest.mark.parametrize("method", ["run", "run_isolated"])
def test_unset_profile_limit_preserves_injected_legacy_signature(tmp_path, method):
    for profile in (None, ModelProfile("legacy", "fixture-model")):
        model = LegacyModel()
        agent = AgentLoopRuntime(model, profile=profile)
        assert getattr(agent, method)("fixture", tmp_path).text == "done"
        assert len(model.requests) == 1


@pytest.mark.parametrize("method", ["run", "run_isolated"])
def test_configured_profile_limit_reaches_ordinary_and_isolated_calls(tmp_path, method):
    class CappedModel(LegacyModel):
        def complete(self, messages, tools=(), timeout=None, *, max_completion_tokens=None):
            assert max_completion_tokens == 73
            return super().complete(messages, tools, timeout)

    model = CappedModel()
    agent = AgentLoopRuntime(
        model, profile=ModelProfile("capped", "fixture-model", max_completion_tokens=73),
    )
    assert getattr(agent, method)("fixture", tmp_path).text == "done"
    assert len(model.requests) == 1
    if method == "run_isolated":
        assert model.requests[0][1] == ()


@pytest.mark.parametrize("method", ["run", "run_isolated"])
def test_configured_limit_cannot_fall_back_to_unbounded_legacy_call(tmp_path, method):
    model = LegacyModel()
    agent = AgentLoopRuntime(
        model, profile=ModelProfile("capped", "fixture-model", max_completion_tokens=32),
    )
    with pytest.raises(TypeError, match="max_completion_tokens"):
        getattr(agent, method)("fixture", tmp_path)
    assert model.requests == []
    assert not (tmp_path / "answer.txt").exists()


@pytest.mark.parametrize("mode", ["normal", "deep_evolution"])
def test_effect_subject_rejects_capped_tools_without_receipt_or_public_changes(
    tmp_path, monkeypatch, mode,
):
    request = _subject_request(tmp_path / "subject")
    profile = ModelProfile(
        "capped-subject", "gpt-5.6-sol", max_total_tokens=100, max_completion_tokens=32,
    )
    payload = json.loads(request.read_bytes())
    payload["model_profile_sha256"] = hashlib.sha256(canonical(profile)).hexdigest()
    if mode == "deep_evolution":
        payload.update(
            mode=mode, round_index=1, outer_rounds=2, previous_evaluation=None,
            receipt_path="receipts/001.json",
        )
    request.write_text(json.dumps(payload))
    public = {p: p.read_bytes() for p in (request.parent / "case").rglob("*") if p.is_file()}
    calls = []

    def exchange(http_request, timeout):
        calls.append(json.loads(http_request.data))
        assert len(calls) == 1, "a truncated subject must not retry or evaluate"
        body = response(
            SECRET, reason="length",
            tool_calls=[tool(arguments={"path": "solution.json", "content": SECRET})],
        )
        return TransportResponse(200, json.dumps(body).encode())

    monkeypatch.setattr(rt, "exchange", exchange)
    with pytest.raises(EffectAdapterError):
        run_subject_adapter(
            request, model_runtime=rt.OpenAICompatibleRuntime(
                "http://fixture.invalid", "gpt-5.6-sol", SECRET,
            ), model_profile=profile,
        )
    receipt_path = request.parent / payload["receipt_path"]
    diagnostic = json.loads(receipt_path.with_suffix(".failure.json").read_bytes())
    assert diagnostic["model_failure"] == {
        "reason": "invalid_response_shape", "response_status": 200,
    }
    assert diagnostic["mode"] == mode
    assert diagnostic["model_turns"] == diagnostic["tool_steps"] == 0
    assert SECRET not in json.dumps(diagnostic)
    assert calls[0]["max_completion_tokens"] == 32
    assert not receipt_path.exists()
    assert not (request.parent / "solution.json").exists()
    assert all(path.read_bytes() == original for path, original in public.items())
