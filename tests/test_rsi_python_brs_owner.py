"""Local BRS owner acknowledgement over inert evidence and real worker futures."""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from threading import Event, get_ident
from time import monotonic

import pytest
from test_rsi_python_admission import DIGEST, _checkpoint_change, _files, _plan, _rows, _setup
from test_rsi_python_admission_flow import _forged_checkpoint_append, _lose_record, _reference

from lunar_evolution import (
    DeterministicCurriculum,
    RSILearningController,
    RSILearningError,
    RSILedger,
    bundle_evolution,
    producer_process,
    rsi_budget,
)
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_gateway import SolverResult
from lunar_evolution.rsi_learning import PracticeEpisode
from lunar_evolution.rsi_python_brs_admission import build_brs_admission_ready


@pytest.fixture(autouse=True)
def no_actual_worker_or_evaluator(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("BRS evidence fixture invoked an actual worker or evaluator")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(producer_process, "run_producer_process", forbidden)
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", forbidden)
    monkeypatch.setattr(
        bundle_evolution.MultiFileCandidatePipeline, "evaluate_draft_non_publishing", forbidden,
    )


def _brs_fixture(tmp_path):
    value = _setup(tmp_path)
    # This scope fixture preserves all original request/proof/evidence bytes. A
    # separate test below creates a genuine BRS run with fresh practice episodes.
    _checkpoint_change(value, lambda state: state.update(mode="brs"))
    return value


@contextmanager
def _wave(value, *, state=None, episode_ids=None):
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1] if state is None else state
    episode_ids = (value.episode_id,) if episode_ids is None else episode_ids
    with (
        value.ledger.controller_lock(value.binding.run_id),
        value.controller._python_admission_brs_wave_scope(state, episode_ids) as wave,
    ):
        yield wave


def _active(value, episode_id=None):
    return value.controller._python_admission_active_brs_worker(
        value.binding.run_id, value.episode_id if episode_id is None else episode_id,
    )


def _request(value, *, wait_check=lambda: None):
    return value.controller._request_python_admission_for_brs_worker(
        value.binding.run_id, value.episode_id, native_plan=value.plan,
        prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
        wait_check=wait_check,
    )


def _mock_fresh_dispatch(monkeypatch, value, wave, operation):
    def execute(state, episode_id):
        with value.controller._python_admission_brs_worker_scope(state, episode_id):
            return operation()

    monkeypatch.setattr(value.controller, "_execute_intent", execute)


def _service_until(value, wave, future):
    deadline = monotonic() + 10
    while not future.done():
        assert monotonic() < deadline, "owner failed to service the waiting BRS worker"
        wave.channel.service(
            lambda ready: value.controller._python_admission_service_brs_ready(wave, ready),
            timeout=0.02,
            observation_scope=lambda: value.controller._python_admission_brs_service_observations(wave),
        )
    return future.result(timeout=1)


def test_dispatched_worker_gets_only_its_own_brs_authority_and_never_owner_lock(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    owner_thread = get_ident()
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            assert wave.owner_thread == owner_thread
            assert wave.state is not None
            with pytest.raises(RSILearningError, match="rsi_python_"):
                _active(value)

            def observe():
                assert get_ident() != owner_thread
                assert not value.ledger.controller_lock_held(value.binding.run_id)
                state, head = _active(value)
                assert state is wave.state and head == wave.checkpoint_sha256
                with pytest.raises(RSILearningError, match="rsi_python_admission_flow_missing"):
                    value.controller._python_admission_active_flow(value.binding.run_id, value.episode_id)
                with pytest.raises(RSILearningError, match="rsi_python_"):
                    _active(value, "foreign-episode")
                return head

            _mock_fresh_dispatch(monkeypatch, value, wave, observe)
            head = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id).result(timeout=5)
            assert head == wave.checkpoint_sha256
    finally:
        pool.shutdown(wait=True)


