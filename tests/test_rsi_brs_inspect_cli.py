"""CLI inspection projects only the latest unconsumed BRS recovery fence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_evolution import BRSReconcileObligation, RSILedger
from lunar_evolution.cli import main

RUN_ID = "cli-brs-inspect"
HEX = "a" * 64


def _fixture(tmp_path: Path, capsys):
    home = tmp_path / "home"
    contract = tmp_path / "contract.json"
    contract.write_text('{"problem":"local inspect fixture"}', encoding="utf-8")
    assert main([
        "rsi", "run", str(contract), "--mode", "brs", "--practice-count", "1",
        "--run-id", RUN_ID, "--home", str(home), "--json",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
    ledger = RSILedger(home / "rsi.sqlite3")
    return home, ledger


def _inspect(home: Path, ledger: RSILedger, capsys):
    with ledger._connect() as connection:
        before = tuple(connection.iterdump())
    assert main(["rsi", "inspect", RUN_ID, "--home", str(home), "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    with ledger._connect() as connection:
        assert tuple(connection.iterdump()) == before
    return output


def _retain(ledger: RSILedger, phase: str) -> BRSReconcileObligation:
    checkpoint = ledger.controller_checkpoint(RUN_ID)
    episode_id = ledger.episode_ids_for_run(RUN_ID)[0]
    episode = ledger.get_episode(episode_id)
    obligation = BRSReconcileObligation(
        run_id=RUN_ID, episode_id=episode_id, phase=phase,
        handoff_sha256=HEX, request_sha256=episode.request_sha256,
        native_plan_sha256=HEX, controller_checkpoint_sha256=checkpoint[0],
        episode_record_sha256=episode.record_sha256,
        terminal_status="unknown" if phase == "reconcile_required" else None,
        transaction_state="settled" if phase == "settled" else "unknown",
    )
    with ledger.controller_lock(RUN_ID):
        ledger.write_brs_reconcile_obligation(
            RUN_ID, obligation, expected_checkpoint_sha256=checkpoint[0],
        )
    return obligation


@pytest.mark.parametrize("phase", ["selected", "reconcile_required", "settled"])
def test_completed_run_inspection_requires_reconcile_for_every_retained_phase(
    tmp_path: Path, capsys, phase: str,
) -> None:
    home, ledger = _fixture(tmp_path, capsys)
    _retain(ledger, phase)

    inspected = _inspect(home, ledger, capsys)

    assert inspected["head"]["state"] == "completed"
    assert inspected["reconcile"] == {
        "required": True, "run_state": "completed", "unknown_episode_ids": [],
    }


def test_inspection_ignores_consumed_obligations_in_old_checkpoints(tmp_path: Path, capsys) -> None:
    home, ledger = _fixture(tmp_path, capsys)
    obligation = _retain(ledger, "selected")
    assert _inspect(home, ledger, capsys)["reconcile"]["required"] is True
    checkpoint = ledger.controller_checkpoint(RUN_ID)
    # The inspection contract starts at the exact settlement/consume storage boundary;
    # process/native evidence admission is exercised by the separate reconcile tests.
    with ledger.controller_lock(RUN_ID):
        ledger.remove_brs_reconcile_obligation(
            RUN_ID, obligation.episode_id, expected_checkpoint_sha256=checkpoint[0],
            expected_obligation_digest=obligation.digest(),
        )

    assert _inspect(home, ledger, capsys)["reconcile"] == {
        "required": False, "run_state": "completed", "unknown_episode_ids": [],
    }
    assert any(state.get("brs_reconcile_obligations")
               for _head, state in ledger.controller_checkpoint_history(RUN_ID))


def test_legacy_inspection_schema_is_unchanged_without_obligations(tmp_path: Path, capsys) -> None:
    home = tmp_path / "home"
    ledger = RSILedger(home / "rsi.sqlite3")
    created = ledger.create_run(RUN_ID, HEX, {"mode": "brs"})
    running = ledger.transition(RUN_ID, state="running", expected_record_sha256=created.record_sha256)
    ledger.transition(RUN_ID, state="completed", expected_record_sha256=running.record_sha256)
    assert ledger.controller_checkpoint(RUN_ID) is None

    assert _inspect(home, ledger, capsys)["reconcile"] == {
        "required": False, "run_state": "completed", "unknown_episode_ids": [],
    }
