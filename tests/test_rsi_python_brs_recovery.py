"""Partial BRS recovery using original owner CAS, threads and inert evidence."""

from __future__ import annotations

import hashlib
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from threading import Event, get_ident

import pytest
from test_rsi_python_admission import DIGEST, OTHER, _files, _plan, _rows, _setup
from test_rsi_python_admission_flow import _forged_checkpoint_append, _lose_record
from test_rsi_python_brs_owner import _decisions

from lunar_evolution import (
    RSILearningController,
    RSILearningError,
    RSILedger,
    bundle_evolution,
    producer_process,
)
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_callbacks import DurableCallbackJournal
from lunar_evolution.rsi_gateway import SolverResult
from lunar_evolution.rsi_python_brs_admission import build_brs_admission_ready


class _OwnerStoppedAfterExecutionSave(BaseException):
    pass


class _SiblingDispatchNeverStarted(BaseException):
    pass


@pytest.fixture(autouse=True)
def inert_local_evidence_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("BRS recovery fixture invoked an actual worker or evaluator")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(producer_process, "run_producer_process", forbidden)
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", forbidden)
    monkeypatch.setattr(
        bundle_evolution.MultiFileCandidatePipeline, "evaluate_draft_non_publishing", forbidden,
    )


def _partial_wave(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    ledger = RSILedger(tmp_path / "brs-recovery.sqlite3")
    owner = get_ident()
    controller = None
    native_id = value.binding.run_id + "-practice-0-0"
    sibling_id = value.binding.run_id + "-practice-0-1"
    calls = []
    worker_failures = []
    owner_stopped = Event()

    class InertGateway:
        def rsi_fingerprint_config(self):
            return {"fixture": "brs-partial-wave-original-owner"}

        def run(self, request):
            active_controller = value.controller
            assert get_ident() != owner
            assert not ledger.controller_lock_held(value.binding.run_id)
            calls.append(request.episode_id)
            state, _head = active_controller._python_admission_active_brs_worker(
                value.binding.run_id, request.episode_id,
            )
            assert len(state["intents"]) == 2
            assert state["budget_state"]["consumed"]["solver_invocations"] == 2
            result = SolverResult(
                episode_id=request.episode_id, request_sha256=request.digest(), status="completed",
                candidate_receipt_sha256=DIGEST, execution_receipt_sha256=DIGEST,
                official_evaluation_receipt_sha256=DIGEST, trace_digest=DIGEST,
                solver_score=1.0, terminal_reason="inert-partial-brs",
            )
            if request.episode_id == native_id:
                plan = _plan(value.binding, request, active_controller.snapshot)
                claim = ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
                digest = active_controller._request_python_admission_for_brs_worker(
                    value.binding.run_id, request.episode_id, native_plan=plan,
                    prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
                    wait_check=lambda: None,
                )
                assert state["python_admission_refs"][native_id]["record_sha256"] == digest
                value.request, value.plan, value.claim = request, plan, claim
                ledger.publish_native_episode_result(
                    request, plan_sha256=plan.plan_sha256, result=result, expected_claim=claim,
                )
            else:
                assert request.episode_id == sibling_id
            return result

    gateway = InertGateway()
    controller = RSILearningController(
        gateway, ledger=ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.workspace,
    )
    value.controller = controller
    save = controller._save_flow
    execute = controller._execute_intent

    def observe_execution(state, episode_id):
        if episode_id == sibling_id:
            # Stop this scheduled invocation before the original runner creates a
            # head or dispatches a gateway. A durable sibling result would be rebuilt
            # by public resume before _drive_brs, leaving no pending wave to capture.
            assert owner_stopped.wait(timeout=10), "owner did not reach the durable stop"
            raise _SiblingDispatchNeverStarted()
        try:
            return execute(state, episode_id)
        except BaseException as exc:
            worker_failures.append((episode_id, repr(exc)))
            raise

    def save_then_stop(record, state):
        head = save(record, state)
        if state["phase"] == "evaluated" and state["current_episode_id"] == native_id:
            assert set(state["executions"]) == {native_id}
            assert set(state["python_admission_refs"]) == {native_id}
            assert ledger.get_episode(sibling_id) is None
            owner_stopped.set()
            raise _OwnerStoppedAfterExecutionSave()
        return head

    with monkeypatch.context() as patch:
        patch.setattr(controller, "_save_flow", save_then_stop)
        patch.setattr(controller, "_execute_intent", observe_execution)
        with pytest.raises(_OwnerStoppedAfterExecutionSave):
            controller.run_brs(
                run_id=value.binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
                environment_sha256=DIGEST, solver_id="native",
                practices=_decisions(controller, value.binding.run_id, 2), max_workers=2,
                budget={"deadline_unix": value.binding.deadline_unix},
            )
    value.ledger, value.gateway, value.controller = ledger, gateway, controller
    value.episode_id, value.sibling_id, value.calls = native_id, sibling_id, calls
    checkpoint = ledger.controller_checkpoint(value.binding.run_id)
    assert checkpoint[1]["status"] == "running"
    assert set(checkpoint[1]["executions"]) == {native_id}
    assert set(checkpoint[1]["python_admission_refs"]) == {native_id}
    assert calls == [native_id]
    assert not worker_failures
    assert ledger.get_episode(sibling_id) is None
    assert ledger.episode_result(sibling_id) is None
    return value


def _fresh_controller(value):
    value.controller = RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.workspace,
    )
    return value.controller


