"""Private live ownership of one independent native guardian child.

Only the original live bootstrap Popen may supply a group pidfd. This module
owns that fresh descriptor and its exact watcher Popen, never caller pipes or
durable PID/PGID records. Native code performs the R/F/EOF/D protocol and the
runtime PIDFD_SIGNAL_PROCESS_GROUP probe; no weaker signaling fallback exists.
"""

from __future__ import annotations

import math
import os
import select
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable

try:
    import fcntl
except ImportError:
    fcntl = None

_POPEN_TYPE = subprocess.Popen
_GROUP_SIGNAL = 4


class NativeGuardianError(ValueError):
    """Fixed-code failure without process arguments, pipe bytes or host paths."""

    def __init__(self, code: str) -> None:
        self.code = code
        # A failed startup may retain an exact live owner for the caller's
        # bounded cleanup after it closes its own lifeline writer. Never IDs.
        self.guardian_owner: NativeGuardianOwner | None = None
        super().__init__(code)


def _remaining(deadline: float, monotonic: Callable[[], float], code: str) -> float:
    try:
        remaining = deadline - monotonic()
    except (TypeError, ValueError, OverflowError) as exc:
        raise NativeGuardianError(code) from exc
    if not math.isfinite(remaining) or remaining <= 0:
        raise NativeGuardianError(code)
    return remaining


def _pipe(fd: int, direction: int) -> None:
    info = os.fstat(fd)
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    if (not stat.S_ISFIFO(info.st_mode) or flags & os.O_ACCMODE != direction
            or flags & os.O_ASYNC):
        raise NativeGuardianError("native_guardian_start_invalid")


class NativeGuardianOwner:
    """An ephemeral exact-child owner; no reconstruction or PID-based resume."""

    __slots__ = (
        "_bootstrap",
        "_cleanup_result",
        "_deadline",
        "_finished",
        "_group_fd",
        "_monotonic",
        "_watcher",
    )

    def __init__(
        self, bootstrap: subprocess.Popen, watcher: subprocess.Popen, group_fd: int,
        deadline: float, monotonic: Callable[[], float],
    ) -> None:
        self._bootstrap = bootstrap
        self._watcher = watcher
        self._group_fd = group_fd
        self._deadline = deadline
        self._monotonic = monotonic
        self._finished = False
        self._cleanup_result: bool | None = None

    def _close_group(self) -> None:
        if self._group_fd >= 0:
            os.close(self._group_fd)
            self._group_fd = -1

    def finish(self) -> None:
        """Require actual watcher exit0/reap within the original deadline."""
        if self._finished:
            return
        if self._group_fd < 0 or self._bootstrap.poll() is None:
            raise NativeGuardianError("native_guardian_exit_unknown")
        remaining = _remaining(self._deadline, self._monotonic, "native_guardian_exit_unknown")
        try:
            status = self._watcher.wait(timeout=remaining)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NativeGuardianError("native_guardian_exit_unknown") from exc
        _remaining(self._deadline, self._monotonic, "native_guardian_exit_unknown")
        if status != 0 or self._watcher.returncode != 0:
            raise NativeGuardianError("native_guardian_exit_unknown")
        self._finished = True
        self._close_group()

    def cleanup(self, timeout: float = 2.0) -> bool:
        """Stop the original group first, then boundedly reap the exact watcher.

        The caller closes its original lifeline writer before calling cleanup.
        A group-stop signal is attempted before exact watcher retirement. If
        that signal fails, the watcher is still reaped but cleanup stays unknown.
        """
        if type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0:
            raise NativeGuardianError("native_guardian_cleanup_invalid")
        if self._finished:
            return True
        if self._group_fd < 0:
            return self._cleanup_result is True
        stopped = False
        try:
            signal.pidfd_send_signal(self._group_fd, signal.SIGKILL, None, _GROUP_SIGNAL)
            stopped = True
        except ProcessLookupError:
            stopped = True
        except OSError:
            pass  # No flags0 or numeric process-group fallback.
        # Cleanup must remain inside both the caller-provided bound and the
        # original execution deadline.  A failed group signal still leaves an
        # exact watcher child owned by this object, so it is always reaped (or
        # reported as boundedly unknown) rather than leaked.
        try:
            now = self._monotonic()
            budget = min(timeout, max(0.0, self._deadline - now))
        except (TypeError, ValueError, OverflowError):
            budget = 0.0
        expires = time.monotonic() + budget
        watcher_reaped = False
        try:
            # Give native death/lifeline handling the first half of the bounded
            # teardown allowance. Reserve time for exact owned-child kill/reap.
            self._watcher.wait(timeout=max(0, (expires - time.monotonic()) / 2))
            watcher_reaped = True
        except subprocess.TimeoutExpired:
            try:
                if self._watcher.poll() is None:
                    self._watcher.kill()
                self._watcher.wait(timeout=max(0, expires - time.monotonic()))
                watcher_reaped = True
            except (OSError, subprocess.TimeoutExpired):
                watcher_reaped = False
        except OSError:
            try:
                if self._watcher.poll() is None:
                    self._watcher.kill()
                self._watcher.wait(timeout=max(0, expires - time.monotonic()))
                watcher_reaped = True
            except (OSError, subprocess.TimeoutExpired):
                watcher_reaped = False
        if not watcher_reaped:
            return False
        self._close_group()
        self._cleanup_result = stopped and budget > 0.0
        return self._cleanup_result


