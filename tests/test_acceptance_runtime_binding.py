from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest
from test_frozen_evaluator_bundle import BundleRuntime

import lunar_evolution.acceptance_runtime_binding as binding
from lunar_evolution.acceptance_observer import DEFAULT_ACCEPTANCE_BUDGETS
from lunar_evolution.acceptance_registration import build_acceptance_registration
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.automatic_solve_bundle import prepare_automatic_solve_bundle
from lunar_evolution.bundle_evolution import MultiFileCandidatePipeline
from lunar_evolution.candidate_evaluation_spec import CandidateEvaluationSpec, canonical_json
from lunar_evolution.candidate_execution import CandidateExecutionInput
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.conversational import build_algorithm_plan
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
    root = Path(__file__).resolve().parents[1] / "specs/142-automatic-solve-lifecycle/measurement/materials/reference"
    return (root / "evaluator-criteria.json").read_bytes(), (root / "profile-criteria.json").read_bytes()


def test_binding_accepts_complete_frozen_criteria_materials():
    evaluator, profile = _criteria(_contract())
    registration = _registration(b"task", b'{"limit":3}\n', evaluator, profile)
    actual_evaluator, actual_profile = binding._criteria(evaluator, profile, registration)
    assert canonical_json(actual_evaluator) == evaluator
    assert canonical_json(actual_profile) == profile
    binding._verify_contract(_contract(), actual_evaluator)


@pytest.mark.parametrize("target", ["evaluator", "profile"])
@pytest.mark.parametrize("change", ["unknown_field", "missing_field", "noncanonical", "duplicate_key"])
def test_binding_rejects_nonexact_criteria_json(target, change):
    evaluator, profile = _criteria(_contract())
    values = {"evaluator": json.loads(evaluator), "profile": json.loads(profile)}
    value = values[target]
    if change == "unknown_field":
        value["unused"] = "ignored"
    elif change == "missing_field":
        del value["schema_version"]
    raw = canonical_json(value)
    if change == "noncanonical":
        raw = json.dumps(value, indent=2).encode()
    elif change == "duplicate_key":
        raw = raw[:-1] + b',"schema_version":"1"}'
    if target == "evaluator":
        evaluator = raw
        values["profile"]["evaluator_criteria_sha256"] = hashlib.sha256(evaluator).hexdigest()
        profile = canonical_json(values["profile"])
    else:
        profile = raw
    registration = _registration(b"task", b'{"limit":3}\n', evaluator, profile)
    with pytest.raises(binding.AcceptanceRuntimeBindingError, match="criteria_(noncanonical|semantics_mismatch)"):
        binding._criteria(evaluator, profile, registration)


@pytest.mark.parametrize("change", [
    "generated_bundle_false", "audit_false", "holdout_float", "input_type", "source_paths",
    "valid_range", "valid_judgment", "invalid_judgment", "source_only_false", "boolean_validity",
])
def test_binding_rejects_changed_criteria_semantics(change):
    evaluator, profile = _criteria(_contract())
    ev, pr = json.loads(evaluator), json.loads(profile)
    if change == "generated_bundle_false":
        pr["generated_bundle_required"] = False
    elif change == "audit_false":
        pr["independent_audit"] = False
    elif change == "holdout_float":
        pr["holdout_count"] = 8.0
    elif change == "input_type":
        ev["input"]["type"] = "string"
    elif change == "source_paths":
        ev["source_paths"] = "zero_files"
    elif change == "valid_range":
        ev["valid_range"] = "unbounded"
    elif change == "valid_judgment":
        ev["valid_judgment"]["combined_score"] = 0
    elif change == "invalid_judgment":
        ev["invalid_judgment"]["constraint_code"] = None
    elif change == "source_only_false":
        ev["source_path_check_only"] = False
    else:
        ev["valid_judgment"]["validity"] = True
    evaluator = canonical_json(ev)
    pr["evaluator_criteria_sha256"] = hashlib.sha256(evaluator).hexdigest()
    profile = canonical_json(pr)
    registration = _registration(b"task", b'{"limit":3}\n', evaluator, profile)
    with pytest.raises(binding.AcceptanceRuntimeBindingError, match="criteria_semantics_mismatch"):
        binding._criteria(evaluator, profile, registration)


