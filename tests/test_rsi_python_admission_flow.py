"""Explicit durable late-admission obligations over inert local RSI evidence."""

from __future__ import annotations

import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace

import pytest
from test_rsi_python_admission import (
    DIGEST,
    OTHER,
    _assert_no_effect,
    _checkpoint_change,
    _files,
    _register,
    _rows,
    _run_state,
    _setup,
)

from lunar_evolution import RSILearningController, RSILearningError, RSILedger
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_callbacks import DurableCallbackJournal
from lunar_evolution.rsi_gateway import SolverResult
from lunar_evolution.rsi_learning import PracticeEpisode, VerifierCheck, VerifierDecision


def _pin(value):
    return value.controller.pin_python_admission(
        value.binding.run_id, value.episode_id, native_plan=value.plan,
        prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
    )


def _reference(value, record):
    return {
        "journal_id": record.journal_id, "attempt_id": record.attempt_id,
        "record_sha256": record.record_sha256, "native_plan": value.plan.to_dict(),
        "prepared_journal": value.journal.to_dict(),
    }


def _fresh_controller(value):
    return RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.workspace,
    )


def _forbid_effects(monkeypatch, controller):
    def forbidden(*args, **kwargs):
        pytest.fail("admission refusal reached callback, verification or usage accounting")

    for name in ("_invoke_callback", "_verify_episode", "_usage_replay_marker"):
        monkeypatch.setattr(controller, name, forbidden)


def _inactive(value, resource, *, status="unknown"):
    if resource == "run":
        _run_state(value, status)
    elif resource == "episode":
        head = value.ledger.get_episode(value.episode_id)
        terminal = PracticeEpisode.from_dict(head.payload).transition(
            status, terminal_reason="inert-fixture-terminal",
        )
        value.ledger.append_episode_record(terminal, expected_record_sha256=head.record_sha256)
    else:
        result = SolverResult(
            episode_id=value.episode_id, request_sha256=value.request.digest(), status=status,
            candidate_receipt_sha256=None, execution_receipt_sha256=None,
            official_evaluation_receipt_sha256=None, trace_digest=DIGEST,
            terminal_reason="inert-fixture-terminal",
        )
        value.ledger.publish_native_episode_result(
            value.request, plan_sha256=value.plan.plan_sha256, result=result,
            expected_claim=value.claim,
        )


def _lose_record(value, record, mutation):
    with sqlite3.connect(value.ledger.database) as connection:
        if mutation == "missing":
            connection.execute("DELETE FROM rsi_python_admissions WHERE run_id=?", (value.binding.run_id,))
        else:
            # This replacement is internally canonical and self-consistent.  The
            # checkpoint's independently retained identity must still reject it.
            changed = replace(record, native_plan_sha256=OTHER, record_sha256=None)
            changed = replace(changed, record_sha256=changed.digest())
            assert changed.record_sha256 != record.record_sha256
            connection.execute(
                "UPDATE rsi_python_admissions SET payload=?,record_sha256=? WHERE run_id=?",
                (changed.to_json().decode("utf-8"), changed.record_sha256, value.binding.run_id),
            )


def _mutate_reference(value, state, mutation):
    if mutation == "delete":
        del state["python_admission_refs"]
    elif mutation == "replace":
        state["python_admission_refs"][value.episode_id]["record_sha256"] = OTHER
    else:
        reference = state["python_admission_refs"].pop(value.episode_id)
        state["python_admission_refs"]["foreign-episode"] = reference


