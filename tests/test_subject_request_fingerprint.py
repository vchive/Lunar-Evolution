"""Score-free failed-request fingerprints: strict readers and local fake collection."""

import copy
import hashlib
import json
import os
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
from test_subject_diagnostics import _context

from lunar_evolution.agent_loop import ProfileBudgetFailure
from lunar_evolution.deep_effect_trial import DeepEffectTrialRunner
from lunar_evolution.effect_trial import EffectTrialConfig, EffectTrialRunner
from lunar_evolution.http_transport import MAX_REQUEST_BYTES, TransportObservation
from lunar_evolution.model_profile import BudgetFailureEvidence, UsageSnapshot
from lunar_evolution.runtime import (
    ModelRequestFailure,
    ModelRequestFingerprint,
    ModelRequestObservation,
    RuntimeExecutionError,
)
from lunar_evolution.subject_diagnostics import (
    SubjectDiagnosticContext,
    SubjectDiagnosticObserver,
    normalize_diagnostic,
    publish_diagnostic,
)

SECRET = "REQUEST-FINGERPRINT-PRIVATE-SENTINEL"
BODY = ('{"messages":[{"role":"user","content":"' + SECRET + '月"}]}').encode()
FINGERPRINT = {"body_bytes": len(BODY), "body_sha256": hashlib.sha256(BODY).hexdigest()}
SUBTOTAL = {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11,
            "cost_micros": None, "rounds": 1}


def _model_error(*, fingerprint=True, timing=True, transport=True):
    error = ModelRequestFailure(SECRET, "transport_timeout")
    error.__cause__ = TimeoutError(SECRET)
    if fingerprint:
        error.request_fingerprint = ModelRequestFingerprint(**FINGERPRINT)
    if timing:
        error.observation = ModelRequestObservation("open_response", 12, 20)
    if transport:
        error.transport_observation = TransportObservation("wait_response_headers", 1, 3)
    return error


def _observer(*, rounds=0):
    observer = SubjectDiagnosticObserver()
    observer.stage, observer.code = "model", "model_failed"
    observer.model_turns = rounds
    return observer


def _legacy(context, version="5", *, partial=False):
    value = context.payload("model", "timeout", 1 if partial else 0, 0, None)
    value["schema_version"] = version
    if version in {"3", "4", "5"}:
        value["model_failure"] = {"reason": "transport_timeout", "response_status": None}
    if version in {"4", "5"}:
        value["request_observation"] = {"phase": "open_response", "elapsed_ms": 12,
                                        "request_timeout_ms": 20}
    if version == "5":
        value["transport_observation"] = {"last_milestone": "wait_response_headers",
                                          "http_exchange_index": 1, "elapsed_ms": 3}
    if partial:
        value.update(schema_version="6", accepted_usage=dict(SUBTOTAL), usage_completeness="partial")
    return normalize_diagnostic(value)


@pytest.mark.parametrize("legacy_version", ["3", "4", "5"])
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("body_bytes", [1, MAX_REQUEST_BYTES])
def test_v7_wraps_valid_model_failures_and_preserves_original_accounting(
    tmp_path, legacy_version, partial, body_bytes,
):
    original = _legacy(_context(tmp_path), legacy_version, partial=partial)
    fingerprint = {**FINGERPRINT, "body_bytes": body_bytes}
    value = {**original, "schema_version": "7", "request_fingerprint": fingerprint}
    frozen = json.dumps(value, sort_keys=True)
    assert normalize_diagnostic(json.loads(frozen)) == value
    assert json.dumps(value, sort_keys=True) == frozen
    assert SECRET not in frozen and len(frozen.encode()) <= 4096
    restored = {key: item for key, item in value.items() if key != "request_fingerprint"}
    restored["schema_version"] = original["schema_version"]
    assert normalize_diagnostic(restored) == original


