"""Bounded bytes for one original local child; never remote cleanup evidence."""

from __future__ import annotations

import os
import selectors
import subprocess
import time
from dataclasses import dataclass, field

from .automatic_solve_lifecycle import SolveExecutionControl
from .process_ownership import (
    ProcessCleanupStatus,
    RegisteredProcess,
    cleanup_registered_process,
)


class WorkerChannelError(ValueError):
    """Fixed local-channel codes, excluding command output and credentials."""


@dataclass(frozen=True, slots=True)
class WorkerChannelOutput:
    exit_code: int
    stdout: bytes = field(repr=False)


def run_worker_channel(
    argv: tuple[str, ...], data: bytes, *, control: SolveExecutionControl,
    stdout_limit: int = 512 * 1024, stderr_limit: int = 4096,
    environment: dict[str, str] | None = None,
) -> WorkerChannelOutput:
    """Run fixed trusted argv with bounded pipes and original local group cleanup."""
    if (
        type(argv) is not tuple or not argv or any(type(x) is not str or not x or "\0" in x for x in argv)
        or type(data) is not bytes or len(data) > 512 * 1024
        or not isinstance(control, SolveExecutionControl)
        or type(stdout_limit) is not int or not 1 <= stdout_limit <= 2 * 1024 * 1024
        or type(stderr_limit) is not int or not 1 <= stderr_limit <= 65536
    ):
        raise WorkerChannelError("worker_channel_input_invalid")
    control.check("external_worker_channel_start")
    if environment is None:
        environment = {name: os.environ[name] for name in (
            "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "SSH_AUTH_SOCK",
        ) if name in os.environ}
    try:
        process = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, shell=False, close_fds=True, start_new_session=True,
        )
    except OSError:
        raise WorkerChannelError("worker_channel_start_failed") from None
    original_pid = process.pid
    output = bytearray()
    stderr_bytes = 0
    offset = 0
    try:
        with selectors.DefaultSelector() as selector:
            for pipe, mode, role in (
                (process.stdin, selectors.EVENT_WRITE, "input"),
                (process.stdout, selectors.EVENT_READ, "output"),
                (process.stderr, selectors.EVENT_READ, "error"),
            ):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, mode, role)
            while selector.get_map():
                remaining = control.check("external_worker_channel_wait")
                process.poll()
                for event, _mask in selector.select(min(remaining, 0.05)):
                    pipe = event.fileobj
                    if event.data == "input":
                        try:
                            written = os.write(pipe.fileno(), data[offset:offset + 65536])
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            written = 0
                            offset = len(data)
                        offset += written
                        if offset == len(data):
                            selector.unregister(pipe)
                            pipe.close()
                        continue
                    try:
                        chunk = os.read(pipe.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(pipe)
                        pipe.close()
                    elif event.data == "output":
                        if len(output) + len(chunk) > stdout_limit:
                            raise WorkerChannelError("worker_channel_stdout_limit")
                        output.extend(chunk)
                    else:
                        stderr_bytes += len(chunk)
                        if stderr_bytes > stderr_limit:
                            raise WorkerChannelError("worker_channel_stderr_limit")
            while process.poll() is None:
                time.sleep(min(control.check("external_worker_channel_exit"), 0.01))
        control.check("external_worker_channel_response")
        return WorkerChannelOutput(process.returncode, bytes(output))
    finally:
        cleanup = cleanup_registered_process(
            RegisteredProcess(original_pid, original_pid,
                              owner_check=lambda: process.pid == original_pid,
                              label="external-worker-local-channel"),
            grace_seconds=0.1, deadline=time.monotonic() + 0.3,
            allow_exited_leader_initial=True, reap_child=process.poll,
        )
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
        if cleanup.status not in {ProcessCleanupStatus.ALREADY_EXITED, ProcessCleanupStatus.CLEANED}:
            raise WorkerChannelError("worker_channel_local_cleanup_unverified")