def _forged_checkpoint_append(value, mutate):
    """Bypass the writer but retain a completely valid checkpoint hash chain."""
    current, state = value.ledger.controller_checkpoint(value.binding.run_id)
    state = deepcopy(state)
    mutate(state)
    with sqlite3.connect(value.ledger.database) as connection:
        revision = connection.execute(
            "SELECT MAX(revision) FROM rsi_controller_journal WHERE run_id=?",
            (value.binding.run_id,),
        ).fetchone()[0] + 1
        digest = value.ledger._checkpoint_digest(value.binding.run_id, revision, current, state)
        connection.execute(
            "INSERT INTO rsi_controller_journal VALUES (?, ?, ?, ?, ?)",
            (value.binding.run_id, revision, current, json.dumps(state, sort_keys=True), digest),
        )
    return digest


def test_first_pin_atomically_adds_only_row_and_original_wire_reference(tmp_path):
    value = _setup(tmp_path)
    rows, files = _rows(value), _files(value)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    before = deepcopy(history[-1][1])
    run_history = value.ledger.history(value.binding.run_id)
    record = _pin(value)
    after = value.ledger.controller_checkpoint_history(value.binding.run_id)
    expected = deepcopy(before)
    expected["python_admission_refs"] = {value.episode_id: _reference(value, record)}
    assert len(after) == len(history) + 1
    assert after[:-1] == history
    assert after[-1][1] == expected
    assert record.production_admission is False
    assert record.original_run_request_sha256 == run_history[0].request_sha256
    assert value.ledger.history(value.binding.run_id) == run_history
    changed = _rows(value)
    assert set(changed) == set(rows)
    for table in rows:
        if table not in {"rsi_python_admissions", "rsi_controller_journal"}:
            assert changed[table] == rows[table]
    assert len(changed["rsi_python_admissions"]) == len(rows["rsi_python_admissions"]) + 1
    assert _files(value) == files
    assert canonical_json(after[-1][1]["python_admission_refs"][value.episode_id]["native_plan"]) == canonical_json(value.plan.to_dict())
    assert value.gateway.calls == 1


def test_exact_pin_replay_preserves_timestamps_checkpoint_and_all_files(tmp_path):
    value = _setup(tmp_path)
    record = _pin(value)
    rows, files = _rows(value), _files(value)
    assert _pin(value) == record
    assert _rows(value) == rows
    assert _files(value) == files
    assert value.gateway.calls == 1


def test_legacy_registration_remains_checkpoint_neutral_then_explicit_pin_adds_obligation(tmp_path):
    value = _setup(tmp_path)
    checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)
    record = _register(value)
    assert value.ledger.controller_checkpoint(value.binding.run_id) == checkpoint
    assert "python_admission_refs" not in checkpoint[1]
    rows = _rows(value)
    assert _pin(value) == record
    assert _rows(value)["rsi_python_admissions"] == rows["rsi_python_admissions"]
    assert value.ledger.controller_checkpoint(value.binding.run_id)[1]["python_admission_refs"] == {
        value.episode_id: _reference(value, record),
    }


@pytest.mark.parametrize("window", ["checkpoint-insert", "before-commit"])
def test_pin_transaction_rolls_back_row_and_checkpoint_together(tmp_path, monkeypatch, window):
    value = _setup(tmp_path)
    original = value.ledger._connect
    observed = []

    class InterruptedConnection:
        def __init__(self, connection):
            self.connection = connection
            self.row_inserted = False
            self.checkpoint_inserted = False

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, kind, error, traceback):
            if kind is None and window == "before-commit" and self.checkpoint_inserted:
                observed.append(window)
                failure = RSILearningError("fixture_pin_transaction_interrupted")
                self.connection.__exit__(type(failure), failure, failure.__traceback__)
                raise failure
            return self.connection.__exit__(kind, error, traceback)

        def execute(self, sql, *args, **kwargs):
            normalized = " ".join(sql.upper().split())
            if normalized.startswith("INSERT INTO RSI_CONTROLLER_JOURNAL") and self.row_inserted:
                assert self.connection.execute("SELECT COUNT(*) FROM rsi_python_admissions").fetchone()[0] == 1
                if window == "checkpoint-insert":
                    observed.append(window)
                    raise RSILearningError("fixture_pin_transaction_interrupted")
                self.checkpoint_inserted = True
            result = self.connection.execute(sql, *args, **kwargs)
            if normalized.startswith("INSERT INTO RSI_PYTHON_ADMISSIONS"):
                self.row_inserted = True
            return result

        def __getattr__(self, name):
            return getattr(self.connection, name)

    with monkeypatch.context() as patch:
        patch.setattr(value.ledger, "_connect", lambda: InterruptedConnection(original()))
        _assert_no_effect(value, lambda: _pin(value), match="fixture_pin_transaction_interrupted")
    assert observed == [window]
    assert not _rows(value)["rsi_python_admissions"]
    assert "python_admission_refs" not in value.ledger.controller_checkpoint(value.binding.run_id)[1]


