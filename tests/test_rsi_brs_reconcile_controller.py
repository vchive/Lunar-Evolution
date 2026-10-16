"""Provider-free controller wiring for explicit BRS reconcile obligations."""

from __future__ import annotations

from pathlib import Path
from threading import get_ident

import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT,
    BRSReconcileEvidence,
    RSILearningError,
    RSILedger,
    RSIPracticeEpisode,
    SolverRequest,
    consume_brs_selected_reconcile,
    register_brs_selected_obligation,
)
from lunar_evolution.rsi_brs_reconcile import FIELD
from lunar_evolution.rsi_python_brs_handoff import BRSSelectedChildHandoff

HEX = "a" * 64
OTHER = "b" * 64


def _fixture(tmp_path: Path) -> tuple[
    RSILedger, str, str, SolverRequest, str, BRSSelectedChildHandoff, str
]:
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    run_id = "controller-run"
    episode_id = f"{run_id}-practice-0-0"
    request = SolverRequest.build(
        episode_id=episode_id,
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="fixture",
    )
    intents = {episode_id: {"request": request.to_dict()}}
    created = ledger.create_run(run_id, request.digest(), {"mode": "brs", "intents": intents})
    running = ledger.transition(run_id, state="running", expected_record_sha256=created.record_sha256)
    episode = RSIPracticeEpisode(
        episode_id=episode_id,
        run_id=run_id,
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="fixture",
        status="running",
        wave=0,
        ordinal=0,
        request_sha256=request.digest(),
    )
    episode_record = ledger.create_episode_record(episode)
    state = {"run_id": run_id, "intents": intents, FIELD: {}}
    with ledger.controller_lock(run_id):
        checkpoint = ledger.write_controller_checkpoint(run_id, state, expected_sha256=None)
    handoff = BRSSelectedChildHandoff(
        run_id=run_id,
        wave=0,
        ordinal=0,
        episode_id=episode_id,
        request_sha256=request.digest(),
        root_snapshot_sha256=HEX,
        selection_sha256=HEX,
        controller_id="controller",
        ledger_id="ledger",
        workspace_id="workspace",
        sidecar_id="sidecar",
        owner_thread_id=get_ident(),
        head_sha256=HEX,
        state_sha256=HEX,
        source_sha256=HEX,
        policy_sha256=HEX,
        execution_control_sha256=HEX,
        max_workers=1,
        lease_nonce="N" * 32,
    )
    # Keep the local variable useful in failure output and make this fixture's
    # intent explicit: the transition is the only run mutation before capture.
    assert running.state == "running"
    return ledger, run_id, episode_id, request, checkpoint, handoff, episode_record.record_sha256


def _register(
    ledger: RSILedger,
    run_id: str,
    checkpoint: str,
    handoff: BRSSelectedChildHandoff,
    episode_record_sha256: str,
    **kwargs: object,
):
    with ledger.controller_lock(run_id):
        return register_brs_selected_obligation(
            ledger,
            handoff,
            native_plan_sha256=HEX,
            controller_checkpoint_sha256=checkpoint,
            episode_record_sha256=episode_record_sha256,
            **kwargs,
        )


def _evidence(obligation, **changes: object) -> BRSReconcileEvidence:
    values = {
        "obligation_sha256": obligation.digest(),
        "handoff_sha256": obligation.handoff_sha256,
        "request_sha256": obligation.request_sha256,
        "native_plan_sha256": obligation.native_plan_sha256,
        "controller_checkpoint_sha256": obligation.controller_checkpoint_sha256,
        "episode_record_sha256": obligation.episode_record_sha256,
        "process_state": "exited",
        "process_evidence_sha256": HEX,
        "native_evidence_sha256": HEX,
        "mailbox_evidence_sha256": HEX,
        "result_evidence_sha256": HEX,
        "mailbox_state": "closed",
        "transaction_state": "terminal",
        "terminal_status": "completed",
        "controller_observed_terminal": True,
        "cleanup_confirmed": True,
    }
    values.update(changes)
    return BRSReconcileEvidence(**values)


def test_registration_requires_owner_and_binds_exact_heads(tmp_path: Path) -> None:
    ledger, run_id, _episode_id, _request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    with pytest.raises(RSILearningError, match="owner_required"):
        register_brs_selected_obligation(
            ledger, handoff, native_plan_sha256=HEX,
            controller_checkpoint_sha256=checkpoint, episode_record_sha256=episode_sha,
        )
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    assert registration.obligation.handoff_sha256 == handoff.sha256
    assert registration.obligation.controller_checkpoint_sha256 == checkpoint
    assert registration.checkpoint_sha256 != checkpoint

    replay = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    assert replay.obligation == registration.obligation
    assert replay.checkpoint_sha256 == registration.checkpoint_sha256


@pytest.mark.parametrize("field", ["native_plan_sha256", "episode_record_sha256"])
def test_registration_refuses_stale_or_foreign_binding(tmp_path: Path, field: str) -> None:
    ledger, run_id, _episode_id, _request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    value = "0" * 64 if field == "native_plan_sha256" else OTHER
    with pytest.raises(RSILearningError, match="(native_plan|episode|checkpoint|conflict)"), ledger.controller_lock(run_id):
            register_brs_selected_obligation(
                ledger,
                handoff,
                native_plan_sha256=value if field == "native_plan_sha256" else HEX,
                controller_checkpoint_sha256=OTHER if field == "episode_record_sha256" else checkpoint,
                episode_record_sha256=value if field == "episode_record_sha256" else episode_sha,
            )


def test_resume_nonterminal_reconcile_preserves_head_and_obligation(tmp_path: Path) -> None:
    ledger, run_id, episode_id, _request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    before = ledger.controller_checkpoint(run_id)
    evidence = _evidence(registration.obligation, process_state="unknown")
    with ledger.controller_lock(run_id):
        result = consume_brs_selected_reconcile(ledger, run_id, episode_id, evidence)
    assert result.decision.outcome == "manual_review"
    assert result.consumed is False
    assert ledger.controller_checkpoint(run_id) == before
    assert ledger.controller_brs_reconcile_obligations(run_id)[episode_id] == registration.obligation.to_dict()


def test_resume_terminal_evidence_consumes_exact_obligation(tmp_path: Path) -> None:
    ledger, run_id, episode_id, _request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    with ledger.controller_lock(run_id):
        result = consume_brs_selected_reconcile(
            ledger, run_id, episode_id, _evidence(registration.obligation),
        )
    assert result.decision.outcome == "already_terminal"
    assert result.consumed is True
    assert ledger.controller_brs_reconcile_obligations(run_id) == {}


def test_unknown_or_drifted_evidence_never_consumes(tmp_path: Path) -> None:
    ledger, run_id, episode_id, _request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    with ledger.controller_lock(run_id):
        result = consume_brs_selected_reconcile(
            ledger, run_id, episode_id, _evidence(registration.obligation, obligation_sha256=OTHER),
        )
    assert result.decision.outcome == "drifted"
    assert result.consumed is False
    assert episode_id in ledger.controller_brs_reconcile_obligations(run_id)