def test_direct_worker_scope_cannot_create_ready_authority(tmp_path):
    value = _brs_fixture(tmp_path)
    with (
        _wave(value) as wave,
        value.controller._python_admission_brs_worker_scope(wave.state, value.episode_id),
    ):
        with pytest.raises(RSILearningError, match="rsi_python_"):
            _active(value)
        with pytest.raises(RSILearningError, match="rsi_python_"):
            _request(value)
    with pytest.raises(RSILearningError, match="rsi_python_"):
        _active(value)
    assert not _rows(value)["rsi_python_admissions"]


def test_selected_owner_binding_refuses_legacy_drs_projection(tmp_path):
    """The private selected seam never upgrades a legacy DRS checkpoint to BRS authority."""
    value = _brs_fixture(tmp_path)
    with _wave(value) as wave:
        with pytest.raises(
            RSILearningError,
            match="rsi_python_brs_admission_selected_policy_invalid",
        ):
            value.controller._python_admission_bind_selected_brs_handoff(wave)
        assert wave.selected_handoff is None
        assert wave.selected_context is None


def test_nested_unrelated_scope_suppresses_then_restores_fresh_worker_authority(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            def observe():
                state, head = _active(value)
                with (
                    pytest.raises(RuntimeError, match="inert-nested-dispatch"),
                    value.controller._python_admission_brs_worker_scope(state, "foreign-episode"),
                ):
                    with pytest.raises(RSILearningError, match="rsi_python_"):
                        _active(value)
                    raise RuntimeError("inert-nested-dispatch")
                assert _active(value) == (state, head)

            _mock_fresh_dispatch(monkeypatch, value, wave, observe)
            pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id).result(timeout=5)
    finally:
        pool.shutdown(wait=True)


