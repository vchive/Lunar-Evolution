"""Fixed real-acceptance reference bytes, without loading historical runtime code."""
import hashlib
import importlib.util
import json
from pathlib import Path

_CASE_PATH = (Path(__file__).resolve().parents[1] / "specs" /
              "142-automatic-solve-lifecycle" / "measurement" / "case.py")
_SPEC = importlib.util.spec_from_file_location("acceptance_case", _CASE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
case = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(case)


def test_historical_task_and_input_are_byte_exact() -> None:
    materials = case.build_case_materials()
    assert materials["task.txt"] == case.TASK_BYTES
    assert hashlib.sha256(materials["task.txt"]).hexdigest() == (
        "2c015edee8cac2c0a36a02acb9de86cc741e2bce60e340f5dfd4c3f1e67b3028"
    )
    assert materials["input/limit.json"] == b'{"limit":3}\n'
    assert hashlib.sha256(materials["input/limit.json"]).hexdigest() == (
        "a87f29f60db7ebd0d5269a34a8be49b964bb77e62ee38f77987aced80accb5c7"
    )
    assert (case.PROVIDER, case.MODEL, case.API_MODE) == (
        "openai-compatible", "glm-5.2", "chat_completions",
    )
    assert case.CONFIGURED_API_MODE == "responses"


def test_eight_snapshot_probes_and_independent_judgments() -> None:
    materials = case.build_case_materials()
    assert len(materials) == 20
    assert case.HOLDOUT_PAIRS == ((1, -1), (1, 0), (1, 1), (1, 2),
                                  (3, 0), (3, 2), (3, 3), (3, 4))
    for ordinal, (limit, value) in enumerate(case.HOLDOUT_PAIRS):
        prefix = f"holdouts/{ordinal:02d}"
        probe = json.loads(materials[f"{prefix}/snapshot.json"])
        expected = json.loads(materials[f"{prefix}/expected.json"])
        valid = 0 <= value <= limit
        assert probe["files"] == [
            {"path": "data/raw/limit.json", "content": f'{{"limit":{limit}}}\n'},
            {"path": "output/result.json", "content": f'{{"value":{value}}}\n'},
        ]
        assert probe["expected_validity"] == int(valid)
        assert probe["constraint_id"] == (None if valid else "valid-value")
        assert expected == {
            "validity": int(valid), "quality": value if valid else None,
            "combined_score": value if valid else 0,
            "constraint_code": None if valid else "valid-value",
        }


def test_pins_cover_fresh_deterministic_materials_not_generated_evaluator() -> None:
    materials = case.build_case_materials()
    pins = case.build_case_pins()
    assert pins == case.build_case_pins()
    assert len({item["path"] for item in (
        pins["task_material"], pins["input_material"], pins["evaluator_material"],
        pins["evaluator_profile_material"],
        *(row[key] for row in pins["holdout_pins"] for key in ("input", "expected")),
    )}) == len(materials)
    for item in (pins["task_material"], pins["input_material"],
                 pins["evaluator_material"], pins["evaluator_profile_material"],
                 *(row[key] for row in pins["holdout_pins"] for key in ("input", "expected"))):
        path = item["path"]
        assert path.startswith(case.MATERIAL_ROOT + "/")
        data = materials[path.removeprefix(case.MATERIAL_ROOT + "/")]
        assert item["size"] == len(data)
        assert item["sha256"] == hashlib.sha256(data).hexdigest()
        assert (_CASE_PATH.parent / "materials" / path.removeprefix(case.MATERIAL_ROOT + "/")).read_bytes() == data
    assert all(row["ordinal"] == index and row["max_duration_ms"] == 5000
               for index, row in enumerate(pins["holdout_pins"]))
    criteria = json.loads(materials["reference/evaluator-criteria.json"])
    profile = json.loads(materials["reference/profile-criteria.json"])
    assert criteria["kind"] == "independent_evaluator_criteria"
    assert criteria["hard_constraints"] == ["valid-value", "python-files"]
    assert profile["evaluator_criteria_sha256"] == pins["evaluator_material"]["sha256"]
    assert profile["generated_bundle_required"] is True
    materials["task.txt"] = b"changed"
    assert case.build_case_materials()["task.txt"] == case.TASK_BYTES
