"""Safe local Linux control probes, never provider or external campaign calls.

All signal probes use signal 0. Namespace clone probes are deliberately invalid
thread combinations, so even an unfiltered target cannot create a namespace.
These tests do not claim post-bootstrap descendant supervision or full egress.
"""

from __future__ import annotations

import json
import os
import platform
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _native_target_fixture import compile_native_target
from test_native_bootstrap import _launch

from lunar_evolution.native_bootstrap import (
    build_native_bootstrap_artifact,
    encode_native_bootstrap_control,
    native_bootstrap_command,
)
from lunar_evolution.process_ownership import (
    ProcessCleanupStatus,
    RegisteredProcess,
    cleanup_registered_process,
)
from lunar_evolution.producer_bootstrap import parse_bootstrap_handshake_frame
from lunar_evolution.producer_isolation import build_producer_isolation_policy

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux target control isolation")

_SOURCE = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include "native_producer_isolation.h"

static volatile sig_atomic_t stopping;
static void stop(int value) { (void)value; stopping = 1; }
static int denied(long number, long a, long b, long c, long d, long e, long f, int expected) {
    errno = 0;
    long result = syscall(number, a, b, c, d, e, f);
    int error = errno;
    printf("%ld %d\n", result, error);
    return result == -1 && error == expected ? 0 : 20;
}
static int wait_ok(pid_t child) {
    int status;
    pid_t result;
    do { result = waitpid(child, &status, 0); } while (result < 0 && errno == EINTR);
    return result == child && WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : 21;
}
static void *thread_value(void *value) { *(int *)value = 42; return value; }
static int ordinary_children(void) {
    pid_t child = fork();
    if (child < 0) return 22;
    if (child == 0) _exit(0);
    if (wait_ok(child)) return 23;
    child = vfork();
    if (child < 0) return 24;
    if (child == 0) _exit(0);
    if (wait_ok(child)) return 25;
    pthread_t thread;
    int value = 0;
    void *result = NULL;
    if (pthread_create(&thread, NULL, thread_value, &value)) return 26;
    if (pthread_join(thread, &result) || result != &value || value != 42) return 27;
    return 0;
}
static int retained_child(void) {
    int observed[2];
    if (pipe(observed)) return 30;
    struct sigaction action;
    memset(&action, 0, sizeof(action)); action.sa_handler = stop;
    if (sigemptyset(&action.sa_mask) || sigaction(SIGTERM, &action, NULL)) return 31;
    sigset_t blocked, previous;
    if (sigemptyset(&blocked) || sigaddset(&blocked, SIGTERM) ||
        sigprocmask(SIG_BLOCK, &blocked, &previous)) return 31;
    pid_t group = getpgrp(), child = fork();
    if (child < 0) return 32;
    if (child == 0) {
        close(observed[0]);
        action.sa_handler = SIG_DFL;
        if (sigaction(SIGTERM, &action, NULL) || sigprocmask(SIG_SETMASK, &previous, NULL)) _exit(33);
        errno = 0; pid_t session = setsid(); int session_error = errno;
        errno = 0; int moved = setpgid(0, 0); int group_error = errno;
        int valid = session == -1 && session_error == EPERM && moved == -1 &&
                    group_error == EPERM && getpgrp() == group;
        if (write(observed[1], &valid, sizeof(valid)) != (ssize_t)sizeof(valid)) _exit(34);
        close(observed[1]);
        if (!valid) _exit(35);
        for (;;) pause();
    }
    close(observed[1]);
    int valid = 0;
    if (read(observed[0], &valid, sizeof(valid)) != (ssize_t)sizeof(valid)) return 36;
    close(observed[0]);
    printf("{\"child\":%ld,\"group\":%ld,\"valid\":%d}\n", (long)child, (long)group, valid);
    if (fflush(stdout)) return 37;
    if (!valid) return wait_ok(child) ? 38 : 39;
    while (!stopping) sigsuspend(&previous);
    if (sigprocmask(SIG_SETMASK, &previous, NULL)) return 40;
    int status;
    pid_t result;
    do { result = waitpid(child, &status, 0); } while (result < 0 && errno == EINTR);
    return result == child && WIFSIGNALED(status) && WTERMSIG(status) == SIGTERM ? 0 : 40;
}
static int guardian_probes(pid_t controller) {
    pid_t guardian = getppid(), group = getpgrp();
    if (denied(__NR_kill, guardian, 0, 0, 0, 0, 0, EPERM)) return 41;
    if (denied(__NR_kill, controller, 0, 0, 0, 0, 0, EPERM)) return 42;
    if (denied(__NR_tgkill, guardian, guardian, 0, 0, 0, 0, EPERM)) return 43;
    if (denied(__NR_process_vm_readv, guardian, 0, 0, 0, 0, 0, EPERM)) return 44;
    if (denied(__NR_setsid, 0, 0, 0, 0, 0, 0, EPERM)) return 45;
    if (denied(__NR_setpgid, 0, 0, 0, 0, 0, 0, EPERM)) return 46;
    if (getpgrp() != group || group != guardian || getsid(0) != guardian) return 47;
    return ordinary_children();
}
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    const char *mode = argv[2], *writes[] = {argv[1]};
    /* Native bootstrap supplies isolation for guard mode; all other modes
       install the same header boundary directly in their private process. */
    if (strcmp(mode, "guard") && lunar_apply_isolation("linux-landlock-seccomp-v1", NULL, 0, writes, 1)) return 3;
    if (!strcmp(mode, "ordinary")) return ordinary_children();
    if (!strcmp(mode, "retained")) return retained_child();
    if (!strcmp(mode, "guard")) return guardian_probes((pid_t)strtol(argv[3], NULL, 10));
    if (!strcmp(mode, "clone_namespace")) {
        unsigned long flag = strtoul(argv[3], NULL, 0);
        /* CLONE_THREAD without CLONE_SIGHAND/CLONE_VM is invalid regardless
           of privilege. A missing filter cannot create a real namespace. */
        return denied(__NR_clone, (long)(flag | CLONE_THREAD), 0, 0, 0, 0, 0, EPERM);
    }
    if (!strcmp(mode, "setsid")) return denied(__NR_setsid, 0, 0, 0, 0, 0, 0, EPERM);
    if (!strcmp(mode, "setpgid")) return denied(__NR_setpgid, 0, 0, 0, 0, 0, 0, EPERM);
    if (!strcmp(mode, "setns")) return denied(__NR_setns, -1, 0, 0, 0, 0, 0, EPERM);
    if (!strcmp(mode, "clone3")) return denied(LUNAR_NR_CLONE3, 0, 0, 0, 0, 0, 0, ENOSYS);
    if (!strcmp(mode, "kill")) return denied(__NR_kill, getppid(), 0, 0, 0, 0, 0, EPERM);
    if (!strcmp(mode, "tkill")) {
#ifdef __NR_tkill
        return denied(__NR_tkill, getpid(), 0, 0, 0, 0, 0, EPERM);
#else
        return 77;
#endif
    }
    if (!strcmp(mode, "tgkill")) return denied(__NR_tgkill, getpid(), getpid(), 0, 0, 0, 0, EPERM);
    if (!strcmp(mode, "rt_sigqueueinfo")) {
#ifdef __NR_rt_sigqueueinfo
        return denied(__NR_rt_sigqueueinfo, getpid(), 0, 0, 0, 0, 0, EPERM);
#else
        return 77;
#endif
    }
    if (!strcmp(mode, "rt_tgsigqueueinfo")) {
#ifdef __NR_rt_tgsigqueueinfo
        return denied(__NR_rt_tgsigqueueinfo, getpid(), getpid(), 0, 0, 0, 0, EPERM);
#else
        return 77;
#endif
    }
    if (!strcmp(mode, "pidfd_send_signal")) return denied(LUNAR_NR_PIDFD_SEND_SIGNAL, -1, 0, 0, 0, 0, 0, EPERM);
    if (!strcmp(mode, "pidfd_getfd")) return denied(LUNAR_NR_PIDFD_GETFD, -1, -1, 0, 0, 0, 0, EPERM);
    if (!strcmp(mode, "process_vm_readv")) return denied(__NR_process_vm_readv, getppid(), 0, 0, 0, 0, 0, EPERM);
    if (!strcmp(mode, "process_vm_writev")) return denied(__NR_process_vm_writev, getppid(), 0, 0, 0, 0, 0, EPERM);
    if (!strcmp(mode, "io_uring_setup")) return denied(LUNAR_NR_IO_URING_SETUP, 0, 0, 0, 0, 0, 0, EPERM);
    if (!strcmp(mode, "io_uring_register")) return denied(LUNAR_NR_IO_URING_REGISTER, -1, 0, 0, 0, 0, 0, EPERM);
    if (!strcmp(mode, "io_uring_enter")) return denied(LUNAR_NR_IO_URING_ENTER, -1, 0, 0, 0, 0, 0, EPERM);