@pytest.mark.parametrize("mutation", [
    "missing", "null", "list", "extra_fingerprint", "missing_bytes", "missing_digest",
    "zero", "negative", "too_large", "boolean", "float", "string_bytes",
    "uppercase", "short_digest", "nonhex", "bytes_digest", "null_digest",
    "extra_root", "score", "budget", "runtime_stage", "tool_stage", "invalid_code",
    "missing_model_failure", "partial_without_model_evidence", "downgrade",
    "partial_without_usage", "complete_usage",
])
def test_v7_rejects_unsafe_fingerprint_schema_and_authority_mixing(tmp_path, mutation):
    value = {**_legacy(_context(tmp_path)), "schema_version": "7",
             "request_fingerprint": dict(FINGERPRINT)}
    fingerprint = value["request_fingerprint"]
    if mutation == "missing":
        del value["request_fingerprint"]
    elif mutation in {"null", "list"}:
        value["request_fingerprint"] = None if mutation == "null" else []
    elif mutation == "extra_fingerprint":
        fingerprint["body"] = SECRET
    elif mutation == "missing_bytes":
        del fingerprint["body_bytes"]
    elif mutation == "missing_digest":
        del fingerprint["body_sha256"]
    elif mutation in {"zero", "negative", "too_large", "boolean", "float", "string_bytes"}:
        fingerprint["body_bytes"] = {"zero": 0, "negative": -1, "too_large": MAX_REQUEST_BYTES + 1,
                                     "boolean": True, "float": 1.0, "string_bytes": "1"}[mutation]
    elif mutation in {"uppercase", "short_digest", "nonhex", "bytes_digest", "null_digest"}:
        fingerprint["body_sha256"] = {"uppercase": "A" * 64, "short_digest": "a" * 63,
                                      "nonhex": "g" * 64, "bytes_digest": b"a" * 64,
                                      "null_digest": None}[mutation]
    elif mutation == "extra_root":
        value["endpoint"] = SECRET
    elif mutation == "score":
        value["overall_score"] = 1
    elif mutation == "budget":
        value["budget"] = {}
    elif mutation in {"runtime_stage", "tool_stage"}:
        value["stage"] = "runtime" if mutation == "runtime_stage" else "tool"
    elif mutation == "invalid_code":
        value["code"] = "tool_failed"
    elif mutation == "missing_model_failure":
        del value["model_failure"]
    elif mutation == "partial_without_model_evidence":
        for key in ("model_failure", "request_observation", "transport_observation"):
            del value[key]
        value.update(accepted_usage=dict(SUBTOTAL), usage_completeness="partial", model_turns=1)
    elif mutation == "downgrade":
        value["schema_version"] = "5"
    elif mutation == "partial_without_usage":
        value["usage_completeness"] = "partial"
    elif mutation == "complete_usage":
        value.update(accepted_usage=dict(SUBTOTAL), usage_completeness="complete", model_turns=1)
    with pytest.raises(ValueError):
        normalize_diagnostic(value)


@pytest.mark.parametrize("kind", ["missing", "none", "dict", "subtype", "missing_field", "invalid_bytes", "invalid_digest"])
def test_invalid_optional_typed_fingerprint_preserves_identical_legacy_failure(tmp_path, kind):
    context = _context(tmp_path)
    error = _model_error(fingerprint=False)
    observer = _observer()
    legacy = observer.failure(context, error)
    assert legacy["schema_version"] == "5"
    if kind == "missing":
        del error.request_fingerprint
    elif kind == "none":
        error.request_fingerprint = None
    elif kind == "dict":
        error.request_fingerprint = dict(FINGERPRINT)
    elif kind == "subtype":
        class ForeignFingerprint(ModelRequestFingerprint):
            pass

        error.request_fingerprint = ForeignFingerprint(**FINGERPRINT)
    elif kind == "missing_field":
        error.request_fingerprint = ModelRequestFingerprint(**FINGERPRINT)
        object.__delattr__(error.request_fingerprint, "body_bytes")
    else:
        error.request_fingerprint = ModelRequestFingerprint(
            True if kind == "invalid_bytes" else FINGERPRINT["body_bytes"],
            SECRET if kind == "invalid_digest" else FINGERPRINT["body_sha256"],
        )
    assert observer.failure(context, error) == legacy


@pytest.mark.parametrize("coarse", ["missing", "foreign", "invalid", "valid"])
@pytest.mark.parametrize("detail", ["missing", "foreign", "invalid", "valid"])
def test_optional_timing_or_transport_failure_cannot_suppress_valid_fingerprint(tmp_path, coarse, detail):
    context = _context(tmp_path)
    error = _model_error()
    if coarse == "missing":
        error.observation = None
    elif coarse == "foreign":
        error.observation = {"phase": "open_response"}
    elif coarse == "invalid":
        error.observation = ModelRequestObservation("validate_response", 12, 20)
    if detail == "missing":
        error.transport_observation = None
    elif detail == "foreign":
        error.transport_observation = {"body": SECRET}
    elif detail == "invalid":
        error.transport_observation = TransportObservation(SECRET, 1, 3)
    payload = _observer().failure(context, error)
    assert normalize_diagnostic(payload) == payload
    assert payload["schema_version"] == "7" and payload["request_fingerprint"] == FINGERPRINT
    assert payload["code"] == "timeout"
    assert payload["model_failure"] == {"reason": "transport_timeout", "response_status": None}
    assert ("request_observation" in payload) is (coarse == "valid")
    assert ("transport_observation" in payload) is (coarse == "valid" and detail == "valid")
    assert SECRET not in json.dumps(payload)


