"""The retained Python terminal CLI is detached, read-only, and fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_evolution import cli
from lunar_evolution.python_producer_lifecycle import build_python_producer_terminal

D = "a" * 64


def _terminal(*, status: str = "completed", **changes):
    value = {
        "binding_sha256": D,
        "run_id": "run-1",
        "journal_id": "journal-1",
        "launch_id": "launch-1",
        "process_registration_sha256": D if status != "unknown" else None,
        "owner_identity_sha256": D if status != "unknown" else None,
        "executable_sha256": D if status != "unknown" else None,
        "executable_size": 10 if status != "unknown" else None,
        "executable_device": 1 if status != "unknown" else None,
        "executable_inode": 2 if status != "unknown" else None,
        "started_unix": 10.0,
        "released_unix": 11.0,
        "exited_unix": 12.0 if status != "unknown" else None,
        "deadline_unix": 100.0,
        "status": status,
        "exit_code": 0 if status == "completed" else None,
        "signal": None,
        "cleanup_status": "cleaned" if status != "unknown" else "missing",
        "request_journal_sha256": D if status != "unknown" else None,
        "request_count": 1,
        "stdout_sha256": D,
        "stderr_sha256": D,
        "publication_eligible": False,
    }
    value.update(changes)
    return build_python_producer_terminal(**value)


def _write(path: Path, terminal) -> None:
    path.write_bytes(terminal.to_json())


def test_terminal_inspect_validates_retained_completed_wire_without_initializing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    path = tmp_path / "terminal.json"
    _write(path, _terminal())
    monkeypatch.setattr(cli, "_config", lambda *_a, **_k: pytest.fail("state initialized"))

    assert cli.main([
        "rsi", "producer-terminal", str(path), "--binding-sha256", D,
        "--deadline-unix", "100", "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "completed",
        "reason": "retained_terminal_valid",
        "terminal_sha256": _terminal().terminal_sha256,
        "binding_sha256": D,
        "run_id": "run-1",
        "journal_id": "journal-1",
        "launch_id": "launch-1",
        "cleanup_status": "cleaned",
        "request_count": 1,
        "reconcile_required": False,
        "read_only": True,
        "evidence_scope": "retained_python_terminal",
        "production_admission": False,
        "online_publication": False,
    }


def test_unknown_terminal_is_reported_as_reconcile_required_without_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    path = tmp_path / "terminal.json"
    _write(path, _terminal(status="unknown"))
    monkeypatch.setattr(cli, "_config", lambda *_a, **_k: pytest.fail("state initialized"))

    assert cli.main([
        "rsi", "producer-terminal", str(path), "--binding-sha256", D, "--json",
    ]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unknown"
    assert payload["reason"] == "reconcile_required"
    assert payload["reconcile_required"] is True
    assert payload["production_admission"] is False


def test_terminal_binding_drift_refuses_before_state_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    path = tmp_path / "terminal.json"
    _write(path, _terminal())
    monkeypatch.setattr(cli, "_config", lambda *_a, **_k: pytest.fail("state initialized"))

    assert cli.main([
        "rsi", "producer-terminal", str(path), "--binding-sha256", "b" * 64, "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().err) == {
        "error": "python_producer_lifecycle_binding_drift",
    }


def test_terminal_cli_rejects_noncanonical_json_without_process_or_evaluator(
    tmp_path: Path, capsys,
) -> None:
    path = tmp_path / "terminal.json"
    path.write_text(json.dumps(_terminal().to_dict(), indent=2), encoding="utf-8")

    assert cli.main([
        "rsi", "producer-terminal", str(path), "--binding-sha256", D, "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().err) == {
        "error": "python_producer_lifecycle_noncanonical_json",
    }
