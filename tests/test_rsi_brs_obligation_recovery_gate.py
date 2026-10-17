"""A retained BRS owner obligation fences every default recovery/drive path."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution import (
    BRSReconcileEvidence,
    BRSReconcileObligation,
    DeterministicCurriculum,
    RSILearningController,
    RSILearningError,
    RSILedger,
    SolverRequest,
    SolverResult,
    fixture_solver_gateway,
)
from lunar_evolution.rsi_brs_reconcile import FIELD

HEX = "a" * 64
RUN_ID = "brs-recovery-fence"
EPISODE_ID = RUN_ID + "-practice-0-0"


class CountingGateway:
    def __init__(self) -> None:
        self.calls = 0

    def rsi_fingerprint_config(self):
        return {"fixture": "brs-recovery-fence-v1"}

    def run(self, request: SolverRequest) -> SolverResult:
        self.calls += 1
        return fixture_solver_gateway("mock").run(request)


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, terminal: bool = False):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = CountingGateway()
    controller = RSILearningController(gateway, ledger=ledger)
    target = controller._target_episode(
        RUN_ID, RUN_ID + "-target", {
            "contract_sha256": HEX, "evaluator_sha256": HEX,
            "environment_sha256": HEX, "solver_id": "mock",
        }, 0,
    )
    practice = DeterministicCurriculum().choose(
        target=target, diagnosis="fixture gap", wave=0, ordinal=0,
    )

    def stop_before_finish(*_args, **_kwargs):
        raise RuntimeError("fixture_before_finish")

    with monkeypatch.context() as patch:
        if not terminal:
            patch.setattr(controller, "_finish_flow", stop_before_finish)
        try:
            controller.run_brs(
                run_id=RUN_ID, contract_sha256=HEX, evaluator_sha256=HEX,
                environment_sha256=HEX, solver_id="mock", practices=[practice],
            )
        except RuntimeError as exc:
            assert str(exc) == "fixture_before_finish"
    assert gateway.calls == 1
    return ledger, controller, gateway


def _retain(ledger: RSILedger, *, phase: str = "selected") -> BRSReconcileObligation:
    checkpoint = ledger.controller_checkpoint(RUN_ID)
    episode = ledger.get_episode(EPISODE_ID)
    assert checkpoint is not None and episode is not None
    obligation = BRSReconcileObligation(
        run_id=RUN_ID, episode_id=EPISODE_ID, phase=phase, handoff_sha256=HEX,
        request_sha256=episode.request_sha256, native_plan_sha256=HEX,
        controller_checkpoint_sha256=checkpoint[0],
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
def test_default_resume_does_not_finish_or_retry_unconsumed_obligation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str,
) -> None:
    ledger, controller, gateway = _run(tmp_path, monkeypatch)
    _retain(ledger, phase=phase)
    before = ledger.controller_checkpoint_history(RUN_ID), ledger.history(RUN_ID)

    with pytest.raises(RSILearningError, match="^rsi_brs_reconcile_required$"):
        controller.resume(RUN_ID)

    assert (ledger.controller_checkpoint_history(RUN_ID), ledger.history(RUN_ID)) == before
    assert gateway.calls == 1
    assert ledger.get_run(RUN_ID).state == "running"


def test_default_resume_keeps_terminal_run_fenced_without_claiming_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, controller, gateway = _run(tmp_path, monkeypatch, terminal=True)
    _retain(ledger)
    before = ledger.controller_checkpoint_history(RUN_ID), ledger.history(RUN_ID)

    with pytest.raises(RSILearningError, match="^rsi_brs_reconcile_required$"):
        controller.resume(RUN_ID)

    assert (ledger.controller_checkpoint_history(RUN_ID), ledger.history(RUN_ID)) == before
    assert gateway.calls == 1
    assert ledger.get_run(RUN_ID).state == "completed"


@pytest.mark.parametrize("driver", ["_drive", "_drive_brs", "_finish_flow"])
def test_direct_drive_reads_durable_fence_even_when_local_state_omits_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver: str,
) -> None:
    ledger, controller, gateway = _run(tmp_path, monkeypatch)
    stale_state = ledger.controller_checkpoint(RUN_ID)[1]
    _retain(ledger)
    before = ledger.controller_checkpoint_history(RUN_ID), ledger.history(RUN_ID)
    record = ledger.get_run(RUN_ID)
    with ledger.controller_lock(RUN_ID), pytest.raises(
        RSILearningError, match="^rsi_brs_reconcile_required$",
    ):
        if driver == "_finish_flow":
            controller._finish_flow(record, stale_state, "completed")
        else:
            getattr(controller, driver)(record, stale_state)

    assert (ledger.controller_checkpoint_history(RUN_ID), ledger.history(RUN_ID)) == before
    assert gateway.calls == 1
    assert FIELD not in stale_state


def test_terminal_replay_ignores_only_consumed_historical_obligations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, controller, gateway = _run(tmp_path, monkeypatch, terminal=True)
    obligation = _retain(ledger)
    evidence = BRSReconcileEvidence(
        obligation_sha256=obligation.digest(), handoff_sha256=obligation.handoff_sha256,
        request_sha256=obligation.request_sha256, native_plan_sha256=obligation.native_plan_sha256,
        controller_checkpoint_sha256=obligation.controller_checkpoint_sha256,
        episode_record_sha256=obligation.episode_record_sha256,
        process_state="exited", process_evidence_sha256=HEX, native_evidence_sha256=HEX,
        mailbox_evidence_sha256=HEX, result_evidence_sha256=HEX, mailbox_state="closed",
        transaction_state="terminal", terminal_status="completed",
        controller_observed_terminal=True, cleanup_confirmed=True,
    )
    assert controller.resume_brs_reconcile(RUN_ID, {EPISODE_ID: evidence})[EPISODE_ID].consumed
    before = ledger.controller_checkpoint_history(RUN_ID), ledger.history(RUN_ID)

    assert controller.resume(RUN_ID).status == "completed"

    assert (ledger.controller_checkpoint_history(RUN_ID), ledger.history(RUN_ID)) == before
    assert gateway.calls == 1
    assert any(state.get(FIELD) for _head, state in before[0])


def test_malformed_obligation_cannot_bypass_default_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, controller, gateway = _run(tmp_path, monkeypatch)
    checkpoint = ledger.controller_checkpoint(RUN_ID)
    state = checkpoint[1]
    state[FIELD] = {EPISODE_ID: {"invalid": True}}
    with ledger.controller_lock(RUN_ID):
        ledger.write_controller_checkpoint(RUN_ID, state, expected_sha256=checkpoint[0])
    before = ledger.controller_checkpoint_history(RUN_ID), ledger.history(RUN_ID)

    with pytest.raises(RSILearningError, match="^rsi_brs_reconcile_obligation_invalid$"):
        controller.resume(RUN_ID)

    assert (ledger.controller_checkpoint_history(RUN_ID), ledger.history(RUN_ID)) == before
    assert gateway.calls == 1


def test_supplied_checkpoint_obligation_is_a_fence_without_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, controller, _gateway = _run(tmp_path, monkeypatch)
    obligation = _retain(ledger)
    state = ledger.controller_checkpoint(RUN_ID)[1]
    controller.ledger = None
    state[FIELD][EPISODE_ID] = replace(obligation, phase="worker_running").to_dict()

    with pytest.raises(RSILearningError, match="^rsi_brs_reconcile_required$"):
        controller._drive(None, state)
