from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_python_producer_adapter import _supported_chain

from lunar_evolution.algorithm import AlgorithmProblemContract, EvaluationReport
from lunar_evolution.openevolve_handoff import (
    RESULT_BINDING_MISMATCH,
    OpenEvolveHandoffError,
    admit_openevolve_result,
)
from lunar_evolution.producer_handoff import ProducerResultEnvelope
from lunar_evolution.python_producer_adapter import (
    PythonProducerAdapterError,
    verify_python_producer_result_binding,
)
from lunar_evolution.shinka_handoff import (
    SHINKA_BINDING_MISMATCH,
    ShinkaHandoffError,
    export_shinka_result,
)


def _shinka_run(root: Path, code: str = "answer = 1\n") -> None:
    database = sqlite3.connect(root / "programs.sqlite")
    database.execute(
        """CREATE TABLE programs (
            id TEXT, code TEXT, language TEXT, parent_id TEXT,
            generation INTEGER, combined_score REAL, correct BOOLEAN
        )"""
    )
    database.execute("INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
                     ("program", code, "python", None, 0, 1.0, 1))
    database.commit()
    database.close()
    generation = root / "gen_0"
    generation.mkdir()
    (generation / "main.py").write_text(code, encoding="utf-8")


def test_common_binding_result_verifier_reparses_and_rejects_drift(tmp_path: Path) -> None:
    binding, _terminal, _observation, result = _supported_chain(tmp_path, producer="shinka")
    assert verify_python_producer_result_binding(binding, result) == result

    drifted = ProducerResultEnvelope.from_dict({
        **result.to_dict(),
        "producer_fingerprint": "f" * 64,
    })
    with pytest.raises(PythonProducerAdapterError, match="producer_fingerprint_drift"):
        verify_python_producer_result_binding(binding, drifted)


def test_shinka_export_can_explicitly_bind_common_python_result(tmp_path: Path) -> None:
    binding, _terminal, _observation, _result = _supported_chain(tmp_path, producer="shinka")
    run = tmp_path / "shinka"
    run.mkdir()
    _shinka_run(run)
    envelope = export_shinka_result(
        run,
        tmp_path / "export",
        contract_sha256=binding.contract_sha256,
        producer_fingerprint=binding.producer_fingerprint,
        producer_run_id=binding.run_id,
        binding=binding,
    )
    assert envelope.producer_id == "shinka"
    assert envelope.producer_run_id == binding.run_id


def test_shinka_export_binding_drift_is_fixed_and_does_not_publish(tmp_path: Path) -> None:
    binding, _terminal, _observation, _result = _supported_chain(tmp_path, producer="shinka")
    run = tmp_path / "shinka"
    run.mkdir()
    _shinka_run(run)
    export = tmp_path / "export"
    with pytest.raises(ShinkaHandoffError) as caught:
        export_shinka_result(
            run,
            export,
            contract_sha256=binding.contract_sha256,
            producer_fingerprint="f" * 64,
            producer_run_id=binding.run_id,
            binding=binding,
        )
    assert caught.value.code == SHINKA_BINDING_MISMATCH
    assert not export.exists()


def test_openevolve_wrapper_binding_drift_is_rejected_before_evaluation(tmp_path: Path) -> None:
    binding, _terminal, _observation, _result = _supported_chain(tmp_path, producer="openevolve")
    root = tmp_path / "openevolve"
    root.mkdir()
    (root / "candidate.py").write_text("answer = 1\n", encoding="utf-8")
    (root / "result.json").write_text('{"candidate_path":"candidate.py"}', encoding="utf-8")
    contract = AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "binding-drift", "problem_type": "routing",
        "statement": "fixture", "inputs": [{"path": "input.txt", "format": "text", "fields": {"value": "value"}}], "decision_variables": ["x"],
        "objective": {"name": "quality", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [], "success_criteria": ["x"],
        "deliverables": ["x"], "evolution": {"strategy": "openevolve", "max_rounds": 1,
        "stagnation_rounds": 1},
    })
    evaluated = False

    def evaluator(_path: Path, _contract: AlgorithmProblemContract) -> EvaluationReport:
        nonlocal evaluated
        evaluated = True
        raise AssertionError("binding gate must precede evaluation")

    with pytest.raises(OpenEvolveHandoffError) as caught:
        admit_openevolve_result(
            root, contract, evaluator,
            evaluator_fingerprint=binding.evaluator_fingerprint,
            producer_fingerprint=binding.producer_fingerprint,
            producer_run_id=binding.run_id,
            binding=binding,
        )
    assert caught.value.code == RESULT_BINDING_MISMATCH
    assert not evaluated
