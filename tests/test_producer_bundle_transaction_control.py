"""Shared active deadline and cancellation across native publication boundaries."""

from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from dataclasses import replace
from threading import Event, Thread

import pytest
from test_bundle_population import build_context
from test_producer_bundle_transaction import (
    _batch_directory,
    _initialize_native_population,
    _shinka_drafts,
)

from lunar_evolution import bundle_evolution, producer_bundle_staging, producer_bundle_transaction
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.evolution import PopulationStrategy
from lunar_evolution.producer_bundle_control import native_producer_bundle_budget_sha256
from lunar_evolution.producer_bundle_transaction import (
    NativeProducerBundleTransactionError,
    run_native_producer_bundle_publication_transaction,
)


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


def _fixture(tmp_path, values=(9,)):
    context = build_context(tmp_path / "native")
    _initialize_native_population(PopulationStrategy(context))
    strategy, drafts, plan, _ = _shinka_drafts(tmp_path, context, values)
    journal_id = "controlled-import"
    _batch_directory(context.workspace, journal_id)
    return context, strategy, drafts, plan, journal_id


def _prefix(context):
    evolution = context.workspace / "evolution"
    return (evolution / "archive.jsonl").read_bytes(), (evolution / "state.json").read_bytes()


def _call(fixture, control, **kwargs):
    context, strategy, drafts, plan, journal_id = fixture
    return run_native_producer_bundle_publication_transaction(
        context.workspace, strategy, drafts, plan, journal_id=journal_id,
        execution_control=control, **kwargs,
    )


def _batch(context, journal_id):
    return context.workspace / "evolution" / "producer-batches" / journal_id


def test_shared_control_policy_is_bound_to_prepared_and_published_journal(tmp_path) -> None:
    fixture = _fixture(tmp_path)
    context, strategy, _drafts, _plan, journal_id = fixture
    control = SolveExecutionControl(30, clock=FakeClock())
    expected = native_producer_bundle_budget_sha256(strategy, control)
    result = _call(fixture, control, budget_sha256=expected)
    assert result.publication_status == "published"
    assert result.journal.budget_sha256 == expected
    assert result.published_journal.budget_sha256 == expected
    prepared = json.loads((_batch(context, journal_id) / "journal.prepared.json").read_bytes())
    assert prepared["budget_sha256"] == expected
    assert context.bundle_pipeline._remaining_timeout is None


def test_wrong_explicit_budget_pin_fails_before_any_draft_side_effect(tmp_path, monkeypatch) -> None:
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)

    def unexpected(*args, **kwargs):
        raise AssertionError("mismatched budget must not evaluate")

    monkeypatch.setattr(context.bundle_pipeline, "evaluate_draft_non_publishing", unexpected)
    with pytest.raises(NativeProducerBundleTransactionError, match="budget_mismatch"):
        _call(fixture, SolveExecutionControl(30, clock=FakeClock()), budget_sha256="0" * 64)
    assert _prefix(context) == before
    assert not (_batch(context, journal_id) / "journal.prepared.json").exists()
    assert not (_batch(context, journal_id) / "native-drafts").exists()


def test_expiry_after_first_draft_does_not_admit_second_or_publish(tmp_path, monkeypatch) -> None:
    fixture = _fixture(tmp_path, values=(9, 8))
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    clock = FakeClock()
    control = SolveExecutionControl(30, clock=clock)
    original = context.bundle_pipeline.evaluate_draft_non_publishing
    evaluated = []

    def expire_after_first(*args, **kwargs):
        evaluated.append(kwargs["ordinal"])
        result = original(*args, **kwargs)
        clock.value = control.deadline
        return result

    monkeypatch.setattr(context.bundle_pipeline, "evaluate_draft_non_publishing", expire_after_first)
    with pytest.raises(SolveExecutionBudgetExceeded):
        _call(fixture, control)
    assert evaluated == [0]
    assert _prefix(context) == before
    assert not (_batch(context, journal_id) / "stage").exists()
    assert context.bundle_pipeline._remaining_timeout is None


