"""Interrupt the actual rejected root transaction and original retirement boundary.

The profile callbacks below are test-only fault injection into existing call and
return events. They add no product hook or recovery/retirement capability. Every
test first completes the real local rejection, worker ACK and natural terminal;
the imported fixture substitutes only native execution/evaluation observations.
"""

from __future__ import annotations

import sys
from copy import deepcopy

import pytest
import test_rsi_brs_rejected_lifecycle as rejected_fixture
import test_rsi_brs_terminal_recovery as terminal_fixture
from test_rsi_python_admission import _rows

from lunar_evolution import RSILearningError
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_python_brs_admission import BRSAdmissionChannel
from lunar_evolution.rsi_store import RSILedger

inert_only = rejected_fixture.inert_only
sealed_launch = rejected_fixture.sealed_launch
tmp_path = rejected_fixture.tmp_path


class _InjectedStop(RuntimeError):
    pass


@pytest.mark.parametrize("entry", ["public", "held"])
def test_terminal_reconcile_uses_one_original_nonreentrant_run_lease(tmp_path, monkeypatch, entry):
    from lunar_evolution import rsi_brs_terminal_evidence as composer

    ledger = RSILedger(tmp_path / "lease.sqlite3")
    controller = RSILearningController.__new__(RSILearningController)
    controller.ledger = ledger
    monkeypatch.setattr(ledger, "get_run", lambda _run_id: object())
    observed = []

    def compose(held_ledger, run_id, episode_id, **_contexts):
        assert held_ledger is ledger and ledger.controller_lock_held(run_id)
        observed.append((run_id, episode_id))
        return {"status": "incomplete"}, None, None

    monkeypatch.setattr(composer, "_compose_brs_terminal_evidence", compose)
    if entry == "public":
        result = controller.reconcile_brs_terminal("run", "episode", workspace=None, native_plan=None)
        assert not ledger.controller_lock_held("run")
    else:
        with ledger.controller_lock("run"):
            result = RSILearningController._reconcile_brs_terminal_locked(
                controller, "run", "episode", workspace=None, native_plan=None,
            )
            assert ledger.controller_lock_held("run")
            with (pytest.raises(RSILearningError, match="^rsi_controller_busy$"),
                  ledger.controller_lock("run")):
                pytest.fail("the original run lease must remain nonreentrant")
    assert result == {"observation": {"status": "incomplete"}, "consumption": None}
    assert observed == [("run", "episode")]


def test_locked_terminal_reconcile_requires_held_lease_before_observation(tmp_path, monkeypatch):
    from lunar_evolution import rsi_brs_terminal_evidence as composer

    controller = RSILearningController.__new__(RSILearningController)
    controller.ledger = RSILedger(tmp_path / "unheld.sqlite3")
    monkeypatch.setattr(composer, "_compose_brs_terminal_evidence",
                        lambda *_args, **_kwargs: pytest.fail("observation without original lease"))
    with pytest.raises(RSILearningError, match="^rsi_controller_lock_required$"):
        RSILearningController._reconcile_brs_terminal_locked(
            controller, "run", "episode", workspace=None, native_plan=None,
        )


def _terminal(value):
    value.ready.set()
    value.session.serve(value.preparation, check=lambda: None, timeout=30)
    execution = rejected_fixture._assert_single_failed_worker(value)
    head, state = value.ledger.controller_checkpoint(value.binding.run_id)
    assert state["executions"] == {}
    assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
    return execution, head, deepcopy(state), len(value.ledger.controller_checkpoint_history(value.binding.run_id))


def _assert_committed(value, execution, old_head, before, count):
    head, state = value.ledger.controller_checkpoint(value.binding.run_id)
    assert head != old_head
    assert len(value.ledger.controller_checkpoint_history(value.binding.run_id)) == count + 1
    assert state["executions"] == {value.episode_id: value.controller._serialize_execution(execution)}
    assert state["root_snapshot"] == before["root_snapshot"]
    assert state["budget_state"] == before["budget_state"]
    assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id) == {}
    assert len(value.callback_calls) == value.gateway.calls == 1


def _assert_no_live_retry(value):
    before = _rows(value)
    with pytest.raises(RSILearningError):
        value.controller._python_admission_settle_original_brs_terminal(value.owner, value.session)
    assert _rows(value) == before
    assert value.owner._poisoned is True and value.session._poisoned is True
    assert value.wave.selected_settlement_started is True
    assert len(value.callback_calls) == value.gateway.calls == 1


def _assert_consumed_recovery_is_read_only(value):
    recovered = rejected_fixture._fresh_controller(value)
    before = _rows(value)
    with pytest.raises(RSILearningError, match="obligation_missing"):
        recovered.reconcile_brs_terminal(value.binding.run_id, value.episode_id,
                                        **terminal_fixture._context(value))
    assert _rows(value) == before
    assert len(value.callback_calls) == value.gateway.calls == 1


