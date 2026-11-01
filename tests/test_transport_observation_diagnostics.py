"""Optional local transport detail preserves model failure and historical diagnostics."""

import hashlib
import json
from dataclasses import FrozenInstanceError, fields, replace
from urllib.error import HTTPError

import pytest
from test_effect_adapters import _subject_request
from test_model_failure_evidence import SECRET, chat, local_model, observer_payload
from test_model_request_timing import Response

import lunar_evolution.runtime as rt
from lunar_evolution.effect_adapters import EffectAdapterError, run_subject_adapter
from lunar_evolution.http_transport import TransportFailure, TransportObservation, TransportResponse
from lunar_evolution.subject_diagnostics import SubjectDiagnosticContext, normalize_diagnostic


def detail(milestone="wait_response_headers", index=1, elapsed=17):
    return TransportObservation(milestone, index, elapsed)


def projection(observation):
    return {
        "last_milestone": observation.last_milestone,
        "http_exchange_index": observation.http_exchange_index,
        "elapsed_ms": observation.elapsed_ms,
    }


def observed_error(*, reason="transport_timeout", phase="open_response", status=None):
    error = rt.ModelRequestFailure(SECRET, reason, status)
    error.observation = rt.ModelRequestObservation(phase, 25, 1000)
    error.transport_observation = detail()
    if reason == "transport_timeout":
        error.__cause__ = TimeoutError(SECRET)
    elif reason == "http_error":
        error.__cause__ = HTTPError("http://fixture.invalid/" + SECRET, status, SECRET, {}, None)
    return error


def bounded_call(monkeypatch, *, response=None, failure=None):
    calls = []

    def exchange(request, timeout):
        calls.append((request, timeout))
        if failure is not None:
            raise failure
        return response

    monkeypatch.setattr(rt, "exchange", exchange)
    messages = [{"role": "user", "content": SECRET}]
    tool = {"type": "function", "function": {"name": "read_file"}}
    model = rt.OpenAICompatibleRuntime("http://fixture.invalid/" + SECRET, "fixture", SECRET)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        model.complete(messages, (tool,), timeout=1.25)
    assert len(calls) == 1
    request, timeout = calls[0]
    assert timeout == 1.25 and request.get_method() == "POST"
    assert json.loads(request.data) == {
        "model": "fixture", "messages": messages, "stream": False, "tools": [tool],
    }
    assert request.get_header("Authorization") == "Bearer " + SECRET
    return caught.value


@pytest.mark.parametrize("phase,status,cause,reason,code", [
    ("open_response", None, "timeout", "transport_timeout", "timeout"),
    ("open_response", None, "url_timeout", "transport_timeout", "model_failed"),
    ("open_response", None, "url_error", "transport_error", "model_failed"),
    ("open_response", None, "local_error", "transport_error", "model_failed"),
    ("read_response_body", 200, "timeout", "transport_timeout", "timeout"),
    ("read_response_body", 200, "os_error", "transport_error", "model_failed"),
    ("read_http_error_body", 429, "http_error", "http_error", "model_http_failed"),
])
def test_bounded_transport_failure_retains_detail_without_changing_request_or_classification(
    tmp_path, monkeypatch, phase, status, cause, reason, code,
):
    observation = detail("response_headers_received" if status else "connect")
    failure = TransportFailure(phase, reason, status, cause, b"", observation=observation)
    error = bounded_call(monkeypatch, failure=failure)
    payload = observer_payload(tmp_path, error)
    assert error.transport_observation is observation
    assert payload["schema_version"] == "7" and payload["code"] == code
    assert payload["model_failure"] == {"reason": reason, "response_status": status}
    assert payload["request_observation"]["phase"] == phase
    assert payload["transport_observation"] == projection(observation)
    assert SECRET not in json.dumps(payload)