def test_nested_dispatch_wrapper_cannot_mint_another_fresh_worker_token(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            observations = []

            def observe():
                state, head = _active(value)
                observations.append(head)
                for nested_episode_id in (value.episode_id, "foreign-episode"):
                    with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_nested_dispatch$"):
                        value.controller._execute_brs_intent(wave, state, nested_episode_id)
                    assert _active(value) == (state, head)
                return head

            _mock_fresh_dispatch(monkeypatch, value, wave, observe)
            assert pool.submit(
                value.controller._execute_brs_intent, wave, wave.state, value.episode_id,
            ).result(timeout=5) == wave.checkpoint_sha256
            assert observations == [wave.checkpoint_sha256]
            assert not _rows(value)["rsi_python_admissions"]
    finally:
        pool.shutdown(wait=True)


def test_recovered_episode_has_no_ready_authority(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    recovered = object()
    observed = []

    def resume(head, **kwargs):
        assert head.logical_id == value.episode_id and kwargs["request_hint"] == value.request
        with pytest.raises(RSILearningError, match="rsi_python_"):
            _active(value)
        state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
        # A recovered callback cannot turn the dispatch token into fresh scope,
        # even if it invokes the private scope directly with the original state.
        with (
            value.controller._python_admission_brs_worker_scope(
                value.controller._python_admission_brs_wave.state, value.episode_id,
            ),
            pytest.raises(RSILearningError, match="rsi_python_"),
        ):
            _active(value)
        assert state["mode"] == "brs"
        observed.append(head)
        return recovered

    monkeypatch.setattr(value.controller, "_resume_episode_execution", resume)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            assert pool.submit(
                value.controller._execute_brs_intent, wave, wave.state, value.episode_id,
            ).result(timeout=5) is recovered
    finally:
        pool.shutdown(wait=True)
    assert len(observed) == 1


@pytest.mark.parametrize("mutation", ["state", "durable-head", "sidecar"])
def test_changed_wave_identity_or_state_is_refused_without_adoption(tmp_path, monkeypatch, mutation):
    value = _brs_fixture(tmp_path)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            if mutation == "state":
                wave.state["phase"] = "inert-unrelated-change"
            elif mutation == "durable-head":
                _forged_checkpoint_append(value, lambda state: state.update(phase="inert-unrelated-change"))
            else:
                value.controller.producer_sidecar = object()
            before = deepcopy(wave.state)
            rows, files = _rows(value), _files(value)
            _mock_fresh_dispatch(monkeypatch, value, wave, lambda: _active(value))
            with pytest.raises(RSILearningError, match="rsi_python_"):
                pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id).result(timeout=5)
            assert wave.state == before
            assert (_rows(value), _files(value)) == (rows, files)
    finally:
        pool.shutdown(wait=True)


def test_ready_owner_pin_acknowledges_only_reference_and_exact_captured_head(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    original_rows, original_files = _rows(value), _files(value)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            before = deepcopy(wave.state)
            old_head = wave.checkpoint_sha256
            _mock_fresh_dispatch(monkeypatch, value, wave, lambda: _request(value))
            future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id)
            record_digest = _service_until(value, wave, future)
            retained = value.controller.validate_python_admission(
                value.binding.run_id, value.episode_id, native_plan=value.plan,
                prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
                expected_record_sha256=record_digest,
            )
            expected = deepcopy(before)
            expected["python_admission_refs"] = {value.episode_id: _reference(value, retained)}
            assert wave.state == expected
            assert value.ledger.controller_checkpoint(value.binding.run_id) == (wave.checkpoint_sha256, expected)
            assert wave.checkpoint_sha256 != old_head
            assert wave.admitted_episode_id == value.episode_id
            assert retained.production_admission is False
            changed = _rows(value)
            for table in original_rows:
                if table not in {"rsi_python_admissions", "rsi_controller_journal"}:
                    assert changed[table] == original_rows[table]
    finally:
        pool.shutdown(wait=True)
    assert _files(value) == original_files


@pytest.mark.parametrize("interruption", ["return-lost", "unrelated-ack-head"])
def test_durable_pin_ack_failure_keeps_obligation_and_original_wave_stale(tmp_path, monkeypatch, interruption):
    value = _brs_fixture(tmp_path)
    original_pin = value.ledger.pin_python_admission_record
    retained = []

    def interrupted(record, **kwargs):
        result = original_pin(record, **kwargs)
        retained.append(result)
        if interruption == "return-lost":
            raise RSILearningError("fixture_brs_pin_return_unknown")
        _forged_checkpoint_append(value, lambda state: state.update(phase="inert-after-pin-drift"))
        return result

    monkeypatch.setattr(value.ledger, "pin_python_admission_record", interrupted)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            before, old_head = deepcopy(wave.state), wave.checkpoint_sha256
            _mock_fresh_dispatch(monkeypatch, value, wave, lambda: _request(value))
            future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id)
            with pytest.raises(RSILearningError):
                _service_until(value, wave, future)
            with pytest.raises(RSILearningError, match="rsi_python_brs_admission_handler_failed"):
                future.result(timeout=5)
            assert len(retained) == 1
            record, _ = retained[0]
            assert wave.state == before and wave.checkpoint_sha256 == old_head
            durable = value.ledger.controller_checkpoint(value.binding.run_id)[1]
            assert durable["python_admission_refs"] == {value.episode_id: _reference(value, record)}
            assert len(_rows(value)["rsi_python_admissions"]) == 1
    finally:
        pool.shutdown(wait=True)


