"""Original-owned inert Linux processes; no providers or persisted PID authority.

Every bootstrap/watcher is a directly owned Popen child. Groups are stopped only
through an original live pidfd with flag4, never by a remembered numeric PGID.
Darwin skips do not establish the Linux pidfd process-group capability.
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
import select
import signal
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_native_bootstrap import _launch
from test_native_fd_handoff import _sealed
from test_native_grant_objects import _TARGET, _graph, _wire
from test_native_trusted_controller_death import _frame, _state

from lunar_evolution.native_bootstrap import (
    build_native_bootstrap_artifact,
    native_bootstrap_source_path,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux original pidfd guardian")

_TREE = r'''
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <unistd.h>
static void marker(const char *root, const char *name, long value) {
    char path[4096], content[64];
    if (snprintf(path, sizeof(path), "%s/%s", root, name) >= (int)sizeof(path)) _exit(90);
    int fd = open(path, O_CREAT | O_WRONLY | O_TRUNC, 0600);
    int size = snprintf(content, sizeof(content), "%ld", value);
    if (fd < 0 || write(fd, content, (size_t)size) != size || close(fd)) _exit(91);
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    if (atoi(argv[2])) {
        pid_t child = fork(); if (child < 0) return 3;
        if (!child) {
            marker(argv[1], "descendant.pid", (long)getpid());
            usleep(1800000); marker(argv[1], "late-descendant", 1); _exit(0);
        }
    }
    marker(argv[1], "bootstrap.pid", (long)getpid());
    usleep(1800000); marker(argv[1], "late-bootstrap", 1);
    usleep(2000000); return 0;
}
'''


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    root = tmp_path_factory.mktemp("independent-guardian-native")
    tree_source, tree = root / "tree.c", root / "tree"
    tree_source.write_text(_TREE)
    compile_native_target(tree_source, tree)
    target_source, target = root / "target.c", root / "target"
    target_source.write_text(_TARGET)
    compile_native_target(target_source, target)
    return SimpleNamespace(tree=tree, target=target, artifact=build_native_bootstrap_artifact(root / "install"))


def _read(fd, timeout=3):
    end = time.monotonic() + timeout
    while True:
        remaining = end - time.monotonic()
        assert remaining > 0, "original bounded fixture read expired"
        if select.select([fd], [], [], remaining)[0]:
            return os.read(fd, 2)


def _wait_file(path, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.exists():
            return path.read_text()
        time.sleep(0.01)
    pytest.fail(f"inert fixture missing {path.name}")


def _inactive(pid, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        state = _state(pid)
        if not state or state.startswith(("Z", "X")):
            return
        time.sleep(0.01)
    pytest.fail("original fixture descendant remained active")


def _group_signal(fd, value):
    try:
        signal.pidfd_send_signal(fd, value, None, 4)
    except ProcessLookupError:
        return errno.ESRCH
    return 0


def _watch_command(path, group, owner, finish, ack, deadline):
    return [str(path), "--group-pidfd", str(group), "--controller-lifeline-fd", str(owner),
            "--guardian-finish-fd", str(finish), "--guardian-ack-fd", str(ack),
            "--deadline-monotonic-ns", str(deadline)]


@contextmanager
def _watch(compiled, tmp_path, *, tree=True, budget=1.0, before=None, command=None,
           path=None, fill_ack=False, extra=()):
    """A fresh inert original group and exact original watcher owner, no grant wire."""
    with ExitStack() as stack:
        owned = set()

        def fd(value):
            owned.add(value)
            return value

        def close(value):
            if value in owned:
                os.close(value)
                owned.remove(value)

        def pipe():
            return tuple(fd(value) for value in os.pipe())

        stack.callback(lambda: [close(value) for value in tuple(owned)])
        boot = subprocess.Popen([str(compiled.tree), str(tmp_path), str(int(tree))],
                                start_new_session=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        group = fd(os.pidfd_open(boot.pid))
        owner_r, owner_w = pipe()
        finish_r, finish_w = pipe()
        ack_r, ack_w = pipe()
        if tree:
            _wait_file(tmp_path / "descendant.pid")
        _wait_file(tmp_path / "bootstrap.pid")
        # A real signal0/flag4 runtime probe is deliberately required. A6.8
        # runner without this feature fails, rather than borrowing header names.
        _group_signal(group, 0)
        if fill_ack:
            fcntl.fcntl(ack_w, fcntl.F_SETFL, os.O_NONBLOCK)
            while True:
                try:
                    os.write(ack_w, b"x" * 4096)
                except BlockingIOError:
                    break
        values = SimpleNamespace(group=group, owner_r=owner_r, owner_w=owner_w,
                                 finish_r=finish_r, finish_w=finish_w, ack_r=ack_r, ack_w=ack_w,
                                 close=close, boot=boot, deadline=time.monotonic_ns() + int(budget * 1e9))
        if before:
            before(values)
        argv = _watch_command(path or compiled.artifact.path, group, owner_r, finish_r, ack_w, values.deadline)
        if command:
            argv = command(argv, values)
        watcher = None
        try:
            with _sealed(path or compiled.artifact.path) as sealed:
                watcher = subprocess.Popen(argv, executable=f"/proc/self/fd/{sealed}",
                                           pass_fds=tuple(owned | {sealed, *extra}), close_fds=True,
                                           start_new_session=True, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           env={"PATH": os.defpath, "LANG": "C"})
            values.watcher = watcher
            close(owner_r)
            close(finish_r)
            close(ack_w)
            yield values
        finally:
            # Watcher gets original EOF before being retired. The group remains
            # owned by the original pidfd if a deliberately malformed startup
            # refused before watcher activation.
            close(owner_w)
            try:
                _group_signal(group, signal.SIGKILL)
            finally:
                boot.wait(timeout=3)
            if watcher:
                try:
                    watcher.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    watcher.kill()
                    watcher.wait(timeout=3)
                watcher.stdout.close()
                watcher.stderr.close()


def test_watcher_ready_finish_exact_exit_and_unrelated_fd_closure(compiled, tmp_path):
    extra_r, extra_w = os.pipe()
    try:
        with _watch(compiled, tmp_path, tree=False, extra=(extra_w,)) as fixture:
            os.close(extra_w)
            extra_w = None
            assert _read(fixture.ack_r) == b"R"
            assert select.select([extra_r], [], [], 1)[0]
            assert os.read(extra_r, 1) == b""  # watcher discarded extra writer
            assert fixture.watcher.stdout.read() == b""  # it closed inherited stdio
            os.write(fixture.finish_w, b"F")
            fixture.close(fixture.finish_w)
            assert _read(fixture.ack_r) == b"D"
            assert _read(fixture.ack_r) == b""
            assert fixture.watcher.wait(timeout=3) == 0
            assert fixture.boot.poll() is None
    finally:
        if extra_w is not None:
            os.close(extra_w)
        os.close(extra_r)


@pytest.mark.parametrize("fault", ["stop-deadline", "kill", "stop-owner-eof", "stop-owner-data"])
def test_independent_watcher_stops_bootstrap_only_fault_tree(compiled, tmp_path, fault):
    with _watch(compiled, tmp_path, budget=0.8) as fixture:
        assert _read(fixture.ack_r) == b"R"
        child = int(_wait_file(tmp_path / "descendant.pid"))
        if fault == "kill":
            fixture.boot.kill()
        else:
            os.kill(fixture.boot.pid, signal.SIGSTOP)
            if fault == "stop-owner-eof":
                fixture.close(fixture.owner_w)
            elif fault == "stop-owner-data":
                os.write(fixture.owner_w, b"bad")
        assert fixture.watcher.wait(timeout=3) == 78
        assert fixture.boot.wait(timeout=3) == -signal.SIGKILL
        _inactive(child)
        assert not (tmp_path / "late-bootstrap").exists()
        assert not (tmp_path / "late-descendant").exists()


def test_original_pidfd_group_stop_after_leader_already_reaped(compiled, tmp_path):
    def dead_leader(fixture):
        fixture.boot.kill()
        assert fixture.boot.wait(timeout=3) == -signal.SIGKILL
        assert _group_signal(fixture.group, 0) == 0  # member still pins original group

    with _watch(compiled, tmp_path, before=dead_leader) as fixture:
        assert fixture.watcher.wait(timeout=3) == 78
        assert _read(fixture.ack_r) == b""
        _inactive(int((tmp_path / "descendant.pid").read_text()))
        assert not (tmp_path / "late-descendant").exists()


def test_empty_original_group_pidfd_does_not_signal_unrelated_group(compiled, tmp_path):
    with _watch(compiled, tmp_path, tree=False) as fixture:
        assert _read(fixture.ack_r) == b"R"
        fixture.boot.kill()
        fixture.boot.wait(timeout=3)
        assert fixture.watcher.wait(timeout=3) == 78
        unrelated = subprocess.Popen([str(compiled.tree), str(tmp_path), "0"], start_new_session=True)
        try:
            assert _group_signal(fixture.group, signal.SIGKILL) == errno.ESRCH
            assert unrelated.poll() is None
        finally:
            unrelated.kill()
            unrelated.wait(timeout=3)


@pytest.mark.parametrize("payload", [b"", b"X", b"FF", b"FX", b"FXX"])
def test_malformed_or_premature_finish_stops_group(compiled, tmp_path, payload):
    with _watch(compiled, tmp_path) as fixture:
        assert _read(fixture.ack_r) == b"R"
        if payload:
            os.write(fixture.finish_w, payload)
        fixture.close(fixture.finish_w)
        assert fixture.watcher.wait(timeout=3) == 78
        assert fixture.boot.wait(timeout=3) == -signal.SIGKILL
        _inactive(int((tmp_path / "descendant.pid").read_text()))


@pytest.mark.parametrize("fault", ["finish-no-eof", "ack-full", "ack-closed"])
def test_watcher_never_blocks_past_original_deadline(compiled, tmp_path, fault):
    with _watch(compiled, tmp_path, budget=0.6, fill_ack=fault == "ack-full") as fixture:
        if fault != "ack-full":
            assert _read(fixture.ack_r) == b"R"
        if fault == "finish-no-eof":
            os.write(fixture.finish_w, b"F")
        elif fault == "ack-closed":
            fixture.close(fixture.ack_r)
            os.write(fixture.finish_w, b"F")
            fixture.close(fixture.finish_w)
        assert fixture.watcher.wait(timeout=3) == 78
        assert fixture.boot.wait(timeout=3) == -signal.SIGKILL


@pytest.mark.parametrize("role", ["owner_r", "finish_r", "ack_w", "group"])
@pytest.mark.parametrize("kind", ["regular", "wrong-direction", "alias", "async"])
def test_private_watcher_roles_refuse_invalid_bindings_before_ready(compiled, tmp_path, role, kind):
    # Role numbers are live fixture-owned endpoints only. Never introduce a real
    # outside pidfd or kernel object to exercise refusal.
    opened = []

    def changed(argv, fixture):
        index = {"group": 2, "owner_r": 4, "finish_r": 6, "ack_w": 8}[role]
        actual = getattr(fixture, role)
        if kind == "regular":
            path = tmp_path / "regular"
            path.write_bytes(b"bounded")
            replacement = os.open(path, os.O_RDWR)
            opened.append(replacement)
        elif kind == "wrong-direction":
            replacement = fixture.ack_w if role in {"owner_r", "finish_r", "group"} else fixture.owner_r
        elif kind == "alias":
            replacement = fixture.finish_r if role != "finish_r" else fixture.owner_r
        else:
            if role == "group":
                replacement = fixture.finish_r
            else:
                replacement = actual
                fcntl.fcntl(actual, fcntl.F_SETFL, fcntl.fcntl(actual, fcntl.F_GETFL) | os.O_ASYNC)
        argv[index] = str(replacement)
        # _watch inherits owned role FDs; extra regular handle is explicitly added.
        return argv

    # A regular replacement must be present in pass_fds before watcher spawn.
    # Use the original existing group fd duplication for regular type: a memfd
    # can be created before fixture setup and is independently owned here.
    regular = os.memfd_create("guardian-invalid", os.MFD_CLOEXEC)
    try:
        def mutate(argv, fixture):
            if kind == "regular":
                argv[{"group": 2, "owner_r": 4, "finish_r": 6, "ack_w": 8}[role]] = str(regular)
                return argv
            return changed(argv, fixture)

        with _watch(compiled, tmp_path, command=mutate, extra=(regular,)) as fixture:
            assert fixture.watcher.wait(timeout=3) == 64
            assert _read(fixture.ack_r) == b""
            assert fixture.boot.poll() is None
    finally:
        os.close(regular)
        for descriptor in opened:
            os.close(descriptor)


@pytest.mark.parametrize("value", ["0", "2", "03", "+3", "-3", "2147483648", "x"])
def test_private_watcher_fd_numbers_are_strict(compiled, tmp_path, value):
    def command(argv, _fixture):
        argv[6] = value
        return argv

    with _watch(compiled, tmp_path, command=command) as fixture:
        assert fixture.watcher.wait(timeout=3) == 64
        assert _read(fixture.ack_r) == b""


def test_runtime_group_flag_refusal_never_falls_back(compiled, tmp_path):
    original = native_bootstrap_source_path().read_text()
    needle = "return (int)syscall(__NR_pidfd_send_signal, fd, sig, NULL, LUNAR_PIDFD_SIGNAL_PROCESS_GROUP);"
    assert original.count(needle) == 1
    source, target = tmp_path / "unsupported.c", tmp_path / "unsupported"
    source.write_text(original.replace(needle, "if (!sig) { errno = EINVAL; return -1; } " + needle))
    compile_native_target(source, target, "-pthread", "-Wno-deprecated-declarations", "-I",
                          str(native_bootstrap_source_path().parent))
    with _watch(compiled, tmp_path, path=target) as fixture:
        assert fixture.watcher.wait(timeout=3) == 64
        assert _read(fixture.ack_r) == b""
        assert fixture.boot.poll() is None


@contextmanager
def _formal(compiled, tmp_path, *, broker=False, mutate=None, ack_payload=None):
    """Private v2 grants with actual sealed original B/G, not a host DTO mock."""
    target, artifact = compiled.target, compiled.artifact
    working, output, inputs = tmp_path / "work", tmp_path / "output", tmp_path / "inputs"
    for path in (working, output, inputs):
        path.mkdir(mode=0o700)
    approved, secret = inputs / "config.json", tmp_path / "secret"
    approved.write_bytes(b"approved")
    approved.chmod(0o400)
    secret.write_bytes(b"private")
    with ExitStack() as stack:
        descriptors = set()

        def close(fd):
            if fd in descriptors:
                os.close(fd)
                descriptors.remove(fd)

        def owned(fd):
            descriptors.add(fd)
            stack.callback(close, fd)
            return fd

        def pipe():
            return tuple(owned(fd) for fd in os.pipe())

        control_r, control_w = pipe()
        gate_r, gate_w = pipe()
        frame_r, frame_w = pipe()
        owner_r, owner_w = pipe()
        finish_r, finish_w = pipe()
        ack_r, ack_w = pipe()
        target_fd = stack.enter_context(_sealed(target))
        bootstrap_fd = stack.enter_context(_sealed(artifact.path))
        sentinel = owned(os.open(secret, os.O_RDONLY | os.O_CLOEXEC))
        nodes, indexes = _graph([approved, working, output])
        paths = sorted((approved, working, output), key=str)
        grants = [{"node": indexes[str(path)], "fd": owned(os.open(path, os.O_PATH | os.O_CLOEXEC)),
                   "role": 1 if path == approved else (12 if path == working else 4)}
                  for path in paths]
        info = working.stat()
        data = SimpleNamespace(launch=_launch(target), target=target, target_fd=target_fd,
                               bootstrap_fd=bootstrap_fd, nodes=nodes, grants=grants,
                               cwd_index=next(i for i, grant in enumerate(grants) if grant["role"] == 12),
                               isolation_kind=1,
                               argv=[str(target), str(approved), str(secret), str(info.st_dev), str(info.st_ino),
                                     str(target_fd), str(output / "output-marker"), "broker" if broker else "plain"],
                               finish=finish_w, ack=ack_r)
        inherited = [control_r, gate_r, frame_w, owner_r, target_fd, bootstrap_fd, sentinel,
                     finish_w, ack_r, *(grant["fd"] for grant in grants)]
        env = {"PATH": os.defpath, "LANG": "C"}
        request = response = None
        if broker:
            request, request_w = pipe()
            response_r, response = pipe()
            inherited.extend((request_w, response_r))
            env.update(LUNAR_PRODUCER_REQUEST_FD=str(request_w), LUNAR_PRODUCER_RESPONSE_FD=str(response_r))
        if mutate:
            mutate(data)
        deadline = time.monotonic_ns() + 5_000_000_000
        command = [str(artifact.path), "--control-fd", str(control_r), "--gate-fd", str(gate_r),
                   "--frame-fd", str(frame_w), "--controller-lifeline-fd", str(owner_r),
                   "--deadline-monotonic-ns", str(deadline), "--child-supervision", "linux-subreaper-v1",
                   "--grant-object-binding", "linux-held-grants-v1", "--guardian-finish-fd", str(data.finish),
                   "--guardian-ack-fd", str(data.ack)]
        process = subprocess.Popen(command, executable=f"/proc/self/fd/{bootstrap_fd}", pass_fds=tuple(inherited),
                                   close_fds=True, start_new_session=True, env=env, cwd="/",
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        watcher = None
        group = None
        try:
            group = owned(os.pidfd_open(process.pid))
            if ack_payload is None:
                watcher = subprocess.Popen(_watch_command(artifact.path, group, owner_r, finish_r, ack_w, deadline),
                                           executable=f"/proc/self/fd/{bootstrap_fd}",
                                           pass_fds=(group, owner_r, finish_r, ack_w, bootstrap_fd),
                                           close_fds=True, start_new_session=True, env=env,
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                assert _read(ack_r) == b"R"
                close(ack_w)
            else:
                os.write(ack_w, ack_payload)
                close(ack_w)
            for fd in (control_r, gate_r, frame_w, owner_r, finish_w, ack_r):
                close(fd)
            if ack_payload is None:
                close(finish_r)
            try:
                os.write(control_w, _wire(data))
            except BrokenPipeError:
                pass  # intentional endpoint refusals can precede control read
            close(control_w)
            yield SimpleNamespace(process=process, watcher=watcher, frame=frame_r, gate=gate_w,
                                  close=close, working=working, output=output, request=request,
                                  response=response, owner=owner_w, data=data)
        finally:
            close(owner_w)
            if group is not None:
                _group_signal(group, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()  # original exact pre-target Popen only
            process.wait(timeout=3)
            if watcher:
                try:
                    watcher.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    watcher.kill()
                    watcher.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()


@pytest.mark.parametrize("broker", [False, True])
def test_v2_guardian_finish_keeps_normal_io_grants_and_target_fd_closure(compiled, tmp_path, broker):
    with _formal(compiled, tmp_path, broker=broker) as fixture:
        if broker:
            os.write(fixture.response, b"pong")
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        os.write(fixture.gate, b"1")
        fixture.close(fixture.gate)
        assert _frame(fixture.frame).kind == "target_started"
        assert _frame(fixture.frame).kind == "terminal"
        stdout, stderr = fixture.process.communicate(timeout=3)
        assert fixture.process.returncode == 0, stderr
        assert json.loads(stdout) == {"original_cwd": True, "original_read": True, "closed": True}
        assert fixture.watcher.wait(timeout=3) == 0
        assert (fixture.working / "marker").read_bytes() == b"ran"
        assert (fixture.output / "output-marker").read_bytes() == b"out"
        if broker:
            assert os.read(fixture.request, 4) == b"ping"


@pytest.mark.parametrize("payload", [b"", b"X", b"DD", b"R", b"DX"])
def test_v2_terminal_does_not_make_invalid_ack_clean(compiled, tmp_path, payload):
    with _formal(compiled, tmp_path, ack_payload=payload) as fixture:
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        os.write(fixture.gate, b"1")
        fixture.close(fixture.gate)
        assert _frame(fixture.frame).kind == "target_started"
        assert _frame(fixture.frame).kind == "terminal"
        fixture.process.communicate(timeout=3)
        assert fixture.process.returncode == -signal.SIGKILL


@pytest.mark.parametrize("role", ["finish", "ack"])
@pytest.mark.parametrize("kind", ["target", "bootstrap", "grant", "same-pipe"])
def test_v2_new_guardian_roles_are_reserved_before_ready(compiled, tmp_path, role, kind):
    def mutate(data):
        replacement = {"target": data.target_fd, "bootstrap": data.bootstrap_fd,
                       "grant": data.grants[0]["fd"], "same-pipe": data.ack if role == "finish" else data.finish}[kind]
        setattr(data, role, replacement)

    # These fail before control can produce a ready frame. Don't require an
    # independent watcher startup after the intentionally invalid B exits.
    with _formal(compiled, tmp_path, mutate=mutate, ack_payload=b"D") as fixture:
        fixture.process.communicate(timeout=3)
        assert fixture.process.returncode in (64, 73)
        assert os.read(fixture.frame, 1) == b""
        assert not (fixture.working / "marker").exists()
