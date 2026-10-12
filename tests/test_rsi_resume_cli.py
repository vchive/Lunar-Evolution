from __future__ import annotations

import json
from pathlib import Path

from lunar_evolution.cli import main


def _run_fixture(tmp_path: Path, capsys, *, worker_status: str = "completed") -> tuple[Path, Path, dict[str, object]]:
    contract = tmp_path / "contract.json"
    contract.write_text('{"problem":"fixture"}', encoding="utf-8")
    home = tmp_path / "home"
    assert main([
        "rsi", "run", str(contract), "--run-id", "resume-fixture",
        "--worker-status", worker_status, "--json", "--home", str(home),
    ]) in {0, 1}
    payload = json.loads(capsys.readouterr().out)
    return contract, home, payload


def test_rsi_resume_reopens_terminal_run_without_new_dispatch(tmp_path: Path, capsys) -> None:
    _contract, home, started = _run_fixture(tmp_path, capsys)
    assert started["status"] == "completed"

    assert main([
        "rsi", "resume", "resume-fixture", "--json", "--home", str(home),
    ]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["resumed"] is True
    assert resumed["status"] == "completed"
    assert resumed["target_attempts"] == started["target_attempts"]
    assert resumed["practice_episodes"] == started["practice_episodes"]


def test_rsi_resume_rejects_solver_identity_drift(tmp_path: Path, capsys) -> None:
    _contract, home, _started = _run_fixture(tmp_path, capsys)

    assert main([
        "rsi", "resume", "resume-fixture", "--solver", "openevolve",
        "--json", "--home", str(home),
    ]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error == {"error": "rsi_resume_solver_id_drift"}


def test_rsi_resume_keeps_unknown_episode_quarantined(tmp_path: Path, capsys) -> None:
    _contract, home, started = _run_fixture(tmp_path, capsys, worker_status="unknown")
    assert started["status"] == "unknown"

    # Reconstructing the original fixture identity still cannot settle unknown evidence.
    assert main([
        "rsi", "resume", "resume-fixture", "--worker-status", "unknown",
        "--json", "--home", str(home),
    ]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error == {"error": "rsi_unknown_reconcile_required"}
