"""Optional parent progress observes one exchange without exposing worker payloads."""

import io
import json
from urllib.request import Request

import pytest
from test_http_transport_deadline import clear_proxy_environment, frames, local_http, success_frames
from test_http_transport_observation_ipc import detailed_success, details, milestone

from lunar_evolution import http_transport as h

SECRET = "private-progress-fixture-body-and-key"
FIELDS = {
    "phase", "status", "last_milestone", "http_exchange_index",
    "milestone_elapsed_ms", "elapsed_ms",
}


class Process:
    def __init__(self, clock, steps):
        self.clock, self.steps = clock, iter(steps)
        self.stdin, self.stdout = io.BytesIO(), io.BytesIO()
        self.returncode = None
        self.calls = []
        self.killed = False
        self.waited = False

    def communicate(self, **kwargs):
        self.calls.append(kwargs)
        delay, outcome, raw = next(self.steps)
        self.clock[0] += delay
        if outcome == "timeout":
            raise h.TimeoutExpired("fixed-fixture", kwargs["timeout"], output=raw)
        if outcome == "interrupt":
            raise KeyboardInterrupt
        self.returncode = 0
        return raw, None

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self):
        self.waited = True
        return self.returncode


@pytest.fixture
def setup_exchange(monkeypatch):
    clock = [0.0]
    processes = []
    monkeypatch.setattr(h, "monotonic", lambda: clock[0])
    monkeypatch.setattr(h, "_configuration", dict)

    def setup(steps):
        def spawn(*args, **kwargs):
            process = Process(clock, steps)
            processes.append(process)
            return process

        monkeypatch.setattr(h, "Popen", spawn)
        request = Request(
            "https://private.invalid/" + SECRET + "?key=" + SECRET,
            data=SECRET.encode(), headers={"Authorization": "Bearer " + SECRET}, method="POST",
        )
        return request, processes

    return setup


def assert_closed(process):
    assert process.waited and process.poll() is not None
    assert process.stdin.closed and process.stdout.closed


def test_default_uses_one_communicate_with_original_timeout(setup_exchange):
    request, processes = setup_exchange([(1, "response", frames(*success_frames()))])
    assert h.exchange(request, 90) == h.TransportResponse(200, b"{}")
    assert len(processes) == 1
    process = processes[0]
    assert len(process.calls) == 1 and process.calls[0]["timeout"] == 90
    assert "input" in process.calls[0]
    assert_closed(process)


def test_accumulated_output_is_not_appended_and_input_is_sent_once(setup_exchange):
    prefix = frames(success_frames()[0], *details()[:-1])
    request, processes = setup_exchange([
        (30, "timeout", prefix), (30, "timeout", prefix),
        (1, "response", frames(*detailed_success())),
    ])
    snapshots = []
    result = h.exchange(request, 95, observer=snapshots.append)
    assert result.status == 200 and result.body == b"{}"
    assert len(processes) == 1
    process = processes[0]
    assert [call["timeout"] for call in process.calls] == [30, 30, 30]
    assert ["input" in call for call in process.calls] == [True, False, False]
    assert [value["elapsed_ms"] for value in snapshots] == [30_000, 60_000]
    assert all(value["last_milestone"] == "wait_response_headers" for value in snapshots)
    assert all(set(value) == FIELDS for value in snapshots)
    assert SECRET not in json.dumps(snapshots) and "https://" not in json.dumps(snapshots)
    assert_closed(process)


@pytest.mark.parametrize("count,name", [
    (0, None), (1, "worker_ready"), (3, "connect"),
    (4, "send_request"), (5, "wait_response_headers"),
])
def test_wait_snapshot_uses_only_complete_validated_milestones(setup_exchange, count, name):
    prefix = frames(success_frames()[0], *details()[:count])
    request, processes = setup_exchange([
        (30, "timeout", prefix + b'{"kind":"milestone"'),
        (1, "response", frames(*detailed_success())),
    ])
    snapshots = []
    h.exchange(request, 90, observer=snapshots.append)
    assert len(snapshots) == 1 and snapshots[0]["last_milestone"] == name
    assert snapshots[0]["phase"] == "open_response"
    assert snapshots[0]["status"] is None
    assert snapshots[0]["http_exchange_index"] == (None if count == 0 else int(count > 1))
    assert_closed(processes[0])


def test_startup_wait_has_no_invented_milestone(setup_exchange):
    request, _ = setup_exchange([
        (30, "timeout", b""), (1, "response", frames(*success_frames())),
    ])
    snapshots = []
    h.exchange(request, 90, observer=snapshots.append)
    assert snapshots == [{
        "phase": "open_response", "status": None, "last_milestone": None,
        "http_exchange_index": None, "milestone_elapsed_ms": None, "elapsed_ms": 30_000,
    }]


@pytest.mark.parametrize("phase,status", [
    ("read_response_body", 200), ("read_http_error_body", 503),
])
def test_body_wait_keeps_coarse_status_without_exposing_terminal(setup_exchange, phase, status):
    values = detailed_success()
    values[-2].update(phase=phase, status=status)
    terminal = {
        "kind": "terminal", "outcome": "failure", "reason": "http_error",
        "cause": "http_error", "status": status, "body": SECRET,
    }
    prefix = frames(*values[:-1], terminal)
    request, _ = setup_exchange([
        (30, "timeout", prefix), (5, "timeout", prefix),
    ])
    snapshots = []
    with pytest.raises(h.TransportFailure) as caught:
        h.exchange(request, 35, observer=snapshots.append)
    assert caught.value.phase == phase and caught.value.status == status
    assert len(snapshots) == 1
    assert snapshots[0]["phase"] == phase and snapshots[0]["status"] == status
    assert snapshots[0]["last_milestone"] == "response_headers_received"
    assert SECRET not in json.dumps(snapshots)


