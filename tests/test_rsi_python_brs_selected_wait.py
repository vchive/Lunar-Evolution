"""Selected owner waiting observes fixed pins while a real ACKed worker settles."""

from __future__ import annotations

import hashlib
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from threading import Event, get_ident

import pytest
import test_rsi_python_brs_selected_service as selected
from test_rsi_python_admission import OTHER, _rows
from test_rsi_python_admission_flow import _forged_checkpoint_append

from lunar_evolution import RSILearningError, rsi_controller
from lunar_evolution.rsi_fingerprint import RSIFingerprintError

no_external_execution = selected.no_external_execution


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("selected wait fixtures must not connect")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.mark.parametrize("fault", ["worker-thread", "unowned"])
def test_selected_wait_requires_actual_owner_before_any_source_hook(tmp_path, monkeypatch, fault):
    value = selected._fixture(tmp_path, monkeypatch)
    with selected._wave(value) as wave:
        handoff = value.controller._python_admission_bind_selected_brs_handoff(wave)
        rows, files = _rows(value), selected._evidence_files(value)
        head, payload = wave.checkpoint_sha256, wave.payload

        def forbidden(*_args, **_kwargs):
            pytest.fail("unowned wait reached a source/configuration hook")

        monkeypatch.setattr(value.controller, "_python_admission_brs_fixed_pins", forbidden)

        def observe():
            with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_identity_invalid$"):
                value.controller._python_admission_assert_selected_brs_wait(wave, handoff)

        if fault == "worker-thread":
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(observe).result(timeout=10)
        else:
            with monkeypatch.context() as patch:
                patch.setattr(value.ledger, "controller_lock_held", lambda _run_id: False)
                observe()
        assert wave.checkpoint_sha256 == head and wave.payload == payload
        assert wave.selected_return is None
        assert not wave.channel._completed_selected_episodes
        assert _rows(value) == rows and selected._evidence_files(value) == files
        assert value.gateway.calls == 0


@pytest.mark.parametrize("path", ["fixed-default", "selected-full"])
def test_fixed_and_selected_pins_run_producer_and_staging_validation_once(
    tmp_path, monkeypatch, path,
):
    value = selected._fixture(tmp_path, monkeypatch)
    counts = {"checkpoint": 0, "original": 0, "staging": 0}
    original_checkpoint = value.controller._validate_producer_checkpoint
    original_binding = value.controller._validate_original_producer_checkpoint
    original_staging = value.controller._validate_producer_staging

    def checkpoint(run_id, state):
        counts["checkpoint"] += 1
        return original_checkpoint(run_id, state)

    def binding(run_id, state):
        counts["original"] += 1
        return original_binding(run_id, state)

    def staging(record, state):
        counts["staging"] += 1
        return original_staging(record, state)

    monkeypatch.setattr(value.controller, "_validate_producer_checkpoint", checkpoint)
    monkeypatch.setattr(value.controller, "_validate_original_producer_checkpoint", binding)
    monkeypatch.setattr(value.controller, "_validate_producer_staging", staging)

    with selected._wave(value) as wave:
        if path == "fixed-default":
            context = value.controller._python_admission_brs_fixed_pins(wave)
            expected_checkpoint_calls = 0
        else:
            context = value.controller._python_admission_brs_selected_pins_once(wave)
            expected_checkpoint_calls = 1
        assert context.head_sha256 == wave.checkpoint_sha256
        assert context.state_sha256 == hashlib.sha256(wave.payload).hexdigest()

    assert counts == {"checkpoint": expected_checkpoint_calls, "original": 1, "staging": 1}


def test_selected_pins_allows_prewrite_transition_with_one_full_producer_gate(tmp_path, monkeypatch):
    value = selected._fixture(tmp_path, monkeypatch)
    counts = {"checkpoint": 0, "original": 0, "staging": 0}
    original_checkpoint = value.controller._validate_producer_checkpoint
    original_binding = value.controller._validate_original_producer_checkpoint
    original_staging = value.controller._validate_producer_staging

    def checkpoint(run_id, state):
        counts["checkpoint"] += 1
        return original_checkpoint(run_id, state)

    def binding(run_id, state):
        counts["original"] += 1
        return original_binding(run_id, state)

    def staging(record, state):
        counts["staging"] += 1
        return original_staging(record, state)

    monkeypatch.setattr(value.controller, "_validate_producer_checkpoint", checkpoint)
    monkeypatch.setattr(value.controller, "_validate_original_producer_checkpoint", binding)
    monkeypatch.setattr(value.controller, "_validate_producer_staging", staging)
    with (selected._wave(value) as wave,
          value.controller._python_admission_brs_checkpoint_transition(wave)):
        context = value.controller._python_admission_brs_selected_pins_once(wave)
        assert context.head_sha256 == wave.checkpoint_sha256
        assert context.state_sha256 == hashlib.sha256(wave.payload).hexdigest()
    assert counts == {"checkpoint": 1, "original": 1, "staging": 1}