#if defined(__x86_64__)
    if (!strcmp(mode, "x32")) return denied(__NR_getpid | 0x40000000U, 0, 0, 0, 0, 0, 0, EPERM);
#endif
#if defined(__i386__)
    if (!strcmp(mode, "socketcall")) return denied(__NR_socketcall, 1, 0, 0, 0, 0, 0, EPERM);
#endif
    return 4;
}
'''


@pytest.fixture(scope="module")
def control_target(tmp_path_factory):
    root = tmp_path_factory.mktemp("target-control")
    source = root / "target.c"
    target = root / "target"
    source.write_text(_SOURCE, encoding="utf-8")
    compile_native_target(
        source, target, "-pthread", "-I", str(Path(__file__).parents[1] / "src/lunar_evolution"),
    )
    return target


@pytest.mark.parametrize("operation", [
    "setsid", "setpgid", "setns", "clone3", "kill", "tkill", "tgkill",
    "rt_sigqueueinfo", "rt_tgsigqueueinfo", "pidfd_send_signal", "pidfd_getfd",
    "process_vm_readv", "process_vm_writev",
    "io_uring_setup", "io_uring_register", "io_uring_enter",
])
def test_target_control_syscalls_are_denied_without_side_effects(control_target, tmp_path, operation):
    result = subprocess.run(
        [str(control_target), str(tmp_path), operation, "0"],
        start_new_session=True, capture_output=True, timeout=5, check=False,
    )
    if result.returncode == 77 and operation in {"tkill", "rt_sigqueueinfo", "rt_tgsigqueueinfo"}:
        pytest.skip(f"native ABI has no {operation} syscall")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith(b"-1 ")


@pytest.mark.parametrize("namespace_flag", [
    pytest.param(0x80, id="newtime"), pytest.param(0x20000, id="newns"),
    pytest.param(0x2000000, id="newcgroup"), pytest.param(0x4000000, id="newuts"),
    pytest.param(0x8000000, id="newipc"), pytest.param(0x10000000, id="newuser"),
    pytest.param(0x20000000, id="newpid"), pytest.param(0x40000000, id="newnet"),
])
def test_namespace_clone_flags_are_denied_before_invalid_kernel_operation(control_target, tmp_path, namespace_flag):
    result = subprocess.run(
        [str(control_target), str(tmp_path), "clone_namespace", hex(namespace_flag)],
        start_new_session=True, capture_output=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("operation,architecture", [("x32", "x86_64"), ("socketcall", "i386")])
def test_alternate_syscall_number_space_cannot_bypass_filter(control_target, tmp_path, operation, architecture):
    machine = platform.machine().lower()
    supported = machine in {"x86_64", "amd64"} if architecture == "x86_64" else machine in {"i386", "i486", "i586", "i686"}
    if not supported:
        pytest.skip(f"requires {architecture} ABI")
    result = subprocess.run(
        [str(control_target), str(tmp_path), operation, "0"],
        start_new_session=True, capture_output=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_ordinary_fork_vfork_and_pthread_remain_available(control_target, tmp_path):
    result = subprocess.run(
        [str(control_target), str(tmp_path), "ordinary", "0"],
        start_new_session=True, capture_output=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _ready(stream, *, timeout=5):
    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        assert selector.select(timeout), "control fixture did not reach its readiness boundary"


def test_child_cannot_leave_owned_group_and_parent_cleanup_reaps_it(control_target, tmp_path):
    process = subprocess.Popen(
        [str(control_target), str(tmp_path), "retained", "0"],
        start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        _ready(process.stdout)
        evidence = json.loads(process.stdout.readline())
        assert evidence["valid"] == 1
        assert evidence["group"] == process.pid == os.getpgid(evidence["child"])
        owner = RegisteredProcess(
            process.pid, process.pid,
            owner_check=lambda: process.poll() is None and os.getpgid(process.pid) == process.pid,
            label="isolated-control-fixture",
        )
        result = cleanup_registered_process(
            owner, grace_seconds=1, deadline=time.monotonic() + 3, reap_child=process.poll,
        )
        assert result.status == ProcessCleanupStatus.CLEANED
        assert result.term_sent and not result.kill_sent and not result.alive_after
        assert process.wait(timeout=3) == 0
        with pytest.raises(ProcessLookupError):
            os.getpgid(evidence["child"])
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        process.stdout.close()
        process.stderr.close()


def _frame(fd):
    line = bytearray()
    deadline = time.monotonic() + 5
    while not line.endswith(b"\n"):
        _ready(fd, timeout=max(0, deadline - time.monotonic()))
        chunk = os.read(fd, 1)
        assert chunk, "bootstrap closed before its expected frame"
        line.extend(chunk)
        assert len(line) < 8192
    return parse_bootstrap_handshake_frame(bytes(line[:-1]))


def test_native_isolated_target_cannot_control_guardian_or_controller(control_target, tmp_path):
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    policy = build_producer_isolation_policy(read_paths=[control_target], write_dirs=[tmp_path])
    control = encode_native_bootstrap_control(
        _launch(control_target), target_path=control_target,
        target_argv=(str(control_target), str(tmp_path), "guard", str(os.getpid())),
        target_cwd=tmp_path, isolation_policy=policy,
    )
    control_r, control_w = os.pipe()
    gate_r, gate_w = os.pipe()
    frame_r, frame_w = os.pipe()
    owner_r, owner_w = os.pipe()
    process = None
    try:
        process = subprocess.Popen(
            native_bootstrap_command(
                artifact, control_fd=control_r, gate_fd=gate_r, frame_fd=frame_w,
                controller_lifeline_fd=owner_r, deadline_monotonic_ns=time.monotonic_ns() + 5_000_000_000,
            ),
            start_new_session=True, close_fds=True, pass_fds=(control_r, gate_r, frame_w, owner_r),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": os.defpath, "LANG": "C"},
        )
        for fd in (control_r, gate_r, frame_w, owner_r):
            os.close(fd)
        control_r = gate_r = frame_w = owner_r = None
        os.write(control_w, control)
        os.close(control_w)
        control_w = None
        assert _frame(frame_r).kind == "bootstrap_ready"
        os.write(gate_w, b"1")
        os.close(gate_w)
        gate_w = None
        started = _frame(frame_r)
        assert started.kind == "target_started" and started.observed_pgid == process.pid
        assert _frame(frame_r).kind == "terminal"
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stdout + stderr
        assert stdout.count(b"-1 ") == 6
    finally:
        for fd in (control_r, control_w, gate_r, gate_w, frame_r, frame_w, owner_r, owner_w):
            if fd is not None:
                os.close(fd)
        if process is not None:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()
