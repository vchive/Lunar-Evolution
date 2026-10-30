"""Accepted-response subtotals after a later request fails; no provider calls."""

import copy
import json

import pytest
from test_effect_adapters import _subject_request
from test_staged_effect_adapter import StagedSubject, _config
from test_staged_effect_adapter import _profile as _staged_profile
from test_subject_diagnostics import _context

from lunar_evolution.agent_loop import AgentLoopRuntime, InvocationDiagnostics, ProfileBudgetFailure
from lunar_evolution.effect_adapters import (
    EffectAdapterError,
    _model_profile_digest,
    run_subject_adapter,
)
from lunar_evolution.http_transport import TransportObservation
from lunar_evolution.model_profile import BudgetFailureEvidence, UsageLedger, UsageSnapshot
from lunar_evolution.profiles import ModelProfile
from lunar_evolution.runtime import (
    ModelRequestFailure,
    ModelRequestObservation,
    ModelTurn,
    ToolCall,
)
from lunar_evolution.subject_diagnostics import SubjectDiagnosticObserver, normalize_diagnostic

SECRET = "SUBJECT-USAGE-PRIVATE-SENTINEL"
SUBTOTAL = {"input_tokens": 60, "output_tokens": 12, "total_tokens": 72,
            "cost_micros": None, "rounds": 3}


def _timeout():
    error = ModelRequestFailure(SECRET, "transport_timeout")
    error.observation = ModelRequestObservation("open_response", 100, 100)
    error.transport_observation = TransportObservation("wait_response_headers", 1, 2)
    return error


class LateFailureModel:
    model = "gpt-5.6-sol"
    api_key = SECRET

    def __init__(self, successful_turns=3):
        self.calls = 0
        self.successful_turns = successful_turns
        self.error = _timeout()

    def complete(self, messages, tools=(), timeout=None):
        self.calls += 1
        if self.calls > self.successful_turns:
            raise self.error from TimeoutError(SECRET)
        count = 2 if self.calls == 1 else 1
        return ModelTurn(
            "", tuple(ToolCall(f"{self.calls}-{i}", "list_dir", {"path": "."})
                      for i in range(count)),
            response_model=self.model,
            usage={"input_tokens": 10 * self.calls, "output_tokens": 2 * self.calls,
                   "total_tokens": 12 * self.calls},
        )


def _profile(*, priced=False):
    return ModelProfile(
        "accepted-usage-fixture", LateFailureModel.model, max_steps=12,
        timeout_seconds=10, max_total_tokens=160000,
        input_cost_per_1k_micros=1000 if priced else None,
        output_cost_per_1k_micros=2000 if priced else None,
    )


def _request(root, profile):
    request = _subject_request(root)
    if profile is not None:
        payload = json.loads(request.read_text())
        payload["model_profile_sha256"] = _model_profile_digest(profile)
        request.write_text(json.dumps(payload))
    return request


@pytest.mark.parametrize("priced", [False, True])
def test_late_request_failure_retains_only_accepted_usage(tmp_path, monkeypatch, priced):
    profile = _profile(priced=priced)
    request = _request(tmp_path / "subject", profile)
    model = LateFailureModel()
    checks = []
    original_check = UsageLedger.check_request

    def checked(ledger, *, require_complete=True):
        checks.append(require_complete)
        return original_check(ledger, require_complete=require_complete)

    monkeypatch.setattr(UsageLedger, "check_request", checked)
    with pytest.raises(EffectAdapterError, match="ModelRequestFailure") as caught:
        run_subject_adapter(request, model_runtime=model, model_profile=profile, timeout=10)
    assert caught.value.__cause__ is model.error
    assert model.calls == 4  # Three accepted responses and exactly one failed request.
    assert checks == [False] * 4  # Keep the original private-ledger path.
    raw = (request.parent / "receipt.failure.json").read_bytes()
    diagnostic = json.loads(raw)
    assert normalize_diagnostic(diagnostic) == diagnostic
    assert diagnostic["schema_version"] == "6"
    assert diagnostic["stage"] == "model" and diagnostic["code"] == "timeout"
    assert diagnostic["model_turns"] == 3 and diagnostic["tool_steps"] == 4
    assert diagnostic["accepted_usage"] == {**SUBTOTAL, "cost_micros": 84 if priced else None}
    assert diagnostic["usage_completeness"] == "partial"
    assert diagnostic["model_failure"]["reason"] == "transport_timeout"
    assert diagnostic["request_observation"]["phase"] == "open_response"
    assert diagnostic["transport_observation"]["last_milestone"] == "wait_response_headers"
    assert SECRET.encode() not in raw and len(raw) <= 4096
    assert not (request.parent / "receipt.json").exists()


