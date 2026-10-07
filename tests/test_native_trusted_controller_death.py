"""Native lifeline fixtures never use external producers, models, or evaluators."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_native_bootstrap import _launch
from test_native_trusted_attempt import _attempt

from lunar_evolution.native_bootstrap import (
    NativeBootstrapError,
    build_native_bootstrap_artifact,
    encode_native_bootstrap_control,
    native_bootstrap_command,
)
from lunar_evolution.native_trusted_attempt import recover_native_trusted_attempt
from lunar_evolution.producer_bootstrap import parse_bootstrap_handshake_frame

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native lifeline")


def _frame(fd, timeout=5):
    line = bytearray()
    deadline = time.monotonic() + timeout
    while not line.endswith(b"\n"):
        assert select.select([fd], [], [], max(0, deadline - time.monotonic()))[0]
        chunk = os.read(fd, 1)
        assert chunk, "native bootstrap closed before expected frame"
        line.extend(chunk)
        assert len(line) < 8192
    return parse_bootstrap_handshake_frame(bytes(line[:-1]))


def _state(pid):
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True,
        timeout=2, check=False,
    )
    assert result.returncode in {0, 1}
    return result.stdout.strip()


def _stopped(pid, *, timeout=3):
    deadline = time.monotonic() + timeout
    while True:
        state = _state(pid)
        if not state or state.startswith("Z"):
            return
        assert time.monotonic() < deadline, f"fixture process {pid} remains active: {state}"
        time.sleep(0.01)


@contextmanager
def _guarded(tmp_path, source, *, argv_fd=False, missing_cwd=False):
    source_path = tmp_path / "target.c"
    target = tmp_path / "target"
    source_path.write_text(source)
    compile_native_target(source_path, target)
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    control_r, control_w = os.pipe()
    gate_r, gate_w = os.pipe()
    frame_r, frame_w = os.pipe()
    owner_r, owner_w = os.pipe()
    control = encode_native_bootstrap_control(
        _launch(target), target_path=target,
        target_argv=(str(target), str(owner_r)) if argv_fd else (str(target),),
        target_cwd=tmp_path / "missing" if missing_cwd else tmp_path,
    )
    process = subprocess.Popen(
        native_bootstrap_command(
            artifact, control_fd=control_r, gate_fd=gate_r, frame_fd=frame_w,
            controller_lifeline_fd=owner_r,
        ),
        pass_fds=(control_r, gate_r, frame_w, owner_r), close_fds=True,
        start_new_session=True, env={"PATH": os.defpath},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    for fd in (control_r, gate_r, frame_w, owner_r):
        os.close(fd)
    os.write(control_w, control)
    os.close(control_w)
    fixture = SimpleNamespace(process=process, gate=gate_w, frame=frame_r, owner=owner_w)
    try:
        yield fixture
    finally:
        for fd in (fixture.gate, fixture.frame, fixture.owner):
            if fd is not None:
                os.close(fd)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
        process.stderr.close()


def _release(fixture):
    os.write(fixture.gate, b"1")
    os.close(fixture.gate)
    fixture.gate = None


@pytest.mark.parametrize("invalid", [True, -1, "4", 1, 2, 3])
def test_guard_command_rejects_invalid_or_aliased_descriptor(invalid):
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_fd_invalid"):
        native_bootstrap_command("fixture", control_fd=1, gate_fd=2, frame_fd=3,
                                 controller_lifeline_fd=invalid)


@pytest.mark.parametrize("invalid", ["regular", "write", "nonblocking", "not-private", "alias"])
def test_c_guard_rejects_invalid_descriptor_or_nonprivate_session(tmp_path, invalid):
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    read_fd, write_fd = os.pipe()
    extra_fd = None
    with ExitStack() as stack:
        stack.callback(os.close, read_fd)
        stack.callback(os.close, write_fd)
        control_r, control_w = os.pipe()
        os.close(control_w)  # Empty control reaches 66 if the guard refusal is lost.
        gate_r, gate_w = os.pipe()
        frame_r, frame_w = os.pipe()
        for fd in (control_r, gate_r, gate_w, frame_r, frame_w):
            stack.callback(os.close, fd)
        selected = read_fd
        if invalid == "regular":
            path = tmp_path / "regular"
            path.write_bytes(b"fixture")
            extra_fd = selected = os.open(path, os.O_RDONLY)
            stack.callback(os.close, extra_fd)
        elif invalid == "write":
            selected = write_fd
        elif invalid == "nonblocking":
            os.set_blocking(read_fd, False)
        command = [str(artifact.path), "--control-fd", str(control_r), "--gate-fd", str(gate_r),
                   "--frame-fd", str(frame_w), "--controller-lifeline-fd",
                   str(control_r if invalid == "alias" else selected)]
        process = subprocess.Popen(
            command, pass_fds=(control_r, gate_r, frame_w, read_fd, write_fd,
                               *((extra_fd,) if extra_fd is not None else ())),
            start_new_session=invalid != "not-private", stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={"PATH": os.defpath},
        )
        stdout, _ = process.communicate(timeout=5)
        assert process.returncode == 64
        assert stdout == b""


def test_guard_eof_before_gate_stops_without_target_start(tmp_path):
    source = '#include <fcntl.h>\n#include <unistd.h>\nint main(void){return open("marker",O_CREAT|O_WRONLY,0600)<0;}\n'
    with _guarded(tmp_path, source) as fixture:
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        # Retain gate writer: EOF on the owner pipe, not on the gate, ends waiting.
        os.close(fixture.owner)
        fixture.owner = None
        # Darwin may observe the fail-closed _exit before delivery of self SIGKILL.
        assert fixture.process.wait(timeout=3) in {-signal.SIGKILL, 78}
        assert os.read(fixture.frame, 8192) == b""
        assert not (tmp_path / "marker").exists()


def test_guard_eof_stops_active_target_and_contained_descendant(tmp_path):
    source = (
        '#include <fcntl.h>\n#include <stdio.h>\n#include <unistd.h>\n'
        'int main(void){pid_t p=fork();if(p<0)return 2;if(p==0){sleep(20);return 0;}'
        'int fd=open("descendant",O_CREAT|O_WRONLY,0600);if(fd<0)return 3;'
        'char s[32];int n=snprintf(s,sizeof(s),"%ld",(long)p);'
        'if(write(fd,s,n)!=n)return 4;if(close(fd))return 5;sleep(20);return 0;}\n'
    )
    with _guarded(tmp_path, source) as fixture:
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        _release(fixture)
        started = _frame(fixture.frame)
        assert started.kind == "target_started"
        deadline = time.monotonic() + 3
        while not (tmp_path / "descendant").exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        descendant = int((tmp_path / "descendant").read_text())
        assert os.getpgid(descendant) == fixture.process.pid == started.observed_pgid
        os.close(fixture.owner)
        fixture.owner = None
        assert fixture.process.wait(timeout=3) in {-signal.SIGKILL, 78}
        _stopped(started.observed_pid)
        _stopped(descendant)
        assert os.read(fixture.frame, 8192) == b""


def test_closed_frame_pipe_cannot_leave_guarded_target_running(tmp_path):
    source = '#include <unistd.h>\nint main(void){sleep(20);return 0;}\n'
    with _guarded(tmp_path, source) as fixture:
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        os.close(fixture.frame)
        fixture.frame = None
        _release(fixture)
        # A default SIGPIPE exit would be -13 and leave the target behind.
        assert fixture.process.wait(timeout=3) in {-signal.SIGKILL, 78}


def test_guarded_target_closes_owner_fd_restores_sigpipe_and_finishes(tmp_path):
    source = (
        '#include <errno.h>\n#include <fcntl.h>\n#include <signal.h>\n#include <stdlib.h>\n'
        'int main(int argc,char **argv){if(argc!=2)return 1;errno=0;'
        'if(fcntl(atoi(argv[1]),F_GETFD)!=-1||errno!=EBADF)return 2;'
        'struct sigaction s;if(sigaction(SIGPIPE,0,&s)||s.sa_handler!=SIG_DFL)return 3;return 0;}\n'
    )
    with _guarded(tmp_path, source, argv_fd=True) as fixture:
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        _release(fixture)
        assert _frame(fixture.frame).kind == "target_started"
        assert _frame(fixture.frame).kind == "terminal"
        assert fixture.process.wait(timeout=3) == 0


def test_guarded_exec_error_stops_group_without_success_frame(tmp_path):
    source = '#include <unistd.h>\nint main(void){sleep(20);return 0;}\n'
    with _guarded(tmp_path, source, missing_cwd=True) as fixture:
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        _release(fixture)
        assert fixture.process.wait(timeout=3) in {-signal.SIGKILL, 78}
        if sys.platform == "linux":
            refused = _frame(fixture.frame)
            assert refused.kind == "target_start_failed"
            assert refused.observed_pid is None
            assert refused.observed_pgid is None
        assert os.read(fixture.frame, 8192) == b""


_CONTROLLER = r'''
import json
import signal
import sys
from pathlib import Path
from lunar_evolution import native_trusted_attempt as runner
from lunar_evolution.native_bootstrap import load_native_bootstrap_artifact
from lunar_evolution.producer_bootstrap import TrustedBootstrapDescriptor, TrustedBootstrapSession
from lunar_evolution.producer_launcher import parse_producer_launch_intent, parse_producer_launch_attestation

context = json.loads(sys.argv[1])
intent = parse_producer_launch_intent(context["intent"])
attestation = parse_producer_launch_attestation(context["attestation"])
descriptor = TrustedBootstrapDescriptor(**context["descriptor"])
artifact = load_native_bootstrap_artifact(context["artifact"], descriptor=descriptor,
                                         allowlist_id=descriptor.allowlist_id)
accept = TrustedBootstrapSession.accept_frame
publish = runner.publish_trusted_bootstrap_registration

def registered(*args, **kwargs):
    published = publish(*args, **kwargs)
    if context["phase"] == "before_gate":
        registration = published.registration
        print(json.dumps({"pid": None, "pgid": registration["pgid"]}), flush=True)
        signal.pause()
    return published

def observed(self, frame):
    result = accept(self, frame)
    if frame.kind == "target_started" and context["phase"] == "target_started":
        print(json.dumps({"pid": self.target_pid, "pgid": self.target_pgid}), flush=True)
    return result

TrustedBootstrapSession.accept_frame = observed
runner.publish_trusted_bootstrap_registration = registered
runner.run_native_trusted_attempt(Path(context["workspace"]),
    producer_root=Path(context["producer_root"]), intent=intent,
    attestation=attestation, artifact=artifact)
'''


def _inventory(root):
    return {
        path.relative_to(root).as_posix(): (
            path.read_bytes(), path.stat().st_dev, path.stat().st_ino,
            path.stat().st_mtime_ns,
        ) for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("phase", ["before_gate", "target_started"])
def test_formal_controller_only_sigkill_stops_work_before_original_deadline(tmp_path, monkeypatch, phase):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=12, target_sleep=20, mark_started_before_sleep=True,
    )
    context = {
        "workspace": str(workspace), "producer_root": str(producer_root),
        "intent": intent.to_dict(), "attestation": attestation.to_dict(),
        "descriptor": artifact.descriptor.to_dict(), "artifact": str(artifact.path),
        "phase": phase,
    }
    controller = subprocess.Popen(
        [sys.executable, "-B", "-c", _CONTROLLER, json.dumps(context)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        env={"PYTHONPATH": str(Path(runner.__file__).resolve().parents[1])},
    )
    target = None
    try:
        assert select.select([controller.stdout], [], [], 8)[0], "formal target did not start"
        line = controller.stdout.readline(4096)
        assert line, controller.stderr.read().decode()
        target = json.loads(line)
        assert controller.pid != target["pgid"]
        deadline = json.loads((batch / "native-trusted-attempt-deadline.json").read_bytes())
        assert deadline["deadline_monotonic"] == deadline["started_monotonic"] + 12
        marker = batch / "work" / "marker"
        if phase == "target_started":
            wait_until = time.monotonic() + 3
            while not marker.exists():
                assert time.monotonic() < wait_until
                time.sleep(0.01)
        else:
            assert not marker.exists()
        # The test sends exactly one signal: to the controller, never bootstrap/target.
        controller.kill()
        assert controller.wait(timeout=3) == -signal.SIGKILL
        _stopped(target["pgid"])
        if target["pid"] is not None:
            _stopped(target["pid"])
        else:
            assert not marker.exists()
        assert time.monotonic() < deadline["deadline_monotonic"]
        assert not (batch / "native-trusted-process-terminal.json").exists()
        assert not (batch / "execution-receipt.json").exists()
        before = _inventory(batch)

        def forbidden(*_args, **_kwargs):
            raise AssertionError("read-only recovery cannot spawn or clean up work")

        with monkeypatch.context() as patch:
            patch.setattr(runner.subprocess, "Popen", forbidden)
            patch.setattr(runner, "_cleanup", forbidden)
            patch.setattr(runner, "_cleanup_recovered_attempt", forbidden)
            patch.setattr(runner, "cleanup_registered_process", forbidden)
            patch.setattr(runner.os, "kill", forbidden)
            patch.setattr(runner.os, "killpg", forbidden)
            observed = recover_native_trusted_attempt(
                workspace, intent=intent, attestation=attestation, artifact=artifact,
            )
        assert observed["status"] == "recovery_required"
        assert observed["reason"] == "native_trusted_attempt_terminal_receipt_missing"
        assert observed["pid"] == observed["pgid"] == target["pgid"]
        assert _inventory(batch) == before
    finally:
        if controller.poll() is None:
            controller.kill()
            controller.wait(timeout=3)
        state = _state(target["pgid"]) if target is not None else ""
        if state and not state.startswith("Z"):
            # Emergency fixture teardown only, after product assertions finish.
            try:
                os.killpg(target["pgid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        controller.stdout.close()
        controller.stderr.close()
