"""Controller-owned preparation details from fresh local probe fixtures only."""
from __future__ import annotations

import json
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_synthetic_input_format import (
    _audit,
    _compile,
    _contract,
    _envelope,
    _Runtime,
    _track_harness,
)

from lunar_evolution import candidate_execution_runner as runner
from lunar_evolution import evaluator_bundle as bundle
from lunar_evolution.evaluator_diagnostics import EvaluatorPreparationDiagnostic as Diagnostic
from lunar_evolution.runtime import RuntimeResult

ROLES = ["compiler", "audit"]
MODES = ["candidate", "snapshot"]
SECRET = "fresh-private-output-content"
PROBE_REASONS = [
    "output_schema_invalid", "file_set_invalid", "process_failed", "report_invalid",
    "validity_mismatch", "constraint_code_missing",
]


def _stage(role, boundary="preflight"):
    return f"{'auditor' if role == 'audit' else 'compiler'}_{boundary}"


def _expected(stage, reason, probe=None, input_index=None, order=None):
    return {"schema_version": "1", "stage": stage, "reason": reason,
            "probe_index": probe, "input_index": input_index, "order_index": order}


@pytest.mark.parametrize("stage", ["compiler_response", "auditor_response"])
def test_response_diagnostic_has_only_fixed_fields_and_round_trips(stage):
    value = Diagnostic(stage, "response_invalid")
    assert value.to_dict() == _expected(stage, "response_invalid")
    assert Diagnostic.from_dict(value.to_dict()) == value
    with pytest.raises(FrozenInstanceError):
        value.reason = "secret"


@pytest.mark.parametrize("stage", ["compiler_preflight", "auditor_preflight"])
@pytest.mark.parametrize("reason,probe,input_index,order", [
    ("input_format_invalid", 64, 32, None),
    *((reason, 64, None, None) for reason in PROBE_REASONS),
    ("score_order_mismatch", None, None, 64),
    ("evidence_changed", None, None, None),
    ("evidence_changed", 64, None, None),
    ("preflight_failed", None, None, None),
    ("preflight_failed", 64, None, None),
])
def test_preflight_diagnostic_round_trips_boundary_indices(
    stage, reason, probe, input_index, order,
):
    value = Diagnostic(stage, reason, probe, input_index, order)
    assert value.to_dict() == _expected(stage, reason, probe, input_index, order)
    assert Diagnostic.from_dict(value.to_dict()) == value


@pytest.mark.parametrize("field,invalid", [
    ("stage", "provider_wait"), ("stage", "compiler"), ("stage", None), ("stage", []),
    ("reason", "timeout"), ("reason", SECRET), ("reason", True), ("reason", {}),
    ("schema_version", 1), ("schema_version", True), ("schema_version", "2"),
    ("schema_version", None),
])
def test_diagnostic_rejects_unknown_or_wrongly_typed_identity(field, invalid):
    value = _expected("compiler_preflight", "input_format_invalid", 1, 1)
    value[field] = invalid
    with pytest.raises(ValueError):
        Diagnostic.from_dict(value)


@pytest.mark.parametrize("field,maximum", [
    ("probe_index", 64), ("input_index", 32), ("order_index", 64),
])
@pytest.mark.parametrize("invalid", [True, False, 1.0, 0, -1, "1", [], {}])
def test_diagnostic_indices_are_strict_bounded_integers(field, maximum, invalid):
    del maximum
    value = (_expected("compiler_preflight", "score_order_mismatch", order=1)
             if field == "order_index"
             else _expected("compiler_preflight", "input_format_invalid", 1, 1))
    value[field] = invalid
    with pytest.raises(ValueError):
        Diagnostic.from_dict(value)


@pytest.mark.parametrize("field,maximum", [
    ("probe_index", 64), ("input_index", 32), ("order_index", 64),
])
def test_diagnostic_indices_reject_values_above_capacity(field, maximum):
    value = (_expected("compiler_preflight", "score_order_mismatch", order=1)
             if field == "order_index"
             else _expected("compiler_preflight", "input_format_invalid", 1, 1))
    value[field] = maximum + 1
    with pytest.raises(ValueError):
        Diagnostic.from_dict(value)