def test_cancel_after_durable_pin_before_channel_delivery_retains_stale_wave(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    control = SolveExecutionControl(30.0)
    requester_stopped = Event()
    original_service = value.controller._python_admission_service_brs_ready
    retained = []
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            before, old_head = deepcopy(wave.state), wave.checkpoint_sha256

            def service_then_cancel(active_wave, ready):
                digest = original_service(active_wave, ready)
                retained.append(digest)
                assert wave.state["python_admission_refs"][value.episode_id]["record_sha256"] == digest
                control.cancel()
                assert requester_stopped.wait(timeout=5), "ready waiter held the observation lock during cancellation"
                return digest

            def request_then_stop():
                try:
                    return _request(value, wait_check=control.check)
                finally:
                    requester_stopped.set()

            monkeypatch.setattr(value.controller, "_python_admission_service_brs_ready", service_then_cancel)
            _mock_fresh_dispatch(monkeypatch, value, wave, request_then_stop)
            future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id)
            with pytest.raises(RSILearningError, match="rsi_python_brs_admission_ack_invalid"):
                _service_until(value, wave, future)
            with pytest.raises(SolveExecutionCancelled):
                future.result(timeout=5)
            assert len(retained) == 1
            assert wave.state == before and wave.checkpoint_sha256 == old_head
            assert "python_admission_refs" not in wave.state
            assert len(_rows(value)["rsi_python_admissions"]) == 1
            durable = value.ledger.controller_checkpoint(value.binding.run_id)[1]
            assert durable["python_admission_refs"][value.episode_id]["record_sha256"] == retained[0]
    finally:
        pool.shutdown(wait=True)


def test_owner_uses_original_cas_when_durable_checkpoint_changes_after_evidence(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    original_pin = value.ledger.pin_python_admission_record
    attempts = []

    def drift_then_pin(record, **kwargs):
        attempts.append(kwargs["expected_checkpoint_sha256"])
        _forged_checkpoint_append(value, lambda state: state.update(phase="inert-cas-race"))
        return original_pin(record, **kwargs)

    monkeypatch.setattr(value.ledger, "pin_python_admission_record", drift_then_pin)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            before, old_head = deepcopy(wave.state), wave.checkpoint_sha256
            _mock_fresh_dispatch(monkeypatch, value, wave, lambda: _request(value))
            future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id)
            with pytest.raises(RSILearningError, match="conflict"):
                _service_until(value, wave, future)
            with pytest.raises(RSILearningError, match="rsi_python_brs_admission_handler_failed"):
                future.result(timeout=5)
            assert attempts == [old_head]
            assert wave.state == before and wave.checkpoint_sha256 == old_head
            assert not _rows(value)["rsi_python_admissions"]
            assert "python_admission_refs" not in value.ledger.controller_checkpoint(value.binding.run_id)[1]
    finally:
        pool.shutdown(wait=True)


