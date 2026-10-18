"""Read-only queued captures refuse real subsequent transport transitions."""

from contextlib import contextmanager
from threading import Event, Thread

import pytest
from test_rsi_brs_rejection_ready_channel import _bound
from test_rsi_python_brs_handoff import _selected_ready

from lunar_evolution.rsi_brs_rejection_ready_channel import (
    assert_selected_ready_stage,
    capture_selected_ready_stage,
)
from lunar_evolution.rsi_learning import RSILearningError


@contextmanager
def _worker(*, cancel=False):
    channel, scope = _bound()
    posted, release, done = Event(), Event(), Event()
    results, errors = [], []
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        if calls == 2:
            posted.set()
            assert release.wait(5)
            if cancel:
                raise RSILearningError("fixture_worker_cancelled")

    def work():
        try:
            results.append(channel.request(_selected_ready(scope[1]), check=check))
        except BaseException as exc:  # noqa: BLE001 - report every thread outcome.
            errors.append(exc)
        finally:
            done.set()

    thread = Thread(target=work, daemon=True)
    thread.start()
    try:
        assert posted.wait(5)
        capsule = capture_selected_ready_stage(channel, expected_scope=scope)
        yield channel, capsule, release, done, results, errors
    finally:
        # No observer or Condition lock is held during close or worker join.
        channel.close()
        release.set()
        thread.join(5)
        assert not thread.is_alive()


def test_real_close_invalidates_capture_without_clearing_original_evidence():
    with _worker() as (channel, capsule, release, done, results, errors):
        pending = capsule[2][7]
        channel.close()
        with pytest.raises(RSILearningError, match="state_invalid"):
            assert_selected_ready_stage(channel, capsule)
        assert pending.ack is None and pending.ack_fields is None and pending.error == "closed"
        release.set()
        assert done.wait(5)
        assert results == [] and [str(error) for error in errors] == [
            "rsi_python_brs_admission_closed",
        ]


def test_real_worker_cancellation_invalidates_capture_without_repair():
    with _worker(cancel=True) as (channel, capsule, release, done, results, errors):
        pending = capsule[2][7]
        release.set()
        assert done.wait(5)
        assert results == [] and [str(error) for error in errors] == ["fixture_worker_cancelled"]
        with pytest.raises(RSILearningError, match="state_invalid"):
            assert_selected_ready_stage(channel, capsule)
        assert pending.cancelled is True and pending.state == "cancelled"
        assert not channel._queue and pending.ack is None and pending.ack_fields is None


def test_legacy_service_stays_unchanged_but_cannot_reuse_queued_capture():
    with _worker() as (channel, capsule, release, done, results, errors):
        digest = "d" * 64
        pending = capsule[2][7]
        assert channel.service(lambda ready: digest, timeout=0) is True
        ack, fields = pending.ack, pending.ack_fields
        with pytest.raises(RSILearningError, match="state_invalid"):
            assert_selected_ready_stage(channel, capsule)
        assert pending.ack is ack and pending.ack_fields is fields
        assert pending.state == "done" and channel._servicing is False
        release.set()
        assert done.wait(5)
        assert errors == [] and len(results) == 1 and results[0].record_sha256 == digest
        assert pending.ack is ack and pending.ack_fields is fields
