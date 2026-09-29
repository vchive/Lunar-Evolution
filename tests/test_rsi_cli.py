import json
from pathlib import Path

from lunar_evolution.cli import main
from lunar_evolution.rsi_store import RSILedger


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
    assert payload["budget"]["consumed"] == {
        "solver_invocations": 3,
        "practice_episodes": 1,
        "unknown_retries": 0,
    }
    assert "request_count" in payload["usage"]
    assert payload["usage"]["wall_elapsed_ms"] >= 0

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
    assert inspected["budget"] == payload["budget"]
    assert inspected["usage"] == payload["usage"]

    assert main(["rsi", "inspect", "cli-rsi-drs-target-0", "--json", "--home", str(home)]) == 0
    episode = json.loads(capsys.readouterr().out)
    assert episode["budget"] == payload["budget"]
    assert episode["usage"] == payload["usage"]


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


def test_rsi_cli_restart_reuses_completed_run_without_gateway(tmp_path, capsys, monkeypatch):
    from lunar_evolution.rsi_adapters import ProviderFreeSolverGateway

    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    home = tmp_path / "home"
    args = ["rsi", "run", str(contract), "--run-id", "reuse", "--home", str(home), "--json"]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)

    def unexpected(*_args):
        raise AssertionError("resuming a terminal run must not invoke gateway")

    monkeypatch.setattr(ProviderFreeSolverGateway, "run", unexpected)
    assert main(["rsi", "resume", "reuse", "--home", str(home), "--json"]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert {key: resumed[key] for key in first if key != "usage"} == {
        key: first[key] for key in first if key != "usage"
    }
    assert resumed["usage"]["wall_elapsed_ms"] >= first["usage"]["wall_elapsed_ms"]
    assert main(args) == 0
    rerun = json.loads(capsys.readouterr().out)
    assert {key: rerun[key] for key in first if key != "usage"} == {
        key: first[key] for key in first if key != "usage"
    }
    assert rerun["usage"]["wall_elapsed_ms"] >= resumed["usage"]["wall_elapsed_ms"]


def test_rsi_cli_unknown_resume_never_reissues_and_result_continues(tmp_path, capsys, monkeypatch):
    from lunar_evolution.rsi_adapters import ProviderFreeSolverGateway, fixture_solver_gateway
    from lunar_evolution.rsi_gateway import SolverRequest

    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    home = tmp_path / "home"
    assert main(["rsi", "run", str(contract), "--run-id", "uncertain", "--mode", "brs",
                 "--practice-count", "1", "--worker-status", "unknown",
                 "--home", str(home), "--json"]) == 1
    capsys.readouterr()
    ledger = RSILedger(home / "rsi.sqlite3")
    checkpoint = ledger.controller_checkpoint("uncertain")[1]
    episode_id = "uncertain-practice-0-0"
    request = SolverRequest.from_dict(checkpoint["episodes"][episode_id]["request"])
    evidence = fixture_solver_gateway("mock").run(request)
    retained = tmp_path / "result.json"
    retained.write_text(json.dumps(evidence.to_dict()))
    head = ledger.get(episode_id)

    def unexpected(*_args):
        raise AssertionError("unknown launch must not be reissued")

    monkeypatch.setattr(ProviderFreeSolverGateway, "run", unexpected)
    assert main(["rsi", "resume", "uncertain", "--home", str(home), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "unknown"
    assert main(["rsi", "reconcile", episode_id, "--result", str(retained),
                 "--expected-record-sha256", head.record_sha256,
                 "--home", str(home), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed" and result["practice_episodes"] == 1
    assert "budget" in result and "usage" in result
    assert main(["rsi", "resume", "uncertain", "--home", str(home), "--json"]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert {key: resumed[key] for key in result if key != "usage"} == {
        key: result[key] for key in result if key != "usage"
    }
    assert resumed["usage"]["wall_elapsed_ms"] >= result["usage"]["wall_elapsed_ms"]


def test_rsi_cli_resume_is_stable_across_real_processes(tmp_path):
    import os
    import subprocess
    import sys

    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    common = ["--home", str(tmp_path / "home"), "--json"]
    prefix = [sys.executable, "-m", "lunar_evolution"]
    first = subprocess.run(prefix + ["rsi", "run", str(contract), "--run-id", "restart"] + common,
                           env=env, capture_output=True, text=True, timeout=30, check=True)
    second = subprocess.run(prefix + ["rsi", "resume", "restart"] + common,
                            env=env, capture_output=True, text=True, timeout=30, check=True)
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert {key: second_payload[key] for key in first_payload if key != "usage"} == {
        key: first_payload[key] for key in first_payload if key != "usage"
    }
    assert second_payload["usage"]["wall_elapsed_ms"] >= first_payload["usage"]["wall_elapsed_ms"]