def test_selected_pins_bind_full_validation_to_capture_and_reject_adopted_successor(
    tmp_path, monkeypatch,
):
    value = selected._fixture(tmp_path, monkeypatch)
    with selected._wave(value) as wave:
        captured_payload = wave.payload
        captured_state = json.loads(captured_payload)
        captured_head = wave.checkpoint_sha256
        original_checkpoint = value.controller._validate_producer_checkpoint
        original_read_only = value.ledger.read_only_observations
        full_states = []
        read_only_depth = 0
        successor_adopted = False

        def transition_after_validation(run_id, state):
            full_states.append(deepcopy(state))
            return original_checkpoint(run_id, state)

        def adopt_successor_after_read_only_gate():
            nonlocal successor_adopted
            successor = deepcopy(captured_state)
            successor["transition_probe"] = True
            successor_payload = value.controller._python_admission_flow_payload(successor)
            with value.controller._python_admission_brs_checkpoint_transition(wave):
                next_head = value.ledger.write_controller_checkpoint(
                    value.binding.run_id, successor, expected_sha256=wave.checkpoint_sha256,
                )
                wave.state.clear()
                wave.state.update(successor)
                wave.payload = successor_payload
                wave.checkpoint_sha256 = next_head
            successor_adopted = True

        @contextmanager
        def read_only_observations():
            nonlocal read_only_depth
            read_only_depth += 1
            try:
                with original_read_only():
                    yield
            finally:
                read_only_depth -= 1
                if read_only_depth == 0 and full_states and not successor_adopted:
                    # Model a concurrent checkpoint transition after the selected
                    # full validator releases its read-only snapshot and before
                    # the selected gate performs its final CAS.
                    adopt_successor_after_read_only_gate()

        monkeypatch.setattr(
            value.controller, "_validate_producer_checkpoint", transition_after_validation,
        )
        monkeypatch.setattr(value.ledger, "read_only_observations", read_only_observations)
        history_before = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_stale$"):
            value.controller._python_admission_brs_selected_pins_once(wave)

        assert full_states == [captured_state]
        assert captured_payload != wave.payload
        assert captured_head != wave.checkpoint_sha256
        assert successor_adopted is True
        assert wave.checkpoint_transition is False
        assert len(value.ledger.controller_checkpoint_history(value.binding.run_id)) == len(history_before) + 1
        durable = value.ledger.controller_checkpoint(value.binding.run_id)
        assert durable == (wave.checkpoint_sha256, wave.state)


def test_selected_wait_allows_real_ack_worker_to_settle_during_fixed_source_observation(
    tmp_path, monkeypatch,
):
    value = selected._fixture(tmp_path, monkeypatch)
    pending, release, worker_finished = Event(), Event(), Event()
    waiting = Event()
    interleaving = []
    complete_gates = []
    original_append = value.ledger.append_episode_record
    original_admission = value.ledger.python_admission_record
    original_execute = value.controller._execute_intent
    original_wait = value.controller._python_admission_assert_selected_brs_wait
    original_full = value.controller._python_admission_assert_selected_brs
    original_config = value.gateway.rsi_fingerprint_config

    def append(episode, **options):
        if (episode.status == "completed" and get_ident() != value.owner_thread
                and not pending.is_set()):
            assert "ack" in [event[0] for event in value.events]
            assert value.ledger.get_episode(episode.episode_id).state == "running"
            pending.set()
            assert release.wait(timeout=20), "owner never observed fixed invocation pins"
            interleaving.append("worker-terminal-append")
        return original_append(episode, **options)

    def admission(*arguments, **options):
        if get_ident() == value.owner_thread and waiting.is_set():
            assert options.get("expected_episode_record_sha256") is None, (
                "pending owner compared a changing episode head"
            )
        return original_admission(*arguments, **options)

    def execute(*arguments, **options):
        try:
            return original_execute(*arguments, **options)
        finally:
            worker_finished.set()

    def wait(wave, handoff):
        if value.episode_id in wave.state.get("python_admission_refs", {}):
            assert pending.wait(timeout=20), "ACKed worker never reached terminal append"
            waiting.set()
        try:
            return original_wait(wave, handoff)
        finally:
            waiting.clear()

    def source_config():
        if get_ident() == value.owner_thread and waiting.is_set() and not release.is_set():
            assert value.ledger.get_episode(value.episode_id).state == "running"
            interleaving.append("owner-fixed-source")
            release.set()
            # Completion performs real admission checks on the other thread. This
            # also proves source hooks retain neither the short mutex nor a DB writer.
            assert worker_finished.wait(timeout=20), "source hook blocked worker settlement"
            assert value.ledger.get_episode(value.episode_id).state == "completed"
            interleaving.append("owner-source-after-completion")
        return original_config()

    def complete(wave, handoff):
        if get_ident() == value.owner_thread:
            complete_gates.append((worker_finished.is_set(), wave.channel._closed))
        return original_full(wave, handoff)

    monkeypatch.setattr(value.ledger, "append_episode_record", append)
    monkeypatch.setattr(value.ledger, "python_admission_record", admission)
    monkeypatch.setattr(value.controller, "_execute_intent", execute)
    monkeypatch.setattr(value.controller, "_python_admission_assert_selected_brs_wait", wait)
    monkeypatch.setattr(value.controller, "_python_admission_assert_selected_brs", complete)
    monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", source_config)
    with selected._wave(value) as wave:
        original_close = wave.channel.close

        def close():
            try:
                original_close()
            finally:
                release.set()

        monkeypatch.setattr(wave.channel, "close", close)
        execution = value.controller._python_admission_run_selected_brs_intent(wave)
        assert execution.episode.status == "completed"
        assert wave.channel._completed_selected_episodes == {value.episode_id}
        assert wave.selected_return is not None
        assert value.ledger.episode_result(value.episode_id) == (execution.request, execution.result)
        assert wave.state["executions"] == {}
        assert value.ledger.controller_checkpoint(value.binding.run_id) == (
            wave.checkpoint_sha256, wave.state,
        )
    assert interleaving == [
        "owner-fixed-source", "worker-terminal-append", "owner-source-after-completion",
    ]
    assert (False, False) in complete_gates  # real ready service before ACK delivery
    assert complete_gates[-2:] == [(True, False), (True, True)]
    assert len(_rows(value)["rsi_python_admissions"]) == 1
    assert value.ledger.get_episode(value.sibling_id) is None