def start_native_guardian(
    *, process: subprocess.Popen, executable: str, bootstrap_fd: int,
    lifeline_fd: int, finish_fd: int, ack_fd: int, ack_read_fd: int,
    deadline: float, deadline_ns: int, monotonic: Callable[[], float] = time.monotonic,
) -> NativeGuardianOwner:
    """Start one direct controller-owned watcher and consume its exact R byte.

    Borrowed descriptors remain caller-owned on every path. Readiness must be
    consumed before writing bootstrap control or releasing its gate. The host
    closes its ack reader and excess finish/ack writers after this returns.
    """
    if (sys.platform != "linux" or fcntl is None or not hasattr(os, "pidfd_open")
            or not hasattr(signal, "pidfd_send_signal")):
        raise NativeGuardianError("native_guardian_unsupported")
    descriptors = (bootstrap_fd, lifeline_fd, finish_fd, ack_fd, ack_read_fd)
    if (not isinstance(process, _POPEN_TYPE) or type(process.pid) is not int or process.pid <= 1
            or process.returncode is not None or type(executable) is not str or not executable
            or executable != f"/proc/self/fd/{bootstrap_fd}" or type(deadline) not in {int, float}
            or not math.isfinite(deadline) or not callable(monotonic)
            or type(deadline_ns) is not int or not 0 < deadline_ns <= 0xFFFFFFFFFFFFFFFF
            or any(type(fd) is not int or fd <= 2 for fd in descriptors)
            or len(set(descriptors)) != len(descriptors)):
        raise NativeGuardianError("native_guardian_start_invalid")
    _remaining(deadline, monotonic, "native_guardian_start_invalid")
    group_fd = -1
    owner = None
    error = None
    try:
        if (process.poll() is not None or os.getpgid(process.pid) != process.pid
                or os.getsid(process.pid) != process.pid):
            raise NativeGuardianError("native_guardian_start_invalid")
        for fd, direction in ((lifeline_fd, os.O_RDONLY), (finish_fd, os.O_RDONLY),
                              (ack_read_fd, os.O_RDONLY), (ack_fd, os.O_WRONLY)):
            _pipe(fd, direction)
        os.fstat(bootstrap_fd)
        fresh_fd = os.pidfd_open(process.pid, 0)
        if type(fresh_fd) is not int or fresh_fd < 0 or fresh_fd in descriptors:
            raise NativeGuardianError("native_guardian_start_invalid")
        group_fd = fresh_fd
        if group_fd <= 2 or process.poll() is not None:
            raise NativeGuardianError("native_guardian_start_invalid")
        _remaining(deadline, monotonic, "native_guardian_start_invalid")
        command = (
            executable, "--group-pidfd", str(group_fd),
            "--controller-lifeline-fd", str(lifeline_fd),
            "--guardian-finish-fd", str(finish_fd), "--guardian-ack-fd", str(ack_fd),
            "--deadline-monotonic-ns", str(deadline_ns),
        )
        watcher = subprocess.Popen(
            command, executable=executable, pass_fds=(group_fd, lifeline_fd, finish_fd, ack_fd, bootstrap_fd),
            close_fds=True, start_new_session=True, env={"PATH": os.defpath, "LANG": "C"},
            cwd="/",
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        owner = NativeGuardianOwner(process, watcher, group_fd, deadline, monotonic)
        remaining = _remaining(deadline, monotonic, "native_guardian_ready_invalid")
        readable, _, _ = select.select((ack_read_fd,), (), (), remaining)
        if not readable or os.read(ack_read_fd, 2) != b"R":
            raise NativeGuardianError("native_guardian_ready_invalid")
        _remaining(deadline, monotonic, "native_guardian_ready_invalid")
        if watcher.poll() is not None or process.poll() is not None:
            raise NativeGuardianError("native_guardian_ready_invalid")
        return owner
    except NativeGuardianError as exc:
        error = exc
        raise
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        error = NativeGuardianError(
            "native_guardian_ready_invalid" if owner is not None else "native_guardian_start_invalid",
        )
        raise error from exc
    finally:
        if sys.exc_info()[0] is not None:
            if owner is not None:
                if error is not None:
                    error.guardian_owner = owner
            elif group_fd >= 0:
                os.close(group_fd)