def _registration(task: bytes, input_bytes: bytes, evaluator: bytes, profile: bytes) -> dict[str, object]:
    expected_projection = {"validity": 1, "quality": 1, "combined_score": 1, "constraint_code": None}
    expected_digest = hashlib.sha256(canonical_json(expected_projection)).hexdigest()
    holdout = [{
        "holdout_id": f"holdout-{index:02d}", "ordinal": index,
        "input": {"path": f"holdout/{index:02d}.json", "size": 1, "sha256": "1" * 64},
        "expected": {"path": f"expected/{index:02d}.json", "size": 1, "sha256": expected_digest},
        "max_duration_ms": 5000,
    } for index in range(8)]
    frozen = {"registration_id": ["old-reg"], "campaign_id": ["old-camp"], "campaign_root": ["old-root"]}
    frozen_digest = hashlib.sha256(canonical_json(frozen)).hexdigest()
    return build_acceptance_registration({
        "schema_version": "1", "scope": "acceptance_registration",
        "registration_id": "reg-1", "campaign_id": "camp-1", "attempt_id": "attempt-001",
        "product_commit": "b" * 40,
        "product_files": [{"path": "src/main.py", "size": 1, "sha256": "9" * 64}],
        "task_material": {"path": "task.bin", "size": len(task), "sha256": hashlib.sha256(task).hexdigest()},
        "input_material": {"path": "input.bin", "size": len(input_bytes), "sha256": hashlib.sha256(input_bytes).hexdigest()},
        "evaluator_material": {"path": "evaluator.bin", "size": len(evaluator), "sha256": hashlib.sha256(evaluator).hexdigest()},
        "evaluator_profile_material": {"path": "profile-criteria.bin", "size": len(profile), "sha256": hashlib.sha256(profile).hexdigest()},
        "campaign_root": "camp-root", "task_sha256": hashlib.sha256(task).hexdigest(),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(), "evaluator_sha256": hashlib.sha256(evaluator).hexdigest(),
        "evaluator_profile_sha256": hashlib.sha256(profile).hexdigest(), "provider": "openai-compatible",
        "model": "glm-5.2", "runtime": "python", "api_mode": "chat_completions", "entrypoint": "src/main.py",
        "budgets": dict(DEFAULT_ACCEPTANCE_BUDGETS), "islands": 1, "population_size": 1,
        "offspring_count": 1, "rounds": 1, "candidate_tool_steps": 12,
        "holdout_pins": holdout, "frozen_identities": frozen, "frozen_identities_sha256": frozen_digest,
    })


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    contract = _contract()
    task = b"task bytes"
    input_bytes = b'{"limit":3}\n'
    evaluator, profile_criteria = _criteria(contract)
    registration = _registration(task, input_bytes, evaluator, profile_criteria)
    case_path = Path(__file__).resolve().parents[1] / "specs/142-automatic-solve-lifecycle/measurement/case.py"
    case_spec = importlib.util.spec_from_file_location("binding_case_fixture", case_path)
    assert case_spec is not None and case_spec.loader is not None
    case = importlib.util.module_from_spec(case_spec)
    case_spec.loader.exec_module(case)
    case_materials = case.build_case_materials()
    materials = {case.MATERIAL_ROOT + "/" + name: raw for name, raw in case_materials.items()}
    pins = case.build_case_pins()
    registration_payload = {key: value for key, value in registration.items() if key != "registration_sha256"}
    registration_payload["holdout_pins"] = pins["holdout_pins"]
    registration = build_acceptance_registration(registration_payload)
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
        evaluator=spec, harness_path=harness, input_root=input_root,
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
    (root / "evaluator.py").write_bytes(harness.read_bytes())
    bundle = FrozenEvaluatorBundle(root, "e" * 64, contract.digest(), "f" * 64, 2, "snapshot")
    monkeypatch.setattr(binding, "load_evaluator_bundle", lambda *args, **kwargs: bundle)
    return registration, task, input_bytes, evaluator, profile_criteria, contract, pipeline, bundle, profile, materials


def _probe(index: int = 0, holdout_id: str | None = None) -> dict[str, object]:
    material_root = Path(__file__).resolve().parents[1] / "specs/142-automatic-solve-lifecycle/measurement/materials"
    snapshot = (material_root / f"holdouts/{index:02d}/snapshot.json").read_bytes()
    expected_bytes = (material_root / f"holdouts/{index:02d}/expected.json").read_bytes()
    declaration = json.loads(snapshot)
    projection = json.loads(expected_bytes)
    report = {"schema_version": "1", "evaluator_id": "compiled-bundle", "validity": projection["validity"],
              "quality": projection["quality"], "combined_score": projection["combined_score"], "detailed_scores": {},
              "error_info": [{"code": "valid-value", "message": "invalid"}] if not projection["validity"] else []}
    projection_bytes = canonical_json(projection)
    report_bytes = canonical_json(report)
    raw_input = next(item["content"].encode() for item in declaration["files"] if item["path"] == "data/raw/limit.json")
    digest = hashlib.sha256(raw_input).hexdigest()
    return {
        "ordinal": index, "holdout_id": holdout_id or declaration["name"],
        "input_sha256": hashlib.sha256(snapshot).hexdigest(), "expected_output_sha256": hashlib.sha256(expected_bytes).hexdigest(),
        "actual_output_sha256": hashlib.sha256(projection_bytes).hexdigest(), "outcome": "passed", "evidence": {
            "report": report, "projection": projection, "expected": projection, "passed": True,
            "reason": "passed", "duration_ms": 2, "process_exit_code": 0, "native_exit_code": 0,
            "cleanup": "verified", "observer_identity": [10, 10], "release_identity": [10, 10],
            "input_sha256": digest, "expected_output_sha256": hashlib.sha256(expected_bytes).hexdigest(),
            "actual_output_sha256": hashlib.sha256(projection_bytes).hexdigest(),
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "projection_sha256": hashlib.sha256(projection_bytes).hexdigest(),
            "harness_sha256": "0" * 64,
        },
    }