def test_cancel_after_stage_never_calls_commit(tmp_path, monkeypatch) -> None:
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    control = SolveExecutionControl(30, clock=FakeClock())
    original_stage = producer_bundle_transaction.stage_producer_bundle_publication

    def stage_then_cancel(*args, **kwargs):
        result = original_stage(*args, **kwargs)
        control.cancel()
        return result

    def unexpected(*args, **kwargs):
        raise AssertionError("cancelled transaction must not commit")

    monkeypatch.setattr(producer_bundle_transaction, "stage_producer_bundle_publication", stage_then_cancel)
    monkeypatch.setattr(producer_bundle_transaction, "commit_producer_bundle_publication", unexpected)
    with pytest.raises(SolveExecutionCancelled):
        _call(fixture, control)
    marker = json.loads((context.workspace / "evolution" / "producer-publication.json").read_bytes())
    assert marker["status"] == "staged"
    assert _prefix(context) == before
    assert not (_batch(context, journal_id) / "terminal.json").exists()


@pytest.mark.parametrize("boundary", ["lock", "verification"])
@pytest.mark.parametrize("reason", ["cancellation", "deadline"])
def test_commit_rechecks_stop_after_lock_and_verification(tmp_path, monkeypatch, boundary, reason) -> None:
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    clock = FakeClock()
    control = SolveExecutionControl(30, clock=clock)
    committing = False
    original_commit = producer_bundle_transaction.commit_producer_bundle_publication

    def mark_commit(*args, **kwargs):
        nonlocal committing
        committing = True
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(producer_bundle_transaction, "commit_producer_bundle_publication", mark_commit)
    if boundary == "lock":
        original_lock = producer_bundle_staging._locked

        @contextmanager
        def cancel_after_lock(*args, **kwargs):
            with original_lock(*args, **kwargs):
                if committing:
                    if reason == "cancellation":
                        control.cancel()
                    else:
                        clock.value = control.deadline
                yield

        monkeypatch.setattr(producer_bundle_staging, "_locked", cancel_after_lock)
    else:
        original_verify = producer_bundle_staging._verify_stage

        def cancel_after_verification(*args, **kwargs):
            result = original_verify(*args, **kwargs)
            if reason == "cancellation":
                control.cancel()
            else:
                clock.value = control.deadline
            return result

        monkeypatch.setattr(producer_bundle_staging, "_verify_stage", cancel_after_verification)
    expected = SolveExecutionCancelled if reason == "cancellation" else SolveExecutionBudgetExceeded
    with pytest.raises(expected):
        _call(fixture, control)
    marker = json.loads((context.workspace / "evolution" / "producer-publication.json").read_bytes())
    assert marker["status"] == "staged"
    assert _prefix(context) == before
    assert not (_batch(context, journal_id) / "terminal.json").exists()


@pytest.mark.parametrize("reason", ["cancellation", "deadline"])
def test_stop_after_staging_lock_does_not_build_stage_or_publication_marker(tmp_path, monkeypatch, reason) -> None:
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    clock = FakeClock()
    control = SolveExecutionControl(30, clock=clock)
    staging = False
    original_stage = producer_bundle_transaction.stage_producer_bundle_publication
    original_lock = producer_bundle_staging._locked

    def mark_stage(*args, **kwargs):
        nonlocal staging
        staging = True
        return original_stage(*args, **kwargs)

    @contextmanager
    def cancel_after_lock(*args, **kwargs):
        with original_lock(*args, **kwargs):
            if staging:
                if reason == "cancellation":
                    control.cancel()
                else:
                    clock.value = control.deadline
            yield

    monkeypatch.setattr(producer_bundle_transaction, "stage_producer_bundle_publication", mark_stage)
    monkeypatch.setattr(producer_bundle_staging, "_locked", cancel_after_lock)
    expected = SolveExecutionCancelled if reason == "cancellation" else SolveExecutionBudgetExceeded
    with pytest.raises(expected):
        _call(fixture, control)
    assert _prefix(context) == before
    assert not (_batch(context, journal_id) / "stage").exists()
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()


