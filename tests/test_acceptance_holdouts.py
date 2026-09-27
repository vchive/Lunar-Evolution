from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from lunar_evolution.acceptance_holdouts import AcceptanceHoldoutError, run_acceptance_holdouts
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionCancelled


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
        holdout_id = f"limit-{limit}-value-{'minus-' if value < 0 else ''}{abs(value)}"
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
        assert hashlib.sha256((item / "actual.json").read_bytes()).hexdigest() == row["actual_output_sha256"]


def test_real_frozen_evaluator_runs_all_eight_materialized_probes(tmp_path: Path):
    """Exercise the actual snapshot subprocess once per registered eight-pair batch."""
    raw, registration = materials()
    rows = run_acceptance_holdouts(
        registration, materials=raw, evaluator=evaluator(tmp_path), contract=contract(),
        workspace=tmp_path / "holdouts",
    )
    assert len(rows) == 8
    assert [row["ordinal"] for row in rows] == list(range(8))
    assert all(row["outcome"] == "passed" for row in rows)
    assert all((tmp_path / "holdouts" / f"{index:02d}" / "probe").is_dir() for index in range(8))


def test_materials_are_validated_before_root_creation(tmp_path: Path, monkeypatch):
    import lunar_evolution.acceptance_holdouts as module

    execute = Mock(side_effect=AssertionError("late invalid material must not execute any probe"))
    monkeypatch.setattr(module, "run_acceptance_snapshot_probe", execute)
    raw, registration = materials()
    raw["exp-7"] = b"{}"
    with pytest.raises(AcceptanceHoldoutError, match="holdout_expected_invalid|holdout_pair_invalid"):
        run_acceptance_holdouts(registration, materials=raw, evaluator=evaluator(tmp_path), contract=contract(), workspace=tmp_path / "holdouts")
    assert not (tmp_path / "holdouts").exists()
    execute.assert_not_called()


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


def test_reordered_pairs_rehashed_under_same_material_paths_fail_before_start(tmp_path, monkeypatch):
    import lunar_evolution.acceptance_holdouts as module

    execute = Mock(side_effect=AssertionError("reordered pairs must never execute"))
    monkeypatch.setattr(module, "run_acceptance_snapshot_probe", execute)
    raw, registration = materials()
    for kind, prefix in (("input", "in"), ("expected", "exp")):
        raw[f"{prefix}-6"], raw[f"{prefix}-7"] = raw[f"{prefix}-7"], raw[f"{prefix}-6"]
        for index in (6, 7):
            pin = registration["holdout_pins"][index][kind]
            pin["size"] = len(raw[pin["path"]])
            pin["sha256"] = hashlib.sha256(raw[pin["path"]]).hexdigest()
    for index in (6, 7):
        registration["holdout_pins"][index]["holdout_id"] = json.loads(raw[f"in-{index}"])["name"]
    with pytest.raises(AcceptanceHoldoutError, match="holdout_pair_invalid"):
        run_acceptance_holdouts(registration, materials=raw, evaluator=evaluator(tmp_path),
                                contract=contract(), workspace=tmp_path / "holdouts")
    execute.assert_not_called()
    assert not (tmp_path / "holdouts").exists()


@pytest.mark.parametrize("failure", ["nan", "cancelled"])
def test_cancelled_or_unknown_deadline_burns_root_and_refuses_reuse(tmp_path, monkeypatch, failure):
    import lunar_evolution.acceptance_holdouts as module

    execute = Mock(side_effect=AssertionError("inactive batch must not start"))
    monkeypatch.setattr(module, "run_acceptance_snapshot_probe", execute)
    raw, registration = materials()
    root = tmp_path / "holdouts"
    harness = evaluator(tmp_path)

    def cancel():
        raise SolveExecutionCancelled("cancelled")

    options = {"remaining_timeout": lambda _stage: float("nan")} if failure == "nan" else {"check_active": cancel}
    expected_error = AcceptanceHoldoutError if failure == "nan" else SolveExecutionCancelled
    with pytest.raises(expected_error):
        run_acceptance_holdouts(registration, materials=raw, evaluator=harness,
                                contract=contract(), workspace=root, **options)
    assert root.is_dir() and list(root.iterdir()) == []
    execute.assert_not_called()
    with pytest.raises(AcceptanceHoldoutError, match="holdout_workspace_exists"):
        run_acceptance_holdouts(registration, materials=raw, evaluator=harness,
                                contract=contract(), workspace=root)


