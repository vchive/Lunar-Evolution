from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution.acceptance_probes import AcceptanceProbeError, run_acceptance_snapshot_probe
from lunar_evolution.algorithm import AlgorithmProblemContract, EvaluationReport
from lunar_evolution.evaluator_bundle import EvaluatorProbe, ProbeFile


def contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "probe", "problem_type": "continuous",
        "statement": "choose value", "inputs": [{"path": "limit.json", "format": "json", "fields": {"limit": "integer"}}],
        "decision_variables": ["value"], "objective": {"name": "value", "direction": "maximize"},
        "hard_constraints": [{"id": "valid-value", "description": "in range", "source": "user_confirmed", "verification": "independent"}],
        "soft_constraints": [], "success_criteria": ["valid"], "deliverables": ["output/result.json"], "assumptions": [],
        "outputs": [{"path": "output/result.json", "format": "json", "fields": ["value"]}],
        "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
    })


def source(root: Path, sleep: float = 0) -> Path:
    path = root / "acceptance_probe_harness.py"
    path.write_text(f'''import json, pathlib, time\n\nif {sleep!r}: time.sleep({sleep!r})\nreq=json.loads(pathlib.Path("request.json").read_text())\nraw=json.loads((pathlib.Path("inputs") / "limit.json").read_text())\nout=json.loads(pathlib.Path("output/result.json").read_text())\nvalue=out["value"]\nvalid=type(value) is int and not isinstance(value,bool) and 0 <= value <= raw["limit"]\nprint(json.dumps({{"schema_version":"1","evaluator_id":"compiled-bundle","validity":int(valid),"quality":value if valid else None,"combined_score":value if valid else 0,"detailed_scores":{{}},"error_info":[] if valid else [{{"code":"valid-value","message":"invalid"}}]}}))\n''', encoding="utf-8")
    return path


def probe(value: int, limit: int = 3, validity: int | None = None) -> EvaluatorProbe:
    valid = 0 <= value <= limit
    return EvaluatorProbe(
        f"p-{limit}-{value}", None if valid else "valid-value", int(valid) if validity is None else validity,
        (ProbeFile("data/raw/limit.json", f'{{"limit":{limit}}}\n'), ProbeFile("output/result.json", f'{{"value":{value}}}\n')),
    )


def expected(value: int, limit: int = 3) -> dict[str, object]:
    valid = 0 <= value <= limit
    return {"validity": int(valid), "quality": value if valid else None, "combined_score": value if valid else 0, "constraint_code": None if valid else "valid-value"}


def test_native_snapshot_probe_returns_projection_and_cleanup(tmp_path):
    harness = source(tmp_path)
    result = run_acceptance_snapshot_probe(harness, probe(2), contract(), tmp_path / "work", expected=expected(2))
    assert result.passed is True
    assert result.reason == "passed"
    assert result.projection == expected(2)
    assert result.process_exit_code == result.native_exit_code == 0
    assert result.cleanup == "verified"
    assert result.observer_identity == result.release_identity
    assert result.actual_output_bytes == result.expected_output_bytes
    assert result.to_dict()["report_sha256"]


def test_wrong_projection_is_failed_even_when_process_exits_zero(tmp_path):
    harness = source(tmp_path)
    result = run_acceptance_snapshot_probe(harness, probe(2), contract(), tmp_path / "work", expected=expected(1))
    assert result.passed is False
    assert result.reason == "projection_mismatch"
    assert result.process_exit_code == 0


def test_invalid_value_has_independent_constraint_projection(tmp_path):
    harness = source(tmp_path)
    result = run_acceptance_snapshot_probe(harness, probe(4), contract(), tmp_path / "work", expected=expected(4))
    assert result.passed is True
    assert result.projection == expected(4)
    assert result.projection["constraint_code"] == "valid-value"