@pytest.mark.parametrize("stage,reason,probe,input_index,order", [
    ("compiler_response", "input_format_invalid", 1, 1, None),
    ("auditor_response", "response_invalid", 1, None, None),
    ("compiler_response", "response_invalid", None, 1, None),
    ("compiler_response", "response_invalid", None, None, 1),
    ("compiler_preflight", "response_invalid", None, None, None),
    ("auditor_preflight", "input_format_invalid", None, 1, None),
    ("compiler_preflight", "input_format_invalid", 1, None, None),
    ("compiler_preflight", "input_format_invalid", 1, 1, 1),
    *(("compiler_preflight", reason, None, None, None) for reason in PROBE_REASONS),
    *(("auditor_preflight", reason, 1, 1, None) for reason in PROBE_REASONS),
    *(("auditor_preflight", reason, 1, None, 1) for reason in PROBE_REASONS),
    ("compiler_preflight", "score_order_mismatch", None, None, None),
    ("compiler_preflight", "score_order_mismatch", 1, None, 1),
    ("compiler_preflight", "score_order_mismatch", None, 1, 1),
    ("compiler_preflight", "evidence_changed", 1, 1, None),
    ("compiler_preflight", "evidence_changed", None, None, 1),
    ("compiler_preflight", "preflight_failed", None, 1, None),
    ("compiler_preflight", "preflight_failed", None, None, 1),
])
def test_diagnostic_rejects_inapplicable_index_relationships(
    stage, reason, probe, input_index, order,
):
    with pytest.raises(ValueError):
        Diagnostic(stage, reason, probe, input_index, order)


@pytest.mark.parametrize("key", list(_expected("compiler_response", "response_invalid")))
def test_diagnostic_rejects_missing_fields(key):
    value = _expected("compiler_response", "response_invalid")
    del value[key]
    with pytest.raises(ValueError):
        Diagnostic.from_dict(value)


@pytest.mark.parametrize("value", [None, [], "{}", 1, True])
def test_diagnostic_rejects_nonobject_payloads(value):
    with pytest.raises(ValueError):
        Diagnostic.from_dict(value)


def test_diagnostic_rejects_extra_fields_and_revalidates_mutated_instances():
    value = _expected("compiler_response", "response_invalid")
    with pytest.raises(ValueError):
        Diagnostic.from_dict({**value, "exception": SECRET})
    diagnostic = Diagnostic.from_dict(value)
    object.__setattr__(diagnostic, "reason", SECRET)
    with pytest.raises(ValueError):
        diagnostic.to_dict()
    with pytest.raises(ValueError):
        bundle.EvaluatorPreparationError("old error message", diagnostic)


def test_diagnostic_rejects_mapping_subclasses_and_enum_subclasses():
    class CustomDict(dict):
        pass

    class CustomString(str):
        pass

    with pytest.raises(ValueError):
        Diagnostic.from_dict(CustomDict(_expected("compiler_response", "response_invalid")))
    with pytest.raises(ValueError):
        Diagnostic(CustomString("compiler_response"), "response_invalid")
    with pytest.raises(ValueError):
        Diagnostic("compiler_response", CustomString("response_invalid"))


def test_typed_exception_requires_a_valid_exact_diagnostic_and_copies_it():
    diagnostic = Diagnostic("compiler_response", "response_invalid")
    failure = bundle.EvaluatorPreparationError("compatible error", diagnostic)
    assert isinstance(failure, bundle.EvaluatorBundleError)
    assert str(failure) == "compatible error"
    assert failure.diagnostic == diagnostic
    assert failure.diagnostic is not diagnostic
    with pytest.raises(TypeError):
        bundle.EvaluatorPreparationError("error", diagnostic.to_dict())

    class DiagnosticSubclass(Diagnostic):
        pass

    with pytest.raises(TypeError):
        bundle.EvaluatorPreparationError(
            "error", DiagnosticSubclass("compiler_response", "response_invalid"),
        )


