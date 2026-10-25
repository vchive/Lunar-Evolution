"""Local HTTP and native failure boundaries; no external provider or credentials."""

import hashlib
import io
import json
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from test_effect_adapters import _subject_request
from test_effect_trial import _fixture
from test_staged_effect_adapter import _config, _profile, _profile_sha

import lunar_evolution.runtime as rt
from lunar_evolution.effect_adapters import EffectAdapterError, run_subject_adapter
from lunar_evolution.effect_trial import EffectTrialConfig, EffectTrialRunner
from lunar_evolution.subject_diagnostics import (
    SubjectDiagnosticContext,
    SubjectDiagnosticObserver,
    normalize_diagnostic,
)

SECRET = "LOCAL-DIAGNOSTIC-SECRET-SENTINEL"


@contextmanager
def local_model(*responses):
    """Exercise urllib's HTTP path with bounded fixture responses and no stored request body."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append(self.path)
            status, raw = responses[min(len(calls) - 1, len(responses) - 1)]
            body = raw if isinstance(raw, bytes) else json.dumps(raw).encode()
            self.send_response(status)
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


def observer_payload(tmp_path, error):
    context = SubjectDiagnosticContext.from_request(
        tmp_path, {"mode": "normal", "run_index": 1, "receipt_path": "receipt.json"}, "a" * 64,
    )
    observer = SubjectDiagnosticObserver()
    observer.event("agent_runtime_failure", {"phase": "model_turn", "error": SECRET})
    return observer.failure(context, error)


def chat(content="done", **extra):
    return {"choices": [{"message": {"content": content, **extra}}]}


@pytest.mark.parametrize("status,body,reason", [
    (429, SECRET.encode(), "http_error"),
    (500, {"error": SECRET}, "http_error"),
    (200, b"\xff", "invalid_json"),
    (200, b"not json", "invalid_json"),
    (200, [], "invalid_response_shape"),
    (200, None, "invalid_response_shape"),
    (200, 42, "invalid_response_shape"),
    (200, {}, "invalid_response_shape"),
    (200, {"choices": "wrong"}, "invalid_response_shape"),
    (200, {"choices": [42]}, "invalid_response_shape"),
    (200, {"choices": [{"message": []}]}, "invalid_response_shape"),
    (200, chat([]), "empty_response"),
    (200, chat(None), "empty_response"),
    (200, chat("", tool_calls="wrong"), "invalid_tool_calls"),
    (200, chat("", tool_calls=[{}]), "invalid_tool_calls"),
    (200, chat("", tool_calls=[{"function": {"name": "read_file", "arguments": "{"}}]),
     "invalid_tool_calls"),
    (200, chat(None, tool_calls=[{"id": "", "function": {"name": "", "arguments": "{}"}}]),
     "invalid_tool_calls"),
    (200, {**chat(), "model": 42}, "invalid_model_identity"),
    (200, {**chat(), "usage": []}, "invalid_usage"),
    (200, {**chat(), "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 4}},
     "invalid_usage"),
])
def test_real_http_failure_has_typed_projection(tmp_path, status, body, reason):
    with local_model((status, body)) as (endpoint, calls):
        runtime = rt.OpenAICompatibleRuntime(endpoint, "fixture", SECRET)
        with pytest.raises(rt.RuntimeExecutionError) as caught:
            runtime.complete([{"role": "user", "content": SECRET}], timeout=1)
    payload = observer_payload(tmp_path, caught.value)
    assert payload["schema_version"] == "5"
    assert payload["model_failure"] == {"reason": reason, "response_status": status}
    assert payload["code"] == ("model_http_failed" if status >= 400 else "model_failed")
    assert payload["http_status"] == (status if status >= 400 else None)
    assert len(calls) == 1
    encoded = json.dumps(payload)
    assert SECRET not in encoded and endpoint not in encoded
    assert len(encoded.encode()) <= 4096


@pytest.mark.parametrize("body,expected", [
    (chat(" done "), rt.ModelTurn("done")),
    ({"choices": [{"text": " legacy "}]}, rt.ModelTurn("legacy")),
    ({"message": {"content": "fallback"}}, rt.ModelTurn("fallback")),
    ({"response": "fallback"}, rt.ModelTurn("fallback")),
    ({"choices": None, "response": "fallback"}, rt.ModelTurn("fallback")),
    ({"choices": "invalid", "message": {"content": "fallback"}}, rt.ModelTurn("fallback")),
    ({"choices": [42], "response": "fallback"}, rt.ModelTurn("fallback")),
    ({"choices": [{"message": []}], "response": "fallback"}, rt.ModelTurn("fallback")),
    ({"choices": [{"message": None, "text": "legacy"}], "response": "unused"}, rt.ModelTurn("legacy")),
    ({"message": [], "response": "fallback"}, rt.ModelTurn("fallback")),
    (chat([{"text": "A"}, "ignored", {"text": 42}, {"text": "B"}]), rt.ModelTurn("AB")),
    ({**chat(), "usage": None}, rt.ModelTurn("done")),
    ({**chat(), "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}},
     rt.ModelTurn("done", usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})),
    (chat(None, tool_calls=[{"function": {"name": "read_file"}}]),
     rt.ModelTurn("", (rt.ToolCall("call-1", "read_file", {}),))),
    (chat(None, tool_calls=[{"id": "", "function": {"name": "read_file", "arguments": "{}"}}]),
     rt.ModelTurn("", (rt.ToolCall("call-1", "read_file", {}),))),
    ({**chat(), "model": " fixture "}, rt.ModelTurn("done", response_model="fixture")),
])
def test_real_http_preserves_success_acceptance_and_defaults(body, expected):
    with local_model((200, body)) as (endpoint, calls):
        actual = rt.OpenAICompatibleRuntime(endpoint, "fixture", SECRET).complete([], timeout=1)
    assert actual == expected
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["normal", "deep_evolution"])
def test_native_subject_retains_bound_v4_and_no_receipt(tmp_path, mode):
    request = _subject_request(tmp_path / "subject")
    data = json.loads(request.read_bytes())
    if mode == "deep_evolution":
        data.update(mode=mode, round_index=1, outer_rounds=2, previous_evaluation=None,
                    receipt_path="receipts/001.json")
        request.write_text(json.dumps(data))
    public = {p: p.read_bytes() for p in (request.parent / "case").rglob("*") if p.is_file()}
    with local_model((200, b"bad json")) as (endpoint, calls), pytest.raises(EffectAdapterError):
        run_subject_adapter(request, model_runtime=rt.OpenAICompatibleRuntime(
            endpoint, "gpt-5.6-sol", SECRET,
        ))
    path = (request.parent / data["receipt_path"]).with_suffix(".failure.json")
    result = json.loads(path.read_bytes())
    assert result["schema_version"] == "4"
    assert result["model_failure"] == {"reason": "invalid_json", "response_status": 200}
    assert result["request_sha256"] == hashlib.sha256(request.read_bytes()).hexdigest()
    assert result["mode"] == mode
    assert result["round_index"] == (1 if mode == "deep_evolution" else None)
    assert not (request.parent / data["receipt_path"]).exists()
    assert public == {p: p.read_bytes() for p in public}
    assert len(calls) == 1


@pytest.mark.parametrize("phase", ["normal", "master", "build"])
def test_native_trial_failure_does_not_dispatch_harness_or_retry(tmp_path, phase):
    suite, baseline, public, subject, harness = _fixture(tmp_path)
    profile = _profile()
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict()))
    staged = phase != "normal"
    plan = {**chat(json.dumps({"plan": ["Build the public output"],
                              "expected_paths": ["solution.json", "_agent_summary.md"]})),
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}
    responses = [(200, plan), (200, b"bad json")] if phase == "build" else [(200, b"bad json")]
    invocations = []

    with local_model(*responses) as (endpoint, calls):
        def executor(command, *, cwd, env, timeout):
            del env, timeout
            invocations.append(cwd.name)
            assert cwd.name == "subject", "failed subject must never dispatch the harness"
            request = Path(command[-1])
            try:
                run_subject_adapter(
                    request, model_runtime=rt.OpenAICompatibleRuntime(endpoint, "gpt-5.6-sol", SECRET),
                    model_profile=profile if staged else None, max_steps=8,
                    workflow_config=_config(request, profile, checkpoint_after_rounds=None) if staged else None,
                )
            except EffectAdapterError:
                return subprocess.CompletedProcess(command, 2)
            pytest.fail("fixture must fail")

        runner = EffectTrialRunner(
            suite, baseline, tmp_path / "trial", case_sources={"fixture_case": public},
            config=EffectTrialConfig(
                runs_per_case=1, timeout_seconds=10, requested_model="gpt-5.6-sol",
                subject_command=subject, harness_command=harness,
                subject_model_profile_path=profile_path if staged else None,
                model_profile_sha256=_profile_sha(profile) if staged else None,
            ), process_executor=executor,
        )
        record = runner.run().to_dict()["cases"][0]["runs"][0]
    assert invocations == ["subject"]
    assert len(calls) == (2 if phase == "build" else 1)
    assert record["error_code"] == "process_nonzero_exit" and record["ready"] is False
    assert all(record[key] is None for key in ("usage", "cost_micros", "overall_score", "validity_score"))
    attempt = tmp_path / "trial" / record["attempt"]
    payload = json.loads((attempt / "diagnostics/subject-failure.json").read_bytes())
    assert payload["model_failure"] == {"reason": "invalid_json", "response_status": 200}
    assert payload["model_turns"] == (1 if phase == "build" else 0)
    assert not (attempt / "subject/receipt.json").exists()
    assert not (attempt / "harness").exists()
    if staged:
        state = json.loads((attempt / "subject/workflow/state.json").read_bytes())
        assert state["stage"] == ("build_running" if phase == "build" else "master_running")


@pytest.mark.parametrize("error,reason,legacy_code", [
    (TimeoutError(SECRET), "transport_timeout", "timeout"),
    (URLError(TimeoutError(SECRET)), "transport_timeout", "model_failed"),
    (URLError(URLError(TimeoutError(SECRET))), "transport_timeout", "model_failed"),
    (URLError("timeout " + SECRET), "transport_error", "model_failed"),
    (OSError(SECRET), "transport_error", "model_failed"),
    (ConnectionResetError(SECRET), "transport_error", "model_failed"),
])
@pytest.mark.parametrize("status", [None, 200])
def test_transport_observation_preserves_legacy_code_and_prior_status(
    tmp_path, monkeypatch, error, reason, legacy_code, status,
):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def getcode(self):
            return status

        def read(self, maximum):
            raise error

    def open_response(*args, **kwargs):
        if status is None:
            raise error
        return Response()

    monkeypatch.setattr(rt, "urlopen", open_response)
    with pytest.raises(rt.RuntimeExecutionError) as caught:
        rt.OpenAICompatibleRuntime("http://local.invalid/" + SECRET, "fixture", SECRET).complete([])
    payload = observer_payload(tmp_path, caught.value)
    assert payload["model_failure"] == {"reason": reason, "response_status": status}
    assert payload["code"] == legacy_code and payload["http_status"] is None
    assert caught.value.__cause__ is error
    assert SECRET not in json.dumps(payload)


@pytest.mark.parametrize("status", [True, 200.0, 999, -1])
def test_invalid_observed_status_is_null_without_losing_typed_reason(tmp_path, monkeypatch, status):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def getcode(self):
            return status

        def read(self, maximum):
            return b"invalid json"

    monkeypatch.setattr(rt, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(rt.RuntimeExecutionError) as caught:
        rt.OpenAICompatibleRuntime("http://local.invalid", "fixture", SECRET).complete([])
    result = observer_payload(tmp_path, caught.value)
    assert result["schema_version"] == "4"
    assert result["model_failure"] == {
        "reason": "invalid_json" if status == 200 else "http_error", "response_status": None,
    }
    assert result["http_status"] is None and result["code"] == "model_failed"


def test_explicit_non_success_response_preserves_null_legacy_http_status(tmp_path, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def getcode(self):
            return 503

        def read(self, maximum):
            return SECRET.encode()

    monkeypatch.setattr(rt, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(rt.RuntimeExecutionError) as caught:
        rt.OpenAICompatibleRuntime("http://local.invalid", "fixture", SECRET).complete([])
    result = observer_payload(tmp_path, caught.value)
    assert result["model_failure"] == {"reason": "http_error", "response_status": 503}
    assert result["code"] == "model_failed" and result["http_status"] is None
    assert caught.value.__cause__ is None


def test_foreign_exception_cannot_break_typed_transport_inspection():
    class ForeignError(OSError):
        def __getattribute__(self, name):
            if name in {"__cause__", "reason"}:
                raise ValueError(SECRET)
            return super().__getattribute__(name)

    assert rt._transport_failure_reason(ForeignError()) == "transport_error"


@pytest.mark.parametrize("depth", [0, 6, 7, 8, 12])
def test_typed_replacement_preserves_eight_node_legacy_cause_boundary(tmp_path, depth):
    root = HTTPError("http://local.invalid/" + SECRET, 429, SECRET, {}, io.BytesIO())
    error = rt.ModelRequestFailure(SECRET, "http_error", 429)
    error.__cause__ = root
    for _ in range(depth):
        wrapped = rt.RuntimeExecutionError(SECRET)
        wrapped.__cause__ = error
        error = wrapped
    result = observer_payload(tmp_path, error)
    assert result["code"] == ("model_http_failed" if depth <= 6 else "model_failed")
    assert result["http_status"] == (429 if depth <= 6 else None)
    assert result["schema_version"] == ("3" if depth <= 7 else "1")
    assert SECRET not in json.dumps(result)


def test_bounded_typed_reason_walk_handles_cycles_and_ignores_foreign_attributes(tmp_path, monkeypatch):
    error = URLError(SECRET)
    error.reason = error
    error.__cause__ = error
    error.response_status = 429
    assert rt._transport_failure_reason(error) == "transport_error"
    # urllib's own __str__ cannot format a reason cycle. Keep that pre-existing execution
    # behavior outside this diagnostic feature; the cause cycle still exercises projection.
    error.reason = SECRET

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(rt, "urlopen", fail)
    with pytest.raises(rt.RuntimeExecutionError) as caught:
        rt.OpenAICompatibleRuntime("http://local.invalid", "fixture", SECRET).complete([])
    result = observer_payload(tmp_path, caught.value)
    assert result["model_failure"] == {"reason": "transport_error", "response_status": None}


@pytest.mark.parametrize("kind", ["foreign_error", "foreign_evidence", "subtype_error", "subtype_evidence",
                                 "missing", "bad_reason", "status_bool", "status_large", "bad_pair"])
def test_invalid_or_foreign_typed_evidence_falls_back_to_v1(tmp_path, kind):
    error = rt.ModelRequestFailure(SECRET, "invalid_json", 200)
    if kind == "foreign_error":
        error = rt.RuntimeExecutionError(SECRET)
        error.evidence = rt.ModelFailureEvidence("invalid_json", 200)
    elif kind == "foreign_evidence":
        error.evidence = {"reason": "invalid_json", "response_status": 200, "private": SECRET}
    elif kind == "subtype_error":
        class ForeignError(rt.ModelRequestFailure):
            pass
        error = ForeignError(SECRET, "invalid_json", 200)
    elif kind == "subtype_evidence":
        class ForeignEvidence(rt.ModelFailureEvidence):
            pass
        error.evidence = ForeignEvidence("invalid_json", 200)
    elif kind == "missing":
        del error.evidence
    else:
        changes = {"bad_reason": {"reason": SECRET}, "status_bool": {"response_status": True},
                   "status_large": {"response_status": 900}, "bad_pair": {"response_status": 429}}
        error.evidence = replace(error.evidence, **changes[kind])
    payload = observer_payload(tmp_path, error)
    assert payload["schema_version"] == "1" and "model_failure" not in payload
    assert payload["code"] == "model_failed" and SECRET not in json.dumps(payload)


@pytest.mark.parametrize("change", [
    {"stage": "runtime"}, {"code": "budget_exceeded"}, {"code": "model_http_failed"},
    {"http_status": 429}, {"budget": {}}, {"raw_error": SECRET},
    {"model_failure": {"reason": "invalid_json", "response_status": 200, "body": SECRET}},
    {"model_failure": {"reason": SECRET, "response_status": None}},
    {"model_failure": {"reason": [], "response_status": None}},
    {"model_failure": {"reason": "http_error", "response_status": 200}},
    {"model_failure": {"reason": "invalid_json", "response_status": 429}},
    {"model_failure": {"reason": "invalid_json", "response_status": True}},
    {"model_failure": {"reason": "invalid_json", "response_status": 1000}},
])
def test_v3_rejects_malformed_and_inconsistent_claims(tmp_path, change):
    payload = observer_payload(tmp_path, rt.ModelRequestFailure("fixed", "invalid_json", 200))
    assert normalize_diagnostic(payload) == payload
    with pytest.raises(ValueError):
        normalize_diagnostic({**payload, **change})


def test_legacy_diagnostics_remain_unchanged_and_model_evidence_cannot_be_runtime_budget(tmp_path):
    context = SubjectDiagnosticContext.from_request(
        tmp_path, {"mode": "normal", "run_index": 1, "receipt_path": "receipt.json"}, "a" * 64,
    )
    observer = SubjectDiagnosticObserver()
    legacy = context.payload("runtime", "runtime_failed", 0, 0, None)
    assert observer.failure(context, rt.ModelRequestFailure(SECRET, "invalid_json", 200)) == legacy
    assert normalize_diagnostic(legacy) == legacy


def test_deep_second_round_http_failure_keeps_first_independent_score(tmp_path):
    from test_deep_effect_trial import (
        _deep_config,
        _make_bound_subject_script,
        _make_case,
        _make_constant_harness_script,
        _write_baseline,
        _write_json,
    )

    from lunar_evolution.deep_effect_trial import DeepEffectTrialRunner

    public, suite = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline_path = _write_baseline(tmp_path, suite)
    subject = _make_bound_subject_script(tmp_path / "subject.py")
    harness = _make_constant_harness_script(tmp_path / "harness.py")
    invocations = []
    with local_model((200, b"invalid json")) as (endpoint, calls):
        def executor(command, *, cwd, env, timeout):
            request = Path(command[-1])
            payload = json.loads(request.read_bytes())
            invocations.append("harness" if "candidate_workspace" in payload else "subject")
            if payload.get("round_index") == 2 and "candidate_workspace" not in payload:
                try:
                    run_subject_adapter(request, model_runtime=rt.OpenAICompatibleRuntime(endpoint, "model", SECRET))
                except EffectAdapterError:
                    return subprocess.CompletedProcess(command, 2)
                pytest.fail("second round must fail")
            return subprocess.run(command, cwd=cwd, env=env, timeout=timeout, check=False, capture_output=True)

        runner = DeepEffectTrialRunner(
            suite_path, baseline_path, tmp_path / "trial", case_sources={"case-a": public},
            config=_deep_config(subject, harness, outer_rounds=2), process_executor=executor,
        )
        record = runner.run().to_dict()["cases"][0]["runs"][0]
    assert invocations == ["subject", "harness", "subject"] and len(calls) == 1
    assert record["error_code"] == "process_nonzero_exit" and record["ready"] is False
    assert len(record["rounds"]) == 1 and record["rounds"][0]["overall_score"] == 0.5
    assert record["usage"] is None and record.get("cost_micros") is None
    attempt = tmp_path / "trial" / record["attempt"]
    assert not (attempt / "subject/receipts/002.json").exists()
    payload = json.loads((attempt / "diagnostics/subject-002-failure.json").read_bytes())
    assert payload["schema_version"] == "4" and payload["round_index"] == 2
    assert payload["model_failure"] == {"reason": "invalid_json", "response_status": 200}
