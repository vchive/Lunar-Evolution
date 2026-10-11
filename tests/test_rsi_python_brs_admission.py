"""Real-thread channel tests over inert JSON; no producer/runtime/evaluator is run."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from dataclasses import replace

import pytest

from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_brs_admission import (
    MAX_BRS_ADMISSION_BYTES,
    BRSAdmissionAck,
    BRSAdmissionChannel,
    BRSAdmissionReady,
    RSIPythonBRSAdmissionError,
    build_brs_admission_ready,
)

DIGEST = "a" * 64
OTHER = "b" * 64


def _payload(**changes):
    value = {"native_plan": {"fixture": "original"}, "prepared_journal": {},
             "expected_anchor_sha256": DIGEST}
    value.update(changes)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _ready(episode="episode-1", *, run="run-1", payload=None):
    return build_brs_admission_ready(run, episode, _payload() if payload is None else payload)


class _Worker:
    def __init__(self, channel, ready, check):
        self.posted = threading.Event()
        self.done = threading.Event()
        self.result = None
        self.error = None
        self.checks = 0

        def checked():
            self.checks += 1
            if self.checks == 2:
                self.posted.set()  # The second check runs after the request is enqueued.
            check()

        def run():
            try:
                self.result = channel.request(ready, check=checked)
            except BaseException as exc:  # noqa: BLE001 - surface every worker-thread failure.
                self.error = exc
            finally:
                self.done.set()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def wait_posted(self):
        assert self.posted.wait(3), "worker failed to submit its ready message"

    def wait_done(self):
        assert self.done.wait(3), "worker was not woken"
        self.thread.join(3)
        assert not self.thread.is_alive()


class _Threads:
    def __init__(self):
        self.channels = []
        self.workers = []

    def channel(self, *episodes, **kwargs):
        result = BRSAdmissionChannel("run-1", episodes or ("episode-1",), **kwargs)
        self.channels.append(result)
        return result

    def request(self, channel, ready=None, check=lambda: None):
        result = _Worker(channel, _ready() if ready is None else ready, check)
        self.workers.append(result)
        return result


@pytest.fixture
def threads():
    result = _Threads()
    yield result
    for channel in result.channels:
        channel.close()
    for worker in result.workers:
        worker.wait_done()


def _error(worker, code):
    worker.wait_done()
    assert type(worker.error) is RSIPythonBRSAdmissionError
    assert str(worker.error) == "rsi_python_brs_admission_" + code
    assert worker.result is None


def test_ready_digest_binds_exact_payload_and_both_identities():
    first = _ready()
    assert first == _ready()
    assert len(first.request_sha256) == 64
    assert len({first.request_sha256, _ready(run="run-2").request_sha256,
                _ready("episode-2").request_sha256,
                _ready(payload=_payload(native_plan={"fixture": "different"})).request_sha256}) == 4
    with pytest.raises(RSIPythonBRSAdmissionError, match="request_digest_mismatch"):
        replace(first, payload=_payload(native_plan={"fixture": "different"}))


@pytest.mark.parametrize("raw,code", [
    ("{}", "payload_invalid"),
    (bytearray(b"{}"), "payload_invalid"),
    (b"\xff", "payload_invalid"),
    (b"", "payload_invalid"),
    (b"[]", "payload_shape_invalid"),
    (b"{}", "payload_shape_invalid"),
    (_payload(native_plan=[]), "payload_shape_invalid"),
    (_payload(prepared_journal=None), "payload_shape_invalid"),
    (_payload(extra=True), "payload_shape_invalid"),
    (_payload(expected_anchor_sha256="0" * 64), "digest_invalid"),
    (_payload(expected_anchor_sha256=True), "digest_invalid"),
    (_payload() + b"\n", "payload_noncanonical"),
    (_payload().replace(b'"fixture":"original"', b'"fixture":"original","fixture":"again"'),
     "duplicate_json_key"),
    (_payload().replace(b'"fixture":"original"', b'"fixture":NaN'), "payload_invalid"),
    (_payload().replace(b'"fixture":"original"', b'"fixture":Infinity'), "payload_invalid"),
    (_payload().replace(b'"fixture":"original"', b'"fixture":1e999'), "shape_invalid"),
])
def test_ready_refuses_malformed_noncanonical_or_nonexact_bytes(raw, code):
    with pytest.raises(RSIPythonBRSAdmissionError, match=code):
        _ready(payload=raw)


def test_ready_refuses_bytes_subclass_before_decoder():
    class Child(bytes):
        def decode(self, *args, **kwargs):
            pytest.fail("bytes subclass callback must not run")

    with pytest.raises(RSIPythonBRSAdmissionError, match="payload_invalid"):
        _ready(payload=Child(_payload()))


def test_ready_has_byte_and_nesting_bounds():
    with pytest.raises(RSIPythonBRSAdmissionError, match="payload_too_large"):
        _ready(payload=b" " * (MAX_BRS_ADMISSION_BYTES + 1))
    nested = None
    for _ in range(50):
        nested = [nested]
    with pytest.raises(RSIPythonBRSAdmissionError, match="shape_invalid"):
        _ready(payload=_payload(native_plan={"nested": nested}))


@pytest.mark.parametrize("field,value", [
    ("run_id", "bad id"), ("episode_id", ""), ("request_sha256", "0" * 64),
    ("record_sha256", "0" * 64), ("record_sha256", OTHER.upper()),
    ("record_sha256", True),
])
def test_ack_refuses_invalid_identity_and_digest(field, value):
    fields = {"run_id": "run-1", "episode_id": "episode-1",
              "request_sha256": DIGEST, "record_sha256": OTHER}
    fields[field] = value
    with pytest.raises(RSIPythonBRSAdmissionError):
        BRSAdmissionAck(**fields)


@pytest.mark.parametrize("episodes,owner", [
    ((), None), (("episode-1", "episode-1"), None), (("bad id",), None),
    ({"episode-1"}, None), (("episode-1",), True), (("episode-1",), 0),
])
def test_channel_refuses_unbounded_or_invalid_wave(episodes, owner):
    with pytest.raises(RSIPythonBRSAdmissionError):
        BRSAdmissionChannel("run-1", episodes, owner_thread=owner)


def test_service_empty_timeout_and_owner_request_refusal(threads):
    channel = threads.channel()
    assert channel.service(lambda ready: pytest.fail("empty queue invoked handler"), timeout=0) is False
    with pytest.raises(RSIPythonBRSAdmissionError, match="request_on_owner"):
        channel.request(_ready(), check=lambda: pytest.fail("owner invoked worker check"))


@pytest.mark.parametrize("timeout", [-1, True, "0", float("nan"), float("inf"), 10 ** 500])
def test_service_timeout_shape_is_fixed(threads, timeout):
    with pytest.raises(RSIPythonBRSAdmissionError, match="timeout_invalid"):
        threads.channel().service(lambda ready: DIGEST, timeout=timeout)


def test_only_owner_thread_services_ready(threads):
    channel = threads.channel()
    observed = []

    def wrong_owner():
        try:
            channel.service(lambda ready: pytest.fail("nonowner handler ran"), timeout=0)
        except RSIPythonBRSAdmissionError as exc:
            observed.append(exc)

    thread = threading.Thread(target=wrong_owner)
    thread.start()
    thread.join(3)
    assert not thread.is_alive()
    assert len(observed) == 1
    assert str(observed[0]) == "rsi_python_brs_admission_service_owner_required"


def test_out_of_order_ready_does_not_wait_for_earlier_ordinal(threads):
    channel = threads.channel("episode-1", "episode-2")
    second = threads.request(channel, _ready("episode-2"))
    second.wait_posted()
    first = threads.request(channel)
    first.wait_posted()
    serviced = []

    def handler(ready):
        serviced.append(ready.episode_id)
        return OTHER

    assert channel.service(handler)
    second.wait_done()
    assert second.error is None
    assert second.result == BRSAdmissionAck("run-1", "episode-2", _ready("episode-2").request_sha256, OTHER)
    assert not first.done.is_set()
    assert channel.service(handler)
    first.wait_done()
    assert first.error is None
    assert serviced == ["episode-2", "episode-1"]


def test_fixed_wave_bounds_queue_and_duplicate_remains_used_after_ack(threads):
    channel = threads.channel("episode-1", "episode-2")
    first = threads.request(channel)
    first.wait_posted()
    second = threads.request(channel, _ready("episode-2"))
    second.wait_posted()
    _error(threads.request(channel, _ready("episode-3")), "wave_mismatch")
    _error(threads.request(channel, _ready(run="run-2")), "wave_mismatch")
    _error(threads.request(channel), "duplicate_request")
    calls = []
    for _ in range(2):
        assert channel.service(lambda ready: calls.append(ready.episode_id) or DIGEST)
    assert channel.service(lambda ready: pytest.fail("queue exceeded fixed wave"), timeout=0) is False
    _error(threads.request(channel), "duplicate_request")
    assert calls == ["episode-1", "episode-2"]


def test_close_wakes_queued_workers_and_refuses_late_requests(threads):
    channel = threads.channel("episode-1", "episode-2")
    first = threads.request(channel)
    first.wait_posted()
    second = threads.request(channel, _ready("episode-2"))
    second.wait_posted()
    channel.close()
    channel.close()
    _error(first, "closed")
    _error(second, "closed")
    _error(threads.request(channel), "closed")
    assert channel.service(lambda ready: pytest.fail("closed handler ran"), timeout=0) is False


def test_cancel_during_wait_removes_request_and_preserves_original_error(threads):
    channel = threads.channel()
    checks = []
    original = RSILearningError("fixture_original_budget_exhausted")

    def check():
        checks.append(True)
        if len(checks) == 4:
            raise original

    worker = threads.request(channel, check=check)
    worker.wait_done()
    assert worker.error is original
    assert len(checks) == 4  # Initial, queued, and repeated original budget checks.
    assert channel.service(lambda ready: pytest.fail("cancelled request invoked handler"), timeout=0) is False
    _error(threads.request(channel), "duplicate_request")


def test_cancel_before_submission_invokes_no_handler(threads):
    channel = threads.channel()
    original = RuntimeError("fixture_cancelled_before_queue")

    def check():
        raise original

    worker = threads.request(channel, check=check)
    worker.wait_done()
    assert worker.error is original
    assert channel.service(lambda ready: pytest.fail("cancelled check invoked handler"), timeout=0) is False
    # A pre-submission check does not use an episode's one allowed request.
    replacement = threads.request(channel)
    replacement.wait_posted()
    assert channel.service(lambda ready: DIGEST)
    replacement.wait_done()
    assert replacement.error is None


def test_cancellation_racing_durable_handler_retains_pin_and_stops_owner(threads):
    channel = threads.channel()
    cancel = threading.Event()
    original = RSILearningError("fixture_cancelled_after_pin")
    pins = []

    def check():
        if cancel.is_set():
            raise original

    worker = threads.request(channel, check=check)
    worker.wait_posted()

    def handler(ready):
        pins.append(ready.request_sha256)
        cancel.set()
        worker.wait_done()  # Requires condition lock to be released during the handler.
        return DIGEST

    with pytest.raises(RSIPythonBRSAdmissionError, match="ack_invalid"):
        channel.service(handler)
    assert worker.error is original
    assert pins == [_ready().request_sha256]
    assert channel.service(lambda ready: pytest.fail("pin was retried"), timeout=0) is False


def test_close_racing_durable_handler_retains_pin_and_stops_owner(threads):
    channel = threads.channel()
    worker = threads.request(channel)
    worker.wait_posted()
    pins = []

    def handler(ready):
        pins.append(ready.request_sha256)
        closer = threading.Thread(target=channel.close)
        closer.start()
        closer.join(3)
        assert not closer.is_alive(), "handler held the condition lock"
        worker.wait_done()
        return DIGEST

    with pytest.raises(RSIPythonBRSAdmissionError, match="ack_invalid"):
        channel.service(handler)
    _error(worker, "closed")
    assert len(pins) == 1


def test_original_check_does_not_hold_condition_lock(threads):
    channel = threads.channel()
    counts = []

    def check():
        counts.append(True)
        if len(counts) == 2:
            closer = threading.Thread(target=channel.close)
            closer.start()
            closer.join(3)
            assert not closer.is_alive(), "check held the condition lock"

    _error(threads.request(channel, check=check), "closed")
    assert counts == [True, True]


def test_handler_failure_wakes_requester_with_fixed_code_and_owner_original_error(threads):
    channel = threads.channel()
    worker = threads.request(channel)
    worker.wait_posted()
    original = RuntimeError("private fixture child text /private/path")

    def handler(ready):
        raise original

    with pytest.raises(RuntimeError) as caught:
        channel.service(handler)
    assert caught.value is original
    _error(worker, "handler_failed")
    assert "private" not in str(worker.error)


@pytest.mark.parametrize("result", [None, True, "0" * 64, "not-a-digest"])
def test_bad_handler_ack_is_owner_error_and_fixed_worker_refusal(threads, result):
    channel = threads.channel()
    worker = threads.request(channel)
    worker.wait_posted()
    with pytest.raises(RSIPythonBRSAdmissionError, match="digest_invalid"):
        channel.service(lambda ready: result)
    _error(worker, "handler_failed")


def test_service_reentry_is_refused_without_deadlocking(threads):
    channel = threads.channel()
    worker = threads.request(channel)
    worker.wait_posted()

    def handler(ready):
        with pytest.raises(RSIPythonBRSAdmissionError, match="service_reentrant"):
            channel.service(lambda nested: pytest.fail("nested handler ran"), timeout=0)
        return DIGEST

    assert channel.service(handler)
    worker.wait_done()
    assert worker.error is None


def test_request_refuses_subclass_before_its_validation_callback(threads):
    class Child(BRSAdmissionReady):
        def __post_init__(self):
            pytest.fail("Ready subclass validation callback ran")

    child = object.__new__(Child)
    _error(threads.request(threads.channel(), child), "ready_invalid")


def test_request_revalidates_tampered_frozen_dto(threads):
    ready = _ready()
    object.__setattr__(ready, "payload", _payload(native_plan={"fixture": "tampered"}))
    _error(threads.request(threads.channel(), ready), "request_digest_mismatch")


def test_request_detaches_original_message_from_caller_mutation(threads):
    channel = threads.channel()
    ready = _ready()
    worker = threads.request(channel, ready)
    worker.wait_posted()
    different = _ready(payload=_payload(native_plan={"fixture": "tampered"}))
    object.__setattr__(ready, "payload", different.payload)
    object.__setattr__(ready, "request_sha256", different.request_sha256)
    observed = []
    assert channel.service(lambda detached: observed.append(detached) or DIGEST)
    worker.wait_done()
    assert observed == [_ready()]
    assert worker.error is None
    assert worker.result.request_sha256 == _ready().request_sha256


def test_mutating_handler_message_refuses_ack_and_wakes_worker(threads):
    channel = threads.channel()
    worker = threads.request(channel)
    worker.wait_posted()

    def handler(ready):
        object.__setattr__(ready, "payload", _payload(native_plan={"fixture": "changed"}))
        return DIGEST

    with pytest.raises(RSIPythonBRSAdmissionError, match="request_digest_mismatch"):
        channel.service(handler)
    _error(worker, "handler_failed")


def test_handler_cannot_replace_request_with_another_valid_message(threads):
    channel = threads.channel()
    worker = threads.request(channel)
    worker.wait_posted()
    different = _ready(payload=_payload(native_plan={"fixture": "changed"}))

    def handler(ready):
        object.__setattr__(ready, "payload", different.payload)
        object.__setattr__(ready, "request_sha256", different.request_sha256)
        return DIGEST

    with pytest.raises(RSIPythonBRSAdmissionError, match="request_mutated"):
        channel.service(handler)
    _error(worker, "handler_failed")


def test_owner_wait_is_woken_by_channel_close(threads):
    channel = threads.channel()
    closer = threading.Thread(target=channel.close)
    closer.start()
    assert channel.service(lambda ready: pytest.fail("closed wait invoked handler"), timeout=3) is False
    closer.join(3)
    assert not closer.is_alive()


def test_owner_observation_scope_covers_handler_and_ack_dispatch(threads):
    channel = threads.channel()
    worker = threads.request(channel)
    worker.wait_posted()
    observed = []

    @contextmanager
    def scope():
        observed.append("entered")
        try:
            yield
        finally:
            observed.append("left")

    def handler(ready):
        assert observed == ["entered"]
        observed.append("pinned")
        return DIGEST

    assert channel.service(handler, observation_scope=scope)
    worker.wait_done()
    assert worker.error is None
    assert observed == ["entered", "pinned", "left"]


def test_ack_failure_is_raised_inside_owner_observation_scope(threads):
    channel = threads.channel()
    worker = threads.request(channel)
    worker.wait_posted()
    durable = []
    memory = []
    observed = []

    @contextmanager
    def scope():
        try:
            yield
        except RSIPythonBRSAdmissionError as exc:
            observed.append(str(exc))
            memory.clear()  # Owner restores old memory, never removes the durable pin.
            raise

    def handler(ready):
        durable.append(ready.request_sha256)
        memory.append(ready.request_sha256)
        channel.close()
        return DIGEST

    with pytest.raises(RSIPythonBRSAdmissionError, match="ack_invalid"):
        channel.service(handler, observation_scope=scope)
    _error(worker, "closed")
    assert durable == [_ready().request_sha256]
    assert memory == []
    assert observed == ["rsi_python_brs_admission_ack_invalid"]


def test_observation_scope_entry_does_not_hold_condition_lock(threads):
    channel = threads.channel()
    worker = threads.request(channel)
    worker.wait_posted()

    @contextmanager
    def scope():
        closer = threading.Thread(target=channel.close)
        closer.start()
        closer.join(3)
        assert not closer.is_alive(), "observation scope entry held the condition lock"
        yield

    with pytest.raises(RSIPythonBRSAdmissionError, match="ack_invalid"):
        channel.service(lambda ready: DIGEST, observation_scope=scope)
    _error(worker, "closed")


def test_scope_is_not_entered_for_empty_wait(threads):
    channel = threads.channel()
    assert channel.service(lambda ready: pytest.fail("empty handler ran"), timeout=0,
                           observation_scope=lambda: pytest.fail("empty wait entered scope")) is False
