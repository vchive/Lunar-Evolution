"""Actual native proof registration across controller result/episode/checkpoint crash gaps."""
from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import replace

import pytest
from test_rsi_native_failure_gateway import FixtureCrash, _gateway, _pins
from test_rsi_native_failure_provenance import _native_failure_rsi_fixture

import lunar_evolution.rsi_native_scheduler as scheduler
from lunar_evolution.producer_bootstrap import TrustedBootstrapSession
from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_controller import CurriculumDecision, RSILearningController
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, RSILearningError
from lunar_evolution.rsi_native_gateway import NativeRSISolverGatewayError
from lunar_evolution.rsi_native_scheduler import make_native_rsi_scheduler_provider


class ObservedCancellation:
    def __init__(self, marker):
        self.marker = marker
        self.accepted = False

    def __call__(self):
        return self.accepted and self.marker.exists()

    def rsi_fingerprint_config(self):
        return {"fixture": "accepted-start-cancellation", "marker": str(self.marker)}


def _prepare_controller(tmp_path, monkeypatch, *, mode="drs", crash_point="result", deadline=None, outcome="failed"):
    policy = {"max_practice_rounds": 0, "max_target_attempts": 1,
              "max_solver_invocations": 1, "max_unknown_retries": 3}
    if deadline is not None:
        policy["deadline_unix"] = deadline
    decision = CurriculumDecision("local", "gap", "fixture", "practice", "failure", "local",
                                  ("native_population",))
    if mode == "brs":
        policy["max_practice_rounds"] = 1
    prepared = _native_failure_rsi_fixture(
        tmp_path, episode_id="failure-run-target-0" if mode == "drs" else "failure-run-practice-0-0",
        budget=RSIRunBudget.create(policy).state["planned"],
        practice_charter=None if mode == "drs" else {**decision.to_dict(), "decision_sha256": decision.digest()},
        target_source=None if outcome == "failed" else (
            '#include <stdio.h>\n#include <unistd.h>\n'
            'int main(void){FILE *f=fopen("started","wb");'
            'if(!f||fputs("target",f)<0||fclose(f)!=0)return 2;sleep(20);return 0;}\n'
        ),
    )
    if outcome == "cancelled":
        cancellation = ObservedCancellation(prepared.batch / "work" / "started")
        accept_frame = TrustedBootstrapSession.accept_frame
        def observe(session, frame):
            accept_frame(session, frame)
            if frame.kind == "target_started":
                cancellation.accepted = True
        monkeypatch.setattr(TrustedBootstrapSession, "accept_frame", observe)
        prepared.context = replace(prepared.context, cancelled=cancellation)
        prepared.provider = make_native_rsi_scheduler_provider(prepared.context)
    gateway = _gateway(prepared)
    learner = RSILearningController(gateway, ledger=prepared.ledger)
    if crash_point == "result":
        original = prepared.ledger.publish_native_episode_result
        def crash(*args, **kwargs):
            raise FixtureCrash("proof before result")
        target, name = prepared.ledger, "publish_native_episode_result"
    else:
        original = prepared.ledger.save_episode_result
        def crash(*args, **kwargs):
            raise FixtureCrash("result before episode")
        target, name = prepared.ledger, "save_episode_result"
    with monkeypatch.context() as patch:
        patch.setattr(target, name, crash)
        arguments = {key: getattr(prepared.request, key) for key in (
            "contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id",
        )}
        with pytest.raises(FixtureCrash):
            if mode == "drs":
                learner.run_drs(run_id="failure-run", **arguments, budget=policy,
                                max_practice_rounds=0, max_target_attempts=1)
            else:
                learner.run_brs(run_id="failure-run", **arguments, budget=policy, practices=[decision])
    assert getattr(target, name) == original
    checkpoint = prepared.ledger.controller_checkpoint("failure-run")
    head = prepared.ledger.get_episode(prepared.request.episode_id)
    pins = dict(expected_checkpoint_sha256=checkpoint[0], expected_episode_record_sha256=head.record_sha256,
                **_pins(prepared))
    return prepared, gateway, learner, pins


def _reconcile(learner, prepared, pins):
    return learner.reconcile_native_failure("failure-run", prepared.request.episode_id, **pins)


