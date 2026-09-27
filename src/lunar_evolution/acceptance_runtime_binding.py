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
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .acceptance_registration import AcceptanceRegistrationError, parse_acceptance_registration
from .algorithm import AlgorithmProblemContract
from .bundle_evolution import MultiFileCandidatePipeline
from .candidate_evaluation_spec import canonical_json
from .candidate_execution import CandidateExecutionInput
from .evaluator_bundle import EvaluatorBundleError, FrozenEvaluatorBundle, load_evaluator_bundle

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
    result = dict(registration)
    # A full acceptance manifest is canonical and digest-bound.  Keep the small fixture
    # shape useful for local unit tests, but never silently downgrade a production manifest.
    if "holdout_pins" in result:
        try:
            result = parse_acceptance_registration(result)
        except (AcceptanceRegistrationError, TypeError, ValueError):
            _fail("registration_invalid")
    return result


def _criteria(evaluator_bytes: bytes, profile_bytes: bytes, registration: Mapping[str, Any]) -> tuple[dict, dict]:
    _digest_bytes(evaluator_bytes, registration["evaluator_sha256"], "evaluator_criteria_mismatch")
    _digest_bytes(profile_bytes, registration["evaluator_profile_sha256"], "profile_criteria_mismatch")
    try:
        evaluator, profile = json.loads(evaluator_bytes), json.loads(profile_bytes)
    except (TypeError, ValueError, UnicodeDecodeError, RecursionError):
        _fail("criteria_json_invalid")
    if not isinstance(evaluator, dict) or not isinstance(profile, dict):
        _fail("criteria_json_invalid")
    if (evaluator.get("kind") != "independent_evaluator_criteria"
            or profile.get("kind") != "independent_evaluator_profile_criteria"
            or profile.get("evaluator_criteria_sha256") != registration["evaluator_sha256"]
            or profile.get("holdout_count") != 8
            or profile.get("invocation") != "snapshot"
            or profile.get("independent_audit") is not True):
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
    holdout_pins: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if probe_results is None:
        _fail("probe_results_missing")
    if not isinstance(probe_results, Sequence) or isinstance(probe_results, (str, bytes)):
        _fail("probe_results_invalid")
    if len(probe_results) != 8:
        _fail("probe_count_invalid")
    values = []
    pins = {item["ordinal"]: item for item in holdout_pins} if holdout_pins is not None else None
    if pins is not None and set(pins) != set(range(8)):
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
        }
        if set(evidence) != expected_keys:
            _fail("probe_result_invalid")
        if evidence.get("passed") is not True or evidence.get("reason") != "passed":
            _fail("probe_result_incomplete")
        if evidence.get("cleanup") != "verified":
            _fail("probe_cleanup_unknown")
        if (evidence.get("process_exit_code") != 0
                or evidence.get("native_exit_code") != 0
                or evidence.get("observer_identity") is None
                or evidence.get("observer_identity") != evidence.get("release_identity")):
            _fail("probe_process_invalid")
        duration = evidence.get("duration_ms")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            _fail("probe_result_invalid")
        for key in (
            "input_sha256", "expected_output_sha256", "actual_output_sha256",
            "report_sha256", "projection_sha256",
        ):
            _sha(evidence.get(key), "probe_digest_invalid")
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
        except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
            _fail("probe_report_invalid")
        if hashlib.sha256(report_bytes).hexdigest() != evidence["report_sha256"]:
            _fail("probe_report_invalid")
        if item.get("outcome", "passed") != "passed":
            _fail("probe_result_incomplete")
        if pins is not None:
            holdout_id = item.get("holdout_id")
            pin = pins[index]
            if holdout_id != pin.get("holdout_id"):
                _fail("probe_identity_mismatch")
            for field, pin_field in (("input_sha256", "input"), ("expected_output_sha256", "expected")):
                digest = item.get(field)
                expected_pin = pin.get(pin_field)
                if (not isinstance(expected_pin, Mapping)
                        or digest != expected_pin.get("sha256")):
                    _fail("probe_material_mismatch")
            if item.get("actual_output_sha256") != evidence["actual_output_sha256"]:
                _fail("probe_projection_mismatch")
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
    profile_sha256 = hashlib.sha256(profile_bytes).hexdigest()
    try:
        runtime_profile = json.loads(profile_bytes)
    except (TypeError, ValueError, UnicodeDecodeError, RecursionError):
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
        if (runtime_profile["harness_path"] != "evaluator-bundle/evaluator.py"
                or runtime_profile["input_root"] != "data/raw"
                or runtime_profile["inputs"] != list(table)
                or tuple(runtime_profile["command"]) != tuple(pipeline.command)
                or runtime_profile["environment"] != dict(pipeline.environment)
                or runtime_profile["timeout_seconds"] != pipeline.timeout_seconds
                or runtime_profile["max_output_bytes"] != pipeline.max_output_bytes
                or runtime_profile["dependency_sha256"] != pipeline.dependency_sha256
                or runtime_profile["environment_sha256"] != pipeline.environment_sha256):
            _fail("profile_binding_mismatch")
        runtime_evaluator = runtime_profile["evaluator"]
        if not isinstance(runtime_evaluator, Mapping) or runtime_evaluator != pipeline.evaluator.to_dict():
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
    if bundle.contract_sha256 != contract.digest() or bundle.invocation != "snapshot":
        _fail("bundle_binding_mismatch")
    try:
        verified = load_evaluator_bundle(
            bundle.root, contract, timeout=bundle.timeout_seconds, invocation="snapshot",
        )
    except (EvaluatorBundleError, OSError, TypeError, ValueError, RecursionError):
        _fail("bundle_binding_mismatch")
    if verified.fingerprint != bundle.fingerprint:
        _fail("bundle_binding_mismatch")
    probes = _probe_summary(probe_results, reg.get("holdout_pins"))
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
        "runtime_profile_sha256": profile_sha256, "harness_sha256": harness_sha256,
        "evaluator_bundle_sha256": bundle.fingerprint, "probe_summary": probes,
        "criteria_profile_sha256": hashlib.sha256(canonical_json(profile_criteria)).hexdigest(),
    }
    receipt["binding_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


__all__ = ["AcceptanceRuntimeBindingError", "bind_acceptance_runtime"]
