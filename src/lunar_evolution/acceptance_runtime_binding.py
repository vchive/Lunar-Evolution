"""Bind a prepared native evaluator to an independent acceptance registration.

The registration and the runtime deliberately use different digests for task, input and
evaluator identities.  This module is a read-only bridge between those layers: it verifies the
registered bytes and the generated contract/profile/bundle, then emits a compact binding receipt.
It does not launch a model, execute a candidate, or turn a structural binding into acceptance
success.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ._benchmark_files import absolute_path, read_regular_file
from ._candidate_workspace_io import DirectoryChain
from .acceptance_registration import AcceptanceRegistrationError, parse_acceptance_registration
from .algorithm import AlgorithmProblemContract
from .bundle_evolution import MultiFileCandidatePipeline
from .candidate_evaluation_spec import (
    canonical_json,
    parse_candidate_evaluation_report,
    strict_json,
)
from .candidate_execution import CandidateExecutionInput
from .data_profile import DataProfileError, build_private_input_profile, profile_sha256
from .evaluator_bundle import EvaluatorBundleError, FrozenEvaluatorBundle, load_evaluator_bundle
from .evolution import CandidateInputArtifact, EvolutionError

_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SCHEMA = "1"
_SCOPE = "acceptance_runtime_binding"


class AcceptanceRuntimeBindingError(ValueError):
    """A fixed binding failure without provider, path or exception details."""

    def __init__(self, code: str) -> None:
        self.code = code if re.fullmatch(r"[a-z0-9_]+", code or "") else "invalid"
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise AcceptanceRuntimeBindingError(code)


def _sha(value: object, code: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail(code)
    return value


def _id(value: object, code: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _digest_bytes(value: bytes, expected: object, code: str) -> str:
    if not isinstance(value, bytes):
        _fail(code)
    actual = hashlib.sha256(value).hexdigest()
    if actual != expected:
        _fail(code)
    return actual


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return canonical_json(value, maximum=256 * 1024)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail("binding_json_invalid")


def _registration(registration: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(registration, Mapping):
        _fail("registration_invalid")
    required = {
        "registration_id", "campaign_id", "attempt_id", "registration_sha256", "product_commit",
        "task_sha256", "input_sha256", "evaluator_sha256", "evaluator_profile_sha256",
        "provider", "model", "api_mode",
    }
    if not required <= set(registration):
        _fail("registration_invalid")
    for key in ("registration_id", "campaign_id", "attempt_id"):
        _id(registration[key], "registration_identity_invalid")
    _sha(registration["registration_sha256"], "registration_digest_invalid")
    if type(registration["product_commit"]) is not str or _COMMIT.fullmatch(registration["product_commit"]) is None:
        _fail("registration_commit_invalid")
    for key in ("task_sha256", "input_sha256", "evaluator_sha256", "evaluator_profile_sha256"):
        _sha(registration[key], "registration_material_invalid")
    for key in ("provider", "model", "api_mode"):
        if type(registration[key]) is not str or not registration[key] or len(registration[key]) > 256:
            _fail("registration_runtime_invalid")
    try:
        return parse_acceptance_registration(registration)
    except (AcceptanceRegistrationError, TypeError, ValueError):
        _fail("registration_invalid")


def _criteria(evaluator_bytes: bytes, profile_bytes: bytes, registration: Mapping[str, Any]) -> tuple[dict, dict]:
    _digest_bytes(evaluator_bytes, registration["evaluator_sha256"], "evaluator_criteria_mismatch")
    _digest_bytes(profile_bytes, registration["evaluator_profile_sha256"], "profile_criteria_mismatch")
    try:
        evaluator, profile = json.loads(evaluator_bytes), json.loads(profile_bytes)
    except (TypeError, ValueError, UnicodeDecodeError, RecursionError):
        _fail("criteria_json_invalid")
    if not isinstance(evaluator, dict) or not isinstance(profile, dict):
        _fail("criteria_json_invalid")
    try:
        # Comparing canonical bytes rejects whitespace, duplicate keys, nonfinite numbers
        # and Python's otherwise permissive bool/int/float equality in semantic dictionaries.
        evaluator_canonical = canonical_json(evaluator)
        profile_canonical = canonical_json(profile)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail("criteria_json_invalid")
    if evaluator_canonical != evaluator_bytes or profile_canonical != profile_bytes:
        _fail("criteria_noncanonical")
    expected_evaluator = {
        "schema_version": "1", "kind": "independent_evaluator_criteria",
        "input": {"path": "limit.json", "format": "json", "field": "limit",
                  "type": "nonnegative_json_integer_excluding_bool_float"},
        "output": {"path": "output/result.json", "format": "json", "field": "value",
                   "type": "json_integer_excluding_bool_float"},
        "valid_range": "0 <= value <= limit",
        "valid_judgment": {"validity": 1, "quality": "value", "combined_score": "value",
                           "constraint_code": None},
        "invalid_judgment": {"validity": 0, "quality": None, "combined_score": 0,
                             "constraint_code": "valid-value"},
        "source_check": {"kind": "python_file_count", "minimum": 2},
        "source_paths": "at_least_two_distinct_lowercase_py_paths_including_entrypoint",
        "source_path_check_only": True, "hard_constraints": ["valid-value", "python-files"],
        "objective": "maximize",
    }
    expected_profile = {
        "schema_version": "1", "kind": "independent_evaluator_profile_criteria",
        "evaluator_criteria_sha256": registration["evaluator_sha256"],
        "generated_bundle_required": True, "invocation": "snapshot",
        "independent_audit": True, "holdout_count": 8,
    }
    if (evaluator_canonical != canonical_json(expected_evaluator)
            or profile_canonical != canonical_json(expected_profile)):
        _fail("criteria_semantics_mismatch")
    return evaluator, profile


def _verify_contract(contract: AlgorithmProblemContract, criteria: Mapping[str, Any]) -> None:
    if not isinstance(contract, AlgorithmProblemContract):
        _fail("contract_invalid")
    if len(contract.inputs) != 1:
        _fail("contract_semantics_mismatch")
    item = contract.inputs[0]
    if item.path != "limit.json" or item.format != "json" or set(item.fields) != {"limit"}:
        _fail("contract_semantics_mismatch")
    if len(contract.outputs) != 1:
        _fail("contract_semantics_mismatch")
    output = contract.outputs[0]
    if (output.path != "output/result.json" or output.format != "json"
            or output.fields != ("value",) or output.required is not True):
        _fail("contract_semantics_mismatch")
    if contract.objective.direction != "maximize" or contract.objective.metrics:
        _fail("contract_semantics_mismatch")
    if contract.soft_constraints or len(contract.hard_constraints) != 2:
        _fail("contract_semantics_mismatch")
    constraints = {item.id: item for item in contract.hard_constraints}
    if set(constraints) != {"valid-value", "python-files"}:
        _fail("contract_semantics_mismatch")
    valid = constraints["valid-value"]
    source = constraints["python-files"]
    if (valid.verification != "independent" or valid.verification_scope != "output"
            or valid.result_fields != ("value",) or source.verification != "independent"
            or source.verification_scope != "source" or source.result_fields
            or source.source_check is None or source.source_check.kind != "python_file_count"
            or source.source_check.minimum != 2):
        _fail("contract_semantics_mismatch")
    if contract.evolution.strategy != "population" or contract.deliverables != ("output/result.json",):
        _fail("contract_semantics_mismatch")
    input_criteria = criteria.get("input")
    output_criteria = criteria.get("output")
    source_check = criteria.get("source_check")
    if (criteria.get("hard_constraints") != ["valid-value", "python-files"]
            or not isinstance(input_criteria, Mapping)
            or any(input_criteria.get(key) != value for key, value in {
                "path": "limit.json", "format": "json", "field": "limit",
            }.items())
            or not isinstance(output_criteria, Mapping)
            or any(output_criteria.get(key) != value for key, value in {
                "path": "output/result.json", "format": "json", "field": "value",
            }.items())
            or criteria.get("objective") != "maximize"
            or not isinstance(source_check, Mapping)
            or source_check.get("kind") != "python_file_count"
            or source_check.get("minimum") != 2):
        _fail("criteria_semantics_mismatch")


def _input_table(pipeline: MultiFileCandidatePipeline) -> tuple[dict[str, Any], ...]:
    if not isinstance(pipeline, MultiFileCandidatePipeline):
        _fail("pipeline_invalid")
    try:
        values = tuple(item.to_dict() for item in pipeline.inputs)
        for value in values:
            CandidateExecutionInput.from_dict(value)
        return values
    except (AttributeError, TypeError, ValueError, RecursionError):
        _fail("input_table_invalid")


def _probe_summary(
    probe_results: Sequence[Mapping[str, Any]] | None,
    holdout_pins: Sequence[Mapping[str, Any]],
    materials: Mapping[str, bytes],
    harness_sha256: str,
) -> dict[str, Any]:
    if probe_results is None:
        _fail("probe_results_missing")
    if not isinstance(probe_results, Sequence) or isinstance(probe_results, (str, bytes)):
        _fail("probe_results_invalid")
    if len(probe_results) != 8:
        _fail("probe_count_invalid")
    values = []
    if not isinstance(materials, Mapping):
        _fail("probe_materials_invalid")
    pins = {item["ordinal"]: item for item in holdout_pins}
    if set(pins) != set(range(8)):
        _fail("probe_pins_invalid")
    for index, item in enumerate(probe_results):
        if not isinstance(item, Mapping) or item.get("ordinal") != index:
            _fail("probe_order_invalid")
        evidence = item.get("evidence", item)
        if not isinstance(evidence, Mapping):
            _fail("probe_result_invalid")
        expected_keys = {
            "report", "projection", "expected", "passed", "reason", "duration_ms",
            "process_exit_code", "native_exit_code", "cleanup", "observer_identity",
            "release_identity", "input_sha256", "expected_output_sha256",
            "actual_output_sha256", "report_sha256", "projection_sha256",
            "harness_sha256",
        }
        if set(evidence) != expected_keys:
            _fail("probe_result_invalid")
        if evidence.get("passed") is not True or evidence.get("reason") != "passed":
            _fail("probe_result_incomplete")
        if evidence.get("cleanup") != "verified":
            _fail("probe_cleanup_unknown")
        identity = evidence.get("observer_identity")
        if (type(evidence.get("process_exit_code")) is not int
                or evidence.get("process_exit_code") != 0
                or type(evidence.get("native_exit_code")) is not int
                or evidence.get("native_exit_code") != 0
                or not isinstance(identity, (tuple, list)) or len(identity) != 2
                or type(identity[0]) is not int or identity[0] <= 0
                or type(identity[1]) is not int or identity[1] != identity[0]
                or evidence.get("observer_identity") != evidence.get("release_identity")):
            _fail("probe_process_invalid")
        duration = evidence.get("duration_ms")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            _fail("probe_result_invalid")
        if duration > pins[index].get("max_duration_ms", 0):
            _fail("probe_timeout_invalid")
        for key in (
            "input_sha256", "expected_output_sha256", "actual_output_sha256",
            "report_sha256", "projection_sha256",
            "harness_sha256",
        ):
            _sha(evidence.get(key), "probe_digest_invalid")
        if evidence["harness_sha256"] != harness_sha256:
            _fail("probe_harness_mismatch")
        projection = evidence.get("projection")
        expected = evidence.get("expected")
        if not isinstance(projection, Mapping) or not isinstance(expected, Mapping):
            _fail("probe_projection_invalid")
        try:
            projection_bytes = canonical_json(dict(projection))
            expected_bytes = canonical_json(dict(expected))
        except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
            _fail("probe_projection_invalid")
        if (hashlib.sha256(projection_bytes).hexdigest() != evidence["projection_sha256"]
                or hashlib.sha256(expected_bytes).hexdigest() != evidence["expected_output_sha256"]
                or hashlib.sha256(projection_bytes).hexdigest() != evidence["actual_output_sha256"]
                or dict(projection) != dict(expected)):
            _fail("probe_projection_mismatch")
        report = evidence.get("report")
        if not isinstance(report, Mapping):
            _fail("probe_report_invalid")
        try:
            report_bytes = canonical_json(dict(report))
            parsed_report = parse_candidate_evaluation_report(report_bytes, evaluator_id="compiled-bundle")
        except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
            _fail("probe_report_invalid")
        if hashlib.sha256(report_bytes).hexdigest() != evidence["report_sha256"]:
            _fail("probe_report_invalid")
        report_projection = {
            "validity": parsed_report.validity,
            "quality": parsed_report.quality,
            "combined_score": parsed_report.combined_score,
            "constraint_code": parsed_report.error_info[0]["code"] if parsed_report.error_info else None,
        }
        if report_projection != dict(projection):
            _fail("probe_projection_mismatch")
        if item.get("outcome", "passed") != "passed":
            _fail("probe_result_incomplete")
        holdout_id = item.get("holdout_id")
        pin = pins[index]
        if holdout_id != pin.get("holdout_id"):
            _fail("probe_identity_mismatch")
        pinned_raw: dict[str, bytes] = {}
        for field, pin_field in (("input_sha256", "input"), ("expected_output_sha256", "expected")):
            digest = item.get(field)
            expected_pin = pin.get(pin_field)
            if (not isinstance(expected_pin, Mapping)
                    or digest != expected_pin.get("sha256")):
                _fail("probe_material_mismatch")
            raw = materials.get(expected_pin.get("path"))
            if (not isinstance(raw, bytes) or len(raw) != expected_pin.get("size")
                    or hashlib.sha256(raw).hexdigest() != digest):
                _fail("probe_material_mismatch")
            pinned_raw[pin_field] = raw
        if item.get("actual_output_sha256") != evidence["actual_output_sha256"]:
            _fail("probe_projection_mismatch")
        if (expected_bytes != pinned_raw["expected"]
                or evidence["expected_output_sha256"] != pin["expected"]["sha256"]):
            _fail("probe_material_mismatch")
        try:
            from .acceptance_holdouts import _json, _probe, _validate_fixed_pair
            snapshot = _probe(pinned_raw["input"], "probe_material_mismatch")
            expected_material = _json(pinned_raw["expected"], "probe_material_mismatch")
            _validate_fixed_pair(index, snapshot, expected_material, "probe_material_mismatch")
            raw_input = next(entry.content.encode("utf-8") for entry in snapshot.files
                             if entry.path == "data/raw/limit.json")
        except (TypeError, ValueError, UnicodeError, StopIteration, RecursionError):
            _fail("probe_material_mismatch")
        if (snapshot.name != holdout_id
                or hashlib.sha256(raw_input).hexdigest() != evidence["input_sha256"]):
            _fail("probe_material_mismatch")
        values.append({
            "ordinal": index, "holdout_id": item.get("holdout_id"),
            "input_sha256": item.get("input_sha256"),
            "expected_output_sha256": item.get("expected_output_sha256"),
            "actual_output_sha256": evidence["actual_output_sha256"],
            "outcome": "passed", "evidence": dict(evidence),
        })
    raw = _canonical({"probes": values})
    return {
        "count": 8,
        "status": "passed",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def bind_acceptance_runtime(
    registration: Mapping[str, Any],
    *,
    task_bytes: bytes,
    input_bytes: bytes,
    evaluator_criteria_bytes: bytes,
    profile_criteria_bytes: bytes,
    contract: AlgorithmProblemContract,
    pipeline: MultiFileCandidatePipeline,
    bundle: FrozenEvaluatorBundle,
    profile_bytes: bytes,
    materials: Mapping[str, bytes],
    probe_results: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify registration-to-runtime identities and return a canonical binding receipt."""
    reg = _registration(registration)
    evaluator_criteria, profile_criteria = _criteria(evaluator_criteria_bytes, profile_criteria_bytes, reg)
    _digest_bytes(task_bytes, reg["task_sha256"], "task_material_mismatch")
    _digest_bytes(input_bytes, reg["input_sha256"], "input_material_mismatch")
    _verify_contract(contract, evaluator_criteria)
    if not isinstance(bundle, FrozenEvaluatorBundle):
        _fail("bundle_invalid")
    table = _input_table(pipeline)
    if len(table) != 1 or table[0]["target"] != "limit.json" or table[0]["source_label"] != "parent-input":
        _fail("input_table_semantics_mismatch")
    if table[0]["size"] != len(input_bytes) or table[0]["sha256"] != hashlib.sha256(input_bytes).hexdigest():
        _fail("input_table_material_mismatch")
    input_table_sha256 = hashlib.sha256(canonical_json(list(table))).hexdigest()
    if not isinstance(profile_bytes, bytes):
        _fail("profile_invalid")
    runtime_profile_sha256 = hashlib.sha256(profile_bytes).hexdigest()
    try:
        runtime_profile = strict_json(profile_bytes)
        if canonical_json(runtime_profile) != profile_bytes:
            _fail("profile_noncanonical")
    except AcceptanceRuntimeBindingError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("profile_invalid")
    profile_keys = {
        "schema_version", "protocol", "evaluator", "harness_path", "input_root", "inputs",
        "command", "environment", "timeout_seconds", "max_output_bytes",
        "dependency_sha256", "environment_sha256",
    }
    if (not isinstance(runtime_profile, dict) or set(runtime_profile) != profile_keys
            or runtime_profile.get("schema_version") != "1"
            or runtime_profile.get("protocol") != "lunar-bundle-pipeline-v1"):
        _fail("profile_invalid")
    try:
        expected_profile = {
            "schema_version": "1", "protocol": "lunar-bundle-pipeline-v1",
            "harness_path": "evaluator-bundle/evaluator.py", "input_root": "data/raw",
            "inputs": list(table), "command": list(pipeline.command),
            "environment": dict(pipeline.environment), "timeout_seconds": pipeline.timeout_seconds,
            "max_output_bytes": pipeline.max_output_bytes, "dependency_sha256": pipeline.dependency_sha256,
            "environment_sha256": pipeline.environment_sha256, "evaluator": pipeline.evaluator.to_dict(),
        }
        if profile_bytes != canonical_json(expected_profile):
            _fail("profile_binding_mismatch")
    except (KeyError, TypeError, ValueError):
        _fail("profile_binding_mismatch")
    harness_path = Path(pipeline.harness_path)
    try:
        harness_bytes = harness_path.read_bytes()
    except (OSError, UnicodeError):
        _fail("harness_unavailable")
    harness_sha256 = hashlib.sha256(harness_bytes).hexdigest()
    if pipeline.evaluator.harness_sha256 != harness_sha256:
        _fail("harness_mismatch")
    try:
        bundle_harness = (bundle.root / "evaluator.py").read_bytes()
    except (OSError, UnicodeError):
        _fail("bundle_harness_unavailable")
    if hashlib.sha256(bundle_harness).hexdigest() != harness_sha256:
        _fail("bundle_harness_mismatch")
    try:
        pipeline.preflight()
    except (EvolutionError, AttributeError, OSError, TypeError, ValueError):
        _fail("staged_input_mismatch")
    try:
        input_root = Path(pipeline.input_root)
        workspace_root = input_root.parent.parent
        if input_root != workspace_root / "data/raw":
            _fail("input_profile_binding_mismatch")
        input_profile = build_private_input_profile(workspace_root, contract, tuple(
            CandidateInputArtifact("data/raw/" + row["target"], row["size"], row["sha256"])
            for row in table
        ))
        input_profile_sha256 = profile_sha256(input_profile)
    except (DataProfileError, EvolutionError, AttributeError, OSError, TypeError, ValueError, RecursionError):
        _fail("input_profile_binding_mismatch")
    if bundle.input_profile_sha256 != input_profile_sha256:
        _fail("input_profile_binding_mismatch")
    if bundle.contract_sha256 != contract.digest() or bundle.invocation != "snapshot":
        _fail("bundle_binding_mismatch")
    try:
        verified = load_evaluator_bundle(
            bundle.root, contract, input_profile=input_profile,
            timeout=bundle.timeout_seconds, invocation="snapshot",
        )
    except (EvaluatorBundleError, OSError, TypeError, ValueError, RecursionError):
        _fail("bundle_binding_mismatch")
    if verified.fingerprint != bundle.fingerprint or verified.input_profile_sha256 != input_profile_sha256:
        _fail("bundle_binding_mismatch")
    probes = _probe_summary(probe_results, reg["holdout_pins"], materials, harness_sha256)
    receipt = {
        "schema_version": _SCHEMA,
        "scope": _SCOPE,
        "registration_id": reg["registration_id"], "campaign_id": reg["campaign_id"],
        "attempt_id": reg["attempt_id"], "registration_sha256": reg["registration_sha256"],
        "product_commit": reg["product_commit"],
        "task_material_sha256": reg["task_sha256"], "input_material_sha256": reg["input_sha256"],
        "evaluator_criteria_sha256": reg["evaluator_sha256"],
        "profile_criteria_sha256": reg["evaluator_profile_sha256"],
        "contract_sha256": contract.digest(), "input_table_sha256": input_table_sha256,
        "runtime_profile_sha256": runtime_profile_sha256, "harness_sha256": harness_sha256,
        "runtime_input_profile_sha256": input_profile_sha256,
        "evaluator_bundle_sha256": bundle.fingerprint, "probe_summary": probes,
        "criteria_profile_sha256": hashlib.sha256(canonical_json(profile_criteria)).hexdigest(),
    }
    receipt["binding_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


def prepare_acceptance_runtime_binding(
    registration: Mapping[str, Any],
    *,
    store: Any,
    parent_id: str,
    materials: Mapping[str, bytes],
    contract: AlgorithmProblemContract,
    workspace: Path,
    check_active: Any = None,
    remaining_timeout: Any = None,
) -> dict[str, Any]:
    """Validate a prepared parent, run the fixed holdouts once, and bind their receipt.

    The wrapper is provider-free.  Preparation is re-read before and after the holdout batch;
    the low-level binder then verifies the generated runtime identities and all detached evidence.
    ``workspace`` is create-only and is retained for later campaign publication/audit.
    """
    from .acceptance_holdouts import run_acceptance_holdouts
    from .automatic_solve_bundle import _parent, _read_preparation, validate_automatic_solve_bundle

    reg = _registration(registration)
    if not isinstance(materials, Mapping) or not isinstance(parent_id, str):
        _fail("binding_wrapper_invalid")
    if not isinstance(workspace, Path):
        _fail("binding_wrapper_invalid")
    try:
        materials = dict(materials)
        workspace = absolute_path(workspace)
        if check_active is not None:
            check_active()
        validate_automatic_solve_bundle(store, parent_id)
        parent, prepared_contract = _parent(store, parent_id)
        if prepared_contract is None or prepared_contract.digest() != contract.digest():
            _fail("prepared_contract_mismatch")
        _pipeline, bundle, profile_raw, _ = _read_preparation(store, parent, contract)
        pins = {
            "task": reg["task_sha256"], "input": reg["input_sha256"],
            "evaluator": reg["evaluator_sha256"], "profile": reg["evaluator_profile_sha256"],
        }
        def material(key: str, pin_key: str) -> bytes:
            descriptor = reg[pin_key]
            if not isinstance(descriptor, Mapping):
                _fail("material_binding_invalid")
            path = descriptor.get("path")
            value = materials.get(path) if isinstance(path, str) else None
            if not isinstance(value, bytes) or len(value) != descriptor.get("size"):
                _fail("material_binding_invalid")
            if hashlib.sha256(value).hexdigest() != pins[key]:
                _fail("material_binding_mismatch")
            return value
        task = material("task", "task_material")
        if parent.goal.encode("utf-8") != task:
            _fail("parent_task_material_mismatch")
        input_bytes = material("input", "input_material")
        evaluator_criteria = material("evaluator", "evaluator_material")
        profile_criteria = material("profile", "evaluator_profile_material")
        evaluator_criteria_value, _ = _criteria(evaluator_criteria, profile_criteria, reg)
        _verify_contract(contract, evaluator_criteria_value)
        before_events = [item for item in store.list_events(parent_id)
                         if item.get("type") == "bundle_profile_prepared"]
        if len(before_events) != 1:
            _fail("prepared_event_invalid")
        before_event = _canonical(before_events[0]["payload"])
        rows = run_acceptance_holdouts(
            reg, materials=materials, evaluator=bundle.root / "evaluator.py", contract=contract,
            workspace=workspace, check_active=check_active, remaining_timeout=remaining_timeout,
        )
        validate_automatic_solve_bundle(store, parent_id)
        current_parent, current_contract = _parent(store, parent_id)
        if (current_parent.workspace != parent.workspace or current_parent.goal != parent.goal
                or current_contract is None or current_contract.digest() != contract.digest()):
            _fail("prepared_parent_changed")
        current_pipeline, current_bundle, current_profile, _ = _read_preparation(store, current_parent, contract)
        if current_profile != profile_raw or current_bundle.fingerprint != bundle.fingerprint:
            _fail("prepared_artifacts_changed")
        receipt = bind_acceptance_runtime(
            reg, task_bytes=task, input_bytes=input_bytes,
            evaluator_criteria_bytes=evaluator_criteria, profile_criteria_bytes=profile_criteria,
            contract=contract, pipeline=current_pipeline, bundle=current_bundle, profile_bytes=current_profile,
            materials=materials,
            probe_results=rows,
        )
        events = [item for item in store.list_events(parent_id) if item.get("type") == "bundle_profile_prepared"]
        if len(events) != 1 or _canonical(events[0]["payload"]) != before_event:
            _fail("prepared_event_invalid")
        receipt = {
            **receipt, "parent_run_id": parent_id,
            "prepared_event_sha256": hashlib.sha256(_canonical(events[0]["payload"])).hexdigest(),
        }
        receipt.pop("binding_sha256", None)
        receipt["binding_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
        held = DirectoryChain(workspace, "binding_workspace_changed")
        try:
            for row in rows:
                ordinal = row["ordinal"]
                item = workspace / f"{ordinal:02d}"
                pin = reg["holdout_pins"][ordinal]
                expected_files = {
                    "snapshot.bin": materials[pin["input"]["path"]],
                    "expected.json": materials[pin["expected"]["path"]],
                    "actual.json": canonical_json(row["evidence"]["projection"]),
                    "evidence.json": _canonical(row["evidence"]),
                }
                for name, raw in expected_files.items():
                    if read_regular_file(item / name, len(raw), exact_size=True) != raw:
                        _fail("retained_probe_mismatch")
            held.check()
            if check_active is not None:
                check_active()
            if remaining_timeout is not None:
                from .acceptance_holdouts import _remaining
                _remaining(remaining_timeout, "binding-publish")
            fd = os.open("binding-receipt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=held.fd)
            try:
                content = _canonical(receipt)
                view = memoryview(content)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        _fail("binding_write_failed")
                    view = view[written:]
                os.fsync(fd)
                written_info = os.fstat(fd)
            finally:
                os.close(fd)
            os.fsync(held.fd)
            held.check()
            named = os.stat("binding-receipt.json", dir_fd=held.fd, follow_symlinks=False)
            if (not stat.S_ISREG(named.st_mode) or named.st_nlink != 1
                    or stat.S_IMODE(named.st_mode) != 0o600
                    or (named.st_dev, named.st_ino) != (written_info.st_dev, written_info.st_ino)
                    or read_regular_file(workspace / "binding-receipt.json", len(content), exact_size=True) != content):
                _fail("binding_receipt_changed")
        finally:
            held.close()
        return receipt
    except AcceptanceRuntimeBindingError:
        raise
    except (EvolutionError, AttributeError, KeyError, OSError, TypeError, ValueError, RecursionError):
        _fail("binding_wrapper_failed")


__all__ = [
    "AcceptanceRuntimeBindingError", "bind_acceptance_runtime", "prepare_acceptance_runtime_binding",
]