@contextmanager
def _pending_scope(value, *, pending=None, whole=None, state=None):
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1] if state is None else state
    pending = (value.sibling_id,) if pending is None else pending
    whole = (value.episode_id, value.sibling_id) if whole is None else whole
    with (
        value.ledger.controller_lock(value.binding.run_id),
        value.controller._python_admission_brs_wave_scope(
            state, pending, wave_episode_ids=whole,
        ) as wave,
    ):
        yield wave


def _assert_refused_without_effect(value, operation, *, match="^rsi_(python|producer)_"):
    rows, files, calls = _rows(value), _files(value), tuple(value.calls)
    with pytest.raises(RSILearningError, match=match):
        operation()
    assert (_rows(value), _files(value), tuple(value.calls)) == (rows, files, calls)
    assert value.controller._python_admission_brs_wave is None


def _capture(value, **changes):
    with _pending_scope(value, **changes):
        pass


def test_original_partial_brs_wave_resumes_without_redispatch_or_budget_refresh(tmp_path, monkeypatch):
    value = _partial_wave(tmp_path, monkeypatch)
    run_id = value.binding.run_id
    before = deepcopy(value.ledger.controller_checkpoint(run_id)[1])
    admissions = _rows(value)["rsi_python_admissions"]
    original_result = value.ledger.episode_result(value.episode_id)
    original_head = value.ledger.get_episode(value.episode_id)
    files = _files(value)
    controller = _fresh_controller(value)
    result = controller.resume(run_id)
    after = value.ledger.controller_checkpoint(run_id)[1]
    assert result.status == "completed"
    assert [item.episode.ordinal for item in result.practice_episodes] == [0, 1]
    assert len(result.memory_snapshot.items) == 2
    assert len({item.request.memory_snapshot_sha256 for item in result.practice_episodes}) == 1
    assert sorted(value.calls) == [value.episode_id, value.sibling_id]
    assert after["budget_state"] == before["budget_state"]
    assert after["python_admission_refs"] == before["python_admission_refs"]
    assert _rows(value)["rsi_python_admissions"] == admissions
    # Only the previously unstarted sibling's original verifier lock is new.
    # Preserve every other original name/stat/inode/byte outside the SQL ledger.
    changed_files = _files(value)
    lock_dir = value.ledger.database.relative_to(value.workspace).with_name(
        value.ledger.database.name + ".controller-locks",
    )
    callback = DurableCallbackJournal.identity(run_id, "verifier:" + value.sibling_id)
    sibling_lock = lock_dir / hashlib.sha256(callback.encode("utf-8")).hexdigest()
    assert set(changed_files) - set(files) == {sibling_lock}
    assert set(files) - set(changed_files) == set()
    assert {path for path in files if changed_files[path] != files[path]} == {lock_dir}
    lock_pin = changed_files[sibling_lock]
    assert stat.S_ISREG(lock_pin[2]) and lock_pin[3:5] == (1, 0) and lock_pin[-1] == b""
    assert value.ledger.episode_result(value.episode_id) == original_result
    assert value.ledger.get_episode(value.episode_id) == original_head
    rows, files = _rows(value), _files(value)
    assert _fresh_controller(value).resume(run_id) == result
    assert (_rows(value), _files(value)) == (rows, files)


