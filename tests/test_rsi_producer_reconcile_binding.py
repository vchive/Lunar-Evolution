"""Producer proof remains mandatory after an evidence budget reservation crash."""

from __future__ import annotations

import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from test_rsi_controller_callbacks import (
    PINS,
    CallbackCrash,
    Curriculum,
    Gateway,
    Judge,
    Verifier,
)
from test_rsi_native_failure_gateway import FixtureCrash, _gateway, _pins
from test_rsi_native_failure_provenance import _native_failure_rsi_fixture
from test_rsi_producer_checkpoint_binding import _sidecar

from lunar_evolution import RSILearningController, RSILearningError, RSILedger
from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_callbacks import DurableCallbackJournal


def _ledger_snapshot(ledger: RSILedger, run_id: str):
    """Ignore reads while retaining every controller/episode/result mutation boundary."""
    episodes = ledger.episode_ids_for_run(run_id)
    return (
        ledger.history(run_id),
        ledger.controller_checkpoint_history(run_id),
        tuple((key, ledger.history(key), ledger.episode_result(key),
               ledger.episode_reconciliation(key)) for key in episodes),
    )


def _drift_sidecar(tmp_path: Path, sidecar, drift: str):
    if drift == "missing":
        path = (tmp_path / "evolution" / "producer-batches"
                / sidecar.binding.intent.journal_id / "python-producer-binding.json")
        path.unlink()
        return sidecar
    return replace(sidecar, file_inode=sidecar.file_inode + 1)


def _reserve_then_interrupt(learner, monkeypatch, operation, reservation_field):
    save = learner._save_flow

    def stop_after_reservation(record, state):
        save(record, state)
        if state.get(reservation_field):
            raise FixtureCrash("producer_reconciliation_reservation_persisted")

    with monkeypatch.context() as patch:
        patch.setattr(learner, "_save_flow", stop_after_reservation)
        with pytest.raises(FixtureCrash, match="reservation_persisted"):
            operation()


@pytest.mark.parametrize("drift", ["missing", "mismatch"])
@pytest.mark.parametrize("entry", ["resume", "reconcile"])
def test_reserved_callback_recovery_requires_producer_proof(tmp_path, monkeypatch, drift, entry):
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "callbacks.sqlite")
    gateway, verifier, judge, curriculum = Gateway(), Verifier(), Judge(crash=True), Curriculum()
    components = {"verifier": verifier, "target_judge": judge, "curriculum": curriculum}
    learner = RSILearningController(
        gateway, ledger=ledger, producer_sidecar=sidecar, producer_workspace=tmp_path,
        **components,
    )
    with pytest.raises(CallbackCrash, match="judge_response_lost"):
        learner.run_drs(
            run_id=binding.run_id, **PINS, max_practice_rounds=1, max_target_attempts=2,
            budget={"max_unknown_retries": 1},
        )
    episode_id = f"{binding.run_id}-target-0"
    callback_id = "judge:" + episode_id
    checkpoint, callback = learner.callback_checkpoint(binding.run_id, callback_id)
    result = deepcopy(judge.outputs[episode_id])
    evidence = {
        "source": "local-producer-reconciliation-fixture",
        "binding_sha256": DurableCallbackJournal.digest(callback["binding"]),
        "result_sha256": DurableCallbackJournal.digest(result),
        "receipt_sha256": DurableCallbackJournal.digest({"retained-result": result}),
    }
    arguments = {
        "run_id": binding.run_id, "callback_id": callback_id,
        "expected_checkpoint_sha256": checkpoint, "result": result, "evidence": evidence,
    }
    _reserve_then_interrupt(
        learner, monkeypatch, lambda: learner.reconcile_callback(**arguments),
        "callback_reconciliation_reservations",
    )
    state = ledger.controller_checkpoint(binding.run_id)[1]
    assert state["budget_state"]["consumed"]["unknown_retries"] == 1
    assert learner.callback_checkpoint(binding.run_id, callback_id)[1]["status"] == "started"
    before = _ledger_snapshot(ledger, binding.run_id)
    before_callback = ledger.controller_checkpoint_history(
        DurableCallbackJournal.identity(binding.run_id, callback_id),
    )
    calls = tuple(tuple(component.calls) for component in (gateway, verifier, judge, curriculum))
    restarted = RSILearningController(
        gateway, ledger=ledger, producer_sidecar=_drift_sidecar(tmp_path, sidecar, drift),
        producer_workspace=tmp_path, **components,
    )

    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        if entry == "resume":
            restarted.resume(binding.run_id)
        else:
            restarted.reconcile_callback(**arguments)

    assert _ledger_snapshot(ledger, binding.run_id) == before
    assert ledger.controller_checkpoint_history(
        DurableCallbackJournal.identity(binding.run_id, callback_id),
    ) == before_callback
    assert tuple(tuple(component.calls) for component in (gateway, verifier, judge, curriculum)) == calls


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native platform")
@pytest.mark.parametrize("drift", ["missing", "mismatch"])
@pytest.mark.parametrize("entry", ["resume", "reconcile"])
def test_reserved_native_failure_recovery_requires_producer_proof(tmp_path, monkeypatch, drift, entry):
    binding, sidecar = _sidecar(tmp_path)
    policy = {"max_practice_rounds": 0, "max_target_attempts": 1,
              "max_solver_invocations": 1, "max_unknown_retries": 1}
    prepared = _native_failure_rsi_fixture(
        tmp_path, episode_id=f"{binding.run_id}-target-0",
        budget=RSIRunBudget.create(policy).state["planned"],
    )
    gateway = _gateway(prepared)
    learner = RSILearningController(
        gateway, ledger=prepared.ledger, producer_sidecar=sidecar, producer_workspace=tmp_path,
    )

    def interrupt_result(*_args, **_kwargs):
        raise FixtureCrash("native_proof_before_result")

    with monkeypatch.context() as patch:
        patch.setattr(prepared.ledger, "publish_native_episode_result", interrupt_result)
        with pytest.raises(FixtureCrash, match="native_proof_before_result"):
            learner.run_drs(
                run_id=binding.run_id, **{key: getattr(prepared.request, key) for key in (
                    "contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id",
                )}, budget=policy, max_practice_rounds=0, max_target_attempts=1,
            )
    checkpoint = prepared.ledger.controller_checkpoint(binding.run_id)
    head = prepared.ledger.get_episode(prepared.request.episode_id)
    arguments = dict(
        run_id=binding.run_id, episode_id=prepared.request.episode_id,
        expected_checkpoint_sha256=checkpoint[0],
        expected_episode_record_sha256=head.record_sha256, **_pins(prepared),
    )
    _reserve_then_interrupt(
        learner, monkeypatch, lambda: learner.reconcile_native_failure(**arguments),
        "native_failure_reconciliation_reservations",
    )
    ledger = prepared.ledger
    assert ledger.controller_checkpoint(binding.run_id)[1]["budget_state"]["consumed"]["unknown_retries"] == 1
    assert ledger.episode_result(prepared.request.episode_id) is None
    before = _ledger_snapshot(ledger, binding.run_id)
    restarted = RSILearningController(
        gateway, ledger=ledger, producer_sidecar=_drift_sidecar(tmp_path, sidecar, drift),
        producer_workspace=tmp_path,
    )

    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        if entry == "resume":
            restarted.resume(binding.run_id)
        else:
            restarted.reconcile_native_failure(**arguments)

    assert _ledger_snapshot(ledger, binding.run_id) == before
    assert ledger.episode_result(prepared.request.episode_id) is None
