"""Actual inert Linux v3 native FD route; no static-Python/custody acceptance."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from contextlib import ExitStack

import pytest
from _native_target_fixture import compile_native_target
from test_native_bootstrap import _launch
from test_native_fd_handoff import _sealed
from test_native_trusted_controller_death import _frame

from lunar_evolution.native_bootstrap import (
    LINUX_CHILD_SUPERVISION,
    LINUX_GRANT_OBJECT_BINDING,
    NativeBootstrapPrivateSink,
    build_native_bootstrap_artifact,
    encode_native_bootstrap_control_v3,
    native_bootstrap_command,
)
from lunar_evolution.producer_grant_anchors import ProducerGrantRequest, hold_producer_grants

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux v3 private sink route")

_TARGET = r'''
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
int main(void) {
    struct stat pipe;
    int flags = fcntl(198, F_GETFL);
    if (flags < 0 || (flags & O_ACCMODE) != O_WRONLY || !(flags & O_NONBLOCK) ||
        fstat(198, &pipe) || !S_ISFIFO(pipe.st_mode) || !getenv("LUNAR_FIXED_LIVE_DEADLINE_NS")) return 20;
    if (write(198, "private\n", 8) != 8 || close(198)) return 21;
    pid_t child = fork();
    if (child < 0) return 22;
    if (!child) { errno = 0; _exit(fcntl(198, F_GETFD) == -1 && errno == EBADF ? 0 : 23); }
    int status;
    if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) return 24;
    puts("solver-after-private-close");
    return 0;
}
'''


@pytest.mark.parametrize("fault", [None, "pipe-identity", "deadline", "read-direction", "truncated"])
def test_actual_native_v3_pipe_route_and_original_binding_refusals(tmp_path, fault):
    source, target = tmp_path / "target.c", tmp_path / "target"
    source.write_text(_TARGET)
    compile_native_target(source, target)
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    work, output = tmp_path / "work", tmp_path / "output"
    work.mkdir()
    output.mkdir()
    with ExitStack() as stack:
        open_fds = set()

        def close(fd):
            if fd in open_fds:
                os.close(fd)
                open_fds.remove(fd)

        def pipe():
            ends = os.pipe()
            for fd in ends:
                open_fds.add(fd)
                stack.callback(close, fd)
            return ends

        control_r, control_w = pipe()
        gate_r, gate_w = pipe()
        frame_r, frame_w = pipe()
        owner_r, _owner_w = pipe()
        sink_r, sink_w = pipe()
        target_fd = stack.enter_context(_sealed(target))
        bootstrap_fd = stack.enter_context(_sealed(artifact.path))
        requests = (ProducerGrantRequest(str(work), "writable-directory"),
                    ProducerGrantRequest(str(work), "cwd"),
                    ProducerGrantRequest(str(output), "writable-directory"))
        grants = stack.enter_context(hold_producer_grants(requests))
        deadline_ns = time.monotonic_ns() + 10_000_000_000
        info = os.fstat(sink_w)
        sink = NativeBootstrapPrivateSink(sink_w, info.st_dev, info.st_ino, deadline_ns)
        payload = encode_native_bootstrap_control_v3(
            _launch(target), target_path=str(target), target_argv=(str(target),),
            target_cwd=work, target_fd=target_fd, bootstrap_fd=bootstrap_fd, held_grants=grants,
            private_sink=sink, reserved_fds=tuple(sorted(open_fds - {sink_w})),
        )
        if fault == "pipe-identity":
            payload = payload[:-16] + (info.st_ino + 1).to_bytes(8, "big") + payload[-8:]
        elif fault == "deadline":
            payload = payload[:-8] + (deadline_ns + 1).to_bytes(8, "big")
        elif fault == "read-direction":
            payload = payload[:-28] + sink_r.to_bytes(4, "big") + payload[-24:]
        elif fault == "truncated":
            payload = payload[:-1]
        command = native_bootstrap_command(
            artifact, control_fd=control_r, gate_fd=gate_r, frame_fd=frame_w,
            controller_lifeline_fd=owner_r, deadline_monotonic_ns=deadline_ns,
            child_supervision=LINUX_CHILD_SUPERVISION, grant_object_binding=LINUX_GRANT_OBJECT_BINDING,
        )
        process = subprocess.Popen(
            command, executable=f"/proc/self/fd/{bootstrap_fd}",
            pass_fds=(control_r, gate_r, frame_w, owner_r, sink_w,
                      *((sink_r,) if fault == "read-direction" else ()),
                      target_fd, bootstrap_fd, *grants.pass_fds),
            close_fds=True, start_new_session=True, cwd="/", env={"PATH": os.defpath, "LANG": "C"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            for fd in (control_r, gate_r, frame_w, owner_r, sink_w):
                close(fd)
            os.write(control_w, payload)
            close(control_w)
            if fault is not None:
                stdout, stderr = process.communicate(timeout=3)
                assert process.returncode in {66, 73}, stderr
                assert stdout == b""
                assert os.read(sink_r, 1) == b""
                return
            assert _frame(frame_r).kind == "bootstrap_ready"
            os.write(gate_w, b"1")
            close(gate_w)
            started, terminal = _frame(frame_r), _frame(frame_r)
            assert started.kind == "target_started" and terminal.kind == "terminal"
            stdout, stderr = process.communicate(timeout=3)
            assert process.returncode == 0, stderr
            assert os.read(sink_r, 128) == b"private\n"
            assert os.read(sink_r, 1) == b""
            assert stdout == b"solver-after-private-close\n" and stderr == b""
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()