@pytest.mark.parametrize("mutation", ["foreign-execution", "foreign-reference", "changed-result", "changed-request",
                                    "changed-verifier", "changed-reference", "changed-plan"])
def test_partial_wave_refuses_foreign_or_changed_completed_obligations(tmp_path, monkeypatch, mutation):
    value = _partial_wave(tmp_path, monkeypatch)

    def corrupt(state):
        execution = state["executions"][value.episode_id]
        if mutation == "foreign-execution":
            state["executions"][value.binding.run_id + "-practice-0-2"] = deepcopy(execution)
        elif mutation == "foreign-reference":
            reference = state["python_admission_refs"].pop(value.episode_id)
            state["python_admission_refs"][value.binding.run_id + "-practice-0-2"] = reference
        elif mutation == "changed-result":
            execution["result"]["solver_score"] = 2.0
        elif mutation == "changed-request":
            execution["request"]["practice_charter"]["reason_code"] = "foreign-charter"
        elif mutation == "changed-verifier":
            execution["verifier"]["diagnosis"] = "foreign-diagnosis"
        elif mutation == "changed-reference":
            state["python_admission_refs"][value.episode_id]["record_sha256"] = OTHER
        else:
            state["plan"]["practices"].append(deepcopy(state["plan"]["practices"][0]))

    _forged_checkpoint_append(value, corrupt)
    _assert_refused_without_effect(value, lambda: _capture(value))


@pytest.mark.parametrize("mutation", ["missing", "replace"])
def test_partial_wave_requires_original_completed_admission_row_without_repair(tmp_path, monkeypatch, mutation):
    value = _partial_wave(tmp_path, monkeypatch)
    record = value.ledger.python_admission_record(
        value.binding.run_id, value.episode_id, value.journal.journal_id,
    )
    _lose_record(value, record, mutation)
    _assert_refused_without_effect(value, lambda: _capture(value))


@pytest.mark.parametrize("routing", ["completed-pending", "arbitrary-whole", "incomplete-whole", "reordered-whole"])
def test_partial_wave_whole_plan_cannot_expand_or_reassign_fresh_dispatch(tmp_path, monkeypatch, routing):
    value = _partial_wave(tmp_path, monkeypatch)
    changes = {
        "completed-pending": {"pending": (value.episode_id, value.sibling_id)},
        "arbitrary-whole": {"whole": (value.episode_id, value.sibling_id, "foreign-episode")},
        "incomplete-whole": {"whole": (value.sibling_id,)},
        "reordered-whole": {"whole": (value.sibling_id, value.episode_id)},
    }[routing]
    _assert_refused_without_effect(value, lambda: _capture(value, **changes))


def test_old_dispatch_only_scope_keeps_original_foreign_reference_refusal(tmp_path, monkeypatch):
    value = _partial_wave(tmp_path, monkeypatch)
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]

    def capture():
        with (
            value.ledger.controller_lock(value.binding.run_id),
            value.controller._python_admission_brs_wave_scope(state, (value.sibling_id,)),
        ):
            pass

    _assert_refused_without_effect(value, capture)


def test_capture_head_drift_is_refused_without_latest_state_adoption(tmp_path, monkeypatch):
    value = _partial_wave(tmp_path, monkeypatch)
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    original = value.ledger.controller_checkpoint
    injected = []

    def checkpoint(run_id):
        observed = original(run_id)
        if run_id == value.binding.run_id and not injected:
            injected.append(True)
            _forged_checkpoint_append(value, lambda wire: wire.update(phase="unrelated-head-change"))
            injected.append((_rows(value), _files(value)))
        return observed

    monkeypatch.setattr(value.ledger, "controller_checkpoint", checkpoint)
    with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_stale$"):
        _capture(value, state=state)
    assert len(injected) == 2
    assert (_rows(value), _files(value)) == injected[1]
    assert value.calls == [value.episode_id]
    assert state["phase"] == "evaluated"
    assert value.controller._python_admission_brs_wave is None


