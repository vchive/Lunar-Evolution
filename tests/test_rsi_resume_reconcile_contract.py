"""Executable contracts for evidence-bound recovery of an interrupted target."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from lunar_evolution import (
    DeterministicMockSolver,
    RSILearningController,
    RSILearningError,
    RSILedger,
    RSIPracticeEpisode,
)

HEX = "a" * 64


class Gateway:
    def __init__(self):
        self.calls = []

    def rsi_fingerprint_config(self):
        return {"fixture": "resume-reconcile-completed-v1"}

    def run(self, request):
        self.calls.append(request.episode_id)
        return DeterministicMockSolver().run(request)


class FixtureCrash(RuntimeError):
    pass


def interrupted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, retain_result=True):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = Gateway()
    save = ledger.save_episode_result

    def stop_after_worker(request, result):
        if retain_result:
            save(request, result)
        raise FixtureCrash("worker_finished")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", stop_after_worker)
        with pytest.raises(FixtureCrash, match="worker_finished"):
            RSILearningController(gateway, ledger=ledger).run_drs(
                run_id="reconcile", contract_sha256=HEX, evaluator_sha256=HEX,
                environment_sha256=HEX, solver_id="mock", max_practice_rounds=0,
                max_target_attempts=1, budget={"deadline_unix": 4102444800.0},
            )
    return ledger, gateway


def recover(ledger, gateway):
    run = ledger.get_run("reconcile")
    return RSILearningController(gateway, ledger=RSILedger(ledger.database)).resume(
        "reconcile", observed_fingerprints={"run_fingerprint": run.payload["fingerprints"]["run_fingerprint"]},
    )


def test_resume_replays_persisted_completed_result_without_gateway_call(tmp_path, monkeypatch):
    ledger, gateway = interrupted(tmp_path, monkeypatch)
    saved_request, saved_result = ledger.episode_result("reconcile-target-0")

    result = recover(ledger, gateway)

    assert result.status == "completed"
    assert result.target_attempts[0].request == saved_request
    assert result.target_attempts[0].result == saved_result
    assert gateway.calls == ["reconcile-target-0"]
    assert len(ledger.episode_reconciliation("reconcile-target-0")) == 1


def test_resume_unknown_without_result_stays_quarantined(tmp_path, monkeypatch):
    ledger, gateway = interrupted(tmp_path, monkeypatch, retain_result=False)
    head = ledger.get_episode("reconcile-target-0")
    unknown = RSIPracticeEpisode.from_dict(head.payload).transition("unknown", terminal_reason="result_lost")
    stored = ledger.append_episode_record(unknown, expected_record_sha256=head.record_sha256)

    with pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
        recover(ledger, gateway)

    assert ledger.get_episode(unknown.episode_id) == stored
    assert gateway.calls == ["reconcile-target-0"]
    assert ledger.episode_result(unknown.episode_id) is None
    assert ledger.episode_reconciliation(unknown.episode_id) == ()


def test_resume_does_not_create_a_second_episode_or_expand_budget(tmp_path, monkeypatch):
    ledger, gateway = interrupted(tmp_path, monkeypatch)
    checkpoint = ledger.controller_checkpoint("reconcile")
    budget_before = deepcopy(checkpoint[1]["budget_state"])
    episode_ids = ledger.episode_ids_for_run("reconcile")

    recovered = recover(ledger, gateway)
    run_before = ledger.history("reconcile")
    episode_before = ledger.history("reconcile-target-0")
    journal_before = ledger.episode_reconciliation("reconcile-target-0")
    again = recover(ledger, gateway)

    assert recovered == again
    assert gateway.calls == ["reconcile-target-0"]
    assert ledger.episode_ids_for_run("reconcile") == episode_ids
    assert ledger.get_run("reconcile").payload["budget_state"] == budget_before
    assert ledger.history("reconcile") == run_before
    assert ledger.history("reconcile-target-0") == episode_before
    assert ledger.episode_reconciliation("reconcile-target-0") == journal_before