@pytest.mark.parametrize("outer_kind", ["no_fingerprint", "invalid_fingerprint", "invalid_evidence", "different_fingerprint"])
def test_fingerprint_is_bound_to_first_concrete_accepted_model_failure_node(tmp_path, outer_kind):
    inner = _model_error()
    outer = ModelRequestFailure(SECRET, "invalid_json", 200)
    outer.observation = ModelRequestObservation("validate_response", 4, 20)
    outer.__cause__ = inner
    if outer_kind == "invalid_fingerprint":
        outer.request_fingerprint = {"body_bytes": 1, "body_sha256": "b" * 64}
    elif outer_kind == "invalid_evidence":
        outer.evidence = {"reason": "invalid_json", "response_status": 200}
    elif outer_kind == "different_fingerprint":
        outer.request_fingerprint = ModelRequestFingerprint(1, "b" * 64)
    payload = _observer().failure(_context(tmp_path), outer)
    if outer_kind == "different_fingerprint":
        assert payload["schema_version"] == "7"
        assert payload["request_fingerprint"] == {"body_bytes": 1, "body_sha256": "b" * 64}
    else:
        assert payload["schema_version"] == ("1" if outer_kind == "invalid_evidence" else "4")
        assert "request_fingerprint" not in payload
    assert "transport_observation" not in payload


@pytest.mark.parametrize("depth", [0, 7, 8])
def test_fingerprint_obeys_existing_bounded_cause_traversal(tmp_path, depth):
    error = _model_error()
    for _ in range(depth):
        wrapper = RuntimeExecutionError(SECRET)
        wrapper.__cause__ = error
        error = wrapper
    payload = _observer().failure(_context(tmp_path), error)
    assert payload["schema_version"] == ("7" if depth <= 7 else "1")
    assert ("request_fingerprint" in payload) is (depth <= 7)


def test_foreign_failure_class_cannot_supply_authoritative_fingerprint(tmp_path):
    class ForeignFailure(ModelRequestFailure):
        pass

    error = ForeignFailure(SECRET, "transport_timeout")
    error.request_fingerprint = ModelRequestFingerprint(**FINGERPRINT)
    payload = _observer().failure(_context(tmp_path), error)
    assert payload["schema_version"] == "1" and "request_fingerprint" not in payload


@pytest.mark.parametrize("partial", [False, True])
def test_fingerprint_publication_preserves_partial_usage_and_original_error(tmp_path, partial):
    context = _context(tmp_path)
    observer = _observer(rounds=1 if partial else 0)
    error = _model_error()
    cause = error.__cause__
    observer.emit_failure(context, error, accepted_usage=UsageSnapshot(**SUBTOTAL) if partial else None)
    raw = (context.workspace / context.sidecar).read_bytes()
    payload = json.loads(raw)
    assert error.__cause__ is cause
    assert normalize_diagnostic(payload) == payload
    assert payload["schema_version"] == "7" and payload["request_fingerprint"] == FINGERPRINT
    assert ("accepted_usage" in payload) is partial
    if partial:
        assert payload["accepted_usage"] == SUBTOTAL and payload["usage_completeness"] == "partial"
    assert SECRET.encode() not in raw and len(raw) <= 4096
    assert not (context.workspace / "receipt.json").exists()


@pytest.mark.parametrize("with_model_cause", [False, True])
def test_budget_failure_cannot_borrow_fingerprint_or_be_upgraded_to_v7(tmp_path, with_model_cause):
    context = _context(tmp_path)
    snapshot = UsageSnapshot(1, 1, 2, None, 1)
    error = ProfileBudgetFailure(BudgetFailureEvidence(
        "max_total_tokens", "exhausted", 2, snapshot, snapshot, True,
    ))
    error.request_fingerprint = ModelRequestFingerprint(**FINGERPRINT)
    if with_model_cause:
        error.__cause__ = _model_error()
    observer = SubjectDiagnosticObserver()
    observer.emit_failure(context, error, accepted_usage=snapshot)
    payload = json.loads((context.workspace / context.sidecar).read_bytes())
    assert payload["schema_version"] == ("1" if with_model_cause else "2")
    assert "request_fingerprint" not in payload
    assert normalize_diagnostic(payload) == payload
    with pytest.raises(ValueError):
        normalize_diagnostic({**payload, "schema_version": "7", "request_fingerprint": dict(FINGERPRINT)})


