from __future__ import annotations

import json
from pathlib import Path

from lunar_evolution.cli import main
from lunar_evolution.rsi_usage import UsageLedger


def _contract(tmp_path: Path) -> Path:
    path = tmp_path / "contract.json"
    path.write_text('{"problem":"fixture"}', encoding="utf-8")
    return path


def test_run_accepts_unified_budget_and_usage_sidecar(tmp_path: Path, capsys) -> None:
    contract = _contract(tmp_path)
    home = tmp_path / "home"
    usage = tmp_path / "usage.json"
    assert main([
        "rsi", "run", str(contract), "--run-id", "budgeted", "--max-target-attempts", "1",
        "--max-unknown-retries", "2", "--max-evaluator-invocations", "4",
        "--usage-ledger", str(usage), "--json", "--home", str(home),
    ]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "budget_exhausted"
    assert payload["usage_ledger"] == str(usage)
    assert len(UsageLedger(usage).records()) == 2

    assert main(["rsi", "inspect", "budgeted", "--json", "--home", str(home)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["budget"]["planned"]["max_target_attempts"] == 1
    assert inspected["budget"]["consumed"]["target_attempts"] == 1
    assert inspected["reconcile"] == {
        "required": False, "run_state": "budget_exhausted", "unknown_episode_ids": [],
    }


def test_resume_budget_is_an_assertion_and_reuses_usage_events(tmp_path: Path, capsys) -> None:
    contract = _contract(tmp_path)
    home = tmp_path / "home"
    usage = tmp_path / "usage.json"
    args = [
        "rsi", "run", str(contract), "--run-id", "resume-budget", "--usage-ledger", str(usage),
        "--json", "--home", str(home),
    ]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    before = UsageLedger(usage).state()

    assert main([
        "rsi", "resume", "resume-budget", "--max-target-attempts", "3", "--json",
        "--home", str(home),
    ]) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "rsi_resume_budget_drift"}

    assert main([
        "rsi", "resume", "resume-budget", "--max-target-attempts", "4",
        "--usage-ledger", str(usage), "--json", "--home", str(home),
    ]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["status"] == first["status"] == "completed"
    assert UsageLedger(usage).state() == before


def test_brs_omitted_limits_follow_practice_count(tmp_path: Path, capsys) -> None:
    contract = _contract(tmp_path)
    home = tmp_path / "home"
    assert main([
        "rsi", "run", str(contract), "--run-id", "brs-budget", "--mode", "brs",
        "--practice-count", "2", "--json", "--home", str(home),
    ]) == 0
    capsys.readouterr()
    assert main(["rsi", "inspect", "brs-budget", "--json", "--home", str(home)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["budget"]["planned"]["max_practice_rounds"] == 2
    assert inspected["budget"]["planned"]["max_target_attempts"] == 1