@pytest.mark.parametrize("reason", ["deadline", "cancellation"])
def test_commit_critical_region_finishes_without_false_budget_failure(tmp_path, monkeypatch, reason) -> None:
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    clock = FakeClock()
    control = SolveExecutionControl(30, clock=clock)
    original_replace = producer_bundle_staging._replace_existing
    crossed = []

    def expire_after_unknown_marker(path, content, **kwargs):
        result = original_replace(path, content, **kwargs)
        if path.name == "producer-publication.json" and json.loads(content)["status"] == "unknown":
            crossed.append(True)
            if reason == "deadline":
                clock.value = control.deadline
            else:
                control.cancel()
        return result

    monkeypatch.setattr(producer_bundle_staging, "_replace_existing", expire_after_unknown_marker)
    result = _call(fixture, control)
    assert crossed == [True]
    assert result.publication_status == "published"
    assert result.published_journal.state == "published"
    assert json.loads((_batch(context, journal_id) / "terminal.json").read_bytes())["status"] == "published"
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()
    assert context.bundle_pipeline._remaining_timeout is None


def test_same_control_retry_does_not_refresh_expired_deadline(tmp_path, monkeypatch) -> None:
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    clock = FakeClock()
    control = SolveExecutionControl(30, clock=clock)
    original_evaluate = context.bundle_pipeline.evaluate_draft_non_publishing
    evaluated = []

    def record_evaluation(*args, **kwargs):
        evaluated.append(kwargs["ordinal"])
        return original_evaluate(*args, **kwargs)

    def interrupt_before_stage(*args, **kwargs):
        raise RuntimeError("fixture interruption")

    monkeypatch.setattr(context.bundle_pipeline, "evaluate_draft_non_publishing", record_evaluation)
    monkeypatch.setattr(producer_bundle_transaction, "stage_producer_bundle_publication", interrupt_before_stage)
    with pytest.raises(NativeProducerBundleTransactionError, match="recovery_required"):
        _call(fixture, control)
    intent = (_batch(context, journal_id) / "journal.prepared.json").read_bytes()
    clock.value = control.deadline
    with pytest.raises(SolveExecutionBudgetExceeded):
        _call(fixture, control)
    assert evaluated == [0]
    assert (_batch(context, journal_id) / "journal.prepared.json").read_bytes() == intent
    assert _prefix(context) == before
    assert context.bundle_pipeline._remaining_timeout is None


@pytest.mark.parametrize("retain_budget_pin", [True, False])
def test_controlled_intent_cannot_retry_with_wall_clock_removed(tmp_path, monkeypatch, retain_budget_pin) -> None:
    fixture = _fixture(tmp_path)
    context, strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    control = SolveExecutionControl(30, clock=FakeClock())
    budget_pin = native_producer_bundle_budget_sha256(strategy, control)

    def interrupt_before_stage(*args, **kwargs):
        raise RuntimeError("fixture interruption")

    monkeypatch.setattr(producer_bundle_transaction, "stage_producer_bundle_publication", interrupt_before_stage)
    with pytest.raises(NativeProducerBundleTransactionError, match="recovery_required"):
        _call(fixture, control)
    intent = (_batch(context, journal_id) / "journal.prepared.json").read_bytes()

    def unexpected(*args, **kwargs):
        raise AssertionError("removed wall-clock policy must not evaluate or reuse draft evidence")

    monkeypatch.setattr(context.bundle_pipeline, "evaluate_draft_non_publishing", unexpected)
    expected = "budget_mismatch" if retain_budget_pin else "prepared_intent_mismatch"
    with pytest.raises(NativeProducerBundleTransactionError, match=expected):
        _call(fixture, None, **({"budget_sha256": budget_pin} if retain_budget_pin else {}))
    assert (_batch(context, journal_id) / "journal.prepared.json").read_bytes() == intent
    assert _prefix(context) == before
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()


