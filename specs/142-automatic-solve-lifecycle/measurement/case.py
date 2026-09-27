"""Fixed, provider-free reference materials for the next real acceptance.

These are task and independent reference criteria, not a generated evaluator or
evaluator profile. The latter acquire separate runtime identities after preparation.
"""
from __future__ import annotations

import hashlib
import json

PROVIDER = "openai-compatible"
MODEL = "glm-5.2"
API_MODE = "chat_completions"
CONFIGURED_API_MODE = "responses"
CLI_ENTRYPOINT = "solve --evolve --multi-file"
MATERIAL_ROOT = "specs/142-automatic-solve-lifecycle/measurement/materials"

TASK_TEXT = (
    "Read the single attached input limit.json, a JSON object with the single field limit, "
    "a nonnegative JSON integer excluding booleans and floats. Produce the single required "
    "structured output output/result.json, a JSON object containing the field value. The "
    "output value must be a JSON integer excluding booleans and floats (Python type(value) "
    "is int after JSON parsing) and satisfy 0 <= value <= limit. Maximize value; feasible "
    "suboptimal values are valid. Independently read both files and recompute validity=1, "
    "quality=value and combined_score=value for valid outputs. For invalid outputs use "
    "validity=0, quality=null, combined_score=0 and error_info code valid-value. "
    "Use exactly two hard constraints: valid-value with verification=independent, "
    "verification_scope=output and result_fields=[value]; python-files with "
    "verification=independent, verification_scope=source, result_fields=[] and "
    "source_check={kind: python_file_count, minimum: 2}. Deliver at least two distinct "
    "source paths ending with lowercase .py, including the entrypoint. This source check "
    "only counts paths; it does not require imports, helper use, syntax or dependencies. "
    "Use no soft constraints or execution constraints. The contract has exactly one "
    "input path limit.json, format=json, fields={limit: a nonnegative integer}; exactly "
    "one required output path output/result.json, format=json, fields=[value]; and "
    "deliverables=[output/result.json]. Use one maximize objective without metrics, "
    "and population evolution. Generate the contract and evaluator automatically."
)
TASK_BYTES = TASK_TEXT.encode("utf-8")
INPUT_BYTES = b'{"limit":3}\n'
HOLDOUT_PAIRS = ((1, -1), (1, 0), (1, 1), (1, 2),
                 (3, 0), (3, 2), (3, 3), (3, 4))


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _probe(limit: int, value: int) -> dict[str, object]:
    valid = 0 <= value <= limit
    name = f"limit-{limit}-value-{'minus-' if value < 0 else ''}{abs(value)}"
    return {
        "name": name,
        "constraint_id": None if valid else "valid-value",
        "expected_validity": int(valid),
        "files": [
            {"path": "data/raw/limit.json", "content": f'{{"limit":{limit}}}\n'},
            {"path": "output/result.json", "content": f'{{"value":{value}}}\n'},
        ],
    }


def _expected(limit: int, value: int) -> dict[str, object]:
    valid = 0 <= value <= limit
    return {
        "validity": int(valid),
        "quality": value if valid else None,
        "combined_score": value if valid else 0,
        "constraint_code": None if valid else "valid-value",
    }


def build_case_materials() -> dict[str, bytes]:
    """Return fresh path-to-byte materials; no runtime source is read or executed."""
    evaluator = _canonical({
        "schema_version": "1",
        "kind": "independent_evaluator_criteria",
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
        "source_path_check_only": True,
        "hard_constraints": ["valid-value", "python-files"],
        "objective": "maximize",
    })
    profile = _canonical({
        "schema_version": "1",
        "kind": "independent_evaluator_profile_criteria",
        "evaluator_criteria_sha256": _sha(evaluator),
        "generated_bundle_required": True,
        "invocation": "snapshot",
        "independent_audit": True,
        "holdout_count": len(HOLDOUT_PAIRS),
    })
    materials = {
        "task.txt": TASK_BYTES,
        "input/limit.json": INPUT_BYTES,
        "reference/evaluator-criteria.json": evaluator,
        "reference/profile-criteria.json": profile,
    }
    for ordinal, (limit, value) in enumerate(HOLDOUT_PAIRS):
        prefix = f"holdouts/{ordinal:02d}"
        materials[f"{prefix}/snapshot.json"] = _canonical(_probe(limit, value))
        materials[f"{prefix}/expected.json"] = _canonical(_expected(limit, value))
    return materials


def build_case_pins() -> dict[str, object]:
    """Return registration-shaped pins for the reference materials only."""
    materials = build_case_materials()

    def pin(path: str) -> dict[str, object]:
        content = materials[path]
        return {"path": f"{MATERIAL_ROOT}/{path}", "size": len(content),
                "sha256": _sha(content)}

    return {
        "task_material": pin("task.txt"),
        "input_material": pin("input/limit.json"),
        "evaluator_material": pin("reference/evaluator-criteria.json"),
        "evaluator_profile_material": pin("reference/profile-criteria.json"),
        "holdout_pins": [
            {
                "holdout_id": _probe(limit, value)["name"],
                "ordinal": ordinal,
                "input": pin(f"holdouts/{ordinal:02d}/snapshot.json"),
                "expected": pin(f"holdouts/{ordinal:02d}/expected.json"),
                "max_duration_ms": 5000,
            }
            for ordinal, (limit, value) in enumerate(HOLDOUT_PAIRS)
        ],
    }
