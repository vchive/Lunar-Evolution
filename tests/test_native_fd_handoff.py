"""Actual Linux inherited-FD closure with disposable, local inert handles.

The bootstrap implementation closes finite close_range gaps through UINT_MAX.
The target's bounded census is a fixture only. Standard streams are deliberately
host-controlled; the necessary sealed target handle and fresh broker pipes may
remain inherited. No model, remote evaluator or external address is used.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_native_bootstrap import _launch
from test_native_trusted_controller_death import _frame

from lunar_evolution.native_bootstrap import (
    build_native_bootstrap_artifact,
    encode_native_bootstrap_control,
    native_bootstrap_command,
    native_bootstrap_source_path,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux inherited-FD handoff")

_TARGET = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

static int closed(int fd) {
    errno = 0;
    if (fcntl(fd, F_GETFD) != -1 || errno != EBADF) return 0;
    errno = 0;
    if (write(fd, "unwanted", 8) != -1 || errno != EBADF) return 0;
    return 1;
}
static int census(int argc, char **argv, int target, int r, int w) {
    for (int i = 3; i < argc; ++i) if (!closed(atoi(argv[i]))) return 0;
    for (int fd = 3; fd < 4096; ++fd) {
        if (fd == target || fd == r || fd == w) continue;
        if (!closed(fd)) return 0;
    }
    if (target >= 0) {
        struct stat info;
        int seals = fcntl(target, F_GET_SEALS);
        int required = F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL;
        if (fstat(target, &info) || !S_ISREG(info.st_mode) || info.st_nlink != 0 ||
            seals < 0 || (seals & required) != required ||
            (fcntl(target, F_GETFD) & FD_CLOEXEC)) return 0;
    }
    return 1;
}
int main(int argc, char **argv) {
    if (argc < 3) return 2;
    int target = atoi(argv[2]), r = -1, w = -1;
    const char *response = getenv("LUNAR_PRODUCER_RESPONSE_FD");
    const char *request = getenv("LUNAR_PRODUCER_REQUEST_FD");
    if (response && request) { r = atoi(response); w = atoi(request); }
    if (!census(argc, argv, target, r, w)) return 3;
    pid_t child = fork();
    if (child < 0) return 4;
    if (!child) _exit(census(argc, argv, target, r, w) ? 0 : 5);
    int status;
    if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) return 6;
    if (!strcmp(argv[1], "broker")) {
        char reply[4];
        if (r < 0 || w < 0 || (fcntl(r, F_GETFL) & O_ACCMODE) != O_RDONLY ||
            (fcntl(w, F_GETFL) & O_ACCMODE) != O_WRONLY || write(w, "ping", 4) != 4 ||
            read(r, reply, 4) != 4 || memcmp(reply, "pong", 4)) return 7;
    }
    int marker = open("marker", O_CREAT | O_WRONLY, 0600);
    if (marker < 0 || write(marker, "ran", 3) != 3 || close(marker)) return 8;
    printf("{\"closed\":true,\"fork_closed\":true,\"target_open\":%s,\"broker\":%s}\n",
           target >= 0 ? "true" : "false", r >= 0 ? "true" : "false");
    return 0;
}
'''


@contextmanager
def _sealed(source: Path):
    fd = os.memfd_create("lunar-fd-handoff-fixture", os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
    try:
        data = source.read_bytes()
        assert os.write(fd, data) == len(data)
        os.fchmod(fd, 0o700)
        seals = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
        yield fd
    finally:
        os.close(fd)


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    root = tmp_path_factory.mktemp("fd-handoff-native")
    source, target = root / "target.c", root / "target"
    source.write_text(_TARGET)
    compile_native_target(source, target)
    artifact = build_native_bootstrap_artifact(root / "install")
    return target, artifact


@contextmanager
def _start(
    tmp_path, compiled, *, extras=(), env_builder=None, target_alias=None,
    sealed_target=True, sealed_bootstrap=True, guarded=False, bootstrap=None, script=False,
):
    target, artifact = compiled
    if script:
        target = tmp_path / "script"
        target.write_text('#!/bin/sh\nprintf ran > marker\nprintf "shebang-ok\\n"\n')
        target.chmod(0o700)
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
        target_fd = stack.enter_context(_sealed(target)) if sealed_target else None
        selected = bootstrap or artifact.path
        bootstrap_fd = stack.enter_context(_sealed(selected)) if sealed_bootstrap else None
        inherited = [control_r, gate_r, frame_w, owner_r, *extras]
        if target_fd is not None:
            inherited.append(target_fd)
        if bootstrap_fd is not None:
            inherited.append(bootstrap_fd)
        reserved = {
            "control": control_r, "gate": gate_r, "frame": frame_w, "owner": owner_r,
            "target": target_fd, "stdin": 0, "stdout": 1, "stderr": 2,
        }
        env = {"PATH": os.defpath}
        mode = "census"
        if env_builder:
            additions, broker_fds = env_builder(reserved)
            env.update(additions)
            inherited.extend(broker_fds)
            mode = "broker"
        value = reserved[target_alias] if target_alias else target_fd
        checked = [control_r, gate_r, frame_w, owner_r, *extras]
        if bootstrap_fd is not None:
            checked.append(bootstrap_fd)
        arguments = (str(target), mode, str(target_fd if target_fd is not None else -1),
                     *(str(fd) for fd in checked))
        control = encode_native_bootstrap_control(
            _launch(target), target_path=target, target_argv=arguments, target_cwd=tmp_path,
            target_fd=value,
        )
        kwargs = {}
        if guarded:
            kwargs = {"controller_lifeline_fd": owner_r,
                      "deadline_monotonic_ns": time.monotonic_ns() + 10_000_000_000,
                      "child_supervision": "linux-subreaper-v1"}
        command = native_bootstrap_command(
            selected, control_fd=control_r, gate_fd=gate_r, frame_fd=frame_w, **kwargs,
        )
        process = subprocess.Popen(
            command, executable=f"/proc/self/fd/{bootstrap_fd}" if bootstrap_fd else None,
            pass_fds=tuple(set(inherited)), close_fds=True, start_new_session=True,
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        os.write(control_w, control)
        fixture = SimpleNamespace(
            process=process, gate=gate_w, frame=frame_r, control=control_w, close=close,
        )
        try:
            yield fixture
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()


def _release(fixture):
    fixture.close(fixture.control)
    assert _frame(fixture.frame).kind == "bootstrap_ready"
    os.write(fixture.gate, b"1")
    fixture.close(fixture.gate)


def _result(fixture):
    stdout, stderr = fixture.process.communicate(timeout=5)
    # Frame writer is still owned by the fixture host, so read exactly the
    # expected number rather than waiting for host-held writer EOF.
    return stdout, stderr


@pytest.mark.parametrize("sealed_target", [False, True], ids=["path-target", "sealed-target"])
def test_post_exec_closes_disposable_extra_handles_and_bootstrap(tmp_path, compiled, sealed_target):
    with ExitStack() as stack:
        victim = tmp_path / "owned-victim"
        victim.write_bytes(b"unchanged")
        regular = os.open(victim, os.O_RDWR)
        directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        extra_pipe = os.pipe()
        fifo = tmp_path / "owned-named-fifo"
        os.mkfifo(fifo, 0o600)
        fifo_r = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        fifo_w = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        for fd in (regular, directory, *extra_pipe, fifo_r, fifo_w):
            stack.callback(os.close, fd)
        left, right = socket.socketpair()
        stack.callback(left.close)
        stack.callback(right.close)
        extras = (regular, directory, *extra_pipe, fifo_r, fifo_w, left.fileno(), right.fileno())
        with _start(tmp_path, compiled, extras=extras, sealed_target=sealed_target) as fixture:
            _release(fixture)
            assert _frame(fixture.frame).kind == "target_started"
            assert _frame(fixture.frame).kind == "terminal"
            stdout, stderr = _result(fixture)
            assert fixture.process.returncode == 0, stderr
            assert json.loads(stdout) == {
                "closed": True, "fork_closed": True, "target_open": sealed_target, "broker": False,
            }
        assert victim.read_bytes() == b"unchanged"
        assert not (tmp_path / "unwanted").exists()


def test_high_inherited_fd_is_closed_without_a_rlimit_scan(tmp_path, compiled):
    victim = tmp_path / "high-owned-victim"
    victim.write_bytes(b"unchanged")
    original = os.open(victim, os.O_RDWR)
    try:
        high = fcntl.fcntl(original, fcntl.F_DUPFD_CLOEXEC, 2048)
        try:
            # Lower the real child soft limit after descriptors were inherited.
            # A current-RLIMIT census would miss this already-open high handle.
            anchor = "static int handoff_close_extra(int target_fd, int error_fd, int broker_r, int broker_w) {"
            replacement = anchor + (
                "\nstruct rlimit limit; if (getrlimit(RLIMIT_NOFILE, &limit)) return EIO;"
                "limit.rlim_cur = 64; if (setrlimit(RLIMIT_NOFILE, &limit)) return EIO;"
            )
            bootstrap = _fault_bootstrap(
                tmp_path, "#include <sys/resource.h>", (anchor, replacement),
            )
            with _start(tmp_path, compiled, extras=(high,), bootstrap=bootstrap) as fixture:
                _release(fixture)
                assert _frame(fixture.frame).kind == "target_started"
                assert _frame(fixture.frame).kind == "terminal"
                stdout, stderr = _result(fixture)
                assert fixture.process.returncode == 0, stderr
                assert json.loads(stdout)["closed"] is True
            assert victim.read_bytes() == b"unchanged"
        finally:
            os.close(high)
    finally:
        os.close(original)


def _broker_env(r, w):
    return {"LUNAR_PRODUCER_RESPONSE_FD": str(r), "LUNAR_PRODUCER_REQUEST_FD": str(w)}


def test_two_fresh_anonymous_broker_pipes_exchange_and_stdout_work(tmp_path, compiled):
    request_r, request_w = os.pipe()
    response_r, response_w = os.pipe()
    try:
        def broker(_):
            return _broker_env(response_r, request_w), (response_r, request_w)

        with _start(tmp_path, compiled, env_builder=broker, guarded=True) as fixture:
            os.write(response_w, b"pong")
            _release(fixture)
            assert _frame(fixture.frame).kind == "target_started"
            assert _frame(fixture.frame).kind == "terminal"
            stdout, stderr = _result(fixture)
            assert fixture.process.returncode == 0, stderr
            assert json.loads(stdout)["broker"] is True
            assert os.read(request_r, 4) == b"ping"
    finally:
        for fd in (request_r, request_w, response_r, response_w):
            os.close(fd)


@pytest.mark.parametrize("case", [
    "missing-read", "missing-write", "empty", "plus", "minus", "space", "leading-zero",
    "trailing", "overflow", "same-fd", "reversed", "same-pipe", "regular", "directory",
    "socket", "named-fifo", "opath", "control", "gate", "frame", "owner", "target",
    "stdin", "stdout", "stderr",
])
def test_invalid_broker_refuses_before_target_start(tmp_path, compiled, case):
    with ExitStack() as stack:
        read, write = os.pipe()
        other_read, other_write = os.pipe()
        for fd in (read, write, other_read, other_write):
            stack.callback(os.close, fd)
        replacement = None
        if case == "regular":
            path = tmp_path / "regular"
            path.write_bytes(b"unchanged")
            replacement = os.open(path, os.O_RDONLY)
        elif case == "directory":
            replacement = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        elif case == "socket":
            left, right = socket.socketpair()
            stack.callback(left.close)
            stack.callback(right.close)
            replacement = left.fileno()
        elif case == "named-fifo":
            path = tmp_path / "named-fifo"
            os.mkfifo(path, 0o600)
            replacement = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        elif case == "opath":
            replacement = os.open(f"/proc/self/fd/{read}", os.O_PATH | os.O_CLOEXEC)
        if replacement is not None and case != "socket":
            stack.callback(os.close, replacement)

        def broker(reserved):
            env = _broker_env(read, other_write)
            passed = [read, write, other_read, other_write]
            if replacement is not None:
                env["LUNAR_PRODUCER_RESPONSE_FD"] = str(replacement)
                passed.append(replacement)
            elif case in reserved:
                env["LUNAR_PRODUCER_RESPONSE_FD"] = str(reserved[case])
            elif case == "missing-read":
                env.pop("LUNAR_PRODUCER_RESPONSE_FD")
            elif case == "missing-write":
                env.pop("LUNAR_PRODUCER_REQUEST_FD")
            elif case in {"empty", "plus", "minus", "space", "leading-zero", "trailing", "overflow"}:
                env["LUNAR_PRODUCER_RESPONSE_FD"] = {
                    "empty": "", "plus": f"+{read}", "minus": f"-{read}", "space": f" {read}",
                    "leading-zero": f"0{read}", "trailing": f"{read}x", "overflow": "2147483648",
                }[case]
            elif case == "same-fd":
                env["LUNAR_PRODUCER_REQUEST_FD"] = str(read)
            elif case == "reversed":
                env = _broker_env(write, other_read)
            elif case == "same-pipe":
                env = _broker_env(read, write)
            return env, passed

        with _start(tmp_path, compiled, env_builder=broker, guarded=True) as fixture:
            _release(fixture)
            assert _frame(fixture.frame).kind == "target_start_failed"
            stdout, stderr = _result(fixture)
            assert fixture.process.returncode == 73, stderr
            assert stdout == b""
            assert not (tmp_path / "marker").exists()


@pytest.mark.parametrize("alias", ["control", "gate", "frame", "owner", "stdin", "stdout", "stderr"])
def test_target_fd_reserved_alias_refuses_before_hash_or_dup2(tmp_path, compiled, alias):
    with _start(tmp_path, compiled, target_alias=alias, guarded=True) as fixture:
        _release(fixture)
        assert _frame(fixture.frame).kind == "target_start_failed"
        stdout, stderr = _result(fixture)
        assert fixture.process.returncode == 73, stderr
        assert stdout == b""
        assert not (tmp_path / "marker").exists()


def test_sealed_shebang_target_keeps_necessary_fd_compatibility(tmp_path, compiled):
    with _start(tmp_path, compiled, script=True) as fixture:
        _release(fixture)
        assert _frame(fixture.frame).kind == "target_started"
        assert _frame(fixture.frame).kind == "terminal"
        stdout, stderr = _result(fixture)
        assert fixture.process.returncode == 0, stderr
        assert stdout == b"shebang-ok\n"
        assert (tmp_path / "marker").read_bytes() == b"ran"


@pytest.mark.parametrize("case", [
    "control-gate", "control-frame", "gate-frame", "stdin", "stdout", "stderr",
    "control-plus", "gate-space", "frame-leading-zero", "owner-stdin", "owner-stdout",
    "owner-stderr", "owner-plus", "owner-space", "owner-leading-zero", "owner-frame",
])
def test_raw_protocol_aliases_refuse_before_control_read(tmp_path, compiled, case):
    _target, artifact = compiled
    with ExitStack() as stack:
        descriptors = []
        for _ in range(4):
            read, write = os.pipe()
            stack.callback(os.close, read)
            stack.callback(os.close, write)
            descriptors.append(read)
        control, gate, frame, owner = map(str, descriptors)
        if case == "control-gate":
            gate = control
        elif case == "control-frame":
            frame = control
        elif case == "gate-frame":
            frame = gate
        elif case in {"stdin", "stdout", "stderr"}:
            control = {"stdin": "0", "stdout": "1", "stderr": "2"}[case]
        elif case == "control-plus":
            control = f"+{control}"
        elif case == "gate-space":
            gate = f" {gate}"
        elif case == "frame-leading-zero":
            frame = f"0{frame}"
        elif case == "owner-stdin":
            owner = "0"
        elif case == "owner-stdout":
            owner = "1"
        elif case == "owner-stderr":
            owner = "2"
        elif case == "owner-plus":
            owner = f"+{owner}"
        elif case == "owner-space":
            owner = f" {owner}"
        elif case == "owner-leading-zero":
            owner = f"0{owner}"
        elif case == "owner-frame":
            owner = frame
        command = [str(artifact.path), "--control-fd", control, "--gate-fd", gate,
                   "--frame-fd", frame]
        if case.startswith("owner-"):
            command.extend(["--controller-lifeline-fd", owner])
        # Empty control writers stay open. Reading them would time out, so a
        # bounded zero-output exit proves rejection occurred before that read.
        process = subprocess.run(
            command, pass_fds=tuple(descriptors), close_fds=True, start_new_session=True,
            stdin=subprocess.DEVNULL, capture_output=True, timeout=3, check=False,
            env={"PATH": os.defpath},
        )
        assert process.returncode == 64
        assert process.stdout == process.stderr == b""


def _fault_bootstrap(tmp_path, insertion, replacement):
    source = native_bootstrap_source_path()
    text = source.read_text()
    text = text.replace("static int handoff_close_extra(", insertion + "\nstatic int handoff_close_extra(")
    text = text.replace(*replacement)
    edited, target = tmp_path / "fault-bootstrap.c", tmp_path / "fault-bootstrap"
    edited.write_text(text)
    compiler = shutil.which("clang") or shutil.which("cc")
    assert compiler is not None
    result = subprocess.run(
        [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
         "-I", str(source.parent), str(edited), "-o", str(target)],
        check=False, capture_output=True, timeout=30, env={"PATH": os.defpath, "LANG": "C"},
    )
    (tmp_path / "fault-bootstrap.compiler.stderr").write_bytes(result.stderr)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return target


@pytest.mark.parametrize("failure", [errno.ENOSYS, errno.EPERM, errno.EIO])
@pytest.mark.parametrize("failed_call", [1, 2, 3], ids=["first-gap", "middle-gap", "uintmax-tail"])
@pytest.mark.parametrize("guarded", [False, True], ids=["fixture", "formal-guardian"])
def test_close_range_failure_is_explicit_pre_exec_refusal(
    tmp_path, compiled, failure, failed_call, guarded,
):
    insertion = (
        "static long fixture_close_range(unsigned int first, unsigned int last, unsigned int flags) {"
        f"static int calls; if (++calls == {failed_call}) {{errno={failure}; return -1;}}"
        "return syscall((long)__NR_close_range, first, last, flags); }"
    )
    bootstrap = _fault_bootstrap(
        tmp_path, insertion, ("syscall(__NR_close_range,", "fixture_close_range("),
    )
    with _start(tmp_path, compiled, bootstrap=bootstrap, guarded=guarded) as fixture:
        _release(fixture)
        assert _frame(fixture.frame).kind == "target_start_failed"
        stdout, stderr = _result(fixture)
        assert fixture.process.returncode == (-signal.SIGKILL if guarded else 76), stderr
        assert stdout == b""
        assert not (tmp_path / "marker").exists()


def test_exec_error_cloexec_failure_refuses_before_fork(tmp_path, compiled):
    bootstrap = _fault_bootstrap(
        tmp_path, "",
        ("if (fcntl(exec_pipe[1], F_SETFD, FD_CLOEXEC) != 0)", "if ((errno = EIO, 1))"),
    )
    with _start(tmp_path, compiled, bootstrap=bootstrap) as fixture:
        _release(fixture)
        assert _frame(fixture.frame).kind == "target_start_failed"
        stdout, stderr = _result(fixture)
        assert fixture.process.returncode == 71, stderr
        assert stdout == b""
        assert not (tmp_path / "marker").exists()


def test_old_close_range_headers_keep_actual_finite_closure(tmp_path, compiled):
    anchor = "#if !defined(__NR_close_range) &&"
    bootstrap = _fault_bootstrap(tmp_path, "", (anchor, "#undef __NR_close_range\n" + anchor))
    with _start(tmp_path, compiled, bootstrap=bootstrap) as fixture:
        _release(fixture)
        assert _frame(fixture.frame).kind == "target_started"
        assert _frame(fixture.frame).kind == "terminal"
        stdout, stderr = _result(fixture)
        assert fixture.process.returncode == 0, stderr
        assert json.loads(stdout)["closed"] is True


@pytest.mark.parametrize("collision", ["exec_pipe[0]", "exec_pipe[1]"])
def test_live_target_exec_error_collision_refuses_before_close_or_dup2(tmp_path, compiled, collision):
    # In a real fresh handoff open descriptors cannot share a number. This
    # narrow source seam checks the explicit defensive branch before any dup2.
    bootstrap = _fault_bootstrap(
        tmp_path, "", ("pid_t child = fork();", f"c.target_fd = {collision}; pid_t child = fork();"),
    )
    with _start(tmp_path, compiled, bootstrap=bootstrap) as fixture:
        _release(fixture)
        assert _frame(fixture.frame).kind == "target_start_failed"
        stdout, stderr = _result(fixture)
        assert fixture.process.returncode == 76, stderr
        assert stdout == b""
        assert not (tmp_path / "marker").exists()
