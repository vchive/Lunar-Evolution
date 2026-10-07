"""Private Linux pipe/control fixtures; no devices, external PID or provider calls.

The baseline receiver is the disposable fixture parent, with SIGIO blocked.
It observes only a pipe-triggered signal; the filtered child cannot arm it.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import pytest
from _native_target_fixture import compile_native_target
from test_native_bootstrap import _launch
from test_native_fd_handoff import _sealed
from test_native_trusted_controller_death import _frame

from lunar_evolution.native_bootstrap import (
    build_native_bootstrap_artifact,
    encode_native_bootstrap_control,
    native_bootstrap_command,
)
from lunar_evolution.producer_isolation import build_producer_isolation_policy

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux descriptor control")

_SOURCE = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include "native_producer_isolation.h"

static int isolation(const char *root) {
    const char *writes[] = {root};
    return lunar_apply_isolation("linux-landlock-seccomp-v1", NULL, 0, writes, 1);
}
static int denied(long nr, int fd, uint64_t cmd, uint64_t arg) {
    /* 32-bit syscall varargs are machine words, not split uint64_t values.
       The native kernel supplies zero upper argument words on that ABI. */
    if (sizeof(unsigned long) == 4 && ((cmd >> 32) || (arg >> 32))) return 77;
    errno = 0;
    long result = syscall(nr, fd, (unsigned long)cmd, (unsigned long)arg);
    int error = errno;
    printf("{\"result\":%ld,\"errno\":%d}\n", result, error);
    return result == -1 && error == EPERM ? 0 : 20;
}
static int pipe_operations(int r, int w) {
    int count = -1, flag = O_ASYNC, old = fcntl(r, F_GETFL);
    if (old < 0 || fcntl(r, F_SETFL, old | O_NONBLOCK)) return 30;
    if (!(fcntl(r, F_GETFL) & O_NONBLOCK)) return 31;
    if (ioctl(r, FIONBIO, &flag) || ioctl(r, FIONREAD, &count) || count < 0) return 32;
    /* FIONBIO treats any nonzero payload as a boolean, not status flags. */
    int after_ioctl = fcntl(r, F_GETFL);
    if (after_ioctl < 0 || !(after_ioctl & O_NONBLOCK) || (after_ioctl & O_ASYNC)) return 32;
    if (ioctl(r, FIOCLEX) || !(fcntl(r, F_GETFD) & FD_CLOEXEC)) return 33;
    if (ioctl(r, FIONCLEX) || (fcntl(r, F_GETFD) & FD_CLOEXEC)) return 34;
    int dup = fcntl(w, F_DUPFD, 64), clo = fcntl(w, F_DUPFD_CLOEXEC, 64);
    if (dup < 0 || clo < 0 || !(fcntl(clo, F_GETFD) & FD_CLOEXEC)) return 35;
    if (fcntl(dup, F_SETFD, FD_CLOEXEC) || close(dup) || close(clo)) return 36;
    if (fcntl(r, F_GETPIPE_SZ) <= 0 || fcntl(r, F_SETFL, old)) return 37;
    return 0;
}
static int ordinary(const char *root) {
    int p[2];
    if (pipe(p)) return 40;
    int result = pipe_operations(p[0], p[1]);
    if (result) return result;
    char data[4];
    if (write(p[1], "ping", 4) != 4 || read(p[0], data, 4) != 4 || memcmp(data, "ping", 4)) return 41;
    if (close(p[0]) || close(p[1])) return 42;
    char path[4096];
    if (snprintf(path, sizeof(path), "%s/lock-file", root) >= (int)sizeof(path)) return 43;
    int file = open(path, O_CREAT | O_RDWR, 0600);
    if (file < 0) return 44;
    struct flock lock;
    memset(&lock, 0, sizeof(lock)); lock.l_type = F_WRLCK; lock.l_whence = SEEK_SET;
    if (fcntl(file, F_SETLK, &lock)) return 45;
    lock.l_type = F_UNLCK;
    if (fcntl(file, F_SETLKW, &lock)) return 46;
    lock.l_type = F_WRLCK;
    if (fcntl(file, F_GETLK, &lock) || lock.l_type != F_UNLCK) return 47;
    lock.l_type = F_WRLCK;
    if (fcntl(file, F_OFD_SETLK, &lock)) return 48;
    lock.l_type = F_UNLCK;
    if (fcntl(file, F_OFD_SETLKW, &lock)) return 49;
    lock.l_type = F_WRLCK;
    if (fcntl(file, F_OFD_GETLK, &lock) || lock.l_type != F_UNLCK) return 50;
    if (fcntl(file, F_GETLEASE) != F_UNLCK || close(file)) return 51;
    puts("{\"ordinary\":true}");
    return 0;
}
struct armed { int owner_result, owner_error, flag_result, flag_error; };
static int ordinary64(const char *root) {
#if defined(__i386__)
    int p[2];
    if (pipe(p)) return 52;
    long flags = syscall(221, p[0], F_GETFL, 0);
    if (flags < 0 || syscall(221, p[0], F_SETFL, flags | O_NONBLOCK) ||
        !(syscall(221, p[0], F_GETFL, 0) & O_NONBLOCK)) return 53;
    long duplicate = syscall(221, p[1], F_DUPFD_CLOEXEC, 64);
    if (duplicate < 0 || !(syscall(221, duplicate, F_GETFD, 0) & FD_CLOEXEC)) return 54;
    if (close((int)duplicate) || close(p[0]) || close(p[1])) return 55;
    char path[4096];
    if (snprintf(path, sizeof(path), "%s/lock64-file", root) >= (int)sizeof(path)) return 56;
    int file = open(path, O_CREAT | O_RDWR, 0600);
    if (file < 0) return 57;
    struct flock64 lock;
    memset(&lock, 0, sizeof(lock)); lock.l_type = F_WRLCK; lock.l_whence = SEEK_SET;
    if (syscall(221, file, F_SETLK64, &lock)) return 58;
    lock.l_type = F_UNLCK;
    if (syscall(221, file, F_SETLKW64, &lock) || close(file)) return 59;
    puts("{\"ordinary64\":true}");
    return 0;
#else
    (void)root;
    return 77;
#endif
}
static int signal_route(const char *root, int filtered) {
    sigset_t set, previous;
    if (sigemptyset(&set) || sigaddset(&set, SIGIO) || sigprocmask(SIG_BLOCK, &set, &previous)) return 60;
    int data[2] = {-1, -1}, ready[2] = {-1, -1}, result = 61;
    pid_t receiver = getpid(), child = -1;
    if (pipe(data) || pipe(ready)) goto cleanup;
    child = fork();
    if (child < 0) { result = 62; goto cleanup; }
    if (!child) {
        close(data[1]); close(ready[0]);
        if (filtered && isolation(root)) _exit(63);
        struct armed a;
        errno = 0; a.owner_result = fcntl(data[0], F_SETOWN, receiver); a.owner_error = errno;
        int flags = fcntl(data[0], F_GETFL);
        errno = 0; a.flag_result = fcntl(data[0], F_SETFL, flags | O_ASYNC); a.flag_error = errno;
        if (write(ready[1], &a, sizeof(a)) != (ssize_t)sizeof(a)) _exit(64);
        close(ready[1]);
        char value;
        _exit(read(data[0], &value, 1) == 1 ? 0 : 65);
    }
    close(data[0]); data[0] = -1; close(ready[1]); ready[1] = -1;
    struct armed a;
    if (read(ready[0], &a, sizeof(a)) != (ssize_t)sizeof(a)) { result = 66; goto cleanup; }
    close(ready[0]); ready[0] = -1;
    if (write(data[1], "x", 1) != 1) { result = 67; goto cleanup; }
    struct timespec wait = {.tv_sec = filtered ? 0 : 2, .tv_nsec = filtered ? 50000000 : 0};
    errno = 0;
    siginfo_t info;
    int observed = sigtimedwait(&set, &info, &wait), observed_error = errno;
    close(data[1]); data[1] = -1;
    int status;
    pid_t waited;
    do { waited = waitpid(child, &status, 0); } while (waited < 0 && errno == EINTR);
    if (waited == child || (waited < 0 && errno == ECHILD)) child = -1;
    if (waited <= 0 || !WIFEXITED(status) || WEXITSTATUS(status)) { result = 68; goto cleanup; }
    printf("{\"filtered\":%s,\"signal\":%d,\"owner_error\":%d,\"flag_error\":%d}\n",
           filtered ? "true" : "false", observed, a.owner_error, a.flag_error);
    if (filtered) result = a.owner_result == -1 && a.owner_error == EPERM && a.flag_result == -1 &&
                           a.flag_error == EPERM && observed == -1 && observed_error == EAGAIN ? 0 : 70;
    else result = a.owner_result == 0 && a.flag_result == 0 && observed == SIGIO ? 0 : 71;
cleanup:
    for (int i = 0; i < 2; ++i) {
        if (data[i] >= 0) close(data[i]);
        if (ready[i] >= 0) close(ready[i]);
    }
    if (child > 0) {
        /* Only this fixture's still-unreaped direct child: its PID cannot be
           reused. Never signal after a successful wait or ECHILD. */
        (void)kill(child, SIGKILL);
        pid_t reaped;
        do { reaped = waitpid(child, NULL, 0); } while (reaped < 0 && errno == EINTR);
    }
    /* Drain before restoring the mask, so even a failing baseline stays local. */
    struct timespec now = {0};
    while (sigtimedwait(&set, NULL, &now) >= 0) {}
    if (sigprocmask(SIG_SETMASK, &previous, NULL)) return 69;
    return result;
}
static int native_pipes(int target_fd) {
    int seals = fcntl(target_fd, F_GET_SEALS);
    int required = F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL;
    if (target_fd < 3 || seals < 0 || (seals & required) != required ||
        (fcntl(target_fd, F_GETFD) & FD_CLOEXEC)) return 79;
    const char *rv = getenv("LUNAR_PRODUCER_RESPONSE_FD"), *wv = getenv("LUNAR_PRODUCER_REQUEST_FD");
    if (!rv || !wv) return 80;
    int r = atoi(rv), w = atoi(wv), result = pipe_operations(r, w);
    if (result) return result;
    /* stdout is an allowed host pipe too. Reject its control requests. */
    errno = 0;
    if (fcntl(STDOUT_FILENO, F_SETOWN, getpid()) != -1 || errno != EPERM) return 81;
    int value = 1;
    errno = 0;
    if (ioctl(w, FIOASYNC, &value) != -1 || errno != EPERM) return 82;
    char reply[4];
    if (write(w, "ping", 4) != 4 || read(r, reply, 4) != 4 || memcmp(reply, "pong", 4)) return 83;
    puts("{\"broker\":true,\"control_denied\":true}");
    return 0;
}
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    const char *mode = argv[2];
    if (!strcmp(mode, "baseline") || !strcmp(mode, "filtered-route"))
        return signal_route(argv[1], !strcmp(mode, "filtered-route"));
    if (!strcmp(mode, "native")) return native_pipes(atoi(argv[3]));
    if (isolation(argv[1])) return 3;
    if (!strcmp(mode, "ordinary")) return ordinary(argv[1]);
    if (!strcmp(mode, "ordinary64")) return ordinary64(argv[1]);
    int p[2];
    if (pipe(p)) return 4;
    uint64_t command = strtoull(argv[3], NULL, 0);
    if (!strcmp(mode, "fcntl")) return denied(__NR_fcntl, p[0], command, 0);
    if (!strcmp(mode, "flags")) return denied(__NR_fcntl, p[0], F_SETFL, command);
    if (!strcmp(mode, "ioctl")) return denied(__NR_ioctl, p[0], command, 0);
    if (!strcmp(mode, "fcntl64") || !strcmp(mode, "flags64")) {
#if defined(__i386__)
        return !strcmp(mode, "flags64") ? denied(221, p[0], F_SETFL, command) :
                                           denied(221, p[0], command, 0);
#else
        return 77;
#endif
    }
    return 5;
}
'''


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    root = tmp_path_factory.mktemp("fd-control")
    source, target = root / "target.c", root / "target"
    source.write_text(_SOURCE, encoding="utf-8")
    compile_native_target(source, target, "-I", str(Path(__file__).parents[1] / "src/lunar_evolution"))
    return target, build_native_bootstrap_artifact(root / "install")


def _probe(compiled, tmp_path, mode, argument=0):
    target, _artifact = compiled
    process = subprocess.Popen(
        [str(target), str(tmp_path), mode, str(argument)],
        start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = process.communicate(timeout=6)
    finally:
        # Do not poll/reap before failure cleanup: an unreaped private session
        # leader holds its PID, including when it exited before pipe EOF.
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=3)
        process.stdout.close()
        process.stderr.close()
    if process.returncode == 77:
        if mode in {"fcntl64", "flags64", "ordinary64"}:
            pytest.skip("fcntl64 is a separate syscall only on i386; upper words require a 64-bit ABI")
        if argument > 0xFFFFFFFF:
            pytest.skip("nonzero upper syscall words require a 64-bit ABI")
    assert process.returncode == 0, (process.returncode, stdout, stderr)
    return json.loads(stdout)


def test_private_unfiltered_pipe_can_notify_its_disposable_receiver(compiled, tmp_path):
    observed = _probe(compiled, tmp_path, "baseline")
    assert observed == {"filtered": False, "signal": signal.SIGIO, "owner_error": 0, "flag_error": 0}


def test_filtered_pipe_cannot_arm_kernel_signal_route(compiled, tmp_path):
    observed = _probe(compiled, tmp_path, "filtered-route")
    assert observed == {"filtered": True, "signal": -1, "owner_error": 1, "flag_error": 1}


@pytest.mark.parametrize("command", [
    pytest.param(8, id="setown"), pytest.param(9, id="getown"),
    pytest.param(10, id="setsig"), pytest.param(11, id="getsig"),
    pytest.param(15, id="setown-ex"), pytest.param(16, id="getown-ex"),
    pytest.param(17, id="getowner-uids"), pytest.param(1024, id="setlease"),
    pytest.param(1026, id="notify"), pytest.param(1029, id="cancellk"),
    pytest.param(1031, id="setpipe-size"), pytest.param(1033, id="add-seals"),
    pytest.param(0x7FFFFFFF, id="unknown"), pytest.param(0xFFFFFFFF, id="negative-word"),
    pytest.param(0x100000008, id="upper-setown"), pytest.param(0x100000001, id="upper-allowed-getfd"),
])
@pytest.mark.parametrize("entry", ["fcntl", "fcntl64"])
def test_unadmitted_fcntl_commands_refuse_before_kernel_operation(compiled, tmp_path, command, entry):
    assert _probe(compiled, tmp_path, entry, command) == {"result": -1, "errno": 1}


@pytest.mark.parametrize("flags", [
    pytest.param(0x2000, id="async"), pytest.param(0x2800, id="async-nonblocking"),
    pytest.param(0x100000000, id="upper-only"), pytest.param(0x100002000, id="upper-async"),
    pytest.param(0xFFFFFFFFFFFFFFFF, id="negative"),
])
@pytest.mark.parametrize("entry", ["flags", "flags64"])
def test_setfl_refuses_async_and_noncanonical_flags(compiled, tmp_path, flags, entry):
    assert _probe(compiled, tmp_path, entry, flags) == {"result": -1, "errno": 1}


@pytest.mark.parametrize("ioctl_request", [
    pytest.param(0x5452, id="fioasync"), pytest.param(0x8901, id="fiosetown"),
    pytest.param(0x8902, id="siocspgrp"), pytest.param(0x8903, id="fiogetown"),
    pytest.param(0x5412, id="tiocsti"), pytest.param(0x5402, id="tcsets"),
    pytest.param(0x40086602, id="fs-setflags-native64"),
    pytest.param(0x40046602, id="fs-setflags-native32"),
    pytest.param(0xFFFFFFFF, id="unknown"), pytest.param(0x10000541B, id="upper-fionread"),
    pytest.param(0x100005452, id="upper-fioasync"),
])
def test_unknown_and_device_ioctl_requests_are_denied_on_private_pipe(compiled, tmp_path, ioctl_request):
    assert _probe(compiled, tmp_path, "ioctl", ioctl_request) == {"result": -1, "errno": 1}


def test_ordinary_pipe_descriptor_nonblocking_and_advisory_locks_work(compiled, tmp_path):
    assert _probe(compiled, tmp_path, "ordinary") == {"ordinary": True}


def test_i386_fcntl64_keeps_ordinary_descriptor_and_large_file_locks(compiled, tmp_path):
    assert _probe(compiled, tmp_path, "ordinary64") == {"ordinary64": True}


def test_native_sealed_target_and_broker_pipes_keep_io_but_deny_control(compiled, tmp_path):
    target, artifact = compiled
    with ExitStack() as stack:
        owned = set()

        def close(fd):
            if fd in owned:
                owned.remove(fd)
                os.close(fd)

        def pipe():
            ends = os.pipe()
            for fd in ends:
                owned.add(fd)
                stack.callback(close, fd)
            return ends

        control_r, control_w = pipe()
        gate_r, gate_w = pipe()
        frame_r, frame_w = pipe()
        owner_r, _owner_w = pipe()
        request_r, request_w = pipe()
        response_r, response_w = pipe()
        target_fd = stack.enter_context(_sealed(target))
        policy = build_producer_isolation_policy(read_paths=[target], write_dirs=[tmp_path])
        control = encode_native_bootstrap_control(
            _launch(target), target_path=target, target_fd=target_fd,
            target_argv=(str(target), str(tmp_path), "native", str(target_fd)), target_cwd=tmp_path,
            isolation_policy=policy,
        )
        process = subprocess.Popen(
            native_bootstrap_command(
                artifact, control_fd=control_r, gate_fd=gate_r, frame_fd=frame_w,
                controller_lifeline_fd=owner_r, deadline_monotonic_ns=time.monotonic_ns() + 10_000_000_000,
            ),
            pass_fds=(control_r, gate_r, frame_w, owner_r, target_fd, request_w, response_r),
            start_new_session=True, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": os.defpath, "LANG": "C", "LUNAR_PRODUCER_REQUEST_FD": str(request_w),
                 "LUNAR_PRODUCER_RESPONSE_FD": str(response_r)},
        )
        try:
            for fd in (control_r, gate_r, frame_w, owner_r, request_w, response_r):
                close(fd)
            os.write(control_w, control)
            close(control_w)
            os.write(response_w, b"pong")
            assert _frame(frame_r).kind == "bootstrap_ready"
            os.write(gate_w, b"1")
            close(gate_w)
            assert _frame(frame_r).kind == "target_started"
            assert _frame(frame_r).kind == "terminal"
            stdout, stderr = process.communicate(timeout=5)
            assert process.returncode == 0, (stdout, stderr)
            assert json.loads(stdout) == {"broker": True, "control_denied": True}
            assert os.read(request_r, 4) == b"ping"
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()