@pytest.mark.parametrize("version", ["1", "2", "3", "4", "5", "6"])
def test_legacy_diagnostic_wire_is_unchanged_without_fingerprint(tmp_path, version):
    context = _context(tmp_path)
    if version == "2":
        value = context.payload("runtime", "budget_exceeded", 0, 0, None)
        value.update(schema_version="2", budget={
            "limit": "max_total_tokens", "state": "exceeded", "maximum": 10,
            "accepted_usage": None, "observed_usage": None,
            "trigger_recorded": False, "usage_completeness": "partial",
        })
    else:
        value = _legacy(context, "5" if version == "6" else version, partial=version == "6")
    frozen = json.dumps(value, sort_keys=True)
    assert normalize_diagnostic(json.loads(frozen)) == value
    assert json.dumps(value, sort_keys=True) == frozen
    assert "request_fingerprint" not in value


@pytest.mark.parametrize("mode", ["normal", "deep_evolution"])
@pytest.mark.parametrize("partial", [False, True])
def test_failed_subject_collects_v7_without_harness_retry_or_score(tmp_path, mode, partial):
    invocations = []
    emitted = []

    def executor(command, *, cwd, env, timeout):
        del env, timeout
        invocations.append(cwd.name)
        assert cwd.name == "subject", "failed subject must not dispatch a score harness"
        request_path = Path(command[-1])
        raw = request_path.read_bytes()
        request = json.loads(raw)
        context = SubjectDiagnosticContext.from_request(cwd, request, hashlib.sha256(raw).hexdigest())
        observer = _observer(rounds=1 if partial else 0)
        observer.emit_failure(context, _model_error(), accepted_usage=UsageSnapshot(**SUBTOTAL) if partial else None)
        emitted.append((cwd / context.sidecar).read_bytes())
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
        public, suite = _make_case(tmp_path)
        runner = DeepEffectTrialRunner(
            _write_json(tmp_path / "suite.json", suite), _write_baseline(tmp_path, suite),
            tmp_path / "trial", case_sources={"case-a": public},
            config=_deep_config(_make_bound_subject_script(tmp_path / "subject.py"),
                                _make_constant_harness_script(tmp_path / "harness.py")),
            process_executor=executor,
        )
    record = runner.run().to_dict()["cases"][0]["runs"][0]
    assert invocations == ["subject"] and len(emitted) == 1
    assert record["error_code"] == "process_nonzero_exit" and record["ready"] is False
    assert all(record[key] is None for key in ("usage", "validity_score", "overall_score"))
    assert record.get("cost_micros") is None
    attempt = tmp_path / "trial" / record["attempt"]
    filename = "subject-failure.json" if mode == "normal" else "subject-001-failure.json"
    collected = attempt / "diagnostics" / filename
    assert collected.read_bytes() == emitted[0]
    payload = json.loads(emitted[0])
    assert payload["schema_version"] == "7" and payload["request_fingerprint"] == FINGERPRINT
    assert ("accepted_usage" in payload) is partial
    assert payload["mode"] == mode
    assert SECRET not in emitted[0].decode()
    assert not (attempt / "harness").exists()
    receipt = "receipt.json" if mode == "normal" else "receipts/001.json"
    assert not (attempt / "subject" / receipt).exists()


@pytest.mark.parametrize("deep", [False, True])
@pytest.mark.parametrize("unsafe", ["stale_identity", "oversized", "symlink", "hardlink"])
def test_v7_collection_keeps_existing_identity_and_safe_file_checks(tmp_path, deep, unsafe):
    context = _context(tmp_path, deep=deep)
    value = {**_legacy(context), "schema_version": "7", "request_fingerprint": dict(FINGERPRINT)}
    source = context.workspace / context.sidecar
    source.parent.mkdir(exist_ok=True)
    if unsafe == "stale_identity":
        value["request_sha256"] = "b" * 64
        source.write_text(json.dumps(value))
    elif unsafe == "oversized":
        source.write_text(json.dumps(value) + " " * 4096)
    elif unsafe in {"symlink", "hardlink"}:
        original = tmp_path / "original.json"
        original.write_text(json.dumps(value))
        if unsafe == "symlink":
            source.symlink_to(original)
        else:
            os.link(original, source)
    context.collect()
    assert not (context.workspace.parent / "diagnostics").exists()


def test_v7_publication_rejects_scores_without_overwriting_evidence(tmp_path):
    context = _context(tmp_path)
    value = {**_legacy(context), "schema_version": "7", "request_fingerprint": dict(FINGERPRINT)}
    invalid = copy.deepcopy(value)
    invalid["request_fingerprint"]["score"] = 1
    with pytest.raises(ValueError):
        publish_diagnostic(context.workspace, context.sidecar, invalid)
    assert not (context.workspace / context.sidecar).exists()
    publish_diagnostic(context.workspace, context.sidecar, value)
    raw = (context.workspace / context.sidecar).read_bytes()
    with pytest.raises(OSError):
        publish_diagnostic(context.workspace, context.sidecar, value)
    assert (context.workspace / context.sidecar).read_bytes() == raw