@pytest.mark.parametrize("mode", ["drs", "brs"])
@pytest.mark.parametrize("crash_point", ["result", "episode"])
@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_actual_native_failure_reconciles_without_dispatch_and_reuses_one_budget(tmp_path, monkeypatch, mode, crash_point, outcome):
    prepared, gateway, learner, pins = _prepare_controller(tmp_path, monkeypatch, mode=mode, crash_point=crash_point, outcome=outcome)
    before = prepared.ledger.controller_checkpoint("failure-run")[1]
    original_budget = deepcopy(before["budget_state"])
    monkeypatch.setattr(scheduler, "run_native_trusted_producer_outcome", lambda *_a, **_k: pytest.fail("reconcile launched"))
    settled = _reconcile(learner, prepared, pins)
    assert settled.result.status == outcome and not settled.passed
    state = prepared.ledger.controller_checkpoint("failure-run")[1]
    assert state["budget_state"]["consumed"]["unknown_retries"] == original_budget["consumed"]["unknown_retries"] + 1
    assert state["budget_state"]["consumed"]["solver_invocations"] == 1
    assert state["judgments"] == {} and state["decisions"] == {}
    assert state["status"] == before["status"] and state["phase"] == before["phase"]
    assert learner.snapshot == EMPTY_MEMORY_SNAPSHOT
    history = prepared.ledger.controller_checkpoint_history("failure-run")
    restarted = RSILearningController(gateway, ledger=prepared.ledger)
    assert _reconcile(restarted, prepared, pins) == settled
    assert prepared.ledger.controller_checkpoint_history("failure-run") == history


@pytest.mark.parametrize("crash_point", ["reservation", "result", "episode", "checkpoint"])
def test_reconcile_crashes_keep_one_reservation_and_never_relaunch(tmp_path, monkeypatch, crash_point):
    prepared, gateway, learner, pins = _prepare_controller(tmp_path, monkeypatch)
    if crash_point == "reservation":
        original = learner._save_flow
        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise FixtureCrash("reservation persisted")
        target, name = learner, "_save_flow"
    elif crash_point == "result":
        original = prepared.ledger.publish_native_episode_result
        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise FixtureCrash("result persisted")
        target, name = prepared.ledger, "publish_native_episode_result"
    elif crash_point == "episode":
        original = prepared.ledger.reconcile_episode
        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise FixtureCrash("episode persisted")
        target, name = prepared.ledger, "reconcile_episode"
    else:
        original = learner._save_flow
        def crash(record, state):
            original(record, state)
            if state["executions"]:
                raise FixtureCrash("checkpoint persisted")
        target, name = learner, "_save_flow"
    monkeypatch.setattr(scheduler, "run_native_trusted_producer_outcome", lambda *_a, **_k: pytest.fail("reconcile launched"))
    with monkeypatch.context() as patch:
        patch.setattr(target, name, crash)
        with pytest.raises(FixtureCrash):
            _reconcile(learner, prepared, pins)
    restarted = RSILearningController(gateway, ledger=prepared.ledger)
    result = _reconcile(restarted, prepared, pins)
    assert result.result.status == "failed"
    assert prepared.ledger.controller_checkpoint("failure-run")[1]["budget_state"]["consumed"]["unknown_retries"] == 1
    assert len(prepared.ledger.episode_reconciliation(prepared.request.episode_id)) == 1


@pytest.mark.parametrize("pin", ["expected_checkpoint_sha256", "expected_episode_record_sha256",
                                 "expected_claim_sha256", "expected_provenance_sha256"])
def test_stale_pins_refuse_without_budget_or_result_write(tmp_path, monkeypatch, pin):
    prepared, _gateway_value, learner, pins = _prepare_controller(tmp_path, monkeypatch)
    before = prepared.ledger.controller_checkpoint_history("failure-run")
    with pytest.raises((RSILearningError, NativeRSISolverGatewayError)):
        _reconcile(learner, prepared, {**pins, pin: "a" * 64})
    assert prepared.ledger.controller_checkpoint_history("failure-run") == before
    assert prepared.ledger.episode_result(prepared.request.episode_id) is None


def test_recording_expired_proof_keeps_original_dispatch_deadline(tmp_path, monkeypatch):
    deadline = time.time() + 120
    prepared, gateway, learner, pins = _prepare_controller(tmp_path, monkeypatch, deadline=deadline)
    # Freeze wall observation after the original deadline; evidence-only registration does
    # not invoke the dispatch budget check or change its planned absolute timestamp.
    monkeypatch.setattr(time, "time", lambda: deadline + 1)
    settled = _reconcile(learner, prepared, pins)
    assert settled.result.status == "failed"
    state = prepared.ledger.controller_checkpoint("failure-run")[1]
    assert state["budget_state"]["planned"]["deadline_unix"] == deadline
    assert RSILearningController(gateway, ledger=prepared.ledger).resume("failure-run", now=deadline + 1).status == "budget_exhausted"


def test_changed_proof_after_reservation_cannot_reuse_budget(tmp_path, monkeypatch):
    prepared, gateway, learner, pins = _prepare_controller(tmp_path, monkeypatch)
    original = learner._save_flow
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise FixtureCrash("reservation")
    with monkeypatch.context() as patch:
        patch.setattr(learner, "_save_flow", crash)
        with pytest.raises(FixtureCrash):
            _reconcile(learner, prepared, pins)
    history = prepared.ledger.controller_checkpoint_history("failure-run")
    with pytest.raises(RSILearningError, match="checkpoint_conflict"):
        _reconcile(RSILearningController(gateway, ledger=prepared.ledger), prepared,
                   {**pins, "expected_provenance_sha256": "a" * 64})
    assert prepared.ledger.controller_checkpoint_history("failure-run") == history