@pytest.mark.parametrize("body,reason", [
    (b"\xff", "invalid_json"), (b"invalid json", "invalid_json"),
    ([], "invalid_response_shape"), ({}, "invalid_response_shape"),
    (chat(None), "empty_response"), (chat(None, tool_calls="bad"), "invalid_tool_calls"),
    ({**chat(), "model": 42}, "invalid_model_identity"),
    ({**chat(), "usage": []}, "invalid_usage"),
])
def test_successful_transport_detail_survives_response_validation_failure(
    tmp_path, monkeypatch, body, reason,
):
    observation = detail("response_headers_received", 2, 10)
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    error = bounded_call(monkeypatch, response=TransportResponse(200, raw, observation))
    payload = observer_payload(tmp_path, error)
    assert error.transport_observation is observation
    assert payload["schema_version"] == "7" and payload["code"] == "model_failed"
    assert payload["model_failure"] == {"reason": reason, "response_status": 200}
    assert payload["request_observation"]["phase"] == "validate_response"
    assert payload["transport_observation"] == projection(observation)


def test_non_success_transport_response_keeps_original_null_legacy_http_status(tmp_path, monkeypatch):
    observation = detail("response_headers_received")
    error = bounded_call(monkeypatch, response=TransportResponse(503, b"{}", observation))
    payload = observer_payload(tmp_path, error)
    assert error.__cause__ is None
    assert payload["schema_version"] == "7" and payload["http_status"] is None
    assert payload["code"] == "model_failed"
    assert payload["model_failure"] == {"reason": "http_error", "response_status": 503}
    assert payload["request_observation"]["phase"] == "validate_response"


@pytest.mark.parametrize("failure", [False, True])
def test_legacy_transport_objects_remain_v4(tmp_path, monkeypatch, failure):
    error = bounded_call(
        monkeypatch, response=TransportResponse(200, b"invalid"),
        failure=TransportFailure() if failure else None,
    )
    payload = observer_payload(tmp_path, error)
    assert error.transport_observation is None
    assert payload["schema_version"] == "7" and "transport_observation" not in payload


@pytest.mark.parametrize("kind", ["missing", "foreign", "invalid", "property"])
@pytest.mark.parametrize("failure", [False, True])
def test_invalid_optional_transport_detail_cannot_mask_original_outcome(
    tmp_path, monkeypatch, kind, failure,
):
    if kind == "property":
        class ResponseWithBadDetail:
            status, body = 200, b"invalid"

            @property
            def observation(self):
                raise RuntimeError(SECRET)

        class FailureWithBadDetail(TransportFailure):
            def __getattribute__(self, name):
                if name == "observation":
                    raise RuntimeError(SECRET)
                return super().__getattribute__(name)

        carrier = FailureWithBadDetail() if failure else ResponseWithBadDetail()
    else:
        carrier = TransportFailure() if failure else TransportResponse(200, b"invalid")
        if kind == "missing":
            object.__delattr__(carrier, "observation")
        else:
            observation = {"body": SECRET} if kind == "foreign" else detail(SECRET)
            object.__setattr__(carrier, "observation", observation)
    error = bounded_call(
        monkeypatch, failure=carrier if failure else None, response=None if failure else carrier,
    )
    payload = observer_payload(tmp_path, error)
    assert payload["schema_version"] == "7"
    assert payload["model_failure"]["reason"] == ("transport_error" if failure else "invalid_json")
    assert SECRET not in json.dumps(payload)


def test_missing_coarse_clock_keeps_detail_on_error_but_subject_remains_v3(tmp_path, monkeypatch):
    def invalid_clock():
        raise RuntimeError(SECRET)

    monkeypatch.setattr(rt, "monotonic", invalid_clock)
    observation = detail()
    error = bounded_call(monkeypatch, response=TransportResponse(200, b"invalid", observation))
    assert error.transport_observation is observation and error.observation is None
    payload = observer_payload(tmp_path, error)
    assert payload["schema_version"] == "7" and "transport_observation" not in payload


