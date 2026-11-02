"""Input pauses retain bounded accepted usage without completing or scoring an attempt."""

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from test_deep_effect_trial import (
    _deep_config,
    _make_bound_subject_script,
    _make_case,
    _make_constant_harness_script,
    _write_baseline,
    _write_json,
)
from test_effect_trial import _fixture
from test_subject_accepted_usage import SUBTOTAL, _profile, _request
from test_subject_diagnostics import _context

from lunar_evolution.agent_loop import AgentInputRequired, AgentLoopRuntime
from lunar_evolution.cli import main
from lunar_evolution.deep_effect_trial import DeepEffectTrialRunner
from lunar_evolution.effect_adapters import EffectAdapterError, run_subject_adapter
from lunar_evolution.effect_trial import EffectTrialConfig, EffectTrialRunner
from lunar_evolution.model_profile import UsageLedger, UsageSnapshot
from lunar_evolution.runtime import ModelTurn, ToolCall
from lunar_evolution.subject_diagnostics import (
    MAX_BUDGET_VALUE,
    MAX_COUNTER,
    MAX_DIAGNOSTIC_BYTES,
    SubjectDiagnosticObserver,
    normalize_diagnostic,
)

SECRET = "INPUT-PAUSE-PRIVATE-QUESTION-OPTIONS-ID-SENTINEL"


class PausingModel:
    model = "gpt-5.6-sol"
    api_key = SECRET

    def __init__(self, *, before_response=False):
        self.calls = 0
        self.before_response = before_response
        self.pause = AgentInputRequired(SECRET, (SECRET,))

    def complete(self, messages, tools=(), timeout=None):
        self.calls += 1
        if self.before_response:
            raise self.pause
        assert self.calls <= 3, "an input pause must not trigger another request"
        if self.calls == 3:
            calls = (
                ToolCall(SECRET, "ask_user", {"question": SECRET, "options": [SECRET]}),
                ToolCall("after-pause", "write_file", {"path": "after-pause", "content": SECRET}),
            )
        else:
            calls = tuple(
                ToolCall(f"{self.calls}-{i}", "list_dir", {"path": "."})
                for i in range(2 if self.calls == 1 else 1)
            )
        return ModelTurn(
            SECRET, calls, response_model=self.model,
            usage={"input_tokens": 10 * self.calls, "output_tokens": 2 * self.calls,
                   "total_tokens": 12 * self.calls},
        )


def _pause_request(root, profile, mode):
    request = _request(root, profile)
    payload = json.loads(request.read_bytes())
    if mode == "deep_evolution":
        payload.update(mode=mode, round_index=1, outer_rounds=2, previous_evaluation=None,
                       receipt_path="receipts/001.json")
        request.write_text(json.dumps(payload))
    return request, payload


def _v8(context):
    return {
        **context.payload("runtime", "input_required", 3, 4, None),
        "schema_version": "8", "accepted_usage": dict(SUBTOTAL),
        "usage_completeness": "partial",
    }


@pytest.mark.parametrize("mode", ["normal", "deep_evolution"])
@pytest.mark.parametrize("accounting", ["nullable_cost", "priced", "unprofiled"])
def test_input_pause_cli_retains_only_accepted_usage(
    tmp_path, monkeypatch, capsys, mode, accounting,
):
    profile = None if accounting == "unprofiled" else _profile(priced=accounting == "priced")
    request, payload = _pause_request(tmp_path / "subject", profile, mode)
    model = PausingModel()
    monkeypatch.setattr("lunar_evolution.effect_adapters.OpenAICompatibleRuntime", lambda **kw: model)
    checks = []
    original_check = UsageLedger.check_request

    def checked(ledger, *, require_complete=True):
        checks.append(require_complete)
        return original_check(ledger, require_complete=require_complete)

    monkeypatch.setattr(UsageLedger, "check_request", checked)
    arguments = ["effect-subject", str(request), "--no-exec", "--json"]
    if profile is not None:
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps(profile.to_dict()))
        arguments.extend(["--model-profile", str(profile_path)])
    assert main(arguments) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": "subject runtime failed: AgentInputRequired"}
    assert model.calls == 3
    assert checks == ([] if profile is None else [False] * 3)
    receipt = request.parent / payload["receipt_path"]
    raw = receipt.with_suffix(".failure.json").read_bytes()
    diagnostic = json.loads(raw)
    assert normalize_diagnostic(diagnostic) == diagnostic
    assert diagnostic["stage"] == "runtime" and diagnostic["code"] == "input_required"
    assert diagnostic["http_status"] is None
    assert diagnostic["model_turns"] == 3 and diagnostic["tool_steps"] == 4
    assert diagnostic["mode"] == mode
    assert diagnostic["request_sha256"] == hashlib.sha256(request.read_bytes()).hexdigest()
    assert diagnostic["round_index"] == (1 if mode == "deep_evolution" else None)
    if profile is None:
        assert diagnostic["schema_version"] == "1"
        assert "accepted_usage" not in diagnostic and "usage_completeness" not in diagnostic
    else:
        assert diagnostic["schema_version"] == "8"
        assert diagnostic["accepted_usage"] == {
            **SUBTOTAL, "cost_micros": 84 if accounting == "priced" else None,
        }
        assert diagnostic["usage_completeness"] == "partial"
    assert SECRET.encode() not in raw and len(raw) <= MAX_DIAGNOSTIC_BYTES
    assert not receipt.exists() and not (request.parent / "after-pause").exists()
    assert not {"score", "usage", "status", "model_failure", "request_fingerprint"} & diagnostic.keys()