def test_unknown_return_after_pin_commit_keeps_both_identities_and_replays_read_only(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    original = value.ledger.pin_python_admission_record
    retained = {}

    def interrupted(record, **kwargs):
        retained["result"] = original(record, **kwargs)
        raise RSILearningError("fixture_pin_return_unknown")

    with monkeypatch.context() as patch:
        patch.setattr(value.ledger, "pin_python_admission_record", interrupted)
        with pytest.raises(RSILearningError, match="fixture_pin_return_unknown"):
            _pin(value)
    record, digest = retained["result"]
    checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)
    assert checkpoint[0] == digest
    assert checkpoint[1]["python_admission_refs"][value.episode_id] == _reference(value, record)
    rows, files = _rows(value), _files(value)
    assert _pin(value) == record
    assert _rows(value) == rows
    assert _files(value) == files


@pytest.mark.parametrize("head", ["run", "checkpoint", "episode"])
def test_ledger_pin_requires_all_three_original_compare_and_swap_heads(tmp_path, head):
    value = _setup(tmp_path)
    record = _register(value)
    arguments = {
        "expected_run_record_sha256": value.ledger.get_run(value.binding.run_id).record_sha256,
        "expected_checkpoint_sha256": value.ledger.controller_checkpoint(value.binding.run_id)[0],
        "expected_episode_record_sha256": value.ledger.get_episode(value.episode_id).record_sha256,
    }
    arguments["expected_" + head + ("_sha256" if head == "checkpoint" else "_record_sha256")] = OTHER
    with value.ledger.controller_lock(value.binding.run_id):
        _assert_no_effect(value, lambda: value.ledger.pin_python_admission_record(
            record, reference=_reference(value, record), **arguments,
        ), match="conflict")


def test_foreign_controller_lock_refuses_first_pin(tmp_path):
    value = _setup(tmp_path)
    foreign = RSILedger(value.ledger.database)
    with foreign.controller_lock(value.binding.run_id):
        _assert_no_effect(value, lambda: _pin(value), match="^rsi_controller_busy$")


def test_current_thread_lock_reuses_exact_pinned_identity(tmp_path):
    value = _setup(tmp_path)
    record = _pin(value)
    rows, files = _rows(value), _files(value)
    with value.ledger.controller_lock(value.binding.run_id):
        assert _pin(value) == record
        assert value.ledger.controller_lock_held(value.binding.run_id)
    assert _rows(value) == rows
    assert _files(value) == files