def _assert_failed(root, runtime, invocation, role, expected, *, second_input=False):
    with pytest.raises(bundle.EvaluatorPreparationError) as caught:
        _compile(root, runtime, invocation, second_input=second_input)
    error = caught.value
    assert type(error) is bundle.EvaluatorPreparationError
    assert error.diagnostic.to_dict() == expected
    rendered = json.dumps(error.diagnostic.to_dict())
    for forbidden in (SECRET, str(root), "limit.json", "nonnegative", "small", "large"):
        assert forbidden not in rendered
    assert runtime.calls == (["compiler"] if role == "compiler" else ["compiler", "audit"])
    assert not (root / "evaluator-bundle").exists()
    assert not list(root.glob(".evaluator-bundle-*"))
    assert (root / "data/raw/limit.json").read_bytes() == b'{"limit":50}\n'
    return error


@pytest.mark.parametrize("invocation", MODES)
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("malformation", ["json", "shape", "probes", "coverage", "runtime_result"])
def test_direct_response_failures_are_typed_without_response_content(
    tmp_path, invocation, role, malformation,
):
    envelope = _envelope(invocation)
    runtime = _Runtime(envelope, _audit(envelope))
    original = runtime.run

    def respond(prompt, workspace, timeout=None):
        result = original(prompt, workspace, timeout)
        if runtime.calls[-1] != role:
            return result
        if malformation == "json":
            return RuntimeResult("broken JSON " + SECRET)
        if malformation == "runtime_result":
            return {"text": SECRET}
        payload = json.loads(result.text)
        if malformation == "shape":
            payload["private_extra"] = SECRET
        elif malformation == "probes":
            payload["probes"][0]["files"] = []
        else:
            payload["constraint_coverage"] = []
        return RuntimeResult(json.dumps(payload))

    runtime.run = respond
    reason = "response_invalid"
    if role == "audit" and malformation != "runtime_result":
        reason = (
            "response_probes_invalid" if malformation == "probes" else
            "response_suite_invalid" if malformation == "coverage" else
            "response_envelope_invalid"
        )
    _assert_failed(tmp_path, runtime, invocation, role,
                   _expected(_stage(role, "response"), reason))


@pytest.mark.parametrize("invocation", MODES)
def test_invalid_compiler_source_has_coarse_response_diagnostic(tmp_path, invocation):
    envelope = _envelope(invocation)
    envelope["evaluator_source"] = "import subprocess\n# " + SECRET
    runtime = _Runtime(envelope, _audit(envelope))
    _assert_failed(tmp_path, runtime, invocation, "compiler",
                   _expected("compiler_response", "response_invalid"))


@pytest.mark.parametrize("invocation", MODES)
@pytest.mark.parametrize("role", ROLES)
def test_late_input_format_failure_identifies_contract_position_before_any_suite_process(
    tmp_path, monkeypatch, invocation, role,
):
    envelope = _envelope(invocation, second_input=True)
    audit = _audit(envelope)
    selected = envelope if role == "compiler" else audit
    selected["probes"][2]["files"][2]["content"] = "id,id\n" + SECRET + ",x\n"
    runtime = _Runtime(envelope, audit)
    calls = _track_harness(monkeypatch, invocation)
    _assert_failed(tmp_path, runtime, invocation, role,
                   _expected(_stage(role), "input_format_invalid", 3, 2), second_input=True)
    assert calls == ([] if role == "compiler" else [".compiler-preflight"] * 3)


@pytest.mark.parametrize("invocation", MODES)
@pytest.mark.parametrize("role", ROLES)
def test_direct_preflight_admits_whole_suite_before_creating_any_workspace(
    tmp_path, monkeypatch, invocation, role,
):
    envelope = _envelope(invocation, second_input=True)
    envelope["probes"][2]["files"][2]["content"] = "duplicate,duplicate\n"
    contract = _contract(second_input=True)
    suite = bundle._parse_envelope(json.dumps(envelope), contract,
                                   invocation=invocation).probe_suite()
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text(envelope["evaluator_source"])
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: pytest.fail("created probe workspace"))
    with pytest.raises(bundle.EvaluatorPreparationError) as caught:
        bundle._preflight(evaluator, suite, contract, tmp_path, 2,
                          label=role, invocation=invocation)
    assert caught.value.diagnostic.to_dict() == _expected(
        _stage(role), "input_format_invalid", 3, 2,
    )


