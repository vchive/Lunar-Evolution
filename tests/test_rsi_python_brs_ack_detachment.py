"""Selected owner acknowledgements do not alias worker-returned frozen DTOs."""

from __future__ import annotations

import pytest
import test_rsi_python_brs_admission as admission_cases
from test_rsi_python_brs_admission import OTHER, _ready
from test_rsi_python_brs_handoff import CONTEXT, RUN, _handoff, _preflight

from lunar_evolution.rsi_python_brs_admission import (
    BRSAdmissionAck,
    BRSAdmissionChannel,
    RSIPythonBRSAdmissionError,
)

threads = admission_cases.threads


def _acknowledged(threads):
    preflight, handoff = _preflight(), _handoff()
    channel = BRSAdmissionChannel(RUN, (handoff.episode_id,))
    threads.channels.append(channel)
    channel.bind_selected_handoff(handoff, preflight, CONTEXT)
    ready = _ready(handoff.episode_id, run=RUN)
    worker = threads.request(channel, ready)
    worker.wait_posted()
    assert channel.service(lambda _ready: OTHER)
    worker.wait_done()
    assert worker.error is None
    expected = BRSAdmissionAck(RUN, handoff.episode_id, ready.request_sha256, OTHER)
    assert worker.result == expected
    return channel, handoff, worker, expected


@pytest.mark.parametrize("field,value", [
    ("run_id", "different-run"),
    ("episode_id", "different-episode"),
    ("request_sha256", "c" * 64),
    ("record_sha256", "d" * 64),
])
def test_worker_can_modify_its_return_without_changing_owner_ack(threads, field, value):
    channel, handoff, worker, expected = _acknowledged(threads)
    pending = channel._requests[handoff.episode_id]
    assert worker.result is not pending.ack
    object.__setattr__(worker.result, field, value)
    assert pending.ack == expected
    channel.complete_selected_handoff(handoff.episode_id)
    assert channel._selected_episode_id is None
    assert handoff.episode_id in channel._completed_selected_episodes


@pytest.mark.parametrize("field,value", [
    ("run_id", "different-run"),
    ("episode_id", "different-episode"),
    ("request_sha256", "c" * 64),
    ("record_sha256", "d" * 64),
])
def test_completion_refuses_retained_ack_drift_without_retiring_selection(threads, field, value):
    channel, handoff, _worker, _expected = _acknowledged(threads)
    pending = channel._requests[handoff.episode_id]
    object.__setattr__(pending.ack, field, value)
    with pytest.raises(RSIPythonBRSAdmissionError, match="ack_mismatch"):
        channel.complete_selected_handoff(handoff.episode_id)
    assert channel._selected_episode_id == handoff.episode_id
    assert handoff.episode_id not in channel._completed_selected_episodes


class _CallbackTrap:
    def __init__(self):
        self.calls = 0

    def __eq__(self, _other):
        self.calls += 1
        raise AssertionError("ack equality callback executed")

    def __str__(self):
        self.calls += 1
        raise AssertionError("ack string callback executed")


@pytest.mark.parametrize("field", ["run_id", "episode_id", "request_sha256", "record_sha256"])
def test_completion_checks_strict_ack_fields_before_callbacks(threads, field):
    channel, handoff, _worker, _expected = _acknowledged(threads)
    trap = _CallbackTrap()
    object.__setattr__(channel._requests[handoff.episode_id].ack, field, trap)
    with pytest.raises(RSIPythonBRSAdmissionError):
        channel.complete_selected_handoff(handoff.episode_id)
    assert trap.calls == 0
    assert channel._selected_episode_id == handoff.episode_id


def test_completion_refuses_a_non_ack_object(threads):
    channel, handoff, _worker, _expected = _acknowledged(threads)
    channel._requests[handoff.episode_id].ack = object()
    with pytest.raises(RSIPythonBRSAdmissionError, match="ack_invalid"):
        channel.complete_selected_handoff(handoff.episode_id)
    assert channel._selected_episode_id == handoff.episode_id