@pytest.mark.parametrize("target", ["checkpoint", "episode"])
def test_reader_callback_cannot_move_cas_boundary_before_reservation(tmp_path, monkeypatch, target):
    prepared, gateway, learner, pins = _prepare_controller(tmp_path, monkeypatch)
    inspect_failure = gateway.inspect_failure
    appended = []
    def drift(*args, **kwargs):
        result = inspect_failure(*args, **kwargs)
        if target == "checkpoint":
            checkpoint, state = prepared.ledger.controller_checkpoint("failure-run")
            state["phase"] = "changed-during-reader"
            appended.append(prepared.ledger.write_controller_checkpoint(
                "failure-run", state, expected_sha256=checkpoint,
            ))
        else:
            head = prepared.ledger.get_episode(prepared.request.episode_id)
            appended.append(prepared.ledger.reconcile_episode(
                prepared.request.episode_id, worker_state="unknown", expected_record_sha256=head.record_sha256,
                evidence={"reconciliation": {"source": "competing-reader"}},
            ))
        return result
    monkeypatch.setattr(gateway, "inspect_failure", drift)
    with pytest.raises(RSILearningError, match="checkpoint_conflict"):
        _reconcile(learner, prepared, pins)
    assert appended and prepared.ledger.episode_result(prepared.request.episode_id) is None
    state = prepared.ledger.controller_checkpoint("failure-run")[1]
    assert state["budget_state"]["consumed"]["unknown_retries"] == 0
    assert state.get("native_failure_reconciliation_reservations", {}) == {}
    if target == "checkpoint":
        assert state["phase"] == "changed-during-reader"
    else:
        assert prepared.ledger.get_episode(prepared.request.episode_id).state == "unknown"


@pytest.mark.parametrize("field", ["pins", "root_snapshot"])
def test_rehashed_controller_checkpoint_identity_drift_cannot_settle(tmp_path, monkeypatch, field):
    prepared, _gateway_value, learner, pins = _prepare_controller(tmp_path, monkeypatch)
    checkpoint, state = prepared.ledger.controller_checkpoint("failure-run")
    if field == "pins":
        state["pins"]["solver_id"] = "substituted"
    else:
        state["root_snapshot"]["snapshot_id"] = "substituted"
    with prepared.ledger.controller_lock("failure-run"):
        new = prepared.ledger.write_controller_checkpoint("failure-run", state, expected_sha256=checkpoint)
    pins["expected_checkpoint_sha256"] = new
    before = prepared.ledger.controller_checkpoint_history("failure-run")
    with pytest.raises(RSILearningError, match="episode_mismatch|memory_drift"):
        _reconcile(learner, prepared, pins)
    assert prepared.ledger.controller_checkpoint_history("failure-run") == before
    assert prepared.ledger.episode_result(prepared.request.episode_id) is None


@pytest.mark.parametrize("target", ["checkpoint", "episode"])
def test_restore_reader_cannot_move_reserved_cas_before_result_publication(tmp_path, monkeypatch, target):
    prepared, _gateway_value, learner, pins = _prepare_controller(tmp_path, monkeypatch)
    recover = prepared.provider.recover
    effects = []
    def drift(*args, **kwargs):
        evidence = recover(*args, **kwargs)
        checkpoint, state = prepared.ledger.controller_checkpoint("failure-run")
        if state.get("native_failure_reconciliation_reservations") and not effects:
            if target == "checkpoint":
                state["phase"] = "competing-after-reservation-reader"
                effects.append(prepared.ledger.write_controller_checkpoint(
                    "failure-run", state, expected_sha256=checkpoint,
                ))
            else:
                head = prepared.ledger.get_episode(prepared.request.episode_id)
                effects.append(prepared.ledger.reconcile_episode(
                    prepared.request.episode_id, worker_state="unknown", expected_record_sha256=head.record_sha256,
                    evidence={"reconciliation": {"source": "competing-after-reservation-reader"}},
                ))
        return evidence
    monkeypatch.setattr(prepared.provider, "recover", drift)
    with pytest.raises(RSILearningError, match="checkpoint_conflict"):
        _reconcile(learner, prepared, pins)
    assert effects and prepared.ledger.episode_result(prepared.request.episode_id) is None
    state = prepared.ledger.controller_checkpoint("failure-run")[1]
    assert state["budget_state"]["consumed"]["unknown_retries"] == 1
    if target == "checkpoint":
        assert state["phase"] == "competing-after-reservation-reader"
    else:
        assert prepared.ledger.get_episode(prepared.request.episode_id).state == "unknown"
