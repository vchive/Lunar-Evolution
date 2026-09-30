import json
from pathlib import Path

import pytest

from lunar_evolution.cli import main
from lunar_evolution.rsi_store import RSILedger


@pytest.mark.parametrize("mode", ["drs", "brs"])
def test_rsi_cli_repeated_run_reuses_learning_and_transfer(tmp_path: Path, capsys, mode: str) -> None:
    contract = tmp_path / "contract.json"
    contract.write_text('{"problem_id":"fixture"}', encoding="utf-8")
    home = tmp_path / "home"
    run_id = f"repeat-{mode}"
    arguments = ["rsi", "run", str(contract), "--run-id", run_id, "--mode", mode,
                 "--json", "--home", str(home)]
    assert main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    ledger = RSILedger(home / "rsi.sqlite3")
    run_history = ledger.history(run_id)
    journal = ledger.controller_checkpoint_history(run_id)
    episodes = {key: ledger.history(key) for key in ledger.episode_ids_for_run(run_id)}

    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert ledger.history(run_id) == run_history
    assert ledger.controller_checkpoint_history(run_id) == journal
    assert {key: ledger.history(key) for key in ledger.episode_ids_for_run(run_id)} == episodes


def test_rsi_cli_run_persists_run_and_memory_ledger(tmp_path: Path, capsys) -> None:
    contract = tmp_path / "contract.json"
    contract.write_text('{"problem_id":"fixture"}', encoding="utf-8")
    home = tmp_path / "home"

    assert main([
        "rsi", "run", str(contract), "--run-id", "cli-rsi-drs", "--json", "--home", str(home),
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["memory_snapshot_sha256"]

    ledger = RSILedger(home / "rsi.sqlite3")
    assert [record.state for record in ledger.history("cli-rsi-drs")] == [
        "created", "running", "completed",
    ]
    episode_records = [record for record in ledger.history("cli-rsi-drs-target-0") if record.kind == "episode"]
    assert episode_records
    memory_heads = ledger.history("memory:snapshot-memory-cli-rsi-drs-practice-0-0")
    assert len(memory_heads) == 1

    assert main(["rsi", "inspect", "cli-rsi-drs", "--json", "--home", str(home)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["head"]["payload"]["mode"] == "drs"
    assert inspected["head"]["payload"]["memory_snapshot_sha256"] == payload["memory_snapshot_sha256"]


def test_rsi_cli_unknown_requires_explicit_reconciliation(tmp_path: Path, capsys) -> None:
    contract = tmp_path / "contract.json"
    contract.write_text("{}", encoding="utf-8")
    home = tmp_path / "home"
    assert main([
        "rsi", "run", str(contract), "--run-id", "cli-rsi-unknown", "--worker-status", "unknown",
        "--json", "--home", str(home),
    ]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unknown"
    ledger = RSILedger(home / "rsi.sqlite3")
    episode = ledger.get("cli-rsi-unknown-target-0")
    assert episode is not None and episode.state == "unknown"

    assert main([
        "rsi", "reconcile", episode.logical_id, "--worker-state", "failed",
        "--expected-record-sha256", episode.record_sha256, "--json", "--home", str(home),
    ]) == 0
    reconciled = json.loads(capsys.readouterr().out)
    assert reconciled["state"] == "failed"