@pytest.mark.parametrize("fault", ["source", "deadline", "budget", "handoff", "state", "checkpoint", "proof"])
def test_selected_wait_refuses_drift_after_real_ack_before_any_result(
    tmp_path, monkeypatch, fault,
):
    value = selected._fixture(tmp_path, monkeypatch)
    acknowledged, release, released_by_close, stopped = Event(), Event(), Event(), Event()
    captured = []
    original_request = value.controller._request_python_admission_for_brs_worker
    original_wait = value.controller._python_admission_assert_selected_brs_wait

    class StopAfterAck(BaseException):
        pass

    def request(*arguments, **options):
        original_request(*arguments, **options)
        assert get_ident() != value.owner_thread
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.episode_result(value.episode_id) is None
        acknowledged.set()
        try:
            assert release.wait(timeout=20), "rejected owner never closed the channel"
            released_by_close.set()
            raise StopAfterAck()
        finally:
            stopped.set()

    def wait(wave, handoff):
        if value.episode_id in wave.state.get("python_admission_refs", {}) and not captured:
            assert acknowledged.wait(timeout=20), "worker did not accept the actual ACK"
            captured.append((wave.checkpoint_sha256, wave.payload, deepcopy(wave.budget_state),
                             value.ledger.get_episode(value.episode_id), _rows(value)))
            if fault == "source":
                value.gateway.fingerprint = "drift-after-actual-ack"
            elif fault == "deadline":
                monkeypatch.setattr(rsi_controller.time, "time", lambda: value.binding.deadline_unix)
            elif fault == "budget":
                wave.state["budget_state"]["planned"]["deadline_unix"] += 1
            elif fault == "handoff":
                object.__setattr__(handoff, "source_sha256", OTHER)
            elif fault == "state":
                wave.state["phase"] = "unowned-wait-mutation"
            elif fault == "checkpoint":
                _forged_checkpoint_append(value, lambda state: state.update(phase="unowned-wait-head"))
            else:
                (value.batch / "python-producer-binding.json").write_bytes(b"changed immutable sidecar")
        return original_wait(wave, handoff)

    monkeypatch.setattr(value.controller, "_request_python_admission_for_brs_worker", request)
    monkeypatch.setattr(value.controller, "_python_admission_assert_selected_brs_wait", wait)
    with selected._wave(value) as wave:
        shutdown = selected._track_close_and_shutdown(monkeypatch, wave)
        original_close = wave.channel.close

        def close():
            try:
                original_close()
            finally:
                release.set()

        monkeypatch.setattr(wave.channel, "close", close)
        with pytest.raises((RSILearningError, RSIFingerprintError),
                           match="fingerprint|budget_exhausted|stale|selected_identity_invalid|sidecar_invalid"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        assert acknowledged.is_set() and released_by_close.is_set() and stopped.is_set()
        assert shutdown == ["close", "shutdown"]
        head, payload, budget, episode, before = captured[0]
        assert wave.checkpoint_sha256 == head and wave.payload == payload
        assert wave.budget_state == budget
        assert wave.channel._closed and not wave.channel._completed_selected_episodes
        assert wave.selected_return is None
        assert value.ledger.get_episode(value.episode_id) == episode
        after = _rows(value)
        if fault == "checkpoint":
            assert len(after["rsi_controller_journal"]) == len(before["rsi_controller_journal"]) + 1
            after["rsi_controller_journal"] = before["rsi_controller_journal"]
        assert after == before
    assert value.ledger.episode_result(value.episode_id) is None
    assert value.ledger.get_episode(value.sibling_id) is None
    assert value.gateway.calls == 1
