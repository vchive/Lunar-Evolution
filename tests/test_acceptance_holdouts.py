from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lunar_evolution.acceptance_holdouts import AcceptanceHoldoutError, run_acceptance_holdouts
from lunar_evolution.algorithm import AlgorithmProblemContract


def contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "holdout", "problem_type": "continuous",
        "statement": "choose value", "inputs": [{"path": "limit.json", "format": "json", "fields": {"limit": "integer"}}],
        "decision_variables": ["value"], "objective": {"name": "value", "direction": "maximize"},
        "hard_constraints": [{"id": "valid-value", "description": "in range", "source": "user_confirmed", "verification": "independent"}],
        "soft_constraints": [], "success_criteria": ["valid"], "deliverables": ["output/result.json"], "assumptions": [],
        "outputs": [{"path": "output/result.json", "format": "json", "fields": ["value"]}],
        "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
    })


def evaluator(root: Path) -> Path:
    path = root / "evaluator.py"
    path.write_text('''import json, pathlib
req=json.loads(pathlib.Path("request.json").read_text())
limit=json.loads((pathlib.Path("inputs") / "limit.json").read_text())["limit"]
value=json.loads((pathlib.Path("output") / "result.json").read_text())["value"]
valid=type(value) is int and 0 <= value <= limit
print(json.dumps({"schema_version":"1","evaluator_id":"compiled-bundle","validity":int(valid),"quality":value if valid else None,"combined_score":value if valid else 0,"detailed_scores":{},"error_info":[] if valid else [{"code":"valid-value","message":"invalid"}]}))
''', encoding="utf-8")
    return path


def materials() -> tuple[dict[str, bytes], dict[str, object]]:
    values = ((1, -1), (1, 0), (1, 1), (1, 2), (3, 0), (3, 2), (3, 3), (3, 4))
    out: dict[str, bytes] = {}
    pins = []
    for ordinal, (limit, value) in enumerate(values):
        holdout_id = f"p-{limit}-{value}"
        snapshot = json.dumps({"name": holdout_id, "constraint_id": None if 0 <= value <= limit else "valid-value", "expected_validity": int(0 <= value <= limit), "files": [{"path": "data/raw/limit.json", "content": f'{{"limit":{limit}}}\n'}, {"path": "output/result.json", "content": f'{{"value":{value}}}\n'}]}, sort_keys=True, separators=(",", ":")).encode()
        valid = 0 <= value <= limit
        expected = json.dumps({"validity": int(valid), "quality": value if valid else None, "combined_score": value if valid else 0, "constraint_code": None if valid else "valid-value"}, sort_keys=True, separators=(",", ":")).encode()
        ipath, epath = f"in-{ordinal}", f"exp-{ordinal}"
        out[ipath] = snapshot; out[epath] = expected
        pins.append({"ordinal": ordinal, "holdout_id": holdout_id, "input": {"path": ipath, "size": len(snapshot), "sha256": hashlib.sha256(snapshot).hexdigest()}, "expected": {"path": epath, "size": len(expected), "sha256": hashlib.sha256(expected).hexdigest()}, "max_duration_ms": 5000})
    return out, {"holdout_pins": pins}


def test_runs_all_eight_once_and_retains_raw_projection_evidence(tmp_path: Path, monkeypatch):
    raw, registration = materials()
    import lunar_evolution.acceptance_holdouts as module
    def fake_probe(_evaluator, probe, _contract, workspace, *, expected, timeout_seconds, check_active):
        actual = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
        evidence = {
            "report": {"ok": True}, "projection": dict(expected), "expected": dict(expected),
            "passed": True, "reason": "passed", "duration_ms": 1,
            "process_exit_code": 0, "native_exit_code": 0, "cleanup": "verified",
            "observer_identity": [1, 1], "release_identity": [1, 1],
            "input_sha256": hashlib.sha256(b"input").hexdigest(),
            "expected_output_sha256": hashlib.sha256(actual).hexdigest(),
            "actual_output_sha256": hashlib.sha256(actual).hexdigest(),
            "report_sha256": hashlib.sha256(b'{"ok":true}').hexdigest(),
            "projection_sha256": hashlib.sha256(actual).hexdigest(),
        }
        class FakeEvidence:
            passed = True
            reason = "passed"
            actual_output_bytes = actual
            def to_dict(self): return evidence
        return FakeEvidence()
    monkeypatch.setattr(module, "run_acceptance_snapshot_probe", fake_probe)
    rows = run_acceptance_holdouts(registration, materials=raw, evaluator=evaluator(tmp_path), contract=contract(), workspace=tmp_path / "holdouts")
    assert len(rows) == 8 and [row["ordinal"] for row in rows] == list(range(8))
    assert all(row["outcome"] == "passed" for row in rows)
    for ordinal, row in enumerate(rows):
        item = tmp_path / "holdouts" / f"{ordinal:02d}"
        assert (item / "snapshot.bin").read_bytes() == raw[f"in-{ordinal}"]
        assert (item / "expected.json").read_bytes() == raw[f"exp-{ordinal}"]
        assert json.loads((item / "actual.json").read_bytes()) == row["evidence"]["projection"]
        assert json.loads((item / "evidence.json").read_bytes()) == row["evidence"]
        assert hashlib.sha256(row["evidence"]["actual_output_sha256"].encode()).digest()  # bounded shape


def test_materials_are_validated_before_root_creation(tmp_path: Path):
    raw, registration = materials()
    raw["exp-7"] = b"{}"
    with pytest.raises(AcceptanceHoldoutError, match="holdout_expected_invalid|holdout_pair_invalid"):
        run_acceptance_holdouts(registration, materials=raw, evaluator=evaluator(tmp_path), contract=contract(), workspace=tmp_path / "holdouts")
    assert not (tmp_path / "holdouts").exists()


def test_root_is_create_only_and_active_callback_runs_before_each(tmp_path: Path):
    raw, registration = materials(); root = tmp_path / "holdouts"; root.mkdir()
    with pytest.raises(AcceptanceHoldoutError, match="holdout_workspace_exists"):
        run_acceptance_holdouts(registration, materials=raw, evaluator=evaluator(tmp_path), contract=contract(), workspace=root)
    root.rmdir()
    calls: list[str] = []
    rows = run_acceptance_holdouts(registration, materials=raw, evaluator=evaluator(tmp_path), contract=contract(), workspace=root, check_active=lambda: calls.append("active"), remaining_timeout=lambda stage: calls.append(stage) or 20)
    assert len(rows) == 8 and calls.count("active") >= 16 and any(item.endswith("before") for item in calls)


def test_duplicate_or_reordered_ids_are_rejected(tmp_path: Path):
    raw, registration = materials(); registration["holdout_pins"][1]["holdout_id"] = registration["holdout_pins"][0]["holdout_id"]
    with pytest.raises(AcceptanceHoldoutError, match="holdout_identity_invalid"):
        run_acceptance_holdouts(registration, materials=raw, evaluator=evaluator(tmp_path), contract=contract(), workspace=tmp_path / "holdouts")