def test_owner_save_refuses_checkpoint_drift_after_producer_entry_gate(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    original_gate = value.controller._validate_run_checkpoint_producer_binding
    gates = []
    with _wave(value) as wave:
        record = value.ledger.get_run(value.binding.run_id)
        captured_head, captured_payload = wave.checkpoint_sha256, wave.payload
        budget = deepcopy(wave.state["budget_state"])
        wave.state.update(phase="evaluated", current_episode_id=value.episode_id)
        expected_owner_state = deepcopy(wave.state)

        def gate_then_drift(run_record, state):
            original_gate(run_record, state)
            gates.append(run_record.logical_id)
            _forged_checkpoint_append(value, lambda durable: durable.update(phase="inert-unrelated-drift"))

        monkeypatch.setattr(value.controller, "_validate_run_checkpoint_producer_binding", gate_then_drift)
        with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_stale$"):
            value.controller._save_flow(record, wave.state)
        assert gates == [value.binding.run_id]
        durable_head, durable_state = value.ledger.controller_checkpoint(value.binding.run_id)
        assert durable_head != captured_head and durable_state["phase"] == "inert-unrelated-drift"
        assert wave.checkpoint_sha256 == captured_head and wave.payload == captured_payload
        assert wave.state == expected_owner_state
        assert wave.state["budget_state"] == budget
        assert "python_admission_refs" not in wave.state
        assert not _rows(value)["rsi_python_admissions"]


def test_wave_exit_closes_channel_before_waiting_worker_shutdown(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    entered = Event()
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            def waiting():
                entered.set()
                return _request(value)

            _mock_fresh_dispatch(monkeypatch, value, wave, waiting)
            future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id)
            assert entered.wait(timeout=5)
        with pytest.raises(RSILearningError, match="rsi_python_"):
            future.result(timeout=5)
    finally:
        pool.shutdown(wait=True)
    assert not _rows(value)["rsi_python_admissions"]


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_wait_rechecks_execution_control_and_removes_unhandled_request(tmp_path, monkeypatch, stop):
    value = _brs_fixture(tmp_path)
    clock = {"now": 100.0}
    control = SolveExecutionControl(30.0, clock=lambda: clock["now"])
    waiting, calls = Event(), []
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            before = deepcopy(wave.state)
            rows, files = _rows(value), _files(value)

            def check():
                calls.append(1)
                if len(calls) >= 2:
                    waiting.set()
                control.check()

            _mock_fresh_dispatch(monkeypatch, value, wave, lambda: _request(value, wait_check=check))
            future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id)
            assert waiting.wait(timeout=5)
            if stop == "cancel":
                control.cancel()
            else:
                clock["now"] = control.deadline
            expected = SolveExecutionCancelled if stop == "cancel" else SolveExecutionBudgetExceeded
            with pytest.raises(expected):
                future.result(timeout=5)
            assert wave.channel.service(
                lambda ready: pytest.fail("cancelled ready request reached owner pin"), timeout=0.01,
            ) is False
            assert len(calls) >= 3 and wave.state == before
            assert (_rows(value), _files(value)) == (rows, files)
    finally:
        pool.shutdown(wait=True)


def test_wait_rechecks_original_rsi_deadline_without_refreshing_reserved_budget(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    waiting, calls = Event(), []
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            before, budget = deepcopy(wave.state), deepcopy(wave.budget_state)
            clock = {"now": value.binding.deadline_unix - 1}
            monkeypatch.setattr(rsi_budget.time, "time", lambda: clock["now"])

            def wait_check():
                calls.append(1)
                if len(calls) >= 2:
                    waiting.set()

            _mock_fresh_dispatch(monkeypatch, value, wave, lambda: _request(value, wait_check=wait_check))
            future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id)
            assert waiting.wait(timeout=5)
            clock["now"] = value.binding.deadline_unix
            with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
                future.result(timeout=5)
            assert wave.channel.service(
                lambda ready: pytest.fail("expired RSI ready request reached owner pin"), timeout=0.01,
            ) is False
            assert wave.state == before and wave.budget_state == budget
            assert not _rows(value)["rsi_python_admissions"]
    finally:
        pool.shutdown(wait=True)


def test_sibling_proof_observation_waits_until_exact_owner_ack(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    pin_reached, sibling_entered, sibling_finished = Event(), Event(), Event()
    original_pin = value.ledger.pin_python_admission_record
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        with _wave(value) as wave:
            def pin_between_durable_and_memory(record, **kwargs):
                result = original_pin(record, **kwargs)
                assert "python_admission_refs" not in wave.state
                assert "python_admission_refs" in value.ledger.controller_checkpoint(value.binding.run_id)[1]
                pin_reached.set()
                assert sibling_entered.wait(timeout=5)
                assert not sibling_finished.wait(timeout=0.05), "sibling observed the durable pin before in-memory acknowledgement"
                return result

            def sibling():
                assert pin_reached.wait(timeout=5)
                sibling_entered.set()
                try:
                    value.controller._validate_producer_checkpoint(value.binding.run_id, wave.state)
                    return deepcopy(wave.state["python_admission_refs"])
                finally:
                    sibling_finished.set()

            monkeypatch.setattr(value.ledger, "pin_python_admission_record", pin_between_durable_and_memory)
            _mock_fresh_dispatch(monkeypatch, value, wave, lambda: _request(value))
            observer = pool.submit(sibling)
            future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id)
            digest = _service_until(value, wave, future)
            assert observer.result(timeout=5) == wave.state["python_admission_refs"]
            assert wave.state["python_admission_refs"][value.episode_id]["record_sha256"] == digest
    finally:
        pool.shutdown(wait=True)


