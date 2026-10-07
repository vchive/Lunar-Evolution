"""Linux waitable-descendant supervision uses only bounded local C fixtures.

Descendants redirect their standard streams and the direct target exits first;
the assertions concern the bootstrap's lifetime and terminal frame, rather than
an inherited output pipe delaying a Python ``communicate`` call. These tests do
not claim containment of a target that escapes the original process group.
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_native_bootstrap import _launch
from test_native_trusted_controller_death import _frame, _state, _stopped

from lunar_evolution.native_bootstrap import (
    NativeBootstrapError,
    build_native_bootstrap_artifact,
    encode_native_bootstrap_control,
    native_bootstrap_command,
    native_bootstrap_source_path,
)

_LINUX_ONLY = pytest.mark.skipif(sys.platform != "linux", reason="Linux subreaper fixture")

_TARGET = r'''
#define _GNU_SOURCE
#include <fcntl.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static void marker(const char *name, long value) {
    int fd = open(name, O_CREAT | O_TRUNC | O_WRONLY, 0600);
    char data[32];
    int count = snprintf(data, sizeof(data), "%ld", value);
    if (fd < 0 || write(fd, data, (size_t)count) != count || close(fd)) _exit(91);
}

static int descendant(void *opaque) {
    int index = (int)(uintptr_t)opaque;
    int sink = open("/dev/null", O_RDWR);
    if (sink < 0 || dup2(sink, 0) < 0 || dup2(sink, 1) < 0 || dup2(sink, 2) < 0)
        _exit(92);
    if (sink > 2) close(sink);
    char name[64];
    snprintf(name, sizeof(name), "descendant-%d.pid", index);
    marker(name, (long)getpid());
    /* Failure teardown is bounded even if a test never creates its release. */
    for (int attempt = 0; attempt < 1000; ++attempt) {
        if (access("release-descendants", F_OK) == 0) {
            snprintf(name, sizeof(name), "descendant-%d.done", index);
            marker(name, 1);
            _exit(47);
        }
        usleep(20000);
    }
    _exit(93);
}

int main(void) {
#if FIXTURE_KIND == 4
    char *stack = malloc(65536);
    /* Clone compatibility: Linux may convert the signal on orphan adoption.
       The direct-bootstrap clone seam below separately proves __WALL. */
    if (!stack || clone(descendant, stack + 65536, 0, NULL) < 0) return 94;
#else
    int count = FIXTURE_KIND == 2 ? 3 : 1;
    for (int index = 0; index < count; ++index) {
        pid_t child = fork();
        if (child < 0) return 95;
        if (child == 0) {
#if FIXTURE_KIND == 3
            pid_t grandchild = fork();
            if (grandchild < 0) _exit(96);
            if (grandchild > 0) _exit(39);
#endif
            descendant((void *)(uintptr_t)index);
        }
    }
#endif
    marker("direct-returning", DIRECT_EXIT);
    _exit(DIRECT_EXIT);
}
'''


def _target(tmp_path: Path, *, kind: int = 1, direct_exit: int = 0) -> Path:
    source, target = tmp_path / "target.c", tmp_path / "target"
    source.write_text(_TARGET)
    compile_native_target(source, target, f"-DFIXTURE_KIND={kind}", f"-DDIRECT_EXIT={direct_exit}")
    return target


def _wait_file(path: Path, *, timeout: float = 3) -> str:
    deadline = time.monotonic() + timeout
    while True:
        if path.exists():
            value = path.read_text()
            if value:
                return value
        assert time.monotonic() < deadline, f"local fixture did not publish {path.name}"
        time.sleep(0.01)


def _close(fixture, name: str) -> None:
    fd = getattr(fixture, name)
    if fd is not None:
        os.close(fd)
        setattr(fixture, name, None)


@contextmanager
def _supervised(
    tmp_path: Path, *, kind: int = 1, direct_exit: int = 0, entry: str = "formal",
    allowance_seconds: float = 12, bootstrap: Path | None = None, launcher: Path | None = None,
):
    target = _target(tmp_path, kind=kind, direct_exit=direct_exit)
    artifact = build_native_bootstrap_artifact(tmp_path / "install") if bootstrap is None else None
    selected = artifact if artifact is not None else bootstrap
    control = encode_native_bootstrap_control(
        _launch(target), target_path=target, target_argv=(str(target),), target_cwd=tmp_path,
    )
    control_r, control_w = os.pipe()
    gate_r, gate_w = os.pipe()
    frame_r, frame_w = os.pipe()
    owner_r, owner_w = os.pipe()
    deadline_ns = time.monotonic_ns() + int(allowance_seconds * 1_000_000_000)
    kwargs = {}
    if entry != "unguarded":
        kwargs["controller_lifeline_fd"] = owner_r
    if entry in {"deadline", "formal"}:
        kwargs["deadline_monotonic_ns"] = deadline_ns
    if entry == "formal":
        kwargs["child_supervision"] = "linux-subreaper-v1"
    # Passing the path preserves legacy argv7/9/11 even with the new artifact.
    command = native_bootstrap_command(
        selected if entry == "formal" else selected.path,
        control_fd=control_r, gate_fd=gate_r, frame_fd=frame_w, **kwargs,
    )
    if launcher is not None:
        command = (str(launcher), *command)
    process = subprocess.Popen(
        command, pass_fds=(control_r, gate_r, frame_w, owner_r), close_fds=True,
        start_new_session=True, env={"PATH": os.defpath}, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmp_path,
    )
    for fd in (control_r, gate_r, frame_w, owner_r):
        os.close(fd)
    fixture = SimpleNamespace(
        process=process, gate=gate_w, frame=frame_r, owner=owner_w,
        deadline_ns=deadline_ns, artifact=artifact,
    )
    try:
        os.write(control_w, control)
    finally:
        os.close(control_w)
    try:
        yield fixture
    finally:
        for name in ("gate", "frame", "owner"):
            _close(fixture, name)
        # Emergency teardown is confined to this new session and its known PIDs.
        active = process.poll() is None
        pid_paths = [*tmp_path.glob("descendant-*.pid"), tmp_path / "non-sigchld.pid"]
        for path in pid_paths:
            if not path.exists():
                continue
            try:
                pid = int(path.read_text())
                active |= bool(_state(pid)) and os.getpgid(pid) == process.pid
            except (ValueError, ProcessLookupError):
                pass
        if active:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=3)
        process.stdout.close()
        process.stderr.close()


def _started_with_descendants(fixture, tmp_path: Path, *, count: int = 1):
    assert _frame(fixture.frame).kind == "bootstrap_ready"
    os.write(fixture.gate, b"1")
    _close(fixture, "gate")
    started = _frame(fixture.frame)
    assert started.kind == "target_started"
    descendants = [int(_wait_file(tmp_path / f"descendant-{index}.pid")) for index in range(count)]
    _wait_file(tmp_path / "direct-returning")
    _stopped(started.observed_pid)
    for pid in descendants:
        assert os.getpgid(pid) == fixture.process.pid == started.observed_pgid
        assert _state(pid) and not _state(pid).startswith("Z")
    assert fixture.process.poll() is None, "bootstrap exited while its waitable descendants run"
    assert not select.select([fixture.frame], [], [], 0.15)[0], "terminal preceded descendant drain"
    return started, descendants


@pytest.mark.parametrize("invalid", ["", "linux-subreaper-v2", "darwin", True, 1])
def test_command_rejects_unknown_child_supervision(invalid):
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_child_supervision_invalid"):
        native_bootstrap_command(
            "fixture", control_fd=1, gate_fd=2, frame_fd=3, controller_lifeline_fd=4,
            deadline_monotonic_ns=5, child_supervision=invalid,
        )


@pytest.mark.parametrize("missing", ["lifeline", "deadline", "both"])
def test_command_requires_original_owner_and_deadline_for_child_supervision(missing):
    kwargs = {"child_supervision": "linux-subreaper-v1"}
    if missing not in {"lifeline", "both"}:
        kwargs["controller_lifeline_fd"] = 4
    if missing not in {"deadline", "both"}:
        kwargs["deadline_monotonic_ns"] = 5
    code = "native_bootstrap_deadline_invalid" if missing == "lifeline" else (
        "native_bootstrap_child_supervision_invalid"
    )
    with pytest.raises(NativeBootstrapError, match=code):
        native_bootstrap_command("fixture", control_fd=1, gate_fd=2, frame_fd=3, **kwargs)


def test_command_rejects_explicit_linux_supervision_on_other_platform(monkeypatch):
    import lunar_evolution.native_bootstrap as native

    monkeypatch.setattr(native.platform, "system", lambda: "Darwin")
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_child_supervision_unsupported"):
        native_bootstrap_command(
            "fixture", control_fd=1, gate_fd=2, frame_fd=3, controller_lifeline_fd=4,
            deadline_monotonic_ns=5, child_supervision="linux-subreaper-v1",
        )


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin native flag rejection")
def test_darwin_c_entrypoint_rejects_linux_supervision_before_control(tmp_path):
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    process = subprocess.run(
        [str(artifact.path), "--control-fd", "0", "--gate-fd", "1", "--frame-fd", "2",
         "--controller-lifeline-fd", "3", "--deadline-monotonic-ns", "5",
         "--child-supervision", "linux-subreaper-v1"],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=3, check=False,
        env={"PATH": os.defpath},
    )
    assert process.returncode == 64
    assert process.stdout == process.stderr == b""


@_LINUX_ONLY
@pytest.mark.parametrize("kind,direct_exit", [(1, 0), (1, 17), (2, 0), (3, 17), (4, 0)],
                         ids=["fork", "nonzero-direct", "multiple", "double-fork", "orphan-clone"])
def test_terminal_waits_for_all_waitable_descendants_and_preserves_direct_status(
    tmp_path, kind, direct_exit,
):
    count = 3 if kind == 2 else 1
    with _supervised(tmp_path, kind=kind, direct_exit=direct_exit) as fixture:
        assert fixture.artifact.descriptor.implementation_version == "native-bootstrap-linux-subreaper-v1"
        _started, descendants = _started_with_descendants(fixture, tmp_path, count=count)
        (tmp_path / "release-descendants").touch()
        terminal = _frame(fixture.frame)
        assert (terminal.kind, terminal.sequence) == ("terminal", 3)
        assert fixture.process.wait(timeout=3) == direct_exit
        for index, pid in enumerate(descendants):
            assert (tmp_path / f"descendant-{index}.done").read_text() == "1"
            assert _state(pid) == "", "successful drain must reap every known descendant"
        assert os.read(fixture.frame, 8192) == b""
        assert fixture.process.stdout.read() == b""


@_LINUX_ONLY
@pytest.mark.parametrize("entry", ["unguarded", "lifeline", "deadline"])
def test_new_linux_artifact_legacy_entrypoints_also_drain_before_terminal(tmp_path, entry):
    with _supervised(tmp_path, entry=entry) as fixture:
        _started_with_descendants(fixture, tmp_path)
        (tmp_path / "release-descendants").touch()
        assert _frame(fixture.frame).kind == "terminal"
        assert fixture.process.wait(timeout=3) == 0


@_LINUX_ONLY
def test_owner_eof_after_direct_exit_stops_remaining_descendants_without_terminal(tmp_path):
    with _supervised(tmp_path) as fixture:
        started, descendants = _started_with_descendants(fixture, tmp_path)
        _close(fixture, "owner")
        assert fixture.process.wait(timeout=3) in {-signal.SIGKILL, 78}
        _stopped(started.observed_pid)
        for pid in descendants:
            _stopped(pid)
        assert time.monotonic_ns() < fixture.deadline_ns
        assert os.read(fixture.frame, 8192) == b""
        assert not (tmp_path / "descendant-0.done").exists()


@_LINUX_ONLY
def test_original_absolute_deadline_remains_active_after_direct_exit(tmp_path):
    with _supervised(tmp_path, allowance_seconds=3) as fixture:
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        # Gate time is charged to the same deadline as the later descendant drain.
        remaining = max(0, (fixture.deadline_ns - time.monotonic_ns()) / 1e9 - 1.4)
        assert not select.select([fixture.frame], [], [], remaining)[0]
        os.write(fixture.gate, b"1")
        _close(fixture, "gate")
        started = _frame(fixture.frame)
        assert started.kind == "target_started"
        descendant = int(_wait_file(tmp_path / "descendant-0.pid", timeout=1))
        _stopped(started.observed_pid, timeout=1)
        assert fixture.process.poll() is None
        assert os.fstat(fixture.owner)
        until_deadline = max(0, (fixture.deadline_ns - time.monotonic_ns()) / 1e9)
        assert fixture.process.wait(timeout=until_deadline + 1.5) in {-signal.SIGKILL, 78}
        observed = time.monotonic_ns()
        assert fixture.deadline_ns - 150_000_000 <= observed <= fixture.deadline_ns + 1_500_000_000
        _stopped(descendant)
        assert os.read(fixture.frame, 8192) == b""
        assert not (tmp_path / "descendant-0.done").exists()


@_LINUX_ONLY
def test_closed_terminal_reader_cannot_retire_guardian_as_a_success(tmp_path):
    with _supervised(tmp_path) as fixture:
        _started_with_descendants(fixture, tmp_path)
        _close(fixture, "frame")
        (tmp_path / "release-descendants").touch()
        assert fixture.process.wait(timeout=3) in {-signal.SIGKILL, 78}


_CONTROLLER = r'''
import json
import os
import signal
import subprocess
import sys

context = json.loads(sys.argv[1])
owner_r, owner_w = os.pipe()
command = context["command"] + ["--controller-lifeline-fd", str(owner_r),
    "--deadline-monotonic-ns", str(context["deadline_ns"]),
    "--child-supervision", "linux-subreaper-v1"]
process = subprocess.Popen(command,
    pass_fds=tuple(context["fds"]) + (owner_r,), start_new_session=True,
    close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL, env={"PATH": os.defpath})
os.close(owner_r)
for fd in context["fds"]:
    os.close(fd)
print(json.dumps({"bootstrap_pid": process.pid}), flush=True)
while True:
    signal.pause()
'''


@_LINUX_ONLY
def test_controller_sigkill_after_direct_exit_leaves_guardian_to_stop_descendants(tmp_path):
    target = _target(tmp_path, kind=3)
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    control = encode_native_bootstrap_control(
        _launch(target), target_path=target, target_argv=(str(target),), target_cwd=tmp_path,
    )
    control_r, control_w = os.pipe()
    gate_r, gate_w = os.pipe()
    frame_r, frame_w = os.pipe()
    deadline_ns = time.monotonic_ns() + 12_000_000_000
    context = {
        "command": list(native_bootstrap_command(
            artifact.path, control_fd=control_r, gate_fd=gate_r, frame_fd=frame_w,
        )), "fds": [control_r, gate_r, frame_w], "deadline_ns": deadline_ns,
    }
    controller = subprocess.Popen(
        [sys.executable, "-B", "-c", _CONTROLLER, json.dumps(context)],
        pass_fds=(control_r, gate_r, frame_w), start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={"PATH": os.defpath},
    )
    for fd in (control_r, gate_r, frame_w):
        os.close(fd)
    bootstrap_pid = None
    fixture = SimpleNamespace(gate=gate_w, frame=frame_r)
    try:
        assert select.select([controller.stdout], [], [], 5)[0]
        bootstrap_pid = json.loads(controller.stdout.readline())['bootstrap_pid']
        os.write(control_w, control)
        os.close(control_w)
        control_w = None
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        os.write(fixture.gate, b"1")
        _close(fixture, "gate")
        started = _frame(fixture.frame)
        assert started.kind == "target_started"
        descendant = int(_wait_file(tmp_path / "descendant-0.pid"))
        _stopped(started.observed_pid)
        assert _state(bootstrap_pid) and not _state(bootstrap_pid).startswith("Z")
        assert not select.select([fixture.frame], [], [], 0.15)[0]
        # Kill only the controller. Its sole owner-writer closes in the kernel.
        controller.kill()
        assert controller.wait(timeout=3) == -signal.SIGKILL
        _stopped(bootstrap_pid)
        _stopped(descendant)
        assert time.monotonic_ns() < deadline_ns
        assert os.read(fixture.frame, 8192) == b""
        assert not (tmp_path / "descendant-0.done").exists()
    finally:
        if control_w is not None:
            os.close(control_w)
        _close(fixture, "gate")
        _close(fixture, "frame")
        if controller.poll() is None:
            controller.kill()
            controller.wait(timeout=3)
        if bootstrap_pid is not None:
            state = _state(bootstrap_pid)
            if state and not state.startswith("Z"):
                try:
                    os.killpg(bootstrap_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        controller.stdout.close()
        controller.stderr.close()


@_LINUX_ONLY
@pytest.mark.parametrize("disposition", ["ignored", "no-child-wait"])
def test_linux_bootstrap_restores_waitable_sigchld_disposition(tmp_path, disposition):
    launcher_source, launcher = tmp_path / "launcher.c", tmp_path / "launcher"
    launcher_source.write_text(
        '#include <signal.h>\n#include <unistd.h>\n'
        'int main(int argc,char **argv){if(argc<2)return 1;'
        'struct sigaction action={0};'
        f'action.sa_handler={"SIG_IGN" if disposition == "ignored" else "SIG_DFL"};'
        f'action.sa_flags={"0" if disposition == "ignored" else "SA_NOCLDWAIT"};'
        'if(sigemptyset(&action.sa_mask)||sigaction(SIGCHLD,&action,0))return 2;'
        'execv(argv[1],argv+1);return 3;}\n',
    )
    compile_native_target(launcher_source, launcher)
    with _supervised(tmp_path, launcher=launcher, direct_exit=17) as fixture:
        _started_with_descendants(fixture, tmp_path)
        (tmp_path / "release-descendants").touch()
        assert _frame(fixture.frame).kind == "terminal"
        assert fixture.process.wait(timeout=3) == 17


def _fault_bootstrap(tmp_path: Path, fault: int) -> Path:
    source, target = tmp_path / "fault.c", tmp_path / "fault-bootstrap"
    source.write_text(r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
''' + f'\n#include {json.dumps(str(native_bootstrap_source_path().with_name("native_producer_isolation.h")))}\n' + r'''
/* Compile the real isolation helper before syscall fault macros. Its variadic
   three-argument PR_SET_SECCOMP call is not part of this setup/drain seam. */
static int fixture_prctl(int option, unsigned long a, unsigned long b,
                         unsigned long c, unsigned long d) {
    if ((FIXTURE_FAULT == 1 && option == PR_SET_CHILD_SUBREAPER) ||
        (FIXTURE_FAULT == 2 && option == PR_GET_CHILD_SUBREAPER)) {
        errno = EPERM; return -1;
    }
    if (FIXTURE_FAULT == 3 && option == PR_GET_CHILD_SUBREAPER) {
        *(int *)a = 0; return 0;
    }
    return prctl(option, a, b, c, d);
}
static int fixture_sigaction(int signum, const struct sigaction *action,
                             struct sigaction *previous) {
    if (FIXTURE_FAULT == 4 && signum == SIGCHLD) { errno = EINVAL; return -1; }
    return sigaction(signum, action, previous);
}
static int fixture_clone_child(void *unused) {
    (void)unused;
    int sink = open("/dev/null", O_RDWR);
    if (sink < 0 || dup2(sink, 0) < 0 || dup2(sink, 1) < 0 || dup2(sink, 2) < 0)
        _exit(101);
    if (sink > 2) close(sink);
    int fd = open("non-sigchld.pid", O_CREAT | O_WRONLY, 0600);
    char data[32];
    int count = snprintf(data, sizeof(data), "%ld", (long)getpid());
    if (fd < 0 || write(fd, data, (size_t)count) != count || close(fd)) _exit(102);
    for (int attempt = 0; attempt < 1000; ++attempt) {
        if (access("release-non-sigchld", F_OK) == 0) {
            fd = open("non-sigchld.done", O_CREAT | O_WRONLY, 0600);
            if (fd < 0 || write(fd, "1", 1) != 1 || close(fd)) _exit(103);
            _exit(49);
        }
        usleep(20000);
    }
    _exit(104);
}
static pid_t fixture_waitpid(pid_t pid, int *status, int options) {
    static int interrupted = 0;
    static int injected = 0;
    if (pid == -1 && options == (__WALL | WNOHANG)) {
        if (FIXTURE_FAULT == 5) { errno = EINVAL; return -1; }
        if (FIXTURE_FAULT == 6 && !interrupted++) { errno = EINTR; return -1; }
    }
    pid_t outcome = waitpid(pid, status, options);
    if (FIXTURE_FAULT == 8 && pid > 0 && options == 0 && outcome == pid && !injected++) {
        /* A real non-SIGCHLD kernel child of bootstrap, without reparenting:
           production target descendants cannot reliably retain that signal. */
        char *stack = malloc(65536);
        if (!stack || clone(fixture_clone_child, stack + 65536, 0, NULL) < 0) return -1;
    }
    return outcome;
}
static int fixture_pthread_join(pthread_t thread, void **result) {
    int outcome = pthread_join(thread, result);
    if (FIXTURE_FAULT == 7 && outcome == 0) {
        int fd = open("join-observed", O_CREAT | O_WRONLY, 0600);
        if (fd < 0 || write(fd, "1", 1) != 1 || close(fd)) _exit(97);
        for (int attempt = 0; attempt < 1000; ++attempt) {
            if (access("release-join", F_OK) == 0) return outcome;
            usleep(20000);
        }
        _exit(98);
    }
    return outcome;
}
#define prctl(option,a,b,c,d) fixture_prctl(option,(unsigned long)(a), \
    (unsigned long)(b),(unsigned long)(c),(unsigned long)(d))
#define sigaction(signum,action,previous) fixture_sigaction(signum,action,previous)
#define waitpid fixture_waitpid
#define pthread_join fixture_pthread_join
''' + f'\n#include {json.dumps(str(native_bootstrap_source_path()))}\n')
    try:
        compile_native_target(
            source, target, f"-DFIXTURE_FAULT={fault}", "-pthread", "-Wno-deprecated-declarations",
        )
    except subprocess.CalledProcessError as error:
        pytest.fail(
            "native bootstrap fault fixture failed strict compilation:\n"
            + error.stderr.decode("utf-8", errors="replace"), pytrace=False,
        )
    return target


@_LINUX_ONLY
@pytest.mark.parametrize("fault", [1, 2, 3, 4], ids=["set-fails", "get-fails", "get-disabled", "sigchld-fails"])
def test_subreaper_setup_failures_stop_before_ready_or_control_consumption(tmp_path, fault):
    bootstrap = _fault_bootstrap(tmp_path, fault)
    process = subprocess.run(
        [str(bootstrap), "--control-fd", "0", "--gate-fd", "1", "--frame-fd", "2"],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=3,
        env={"PATH": os.defpath},
    )
    assert process.returncode == 64  # Empty control would otherwise produce 66.
    assert process.stdout == process.stderr == b""


@_LINUX_ONLY
def test_drain_wait_error_is_unknown_and_stops_original_group(tmp_path):
    bootstrap = _fault_bootstrap(tmp_path, 5)
    with _supervised(tmp_path, bootstrap=bootstrap) as fixture:
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        os.write(fixture.gate, b"1")
        _close(fixture, "gate")
        assert _frame(fixture.frame).kind == "target_started"
        assert fixture.process.wait(timeout=3) in {-signal.SIGKILL, 78}
        assert os.read(fixture.frame, 8192) == b""


@_LINUX_ONLY
def test_interrupted_drain_retries_until_waitable_descendants_complete(tmp_path):
    bootstrap = _fault_bootstrap(tmp_path, 6)
    with _supervised(tmp_path, bootstrap=bootstrap) as fixture:
        _started_with_descendants(fixture, tmp_path)
        (tmp_path / "release-descendants").touch()
        assert _frame(fixture.frame).kind == "terminal"
        assert fixture.process.wait(timeout=3) == 0


@_LINUX_ONLY
def test_owner_eof_during_guardian_join_prevents_successful_bootstrap_exit(tmp_path):
    bootstrap = _fault_bootstrap(tmp_path, 7)
    with _supervised(tmp_path, bootstrap=bootstrap) as fixture:
        _started_with_descendants(fixture, tmp_path)
        (tmp_path / "release-descendants").touch()
        assert _frame(fixture.frame).kind == "terminal"
        assert _wait_file(tmp_path / "join-observed") == "1"
        assert fixture.process.poll() is None
        _close(fixture, "owner")
        (tmp_path / "release-join").touch()
        # A seq3 alone cannot certify successful guard retirement: the caller
        # must also observe a successful native exit and the original authority.
        assert fixture.process.wait(timeout=3) in {-signal.SIGKILL, 78}


@_LINUX_ONLY
def test_drain_wall_waits_for_actual_non_sigchld_bootstrap_child(tmp_path):
    bootstrap = _fault_bootstrap(tmp_path, 8)
    with _supervised(tmp_path, bootstrap=bootstrap) as fixture:
        _started, descendants = _started_with_descendants(fixture, tmp_path)
        extra = int(_wait_file(tmp_path / "non-sigchld.pid"))
        assert os.getpgid(extra) == fixture.process.pid
        fields = (Path("/proc") / str(extra) / "stat").read_text().rsplit(")", 1)[1].split()
        assert int(fields[1]) == fixture.process.pid  # Field 4: the actual kernel parent.
        assert int(fields[35]) == 0  # Field 38: no SIGCHLD exit signal.
        (tmp_path / "release-descendants").touch()
        assert _wait_file(tmp_path / "descendant-0.done") == "1"
        _stopped(descendants[0])
        # Ordinary SIGCHLD children have finished. Omitting __WALL would now
        # yield ECHILD, emit seq3 and retire bootstrap while this child runs.
        assert not select.select([fixture.frame], [], [], 0.15)[0]
        assert fixture.process.poll() is None
        assert _state(extra) and not _state(extra).startswith("Z")
        (tmp_path / "release-non-sigchld").touch()
        assert _frame(fixture.frame).kind == "terminal"
        assert fixture.process.wait(timeout=3) == 0
        assert (tmp_path / "non-sigchld.done").read_text() == "1"
        assert _state(extra) == ""
        assert _state(descendants[0]) == ""
