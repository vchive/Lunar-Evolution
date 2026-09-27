from __future__ import annotations

import hashlib
import stat
import sys
from pathlib import Path

import pytest

import lunar_evolution.acceptance_runtime_binding as binding
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.bundle_evolution import MultiFileCandidatePipeline
from lunar_evolution.candidate_evaluation_spec import CandidateEvaluationSpec, canonical_json
from lunar_evolution.candidate_execution import CandidateExecutionInput
from lunar_evolution.evaluator_bundle import FrozenEvaluatorBundle


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "limit", "problem_type": "continuous",
        "statement": "maximize a bounded integer", "inputs": [{
            "path": "limit.json", "format": "json", "fields": {"limit": "integer"},
        }], "decision_variables": ["value"],
        "objective": {"name": "value", "direction": "maximize"},
        "hard_constraints": [
            {"id": "valid-value", "description": "bounded", "source": "user_confirmed",
             "verification": "independent", "verification_scope": "output",
             "result_fields": ["value"]},
            {"id": "python-files", "description": "source", "source": "user_confirmed",
             "verification": "independent", "verification_scope": "source", "result_fields": [],
             "source_check": {"kind": "python_file_count", "minimum": 2}},
        ], "soft_constraints": [], "success_criteria": ["valid"],
        "deliverables": ["output/result.json"], "assumptions": [],
        "outputs": [{"path": "output/result.json", "format": "json", "fields": ["value"], "required": True}],
        "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
    })


def _criteria(contract: AlgorithmProblemContract) -> tuple[bytes, bytes]:
    del contract
    evaluator = {
        "kind": "independent_evaluator_criteria", "hard_constraints": ["valid-value", "python-files"],
        "input": {"path": "limit.json", "format": "json", "field": "limit"},
        "output": {"path": "output/result.json", "format": "json", "field": "value"},
        "objective": "maximize", "source_check": {"kind": "python_file_count", "minimum": 2},
    }
    evaluator_bytes = canonical_json(evaluator)
    profile = {
        "kind": "independent_evaluator_profile_criteria",
        "evaluator_criteria_sha256": hashlib.sha256(evaluator_bytes).hexdigest(),
        "holdout_count": 8, "invocation": "snapshot", "independent_audit": True,
    }
    return evaluator_bytes, canonical_json(profile)


def _registration(task: bytes, input_bytes: bytes, evaluator: bytes, profile: bytes) -> dict[str, object]:
    return {
        "registration_id": "reg-1", "campaign_id": "camp-1", "attempt_id": "attempt-1",
        "registration_sha256": "a" * 64, "product_commit": "b" * 40,
        "task_sha256": hashlib.sha256(task).hexdigest(), "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "evaluator_sha256": hashlib.sha256(evaluator).hexdigest(),
        "evaluator_profile_sha256": hashlib.sha256(profile).hexdigest(),
        "provider": "openai-compatible", "model": "glm-5.2", "api_mode": "chat_completions",
    }


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    contract = _contract()
    task = b"task bytes"
    input_bytes = b'{"limit":3}\n'
    evaluator, profile_criteria = _criteria(contract)
    registration = _registration(task, input_bytes, evaluator, profile_criteria)
    (tmp_path / "evaluator-bundle").mkdir()
    harness = tmp_path / "evaluator-bundle" / "evaluator.py"
    harness.write_text("print('ok')\n", encoding="utf-8")
    harness.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    spec = CandidateEvaluationSpec(
        hashlib.sha256(harness.read_bytes()).hexdigest(), len(harness.read_bytes()),
        (sys.executable,), evaluator_id="compiled-bundle", timeout_seconds=2,
    )
    input_root = tmp_path / "data" / "raw"
    input_root.mkdir(parents=True)
    (input_root / "limit.json").write_bytes(input_bytes)
    pipeline = MultiFileCandidatePipeline(
        evaluator=spec, harness_path=harness, input_root=tmp_path / "inputs",
        inputs=(CandidateExecutionInput(
            "limit.json", "parent-input", len(input_bytes), hashlib.sha256(input_bytes).hexdigest(),
        ),),
        command=(sys.executable,), dependency_sha256="c" * 64, environment_sha256="d" * 64,
        timeout_seconds=2,
    )
    profile = canonical_json({
        "schema_version": "1", "protocol": "lunar-bundle-pipeline-v1",
        "evaluator": spec.to_dict(), "harness_path": "evaluator-bundle/evaluator.py",
        "input_root": "data/raw", "inputs": [item.to_dict() for item in pipeline.inputs],
        "command": list(pipeline.command), "environment": dict(pipeline.environment),
        "timeout_seconds": pipeline.timeout_seconds, "max_output_bytes": pipeline.max_output_bytes,
        "dependency_sha256": pipeline.dependency_sha256, "environment_sha256": pipeline.environment_sha256,
    })
    root = tmp_path / "bundle"
    root.mkdir()
    bundle = FrozenEvaluatorBundle(root, "e" * 64, contract.digest(), "f" * 64, 2, "snapshot")
    monkeypatch.setattr(binding, "load_evaluator_bundle", lambda *args, **kwargs: bundle)
    return registration, task, input_bytes, evaluator, profile_criteria, contract, pipeline, bundle, profile


