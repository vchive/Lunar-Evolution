import json
import sqlite3
from pathlib import Path

import pytest

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
        "evaluator_invocations": 0,
        "verifier_invocations": 3,
        "transfer_invocations": 0,
    }
    assert payload["memory_policy"] == "verifier_snapshot"
    assert payload["stage_budget_accounting"] == {
        "evaluator": "unavailable",
        "verifier": "durable",
        "transfer": "unavailable",
    }
    assert payload["governance"] == {"available": False, "records": 0, "memories": 0, "heads": []}
    assert payload["pending_verifier_intents"] == []
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
    with sqlite3.connect(home / "rsi.sqlite3") as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='rsi_memory_governance'"
        ).fetchone() is None


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


def test_rsi_cli_candidate_only_policy_survives_restart_and_stays_inactive(tmp_path, capsys, monkeypatch):
    from lunar_evolution.rsi_adapters import ProviderFreeSolverGateway
    from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT_SHA256

    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    home = tmp_path / "home"
    args = ["rsi", "run", str(contract), "--run-id", "candidates", "--home", str(home),
            "--memory-policy", "candidate-only", "--json"]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["memory_policy"] == "candidate_only"
    assert first["memory_snapshot_sha256"] == EMPTY_MEMORY_SNAPSHOT_SHA256
    assert first["governance"]["available"]
    assert first["governance"]["records"] == 3
    assert first["governance"]["memories"] == 1
    assert first["governance"]["heads"][0]["state"] == "candidate"

    def unexpected(*_args):
        raise AssertionError("completed candidate-only run must not launch a worker")

    monkeypatch.setattr(ProviderFreeSolverGateway, "run", unexpected)
    assert main(["rsi", "resume", "candidates", "--home", str(home), "--json"]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["memory_policy"] == first["memory_policy"]
    assert resumed["governance"] == first["governance"]
    assert resumed["memory_snapshot_sha256"] == EMPTY_MEMORY_SNAPSHOT_SHA256
    assert main(["rsi", "inspect", "candidates", "--home", str(home), "--json"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["governance"] == first["governance"]
    assert inspected["memory_policy"] == "candidate_only"


def test_rsi_cli_governance_summary_is_scoped_to_run(tmp_path, capsys):
    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    home = tmp_path / "home"
    for run_id in ("one", "two"):
        assert main(["rsi", "run", str(contract), "--run-id", run_id, "--home", str(home),
                     "--memory-policy", "candidate-only", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["governance"]["memories"] == 1
        assert payload["governance"]["heads"][0]["memory_id"] == f"memory-{run_id}-practice-0-0"


def test_rsi_cli_governance_missing_journal_fails_without_recreating_it(tmp_path, capsys):
    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    home = tmp_path / "home"
    assert main(["rsi", "run", str(contract), "--run-id", "missing", "--home", str(home),
                 "--memory-policy", "candidate-only", "--json"]) == 0
    capsys.readouterr()
    with sqlite3.connect(home / "rsi.sqlite3") as connection:
        connection.execute("DROP TABLE rsi_memory_governance")
    for command in ("inspect", "resume"):
        assert main(["rsi", command, "missing", "--home", str(home), "--json"]) == 2
        capsys.readouterr()
    with sqlite3.connect(home / "rsi.sqlite3") as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='rsi_memory_governance'"
        ).fetchone() is None


def test_rsi_cli_candidate_policy_cannot_change_for_existing_run(tmp_path, capsys):
    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    home = tmp_path / "home"
    base = ["rsi", "run", str(contract), "--run-id", "pinned", "--home", str(home), "--json"]
    assert main(base + ["--memory-policy", "candidate-only"]) == 0
    capsys.readouterr()
    ledger = RSILedger(home / "rsi.sqlite3")
    before = ledger.controller_checkpoint("pinned")
    assert main(base) == 2
    assert "rsi_resume_memory_policy_drift" in capsys.readouterr().err
    assert ledger.controller_checkpoint("pinned") == before


@pytest.fixture
def pending_cli_verifier(tmp_path, capsys, monkeypatch):
    from lunar_evolution.rsi_gateway import LocalExactVerifier

    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    home = tmp_path / "home"
    original = LocalExactVerifier.verify
    retained = []

    def interrupt_after_decision(verifier, *args):
        retained.append(original(verifier, *args))
        raise RuntimeError("interrupted after verifier decision")

    with monkeypatch.context() as patch:
        patch.setattr(LocalExactVerifier, "verify", interrupt_after_decision)
        with pytest.raises(RuntimeError, match="interrupted after verifier decision"):
            main(["rsi", "run", str(contract), "--run-id", "verify-pending", "--mode", "brs",
                  "--practice-count", "1", "--home", str(home), "--json"])
    capsys.readouterr()
    episode_id = "verify-pending-practice-0-0"
    assert main(["rsi", "inspect", episode_id, "--home", str(home), "--json"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    intent = inspected["pending_verifier_intents"][0]
    assert intent["episode_id"] == episode_id
    assert intent["intent"]["decision"] is None
    assert inspected["budget"]["consumed"]["verifier_invocations"] == 1
    decision_file = tmp_path / "decision.json"
    decision_file.write_text(json.dumps(retained[0].to_dict()))
    return {
        "home": home,
        "episode_id": episode_id,
        "decision_file": decision_file,
        "decision": retained[0].to_dict(),
        "record_sha256": inspected["head"]["record_sha256"],
        "intent_sha256": intent["intent_sha256"],
    }


def _verifier_reconcile_args(pending):
    return [
        "rsi", "reconcile", pending["episode_id"], "--verifier-decision", str(pending["decision_file"]),
        "--expected-record-sha256", pending["record_sha256"],
        "--expected-intent-sha256", pending["intent_sha256"],
        "--home", str(pending["home"]), "--json",
    ]


def test_rsi_cli_retained_verifier_reconciliation_never_replays(pending_cli_verifier, capsys, monkeypatch):
    from lunar_evolution.rsi_adapters import ProviderFreeSolverGateway
    from lunar_evolution.rsi_gateway import LocalExactVerifier

    pending = pending_cli_verifier

    def unexpected(*_args):
        raise AssertionError("retained verifier evidence must not relaunch a worker or verifier")

    monkeypatch.setattr(ProviderFreeSolverGateway, "run", unexpected)
    monkeypatch.setattr(LocalExactVerifier, "verify", unexpected)
    assert main(["rsi", "resume", "verify-pending", "--home", str(pending["home"]), "--json"]) == 1
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["status"] == "unknown"
    assert resumed["pending_verifier_intents"][0]["intent_sha256"] == pending["intent_sha256"]
    assert main(_verifier_reconcile_args(pending)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed"
    assert result["pending_verifier_intents"] == []
    assert result["budget"]["consumed"]["verifier_invocations"] == 1
    assert main(["rsi", "resume", "verify-pending", "--home", str(pending["home"]), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["pending_verifier_intents"] == []


@pytest.mark.parametrize("extra", [
    ["--result", "other.json"], ["--worker-state", "failed"], ["--launched"],
])
def test_rsi_cli_verifier_reconciliation_rejects_other_modes(pending_cli_verifier, capsys, extra):
    pending = pending_cli_verifier
    assert main(_verifier_reconcile_args(pending) + extra) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "rsi_reconcile_verifier_decision_conflict"


def test_rsi_cli_verifier_reconciliation_requires_intent_digest(pending_cli_verifier, capsys):
    args = _verifier_reconcile_args(pending_cli_verifier)
    index = args.index("--expected-intent-sha256")
    del args[index:index + 2]
    assert main(args) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "rsi_reconcile_expected_intent_sha256_required"


def test_rsi_cli_verifier_reconciliation_rejects_wrong_intent(pending_cli_verifier, capsys):
    pending = pending_cli_verifier
    args = _verifier_reconcile_args(pending)
    args[args.index("--expected-intent-sha256") + 1] = "f" * 64
    ledger = RSILedger(pending["home"] / "rsi.sqlite3")
    before = ledger.controller_checkpoint("verify-pending")
    assert main(args) == 2
    assert "rsi_verifier_reconcile_intent_conflict" in capsys.readouterr().err
    assert ledger.controller_checkpoint("verify-pending") == before


def test_rsi_cli_reconciliation_rejects_intent_without_decision(pending_cli_verifier, capsys):
    args = _verifier_reconcile_args(pending_cli_verifier)
    index = args.index("--verifier-decision")
    del args[index:index + 2]
    assert main(args + ["--worker-state", "failed"]) == 2
    assert "rsi_reconcile_expected_intent_without_decision" in capsys.readouterr().err


@pytest.mark.parametrize("corruption", ["extra-field", "missing-field", "check-extra", "duplicate", "wrong-pin"])
def test_rsi_cli_verifier_decision_is_strict(pending_cli_verifier, capsys, corruption):
    pending = pending_cli_verifier
    decision = pending["decision"]
    if corruption == "extra-field":
        decision["extra"] = "unexpected"
    elif corruption == "missing-field":
        del decision["diagnosis"]
    elif corruption == "check-extra":
        decision["checks"][0]["extra"] = "unexpected"
    elif corruption == "wrong-pin":
        decision["contract_sha256"] = "f" * 64
    content = json.dumps(decision)
    if corruption == "duplicate":
        content = content[:-1] + ',"outcome":"pass"}'
    pending["decision_file"].write_text(content)
    ledger = RSILedger(pending["home"] / "rsi.sqlite3")
    before = ledger.controller_checkpoint("verify-pending")
    assert main(_verifier_reconcile_args(pending)) == 2
    capsys.readouterr()
    assert ledger.controller_checkpoint("verify-pending") == before


@pytest.mark.parametrize("kind", ["symlink", "directory", "oversize"])
def test_rsi_cli_verifier_decision_requires_bounded_regular_file(pending_cli_verifier, capsys, kind):
    pending = pending_cli_verifier
    path = pending["decision_file"]
    path.unlink()
    if kind == "symlink":
        target = path.with_name("retained.json")
        target.write_text(json.dumps(pending["decision"]))
        path.symlink_to(target)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b" " * (128 * 1024 + 1))
    assert main(_verifier_reconcile_args(pending)) == 2
    capsys.readouterr()