@pytest.mark.parametrize("successful_turns,profiled", [(0, True), (3, False)])
def test_no_owned_accepted_subtotal_preserves_v5(tmp_path, successful_turns, profiled):
    profile = _profile() if profiled else None
    request = _request(tmp_path / "subject", profile)
    model = LateFailureModel(successful_turns)
    with pytest.raises(EffectAdapterError):
        run_subject_adapter(request, model_runtime=model, model_profile=profile)
    payload = json.loads((request.parent / "receipt.failure.json").read_bytes())
    assert payload["schema_version"] == "5"
    assert payload["model_turns"] == successful_turns
    assert "accepted_usage" not in payload and "usage_completeness" not in payload
    assert model.calls == successful_turns + 1


def test_private_accepted_snapshot_is_reset_for_a_reused_invocation(tmp_path):
    runtime = AgentLoopRuntime(LateFailureModel(), profile=_profile())
    assert InvocationDiagnostics().accepted_usage is None
    with pytest.raises(ModelRequestFailure):
        runtime.run("fixture", tmp_path)
    first = runtime.last_invocation
    assert first.accepted_usage.to_dict() == SUBTOTAL
    assert first.provider_requests == 4 and first.responses_received == 3
    assert not first.usage_complete and not runtime.session_history
    runtime.model = LateFailureModel(0)
    with pytest.raises(ModelRequestFailure):
        runtime.run("fixture again", tmp_path)
    assert runtime.last_invocation.accepted_usage is None
    assert runtime.last_invocation.provider_requests == 1
    assert runtime.last_invocation.responses_received == 0
    assert first.accepted_usage.to_dict() == SUBTOTAL


@pytest.mark.parametrize("checkpoint_after_rounds", [None, 1])
def test_staged_late_failure_keeps_all_accepted_phases(tmp_path, checkpoint_after_rounds):
    profile = _staged_profile()
    request = _request(tmp_path / "subject", profile)
    model = StagedSubject(failure="provider")
    config = _config(request, profile, checkpoint_after_rounds=checkpoint_after_rounds)
    with pytest.raises(EffectAdapterError):
        run_subject_adapter(
            request, model_runtime=model, model_profile=profile, max_steps=8,
            workflow_config=config,
        )
    payload = json.loads((request.parent / "receipt.failure.json").read_bytes())
    assert normalize_diagnostic(payload) == payload
    assert payload["schema_version"] == "6"
    assert payload["stage"] == "model" and payload["code"] == "model_failed"
    assert payload["model_turns"] == 2 and payload["tool_steps"] == 2
    assert payload["accepted_usage"] == {
        "input_tokens": 4, "output_tokens": 2, "total_tokens": 6,
        "cost_micros": 6, "rounds": 2,
    }
    assert payload["usage_completeness"] == "partial" and model.turn == 3
    assert not (request.parent / "receipt.json").exists()


def _v6(tmp_path):
    context = _context(tmp_path)
    return {**context.payload("model", "timeout", 3, 4, None), "schema_version": "6",
            "accepted_usage": dict(SUBTOTAL), "usage_completeness": "partial"}