def test_bounded_success_and_subsequent_calls_keep_no_shared_observation_state(tmp_path, monkeypatch):
    observation = detail("response_headers_received")
    responses = iter([
        TransportResponse(200, json.dumps(chat()).encode(), observation),
        TransportResponse(200, b"bad json", observation),
        TransportResponse(200, b"bad json"),
    ])
    monkeypatch.setattr(rt, "exchange", lambda *args: next(responses))
    model = rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture")
    assert model.complete([], timeout=1) == rt.ModelTurn("done")
    assert {field.name for field in fields(rt.ModelTurn)} == {
        "text", "tool_calls", "response_model", "usage",
    }
    assert not hasattr(model, "transport_observation")
    with pytest.raises(rt.ModelRequestFailure) as first:
        model.complete([], timeout=1)
    before = observer_payload(tmp_path, first.value)
    with pytest.raises(rt.ModelRequestFailure) as second:
        model.complete([], timeout=1)
    assert first.value.transport_observation is observation
    assert second.value.transport_observation is None
    assert observer_payload(tmp_path, first.value) == before
    assert before["schema_version"] == "7"
    assert observer_payload(tmp_path, second.value)["schema_version"] == "7"


@pytest.mark.parametrize("timeout", [None, 1])
def test_direct_path_never_adds_response_transport_detail(tmp_path, monkeypatch, timeout):
    response = Response()
    response.observation = detail()
    monkeypatch.setattr(rt, "urlopen", lambda *args, **kwargs: response)
    model = rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture")
    with pytest.raises(rt.ModelRequestFailure) as caught:
        model._complete_direct([], timeout=timeout)
    assert caught.value.transport_observation is None
    assert observer_payload(tmp_path, caught.value)["schema_version"] == "7"


@pytest.mark.parametrize("foreign", [False, True])
def test_detail_attachment_preserves_owned_failure_identity_and_foreign_exception_boundary(
    tmp_path, monkeypatch, foreign,
):
    class ForeignFailure(rt.ModelRequestFailure):
        pass

    error_type = ForeignFailure if foreign else rt.ModelRequestFailure
    original = error_type("fixed", "invalid_usage", 200)
    cause = ValueError(SECRET)
    original.__cause__ = cause
    observation = detail("response_headers_received")

    def reject(*args, **kwargs):
        raise original

    monkeypatch.setattr(rt.OpenAICompatibleRuntime, "_extract_turn", reject)
    error = bounded_call(monkeypatch, response=TransportResponse(200, b"{}", observation))
    assert error is original and error.__cause__ is cause
    assert error.transport_observation is (None if foreign else observation)
    assert observer_payload(tmp_path, error)["schema_version"] == ("1" if foreign else "7")


@pytest.mark.parametrize("milestone,index", [
    ("worker_ready", 0), ("prepare_request", 1), ("connect", 1),
    ("send_request", 256), ("wait_response_headers", 2), ("response_headers_received", 256),
])
def test_fixed_v5_vocabulary_and_boundaries_round_trip(tmp_path, milestone, index):
    error = observed_error()
    error.transport_observation = detail(milestone, index, 10**12)
    payload = observer_payload(tmp_path, error)
    assert payload["schema_version"] == "5"
    assert payload["transport_observation"] == projection(error.transport_observation)
    assert normalize_diagnostic(json.loads(json.dumps(payload))) == payload
    assert len(json.dumps(payload).encode()) < 4096 and SECRET not in json.dumps(payload)
    with pytest.raises(FrozenInstanceError):
        error.transport_observation.elapsed_ms = 0


