"""Real selected owner service over an original BRS wave and inert local evidence.

The gateway below never invokes a producer, evaluator, toolchain, or model. Only
the preparation capture and deliberate fault injections replace controller seams.
Successful calls use the actual selected binder, dispatch, runner, ready/ack CAS,
episode settlement, and channel completion.
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from queue import Queue
from threading import Event, get_ident

import pytest
from test_rsi_python_admission import DIGEST, OTHER, _files, _plan, _rows, _setup
from test_rsi_python_admission_flow import _forged_checkpoint_append
from test_rsi_python_brs_owner import _decisions

from lunar_evolution import (
    RSILearningController,
    RSILearningError,
    RSILedger,
    bundle_evolution,
    producer_process,
    rsi_controller,
)
from lunar_evolution.rsi_fingerprint import RSIFingerprintError
from lunar_evolution.rsi_gateway import SolverResult


class _PreparationCaptured(BaseException):
    pass


class _CallbackBearingVerifier:
    """Must be rejected by exact DTO type checks before equality/serialization."""

    def __init__(self):
        self.calls = 0

    def __eq__(self, _other):
        self.calls += 1
        raise AssertionError("callback-bearing verifier equality executed")

    def to_dict(self):
        self.calls += 1
        raise AssertionError("callback-bearing verifier serializer executed")


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("selected service fixture invoked external execution")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(producer_process, "run_producer_process", forbidden)
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", forbidden)
    monkeypatch.setattr(
        bundle_evolution.MultiFileCandidatePipeline, "evaluate_draft_non_publishing", forbidden,
    )


def _fixture(tmp_path, monkeypatch, *, max_workers=1):
    tmp_path.mkdir(parents=True, exist_ok=True)
    value = _setup(tmp_path)
    value.owner_thread = get_ident()
    value.events = []
    value.operation = None

    class InertGateway:
        calls = 0
        fingerprint = "selected-service-inert-original-wave"

        def rsi_fingerprint_config(self):
            return {"fixture": self.fingerprint}

        def run(self, request):
            self.calls += 1
            assert get_ident() != value.owner_thread
            assert not value.ledger.controller_lock_held(value.binding.run_id)
            value.events.append(("gateway", get_ident(), request.episode_id))
            if value.operation is not None:
                return value.operation(request)
            return _ack_and_result(value, request)

    value.ledger = RSILedger(tmp_path / "selected-service.sqlite3")
    value.gateway = InertGateway()
    value.controller = RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.workspace,
    )

    def capture(state, episode_id):
        assert state["plan"]["mode"] == "brs"
        raise _PreparationCaptured()

    # Create the actual original run and persist its full reserved wave, stopping
    # immediately before any episode head or gateway side effect can be created.
    with monkeypatch.context() as capture_patch:
        capture_patch.setattr(value.controller, "_execute_intent", capture)
        with pytest.raises(_PreparationCaptured):
            value.controller.run_brs(
                run_id=value.binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
                environment_sha256=DIGEST, solver_id="native",
                practices=_decisions(value.controller, value.binding.run_id, 2),
                max_workers=max_workers, budget={"deadline_unix": value.binding.deadline_unix},
            )
    value.episode_id = value.binding.run_id + "-practice-0-0"
    value.sibling_id = value.binding.run_id + "-practice-0-1"
    value.state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    assert value.state["plan"] == value.ledger.history(value.binding.run_id)[0].payload["plan"]
    assert value.state["plan"]["mode"] == "brs"
    assert tuple(value.state["intents"]) == (value.episode_id, value.sibling_id)
    assert value.state["executions"] == {}
    assert value.ledger.get_episode(value.episode_id) is None
    assert value.ledger.get_episode(value.sibling_id) is None
    assert value.gateway.calls == 0
    return value


@contextmanager
def _wave(value, *, episode_ids=None):
    episode_ids = (value.episode_id, value.sibling_id) if episode_ids is None else episode_ids
    with (
        value.ledger.controller_lock(value.binding.run_id),
        value.controller._python_admission_brs_wave_scope(value.state, episode_ids) as wave,
    ):
        yield wave


def _ack_and_result(value, request, *, acknowledge=True):
    plan = _plan(value.binding, request, value.controller.snapshot)
    claim = value.ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
    if acknowledge:
        value.events.append(("ready", get_ident(), request.episode_id))
        digest = value.controller._request_python_admission_for_brs_worker(
            value.binding.run_id, request.episode_id, native_plan=plan,
            prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
            wait_check=lambda: None,
        )
        state, _ = value.controller._python_admission_active_brs_worker(
            value.binding.run_id, request.episode_id,
        )
        assert state["python_admission_refs"][request.episode_id]["record_sha256"] == digest
        value.events.append(("ack", get_ident(), request.episode_id))
    result = SolverResult(
        episode_id=request.episode_id, request_sha256=request.digest(), status="completed",
        candidate_receipt_sha256=DIGEST, execution_receipt_sha256=DIGEST,
        official_evaluation_receipt_sha256=DIGEST, trace_digest=DIGEST,
        solver_score=1.0, terminal_reason="inert-selected-service",
    )
    value.ledger.publish_native_episode_result(
        request, plan_sha256=plan.plan_sha256, result=result, expected_claim=claim,
    )
    return result


def _evidence_files(value):
    # New running episodes create their own controller-lock bookkeeping. This is
    # separate from immutable producer evidence and the independently checked SQL.
    lock_directory = value.ledger.database.name + ".controller-locks"
    return {path: content for path, content in _files(value).items()
            if lock_directory not in path.parts}


def _track_close_and_shutdown(monkeypatch, wave):
    events = []
    original_close = wave.channel.close

    def close():
        events.append("close")
        original_close()

    class ObservedExecutor(ThreadPoolExecutor):
        def shutdown(self, wait=True, *, cancel_futures=False):
            assert wave.channel._closed
            events.append("shutdown")
            return super().shutdown(wait=wait, cancel_futures=cancel_futures)

    monkeypatch.setattr(wave.channel, "close", close)
    monkeypatch.setattr(rsi_controller, "ThreadPoolExecutor", ObservedExecutor)
    return events


def test_actual_selected_service_acknowledges_and_settles_only_first_original_intent(
    tmp_path, monkeypatch,
):
    value = _fixture(tmp_path, monkeypatch)
    original_state = deepcopy(value.state)
    files = _evidence_files(value)
    original_service = value.controller._python_admission_service_brs_ready

    def observed_owner_service(wave, ready):
        assert get_ident() == value.owner_thread
        assert value.ledger.controller_lock_held(value.binding.run_id)
        value.events.append(("owner", get_ident(), ready.episode_id))
        return original_service(wave, ready)

    monkeypatch.setattr(value.controller, "_python_admission_service_brs_ready", observed_owner_service)
    with _wave(value) as wave:
        shutdown = _track_close_and_shutdown(monkeypatch, wave)
        execution = value.controller._python_admission_run_selected_brs_intent(wave)
        assert wave.selected_handoff.episode_id == value.episode_id
        assert wave.selected_handoff.ordinal == 0
        assert wave.selected_handoff.root_snapshot_sha256 == execution.request.memory_snapshot_sha256
        assert wave.selected_context.controller_id == f"controller-{id(value.controller):x}"
        assert wave.selected_context.ledger_id == f"ledger-{id(value.ledger):x}"
        assert wave.selected_worker_started
        assert wave.channel._completed_selected_episodes == {value.episode_id}
        assert wave.channel._selected_episode_id is None
        assert shutdown == ["close", "shutdown"]
        assert execution.episode.status == execution.result.status == "completed"
        assert value.ledger.get_episode(value.episode_id).payload == execution.episode.to_record_dict()
        assert value.ledger.episode_result(value.episode_id) == (execution.request, execution.result)
        durable = value.ledger.controller_checkpoint(value.binding.run_id)[1]
        assert durable == wave.state
        assert set(durable["python_admission_refs"]) == {value.episode_id}
        assert {key: item for key, item in durable.items() if key != "python_admission_refs"} == original_state
    assert [event[0] for event in value.events] == ["gateway", "ready", "owner", "ack"]
    assert value.gateway.calls == 1
    assert value.ledger.get_episode(value.sibling_id) is None
    assert value.ledger.get_run(value.binding.run_id).state == "running"
    assert _evidence_files(value) == files
    assert len(_rows(value)["rsi_python_admissions"]) == 1


def test_selected_service_closes_before_shutdown_on_worker_failure(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)

    def fail(request):
        raise RuntimeError("inert-worker-failure")

    value.operation = fail
    with _wave(value) as wave:
        shutdown = _track_close_and_shutdown(monkeypatch, wave)
        head = wave.checkpoint_sha256
        with pytest.raises(RuntimeError, match="inert-worker-failure"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert shutdown == ["close", "shutdown"]
        assert wave.checkpoint_sha256 == head
        assert not wave.channel._completed_selected_episodes
    assert value.ledger.get_episode(value.episode_id).state == "running"
    assert value.ledger.episode_result(value.episode_id) is None
    assert not _rows(value)["rsi_python_admissions"]


def test_selected_service_owner_pin_failure_wakes_and_joins_waiting_worker(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)

    def fail_pin(*args, **kwargs):
        raise RuntimeError("inert-owner-pin-failure")

    monkeypatch.setattr(value.ledger, "pin_python_admission_record", fail_pin)
    with _wave(value) as wave:
        shutdown = _track_close_and_shutdown(monkeypatch, wave)
        head, state = wave.checkpoint_sha256, deepcopy(wave.state)
        with pytest.raises(RuntimeError, match="inert-owner-pin-failure"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert shutdown == ["close", "shutdown"]
        assert wave.checkpoint_sha256 == head and wave.state == state
        assert wave.channel._requests[value.episode_id].error == "handler_failed"
    assert value.gateway.calls == 1
    assert value.ledger.episode_result(value.episode_id) is None
    assert not _rows(value)["rsi_python_admissions"]


def test_selected_service_failed_ack_restores_thread_scope_for_explicit_reloaded_wave(
    tmp_path, monkeypatch,
):
    value = _fixture(tmp_path, monkeypatch)
    original_service = value.controller._python_admission_service_brs_ready

    def pin_then_close(wave, ready):
        digest = original_service(wave, ready)
        wave.channel.close()
        return digest

    with _wave(value) as wave, monkeypatch.context() as failure_patch:
        original_head, original_state = wave.checkpoint_sha256, deepcopy(wave.state)
        failure_patch.setattr(value.controller, "_python_admission_service_brs_ready", pin_then_close)
        with pytest.raises(RSILearningError, match="rsi_python_brs_admission_ack_invalid"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert wave.checkpoint_sha256 == original_head and wave.state == original_state
        assert wave.channel._closed
        assert not wave.channel._completed_selected_episodes
        assert getattr(value.controller._python_admission_brs_local, "selected_service", None) is None
        durable_head, durable = value.ledger.controller_checkpoint(value.binding.run_id)
        assert durable_head != original_head
        assert value.episode_id in durable["python_admission_refs"]
        assert value.ledger.episode_result(value.episode_id) is None
    assert len(_rows(value)["rsi_python_admissions"]) == 1
    # A caller explicitly reloads the preserved obligation; the failed owning
    # stack cannot adopt it. This fresh wave only observes it, never retries work.
    value.state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    with _wave(value) as recovered_wave:
        with value.controller._python_admission_brs_service_observations(recovered_wave):
            assert value.controller._python_admission_brs_local.selected_service == (recovered_wave, None)
        assert value.controller._python_admission_brs_local.selected_service is None
    assert value.gateway.calls == 1


def test_selected_service_refuses_completed_worker_without_original_ready_ack(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    value.operation = lambda request: _ack_and_result(value, request, acknowledge=False)
    with _wave(value) as wave:
        shutdown = _track_close_and_shutdown(monkeypatch, wave)
        with pytest.raises(RSILearningError, match="handoff_not_acknowledged"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert shutdown == ["close", "shutdown"]
        assert not wave.channel._completed_selected_episodes
    assert value.ledger.get_episode(value.episode_id).state == "completed"
    assert value.ledger.episode_result(value.episode_id) is not None
    assert not _rows(value)["rsi_python_admissions"]


@pytest.mark.parametrize(
    "fault", ["type", "request", "episode", "memory", "result_status", "verifier"],
)
def test_selected_service_refuses_worker_result_drift_after_actual_ack(tmp_path, monkeypatch, fault):
    value = _fixture(tmp_path, monkeypatch)
    original_execute = value.controller._execute_intent

    def corrupt(state, episode_id):
        execution = original_execute(state, episode_id)
        if fault == "type":
            return object()
        if fault == "request":
            return replace(execution, request=replace(execution.request, episode_id="foreign-episode"))
        if fault == "episode":
            verifier = replace(execution.verifier, episode_id="foreign-episode")
            return replace(
                execution, episode=replace(
                    execution.episode, episode_id="foreign-episode", verifier=verifier,
                ), verifier=verifier,
            )
        if fault == "memory":
            return replace(execution, episode=replace(execution.episode, memory_snapshot_sha256=OTHER))
        if fault == "verifier":
            return replace(execution, verifier=replace(execution.verifier, diagnosis="changed-verifier"))
        return replace(execution, result=replace(execution.result, status="failed"))

    monkeypatch.setattr(value.controller, "_execute_intent", corrupt)
    with _wave(value) as wave:
        with pytest.raises(RSILearningError, match="selected_result_invalid"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert wave.channel._closed
        assert not wave.channel._completed_selected_episodes
        assert value.episode_id in wave.state["python_admission_refs"]
    assert len(_rows(value)["rsi_python_admissions"]) == 1
    assert value.gateway.calls == 1
    assert value.ledger.get_episode(value.episode_id).state == "completed"


def test_selected_service_rejects_callback_bearing_fake_verifier_before_comparison(
    tmp_path, monkeypatch,
):
    value = _fixture(tmp_path, monkeypatch)
    original_execute = value.controller._execute_intent
    fake = _CallbackBearingVerifier()

    def corrupt(state, episode_id):
        return replace(original_execute(state, episode_id), verifier=fake)

    monkeypatch.setattr(value.controller, "_execute_intent", corrupt)
    with _wave(value) as wave:
        with pytest.raises(RSILearningError, match="selected_result_invalid"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert fake.calls == 0
        assert wave.channel._closed
        assert not wave.channel._completed_selected_episodes
    assert len(_rows(value)["rsi_python_admissions"]) == 1


@pytest.mark.parametrize("fault", ["episode", "saved_result"])
def test_selected_service_rechecks_actual_ledger_after_worker_settlement(tmp_path, monkeypatch, fault):
    value = _fixture(tmp_path, monkeypatch)
    original_execute = value.controller._execute_intent

    def hide_durable_evidence(state, episode_id):
        execution = original_execute(state, episode_id)
        name = "get_episode" if fault == "episode" else "episode_result"
        original_observation = getattr(value.ledger, name)

        def missing_final_observation(key):
            # Keep all real producer/admission revalidation intact. Inject only
            # the service's final direct ledger observation of the settled result.
            if sys._getframe(1).f_code.co_name == "_python_admission_run_selected_brs_intent":
                return None
            return original_observation(key)

        monkeypatch.setattr(value.ledger, name, missing_final_observation)
        return execution

    monkeypatch.setattr(value.controller, "_execute_intent", hide_durable_evidence)
    with _wave(value) as wave:
        with pytest.raises(RSILearningError, match="selected_result_invalid"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert wave.channel._closed
        assert not wave.channel._completed_selected_episodes
    assert len(_rows(value)["rsi_python_admissions"]) == 1


@pytest.mark.parametrize("fault", ["source", "state", "checkpoint"])
def test_selected_service_refuses_original_pin_drift_before_ready(tmp_path, monkeypatch, fault):
    value = _fixture(tmp_path, monkeypatch)

    def drift(request):
        if fault == "source":
            value.gateway.fingerprint = "changed-original-source"
        elif fault == "state":
            value.state["phase"] = "unowned-state-change"
        else:
            _forged_checkpoint_append(value, lambda state: state.update(phase="unowned-head-change"))
        return _ack_and_result(value, request)

    value.operation = drift
    with _wave(value) as wave:
        head = wave.checkpoint_sha256
        with pytest.raises((RSILearningError, RSIFingerprintError), match="fingerprint|stale"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        with pytest.raises((RSILearningError, RSIFingerprintError), match="fingerprint|stale"):
            value.controller._python_admission_assert_selected_brs(wave, wave.selected_handoff)
        assert wave.checkpoint_sha256 == head
        assert wave.channel._closed
    assert not _rows(value)["rsi_python_admissions"]


def test_actual_selected_service_source_hooks_allow_another_mutex_observer(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    observations = Queue()
    calls = []
    original_config = value.gateway.rsi_fingerprint_config

    def source_config():
        if get_ident() == value.owner_thread:
            completed = Event()
            observations.put(completed)
            assert completed.wait(timeout=4), "selected source hook retained observation mutex"
            calls.append(get_ident())
        return original_config()

    monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", source_config)

    def observe():
        while (completed := observations.get()) is not None:
            with value.controller._python_admission_brs_observations():
                completed.set()

    with ThreadPoolExecutor(max_workers=1) as observer_pool, _wave(value) as wave:
        observer = observer_pool.submit(observe)
        try:
            execution = value.controller._python_admission_run_selected_brs_intent(wave)
            assert execution.episode.status == "completed"
            assert len(calls) >= 3  # bind, owner service gate, and final result gate
        finally:
            observations.put(None)
            observer.result(timeout=10)


@pytest.mark.parametrize("field", ["ordinal", "lease_nonce", "source_sha256"])
def test_selected_service_refuses_shared_handoff_mutation_after_actual_ack(
    tmp_path, monkeypatch, field,
):
    value = _fixture(tmp_path, monkeypatch)
    original_execute = value.controller._execute_intent

    def mutate_handoff(state, episode_id):
        execution = original_execute(state, episode_id)
        handoff = value.controller._python_admission_brs_wave.selected_handoff
        changed = handoff.ordinal + 1 if field == "ordinal" else "X" * 32 if field == "lease_nonce" else OTHER
        object.__setattr__(handoff, field, changed)
        return execution

    monkeypatch.setattr(value.controller, "_execute_intent", mutate_handoff)
    with _wave(value) as wave:
        with pytest.raises(RSILearningError, match="selected_identity_invalid|handoff_"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert wave.channel._closed
        assert not wave.channel._completed_selected_episodes
    assert len(_rows(value)["rsi_python_admissions"]) == 1
    assert value.ledger.get_episode(value.episode_id).state == "completed"


def test_selected_service_rechecks_original_deadline_without_budget_refresh(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    original_execute = value.controller._execute_intent
    clock = {"now": value.binding.deadline_unix - 1}
    monkeypatch.setattr(rsi_controller.time, "time", lambda: clock["now"])

    def expire_after_ack(state, episode_id):
        execution = original_execute(state, episode_id)
        clock["now"] = value.binding.deadline_unix
        return execution

    monkeypatch.setattr(value.controller, "_execute_intent", expire_after_ack)
    with _wave(value) as wave:
        reserved_budget = deepcopy(wave.budget_state)
        with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert wave.budget_state == reserved_budget
        assert wave.state["budget_state"] == reserved_budget
        assert wave.channel._closed
        assert not wave.channel._completed_selected_episodes
    assert len(_rows(value)["rsi_python_admissions"]) == 1


@pytest.mark.parametrize("fault", ["limit", "deadline", "request_budget"])
def test_selected_service_refuses_original_budget_drift_before_executor_creation(
    tmp_path, monkeypatch, fault,
):
    value = _fixture(tmp_path, monkeypatch)

    def drift(state):
        if fault == "request_budget":
            state["intents"][value.episode_id]["request"]["budget"]["deadline_unix"] += 1
        elif fault == "deadline":
            state["budget_state"]["planned"]["deadline_unix"] += 1
        else:
            state["budget_state"]["planned"]["max_solver_invocations"] = 100

    _forged_checkpoint_append(value, drift)
    value.state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    rows = _rows(value)

    def forbidden_executor(*args, **kwargs):
        pytest.fail("drifted original budget reached selected executor creation")

    monkeypatch.setattr(rsi_controller, "ThreadPoolExecutor", forbidden_executor)
    with _wave(value) as wave:
        with pytest.raises(RSILearningError, match="budget|producer"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert wave.selected_handoff is None
    assert _rows(value) == rows
    assert value.gateway.calls == 0


def test_selected_service_cannot_reuse_consumed_dispatch_or_start_sibling(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        value.controller._python_admission_run_selected_brs_intent(wave)
        rows, calls = _rows(value), value.gateway.calls
        with pytest.raises(RSILearningError, match="selected_busy"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        with ThreadPoolExecutor(max_workers=1) as pool:
            for episode_id in (value.episode_id, value.sibling_id):
                future = pool.submit(
                    value.controller._execute_brs_intent,
                    wave, wave.state, episode_id, wave.selected_handoff,
                )
                with pytest.raises(RSILearningError, match="selected_identity_invalid"):
                    future.result(timeout=10)
        assert _rows(value) == rows and value.gateway.calls == calls
        assert value.ledger.get_episode(value.sibling_id) is None


def test_selected_service_refuses_incomplete_pending_projection_and_parallel_policy(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value, episode_ids=(value.episode_id,)) as wave:
        with pytest.raises(RSILearningError, match="selected_policy_invalid"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert wave.selected_handoff is None
    parallel = _fixture(tmp_path / "parallel", monkeypatch, max_workers=2)
    with _wave(parallel) as wave:
        with pytest.raises(RSILearningError, match="selected_policy_invalid"):
            parallel.controller._python_admission_run_selected_brs_intent(wave)
        assert wave.selected_handoff is None
    assert value.gateway.calls == parallel.gateway.calls == 0


def test_public_staged_native_brs_still_refuses_before_any_execution(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    # The public entrance checks the presence of its native stager before any
    # stage callback. This sentinel grants no native launch or staging authority.
    value.controller.producer_stager = object()
    rows, files = _rows(value), _files(value)
    with pytest.raises(RSILearningError, match="rsi_producer_episode_brs_not_supported"):
        value.controller.run_brs(
            run_id=value.binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="native",
            practices=_decisions(value.controller, value.binding.run_id, 2), max_workers=1,
            budget={"deadline_unix": value.binding.deadline_unix},
        )
    assert _rows(value) == rows and _files(value) == files
    assert value.gateway.calls == 0
