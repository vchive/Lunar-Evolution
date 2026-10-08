"""Host ownership tests for the private Linux native guardian boundary."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager

import pytest

from lunar_evolution.native_guardian import NativeGuardianError, start_native_guardian

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux pidfd guardian")


@contextmanager
def _pipes():
    values = [os.pipe() for _ in range(5)]
    try:
        yield values
    finally:
        for pair in values:
            for fd in pair:
                try:
                    os.close(fd)
                except OSError:
                    pass


def test_start_rejects_borrowed_alias_and_stale_process():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    with _pipes() as pairs:
        with pytest.raises(NativeGuardianError) as error:
            start_native_guardian(
                process=process, executable="/proc/self/fd/99", bootstrap_fd=pairs[0][0],
                lifeline_fd=pairs[1][0], finish_fd=pairs[2][0], ack_fd=pairs[3][1],
                ack_read_fd=pairs[4][0], deadline=time.monotonic() + 1,
                deadline_ns=time.monotonic_ns() + 1_000_000_000,
            )
        assert error.value.code == "native_guardian_start_invalid"
        assert error.value.guardian_owner is None
        process.kill()
        process.wait(timeout=2)


@pytest.mark.parametrize("bad", ["unsupported", "expired", "nan"])
def test_start_rejects_before_spawning_when_platform_or_deadline_invalid(monkeypatch, bad):
    if bad == "unsupported":
        monkeypatch.setattr(sys, "platform", "darwin")
        deadline = time.monotonic() + 1
    elif bad == "expired":
        deadline = time.monotonic() - 1
    else:
        deadline = float("nan")
    with pytest.raises(NativeGuardianError) as error:
        start_native_guardian(
            process=object(), executable="/proc/self/fd/9", bootstrap_fd=9,
            lifeline_fd=10, finish_fd=11, ack_fd=12, ack_read_fd=13,
            deadline=deadline, deadline_ns=1,
        )
    assert error.value.code in {"native_guardian_unsupported", "native_guardian_start_invalid"}


def test_owner_cleanup_uses_only_original_pidfd_group_flag(monkeypatch):
    class Process:
        pid = 321
        returncode = None

        def poll(self):
            return self.returncode

    class Watcher:
        returncode = None

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -signal.SIGKILL

    process = Process()
    watcher = Watcher()
    monkeypatch.setattr(os, "close", lambda fd: None)
    called = []
    monkeypatch.setattr(signal, "pidfd_send_signal", lambda fd, sig, info, flags: called.append((fd, sig, flags)))
    from lunar_evolution.native_guardian import NativeGuardianOwner

    owner = NativeGuardianOwner(process, watcher, 77, time.monotonic() + 2, time.monotonic)
    assert owner.cleanup(timeout=0.1) is True
    assert called == [(77, signal.SIGKILL, 4)]


def test_owner_cleanup_reaps_watcher_when_group_signal_fails(monkeypatch):
    class Process:
        pid = 321
        returncode = None

        def poll(self):
            return self.returncode

    class Watcher:
        returncode = None
        waits = 0
        killed = False

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("watcher", timeout)
            self.returncode = -signal.SIGKILL
            return self.returncode

        def kill(self):
            self.killed = True

    process = Process()
    watcher = Watcher()
    monkeypatch.setattr(os, "close", lambda fd: None)
    monkeypatch.setattr(signal, "pidfd_send_signal", lambda *args: (_ for _ in ()).throw(PermissionError()))
    from lunar_evolution.native_guardian import NativeGuardianOwner

    owner = NativeGuardianOwner(process, watcher, 79, time.monotonic() + 2, time.monotonic)
    assert owner.cleanup(timeout=0.1) is False
    assert watcher.killed is True
    assert watcher.waits == 2


def test_owner_cleanup_caps_wait_by_original_deadline(monkeypatch):
    class Process:
        pid = 321
        returncode = None

        def poll(self):
            return self.returncode

    class Watcher:
        returncode = 0

        def __init__(self):
            self.waits = []

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.waits.append(timeout)
            return 0

    watcher = Watcher()
    monkeypatch.setattr(os, "close", lambda fd: None)
    monkeypatch.setattr(signal, "pidfd_send_signal", lambda *args: None)
    from lunar_evolution.native_guardian import NativeGuardianOwner

    owner = NativeGuardianOwner(Process(), watcher, 80, 101.0, lambda: 100.0)
    assert owner.cleanup(timeout=30.0) is True
    assert watcher.waits and watcher.waits[0] <= 0.51


def test_owner_finish_requires_bootstrap_exit_and_watcher_zero(monkeypatch):
    class Process:
        pid = 321
        returncode = 0

        def poll(self):
            return self.returncode

    class Watcher:
        returncode = 0

        def wait(self, timeout=None):
            return 0

    from lunar_evolution.native_guardian import NativeGuardianOwner

    owner = NativeGuardianOwner(Process(), Watcher(), 88, time.monotonic() + 2, time.monotonic)
    monkeypatch.setattr(os, "close", lambda fd: None)
    owner.finish()
    assert owner._finished is True
    assert owner._group_fd == -1


def test_start_consumes_exact_ready_byte_and_returns_live_owner(monkeypatch):
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])

    class Watcher:
        pid = 902
        returncode = None

        def poll(self):
            return self.returncode

    watcher = Watcher()
    with _pipes() as pairs:
        life, finish, ackread = pairs[0], pairs[1], pairs[2]
        bootstrap_fd = pairs[3][0]
        os.write(ackread[1], b"R")
        monkeypatch.setattr(os, "pidfd_open", lambda pid, flags: 77)
        monkeypatch.setattr(os, "getpgid", lambda pid: pid)
        monkeypatch.setattr(os, "getsid", lambda pid: pid)
        monkeypatch.setattr(signal, "pidfd_send_signal", lambda *args: None)
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: watcher)
        monkeypatch.setattr("lunar_evolution.native_guardian.select.select", lambda *args: ([ackread[0]], [], []))
        owner = start_native_guardian(
            process=process, executable=f"/proc/self/fd/{bootstrap_fd}", bootstrap_fd=bootstrap_fd,
            lifeline_fd=life[0], finish_fd=finish[0], ack_fd=ackread[1], ack_read_fd=ackread[0],
            deadline=time.monotonic() + 2, deadline_ns=time.monotonic_ns() + 2_000_000_000,
        )
        assert owner._watcher is watcher
        assert owner._group_fd == 77
    process.kill()
    process.wait(timeout=2)