@pytest.mark.parametrize("change", [
    {"last_milestone": SECRET}, {"last_milestone": []},
    {"last_milestone": "worker_ready"},
    {"http_exchange_index": 0}, {"http_exchange_index": -1}, {"http_exchange_index": 257},
    {"http_exchange_index": True}, {"http_exchange_index": 1.0}, {"http_exchange_index": "1"},
    {"elapsed_ms": -1}, {"elapsed_ms": 10**12 + 1}, {"elapsed_ms": True},
    {"elapsed_ms": 1.0}, {"elapsed_ms": "1"}, {"elapsed_ms": float("nan")},
])
def test_invalid_typed_detail_falls_back_to_identical_v4_and_reader_rejects_it(tmp_path, change):
    error = observed_error()
    error.transport_observation = None
    legacy = observer_payload(tmp_path, error)
    invalid = {**projection(detail()), **change}
    error.transport_observation = TransportObservation(**invalid)
    assert observer_payload(tmp_path, error) == legacy
    with pytest.raises(ValueError):
        normalize_diagnostic({**legacy, "schema_version": "5", "transport_observation": invalid})


@pytest.mark.parametrize("kind", ["missing", "none", "dict", "subtype", "missing_field"])
def test_missing_or_foreign_detail_does_not_replace_valid_v4(tmp_path, kind):
    error = observed_error()
    error.transport_observation = None
    legacy = observer_payload(tmp_path, error)
    if kind == "missing":
        del error.transport_observation
    elif kind == "dict":
        error.transport_observation = {**projection(detail()), "body": SECRET}
    elif kind == "subtype":
        class Foreign(TransportObservation):
            pass
        error.transport_observation = Foreign("connect", 1, 2)
    elif kind == "missing_field":
        error.transport_observation = detail()
        object.__delattr__(error.transport_observation, "elapsed_ms")
    assert observer_payload(tmp_path, error) == legacy


@pytest.mark.parametrize("coarse", [None, "foreign", "invalid"])
def test_valid_transport_detail_cannot_upgrade_missing_or_invalid_v4(tmp_path, coarse):
    error = observed_error()
    if coarse is None:
        error.observation = None
    elif coarse == "foreign":
        error.observation = {"phase": "open_response", "elapsed_ms": 1, "request_timeout_ms": 1}
    else:
        error.observation = replace(error.observation, phase="validate_response")
    payload = observer_payload(tmp_path, error)
    assert payload["schema_version"] == "3"
    assert "request_observation" not in payload and "transport_observation" not in payload


@pytest.mark.parametrize("outer_valid", [False, True])
def test_detail_never_borrowed_from_another_exception_node(tmp_path, outer_valid):
    inner = observed_error()
    outer = rt.ModelRequestFailure("fixed", "invalid_json", 200)
    outer.observation = rt.ModelRequestObservation("validate_response", 25, 1000)
    if not outer_valid:
        outer.evidence = {"reason": "invalid_json", "response_status": 200}
    outer.__cause__ = inner
    payload = observer_payload(tmp_path, outer)
    assert payload["schema_version"] == ("4" if outer_valid else "1")
    assert "transport_observation" not in payload


@pytest.mark.parametrize("depth", [0, 7, 8])
def test_transport_detail_preserves_existing_cause_depth_boundary(tmp_path, depth):
    error = observed_error()
    for _ in range(depth):
        outer = rt.RuntimeExecutionError("fixed")
        outer.__cause__ = error
        error = outer
    assert observer_payload(tmp_path, error)["schema_version"] == ("5" if depth <= 7 else "1")


@pytest.mark.parametrize("mutation", [
    "missing_detail", "null_detail", "extra_detail", "missing_detail_field",
    "missing_coarse", "invalid_coarse", "invalid_model", "extra_root", "downgrade", "stage",
])
def test_v5_reader_rejects_partial_unknown_or_downgraded_fields(tmp_path, mutation):
    payload = observer_payload(tmp_path, observed_error())
    if mutation == "missing_detail":
        del payload["transport_observation"]
    elif mutation == "null_detail":
        payload["transport_observation"] = None
    elif mutation == "extra_detail":
        payload["transport_observation"]["body"] = SECRET
    elif mutation == "missing_detail_field":
        del payload["transport_observation"]["elapsed_ms"]
    elif mutation == "missing_coarse":
        del payload["request_observation"]
    elif mutation == "invalid_coarse":
        payload["request_observation"]["phase"] = "connect"
    elif mutation == "invalid_model":
        payload["model_failure"] = None
    elif mutation == "extra_root":
        payload["source"] = SECRET
    elif mutation == "downgrade":
        payload["schema_version"] = "4"
    elif mutation == "stage":
        payload["stage"] = "runtime"
    with pytest.raises(ValueError):
        normalize_diagnostic(payload)