def test_completed_obligation_never_gets_worker_token_channel_or_ready_ack(tmp_path, monkeypatch):
    value = _partial_wave(tmp_path, monkeypatch)
    ready = build_brs_admission_ready(
        value.binding.run_id, value.episode_id,
        canonical_json({
            "native_plan": value.plan.to_dict(), "prepared_journal": value.journal.to_dict(),
            "expected_anchor_sha256": value.anchor.anchor_sha256,
        }),
    )
    rows, files = _rows(value), _files(value)

    def observe(state, episode_id):
        with value.controller._python_admission_brs_worker_scope(state, episode_id):
            actual, _head = value.controller._python_admission_active_brs_worker(
                value.binding.run_id, episode_id,
            )
            assert actual is state
            with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_identity_invalid$"):
                value.controller._python_admission_active_brs_worker(value.binding.run_id, value.episode_id)
            with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_wave_mismatch$"):
                value.controller._python_admission_brs_wave.channel.request(ready, check=lambda: None)

    monkeypatch.setattr(value.controller, "_execute_intent", observe)
    with ThreadPoolExecutor(max_workers=1) as pool, _pending_scope(value) as wave:
        assert wave.episode_ids == (value.sibling_id,)
        pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.sibling_id).result(timeout=10)
        with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_identity_invalid$"):
            pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id).result(timeout=10)
        with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_request_invalid$"):
            value.controller._python_admission_service_brs_ready(wave, ready)
    assert (_rows(value), _files(value)) == (rows, files)
    assert value.calls == [value.episode_id]


@pytest.mark.parametrize("mutation", ["none", "state", "durable-head", "sidecar", "ledger", "gateway"])
def test_completed_replay_hook_runs_outside_short_mutex_then_rechecks_original_scope(tmp_path, monkeypatch, mutation):
    value = _partial_wave(tmp_path, monkeypatch)
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    callbacks, after_callback = [], []

    def replay(request, result):
        assert value.ledger.controller_lock_held(value.binding.run_id)
        assert value.controller._python_admission_brs_wave is None

        def observation_available():
            lock = value.controller._python_admission_brs_observation_lock
            acquired = lock.acquire(blocking=False)
            if acquired:
                try:
                    with value.ledger.read_only_observations():
                        assert value.ledger.controller_checkpoint(value.binding.run_id) is not None
                finally:
                    lock.release()
            return acquired

        with ThreadPoolExecutor(max_workers=1) as observers:
            assert observers.submit(observation_available).result(timeout=5), "caller replay ran under short mutex"
        callbacks.append(request.episode_id)
        if mutation == "state":
            state["phase"] = "callback-state-drift"
        elif mutation == "durable-head":
            _forged_checkpoint_append(value, lambda wire: wire.update(phase="callback-head-drift"))
        elif mutation == "sidecar":
            value.controller.producer_sidecar = object()
        elif mutation == "ledger":
            value.controller.ledger = object()
        elif mutation == "gateway":
            value.controller.gateway = object()
        after_callback.append((_rows(value), _files(value)))
        return result

    monkeypatch.setattr(value.gateway, "requires_replay_validation", True, raising=False)
    monkeypatch.setattr(value.gateway, "validate_replay", replay, raising=False)
    if mutation == "none":
        _capture(value, state=state)
    else:
        with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_(stale|identity_invalid)$"):
            _capture(value, state=state)
    assert callbacks == [value.episode_id]
    assert (_rows(value), _files(value)) == after_callback[0]
    assert value.calls == [value.episode_id]
    assert value.controller._python_admission_brs_wave is None


@pytest.mark.parametrize("shape", ["list", "extra-object", "str-subclass"])
def test_whole_wave_identity_shape_refuses_callbacks_before_original_history_read(tmp_path, monkeypatch, shape):
    value = _partial_wave(tmp_path, monkeypatch)

    class Hostile:
        def __eq__(self, other):
            pytest.fail("whole-wave identity invoked caller equality")

    class HostileString(str):
        def __eq__(self, other):
            pytest.fail("whole-wave identity invoked subclass equality")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid whole-wave shape read original evidence")

    whole = {
        "list": [value.episode_id, value.sibling_id],
        "extra-object": (value.episode_id, Hostile()),
        "str-subclass": (value.episode_id, HostileString(value.sibling_id)),
    }[shape]
    monkeypatch.setattr(value.ledger, "history", forbidden)
    _assert_refused_without_effect(value, lambda: _capture(value, whole=whole))
