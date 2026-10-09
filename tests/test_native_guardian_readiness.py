"""Pipe readiness tests independent of native compilation and Linux pidfds."""

from __future__ import annotations

import json
import os
import resource
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lunar_evolution.native_guardian import NativeGuardianError, _wait_ready

_HIGH_FD_SCRIPT = """
import fcntl, json, os, resource, sys, time
sys.path.insert(0, sys.argv[1])
from lunar_evolution.native_guardian import NativeGuardianError, _wait_ready
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
if soft < 1025:
    if hard != resource.RLIM_INFINITY and hard < 1025:
        sys.exit(77)
    resource.setrlimit(resource.RLIMIT_NOFILE, (1025, hard))
r, w = os.pipe()
high = fcntl.fcntl(r, fcntl.F_DUPFD_CLOEXEC, 1024)
os.close(r)
payload = bytes.fromhex(sys.argv[2])
if payload:
    os.write(w, payload)
else:
    os.close(w)
    w = -1
try:
    try:
        _wait_ready(high, time.monotonic() + 1.0, time.monotonic)
    except NativeGuardianError as exc:
        result = {'fd': high, 'code': exc.code}
    else:
        result = {'fd': high, 'code': None}
    print(json.dumps(result), flush=True)
finally:
    os.close(high)
    if w >= 0:
        os.close(w)
"""


@pytest.mark.parametrize("payload,expected", [
    (b"R", None),
    (b"", "native_guardian_ready_invalid"),
    (b"F", "native_guardian_ready_invalid"),
    (b"RX", "native_guardian_ready_invalid"),
    (b"D", "native_guardian_ready_invalid"),
])
def test_real_high_fd_ready_and_refusal_frames(payload, expected):
    before = resource.getrlimit(resource.RLIMIT_NOFILE)
    result = subprocess.run(
        [sys.executable, "-c", _HIGH_FD_SCRIPT,
         str(Path(__file__).parents[1] / "src"), payload.hex()],
        check=False, capture_output=True, text=True, timeout=5,
    )
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == before
    if result.returncode == 77:
        pytest.skip("host hard descriptor limit cannot exercise FD >=1024")
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record["fd"] >= 1024
    assert record["code"] == expected


@pytest.mark.parametrize("expired_before_read", [True, False])
def test_readiness_keeps_original_deadline_before_and_after_read(monkeypatch, expired_before_read):
    read_fd, write_fd = os.pipe()
    samples = iter((0.0, 2.0) if expired_before_read else (0.0, 0.0, 2.0))
    real_read = os.read
    reads = []

    def read(fd, size):
        reads.append((fd, size))
        return real_read(fd, size)

    monkeypatch.setattr(os, "read", read)
    os.write(write_fd, b"R")
    try:
        with pytest.raises(NativeGuardianError) as error:
            _wait_ready(read_fd, 1.0, lambda: next(samples))
        assert error.value.code == "native_guardian_ready_invalid"
        assert reads == ([] if expired_before_read else [(read_fd, 2)])
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize("mask", [0, select.POLLERR, select.POLLNVAL, select.POLLHUP,
                                  select.POLLIN | select.POLLHUP])
def test_invalid_poll_events_do_not_read(monkeypatch, mask):
    read_fd, write_fd = os.pipe()

    class Poll:
        def register(self, fd, events):
            assert fd == read_fd
            assert events == select.POLLIN

        def poll(self, timeout):
            assert timeout > 0
            return [(read_fd, mask)]

    monkeypatch.setattr("lunar_evolution.native_guardian.select.poll", Poll)
    monkeypatch.setattr(os, "read", lambda *args: pytest.fail("read without valid readiness"))
    try:
        with pytest.raises(NativeGuardianError) as error:
            _wait_ready(read_fd, time.monotonic() + 1, time.monotonic)
        assert error.value.code == "native_guardian_ready_invalid"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_readiness_timeout_does_not_read_or_allocate_new_deadline(monkeypatch):
    read_fd, write_fd = os.pipe()
    timeouts = []

    class Poll:
        def register(self, fd, events):
            pass

        def poll(self, timeout):
            timeouts.append(timeout)
            return []

    monkeypatch.setattr("lunar_evolution.native_guardian.select.poll", Poll)
    monkeypatch.setattr(os, "read", lambda *args: pytest.fail("read without readiness"))
    try:
        with pytest.raises(NativeGuardianError) as error:
            _wait_ready(read_fd, 1.0, lambda: 0.25)
        assert error.value.code == "native_guardian_ready_invalid"
        assert timeouts == [750]
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_expired_deadline_refuses_before_poll(monkeypatch):
    monkeypatch.setattr("lunar_evolution.native_guardian.select.poll",
                        lambda: pytest.fail("expired readiness entered poll"))
    with pytest.raises(NativeGuardianError) as error:
        _wait_ready(8, 1.0, lambda: 1.0)
    assert error.value.code == "native_guardian_ready_invalid"


def test_real_empty_pipe_wait_is_bounded_by_original_deadline():
    read_fd, write_fd = os.pipe()
    started = time.monotonic()
    try:
        with pytest.raises(NativeGuardianError) as error:
            _wait_ready(read_fd, started + 0.02, time.monotonic)
        assert error.value.code == "native_guardian_ready_invalid"
        assert time.monotonic() - started < 1.0
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_closed_ack_descriptor_is_refused_without_read(monkeypatch):
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    monkeypatch.setattr(os, "read", lambda *args: pytest.fail("invalid descriptor reached read"))
    try:
        with pytest.raises(NativeGuardianError) as error:
            _wait_ready(read_fd, time.monotonic() + 1, time.monotonic)
        assert error.value.code == "native_guardian_ready_invalid"
    finally:
        os.close(write_fd)


def test_ready_read_error_is_a_fixed_refusal(monkeypatch):
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"R")

    def read(*args):
        raise OSError("fixture read failure")

    monkeypatch.setattr(os, "read", read)
    try:
        with pytest.raises(NativeGuardianError) as error:
            _wait_ready(read_fd, time.monotonic() + 1, time.monotonic)
        assert error.value.code == "native_guardian_ready_invalid"
        assert isinstance(error.value.__cause__, OSError)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_foreign_poll_descriptor_does_not_reach_read(monkeypatch):
    read_fd, write_fd = os.pipe()

    class Poll:
        def register(self, fd, events):
            pass

        def poll(self, timeout):
            return [(write_fd, select.POLLIN)]

    monkeypatch.setattr("lunar_evolution.native_guardian.select.poll", Poll)
    monkeypatch.setattr(os, "read", lambda *args: pytest.fail("foreign event reached read"))
    try:
        with pytest.raises(NativeGuardianError) as error:
            _wait_ready(read_fd, time.monotonic() + 1, time.monotonic)
        assert error.value.code == "native_guardian_ready_invalid"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_submillisecond_budget_rounds_wait_only(monkeypatch):
    timeouts = []

    class Poll:
        def register(self, fd, events):
            pass

        def poll(self, timeout):
            timeouts.append(timeout)
            return []

    monkeypatch.setattr("lunar_evolution.native_guardian.select.poll", Poll)
    with pytest.raises(NativeGuardianError) as error:
        _wait_ready(8, 1.0, lambda: 0.99999)
    assert error.value.code == "native_guardian_ready_invalid"
    assert timeouts == [1]