@pytest.mark.parametrize("invalid", [
    b"not-json\n", frames({"kind": "phase", "phase": SECRET, "status": None}),
    frames(success_frames()[0], milestone("connect", 1)),
    frames(success_frames()[0], {"kind": "milestone", "private": SECRET}),
])
def test_invalid_complete_progress_is_not_forwarded(setup_exchange, invalid):
    request, _ = setup_exchange([
        (30, "timeout", invalid), (1, "response", frames(*success_frames())),
    ])
    snapshots = []
    assert h.exchange(request, 90, observer=snapshots.append).status == 200
    assert snapshots == []


@pytest.mark.parametrize("raw", [b"x" * 513 + b"\n", b"x" * 1_000_000])
def test_large_first_frame_cannot_escape_small_prefix_parser(setup_exchange, raw):
    request, _ = setup_exchange([
        (30, "timeout", raw), (1, "response", frames(*success_frames())),
    ])
    snapshots = []
    assert h.exchange(request, 90, observer=snapshots.append).status == 200
    assert snapshots[0]["last_milestone"] is None
    assert set(snapshots[0]) == FIELDS


def test_observation_unavailable_discards_detail_without_changing_success(setup_exchange):
    prefix = frames(success_frames()[0], details()[0], {"kind": "observation_unavailable"})
    request, _ = setup_exchange([
        (30, "timeout", prefix), (1, "response", frames(*success_frames())),
    ])
    snapshots = []
    assert h.exchange(request, 90, observer=snapshots.append).status == 200
    assert snapshots[0]["last_milestone"] is None
    assert snapshots[0]["http_exchange_index"] is None
    assert snapshots[0]["milestone_elapsed_ms"] is None


@pytest.mark.parametrize("observer", [False, lambda value: 1 / 0])
def test_bad_observer_preserves_success_and_cleanup(setup_exchange, observer):
    request, processes = setup_exchange([
        (30, "timeout", frames(success_frames()[0])),
        (1, "response", frames(*success_frames())),
    ])
    assert h.exchange(request, 90, observer=observer).status == 200
    assert_closed(processes[0])


def test_original_absolute_deadline_wins_without_extra_tick_or_dispatch(setup_exchange):
    prefix = frames(success_frames()[0], *details()[:-1])
    request, processes = setup_exchange([
        (30, "timeout", prefix), (30, "timeout", prefix), (5, "timeout", prefix),
    ])
    snapshots = []
    with pytest.raises(h.TransportFailure) as caught:
        h.exchange(request, 65, observer=snapshots.append)
    assert caught.value.reason == "transport_timeout"
    assert caught.value.observation.last_milestone == "wait_response_headers"
    assert len(processes) == 1 and len(snapshots) == 2
    assert [call["timeout"] for call in processes[0].calls] == [30, 30, 5]
    assert processes[0].killed
    assert_closed(processes[0])


def test_observer_time_does_not_extend_deadline(setup_exchange):
    request, processes = setup_exchange([(30, "timeout", frames(success_frames()[0]))])

    def observer(value):
        processes[0].clock[0] += 6

    with pytest.raises(h.TransportFailure) as caught:
        h.exchange(request, 35, observer=observer)
    assert caught.value.reason == "transport_timeout" and len(processes[0].calls) == 1
    assert_closed(processes[0])


def test_late_complete_response_is_still_rejected(setup_exchange):
    request, processes = setup_exchange([
        (30, "timeout", frames(success_frames()[0])),
        (6, "response", frames(*detailed_success())),
    ])
    with pytest.raises(h.TransportFailure) as caught:
        h.exchange(request, 35, observer=lambda value: None)
    assert caught.value.reason == "transport_timeout"
    assert_closed(processes[0])


def test_observer_cannot_override_final_decoder_failure(setup_exchange):
    request, processes = setup_exchange([
        (30, "timeout", frames(success_frames()[0])), (1, "response", SECRET.encode()),
    ])
    with pytest.raises(h.TransportFailure) as caught:
        h.exchange(request, 90, observer=lambda value: None)
    assert caught.value.reason == "transport_error" and SECRET not in str(caught.value)
    assert_closed(processes[0])


@pytest.mark.parametrize("clock", [None, float("nan"), float("inf"), -1, 1e100])
def test_bad_optional_snapshot_clock_is_discarded(monkeypatch, clock):
    monkeypatch.setattr(h, "monotonic", lambda: clock)
    snapshots = []
    h._observe_progress(snapshots.append, frames(success_frames()[0]), 0)
    assert snapshots == []


def test_caller_interrupt_still_kills_reaps_and_closes(setup_exchange):
    request, processes = setup_exchange([(0, "interrupt", b"")])
    with pytest.raises(KeyboardInterrupt):
        h.exchange(request, 90, observer=lambda value: None)
    assert processes[0].killed
    assert_closed(processes[0])


def test_real_loopback_header_wait_reports_progress_and_keeps_one_request(monkeypatch):
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setattr(h, "_PROGRESS_INTERVAL_SECONDS", 0.05)
    snapshots = []
    with local_http("headers") as (endpoint, calls):
        request = Request(endpoint + "/" + SECRET, data=SECRET.encode(), method="POST")
        with pytest.raises(h.TransportFailure) as caught:
            h.exchange(request, 0.4, observer=snapshots.append)
    assert len(calls) == 1
    assert caught.value.reason == "transport_timeout"
    assert any(value["last_milestone"] == "wait_response_headers" for value in snapshots)
    assert all(set(value) == FIELDS for value in snapshots)
    assert all(value["phase"] == "open_response" for value in snapshots)
    assert SECRET not in json.dumps(snapshots) and endpoint not in json.dumps(snapshots)
