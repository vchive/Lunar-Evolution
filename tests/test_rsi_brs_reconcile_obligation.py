"""Provider-free contract tests for the durable BRS owner obligation value."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT,
    BRSReconcileObligation,
    RSILearningError,
    RSILedger,
    parse_brs_reconcile_obligations,
    put_brs_reconcile_obligation,
    remove_brs_reconcile_obligation,
    validate_brs_reconcile_obligations,
)
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_brs_reconcile import FIELD
from lunar_evolution.rsi_gateway import SolverRequest

HEX = "a" * 64


def _request(episode_id: str = "run-practice-0-0") -> SolverRequest:
    return SolverRequest.build(
        episode_id=episode_id,
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="fixture",
    )


def _obligation(request: SolverRequest, checkpoint: str = HEX) -> BRSReconcileObligation:
    return BRSReconcileObligation(
        run_id="run",
        episode_id=request.episode_id,
        phase="selected",
        handoff_sha256=HEX,
        request_sha256=request.digest(),
        native_plan_sha256=HEX,
        controller_checkpoint_sha256=checkpoint,
        episode_record_sha256=HEX,
    )


def test_obligation_roundtrip_and_digest_are_canonical() -> None:
    request = _request()
    obligation = _obligation(request)
    restored = BRSReconcileObligation.from_dict(obligation.to_dict())
    assert restored == obligation
    assert restored.digest() == hashlib.sha256(canonical_json(obligation.to_dict())).hexdigest()
    assert parse_brs_reconcile_obligations({request.episode_id: obligation.to_dict()}) == {
        request.episode_id: obligation,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [("phase", "running"), ("request_sha256", "x" * 64), ("mailbox_state", "callback")],
)
def test_obligation_rejects_invalid_identity_and_phase(field: str, value: str) -> None:
    request = _request()
    wire = _obligation(request).to_dict()
    wire[field] = value
    with pytest.raises(RSILearningError, match="rsi_brs_reconcile"):
        BRSReconcileObligation.from_dict(wire)


def test_phase_transition_preserves_captured_identity_and_forbids_skip() -> None:
    request = _request()
    obligation = _obligation(request)
    advanced = obligation.advance("worker_running", mailbox_state="inflight")
    assert advanced.phase == "worker_running"
    assert advanced.controller_checkpoint_sha256 == obligation.controller_checkpoint_sha256
    assert advanced.episode_record_sha256 == obligation.episode_record_sha256
    with pytest.raises(RSILearningError, match="phase_transition"):
        obligation.advance("settlement")
    settled = obligation.advance("worker_running").advance("worker_result").advance(
        "owner_publication").advance("result_delivery").advance("settlement").advance(
            "settled", transaction_state="settled")
    with pytest.raises(RSILearningError, match="phase_terminal"):
        settled.advance("worker_running")


def test_mutable_state_put_is_idempotent_and_conflicts_are_rejected() -> None:
    request = _request()
    obligation = _obligation(request)
    state = {"run_id": "run"}
    put_brs_reconcile_obligation(state, obligation)
    first = state[FIELD]
    put_brs_reconcile_obligation(state, obligation)
    assert state[FIELD] == first
    with pytest.raises(RSILearningError, match="obligation_conflict"):
        put_brs_reconcile_obligation(state, obligation.advance("worker_running"))
    remove_brs_reconcile_obligation(state, request.episode_id, expected_digest=obligation.digest())
    assert state[FIELD] == {}


def _checkpoint_fixture(tmp_path: Path) -> tuple[RSILedger, str, str, SolverRequest, BRSReconcileObligation]:
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    run_id = "run"
    request = _request()
    payload = {"mode": "brs", "plan": {"mode": "brs"}, "budget": {}, "intents": {
        request.episode_id: {"request": request.to_dict()},
    }}
    created = ledger.create_run(run_id, "b" * 64, payload)
    ledger.transition(run_id, state="running", expected_record_sha256=created.record_sha256)
    state = {"run_id": run_id, "intents": payload["intents"], "brs_reconcile_obligations": {}}
    with ledger.controller_lock(run_id):
        checkpoint = ledger.write_controller_checkpoint(run_id, state, expected_sha256=None)
        obligation = BRSReconcileObligation.from_dict(
            {**_obligation(request, checkpoint).to_dict(), "run_id": run_id}
        )
    return ledger, run_id, checkpoint, request, obligation


def test_ledger_obligation_checkpoint_write_remove_and_exact_replay(tmp_path: Path) -> None:
    ledger, run_id, checkpoint, request, obligation = _checkpoint_fixture(tmp_path)
    with ledger.controller_lock(run_id):
        next_head = ledger.write_brs_reconcile_obligation(
            run_id, obligation, expected_checkpoint_sha256=checkpoint,
        )
        assert next_head != checkpoint
        assert ledger.write_brs_reconcile_obligation(
            run_id, obligation, expected_checkpoint_sha256=next_head,
        ) == next_head
        assert ledger.controller_brs_reconcile_obligations(run_id)[request.episode_id] == obligation.to_dict()
        with pytest.raises(RSILearningError, match="checkpoint_conflict"):
            ledger.write_brs_reconcile_obligation(
                run_id, obligation, expected_checkpoint_sha256=checkpoint,
            )
        removed = ledger.remove_brs_reconcile_obligation(
            run_id, request.episode_id, expected_checkpoint_sha256=next_head,
            expected_obligation_digest=obligation.digest(),
        )
    assert removed != next_head
    assert ledger.controller_brs_reconcile_obligations(run_id) == {}


def test_validate_rejects_stale_request_binding() -> None:
    request = _request()
    obligation = _obligation(request)
    state = {"run_id": "run", "intents": {
        request.episode_id: {"request": {**request.to_dict(), "solver_id": "changed"}},
    }, FIELD: {request.episode_id: obligation.to_dict()}}
    with pytest.raises(RSILearningError, match="request_binding"):
        validate_brs_reconcile_obligations(state, run_id="run", intents=state["intents"])