@pytest.mark.parametrize("invocation", MODES)
@pytest.mark.parametrize("role", ROLES)
def test_output_schema_failure_reports_probe_position(tmp_path, invocation, role):
    envelope = _envelope(invocation)
    audit = _audit(envelope)
    selected = envelope if role == "compiler" else audit
    selected["probes"][1]["files"][1]["content"] = json.dumps({SECRET: 3})
    runtime = _Runtime(envelope, audit)
    _assert_failed(tmp_path, runtime, invocation, role,
                   _expected(_stage(role), "output_schema_invalid", 2))


@pytest.mark.parametrize("role", ROLES)
def test_snapshot_undeclared_file_failure_reports_probe_position(tmp_path, role):
    envelope = _envelope("snapshot")
    audit = _audit(envelope)
    selected = envelope if role == "compiler" else audit
    selected["probes"][1]["files"].append({"path": "output/extra.json", "content": SECRET})
    runtime = _Runtime(envelope, audit)
    _assert_failed(tmp_path, runtime, "snapshot", role,
                   _expected(_stage(role), "file_set_invalid", 2))


def _intercept_process(monkeypatch, invocation, role, probe, action):
    owner = runner if invocation == "snapshot" else bundle.subprocess
    name = "_bounded_process_bytes" if invocation == "snapshot" else "run"
    original = getattr(owner, name)

    def intercept(*args, **kwargs):
        workspace = Path(kwargs["cwd"])
        if workspace.parent.name != f".{role}-preflight" or workspace.name != probe:
            return original(*args, **kwargs)
        result = original(*args, **kwargs)
        stdout = result[0] if invocation == "snapshot" else result.stdout.encode()
        changed = action(stdout, workspace)
        if invocation == "snapshot":
            return (changed, *result[1:])
        return SimpleNamespace(stdout=changed.decode(), stderr=result.stderr,
                               returncode=result.returncode)

    monkeypatch.setattr(owner, name, intercept)


@pytest.mark.parametrize("invocation", MODES)
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("reason,probe,probe_index", [
    ("report_invalid", "large", 2),
    ("validity_mismatch", "large", 2),
    ("constraint_code_missing", "negative", 3),
])
def test_native_report_checks_have_distinct_typed_reasons(
    tmp_path, monkeypatch, invocation, role, reason, probe, probe_index,
):
    def alter(content, workspace):
        if reason == "report_invalid":
            return ("not JSON " + SECRET).encode()
        payload = json.loads(content)
        if reason == "validity_mismatch":
            payload.update(validity=0, quality=None, combined_score=0,
                           error_info=[{"code": "different", "message": SECRET}])
        else:
            payload["error_info"] = [{"code": "different", "message": SECRET}]
        return json.dumps(payload).encode()

    _intercept_process(monkeypatch, invocation, role, probe, alter)
    envelope = _envelope(invocation)
    _assert_failed(tmp_path, _Runtime(envelope, _audit(envelope)), invocation, role,
                   _expected(_stage(role), reason, probe_index))


@pytest.mark.parametrize("invocation", MODES)
@pytest.mark.parametrize("role", ROLES)
def test_process_start_error_is_typed_and_does_not_parse_exception_prose(
    tmp_path, monkeypatch, invocation, role,
):
    def fail(content, workspace):
        raise OSError("report_invalid validity_mismatch " + SECRET)

    _intercept_process(monkeypatch, invocation, role, "large", fail)
    envelope = _envelope(invocation)
    _assert_failed(tmp_path, _Runtime(envelope, _audit(envelope)), invocation, role,
                   _expected(_stage(role), "process_failed", 2))