def test_wave_refuses_second_distinct_python_child_and_duplicate_ready(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    sibling = value.episode_id + "-ordinary-sibling"

    def add_sibling(state):
        episode = replace(PracticeEpisode.from_dict(state["intents"][value.episode_id]["episode"]), episode_id=sibling)
        state["intents"][sibling] = {
            "episode": episode.to_record_dict(), "request": replace(value.request, episode_id=sibling).to_dict(),
        }

    _checkpoint_change(value, add_sibling)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value, episode_ids=(value.episode_id, sibling)) as wave:
            _mock_fresh_dispatch(monkeypatch, value, wave, lambda: _request(value))
            future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id)
            _service_until(value, wave, future)
            before, rows, files = deepcopy(wave.state), _rows(value), _files(value)
            # The second child is refused before any attempt to reuse the original
            # first child's plan, handoff or globally unique attempt.
            ready = build_brs_admission_ready(value.binding.run_id, sibling, canonical_json({
                "native_plan": value.plan.to_dict(), "prepared_journal": value.journal.to_dict(),
                "expected_anchor_sha256": value.anchor.anchor_sha256,
            }))
            with pytest.raises(RSILearningError, match="rsi_python_brs_admission_multiple_children"):
                value.controller._python_admission_service_brs_ready(wave, ready)
            duplicate = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id)
            with pytest.raises(RSILearningError, match="rsi_python_"):
                duplicate.result(timeout=5)
            assert wave.state == before
            assert (_rows(value), _files(value)) == (rows, files)
    finally:
        pool.shutdown(wait=True)


def test_owner_replay_never_repairs_a_missing_required_admission_row(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with _wave(value) as wave:
            _mock_fresh_dispatch(monkeypatch, value, wave, lambda: _request(value))
            future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, value.episode_id)
            digest = _service_until(value, wave, future)
            record = value.controller.validate_python_admission(
                value.binding.run_id, value.episode_id, native_plan=value.plan,
                prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
                expected_record_sha256=digest,
            )
            _lose_record(value, record, "missing")
            before, rows, files = deepcopy(wave.state), _rows(value), _files(value)
            ready = build_brs_admission_ready(value.binding.run_id, value.episode_id, canonical_json({
                "native_plan": value.plan.to_dict(), "prepared_journal": value.journal.to_dict(),
                "expected_anchor_sha256": value.anchor.anchor_sha256,
            }))
            with pytest.raises(RSILearningError, match="rsi_python_"):
                value.controller._python_admission_service_brs_ready(wave, ready)
            assert wave.state == before
            assert (_rows(value), _files(value)) == (rows, files)
            assert not _rows(value)["rsi_python_admissions"]
    finally:
        pool.shutdown(wait=True)


def _decisions(controller, run_id, count):
    target = controller._target_episode(
        run_id, run_id + "-target-seed", {
            "contract_sha256": DIGEST, "evaluator_sha256": DIGEST,
            "environment_sha256": DIGEST, "solver_id": "native",
        }, 0,
    )
    curriculum = DeterministicCurriculum()
    return [curriculum.choose(target=target, diagnosis=f"gap-{i}", wave=0, ordinal=i) for i in range(count)]