def _probe(index: int = 0) -> dict[str, object]:
    projection = {"validity": 1, "quality": 1, "combined_score": 1, "constraint_code": None}
    report = {"schema_version": "1", "evaluator_id": "compiled-bundle", "validity": 1,
              "quality": 1, "combined_score": 1, "detailed_scores": {}, "error_info": []}
    projection_bytes = canonical_json(projection)
    expected_bytes = canonical_json(projection)
    report_bytes = canonical_json(report)
    digest = "1" * 64
    return {
        "ordinal": index, "outcome": "passed", "evidence": {
            "report": report, "projection": projection, "expected": projection, "passed": True,
            "reason": "passed", "duration_ms": 2, "process_exit_code": 0, "native_exit_code": 0,
            "cleanup": "verified", "observer_identity": [10, 10], "release_identity": [10, 10],
            "input_sha256": digest, "expected_output_sha256": hashlib.sha256(expected_bytes).hexdigest(),
            "actual_output_sha256": hashlib.sha256(projection_bytes).hexdigest(),
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "projection_sha256": hashlib.sha256(projection_bytes).hexdigest(),
        },
    }


_DEFAULT = object()


def _bind(fixture, probes=_DEFAULT):
    registration, task, input_bytes, evaluator, profile_criteria, contract, pipeline, bundle, profile = fixture
    return binding.bind_acceptance_runtime(
        registration, task_bytes=task, input_bytes=input_bytes,
        evaluator_criteria_bytes=evaluator, profile_criteria_bytes=profile_criteria,
        contract=contract, pipeline=pipeline, bundle=bundle, profile_bytes=profile,
        probe_results=[_probe(index) for index in range(8)] if probes is _DEFAULT else probes,
    )


def test_runtime_binding_fixture_records_all_runtime_digests(tmp_path, monkeypatch):
    receipt = _bind(_fixture(tmp_path, monkeypatch))
    assert receipt["probe_summary"] == {"count": 8, "status": "passed", "sha256": receipt["probe_summary"]["sha256"]}
    assert len(receipt["binding_sha256"]) == 64


@pytest.mark.parametrize("change", ["order", "projection", "cleanup", "report"])
def test_runtime_binding_rejects_probe_evidence_drift(tmp_path, monkeypatch, change):
    fixture = _fixture(tmp_path, monkeypatch)
    probes = [_probe(index) for index in range(8)]
    evidence = probes[0]["evidence"]
    assert isinstance(evidence, dict)
    if change == "order":
        probes[1]["ordinal"] = 0
    elif change == "projection":
        evidence["projection"] = {"validity": 0, "quality": None, "combined_score": 0, "constraint_code": "x"}
    elif change == "cleanup":
        evidence["cleanup"] = "unknown"
    else:
        evidence["report_sha256"] = "2" * 64
    with pytest.raises(binding.AcceptanceRuntimeBindingError):
        _bind(fixture, probes)


def test_runtime_binding_requires_holdouts(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    with pytest.raises(binding.AcceptanceRuntimeBindingError, match="probe_results_missing"):
        _bind(fixture, None)