@pytest.mark.parametrize("invocation", MODES)
@pytest.mark.parametrize("role", ROLES)
def test_unsuccessful_process_result_has_coarse_process_reason(
    tmp_path, monkeypatch, invocation, role,
):
    owner = runner if invocation == "snapshot" else bundle.subprocess
    name = "_bounded_process_bytes" if invocation == "snapshot" else "run"
    original = getattr(owner, name)

    def failed(*args, **kwargs):
        workspace = Path(kwargs["cwd"])
        if workspace.parent.name == f".{role}-preflight" and workspace.name == "large":
            if invocation == "snapshot":
                return SECRET.encode(), b"", "failed", 1, None
            return SimpleNamespace(stdout=SECRET, stderr="", returncode=1)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, failed)
    envelope = _envelope(invocation)
    _assert_failed(tmp_path, _Runtime(envelope, _audit(envelope)), invocation, role,
                   _expected(_stage(role), "process_failed", 2))


@pytest.mark.parametrize("role", ROLES)
def test_candidate_timeout_is_process_failure(tmp_path, monkeypatch, role):
    def fail(content, workspace):
        raise subprocess.TimeoutExpired([SECRET], 2)

    _intercept_process(monkeypatch, "candidate", role, "large", fail)
    envelope = _envelope("candidate")
    _assert_failed(tmp_path, _Runtime(envelope, _audit(envelope)), "candidate", role,
                   _expected(_stage(role), "process_failed", 2))


@pytest.mark.parametrize("role", ROLES)
def test_candidate_undecodable_stdout_is_report_failure(tmp_path, monkeypatch, role):
    def fail(content, workspace):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, SECRET)

    _intercept_process(monkeypatch, "candidate", role, "large", fail)
    envelope = _envelope("candidate")
    _assert_failed(tmp_path, _Runtime(envelope, _audit(envelope)), "candidate", role,
                   _expected(_stage(role), "report_invalid", 2))


@pytest.mark.parametrize("role", ROLES)
def test_candidate_output_limit_is_process_failure(tmp_path, monkeypatch, role):
    def overflow(content, workspace):
        return b"x" * (bundle.MAX_EVALUATOR_OUTPUT_BYTES + 1)

    _intercept_process(monkeypatch, "candidate", role, "large", overflow)
    envelope = _envelope("candidate")
    _assert_failed(tmp_path, _Runtime(envelope, _audit(envelope)), "candidate", role,
                   _expected(_stage(role), "process_failed", 2))


@pytest.mark.parametrize("role", ROLES)
def test_snapshot_timeout_status_remains_coarse_process_failure(tmp_path, monkeypatch, role):
    original = runner._bounded_process_bytes

    def timed_out(*args, **kwargs):
        workspace = Path(kwargs["cwd"])
        if workspace.parent.name == f".{role}-preflight" and workspace.name == "large":
            return b"", b"", "timed_out", None, "process_timed_out"
        return original(*args, **kwargs)

    monkeypatch.setattr(runner, "_bounded_process_bytes", timed_out)
    envelope = _envelope("snapshot")
    _assert_failed(tmp_path, _Runtime(envelope, _audit(envelope)), "snapshot", role,
                   _expected(_stage(role), "process_failed", 2))


@pytest.mark.parametrize("invocation", MODES)
@pytest.mark.parametrize("role", ROLES)
def test_failed_score_order_reports_order_position_not_probe_position(tmp_path, invocation, role):
    envelope = _envelope(invocation)
    audit = _audit(envelope)
    selected = envelope if role == "compiler" else audit
    selected["score_order"].append({"better": "small", "worse": "large"})
    runtime = _Runtime(envelope, audit)
    _assert_failed(tmp_path, runtime, invocation, role,
                   _expected(_stage(role), "score_order_mismatch", order=2))


@pytest.mark.parametrize("role", ROLES)
def test_snapshot_probe_evidence_mutation_reports_probe_position(tmp_path, monkeypatch, role):
    def mutate(content, workspace):
        (workspace / "request.json").write_text(SECRET)
        return content

    _intercept_process(monkeypatch, "snapshot", role, "large", mutate)
    envelope = _envelope("snapshot")
    _assert_failed(tmp_path, _Runtime(envelope, _audit(envelope)), "snapshot", role,
                   _expected(_stage(role), "evidence_changed", 2))


