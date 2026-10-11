"""Prepared observers cannot admit evaluation before durable authority and control."""

from __future__ import annotations

import pytest
from test_producer_bundle_transaction_control import FakeClock, _batch, _call, _fixture, _prefix

from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.producer_bundle_intent import verify_producer_bundle_prepared_intent
from lunar_evolution.producer_bundle_transaction import NativeProducerBundleTransactionError


def _forbid_evaluation(monkeypatch, context):
    monkeypatch.setattr(
        context.bundle_pipeline, "evaluate_draft_non_publishing",
        lambda *a, **k: pytest.fail("prepared refusal reached the evaluator"),
    )


def test_observer_sees_original_durable_intent_before_evaluation(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    observed = []
    _forbid_evaluation(monkeypatch, context)

    class StopPrepared(ValueError):
        code = "inert_prepared_observer_stop"

    stop = StopPrepared()

    def observer(journal):
        assert journal.state == "prepared"
        assert verify_producer_bundle_prepared_intent(context.workspace, journal) == journal.digest()
        observed.append(journal.to_dict())
        raise stop

    with pytest.raises(NativeProducerBundleTransactionError) as caught:
        _call(fixture, None, prepared_observer=observer)
    assert caught.value.code == stop.code and caught.value.__cause__ is stop
    assert len(observed) == 1
    assert _prefix(context) == before
    assert (_batch(context, journal_id) / "journal.prepared.json").is_file()
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()
    assert not (_batch(context, journal_id) / "terminal.json").exists()


@pytest.mark.parametrize("stop", ["deadline", "cancellation"])
def test_observer_control_change_refuses_before_evaluation(tmp_path, monkeypatch, stop):
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    clock = FakeClock()
    control = SolveExecutionControl(30, clock=clock)
    observed = []
    _forbid_evaluation(monkeypatch, context)

    def observer(journal):
        assert verify_producer_bundle_prepared_intent(context.workspace, journal) == journal.digest()
        observed.append(journal.digest())
        if stop == "deadline":
            clock.value = control.deadline
        else:
            control.cancel()

    expected = SolveExecutionBudgetExceeded if stop == "deadline" else SolveExecutionCancelled
    with pytest.raises(expected):
        _call(fixture, control, prepared_observer=observer)
    assert len(observed) == 1
    assert _prefix(context) == before
    assert (_batch(context, journal_id) / "journal.prepared.json").is_file()
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()


def test_cancelled_prepared_checkpoint_does_not_notify_observer(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    _forbid_evaluation(monkeypatch, context)

    def guard(stage):
        if stage == "producer_prepared_admission":
            raise SolveExecutionCancelled(stage)

    with pytest.raises(SolveExecutionCancelled):
        _call(
            fixture, None, continuation_guard=guard,
            prepared_observer=lambda journal: pytest.fail("stopped checkpoint notified observer"),
        )
    assert _prefix(context) == before
    assert (_batch(context, journal_id) / "journal.prepared.json").is_file()
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()


@pytest.mark.parametrize("mutation", ["missing", "bytes"])
def test_observer_cannot_replace_original_prepared_authority(tmp_path, monkeypatch, mutation):
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    durable = _batch(context, journal_id) / "journal.prepared.json"
    observed = []
    _forbid_evaluation(monkeypatch, context)

    def observer(journal):
        observed.append(journal.digest())
        if mutation == "missing":
            durable.unlink()
        else:
            durable.write_bytes(durable.read_bytes() + b"\n# inert altered intent\n")

    with pytest.raises(NativeProducerBundleTransactionError):
        _call(fixture, None, prepared_observer=observer)
    assert len(observed) == 1
    assert _prefix(context) == before
    if mutation == "missing":
        assert not durable.exists()
    else:
        assert durable.read_bytes().endswith(b"\n# inert altered intent\n")
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()


def test_invalid_observer_refuses_before_prepared_io(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    _forbid_evaluation(monkeypatch, context)
    with pytest.raises(NativeProducerBundleTransactionError) as caught:
        _call(fixture, None, prepared_observer=object())
    assert caught.value.code == "producer_bundle_transaction_prepared_observer_invalid"
    assert _prefix(context) == before
    assert list(_batch(context, journal_id).iterdir()) == []
