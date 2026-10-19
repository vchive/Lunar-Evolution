"""The explicit local producer-process lifecycle CLI is bounded and fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_evolution import cli


def test_inspect_is_read_only_and_skips_controller_initialization(tmp_path: Path, monkeypatch, capsys):
    from lunar_evolution import producer_process

    calls: list[tuple[object, str, bool]] = []

    def inspect(workspace, *, journal_id, cleanup):
        calls.append((workspace, journal_id, cleanup))
        return {"status": "completed", "journal_id": journal_id, "production_admission": False}

    monkeypatch.setattr(producer_process, "recover_producer_process", inspect)
    monkeypatch.setattr(cli, "_config", lambda *_a, **_k: pytest.fail("controller initialized"))
    assert cli.main([
        "producer-process", "inspect", str(tmp_path), "journal-1", "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "inspect"
    assert payload["status"] == "completed"
    assert payload["production_admission"] is False
    assert calls == [(tmp_path, "journal-1", False)]


def test_cleanup_requires_a_second_explicit_confirmation_before_io(tmp_path: Path, monkeypatch, capsys):
    from lunar_evolution import producer_process

    monkeypatch.setattr(
        producer_process, "recover_producer_process",
        lambda *_a, **_k: pytest.fail("cleanup reached lifecycle without confirmation"),
    )
    assert cli.main([
        "producer-process", "cleanup", str(tmp_path), "journal-1", "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().err) == {
        "error": "producer_process_cleanup_confirmation_required",
    }


def test_cleanup_reports_unresolved_terminal_as_nonzero_without_admission(tmp_path: Path, monkeypatch, capsys):
    from lunar_evolution import producer_process

    calls: list[bool] = []

    def cleanup(workspace, *, journal_id, cleanup):
        assert workspace == tmp_path and journal_id == "journal-1"
        calls.append(cleanup)
        return {"status": "recovery_required", "reason": "producer_process_terminal_receipt_missing"}

    monkeypatch.setattr(producer_process, "recover_producer_process", cleanup)
    assert cli.main([
        "producer-process", "cleanup", str(tmp_path), "journal-1", "--confirm", "--json",
    ]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "cleanup"
    assert payload["status"] == "recovery_required"
    assert payload["production_admission"] is False
    assert calls == [True]