@pytest.mark.parametrize("target", ["parent", "root", "ordinal", "probe"])
def test_active_callback_path_swap_is_rejected_before_evaluator(tmp_path, monkeypatch, target):
    import lunar_evolution.acceptance_holdouts as module

    execute = Mock(side_effect=AssertionError("a replaced path must not execute"))
    monkeypatch.setattr(module, "run_acceptance_snapshot_probe", execute)
    raw, registration = materials()
    harness = evaluator(tmp_path)
    parent = tmp_path / "campaign"
    parent.mkdir()
    root = parent / "holdouts"
    paths = {"parent": parent, "root": root, "ordinal": root / "00", "probe": root / "00" / "probe"}
    changed = []

    def swap_before_execution():
        if changed or not (root / "00" / "snapshot.bin").exists():
            return
        path = paths[target]
        path.rename(path.with_name(path.name + ".retained"))
        path.mkdir(mode=0o700)
        changed.append(path)

    with pytest.raises(AcceptanceHoldoutError, match="holdout_workspace_changed"):
        run_acceptance_holdouts(registration, materials=raw, evaluator=harness,
                                contract=contract(), workspace=root, check_active=swap_before_execution)
    execute.assert_not_called()
    assert changed


def test_remaining_callback_path_swap_is_rejected_before_evaluator(tmp_path, monkeypatch):
    import lunar_evolution.acceptance_holdouts as module

    execute = Mock(side_effect=AssertionError("a replaced path must not execute"))
    monkeypatch.setattr(module, "run_acceptance_snapshot_probe", execute)
    raw, registration = materials()
    root = tmp_path / "holdouts"

    def swap_probe(stage):
        if stage.endswith("-run"):
            probe = root / "00" / "probe"
            probe.rename(root / "00" / "probe.retained")
            probe.mkdir()
        return 5

    with pytest.raises(AcceptanceHoldoutError, match="holdout_workspace_changed"):
        run_acceptance_holdouts(registration, materials=raw, evaluator=evaluator(tmp_path),
                                contract=contract(), workspace=root, remaining_timeout=swap_probe)
    execute.assert_not_called()


@pytest.mark.parametrize("mutation", ["input_path", "input_fields", "extra_input", "output_path", "output_fields", "output_optional", "extra_output"])
def test_contract_mismatch_is_rejected_before_root_or_execution(tmp_path, monkeypatch, mutation):
    import lunar_evolution.acceptance_holdouts as module

    execute = Mock(side_effect=AssertionError("mismatched contract must never execute"))
    monkeypatch.setattr(module, "run_acceptance_snapshot_probe", execute)
    value = contract().to_dict()
    if mutation == "input_path": value["inputs"][0]["path"] = "other.json"
    elif mutation == "input_fields": value["inputs"][0]["fields"]["other"] = "integer"
    elif mutation == "extra_input": value["inputs"].append({"path": "other.json", "format": "json", "fields": {"other": "integer"}})
    elif mutation == "output_path": value["outputs"][0]["path"] = "output/other.json"
    elif mutation == "output_fields": value["outputs"][0]["fields"].append("other")
    elif mutation == "output_optional": value["outputs"][0]["required"] = False
    elif mutation == "extra_output": value["outputs"].append({"path": "output/other.json", "format": "json", "fields": ["other"]})
    raw, registration = materials()
    with pytest.raises(AcceptanceHoldoutError, match="holdout_contract_mismatch"):
        run_acceptance_holdouts(registration, materials=raw, evaluator=evaluator(tmp_path),
                                contract=AlgorithmProblemContract.from_dict(value), workspace=tmp_path / "holdouts")
    execute.assert_not_called()
    assert not (tmp_path / "holdouts").exists()


@pytest.mark.parametrize(("key", "value"), [("ordinal", False), ("max_duration_ms", True), ("max_duration_ms", 5001)])
def test_boolean_ordinal_or_invalid_duration_rejected_before_root(tmp_path, key, value):
    raw, registration = materials()
    registration["holdout_pins"][0][key] = value
    with pytest.raises(AcceptanceHoldoutError):
        run_acceptance_holdouts(registration, materials=raw, evaluator=evaluator(tmp_path),
                                contract=contract(), workspace=tmp_path / "holdouts")
    assert not (tmp_path / "holdouts").exists()