def test_worker_reference_validation_is_read_only_under_parent_controller_lock(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    _pin(value)
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    controller = _fresh_controller(value)
    _forbid_effects(monkeypatch, controller)
    with value.ledger.controller_lock(value.binding.run_id), ThreadPoolExecutor(max_workers=1) as pool:
        rows, files = _rows(value), _files(value)
        assert pool.submit(
            controller._validate_producer_checkpoint, value.binding.run_id, state,
        ).result(timeout=30) is None
        assert value.ledger.controller_lock_held(value.binding.run_id)
        assert _rows(value) == rows
        assert _files(value) == files
    assert value.gateway.calls == 1


def test_worker_validation_under_parent_lock_still_refuses_original_anchor_drift(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    _pin(value)
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    anchor = value.batch / "python-producer-admission-anchor.json"
    anchor.unlink()
    controller = _fresh_controller(value)
    _forbid_effects(monkeypatch, controller)
    with value.ledger.controller_lock(value.binding.run_id), ThreadPoolExecutor(max_workers=1) as pool:
        _assert_no_effect(value, lambda: pool.submit(
            controller._validate_producer_checkpoint, value.binding.run_id, state,
        ).result(timeout=30), match="^rsi_python_admission_evidence_invalid$")
        assert value.ledger.controller_lock_held(value.binding.run_id)
    assert not anchor.exists()


@pytest.mark.parametrize("resource", ["run", "episode", "native-result"])
@pytest.mark.parametrize("registered", [False, True], ids=["missing-row", "row-without-reference"])
def test_inactive_attempt_cannot_first_pin_even_when_row_already_registered(tmp_path, resource, registered):
    value = _setup(tmp_path)
    if registered:
        _register(value)
    _inactive(value, resource)
    _assert_no_effect(value, lambda: _pin(value), match="^rsi_python_admission_")
    assert "python_admission_refs" not in value.ledger.controller_checkpoint(value.binding.run_id)[1]


@pytest.mark.parametrize("resource", ["run", "episode", "native-result"])
@pytest.mark.parametrize("status", ["failed", "unknown"])
def test_exact_reference_and_row_replay_remains_read_only_after_attempt_inactive(tmp_path, resource, status):
    value = _setup(tmp_path)
    record = _pin(value)
    _inactive(value, resource, status=status)
    rows, files = _rows(value), _files(value)
    assert _pin(value) == record
    assert _rows(value) == rows
    assert _files(value) == files
    assert value.gateway.calls == 1


@pytest.mark.parametrize("status", ["running", "completed", "unknown"])
@pytest.mark.parametrize("mutation", ["missing", "replacement"])
def test_fresh_resume_requires_original_row_before_any_effect(tmp_path, monkeypatch, status, mutation):
    value = _setup(tmp_path)
    record = _pin(value)
    if status != "running":
        _run_state(value, status)
    _lose_record(value, record, mutation)
    controller = _fresh_controller(value)
    _forbid_effects(monkeypatch, controller)
    _assert_no_effect(value, lambda: controller.resume(value.binding.run_id), match="^rsi_python_admission_")
    # Explicit pin is not a repair route for a once-required row.
    _assert_no_effect(value, lambda: _pin(value), match="^rsi_python_admission_")


@pytest.mark.parametrize("mutation", ["delete", "replace", "reattribute"])
@pytest.mark.parametrize("boundary", ["generic-writer", "forged-append"])
def test_hash_valid_checkpoint_append_cannot_erase_or_change_required_reference(tmp_path, monkeypatch, mutation, boundary):
    value = _setup(tmp_path)
    _pin(value)
    if boundary == "generic-writer":
        _assert_no_effect(value, lambda: _checkpoint_change(
            value, lambda state: _mutate_reference(value, state, mutation),
        ), match="^rsi_python_admission_")
    else:
        _forged_checkpoint_append(value, lambda state: _mutate_reference(value, state, mutation))
        controller = _fresh_controller(value)
        _forbid_effects(monkeypatch, controller)
        _assert_no_effect(value, lambda: controller.resume(value.binding.run_id), match="^rsi_python_admission_")


def test_stale_flow_save_refuses_without_adopting_new_pin(tmp_path):
    value = _setup(tmp_path)
    state = deepcopy(value.ledger.controller_checkpoint(value.binding.run_id)[1])
    run = value.ledger.get_run(value.binding.run_id)
    _pin(value)
    with value.ledger.controller_lock(value.binding.run_id):
        _assert_no_effect(value, lambda: value.controller._save_flow(run, state), match="^rsi_python_admission_")
    assert "python_admission_refs" not in state


def test_unchanged_flow_save_still_requires_missing_pinned_row(tmp_path):
    value = _setup(tmp_path)
    record = _pin(value)
    state = deepcopy(value.ledger.controller_checkpoint(value.binding.run_id)[1])
    run = value.ledger.get_run(value.binding.run_id)
    _lose_record(value, record, "missing")
    with value.ledger.controller_lock(value.binding.run_id):
        _assert_no_effect(value, lambda: value.controller._save_flow(run, state), match="^rsi_python_admission_")


def test_direct_episode_recovery_requires_pin_before_result_or_accounting(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    record = _pin(value)
    head = value.ledger.get_episode(value.episode_id)
    _lose_record(value, record, "missing")
    _forbid_effects(monkeypatch, value.controller)
    monkeypatch.setattr(value.ledger, "episode_result", lambda *args: pytest.fail("recovery read result before pin gate"))
    _assert_no_effect(value, lambda: value.controller._resume_episode_execution(
        head, request_hint=value.request,
    ), match="^rsi_python_admission_")


def test_cached_result_replay_rechecks_pin_before_usage_or_terminal_reconciliation(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    record = _pin(value)
    head = value.ledger.get_episode(value.episode_id)
    result = SolverResult(
        episode_id=value.episode_id, request_sha256=value.request.digest(), status="failed",
        candidate_receipt_sha256=None, execution_receipt_sha256=None,
        official_evaluation_receipt_sha256=None, trace_digest=DIGEST,
        terminal_reason="inert-cached-result",
    )
    value.ledger.save_episode_result(value.request, result)
    retained = {}

    def replay(episode, request, saved_result):
        assert episode.episode_id == value.episode_id
        assert request == value.request
        assert saved_result == result
        _lose_record(value, record, "missing")
        retained.update(rows=_rows(value), files=_files(value))

    _forbid_effects(monkeypatch, value.controller)
    monkeypatch.setattr(value.controller, "_validate_native_replay", replay)
    with pytest.raises(RSILearningError, match="^rsi_python_admission_"):
        value.controller._resume_episode_execution(head, request_hint=value.request)
    assert retained
    assert _rows(value) == retained["rows"]
    assert _files(value) == retained["files"]
    assert value.ledger.get_episode(value.episode_id) == head
    assert value.gateway.calls == 1


@pytest.mark.parametrize("status", ["failed", "completed"])
@pytest.mark.parametrize("anchor_retained", [True, False], ids=["original-anchor", "late-anchor-loss"])
def test_fresh_worker_result_requires_original_pin_before_terminal_settlement(
    tmp_path, monkeypatch, status, anchor_retained,
):
    value = _setup(tmp_path)
    _pin(value)
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    episode_id = value.binding.run_id + "-inert-next"
    request = replace(value.request, episode_id=episode_id)
    planned = replace(
        PracticeEpisode.from_dict(state["intents"][value.episode_id]["episode"]),
        episode_id=episode_id, ordinal=1,
    )
    _checkpoint_change(value, lambda wire: wire["intents"].update({
        episode_id: {"episode": planned.to_record_dict(), "request": request.to_dict()},
    }))
    checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)
    state = deepcopy(checkpoint[1])
    original_budget = deepcopy(state["budget_state"])
    original_run = value.ledger.get_run(value.binding.run_id)
    result = SolverResult(
        episode_id=episode_id, request_sha256=request.digest(), status=status,
        candidate_receipt_sha256=DIGEST if status == "completed" else None,
        execution_receipt_sha256=DIGEST if status == "completed" else None,
        official_evaluation_receipt_sha256=DIGEST if status == "completed" else None,
        trace_digest=DIGEST, terminal_reason="inert-fresh-result",
    )
    observed = {}
    verifications = []

    def local_fixture(request_arg):
        # This is an in-process fixture return; no solver, native process, model
        # or evaluator is invoked. The runner must already have saved running.
        assert request_arg == request
        assert value.ledger.get_episode(episode_id).state == "running"
        value.gateway.calls += 1
        if not anchor_retained:
            (value.batch / "python-producer-admission-anchor.json").unlink()
        observed.update(rows=_rows(value), files=_files(value))
        return result

    def verifier(episode_arg, request_arg, result_arg, *args):
        if not anchor_retained:
            pytest.fail("late anchor loss reached verifier before settlement gate")
        assert request_arg == request and result_arg == result
        verifications.append(episode_arg.episode_id)
        outcome = "pass" if status == "completed" else "fail"
        check_name = "official_evaluator" if status == "completed" else "inert-local-fixture"
        return VerifierDecision(
            episode_id, outcome, DIGEST, "inert-local-fixture", DIGEST,
            (VerifierCheck(check_name, outcome, DIGEST),),
            contract_sha256=request.contract_sha256, evaluator_sha256=request.evaluator_sha256,
            environment_sha256=request.environment_sha256,
            official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
            candidate_receipt_sha256=result.candidate_receipt_sha256,
            execution_receipt_sha256=result.execution_receipt_sha256,
        )

    monkeypatch.setattr(value.gateway, "run", local_fixture)
    monkeypatch.setattr(value.controller, "_verify_episode", verifier)
    with value.ledger.controller_lock(value.binding.run_id):
        if anchor_retained:
            execution = value.controller._execute_intent(state, episode_id)
            assert execution.episode.status == status
            assert execution.result == result
            assert verifications == [episode_id]
        else:
            with pytest.raises(RSILearningError, match="^rsi_python_admission_evidence_invalid$"):
                value.controller._execute_intent(state, episode_id)
            assert verifications == []
    assert observed
    assert value.gateway.calls == 2
    assert value.ledger.episode_result(episode_id) == (request, result)
    head = value.ledger.get_episode(episode_id)
    if anchor_retained:
        assert head.state == status
        assert (head.payload["verifier"] is not None) is (status == "completed")
    else:
        assert head.state == "running"
        assert head.payload["verifier"] is None
        after = _rows(value)
        for table in observed["rows"]:
            if table != "rsi_episode_results":
                assert after[table] == observed["rows"][table]
    assert _files(value) == observed["files"]
    assert state["budget_state"] == original_budget
    assert value.ledger.get_run(value.binding.run_id) == original_run
    assert value.ledger.controller_checkpoint(value.binding.run_id) == checkpoint


def test_callback_started_write_rechecks_original_pin_before_actual_call(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    _pin(value)
    run_id = value.binding.run_id
    callback_id = "verifier:" + value.episode_id
    namespace = DurableCallbackJournal.identity(run_id, callback_id)
    result = SolverResult(
        episode_id=value.episode_id, request_sha256=value.request.digest(), status="failed",
        candidate_receipt_sha256=None, execution_receipt_sha256=None,
        official_evaluation_receipt_sha256=None, trace_digest=DIGEST,
        terminal_reason="inert-callback-fixture",
    )
    inputs = {"request": value.request.to_dict(), "result": result.to_dict()}
    binding = value.controller._callback_binding("verifier", inputs)
    assert DurableCallbackJournal(value.ledger).inspect(run_id, callback_id) is None
    before = _rows(value)
    checkpoint = value.ledger.controller_checkpoint(run_id)
    episode = value.ledger.get_episode(value.episode_id)
    run = value.ledger.get_run(run_id)
    observed = {}
    calls = []
    original = value.ledger.write_controller_checkpoint

    def started_then_lose_anchor(scope_id, state, *, expected_sha256):
        digest = original(scope_id, state, expected_sha256=expected_sha256)
        assert scope_id == namespace and state["status"] == "started"
        (value.batch / "python-producer-admission-anchor.json").unlink()
        observed.update(rows=_rows(value), files=_files(value))
        return digest

    def local_fixture():
        calls.append(callback_id)
        return {}

    monkeypatch.setattr(value.ledger, "write_controller_checkpoint", started_then_lose_anchor)
    with (
        value.ledger.controller_lock(run_id),
        pytest.raises(RSILearningError, match="^rsi_python_admission_evidence_invalid$"),
    ):
        value.controller._invoke_callback(
            run_id, callback_id, "verifier", inputs, local_fixture,
        )
    assert calls == []
    assert observed
    assert _rows(value) == observed["rows"]
    assert _files(value) == observed["files"]
    after = _rows(value)
    for table in before:
        if table != "rsi_controller_journal":
            assert after[table] == before[table]
    assert len(after["rsi_controller_journal"]) == len(before["rsi_controller_journal"]) + 1
    history = value.ledger.controller_checkpoint_history(namespace)
    assert len(history) == 1
    assert history[0][1] == {
        "schema_version": "1", "kind": "durable_callback", "scope_id": run_id,
        "callback_id": callback_id, "status": "started", "binding": binding,
        "binding_sha256": DurableCallbackJournal.digest(binding), "result": None,
        "result_sha256": None, "started_checkpoint_sha256": None, "reconciliation": None,
    }
    assert DurableCallbackJournal(value.ledger).inspect(run_id, callback_id) == history[0]
    assert value.ledger.controller_checkpoint(run_id) == checkpoint
    assert value.ledger.get_episode(value.episode_id) == episode
    assert value.ledger.get_run(run_id) == run
    assert value.gateway.calls == 1


@pytest.mark.parametrize("filename", [
    "python-producer-binding.json", "python-producer-admission-handoff.json",
    "python-producer-admission-anchor.json", "journal.prepared.json",
])
def test_required_reference_revalidates_independent_retained_files(tmp_path, monkeypatch, filename):
    value = _setup(tmp_path)
    _pin(value)
    (value.batch / filename).unlink()
    controller = _fresh_controller(value)
    _forbid_effects(monkeypatch, controller)
    _assert_no_effect(value, lambda: controller.resume(value.binding.run_id), match="^rsi_(python_admission|producer_checkpoint)_")
    assert not (value.batch / filename).exists()


def test_same_bytes_handoff_replacement_does_not_refresh_required_inode_pin(tmp_path):
    value = _setup(tmp_path)
    _pin(value)
    path = value.batch / "python-producer-admission-handoff.json"
    replacement = value.batch / "inert-replacement.json"
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    assert replacement.stat().st_ino != path.stat().st_ino
    os.replace(replacement, path)
    _assert_no_effect(value, lambda: _fresh_controller(value).resume(value.binding.run_id), match="^rsi_python_admission_")


def test_valid_pin_fresh_resume_reaches_existing_quarantine_without_relaunch(tmp_path):
    value = _setup(tmp_path)
    _pin(value)
    _assert_no_effect(value, lambda: _fresh_controller(value).resume(value.binding.run_id), match="^rsi_resume_recovery_required$")


def test_valid_terminal_resume_returns_read_only_with_required_original_pin(tmp_path):
    value = _setup(tmp_path)
    _pin(value)
    _run_state(value, "completed")
    rows, files = _rows(value), _files(value)
    result = _fresh_controller(value).resume(value.binding.run_id)
    assert result.status == "completed"
    assert _rows(value) == rows
    assert _files(value) == files
    assert value.gateway.calls == 1


def test_unpinned_historical_fixture_keeps_existing_recovery_quarantine(tmp_path):
    value = _setup(tmp_path)
    assert "python_admission_refs" not in value.ledger.controller_checkpoint(value.binding.run_id)[1]
    _assert_no_effect(value, lambda: _fresh_controller(value).resume(value.binding.run_id), match="^rsi_resume_recovery_required$")