@pytest.mark.parametrize("mutation", [
    "zero_rounds", "too_many_rounds", "too_few_rounds", "bool_rounds", "negative_tokens",
    "inconsistent_tokens", "unknown_field", "complete", "missing_field", "extra_usage",
    "negative_cost", "nan_cost", "runtime_stage", "budget_mixed", "oversized",
])
def test_v6_rejects_inconsistent_or_non_model_subtotals(tmp_path, mutation):
    value = _v6(tmp_path)
    usage = value["accepted_usage"]
    if mutation in {"zero_rounds", "too_many_rounds", "too_few_rounds", "bool_rounds"}:
        usage["rounds"] = {"zero_rounds": 0, "too_many_rounds": 4,
                           "too_few_rounds": 2, "bool_rounds": True}[mutation]
    elif mutation == "negative_tokens":
        usage["input_tokens"] = -1
    elif mutation == "inconsistent_tokens":
        usage["total_tokens"] += 1
    elif mutation == "unknown_field":
        value["endpoint"] = SECRET
    elif mutation == "complete":
        value["usage_completeness"] = "complete"
    elif mutation == "missing_field":
        del value["usage_completeness"]
    elif mutation == "extra_usage":
        usage["unknown_request_tokens"] = 0
    elif mutation in {"negative_cost", "nan_cost"}:
        usage["cost_micros"] = -1 if mutation == "negative_cost" else float("nan")
    elif mutation == "runtime_stage":
        value.update(stage="runtime", code="runtime_failed")
    elif mutation == "budget_mixed":
        value["budget"] = {}
    elif mutation == "oversized":
        usage.update(input_tokens=10**16, total_tokens=10**16 + usage["output_tokens"])
    with pytest.raises(ValueError):
        normalize_diagnostic(value)


@pytest.mark.parametrize("snapshot", [
    UsageSnapshot(0, 0, 0, None, 0), UsageSnapshot(60, 12, 73, None, 3),
    UsageSnapshot(60, 12, 72, None, 2), UsageSnapshot(10**16, 0, 10**16, None, 3),
    {"input_tokens": 60},
])
def test_invalid_optional_snapshot_keeps_legacy_failure(tmp_path, snapshot):
    context = _context(tmp_path)
    observer = SubjectDiagnosticObserver()
    observer.stage, observer.code = "model", "model_failed"
    observer.model_turns = 3
    observer.emit_failure(context, _timeout(), accepted_usage=snapshot)
    payload = json.loads((context.workspace / context.sidecar).read_bytes())
    assert payload["schema_version"] == "5"
    assert "accepted_usage" not in payload


def test_budget_v2_is_not_rewrapped_with_accepted_subtotal(tmp_path):
    context = _context(tmp_path)
    snapshot = UsageSnapshot(1, 1, 2, None, 1)
    error = ProfileBudgetFailure(BudgetFailureEvidence(
        "max_total_tokens", "exhausted", 2, snapshot, snapshot, True,
    ))
    observer = SubjectDiagnosticObserver()
    observer.model_turns = 1
    observer.emit_failure(context, error, accepted_usage=snapshot)
    payload = json.loads((context.workspace / context.sidecar).read_bytes())
    assert payload["schema_version"] == "2"
    assert normalize_diagnostic(payload) == payload
    forged = {**copy.deepcopy(payload), "schema_version": "6",
              "accepted_usage": snapshot.to_dict(), "usage_completeness": "partial"}
    with pytest.raises(ValueError):
        normalize_diagnostic(forged)


def test_optional_usage_publication_failure_preserves_original_error(tmp_path, monkeypatch):
    import lunar_evolution.subject_diagnostics as diagnostics

    request = _request(tmp_path / "subject", _profile())
    model = LateFailureModel()

    def refused(*args, **kwargs):
        raise OSError(SECRET)

    monkeypatch.setattr(diagnostics, "publish_diagnostic", refused)
    with pytest.raises(EffectAdapterError) as caught:
        run_subject_adapter(request, model_runtime=model, model_profile=_profile())
    assert caught.value.__cause__ is model.error and model.calls == 4
    assert not (request.parent / "receipt.json").exists()


def test_optional_usage_capture_failure_preserves_original_error(tmp_path, monkeypatch):
    request = _request(tmp_path / "subject", _profile())
    model = LateFailureModel()
    original = AgentLoopRuntime.last_invocation.fget

    def failed_after_request(runtime):
        if model.calls > model.successful_turns:
            raise OSError(SECRET)
        return original(runtime)

    monkeypatch.setattr(AgentLoopRuntime, "last_invocation", property(failed_after_request))
    with pytest.raises(EffectAdapterError) as caught:
        run_subject_adapter(request, model_runtime=model, model_profile=_profile())
    assert caught.value.__cause__ is model.error and model.calls == 4
    payload = json.loads((request.parent / "receipt.failure.json").read_bytes())
    assert payload["schema_version"] == "5" and "accepted_usage" not in payload
    assert not (request.parent / "receipt.json").exists()