@pytest.mark.parametrize("mode", ["normal", "deep_evolution"])
def test_pause_before_first_response_preserves_schema1_and_original_error(tmp_path, mode):
    profile = _profile()
    request, payload = _pause_request(tmp_path / "subject", profile, mode)
    model = PausingModel(before_response=True)
    with pytest.raises(EffectAdapterError, match="AgentInputRequired") as caught:
        run_subject_adapter(request, model_runtime=model, model_profile=profile)
    assert caught.value.__cause__ is model.pause and model.calls == 1
    receipt = request.parent / payload["receipt_path"]
    diagnostic = json.loads(receipt.with_suffix(".failure.json").read_bytes())
    assert diagnostic["schema_version"] == "1"
    assert diagnostic["stage"] == "runtime" and diagnostic["code"] == "input_required"
    assert diagnostic["model_turns"] == 0 and diagnostic["tool_steps"] == 0
    assert "accepted_usage" not in diagnostic and not receipt.exists()


@pytest.mark.parametrize("deep", [False, True])
@pytest.mark.parametrize("snapshot", [
    UsageSnapshot(0, 0, 0, None, 1),
    UsageSnapshot(1, 0, 1, 0, 1),
    UsageSnapshot(MAX_BUDGET_VALUE, 0, MAX_BUDGET_VALUE, MAX_BUDGET_VALUE, MAX_COUNTER),
])
def test_schema8_accepts_bounded_partial_snapshots_and_detaches_usage(tmp_path, deep, snapshot):
    context = _context(tmp_path, deep=deep)
    observer = SubjectDiagnosticObserver()
    observer.model_turns = snapshot.rounds
    observer.emit_failure(context, AgentInputRequired(SECRET), accepted_usage=snapshot)
    raw = (context.workspace / context.sidecar).read_bytes()
    payload = json.loads(raw)
    assert payload == {
        **context.payload("runtime", "input_required", snapshot.rounds, 0, None),
        "schema_version": "8", "accepted_usage": snapshot.to_dict(),
        "usage_completeness": "partial",
    }
    normalized = normalize_diagnostic(payload)
    assert normalized == payload
    normalized["accepted_usage"]["rounds"] = 0
    assert payload["accepted_usage"]["rounds"] == snapshot.rounds
    assert len(raw) <= MAX_DIAGNOSTIC_BYTES and SECRET.encode() not in raw


@pytest.mark.parametrize("field,value", [
    ("schema_version", 8), ("stage", "model"), ("stage", "tool"),
    ("code", "timeout"), ("code", "runtime_failed"), ("http_status", 429),
    ("usage_completeness", "complete"), ("accepted_usage", None), ("accepted_usage", []),
    ("model_turns", 0), ("model_turns", True), ("tool_steps", MAX_COUNTER + 1),
    ("run_index", False), ("round_index", 1), ("request_sha256", "A" * 64),
])
def test_schema8_rejects_invalid_classification_and_base_fields(tmp_path, field, value):
    payload = _v8(_context(tmp_path))
    payload[field] = value
    with pytest.raises(ValueError):
        normalize_diagnostic(payload)


@pytest.mark.parametrize("field", ["accepted_usage", "usage_completeness", "model_turns"])
def test_schema8_rejects_missing_required_fields(tmp_path, field):
    payload = _v8(_context(tmp_path))
    del payload[field]
    with pytest.raises(ValueError):
        normalize_diagnostic(payload)


@pytest.mark.parametrize("field", [
    "budget", "model_failure", "request_observation", "transport_observation",
    "request_fingerprint", "overall_score", "usage", "status", "question",
])
def test_schema8_rejects_other_schemas_authority_and_private_fields(tmp_path, field):
    payload = _v8(_context(tmp_path))
    payload[field] = SECRET
    with pytest.raises(ValueError):
        normalize_diagnostic(payload)


