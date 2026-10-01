"""The usage command must never initialize local state or launch any worker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_evolution import cli
from lunar_evolution.rsi_usage import UsageLedger, UsageReceipt, inspect_usage_ledger


@pytest.fixture
def readonly_cli(monkeypatch, tmp_path: Path):
    def forbidden(*args, **kwargs):
        raise AssertionError("usage diagnostics must not initialize or execute")

    monkeypatch.setattr(cli, "_config", forbidden)
    monkeypatch.setattr(cli, "RSILedger", forbidden)
    monkeypatch.setattr(cli, "Store", forbidden)
    monkeypatch.setattr(cli, "fixture_solver_gateway", forbidden)
    monkeypatch.setattr(cli, "RSILearningController", forbidden)
    monkeypatch.setenv("LUNAR_EVOLUTION_HOME", str(tmp_path / "absent-home"))
    monkeypatch.setenv("LUNAR_EVOLUTION_MAX_RETRIES", "invalid-ignored-config")
    monkeypatch.chdir(tmp_path)


def test_cli_usage_matches_api_and_does_not_initialize_home(tmp_path: Path, capsys, readonly_cli):
    path = tmp_path / "usage.json"
    UsageLedger(path).append(UsageReceipt(
        event_id="solver", run_id="run", episode_id="episode", adapter_stage="solver", wall_time_ms=5,
    ))
    before = path.read_bytes()
    names = sorted(item.name for item in tmp_path.iterdir())
    arguments = ["rsi", "usage", str(path), "--run-id", "run", "--episode-id", "episode",
                 "--adapter-stage", "solver", "--json"]
    assert cli.main(arguments) == 0
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out) == inspect_usage_ledger(
        path, run_id="run", episode_id="episode", adapter_stage="solver",
    )
    assert json.loads(output.out)["aggregate"]["evidence_status"] == "partial"
    assert cli.main(arguments) == 0
    assert capsys.readouterr().out == output.out
    assert path.read_bytes() == before
    assert sorted(item.name for item in tmp_path.iterdir()) == names
    assert not (tmp_path / "absent-home").exists()


def test_cli_no_matching_receipts_is_diagnostic_success_not_complete_accounting(tmp_path: Path, capsys, readonly_cli):
    path = tmp_path / "usage.json"
    UsageLedger(path).append(UsageReceipt(event_id="e", run_id="run", adapter_stage="solver"))
    assert cli.main(["rsi", "usage", str(path), "--run-id", "other", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["aggregate"]["evidence_status"] == "no_receipts"
    assert report["aggregate"]["usage_complete"] is False
    assert set(report["aggregate"]["totals"].values()) == {None}


@pytest.mark.parametrize("kind", ["missing", "bad", "symlink", "directory", "invalid_filter"])
def test_cli_usage_errors_are_readonly_and_report_fixed_error_codes(tmp_path: Path, capsys, readonly_cli, kind: str):
    path = tmp_path / "input"
    arguments = ["rsi", "usage", str(path), "--json"]
    if kind == "bad":
        path.write_text("not json")
    elif kind == "symlink":
        target = tmp_path / "target.json"
        UsageLedger(target).append(UsageReceipt(event_id="e", run_id="run", adapter_stage="solver"))
        path.symlink_to(target)
    elif kind == "directory":
        path.mkdir()
    elif kind == "invalid_filter":
        arguments.extend(["--run-id", ""])
    names = sorted(item.name for item in tmp_path.iterdir())
    assert cli.main(arguments) == 2
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["error"] == (
        "rsi_usage_run_id_invalid" if kind == "invalid_filter" else "rsi_usage_ledger_corrupt"
    )
    assert sorted(item.name for item in tmp_path.iterdir()) == names
    assert not (tmp_path / "absent-home").exists()


def test_cli_human_output_labels_estimates_and_incomplete_data(tmp_path: Path, capsys, readonly_cli):
    path = tmp_path / "usage.json"
    UsageLedger(path).append(UsageReceipt(event_id="e", run_id="run", adapter_stage="solver"))
    assert cli.main(["rsi", "usage", str(path)]) == 0
    output = capsys.readouterr()
    assert not output.err
    assert "cost_basis: estimate" in output.out
    assert "partial" in output.out
    assert "unknown_receipt_count" in output.out
