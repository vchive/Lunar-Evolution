"""BRS publication over real local owner/channel pins and inert transaction seams."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace

import pytest
from test_rsi_python_admission import OTHER, _files, _rows
from test_rsi_python_admission_flow import _forged_checkpoint_append, _lose_record
from test_rsi_python_admission_owner import (
    _EvaluationBoundary,
    _owner,
    _state,
    _unregistered_publication,
    no_actual_worker_or_evaluator,  # noqa: F401 -- imported autouse fixture
)

from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution import rsi_python_publication as publication
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.rsi_store import RSILedger


def _call(value, **kwargs):
    return publication.run_rsi_python_bundle_publication_for_active_brs_worker(
        value.controller, value.binding.run_id, value.episode_id,
        value.strategy, value.drafts, value.admission_plan,
        native_plan=kwargs.pop("native_plan", value.plan),
        prepared_journal=kwargs.pop("prepared_journal", value.journal),
        expected_anchor_sha256=value.anchor.anchor_sha256, **kwargs,
    )


@contextmanager
def _wave(value):
    # Only the dispatch mode changes in this inert fixture. The original request,
    # producer proof, episode, native claim and deadlines remain independently pinned.
    _forged_checkpoint_append(value, lambda state: state.update(mode="brs"))
    state = _state(value)
    with (
        value.ledger.controller_lock(value.binding.run_id),
        value.controller._python_admission_brs_wave_scope(state, (value.episode_id,)) as wave,
    ):
        yield wave, state


def _drive(value, monkeypatch, operation, *, handler=None):
    """Use a real dispatch token/channel; the existing running fixture skips runner launch."""
    def dispatched(state, episode_id):
        with value.controller._python_admission_brs_worker_scope(state, episode_id):
            return operation()

    monkeypatch.setattr(value.controller, "_execute_intent", dispatched)
    with _wave(value) as (wave, state):
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(value.controller._execute_brs_intent, wave, state, value.episode_id)
            deadline = time.monotonic() + 20
            while not future.done():
                if time.monotonic() >= deadline:
                    pytest.fail("BRS publication owner/worker did not make progress")
                wave.channel.service(
                    handler or (lambda ready: value.controller._python_admission_service_brs_ready(wave, ready)),
                    timeout=0.05,
                    observation_scope=lambda: value.controller._python_admission_brs_service_observations(wave),
                )
            return future.result()
        finally:
            # A failed owner must wake the waiting worker before executor shutdown.
            wave.channel.close()
            pool.shutdown(wait=True)


@pytest.mark.parametrize("scope", ["direct", "drs-owner", "unscoped-worker"])
def test_brs_facade_cannot_borrow_drs_or_direct_authority(tmp_path, monkeypatch, scope):
    value = _unregistered_publication(tmp_path)
    before = _rows(value), _files(value)

    def forbidden(*args, **kwargs):
        pytest.fail("unscoped BRS caller reached the transaction")

    monkeypatch.setattr(publication, "run_native_producer_bundle_publication_transaction", forbidden)
    with pytest.raises(publication.RSIPythonPublicationError, match="owner_context_invalid"):
        if scope == "drs-owner":
            with _owner(value):
                _call(value)
        elif scope == "unscoped-worker":
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(_call, value).result(timeout=5)
        else:
            _call(value)
    assert (_rows(value), _files(value)) == before


@pytest.mark.parametrize("lose_after_ack", [False, True])
def test_actual_prepared_transaction_waits_for_owner_pin_before_inert_evaluation(
    tmp_path, monkeypatch, lose_after_ack,
):
    value = _unregistered_publication(tmp_path)
    original_service = value.controller._python_admission_service_brs_ready
    records, evaluations = [], []
    prepared = (value.batch / "journal.prepared.json").read_bytes()

    def service(wave, ready):
        assert not _rows(value)["rsi_python_admissions"]
        assert (value.batch / "journal.prepared.json").read_bytes() == prepared
        digest = original_service(wave, ready)
        record = value.ledger.python_admission_record(
            value.binding.run_id, value.episode_id, value.journal.journal_id,
            expected_record_sha256=digest,
        )
        records.append(record)
        if lose_after_ack:
            _lose_record(value, record, "missing")
        return digest

    def inert_evaluation(*args, **kwargs):
        assert len(records) == 1
        assert _state(value)["python_admission_refs"][value.episode_id]["record_sha256"] == records[0].record_sha256
        evaluations.append(kwargs["journal_id"])
        raise _EvaluationBoundary()

    monkeypatch.setattr(transaction, "_verify_native_execution_receipt_link", lambda *a, **k: None)
    monkeypatch.setattr(value.controller, "_python_admission_service_brs_ready", service)
    monkeypatch.setattr(value.strategy.context.bundle_pipeline, "evaluate_draft_non_publishing", inert_evaluation)
    error = publication.RSIPythonPublicationError if lose_after_ack else _EvaluationBoundary
    with pytest.raises(error):
        _drive(value, monkeypatch, lambda: _call(value))
    assert len(records) == 1 and records[0].production_admission is False
    assert evaluations == ([] if lose_after_ack else [value.journal.journal_id])
    assert (value.batch / "journal.prepared.json").read_bytes() == prepared
    assert value.gateway.calls == 1
    assert not (value.workspace / "evolution" / "producer-publication.json").exists()


@pytest.mark.parametrize("changed", ["request", "journal", "plan"])
def test_original_message_identity_is_checked_before_ready_or_transaction(tmp_path, monkeypatch, changed):
    value = _unregistered_publication(tmp_path)
    arguments = {}
    if changed == "request":
        request = replace(value.request, environment_sha256=OTHER)
        arguments["native_plan"] = replace(
            value.plan, request=request, request_sha256=request.digest(), plan_sha256=None,
        )
    elif changed == "journal":
        arguments["prepared_journal"] = replace(value.journal, environment_sha256=OTHER, journal_sha256=None)
    else:
        value.admission_plan = replace(value.admission_plan, environment_sha256=OTHER)

    def forbidden(*args, **kwargs):
        pytest.fail("mismatched BRS request reached transaction or owner ready")

    monkeypatch.setattr(publication, "run_native_producer_bundle_publication_transaction", forbidden)
    monkeypatch.setattr(value.controller, "_request_python_admission_for_brs_worker", forbidden)
    with pytest.raises(publication.RSIPythonPublicationError):
        _drive(value, monkeypatch, lambda: _call(value, **arguments))
    assert not _rows(value)["rsi_python_admissions"]


@pytest.mark.parametrize("stop", ["cancel", "deadline", "guard-drift"])
def test_ready_wait_preserves_control_and_revalidates_after_caller_callbacks(tmp_path, monkeypatch, stop):
    clock = {"now": 100.0}
    control = SolveExecutionControl(30, clock=lambda: clock["now"])
    value = _unregistered_publication(tmp_path, execution_control=control)
    callbacks, transaction_calls = [], []

    def guard(stage):
        assert not value.controller._python_admission_brs_observation_lock._is_owned()
        callbacks.append(stage)
        if stop == "cancel":
            control.cancel()
        elif stop == "deadline":
            clock["now"] = control.deadline
        else:
            _forged_checkpoint_append(value, lambda state: state.update(phase="caller-drift"))

    def prepared_transaction(*args, **kwargs):
        transaction_calls.append("prepared")
        kwargs["prepared_observer"](value.journal)
        pytest.fail("stopped ready wait returned admission")

    monkeypatch.setattr(publication, "run_native_producer_bundle_publication_transaction", prepared_transaction)
    error = {"cancel": SolveExecutionCancelled, "deadline": SolveExecutionBudgetExceeded,
             "guard-drift": publication.RSIPythonPublicationError}[stop]
    with pytest.raises(error):
        _drive(value, monkeypatch, lambda: _call(value, execution_control=control, continuation_guard=guard))
    assert transaction_calls == ["prepared"] and callbacks
    assert not _rows(value)["rsi_python_admissions"]


def test_post_ack_evidence_refusal_keeps_durable_reference_and_never_repairs_it(tmp_path, monkeypatch):
    value = _unregistered_publication(tmp_path)
    transaction_result = object()
    refs = []

    def prepared_transaction(*args, **kwargs):
        kwargs["prepared_observer"](value.journal)
        refs.append(deepcopy(_state(value)["python_admission_refs"]))
        anchor = value.batch / "python-producer-admission-anchor.json"
        anchor.write_bytes(anchor.read_bytes() + b"\n")
        return transaction_result

    monkeypatch.setattr(publication, "run_native_producer_bundle_publication_transaction", prepared_transaction)
    with pytest.raises(publication.RSIPythonPublicationError):
        _drive(value, monkeypatch, lambda: _call(value))
    assert len(_rows(value)["rsi_python_admissions"]) == 1
    assert _state(value)["python_admission_refs"] == refs[0]
    retained = _rows(value), _files(value)
    with pytest.raises(publication.RSIPythonPublicationError, match="owner_context_invalid"):
        _call(value)
    assert (_rows(value), _files(value)) == retained


@pytest.mark.parametrize("observer", ["omitted", "wrong-journal", "replayed"])
def test_prepared_observer_cannot_be_skipped_replaced_or_replayed(tmp_path, monkeypatch, observer):
    value = _unregistered_publication(tmp_path)

    def prepared_transaction(*args, **kwargs):
        if observer == "wrong-journal":
            kwargs["prepared_observer"](replace(value.journal, budget_sha256=OTHER, journal_sha256=None))
        elif observer == "replayed":
            kwargs["prepared_observer"](value.journal)
            kwargs["prepared_observer"](value.journal)
        return object()

    monkeypatch.setattr(publication, "run_native_producer_bundle_publication_transaction", prepared_transaction)
    with pytest.raises(publication.RSIPythonPublicationError, match={
        "omitted": "admission_missing", "wrong-journal": "prepared_journal_mismatch",
        "replayed": "prepared_observer_replayed",
    }[observer]):
        _drive(value, monkeypatch, lambda: _call(value))
    assert len(_rows(value)["rsi_python_admissions"]) == (1 if observer == "replayed" else 0)


@pytest.mark.parametrize("failure", ["deadline", "timeout", "os-error"])
def test_owner_lock_releases_without_reclassifying_body_timeouts_or_os_errors(tmp_path, failure):
    ledger = RSILedger(tmp_path / "owner.sqlite3")
    if failure == "deadline":
        error = SolveExecutionBudgetExceeded("brs_wait", started_at=1, deadline=2, observed_at=2)
    elif failure == "timeout":
        error = TimeoutError("inert-original-timeout")
    else:
        error = OSError("inert-provider-error")
    with pytest.raises(type(error)) as caught, ledger.controller_lock("run-1"):
        assert ledger.controller_lock_held("run-1")
        raise error
    assert caught.value is error
    assert not ledger.controller_lock_held("run-1")
    with ledger.controller_lock("run-1"):
        assert ledger.controller_lock_held("run-1")