def test_timeout_keeps_cleanup_unknown(tmp_path):
    harness = source(tmp_path, 0.2)
    result = run_acceptance_snapshot_probe(harness, probe(2), contract(), tmp_path / "work", expected=expected(2), timeout_seconds=0.01)
    assert result.passed is False
    assert result.reason in {"process_failed", "process_timed_out"}
    assert result.cleanup == "unknown"


def test_pre_cancel_does_not_execute_probe(tmp_path):
    harness = source(tmp_path)
    calls = []
    def cancel():
        calls.append(1)
        raise RuntimeError("cancel")
    result = run_acceptance_snapshot_probe(harness, probe(2), contract(), tmp_path / "work", expected=expected(2), check_active=cancel)
    assert result.reason == "cancelled"
    assert result.process_exit_code is None
    assert calls


@pytest.mark.parametrize("key", ["validity", "quality", "combined_score", "constraint_code"])
def test_expected_projection_is_strict(tmp_path, key):
    value = expected(2)
    value.pop(key)
    with pytest.raises(AcceptanceProbeError, match="expected_projection_invalid"):
        run_acceptance_snapshot_probe(source(tmp_path), probe(2), contract(), tmp_path / "work", expected=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_probe_rejects_nonfinite_timeout_before_execution(tmp_path, value):
    with pytest.raises(AcceptanceProbeError, match="timeout_invalid"):
        run_acceptance_snapshot_probe(source(tmp_path), probe(2), contract(), tmp_path / "work",
                                      expected=expected(2), timeout_seconds=value)


def test_missing_release_never_counts_as_passed(tmp_path, monkeypatch):
    from lunar_evolution import candidate_execution_runner as runner

    original = runner._bounded_process_bytes

    def omit_release(command, **kwargs):
        kwargs.pop("process_released", None)
        return original(command, **kwargs)

    monkeypatch.setattr(runner, "_bounded_process_bytes", omit_release)
    result = run_acceptance_snapshot_probe(source(tmp_path), probe(2), contract(), tmp_path / "work",
                                           expected=expected(2))
    assert result.reason == "cleanup_unknown"
    assert result.cleanup == "unknown"
    assert not result.passed


def test_snapshot_probe_does_not_replace_global_runner(tmp_path, monkeypatch):
    from lunar_evolution import candidate_execution_runner as runner

    original = runner._bounded_process_bytes
    calls = []

    def observe(command, **kwargs):
        assert runner._bounded_process_bytes is observe
        calls.append(1)
        return original(command, **kwargs)

    monkeypatch.setattr(runner, "_bounded_process_bytes", observe)
    result = run_acceptance_snapshot_probe(source(tmp_path), probe(2), contract(), tmp_path / "work",
                                           expected=expected(2))
    assert result.passed and calls == [1]
    assert runner._bounded_process_bytes is observe


def detached_probe(tmp_path, monkeypatch, *, observations=((17, 17),), releases=((17, 17),),
                   exits=(0,), results=(("succeeded", 0, None),),
                   sources=(b"detached-harness-fixture",), error=False):
    """Supply detached callbacks without reading a harness or starting a process."""
    from lunar_evolution import evaluator_bundle as bundle

    def snapshot(*_args, **kwargs):
        for source_bytes in sources:
            kwargs["evaluator_source_observed"](source_bytes)
        for identity in observations:
            kwargs["process_observer"](*identity)
        for identity in releases:
            kwargs["process_released"](*identity)
        for code in exits:
            kwargs["process_exit_observed"](code)
        for result in results:
            kwargs["process_result_observed"](*result)
        if error:
            raise bundle.EvaluatorBundleError("fixture error")
        return EvaluationReport("1", "compiled-bundle", 1, 2, {}, (), quality=2)

    monkeypatch.setattr(bundle, "_snapshot_probe", snapshot)
    harness = tmp_path / "not-created.py"
    workspace = tmp_path / "not-created"
    evidence = run_acceptance_snapshot_probe(harness, probe(2), contract(), workspace,
                                            expected=expected(2))
    assert not harness.exists() and not workspace.exists()
    return evidence


def test_detached_unique_consistent_observers_are_accepted(tmp_path, monkeypatch):
    result = detached_probe(tmp_path, monkeypatch)
    assert result.passed and result.reason == "passed"
    assert result.process_exit_code == result.native_exit_code == 0
    assert result.observer_identity == result.release_identity == (17, 17)


@pytest.mark.parametrize("sources", [
    (), (b"first", b"replacement"), ("text",), (bytearray(b"mutable"),), (None,),
])
def test_missing_duplicate_or_malformed_source_observation_refuses(tmp_path, monkeypatch, sources):
    result = detached_probe(tmp_path, monkeypatch, sources=sources)
    assert not result.passed and result.reason == "process_failed"
    assert result.cleanup == "unknown"
    first = sources[0] if sources else None
    assert result.harness_sha256 == (hashlib.sha256(first).hexdigest() if type(first) is bytes else None)


@pytest.mark.parametrize("exits", [(), (0, 0), (None,), (False,), (0.0,), ("0",), (1,), (-9,)])
def test_missing_duplicate_malformed_or_conflicting_exit_refuses(tmp_path, monkeypatch, exits):
    result = detached_probe(tmp_path, monkeypatch, exits=exits)
    assert not result.passed and result.reason == "process_failed"
    assert result.cleanup == "unknown"
    assert result.native_exit_code == 0
    assert result.process_exit_code == (exits[0] if len(exits) == 1 and type(exits[0]) is int else None)


@pytest.mark.parametrize("results", [
    (), (("succeeded", 0, None), ("succeeded", 0, None)),
    (("failed", 1, None), ("succeeded", 0, None)),
    (("succeeded", False, None),), (("succeeded", 0.0, None),),
    (("succeeded", "0", None),), (("succeeded", 0, "process_cleanup_failed"),),
    (("failed", 0, None),), ((None, 0, None),),
])
def test_missing_duplicate_or_malformed_runner_result_refuses(tmp_path, monkeypatch, results):
    result = detached_probe(tmp_path, monkeypatch, results=results)
    assert not result.passed and result.reason == "process_failed"
    assert result.cleanup == "unknown"
    first_exit = results[0][1] if results else None
    assert result.native_exit_code == (first_exit if type(first_exit) is int else None)


@pytest.mark.parametrize("field,identities", [
    ("observations", ()), ("releases", ()),
    ("observations", ((17, 17), (17, 17))), ("releases", ((17, 17), (17, 17))),
    ("observations", ((True, 17),)), ("releases", ((17, True),)),
    ("observations", ((17.0, 17),)), ("releases", ((17, "17"),)),
    ("observations", ((0, 17),)), ("releases", ((17, -1),)),
    ("observations", ((18, 18),)), ("releases", ((17, None),)),
])
def test_incomplete_malformed_or_conflicting_process_identity_refuses(
    tmp_path, monkeypatch, field, identities,
):
    result = detached_probe(tmp_path, monkeypatch, **{field: identities})
    assert not result.passed and result.reason == "cleanup_unknown"
    assert result.cleanup == "unknown"
    assert result.process_exit_code == result.native_exit_code == 0


def test_observation_type_gates_do_not_invoke_foreign_equality(tmp_path, monkeypatch):
    class Foreign:
        def __eq__(self, _other):
            pytest.fail("observation equality must not run")

    result = detached_probe(tmp_path, monkeypatch, results=((Foreign(), 0, None),))
    assert result.reason == "process_failed"
    result = detached_probe(tmp_path, monkeypatch, observations=((Foreign(), 17),))
    assert result.reason == "cleanup_unknown"
    assert result.observer_identity is None
    result = detached_probe(tmp_path, monkeypatch, results=((Foreign(), 0, Foreign()),), error=True)
    assert result.reason == "process_failed"