@pytest.mark.parametrize("changes", [
    {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "rounds": 0},
    {"rounds": -1}, {"rounds": 2}, {"rounds": 4}, {"rounds": True},
    {"rounds": MAX_COUNTER + 1}, {"input_tokens": -1}, {"input_tokens": 60.0},
    {"output_tokens": True}, {"total_tokens": "72"}, {"total_tokens": 73},
    {"input_tokens": MAX_BUDGET_VALUE, "total_tokens": MAX_BUDGET_VALUE + 12},
    {"cost_micros": -1}, {"cost_micros": True}, {"cost_micros": float("nan")},
    {"cost_micros": MAX_BUDGET_VALUE + 1}, {"question": SECRET},
])
def test_schema8_rejects_malformed_or_inconsistent_usage(tmp_path, changes):
    payload = _v8(_context(tmp_path))
    payload["accepted_usage"].update(changes)
    with pytest.raises(ValueError):
        normalize_diagnostic(payload)


@pytest.mark.parametrize("field", list(SUBTOTAL))
def test_schema8_rejects_incomplete_usage(tmp_path, field):
    payload = _v8(_context(tmp_path))
    del payload["accepted_usage"][field]
    with pytest.raises(ValueError):
        normalize_diagnostic(payload)


@pytest.mark.parametrize("kind", [
    "missing", "mapping", "subclass", "missing_attribute", "projection_error",
    "zero", "negative", "mismatch",
    "boolean", "tokens", "token_bound", "round_bound", "cost_bound", "cost_type",
])
def test_invalid_optional_input_pause_snapshot_preserves_identical_schema1(tmp_path, kind):
    context = _context(tmp_path)
    observer = SubjectDiagnosticObserver()
    observer.model_turns = 3
    error = AgentInputRequired(SECRET)
    legacy = observer.failure(context, error)
    values = dict(SUBTOTAL)
    if kind == "zero":
        values.update(input_tokens=0, output_tokens=0, total_tokens=0, rounds=0)
    elif kind in {"negative", "mismatch", "boolean", "round_bound"}:
        values["rounds"] = {
            "negative": -1, "mismatch": 2, "boolean": True, "round_bound": MAX_COUNTER + 1,
        }[kind]
    elif kind == "tokens":
        values["total_tokens"] += 1
    elif kind == "token_bound":
        values.update(input_tokens=MAX_BUDGET_VALUE, total_tokens=MAX_BUDGET_VALUE + 12)
    elif kind == "cost_bound":
        values["cost_micros"] = MAX_BUDGET_VALUE + 1
    elif kind == "cost_type":
        values["cost_micros"] = SECRET
    snapshot = UsageSnapshot(**values)
    if kind == "missing":
        snapshot = None
    elif kind == "mapping":
        snapshot = values
    elif kind == "subclass":
        class ForeignUsage(UsageSnapshot):
            pass

        snapshot = ForeignUsage(**values)
    elif kind == "missing_attribute":
        object.__delattr__(snapshot, "cost_micros")
    elif kind == "projection_error":
        def failed_projection():
            raise RuntimeError(SECRET)

        object.__setattr__(snapshot, "to_dict", failed_projection)
    observer.emit_failure(context, error, accepted_usage=snapshot)
    raw = (context.workspace / context.sidecar).read_bytes()
    assert json.loads(raw) == legacy
    assert legacy["schema_version"] == "1" and SECRET.encode() not in raw


@pytest.mark.parametrize("version", ["1", "2", "3", "4", "5", "6", "7"])
def test_input_pause_subtotal_cannot_be_relabelled_as_a_legacy_schema(tmp_path, version):
    payload = _v8(_context(tmp_path))
    payload["schema_version"] = version
    if version == "7":
        payload.update(
            request_fingerprint={"body_bytes": 1, "body_sha256": "a" * 64},
            model_failure={"reason": "transport_timeout", "response_status": None},
        )
    with pytest.raises(ValueError):
        normalize_diagnostic(payload)