@pytest.mark.parametrize("invocation", MODES)
@pytest.mark.parametrize("role", ROLES)
def test_bundle_evidence_mutation_has_stage_without_invented_probe_index(
    tmp_path, monkeypatch, invocation, role,
):
    original = bundle._preflight

    def mutate(*args, **kwargs):
        original(*args, **kwargs)
        if kwargs["label"] == role:
            (args[3] / "objective.md").write_text(SECRET)

    monkeypatch.setattr(bundle, "_preflight", mutate)
    envelope = _envelope(invocation)
    _assert_failed(tmp_path, _Runtime(envelope, _audit(envelope)), invocation, role,
                   _expected(_stage(role), "evidence_changed"))


@pytest.mark.parametrize("invocation", MODES)
@pytest.mark.parametrize("role", ROLES)
def test_unclassified_local_failure_stays_coarse_without_message_classification(
    tmp_path, monkeypatch, invocation, role,
):
    name = "_snapshot_probe" if invocation == "snapshot" else "_run_evaluator"
    original = getattr(bundle, name)

    def fail(*args, **kwargs):
        workspace = args[3] if invocation == "snapshot" else args[1].parent
        if workspace.parent.name == f".{role}-preflight":
            raise ValueError("input_format_invalid process_failed " + SECRET)
        return original(*args, **kwargs)

    monkeypatch.setattr(bundle, name, fail)
    envelope = _envelope(invocation)
    _assert_failed(tmp_path, _Runtime(envelope, _audit(envelope)), invocation, role,
                   _expected(_stage(role), "preflight_failed"))


@pytest.mark.parametrize("role", ROLES)
def test_provider_exception_keeps_runtime_failure_separate_from_local_diagnostic(tmp_path, role):
    envelope = _envelope("candidate")
    runtime = _Runtime(envelope, _audit(envelope))
    original = runtime.run

    def fail(prompt, workspace, timeout=None):
        result = original(prompt, workspace, timeout)
        if runtime.calls[-1] == role:
            raise RuntimeError("process_failed " + SECRET)
        return result

    runtime.run = fail
    with pytest.raises(bundle.EvaluatorBundleRuntimeError) as caught:
        _compile(tmp_path, runtime, "candidate")
    assert not hasattr(caught.value, "diagnostic")
    assert not list(tmp_path.glob(".evaluator-bundle-*"))
    assert not (tmp_path / "evaluator-bundle").exists()


def test_frozen_scoring_process_failure_is_not_a_preparation_diagnostic(tmp_path):
    envelope = _envelope("candidate")
    runtime = _Runtime(envelope, _audit(envelope))
    frozen = _compile(tmp_path, runtime, "candidate")
    before = {path.name: path.read_bytes() for path in frozen.root.iterdir()}
    candidate = tmp_path / "candidate.py"
    candidate.write_text("# fresh candidate whose required result is absent\n")
    with pytest.raises(bundle.EvaluatorBundleError) as caught:
        frozen(candidate, _contract())
    assert not isinstance(caught.value, bundle.EvaluatorPreparationError)
    assert not hasattr(caught.value, "diagnostic")
    assert {path.name: path.read_bytes() for path in frozen.root.iterdir()} == before
    assert runtime.calls == ["compiler", "audit"]


@pytest.mark.parametrize("invocation", MODES)
def test_successful_freeze_and_load_keep_formats_and_skip_preparation_reexecution(
    tmp_path, monkeypatch, invocation,
):
    envelope = _envelope(invocation)
    runtime = _Runtime(envelope, _audit(envelope))
    frozen = _compile(tmp_path, runtime, invocation)
    original_files = {path.name: path.read_bytes() for path in frozen.root.iterdir()}
    manifest = json.loads(original_files["manifest.json"])
    assert manifest["schema_version"] == "1"
    assert "local_failure" not in manifest and "diagnostic" not in manifest
    monkeypatch.setattr(bundle, "_preflight", lambda *a, **k: pytest.fail("repeated preparation"))
    monkeypatch.setattr(runtime, "run", lambda *a, **k: pytest.fail("repeated runtime call"))
    assert _compile(tmp_path, runtime, invocation) == frozen
    assert {path.name: path.read_bytes() for path in frozen.root.iterdir()} == original_files
    assert runtime.calls == ["compiler", "audit"]