_DEFAULT = object()


def _bind(fixture, probes=_DEFAULT):
    registration, task, input_bytes, evaluator, profile_criteria, contract, pipeline, bundle, profile, materials = fixture
    selected = [_probe(index) for index in range(8)] if probes is _DEFAULT else probes
    harness_sha = hashlib.sha256(Path(pipeline.harness_path).read_bytes()).hexdigest()
    if selected is not None:
        for row in selected:
            if row["evidence"]["harness_sha256"] == "0" * 64:
                row["evidence"]["harness_sha256"] = harness_sha
    return binding.bind_acceptance_runtime(
        registration, task_bytes=task, input_bytes=input_bytes,
        evaluator_criteria_bytes=evaluator, profile_criteria_bytes=profile_criteria,
        contract=contract, pipeline=pipeline, bundle=bundle, profile_bytes=profile,
        materials=materials,
        probe_results=selected,
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


@pytest.mark.parametrize("change", ["nested_input", "harness", "snapshot", "expected"])
def test_runtime_binding_rejects_cross_material_probe_identity(tmp_path, monkeypatch, change):
    fixture = _fixture(tmp_path, monkeypatch)
    registration, *_, materials = fixture
    probes = [_probe(index) for index in range(8)]
    if change == "nested_input":
        probes[0]["evidence"]["input_sha256"] = "f" * 64
    elif change == "harness":
        probes[0]["evidence"]["harness_sha256"] = "f" * 64
    elif change == "snapshot":
        materials[registration["holdout_pins"][0]["input"]["path"]] = b"{}"
    else:
        materials[registration["holdout_pins"][0]["expected"]["path"]] = b"{}"
    with pytest.raises(binding.AcceptanceRuntimeBindingError, match="probe_(material_mismatch|harness_mismatch)"):
        _bind(fixture, probes)


def test_runtime_binding_rejects_different_bundle_harness(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    bundle = fixture[7]
    (bundle.root / "evaluator.py").write_bytes(b"print('different')\n")
    with pytest.raises(binding.AcceptanceRuntimeBindingError, match="bundle_harness_mismatch"):
        _bind(fixture)


def test_runtime_binding_rejects_staged_input_drift(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    pipeline = fixture[6]
    (pipeline.input_root / "limit.json").write_bytes(b'{"limit":4}\n')
    with pytest.raises(binding.AcceptanceRuntimeBindingError, match="staged_input_mismatch"):
        _bind(fixture)


def test_runtime_binding_requires_holdouts(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    with pytest.raises(binding.AcceptanceRuntimeBindingError, match="probe_results_missing"):
        _bind(fixture, None)


_SOURCE = '''import json
from pathlib import Path


def main():
    limit = json.loads(Path("inputs/limit.json").read_text())["limit"]
    value = json.loads(Path("output/result.json").read_text())["value"]
    valid = type(limit) is int and type(value) is int and 0 <= value <= limit
    print(json.dumps({"schema_version": "1", "evaluator_id": "compiled-bundle",
        "validity": int(valid), "quality": value if valid else None,
        "combined_score": value if valid else 0, "detailed_scores": {},
        "error_info": [] if valid else [{"code": "valid-value", "message": "invalid"}]}))


if __name__ == "__main__":
    main()
'''


def _native_fixture(root):
    case_path = Path(__file__).resolve().parents[1] / "specs/142-automatic-solve-lifecycle/measurement/case.py"
    spec = importlib.util.spec_from_file_location("binding_case", case_path)
    assert spec is not None and spec.loader is not None
    case = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(case)
    raw_materials = case.build_case_materials()
    materials = {case.MATERIAL_ROOT + "/" + name: raw for name, raw in raw_materials.items()}
    pins = case.build_case_pins()
    contract = _contract()
    envelope = {
        "schema_version": "1", "objective": "maximize valid value", "evaluator_source": _SOURCE,
        "constraint_coverage": ["valid-value"],
        "probes": [json.loads(raw_materials[f"holdouts/{index:02d}/snapshot.json"]) for index in (1, 2, 0)],
        "score_order": [{"better": "limit-1-value-1", "worse": "limit-1-value-0"}],
    }
    runtime = BundleRuntime(envelope)
    controller = LocalController(Config(root / "home"), runtime)
    parent = controller.create_conversational_run(case.TASK_BYTES.decode(), workspace=root / "parent")
    task = controller.store.list_tasks(parent.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    controller.store.finish_task(task.id, attempt.id, True)
    controller.store.attach_plan_to_run(parent.id, build_algorithm_plan(parent.goal, contract))
    input_path = parent.workspace / "data/raw/limit.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_bytes(case.INPUT_BYTES)
    controller.store.add_artifact(
        parent.id, task.id, "data/raw/limit.json", hashlib.sha256(case.INPUT_BYTES).hexdigest(),
        len(case.INPUT_BYTES), "input_data",
    )
    prepare_automatic_solve_bundle(controller, parent.id, contract, timeout_seconds=3)
    registration = _registration(case.TASK_BYTES, case.INPUT_BYTES,
                                 raw_materials["reference/evaluator-criteria.json"],
                                 raw_materials["reference/profile-criteria.json"])
    payload = {key: value for key, value in registration.items() if key != "registration_sha256"}
    payload.update(pins)
    registration = build_acceptance_registration(payload)
    return controller, parent, contract, registration, materials


def test_real_native_preparation_and_fixed_holdouts_bind(tmp_path):
    controller, parent, contract, registration, materials = _native_fixture(tmp_path)
    receipt = binding.prepare_acceptance_runtime_binding(
        registration, store=controller.store, parent_id=parent.id, materials=materials,
        contract=contract, workspace=tmp_path / "holdouts",
    )
    assert receipt["parent_run_id"] == parent.id
    assert receipt["probe_summary"]["status"] == "passed"
    assert (tmp_path / "holdouts/binding-receipt.json").read_bytes() == canonical_json(receipt, maximum=256 * 1024)
    payload = {key: value for key, value in receipt.items() if key != "binding_sha256"}
    assert hashlib.sha256(canonical_json(payload, maximum=256 * 1024)).hexdigest() == receipt["binding_sha256"]


def test_wrapper_rejects_retained_evidence_changed_after_probe(tmp_path, monkeypatch):
    import lunar_evolution.acceptance_holdouts as holdouts

    controller, parent, contract, registration, materials = _native_fixture(tmp_path)
    original = holdouts.run_acceptance_holdouts

    def corrupt(*args, **kwargs):
        rows = original(*args, **kwargs)
        (kwargs["workspace"] / "00" / "actual.json").write_bytes(b"{}")
        return rows

    monkeypatch.setattr(holdouts, "run_acceptance_holdouts", corrupt)
    with pytest.raises(binding.AcceptanceRuntimeBindingError):
        binding.prepare_acceptance_runtime_binding(
            registration, store=controller.store, parent_id=parent.id, materials=materials,
            contract=contract, workspace=tmp_path / "holdouts",
        )
    assert not (tmp_path / "holdouts" / "binding-receipt.json").exists()


def test_wrapper_checks_deadline_after_holdouts_before_publication(tmp_path):
    controller, parent, contract, registration, materials = _native_fixture(tmp_path)

    def remaining(stage):
        return 0 if stage == "binding-publish" else 60

    with pytest.raises(binding.AcceptanceRuntimeBindingError):
        binding.prepare_acceptance_runtime_binding(
            registration, store=controller.store, parent_id=parent.id, materials=materials,
            contract=contract, workspace=tmp_path / "holdouts", remaining_timeout=remaining,
        )
    assert (tmp_path / "holdouts" / "07" / "evidence.json").exists()
    assert not (tmp_path / "holdouts" / "binding-receipt.json").exists()


def test_real_preparation_rejects_other_registered_parent_task_before_holdouts(tmp_path):
    controller, parent, contract, registration, materials = _native_fixture(tmp_path)
    changed = b"A different task with the same generated contract"
    payload = {key: value for key, value in registration.items() if key != "registration_sha256"}
    digest = hashlib.sha256(changed).hexdigest()
    payload["task_material"] = {**payload["task_material"], "size": len(changed), "sha256": digest}
    payload["task_sha256"] = digest
    materials[payload["task_material"]["path"]] = changed
    registration = build_acceptance_registration(payload)
    with pytest.raises(binding.AcceptanceRuntimeBindingError, match="parent_task_material_mismatch"):
        binding.prepare_acceptance_runtime_binding(
            registration, store=controller.store, parent_id=parent.id, materials=materials,
            contract=contract, workspace=tmp_path / "holdouts",
        )
    assert not (tmp_path / "holdouts").exists()
