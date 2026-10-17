"""Actual ledger regressions for selected BRS registration and terminal consume."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from test_rsi_brs_reconcile_controller import (
    HEX,
    OTHER,
    _evidence,
    _fixture,
    _register,
    _terminal_evidence,
)

from lunar_evolution import (
    BRSReconcileObligation,
    DeterministicMockSolver,
    RSILearningController,
    RSILearningError,
    RSIPracticeEpisode,
    SolverRequest,
    consume_brs_selected_reconcile,
)
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_brs_reconcile import FIELD


@pytest.mark.parametrize("field", ["head_sha256", "state_sha256", "owner_thread_id"])
def test_registration_refuses_foreign_selected_handoff_pin(tmp_path: Path, field: str) -> None:
    ledger, run_id, _episode_id, _request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    handoff = replace(handoff, **{field: handoff.owner_thread_id + 1 if field == "owner_thread_id" else OTHER})
    before = ledger.controller_checkpoint_history(run_id)
    with pytest.raises(RSILearningError, match="rsi_brs_reconcile"):
        _register(ledger, run_id, checkpoint, handoff, episode_sha)
    assert ledger.controller_checkpoint_history(run_id) == before


def test_registration_replay_cannot_adopt_unrelated_later_checkpoint(tmp_path: Path) -> None:
    ledger, run_id, _episode_id, _request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    _register(ledger, run_id, checkpoint, handoff, episode_sha)
    with ledger.controller_lock(run_id):
        head, state = ledger.controller_checkpoint(run_id)
        ledger.write_controller_checkpoint(run_id, {**state, "unrelated": True}, expected_sha256=head)
    before = ledger.controller_checkpoint_history(run_id)
    with pytest.raises(RSILearningError, match="checkpoint_conflict"):
        _register(ledger, run_id, checkpoint, handoff, episode_sha)
    assert ledger.controller_checkpoint_history(run_id) == before


def test_registration_rechecks_episode_capture_in_checkpoint_transaction(tmp_path: Path, monkeypatch) -> None:
    ledger, run_id, episode_id, _request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    original = ledger.write_brs_reconcile_obligation

    def write(*args, **kwargs):
        current = ledger.get_episode(episode_id)
        episode = RSIPracticeEpisode.from_dict(current.payload)
        ledger.append_episode_record(
            replace(episode, status="failed", terminal_reason="worker_finished",
                    previous_record_sha256=episode.record_sha256),
            expected_record_sha256=current.record_sha256,
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(ledger, "write_brs_reconcile_obligation", write)
    before = ledger.controller_checkpoint_history(run_id)
    with pytest.raises(RSILearningError, match="episode_binding_invalid"):
        _register(ledger, run_id, checkpoint, handoff, episode_sha)
    assert ledger.controller_checkpoint_history(run_id) == before


@pytest.mark.parametrize("scope", ["run", "episode"])
def test_new_registration_requires_natural_running_owner_scope(tmp_path: Path, scope: str) -> None:
    ledger, run_id, episode_id, request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    if scope == "run":
        run = ledger.get_run(run_id)
        ledger.transition(run_id, state="failed", expected_record_sha256=run.record_sha256)
    else:
        obligation = BRSReconcileObligation(
            run_id, episode_id, "selected", handoff.sha256, request.digest(), HEX, checkpoint, episode_sha,
        )
        _terminal_evidence(ledger, request, obligation)
        episode_sha = ledger.get_episode(episode_id).record_sha256
    before = ledger.controller_checkpoint_history(run_id)
    with pytest.raises(RSILearningError, match="running_owner_required"):
        _register(ledger, run_id, checkpoint, handoff, episode_sha)
    assert ledger.controller_checkpoint_history(run_id) == before


def _register_second(ledger, run_id, request, handoff):
    second_request = SolverRequest.from_dict({**request.to_dict(), "episode_id": f"{run_id}-practice-0-1"})
    first = RSIPracticeEpisode.from_dict(ledger.get_episode(request.episode_id).payload)
    second = replace(first, episode_id=second_request.episode_id, ordinal=1,
                     request_sha256=second_request.digest())
    episode = ledger.create_episode_record(second)
    with ledger.controller_lock(run_id):
        head, state = ledger.controller_checkpoint(run_id)
        state["intents"][second.episode_id] = {"request": second_request.to_dict()}
        checkpoint = ledger.write_controller_checkpoint(run_id, state, expected_sha256=head)
    selected = replace(handoff, ordinal=1, episode_id=second.episode_id, request_sha256=second_request.digest(),
                       head_sha256=checkpoint, state_sha256=hashlib.sha256(canonical_json(state)).hexdigest(),
                       lease_nonce="S" * 32)
    registration = _register(ledger, run_id, checkpoint, selected, episode.record_sha256)
    return second_request, registration


def test_multiple_obligations_keep_original_captures_and_consume_independently(tmp_path: Path) -> None:
    ledger, run_id, episode_id, request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    first = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    second_request, second = _register_second(ledger, run_id, request, handoff)
    assert first.obligation.controller_checkpoint_sha256 != second.obligation.controller_checkpoint_sha256
    second_evidence = _terminal_evidence(ledger, second_request, second.obligation)
    controller = RSILearningController(DeterministicMockSolver(), ledger=ledger)
    result = controller.resume_brs_reconcile(run_id, {
        episode_id: _evidence(first.obligation, process_state="unknown"),
        second_request.episode_id: second_evidence,
    })
    assert result[episode_id].consumed is False
    assert result[second_request.episode_id].consumed is True
    remaining = ledger.controller_checkpoint(run_id)[1][FIELD]
    assert remaining == {episode_id: first.obligation.to_dict()}
    first_evidence = _terminal_evidence(ledger, request, first.obligation)
    assert controller.resume_brs_reconcile(run_id, {episode_id: first_evidence})[episode_id].consumed is True
    assert ledger.controller_brs_reconcile_obligations(run_id) == {}


def test_terminal_flag_cannot_consume_a_running_episode(tmp_path: Path) -> None:
    ledger, run_id, episode_id, _request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    before = ledger.controller_checkpoint_history(run_id)
    with ledger.controller_lock(run_id):
        result = consume_brs_selected_reconcile(ledger, run_id, episode_id, _evidence(registration.obligation))
    assert result.consumed is False
    assert ledger.controller_checkpoint_history(run_id) == before


@pytest.mark.parametrize("fault", ["native_evidence_sha256", "result_evidence_sha256", "terminal_status"])
def test_terminal_evidence_must_match_durable_native_result(tmp_path: Path, fault: str) -> None:
    ledger, run_id, episode_id, request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    evidence = _terminal_evidence(ledger, request, registration.obligation)
    evidence = replace(evidence, **{fault: "failed" if fault == "terminal_status" else HEX})
    before = ledger.controller_checkpoint_history(run_id)
    with ledger.controller_lock(run_id):
        result = consume_brs_selected_reconcile(ledger, run_id, episode_id, evidence)
    assert result.consumed is False
    assert ledger.controller_checkpoint_history(run_id) == before


@pytest.mark.parametrize("missing", ["native_claim", "native_result"])
def test_missing_native_terminal_evidence_keeps_obligation(tmp_path: Path, missing: str) -> None:
    ledger, run_id, episode_id, request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    evidence = _terminal_evidence(ledger, request, registration.obligation, **{missing: False})
    before = ledger.controller_checkpoint_history(run_id)
    with ledger.controller_lock(run_id):
        result = consume_brs_selected_reconcile(ledger, run_id, episode_id, evidence)
    assert result.decision.outcome == "manual_review"
    assert result.consumed is False
    assert ledger.controller_checkpoint_history(run_id) == before


@pytest.mark.parametrize("status", ["completed", "failed", "timed_out", "cancelled"])
def test_consume_preserves_original_capture_through_real_terminal_revision(tmp_path: Path, status: str) -> None:
    ledger, run_id, episode_id, request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    evidence = _terminal_evidence(ledger, request, registration.obligation, status=status)
    assert ledger.get_episode(episode_id).record_sha256 != registration.obligation.episode_record_sha256
    assert evidence.episode_record_sha256 == registration.obligation.episode_record_sha256
    with ledger.controller_lock(run_id):
        result = consume_brs_selected_reconcile(ledger, run_id, episode_id, evidence)
    assert result.consumed is True
    assert ledger.get_episode(episode_id).state == status


@pytest.mark.parametrize("status", ["failed", "timed_out", "cancelled"])
@pytest.mark.parametrize("unknown", [False, True])
def test_consume_accepts_real_explicit_reconcile_with_empty_result_reason(
    tmp_path: Path, status: str, unknown: bool,
) -> None:
    ledger, run_id, episode_id, request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    claim = ledger.claim_native_episode(request, plan_sha256=registration.obligation.native_plan_sha256)
    result = replace(DeterministicMockSolver(terminal_status=status).run(request), terminal_reason="")
    ledger.publish_native_episode_result(request, plan_sha256=registration.obligation.native_plan_sha256,
                                         result=result, expected_claim=claim)
    current = ledger.get_episode(episode_id)
    if unknown:
        current = ledger.reconcile_episode(
            episode_id, worker_state="unknown", expected_record_sha256=current.record_sha256,
            evidence={"reconciliation": {"source": "local-worker-receipt"}},
        )
    terminal = ledger.reconcile_episode(
        episode_id, worker_state=status, expected_record_sha256=current.record_sha256, result=result,
        evidence={"reconciliation": {"source": "local-worker-receipt"}},
    )
    assert terminal.payload["terminal_reason"] == f"reconciled_worker_{status}"
    assert ledger.episode_reconciliation(episode_id)[-1]["worker_state"] == status
    evidence = _evidence(
        registration.obligation, terminal_status=status, native_evidence_sha256=claim.claim_sha256,
        result_evidence_sha256=hashlib.sha256(canonical_json(result.to_dict())).hexdigest(),
    )
    with ledger.controller_lock(run_id):
        consumption = consume_brs_selected_reconcile(ledger, run_id, episode_id, evidence)
    assert consumption.consumed is True
    assert ledger.controller_brs_reconcile_obligations(run_id) == {}


def test_nonempty_saved_terminal_reason_cannot_use_reconcile_fallback(tmp_path: Path) -> None:
    ledger, run_id, episode_id, request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    evidence = _terminal_evidence(ledger, request, registration.obligation, status="failed")
    current = ledger.get_episode(episode_id)
    episode = RSIPracticeEpisode.from_dict(current.payload)
    ledger.append_episode_record(
        replace(episode, terminal_reason="reconciled_worker_failed", previous_record_sha256=episode.record_sha256),
        expected_record_sha256=current.record_sha256,
    )
    before = ledger.controller_checkpoint_history(run_id)
    with ledger.controller_lock(run_id):
        consumption = consume_brs_selected_reconcile(ledger, run_id, episode_id, evidence)
    assert consumption.decision.outcome == "drifted"
    assert consumption.consumed is False
    assert ledger.controller_checkpoint_history(run_id) == before


def test_terminal_episode_projection_must_match_saved_result(tmp_path: Path) -> None:
    ledger, run_id, episode_id, request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    evidence = _terminal_evidence(ledger, request, registration.obligation)
    current = ledger.get_episode(episode_id)
    episode = RSIPracticeEpisode.from_dict(current.payload)
    ledger.append_episode_record(
        replace(episode, trace_digest=OTHER, previous_record_sha256=episode.record_sha256),
        expected_record_sha256=current.record_sha256,
    )
    before = ledger.controller_checkpoint_history(run_id)
    with ledger.controller_lock(run_id):
        result = consume_brs_selected_reconcile(ledger, run_id, episode_id, evidence)
    assert result.decision.outcome == "drifted"
    assert result.consumed is False
    assert ledger.controller_checkpoint_history(run_id) == before


def test_terminal_observation_and_consume_share_one_sqlite_transaction(tmp_path: Path, monkeypatch) -> None:
    ledger, run_id, episode_id, request, checkpoint, handoff, episode_sha = _fixture(tmp_path)
    registration = _register(ledger, run_id, checkpoint, handoff, episode_sha)
    evidence = _terminal_evidence(ledger, request, registration.obligation)
    original = ledger._native_result_status
    observed = []

    def observe(connection, selected_id, request_sha256):
        status = original(connection, selected_id, request_sha256)
        # A different worker's connection cannot change episode/result rows after
        # their terminal state has been observed but before the obligation CAS.
        with sqlite3.connect(ledger.database, timeout=0) as other, pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("BEGIN IMMEDIATE")
        observed.append(status)
        return status

    monkeypatch.setattr(ledger, "_native_result_status", observe)
    with ledger.controller_lock(run_id):
        result = consume_brs_selected_reconcile(ledger, run_id, episode_id, evidence)
    assert observed == ["completed"]
    assert result.consumed is True
