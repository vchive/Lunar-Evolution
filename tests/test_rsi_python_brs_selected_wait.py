"""Selected owner waiting observes fixed pins while a real ACKed worker settles."""

from __future__ import annotations

import socket
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
