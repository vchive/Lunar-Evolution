"""Explicit dual native pipes; no production or runtime-custody admission."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from contextlib import ExitStack
from dataclasses import replace

import pytest
from _native_target_fixture import compile_native_target
from test_native_bootstrap import _launch
from test_native_fd_handoff import _sealed
from test_native_grant_control import control_owner as control_owner  # noqa: PLC0414
from test_native_trusted_controller_death import _frame

from lunar_evolution.native_bootstrap import (
    FIXED_LIVE_MODULES_SINK_FD,
    FIXED_PRODUCER_COMPLETION_SINK_FD,
    LINUX_CHILD_SUPERVISION,
    LINUX_GRANT_OBJECT_BINDING,
    NativeBootstrapCompletionSink,
    NativeBootstrapError,
    NativeBootstrapPrivateSink,
    build_native_bootstrap_artifact,
    encode_native_bootstrap_control_v2,
    encode_native_bootstrap_control_v3,
    encode_native_bootstrap_control_v4,
    native_bootstrap_command,
)
from lunar_evolution.producer_grant_anchors import ProducerGrantRequest, hold_producer_grants


def _sink(kind, fd, deadline):
    info = os.fstat(fd)
    return kind(fd, info.st_dev, info.st_ino, deadline)


def _tuple(sink):
    return (sink.fd.to_bytes(4, "big") + sink.device.to_bytes(8, "big")
            + sink.inode.to_bytes(8, "big") + sink.deadline_monotonic_ns.to_bytes(8, "big"))


def test_v4_is_explicit_and_preserves_v2_v3_bytes_and_separate_pipe_identities(control_owner):
    live_r, live_w = os.pipe()
    completion_r, completion_w = os.pipe()
    try:
        live = _sink(NativeBootstrapPrivateSink, live_w, 123456789)
        completion = _sink(NativeBootstrapCompletionSink, completion_w, live.deadline_monotonic_ns)
        v2 = encode_native_bootstrap_control_v2(**control_owner)
        v3 = encode_native_bootstrap_control_v3(**control_owner, private_sink=live)
        v4 = encode_native_bootstrap_control_v4(**control_owner, private_sink=live, completion_sink=completion)
        assert v4[:8] == b"LNB1\x00\x04\x00\x00"
        assert v4[8:-56] == v2[8:]
        assert v4[8:-28] == v3[8:]
        assert v4[-56:] == _tuple(live) + _tuple(completion)
        assert encode_native_bootstrap_control_v2(**control_owner) == v2
        assert encode_native_bootstrap_control_v3(**control_owner, private_sink=live) == v3
    finally:
        for fd in (live_r, live_w, completion_r, completion_w):
            os.close(fd)


def test_v4_refuses_pipe_aliases_drift_reserved_grants_and_renewed_deadlines(control_owner):
    live_r, live_w = os.pipe()
    completion_r, completion_w = os.pipe()
    alias = os.dup(live_w)
    try:
        live = _sink(NativeBootstrapPrivateSink, live_w, 123456789)
        completion = _sink(NativeBootstrapCompletionSink, completion_w, live.deadline_monotonic_ns)
        faults = [
            ({}, replace(live, fd=live_r), completion),
            ({}, live, replace(completion, fd=completion_r)),
            ({}, live, replace(completion, inode=completion.inode + 1)),
            ({}, live, replace(completion, device=completion.device + 1)),
            ({}, live, replace(completion, deadline_monotonic_ns=0)),
            ({}, live, replace(completion, deadline_monotonic_ns=live.deadline_monotonic_ns + 1)),
            ({}, live, _sink(NativeBootstrapCompletionSink, live_w, live.deadline_monotonic_ns)),
            ({}, live, _sink(NativeBootstrapCompletionSink, alias, live.deadline_monotonic_ns)),
            ({"reserved_fds": (completion_w,)}, live, completion),
            ({"reserved_fds": (live_w,)}, live, completion),
            ({"reserved_fds": (FIXED_PRODUCER_COMPLETION_SINK_FD,)}, live, completion),
            ({"reserved_fds": (FIXED_LIVE_MODULES_SINK_FD,)}, live, completion),
            ({"target_fd": completion_w}, live, completion),
            ({"bootstrap_fd": live_w}, live, completion),
            ({"target_fd": FIXED_PRODUCER_COMPLETION_SINK_FD}, live, completion),
            ({"reserved_fds": (True,)}, live, completion),
            ({"reserved_fds": []}, live, completion),
            ({}, live, replace(completion, fd=control_owner["held_grants"].pass_fds[0])),
        ]
        for changes, selected_live, selected_completion in faults:
            with pytest.raises(NativeBootstrapError):
                encode_native_bootstrap_control_v4(
                    **(control_owner | changes), private_sink=selected_live, completion_sink=selected_completion,
                )
    finally:
        for fd in (live_r, live_w, completion_r, completion_w, alias):
            os.close(fd)


_TARGET = r'''
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
int main(int argc, char **argv) {
    struct stat live, completion;
    int live_flags = fcntl(198, F_GETFL), completion_flags = fcntl(197, F_GETFL);
    const char *live_deadline = getenv("LUNAR_FIXED_LIVE_DEADLINE_NS");
    const char *completion_deadline = getenv("LUNAR_FIXED_COMPLETION_DEADLINE_NS");
    if (argc != 3 || !live_deadline || !completion_deadline ||
        strcmp(live_deadline, argv[1]) || strcmp(completion_deadline, argv[1]) ||
        live_flags < 0 || completion_flags < 0 ||
        (live_flags & O_ACCMODE) != O_WRONLY || (completion_flags & O_ACCMODE) != O_WRONLY ||
        !(live_flags & O_NONBLOCK) || !(completion_flags & O_NONBLOCK) ||
        fstat(198, &live) || fstat(197, &completion) || !S_ISFIFO(live.st_mode) ||
        !S_ISFIFO(completion.st_mode) || (live.st_dev == completion.st_dev && live.st_ino == completion.st_ino)) return 20;
    int broker = strcmp(argv[2], "broker") == 0;
    if (!!getenv("LUNAR_PRODUCER_RESPONSE_FD") != broker ||
        !!getenv("LUNAR_PRODUCER_REQUEST_FD") != broker) return 21;
    if (write(198, "startup\n", 8) != 8 || close(198)) return 22;
    errno = 0;
    if (fcntl(198, F_GETFD) != -1 || errno != EBADF || fcntl(197, F_GETFD) < 0) return 23;
    if (write(197, "begun\ncommitted\n", 16) != 16 || close(197)) return 24;
    pid_t child = fork();
    if (child < 0) return 25;
    if (!child) {
        errno = 0;
        if (fcntl(198, F_GETFD) != -1 || errno != EBADF) _exit(26);
        errno = 0;
        _exit(fcntl(197, F_GETFD) == -1 && errno == EBADF ? 0 : 27);
    }
    int status;
    if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) return 28;
    puts("solver-after-startup-close-and-completion-close");
    return 0;
}
'''


@pytest.fixture(scope="module")
def compiled_v4_fixture(tmp_path_factory):
    root = tmp_path_factory.mktemp("native-v4-images")
    source, target = root / "target.c", root / "target"
    source.write_text(_TARGET)
    compile_native_target(source, target)
    return target, build_native_bootstrap_artifact(root / "install")


@pytest.mark.skipif(sys.platform != "linux", reason="actual Linux v4 private pipes")
@pytest.mark.parametrize("fault", [None, "broker", "identity", "deadline", "renew-both",
                                  "read-direction", "alias", "truncated", "trailing"])
def test_actual_v4_native_pipe_handoff_and_pre_release_refusals(tmp_path, compiled_v4_fixture, fault):
    target, artifact = compiled_v4_fixture
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
        live_r, live_w = pipe()
        completion_r, completion_w = pipe()
        broker_r, broker_w = -1, -1
        if fault == "broker":
            broker_r, _response_w = pipe()
            _request_r, broker_w = pipe()
        target_fd = stack.enter_context(_sealed(target))
        bootstrap_fd = stack.enter_context(_sealed(artifact.path))
        grants = stack.enter_context(hold_producer_grants((
            ProducerGrantRequest(str(work), "writable-directory"), ProducerGrantRequest(str(work), "cwd"),
            ProducerGrantRequest(str(output), "writable-directory"),
        )))
        deadline_ns = time.monotonic_ns() + 10_000_000_000
        live = _sink(NativeBootstrapPrivateSink, live_w, deadline_ns)
        completion = _sink(NativeBootstrapCompletionSink, completion_w, deadline_ns)
        payload = encode_native_bootstrap_control_v4(
            _launch(target), target_path=str(target), target_argv=(str(target), str(deadline_ns),
                                                               "broker" if broker_r >= 0 else "no-broker"),
            target_cwd=work, target_fd=target_fd, bootstrap_fd=bootstrap_fd, held_grants=grants,
            private_sink=live, completion_sink=completion,
            reserved_fds=tuple(sorted(open_fds - {live_w, completion_w})),
        )
        if fault == "identity":
            payload = payload[:-16] + (completion.inode + 1).to_bytes(8, "big") + payload[-8:]
        elif fault == "deadline":
            payload = payload[:-8] + (deadline_ns + 1).to_bytes(8, "big")
        elif fault == "renew-both":
            payload = payload[:-36] + (deadline_ns + 1).to_bytes(8, "big") + payload[-28:-8] + (deadline_ns + 1).to_bytes(8, "big")
        elif fault == "read-direction":
            payload = payload[:-28] + completion_r.to_bytes(4, "big") + payload[-24:]
        elif fault == "alias":
            payload = payload[:-28] + _tuple(NativeBootstrapCompletionSink(
                live.fd, live.device, live.inode, live.deadline_monotonic_ns,
            ))
        elif fault == "truncated":
            payload = payload[:-1]
        elif fault == "trailing":
            payload += b"\x00"
        command = native_bootstrap_command(
            artifact, control_fd=control_r, gate_fd=gate_r, frame_fd=frame_w,
            controller_lifeline_fd=owner_r, deadline_monotonic_ns=deadline_ns,
            child_supervision=LINUX_CHILD_SUPERVISION, grant_object_binding=LINUX_GRANT_OBJECT_BINDING,
        )
        inherited = (control_r, gate_r, frame_w, owner_r, live_w, completion_w,
                     target_fd, bootstrap_fd, *grants.pass_fds)
        if fault == "read-direction":
            inherited += (completion_r,)
        environment = {"PATH": os.defpath, "LANG": "C", "LUNAR_FIXED_COMPLETION_DEADLINE_NS": "spoofed"}
        if broker_r >= 0:
            inherited += (broker_r, broker_w)
            environment |= {"LUNAR_PRODUCER_RESPONSE_FD": str(broker_r), "LUNAR_PRODUCER_REQUEST_FD": str(broker_w)}
        process = subprocess.Popen(
            command, executable=f"/proc/self/fd/{bootstrap_fd}", pass_fds=inherited,
            close_fds=True, start_new_session=True, cwd="/", env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            for fd in (control_r, gate_r, frame_w, owner_r, live_w, completion_w, broker_r, broker_w):
                close(fd)
            os.write(control_w, payload)
            close(control_w)
            if fault not in {None, "broker"}:
                stdout, stderr = process.communicate(timeout=3)
                assert process.returncode in {66, 73}, stderr
                assert stdout == b""
                assert os.read(live_r, 1) == os.read(completion_r, 1) == b""
                return
            assert _frame(frame_r).kind == "bootstrap_ready"
            os.write(gate_w, b"1")
            close(gate_w)
            assert _frame(frame_r).kind == "target_started"
            assert _frame(frame_r).kind == "terminal"
            stdout, stderr = process.communicate(timeout=3)
            assert process.returncode == 0, stderr
            assert os.read(live_r, 128) == b"startup\n" and os.read(live_r, 1) == b""
            assert os.read(completion_r, 128) == b"begun\ncommitted\n"
            assert os.read(completion_r, 1) == b""
            assert stdout == b"solver-after-startup-close-and-completion-close\n" and stderr == b""
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()