def test_actual_brs_futures_service_later_ready_before_ordinal_save_with_fewer_workers(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    ledger = RSILedger(tmp_path / "brs-owner.sqlite3")
    owner_thread = get_ident()
    acknowledged, queued_sibling = Event(), Event()
    events, requests, records = [], [], []
    controller = None

    class InertGateway:
        def rsi_fingerprint_config(self):
            return {"fixture": "brs-owner-ready-ack"}

        def run(self, request):
            ordinal = int(request.episode_id.rsplit("-", 1)[1])
            assert get_ident() != owner_thread
            assert not ledger.controller_lock_held(value.binding.run_id)
            requests.append(request)
            state, _head = controller._python_admission_active_brs_worker(
                value.binding.run_id, request.episode_id,
            )
            assert len(state["intents"]) == 3
            assert state["budget_state"]["consumed"]["solver_invocations"] == 3
            result = SolverResult(
                episode_id=request.episode_id, request_sha256=request.digest(), status="completed",
                candidate_receipt_sha256=DIGEST, execution_receipt_sha256=DIGEST,
                official_evaluation_receipt_sha256=DIGEST, trace_digest=DIGEST,
                solver_score=1.0, terminal_reason="inert-brs-owner-fixture",
            )
            if ordinal == 0:
                # This fixture waits through repeated original-evidence observations,
                # including sibling settlement and queued dispatch on CI filesystems.
                # The retained execution deadline remains the production budget.
                assert acknowledged.wait(timeout=60), "owner blocked on ordinal 0 instead of servicing ordinal 1"
                assert queued_sibling.wait(timeout=60), "queued ordinary sibling never received its executor slot"
            elif ordinal == 1:
                plan = _plan(value.binding, request, controller.snapshot)
                claim = ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
                events.append("ready-1")
                digest = controller._request_python_admission_for_brs_worker(
                    value.binding.run_id, request.episode_id, native_plan=plan,
                    prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
                    wait_check=lambda: None,
                )
                records.append((request.episode_id, digest))
                assert state["python_admission_refs"][request.episode_id]["record_sha256"] == digest
                ledger.publish_native_episode_result(
                    request, plan_sha256=plan.plan_sha256, result=result, expected_claim=claim,
                )
                events.append("ack-1")
                acknowledged.set()
            else:
                assert acknowledged.is_set()
                assert len(state["python_admission_refs"]) == 1
                controller._validate_producer_checkpoint(value.binding.run_id, state)
                queued_sibling.set()
            return result

    controller = RSILearningController(
        InertGateway(), ledger=ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.workspace,
    )
    original_lock, original_save = ledger.controller_lock, controller._save_flow

    @contextmanager
    def owner_lock_only(run_id):
        if run_id == value.binding.run_id:
            assert get_ident() == owner_thread, "worker attempted to acquire the owning controller lock"
        with original_lock(run_id):
            yield

    def save(record, state):
        assert get_ident() == owner_thread
        if state["phase"] == "evaluated":
            events.append("save-" + state["current_episode_id"].rsplit("-", 1)[1])
        return original_save(record, state)

    monkeypatch.setattr(ledger, "controller_lock", owner_lock_only)
    monkeypatch.setattr(controller, "_save_flow", save)
    result = controller.run_brs(
        run_id=value.binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
        environment_sha256=DIGEST, solver_id="native", practices=_decisions(controller, value.binding.run_id, 3),
        max_workers=2, budget={"deadline_unix": value.binding.deadline_unix},
    )
    assert result.status == "completed"
    assert [item.episode.ordinal for item in result.practice_episodes] == [0, 1, 2]
    assert [item.trigger for item in result.memory_snapshot.items] == ["gap-0", "gap-1", "gap-2"]
    assert events.index("ready-1") < events.index("ack-1") < events.index("save-0")
    assert [event for event in events if event.startswith("save-")] == ["save-0", "save-1", "save-2"]
    assert len(requests) == 3 and len(records) == 1
    durable = ledger.controller_checkpoint(value.binding.run_id)[1]
    assert durable["status"] == "completed"
    assert durable["python_admission_refs"][records[0][0]]["record_sha256"] == records[0][1]
    assert len({request.memory_snapshot_sha256 for request in requests}) == 1
    assert not (value.workspace / "evolution" / "producer-publication.json").exists()
