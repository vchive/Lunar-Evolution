from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_python_producer_adapter import _supported_chain

from lunar_evolution.shinka_handoff import (
    SHINKA_BINDING_MISMATCH,
    ShinkaHandoffError,
    export_shinka_result,
)


def _shinka_run(root: Path, code: str = "answer = 1\n") -> None:
    root.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(root / "programs.sqlite")
    database.execute(
        """CREATE TABLE programs (
            id TEXT, code TEXT, language TEXT, parent_id TEXT,
            generation INTEGER, combined_score REAL, correct BOOLEAN
        )"""
    )
    database.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("program", code, "python", None, 0, 1.0, 1),
    )
    database.commit()
    database.close()
    generation = root / "gen_0"
    generation.mkdir()
    (generation / "main.py").write_text(code, encoding="utf-8")


def test_shinka_binding_normalizes_omitted_run_id(tmp_path: Path) -> None:
    binding, _terminal, _observation, _result = _supported_chain(
        tmp_path / "binding", producer="shinka",
    )
    run = tmp_path / "run"
    _shinka_run(run)

    envelope = export_shinka_result(
        run,
        tmp_path / "export",
        contract_sha256=binding.contract_sha256,
        producer_fingerprint=binding.producer_fingerprint,
        binding=binding,
    )

    assert envelope.producer_run_id == binding.run_id


def test_shinka_binding_rejects_explicit_run_id_drift_before_export(tmp_path: Path) -> None:
    binding, _terminal, _observation, _result = _supported_chain(
        tmp_path / "binding", producer="shinka",
    )
    run = tmp_path / "run"
    _shinka_run(run)
    export = tmp_path / "export"

    with pytest.raises(ShinkaHandoffError) as caught:
        export_shinka_result(
            run,
            export,
            contract_sha256=binding.contract_sha256,
            producer_fingerprint=binding.producer_fingerprint,
            producer_run_id="foreign-run",
            binding=binding,
        )

    assert caught.value.code == SHINKA_BINDING_MISMATCH
    assert not export.exists()