@pytest.mark.parametrize("failure", ["capture", "publication"])
def test_optional_pause_diagnostics_preserve_original_adapter_failure(tmp_path, monkeypatch, failure):
    profile = _profile()
    request = _request(tmp_path / "subject", profile)
    model = PausingModel()

    def unavailable(*args, **kwargs):
        raise OSError(SECRET)

    if failure == "publication":
        monkeypatch.setattr("lunar_evolution.subject_diagnostics.publish_diagnostic", unavailable)
    else:
        original = AgentLoopRuntime.last_invocation.fget

        def capture(runtime):
            if model.calls == 3 and original(runtime).tool_steps == 4:
                raise OSError(SECRET)
            return original(runtime)

        monkeypatch.setattr(AgentLoopRuntime, "last_invocation", property(capture))
    with pytest.raises(EffectAdapterError, match="AgentInputRequired") as caught:
        run_subject_adapter(request, model_runtime=model, model_profile=profile)
    assert isinstance(caught.value.__cause__, AgentInputRequired)
    assert caught.value.__cause__.question == SECRET and model.calls == 3
    if failure == "capture":
        payload = json.loads((request.parent / "receipt.failure.json").read_bytes())
        assert payload["schema_version"] == "1" and "accepted_usage" not in payload
    assert not (request.parent / "receipt.json").exists()
    assert not (request.parent / "after-pause").exists()


@pytest.mark.parametrize("mode", ["normal", "deep_evolution"])
@pytest.mark.parametrize("mutation", ["valid", "identity", "complete", "score", "zero_rounds"])
def test_input_pause_collection_preserves_failed_attempt_and_prior_score(tmp_path, mode, mutation):
    calls = []
    emitted = []

    def executor(command, *, cwd, env, timeout):
        request_path = Path(command[-1])
        request = json.loads(request_path.read_bytes())
        is_harness = "candidate_workspace" in request
        calls.append("harness" if is_harness else "subject")
        fail = not is_harness and (mode == "normal" or request["round_index"] == 2)
        if not fail:
            return subprocess.run(
                command, cwd=cwd, env=env, timeout=timeout, check=False, capture_output=True,
            )
        payload = {
            "schema_version": "8", "kind": "subject_failure", "mode": mode,
            "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
            "run_index": request["run_index"], "round_index": request.get("round_index"),
            "stage": "runtime", "code": "input_required", "model_turns": 3,
            "tool_steps": 4, "http_status": None, "accepted_usage": dict(SUBTOTAL),
            "usage_completeness": "partial",
        }
        if mutation == "identity":
            payload["request_sha256"] = "0" * 64
        elif mutation == "complete":
            payload["usage_completeness"] = "complete"
        elif mutation == "score":
            payload["overall_score"] = 1.0
        elif mutation == "zero_rounds":
            payload["accepted_usage"].update(input_tokens=0, output_tokens=0, total_tokens=0, rounds=0)
        sidecar = (cwd / request["receipt_path"]).with_suffix(".failure.json")
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(payload))
        emitted.append(copy.deepcopy(payload))
        return subprocess.CompletedProcess(command, 2)

    if mode == "normal":
        suite, baseline, public, subject, harness = _fixture(tmp_path)
        runner = EffectTrialRunner(
            suite, baseline, tmp_path / "trial", case_sources={"fixture_case": public},
            config=EffectTrialConfig(
                runs_per_case=1, timeout_seconds=10, requested_model="gpt-5.6-sol",
                subject_command=subject, harness_command=harness,
            ), process_executor=executor,
        )
    else:
        public, suite_data = _make_case(tmp_path)
        suite = _write_json(tmp_path / "suite.json", suite_data)
        baseline = _write_baseline(tmp_path, suite_data)
        subject = _make_bound_subject_script(tmp_path / "subject.py")
        harness = _make_constant_harness_script(tmp_path / "harness.py")
        runner = DeepEffectTrialRunner(
            suite, baseline, tmp_path / "trial", case_sources={"case-a": public},
            config=_deep_config(subject, harness, outer_rounds=2), process_executor=executor,
        )

    record = runner.run().to_dict()["cases"][0]["runs"][0]
    assert calls == (["subject"] if mode == "normal" else ["subject", "harness", "subject"])
    assert record["error_code"] == "process_nonzero_exit" and record["ready"] is False
    assert record["usage"] is None and record.get("cost_micros") is None
    if mode == "normal":
        assert record["overall_score"] is None and record["validity_score"] is None
    else:
        assert len(record["rounds"]) == 1 and record["rounds"][0]["overall_score"] == 0.5
    attempt = tmp_path / "trial" / record["attempt"]
    name = "subject-failure.json" if mode == "normal" else "subject-002-failure.json"
    diagnostic = attempt / "diagnostics" / name
    assert diagnostic.exists() is (mutation == "valid")
    if mutation == "valid":
        assert json.loads(diagnostic.read_bytes()) == emitted[0]
    receipt = "receipt.json" if mode == "normal" else "receipts/002.json"
    assert not (attempt / "subject" / receipt).exists()
