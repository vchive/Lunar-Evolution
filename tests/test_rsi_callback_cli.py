"""The local CLI can inspect and settle uncertain callbacks without rerunning them."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from lunar_evolution.cli import main
from lunar_evolution.rsi_callbacks import DurableCallbackJournal
from lunar_evolution.rsi_store import RSILedger


class CallbackPublicationCrash(BaseException):
    pass


def database_snapshot(ledger):
    with ledger._connect() as connection:
        return tuple(connection.iterdump())


def interrupted_cli(tmp_path, monkeypatch, stage="verifier"):
    contract = tmp_path / "contract.json"
    contract.write_text('{"problem_id":"callback-fixture"}', encoding="utf-8")
    home = tmp_path / "home"
    run_id = "cli-callback-run"
    episode_id = f"{run_id}-practice-0-0" if stage == "curriculum" else f"{run_id}-target-0"
    callback_id = f"{stage}:{episode_id}"
    arguments = ["rsi", "run", str(contract), "--run-id", run_id, "--json", "--home", str(home)]
    write_checkpoint = RSILedger.write_controller_checkpoint
    outputs = []

    def crash_publication(self, namespace, state, *, expected_sha256):
        if (state.get("kind") == "durable_callback" and state.get("status") == "completed"
                and state.get("callback_id") == callback_id):
            outputs.append(deepcopy(state["result"]))
            raise CallbackPublicationCrash()
        return write_checkpoint(self, namespace, state, expected_sha256=expected_sha256)

    with monkeypatch.context() as patch:
        patch.setattr(RSILedger, "write_controller_checkpoint", crash_publication)
        with pytest.raises(CallbackPublicationCrash):
            main(arguments)
    assert len(outputs) == 1
    ledger = RSILedger(home / "rsi.sqlite3")
    digest, state = DurableCallbackJournal(ledger).inspect(run_id, callback_id)
    assert state["status"] == "started"
    result_path, evidence_path = tmp_path / "result.json", tmp_path / "evidence.json"
    result_path.write_text(json.dumps(outputs[0]), encoding="utf-8")
    evidence_path.write_text(json.dumps({
        "source": "local-fixture-retained-response",
        "binding_sha256": DurableCallbackJournal.digest(state["binding"]),
        "result_sha256": DurableCallbackJournal.digest(outputs[0]),
        "receipt_sha256": DurableCallbackJournal.digest({"retained-result": outputs[0]}),
    }), encoding="utf-8")
    options = [
        "--reconcile-callback", callback_id, "--expected-checkpoint-sha256", digest,
        "--callback-result", str(result_path), "--callback-evidence", str(evidence_path),
    ]
    return ledger, arguments, options, outputs[0]


@pytest.mark.parametrize("stage", ["verifier", "judge", "curriculum"])
def test_cli_inspect_reconcile_then_resume_real_fixture(tmp_path, monkeypatch, capsys, stage):
    ledger, arguments, options, result = interrupted_cli(tmp_path, monkeypatch, stage)
    run_id, callback_id = "cli-callback-run", options[1]
    before_inspection = database_snapshot(ledger)
    assert main(["rsi", "inspect", run_id, "--callback-id", callback_id,
                 "--home", str(tmp_path / "home"), "--json"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["checkpoint_sha256"] == options[3]
    assert inspected["state"]["status"] == "started"
    assert database_snapshot(ledger) == before_inspection

    episodes = ledger.episode_ids_for_run(run_id)
    histories = {episode: ledger.history(episode) for episode in episodes}
    assert main(arguments + options) == 0
    settled = json.loads(capsys.readouterr().out)
    assert settled["status"] == "reconciled"
    assert settled["result"] == result
    assert ledger.get_run(run_id).state == "running"
    assert ledger.episode_ids_for_run(run_id) == episodes
    assert {episode: ledger.history(episode) for episode in episodes} == histories
    assert DurableCallbackJournal(ledger).inspect(run_id, callback_id)[1]["status"] == "completed"

    after_settlement = database_snapshot(ledger)
    assert main(arguments + options) == 0
    assert json.loads(capsys.readouterr().out) == settled
    assert database_snapshot(ledger) == after_settlement
    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"


@pytest.mark.parametrize("missing", [
    "--run-id", "--reconcile-callback", "--expected-checkpoint-sha256",
    "--callback-result", "--callback-evidence",
])
def test_cli_incomplete_reconciliation_options_do_not_write(tmp_path, monkeypatch, capsys, missing):
    ledger, arguments, options, _ = interrupted_cli(tmp_path, monkeypatch)
    command = arguments + options
    index = command.index(missing)
    del command[index:index + 2]
    original = database_snapshot(ledger)
    assert main(command) == 2
    assert "rsi_callback_reconcile_options_required" in capsys.readouterr().err
    assert database_snapshot(ledger) == original


@pytest.mark.parametrize("filename", ["result.json", "evidence.json"])
@pytest.mark.parametrize("raw", [
    b"{bad", b'{"duplicate":1,"duplicate":2}', b'{"invalid":NaN}',
    b'{"invalid":1e999}', b"[]", b'{"invalid":"\xff"}',
])
def test_cli_strict_json_rejection_does_not_write(tmp_path, monkeypatch, capsys, filename, raw):
    ledger, arguments, options, _ = interrupted_cli(tmp_path, monkeypatch)
    (tmp_path / filename).write_bytes(raw)
    original = database_snapshot(ledger)
    assert main(arguments + options) == 2
    assert "_file_invalid" in capsys.readouterr().err
    assert database_snapshot(ledger) == original


@pytest.mark.parametrize("filename,maximum", [("result.json", 1024 * 1024), ("evidence.json", 128 * 1024)])
def test_cli_oversized_callback_files_do_not_write(tmp_path, monkeypatch, capsys, filename, maximum):
    ledger, arguments, options, _ = interrupted_cli(tmp_path, monkeypatch)
    (tmp_path / filename).write_text('{"large":"' + "x" * maximum + '"}', encoding="utf-8")
    original = database_snapshot(ledger)
    assert main(arguments + options) == 2
    assert "_file_invalid" in capsys.readouterr().err
    assert database_snapshot(ledger) == original


@pytest.mark.parametrize("option,value,field", [
    ("--contract-sha256", "f" * 64, "contract_sha256"),
    ("--evaluator-sha256", "f" * 64, "evaluator_sha256"),
    ("--environment-sha256", "f" * 64, "environment_sha256"),
    ("--solver", "shinka", "solver_id"),
    ("--mode", "brs", "mode"),
])
def test_cli_reconcile_rejects_original_run_pin_drift(tmp_path, monkeypatch, capsys, option, value, field):
    ledger, arguments, options, _ = interrupted_cli(tmp_path, monkeypatch)
    original = database_snapshot(ledger)
    assert main(arguments + options + [option, value]) == 2
    assert f"rsi_resume_{field}_drift" in capsys.readouterr().err
    assert database_snapshot(ledger) == original


def test_cli_reconcile_rejects_changed_contract_bytes(tmp_path, monkeypatch, capsys):
    ledger, arguments, options, _ = interrupted_cli(tmp_path, monkeypatch)
    (tmp_path / "contract.json").write_text('{"changed":true}', encoding="utf-8")
    original = database_snapshot(ledger)
    assert main(arguments + options) == 2
    assert "rsi_resume_contract_sha256_drift" in capsys.readouterr().err
    assert database_snapshot(ledger) == original


def test_cli_reconcile_rejects_component_drift_without_writes(tmp_path, monkeypatch, capsys):
    ledger, arguments, options, _ = interrupted_cli(tmp_path, monkeypatch)
    original = database_snapshot(ledger)
    assert main(arguments + options + ["--worker-status", "failed"]) == 2
    assert "rsi_resume_fingerprint_drift" in capsys.readouterr().err
    assert database_snapshot(ledger) == original


def test_cli_reconcile_unknown_run_does_not_create_one(tmp_path, monkeypatch, capsys):
    ledger, arguments, options, _ = interrupted_cli(tmp_path, monkeypatch)
    arguments[arguments.index("--run-id") + 1] = "unknown-run"
    original = database_snapshot(ledger)
    assert main(arguments + options) == 2
    assert "rsi_callback_run_missing" in capsys.readouterr().err
    assert ledger.get_run("unknown-run") is None
    assert database_snapshot(ledger) == original


def test_cli_unknown_callback_inspection_is_read_only(tmp_path, monkeypatch, capsys):
    ledger, _arguments, _options, _ = interrupted_cli(tmp_path, monkeypatch)
    original = database_snapshot(ledger)
    assert main(["rsi", "inspect", "cli-callback-run", "--callback-id", "judge:not-started",
                 "--home", str(tmp_path / "home"), "--json"]) == 2
    assert "rsi_callback_missing" in capsys.readouterr().err
    assert database_snapshot(ledger) == original


@pytest.mark.parametrize("filename", [".env", ".env.local"])
def test_cli_rejects_env_file_as_callback_input_without_reading(tmp_path, monkeypatch, capsys, filename):
    ledger, arguments, options, _ = interrupted_cli(tmp_path, monkeypatch)
    options[options.index("--callback-result") + 1] = str(tmp_path / filename)
    original = database_snapshot(ledger)
    # The file deliberately does not exist; the rejection precedes any filesystem read.
    assert main(arguments + options) == 2
    assert "rsi_callback_result_file_invalid" in capsys.readouterr().err
    assert database_snapshot(ledger) == original