def test_stop_before_root_transaction_keeps_fence_then_fresh_recovery_settles_once(tmp_path, monkeypatch):
    with rejected_fixture._natural_rejected_worker(tmp_path, monkeypatch) as value:
        execution, head, before, count = _terminal(value)
        reached = []

        def stop(run_id, episode_id, _evidence, *, expected_pins=None, settled_execution=None):
            assert expected_pins["root_checkpoint_sha256"] == head
            assert settled_execution == value.controller._serialize_execution(execution)
            reached.append((run_id, episode_id))
            raise _InjectedStop("before-root-transaction")

        with monkeypatch.context() as fault:
            fault.setattr(value.ledger, "_consume_brs_reconcile_obligation", stop)
            with pytest.raises(_InjectedStop, match="before-root-transaction"):
                value.controller._python_admission_settle_original_brs_terminal(value.owner, value.session)
        assert reached == [(value.binding.run_id, value.episode_id)]
        assert value.ledger.controller_checkpoint(value.binding.run_id) == (head, before)
        assert len(value.ledger.controller_checkpoint_history(value.binding.run_id)) == count
        _assert_no_live_retry(value)
    recovered = rejected_fixture._fresh_controller(value)
    result = recovered.reconcile_brs_terminal(value.binding.run_id, value.episode_id,
                                              **terminal_fixture._context(value))
    assert result["consumption"].consumed is True
    _assert_committed(value, execution, head, before, count)
    _assert_consumed_recovery_is_read_only(value)


def test_stop_after_root_commit_before_consume_return_keeps_exact_cached_result(tmp_path, monkeypatch):
    with rejected_fixture._natural_rejected_worker(tmp_path, monkeypatch) as value:
        execution, head, before, count = _terminal(value)
        original = value.ledger._consume_brs_reconcile_obligation
        committed = []

        def stop(run_id, episode_id, evidence, *, expected_pins=None, settled_execution=None):
            result = original(run_id, episode_id, evidence, expected_pins=expected_pins,
                              settled_execution=settled_execution)
            assert result.consumed is True
            assert value.ledger.controller_checkpoint(run_id)[0] == result.checkpoint_sha256
            committed.append(result.checkpoint_sha256)
            raise _InjectedStop("after-root-commit")

        with monkeypatch.context() as fault:
            fault.setattr(value.ledger, "_consume_brs_reconcile_obligation", stop)
            with pytest.raises(_InjectedStop, match="after-root-commit"):
                value.controller._python_admission_settle_original_brs_terminal(value.owner, value.session)
        assert len(committed) == 1 and committed[0] != head
        _assert_committed(value, execution, head, before, count)
        _assert_no_live_retry(value)
    _assert_consumed_recovery_is_read_only(value)


def test_stop_after_verified_root_before_original_channel_retirement_is_not_retry_authority(tmp_path, monkeypatch):
    with rejected_fixture._natural_rejected_worker(tmp_path, monkeypatch) as value:
        execution, head, before, count = _terminal(value)
        original_channel = value.owner._channel
        retire_code = BRSAdmissionChannel.complete_selected_handoff.__code__
        reached = []

        def interrupt(frame, event, _argument):
            if event == "call" and frame.f_code is retire_code:
                reached.append(frame.f_locals["self"])
                raise _InjectedStop("before-original-channel-retirement")

        previous = sys.getprofile()
        try:
            sys.setprofile(interrupt)
            with pytest.raises(_InjectedStop, match="before-original-channel-retirement"):
                value.controller._python_admission_settle_original_brs_terminal(value.owner, value.session)
        finally:
            sys.setprofile(previous)
        assert reached == [original_channel]  # The real retirement call was reached once.
        assert original_channel._selected_episode_id == value.episode_id
        assert original_channel._completed_selected_episodes == set()
        _assert_committed(value, execution, head, before, count)
        _assert_no_live_retry(value)
    _assert_consumed_recovery_is_read_only(value)


def test_source_observation_cannot_replace_original_channel_before_retirement(tmp_path, monkeypatch):
    with rejected_fixture._natural_rejected_worker(tmp_path, monkeypatch) as value:
        execution, head, before, count = _terminal(value)
        original_channel = value.owner._channel
        replacement = BRSAdmissionChannel(value.binding.run_id, value.wave.episode_ids,
                                          owner_thread=value.owner._thread)
        validation_code = RSILearningController._validate_resume_identity.__code__
        retire_code = BRSAdmissionChannel.complete_selected_handoff.__code__
        injected, retired = [], []

        def replace_after_observation(frame, event, _argument):
            if event == "return" and frame.f_code is validation_code and not injected:
                injected.append(frame.f_locals["self"])
                value.owner._channel = replacement
            elif event == "call" and frame.f_code is retire_code:
                retired.append(frame.f_locals["self"])

        previous = sys.getprofile()
        try:
            sys.setprofile(replace_after_observation)
            with pytest.raises(RSILearningError, match="^rsi_brs_terminal_original_readback_drift$"):
                value.controller._python_admission_settle_original_brs_terminal(value.owner, value.session)
        finally:
            sys.setprofile(previous)
        assert injected == [value.controller]  # The intended post-observation boundary ran.
        assert retired == []
        assert original_channel._selected_episode_id == value.episode_id
        assert original_channel._completed_selected_episodes == set()
        assert replacement._requests == {} and replacement._completed_selected_episodes == set()
        _assert_committed(value, execution, head, before, count)
        _assert_no_live_retry(value)
    _assert_consumed_recovery_is_read_only(value)