@pytest.mark.parametrize("controlled", [True, False])
def test_changed_pipeline_execution_budget_cannot_reuse_old_policy_pin(tmp_path, monkeypatch, controlled) -> None:
    fixture = _fixture(tmp_path)
    context, strategy, _drafts, _plan, journal_id = fixture
    control = SolveExecutionControl(30, clock=FakeClock()) if controlled else None
    budget_pin = native_producer_bundle_budget_sha256(strategy, control)
    before = _prefix(context)
    pipeline = context.bundle_pipeline
    pipeline.budget = replace(pipeline.budget, max_input_bytes=pipeline.budget.max_input_bytes - 1)

    def unexpected(*args, **kwargs):
        raise AssertionError("changed execution policy must not evaluate")

    monkeypatch.setattr(pipeline, "evaluate_draft_non_publishing", unexpected)
    with pytest.raises(NativeProducerBundleTransactionError, match="budget_mismatch"):
        _call(fixture, control, budget_sha256=budget_pin)
    assert _prefix(context) == before
    assert not (_batch(context, journal_id) / "journal.prepared.json").exists()


@pytest.mark.parametrize("reason", ["cancellation", "deadline"])
def test_contended_publication_lock_stops_without_writing_prepared_intent(tmp_path, reason) -> None:
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    clock = FakeClock()
    waiting = Event()
    outcomes = []

    def observed(stage):
        if stage == "producer_publication_lock":
            waiting.set()

    control = SolveExecutionControl(30, clock=clock, observe_stage=observed)

    def run():
        try:
            outcomes.append(_call(fixture, control))
        except Exception as error:  # noqa: BLE001 - report worker failures in the main test thread
            outcomes.append(error)

    lock_path = context.workspace / "evolution" / "producer-publication.lock"
    with lock_path.open("a+b") as owned_lock:
        fcntl.flock(owned_lock.fileno(), fcntl.LOCK_EX)
        worker = Thread(target=run, daemon=True)
        worker.start()
        try:
            assert waiting.wait(3), "transaction did not reach the held file lock"
            assert worker.is_alive()
            if reason == "cancellation":
                control.cancel()
            else:
                clock.value = control.deadline
            worker.join(3)
            assert not worker.is_alive(), "control must end contention while the lock is still held"
        finally:
            fcntl.flock(owned_lock.fileno(), fcntl.LOCK_UN)
            worker.join(3)
    expected = SolveExecutionCancelled if reason == "cancellation" else SolveExecutionBudgetExceeded
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], expected)
    assert _prefix(context) == before
    assert not (_batch(context, journal_id) / "journal.prepared.json").exists()
    assert not (_batch(context, journal_id) / "native-drafts").exists()


def test_strategy_cancelled_after_input_preparation_propagates_typed_cancellation(tmp_path, monkeypatch) -> None:
    fixture = _fixture(tmp_path)
    context, strategy, _drafts, _plan, journal_id = fixture
    before = _prefix(context)
    cancelled = False
    strategy.context = replace(strategy.context, cancelled=lambda: cancelled)
    original_staging = bundle_evolution.stage_candidate_execution_inputs

    def stage_then_cancel(*args, **kwargs):
        nonlocal cancelled
        staged = original_staging(*args, **kwargs)
        cancelled = True
        return staged

    def unexpected(*args, **kwargs):
        raise AssertionError("cancelled prepared draft must not execute")

    monkeypatch.setattr(bundle_evolution, "stage_candidate_execution_inputs", stage_then_cancel)
    monkeypatch.setattr(bundle_evolution, "run_candidate_execution_recorded", unexpected)
    with pytest.raises(SolveExecutionCancelled) as error:
        _call(fixture, SolveExecutionControl(30, clock=FakeClock()))
    assert error.value.stage == "candidate_execution"
    assert _prefix(context) == before
    assert (_batch(context, journal_id) / "journal.prepared.json").exists()
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()