@pytest.mark.parametrize("version", ["1", "2", "3", "4"])
def test_historical_diagnostic_versions_keep_exact_shape_and_meaning(tmp_path, version):
    payload = observer_payload(tmp_path, observed_error())
    payload["schema_version"] = version
    del payload["transport_observation"]
    if version in {"1", "2"}:
        del payload["model_failure"]
    if version != "4":
        del payload["request_observation"]
    if version == "2":
        payload.update(stage="runtime", code="budget_exceeded", http_status=None, budget={
            "limit": "max_total_tokens", "state": "exceeded", "maximum": 10,
            "accepted_usage": None, "observed_usage": None,
            "trigger_recorded": False, "usage_completeness": "partial",
        })
    frozen = json.dumps(payload, sort_keys=True)
    assert normalize_diagnostic(json.loads(frozen)) == payload
    assert json.dumps(payload, sort_keys=True) == frozen
    with pytest.raises(ValueError):
        normalize_diagnostic({**payload, "transport_observation": projection(detail())})


def test_last_http_milestone_is_not_reinterpreted_as_current_or_final_response_state(tmp_path):
    error = observed_error(reason="invalid_json", phase="validate_response", status=200)
    # A non-HTTP redirect may finish after the last observed HTTP hop. The standalone
    # projection does not invent an HTTP event or require it to be the final response.
    error.transport_observation = detail("response_headers_received", 1, 7)
    payload = observer_payload(tmp_path, error)
    assert normalize_diagnostic(payload) == payload
    assert payload["model_failure"]["response_status"] == 200
    assert payload["transport_observation"]["http_exchange_index"] == 1


@pytest.mark.parametrize("mode", ["normal", "deep_evolution"])
def test_bounded_native_subject_publishes_and_collects_v5_without_receipt(tmp_path, mode):
    request = _subject_request(tmp_path / "subject")
    data = json.loads(request.read_bytes())
    if mode == "deep_evolution":
        data.update(mode=mode, round_index=1, outer_rounds=2, previous_evaluation=None,
                    receipt_path="receipts/001.json")
        request.write_text(json.dumps(data))
    request_bytes = request.read_bytes()
    public = {path: path.read_bytes() for path in (request.parent / "case").rglob("*") if path.is_file()}
    with local_model((200, b"bad json")) as (endpoint, calls), pytest.raises(EffectAdapterError):
        run_subject_adapter(request, timeout=2, model_runtime=rt.OpenAICompatibleRuntime(
            endpoint, "gpt-5.6-sol", SECRET,
        ))
    sidecar = (request.parent / data["receipt_path"]).with_suffix(".failure.json")
    raw = sidecar.read_bytes()
    payload = json.loads(raw)
    assert payload["schema_version"] == "7"
    assert payload["request_sha256"] == hashlib.sha256(request_bytes).hexdigest()
    assert payload["model_failure"] == {"reason": "invalid_json", "response_status": 200}
    assert payload["transport_observation"]["last_milestone"] == "response_headers_received"
    assert payload["transport_observation"]["http_exchange_index"] == 1
    assert len(calls) == 1 and not (request.parent / data["receipt_path"]).exists()
    assert request.read_bytes() == request_bytes
    assert public == {path: path.read_bytes() for path in public}
    assert SECRET not in raw.decode() and endpoint not in raw.decode()
    context = SubjectDiagnosticContext.from_request(request.parent, data, payload["request_sha256"])
    context.collect()
    name = "subject-failure.json" if mode == "normal" else "subject-001-failure.json"
    collected = request.parent.parent / "diagnostics" / name
    assert collected.read_bytes() == raw
    context.collect()
    assert collected.read_bytes() == raw
