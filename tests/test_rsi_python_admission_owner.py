"""Owning DRS thread pins inert prepared evidence without adopting unrelated state."""

from __future__ import annotations

import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy

import pytest
from test_rsi_python_admission import DIGEST, _files, _rows, _setup
from test_rsi_python_admission_flow import _forged_checkpoint_append, _lose_record, _reference
from test_rsi_python_publication import _fixture as _publication_fixture

from lunar_evolution import bundle_evolution, producer_process
from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution import rsi_python_publication as publication
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.producer_bundle_deadline import persist_controlled_producer_bundle_intent
from lunar_evolution.rsi_gateway import SolverResult
from lunar_evolution.rsi_learning import PracticeEpisode, RSILearningError


class _EvaluationBoundary(BaseException):
    """Stop an inert transaction after its first-pin obligation is acknowledged."""


@pytest.fixture(autouse=True)
def no_actual_worker_or_evaluator(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("owner evidence fixture invoked an actual worker or evaluator")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(producer_process, "run_producer_process", forbidden)
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", forbidden)
    monkeypatch.setattr(
        bundle_evolution.MultiFileCandidatePipeline, "evaluate_draft_non_publishing", forbidden,
    )


def _state(value):
    return value.ledger.controller_checkpoint(value.binding.run_id)[1]


@contextmanager
def _owner(value, state=None):
    state = _state(value) if state is None else state
    with (
        value.ledger.controller_lock(value.binding.run_id),
        value.controller._python_admission_flow_scope(state, value.episode_id),
    ):
        yield state


def _pin(value):
    return value.controller._pin_python_admission_for_active_flow(
        value.binding.run_id, value.episode_id, native_plan=value.plan,
        prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
    )


def _public_pin(value):
    return value.controller.pin_python_admission(
        value.binding.run_id, value.episode_id, native_plan=value.plan,
        prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
    )


def _unchanged_refusal(value, operation, *, match="rsi_python_admission_"):
    rows, files, calls = _rows(value), _files(value), value.gateway.calls
    with pytest.raises(RSILearningError, match=match):
        operation()
    assert (_rows(value), _files(value), value.gateway.calls) == (rows, files, calls)


def _first_publication(value, **kwargs):
    return publication.run_rsi_python_bundle_publication_for_active_flow(
        value.controller, value.binding.run_id, value.episode_id,
        value.strategy, value.drafts, value.admission_plan,
        native_plan=value.plan, prepared_journal=value.journal,
        expected_anchor_sha256=value.anchor.anchor_sha256, **kwargs,
    )


def _unregistered_publication(tmp_path, *, execution_control=None):
    value = _publication_fixture(
        tmp_path, strategy=True, pin=False, complete_transaction=True,
        execution_control=execution_control,
    )
    # The older fixture deliberately exercises explicit registration. This local fixture
    # removes that row before observing the first-pin path; it never removes a reference.
    _lose_record(value, value.record, "missing")
    assert _rows(value)["rsi_python_admissions"] == []
    assert "python_admission_refs" not in _state(value)
    if execution_control is not None:
        # The older fixture writes only a raw prepared intent. A controlled attempt
        # must retain its deadline before the prepared intent, before any first pin.
        prepared = value.batch / "journal.prepared.json"
        original = prepared.read_bytes()
        prepared.unlink()
        persist_controlled_producer_bundle_intent(
            value.workspace, value.journal, execution_control, checkpoint=lambda stage: None,
        )
        assert prepared.read_bytes() == original
    return value


def test_owner_first_pin_acknowledges_only_the_exact_reference_and_replays_readonly(tmp_path):
    value = _setup(tmp_path)
    original_state = deepcopy(_state(value))
    original_rows, original_files = _rows(value), _files(value)
    with _owner(value) as state:
        active, old_head = value.controller._python_admission_active_flow(
            value.binding.run_id, value.episode_id,
        )
        assert active is state
        assert old_head == value.ledger.controller_checkpoint(value.binding.run_id)[0]
        record = _pin(value)
        expected = deepcopy(original_state)
        expected["python_admission_refs"] = {value.episode_id: _reference(value, record)}
        assert state == expected
        assert value.ledger.controller_checkpoint(value.binding.run_id)[1] == expected
        active, pinned_head = value.controller._python_admission_active_flow(
            value.binding.run_id, value.episode_id,
        )
        assert active is state and pinned_head != old_head
        pinned_rows, pinned_files = _rows(value), _files(value)
        assert _pin(value) == record
        assert (_rows(value), _files(value)) == (pinned_rows, pinned_files)
        for table in original_rows:
            if table not in {"rsi_python_admissions", "rsi_controller_journal"}:
                assert pinned_rows[table] == original_rows[table]
    assert _files(value) == original_files
    assert record.production_admission is False and value.gateway.calls == 1
    _unchanged_refusal(value, lambda: _pin(value), match="flow_missing")


@pytest.mark.parametrize("context", ["absent", "without-lock", "brs", "unbound"])
def test_first_pin_requires_the_original_owning_drs_context(tmp_path, context):
    value = _setup(tmp_path)
    state = _state(value)
    if context == "absent":
        _unchanged_refusal(value, lambda: _pin(value), match="flow_missing")
        return
    if context == "brs":
        state["mode"] = "brs"
    elif context == "unbound":
        value.controller.producer_sidecar = None
    if context == "without-lock":
        with value.controller._python_admission_flow_scope(state, value.episode_id):
            _unchanged_refusal(value, lambda: _pin(value), match="flow_missing")
    else:
        with _owner(value, state):
            _unchanged_refusal(value, lambda: _pin(value), match="flow_missing")


def test_worker_thread_cannot_borrow_the_waiting_parent_owner_scope(tmp_path):
    value = _setup(tmp_path)
    with _owner(value):
        with ThreadPoolExecutor(max_workers=1) as pool:
            _unchanged_refusal(
                value, lambda: pool.submit(_pin, value).result(timeout=5), match="flow_missing",
            )
        assert _pin(value).production_admission is False


def test_scope_restores_the_outer_owner_and_cleans_up_after_an_exception(tmp_path):
    value = _setup(tmp_path)
    state = _state(value)
    with _owner(value, state):
        with (
            pytest.raises(RuntimeError, match="inert-inner-scope"),
            value.controller._python_admission_flow_scope(state, value.episode_id),
        ):
            raise RuntimeError("inert-inner-scope")
        assert value.controller._python_admission_active_flow(
            value.binding.run_id, value.episode_id,
        )[0] is state
        _pin(value)
    _unchanged_refusal(value, lambda: _pin(value), match="flow_missing")


@pytest.mark.parametrize("mutation", ["episode", "memory", "durable-head"])
def test_changed_owner_state_or_checkpoint_is_refused_without_adoption(tmp_path, mutation):
    value = _setup(tmp_path)
    with _owner(value) as state:
        if mutation == "episode":
            state["current_episode_id"] = "foreign-episode"
        elif mutation == "memory":
            state["phase"] = "unrelated-memory-change"
        else:
            _forged_checkpoint_append(value, lambda durable: durable.update(phase="unrelated-durable-change"))
        retained_state = deepcopy(state)
        _unchanged_refusal(value, lambda: _pin(value), match="flow_")
        assert state == retained_state and not _rows(value)["rsi_python_admissions"]


def test_scope_does_not_adopt_a_new_checkpoint_written_by_the_public_pin(tmp_path):
    value = _setup(tmp_path)
    with _owner(value) as state:
        original = deepcopy(state)
        record = _public_pin(value)
        assert value.ledger.controller_checkpoint(value.binding.run_id)[1]["python_admission_refs"] == {
            value.episode_id: _reference(value, record),
        }
        _unchanged_refusal(value, lambda: _pin(value), match="flow_stale")
        assert state == original


def test_original_checkpoint_cas_survives_a_change_after_the_last_evidence_read(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    original_pin = value.ledger.pin_python_admission_record
    attempts = []

    def pin_after_drift(record, **kwargs):
        attempts.append(kwargs["expected_checkpoint_sha256"])
        _forged_checkpoint_append(value, lambda durable: durable.update(phase="inert-cas-race"))
        return original_pin(record, **kwargs)

    with _owner(value) as state:
        before = deepcopy(state)
        old_head = value.ledger.controller_checkpoint(value.binding.run_id)[0]
        monkeypatch.setattr(value.ledger, "pin_python_admission_record", pin_after_drift)
        with pytest.raises(RSILearningError, match="conflict"):
            _pin(value)
        assert attempts == [old_head]
        assert state == before and not _rows(value)["rsi_python_admissions"]
        assert "python_admission_refs" not in _state(value)
        assert _state(value)["phase"] == "inert-cas-race"


@pytest.mark.parametrize("interruption", ["return-lost", "unrelated-ack-head"])
def test_durable_pin_before_ack_failure_keeps_the_obligation_and_leaves_old_state_stale(
    tmp_path, monkeypatch, interruption,
):
    value = _setup(tmp_path)
    original_pin = value.ledger.pin_python_admission_record
    committed = []

    def pin_then_interrupt(record, **kwargs):
        result = original_pin(record, **kwargs)
        committed.append(result)
        if interruption == "return-lost":
            raise RSILearningError("fixture_pin_return_unknown")
        _forged_checkpoint_append(value, lambda durable: durable.update(phase="inert-after-pin-drift"))
        return result

    with _owner(value) as state:
        before = deepcopy(state)
        with monkeypatch.context() as patch:
            patch.setattr(value.ledger, "pin_python_admission_record", pin_then_interrupt)
            with pytest.raises(RSILearningError):
                _pin(value)
        record, _ = committed[0]
        assert state == before
        assert _state(value)["python_admission_refs"] == {value.episode_id: _reference(value, record)}
        assert len(_rows(value)["rsi_python_admissions"]) == 1
        _unchanged_refusal(value, lambda: _pin(value), match="flow_stale")
    if interruption == "return-lost":
        rows, files = _rows(value), _files(value)
        with _owner(value):
            assert _pin(value) == record
        assert (_rows(value), _files(value)) == (rows, files)


def test_missing_required_row_is_never_recreated_on_owner_replay(tmp_path):
    value = _setup(tmp_path)
    with _owner(value) as state:
        record = _pin(value)
        _lose_record(value, record, "missing")
        before = deepcopy(state)
        _unchanged_refusal(value, lambda: _pin(value))
        assert state == before and not _rows(value)["rsi_python_admissions"]


@pytest.mark.parametrize("already_pinned", [False, True])
def test_original_anchor_drift_before_or_after_pin_refuses_without_new_effects(tmp_path, already_pinned):
    value = _setup(tmp_path)
    with _owner(value) as state:
        if already_pinned:
            _pin(value)
        anchor = value.batch / "python-producer-admission-anchor.json"
        anchor.write_bytes(anchor.read_bytes() + b"\n# inert drift\n")
        before = deepcopy(state)
        _unchanged_refusal(value, lambda: _pin(value))
        assert state == before


@pytest.mark.parametrize("lose_after_pin", [False, True])
def test_actual_prepared_transaction_installs_first_pin_before_the_evaluator_boundary(
    tmp_path, monkeypatch, lose_after_pin,
):
    value = _unregistered_publication(tmp_path)
    original_pin = value.controller._pin_python_admission_for_active_flow
    pin_records, evaluator_boundaries = [], []
    prepared_bytes = (value.batch / "journal.prepared.json").read_bytes()

    def pin_at_prepared(run_id, episode_id, **kwargs):
        assert (value.batch / "journal.prepared.json").read_bytes() == prepared_bytes
        assert kwargs["prepared_journal"] == value.journal
        assert not _rows(value)["rsi_python_admissions"]
        assert value.ledger.inspect_native_episode_claim(
            value.request, plan_sha256=value.plan.plan_sha256,
        ).status == "started"
        record = original_pin(run_id, episode_id, **kwargs)
        pin_records.append(record)
        if lose_after_pin:
            _lose_record(value, record, "missing")
        return record

    def inert_evaluation(*args, **kwargs):
        evaluator_boundaries.append(kwargs["journal_id"])
        assert len(pin_records) == 1
        assert _state(value)["python_admission_refs"][value.episode_id]["record_sha256"] == pin_records[0].record_sha256
        raise _EvaluationBoundary()

    # Only native process receipt validation and the actual evaluator are inert seams;
    # prepared intent/handoff/anchor, controller pin, checkpoint CAS and evidence gates run.
    monkeypatch.setattr(transaction, "_verify_native_execution_receipt_link", lambda *a, **k: None)
    monkeypatch.setattr(value.controller, "_pin_python_admission_for_active_flow", pin_at_prepared)
    monkeypatch.setattr(value.strategy.context.bundle_pipeline, "evaluate_draft_non_publishing", inert_evaluation)
    with _owner(value) as state:
        original = deepcopy(state)
        expected_error = publication.RSIPythonPublicationError if lose_after_pin else _EvaluationBoundary
        with pytest.raises(expected_error):
            _first_publication(value)
        assert len(pin_records) == 1
        expected = deepcopy(original)
        expected["python_admission_refs"] = {value.episode_id: _reference(value, pin_records[0])}
        assert state == expected
    assert evaluator_boundaries == ([] if lose_after_pin else [value.journal.journal_id])
    assert (value.batch / "journal.prepared.json").read_bytes() == prepared_bytes
    assert not (value.workspace / "evolution" / "producer-publication.json").exists()
    assert value.gateway.calls == 1


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_prepared_first_pin_callback_stop_preserves_pin_and_never_enters_evaluation(tmp_path, monkeypatch, stop):
    clock = {"now": 100.0}
    control = SolveExecutionControl(30.0, clock=lambda: clock["now"])
    value = _unregistered_publication(tmp_path, execution_control=control)
    original_pin = value.controller._pin_python_admission_for_active_flow
    records = []

    def pin_then_stop(*args, **kwargs):
        record = original_pin(*args, **kwargs)
        records.append(record)
        if stop == "cancel":
            control.cancel()
        else:
            clock["now"] = control.deadline
        return record

    monkeypatch.setattr(transaction, "_verify_native_execution_receipt_link", lambda *a, **k: None)
    monkeypatch.setattr(value.controller, "_pin_python_admission_for_active_flow", pin_then_stop)
    with _owner(value) as state:
        before = deepcopy(state)
        with pytest.raises(SolveExecutionCancelled if stop == "cancel" else SolveExecutionBudgetExceeded):
            _first_publication(value, execution_control=control)
        assert len(records) == 1
        before["python_admission_refs"] = {value.episode_id: _reference(value, records[0])}
        assert state == before
        assert _state(value) == before and len(_rows(value)["rsi_python_admissions"]) == 1
    assert not (value.workspace / "evolution" / "producer-publication.json").exists()
    assert value.gateway.calls == 1


def test_fresh_controller_dispatch_exposes_owner_scope_and_keeps_acknowledged_obligation(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    # The original inert gateway interrupted after its running record. Remove only that
    # fixture episode so the genuine runner must dispatch freshly under the same intent.
    with sqlite3.connect(value.ledger.database) as connection:
        connection.execute("DELETE FROM rsi_records WHERE logical_id=?", (value.episode_id,))
    state = _state(value)
    before = deepcopy(state)
    records = []

    def inert_provider(request):
        assert request == value.request
        active, _ = value.controller._python_admission_active_flow(value.binding.run_id, value.episode_id)
        assert active is state
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.inspect_native_episode_claim(
            request, plan_sha256=value.plan.plan_sha256,
        ).status == "started"
        records.append(_pin(value))
        raise _EvaluationBoundary()

    monkeypatch.setattr(value.gateway, "run", inert_provider)
    with value.ledger.controller_lock(value.binding.run_id):
        with pytest.raises(_EvaluationBoundary):
            value.controller._execute_intent(state, value.episode_id)
        assert len(records) == 1
        before["python_admission_refs"] = {value.episode_id: _reference(value, records[0])}
        assert state == before and _state(value) == before
        # The acknowledged state remains usable by the existing save/resume gate.
        value.controller._save_flow(value.ledger.get_run(value.binding.run_id), state)
        assert _state(value) == before
        _unchanged_refusal(value, lambda: _pin(value), match="flow_missing")


def test_fresh_provider_facade_pin_survives_native_result_episode_settlement_and_flow_save(tmp_path, monkeypatch):
    value = _unregistered_publication(tmp_path)
    with sqlite3.connect(value.ledger.database) as connection:
        connection.execute("DELETE FROM rsi_records WHERE logical_id=?", (value.episode_id,))
    state = _state(value)
    episode = PracticeEpisode.from_dict(state["intents"][value.episode_id]["episode"])
    original_head = value.ledger.controller_checkpoint(value.binding.run_id)[0]
    transaction_result = object()
    events = []
    result = SolverResult(
        episode_id=value.episode_id, request_sha256=value.request.digest(), status="completed",
        candidate_receipt_sha256=DIGEST, execution_receipt_sha256=DIGEST,
        official_evaluation_receipt_sha256=DIGEST, trace_digest=DIGEST,
        terminal_reason="inert-owner-settlement-fixture",
    )

    def prepared_transaction(*args, **kwargs):
        # Actual prepared file, handoff/anchor, facade, owner acknowledgement and
        # ledger run here. This seam returns no executed candidate or publication.
        assert kwargs["journal_id"] == value.journal.journal_id
        assert "python_admission_refs" not in state
        assert value.ledger.inspect_native_episode_claim(
            value.request, plan_sha256=value.plan.plan_sha256,
        ).status == "started"
        events.append("prepared")
        kwargs["prepared_observer"](value.journal)
        assert state["python_admission_refs"] == _state(value)["python_admission_refs"]
        assert value.ledger.controller_checkpoint(value.binding.run_id)[0] != original_head
        events.append("pin")
        kwargs["evidence_revalidator"]("inert_transaction_return")
        return transaction_result

    def inert_provider(request):
        # _NoSolverGateway is an in-process fixture, not NativeRSISolverGateway.
        assert request == value.request
        assert value.controller._python_admission_active_flow(
            value.binding.run_id, value.episode_id,
        )[0] is state
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert _first_publication(value) is transaction_result
        assert events == ["prepared", "pin"]
        claim = value.ledger.publish_native_episode_result(
            request, plan_sha256=value.plan.plan_sha256,
            result=result, expected_claim=value.claim,
        )
        assert claim.status == "completed"
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert state["python_admission_refs"] == _state(value)["python_admission_refs"]
        events.append("native_terminal")
        return result

    monkeypatch.setattr(publication, "run_native_producer_bundle_publication_transaction", prepared_transaction)
    monkeypatch.setattr(value.gateway, "run", inert_provider)
    with value.ledger.controller_lock(value.binding.run_id):
        execution = value.controller._flow_episode(
            value.ledger.get_run(value.binding.run_id), state, episode, value.request,
        )
        assert execution.result == result and execution.passed
        assert value.ledger.episode_result(value.episode_id) == (value.request, result)
        assert value.ledger.get_episode(value.episode_id).state == "completed"
        assert state["phase"] == "evaluated" and state == _state(value)
        assert state["executions"][value.episode_id]["result"] == result.to_dict()
        assert len(_rows(value)["rsi_python_admissions"]) == 1
        assert value.episode_id in state["python_admission_refs"]
        events.append("flow_saved")
        retained = deepcopy(state)
        value.controller._save_flow(value.ledger.get_run(value.binding.run_id), state)
        assert state == _state(value) == retained
        _unchanged_refusal(value, lambda: _pin(value), match="flow_missing")
    assert events == ["prepared", "pin", "native_terminal", "flow_saved"]
    assert not (value.workspace / "evolution" / "producer-publication.json").exists()
