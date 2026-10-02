"""Local absolute-deadline fixtures for a live but unresponsive native controller.

Contained descendants are covered while their bootstrap remains alive. Post-bootstrap descendant
ownership is a separate lifecycle limitation and is deliberately not claimed by these tests.
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
from test_native_trusted_attempt import _attempt
from test_native_trusted_controller_death import _frame, _inventory, _state, _stopped

from lunar_evolution.native_bootstrap import (
    NativeBootstrapError,
    build_native_bootstrap_artifact,
    encode_native_bootstrap_control,
    native_bootstrap_command,
)
from lunar_evolution.native_trusted_attempt import (
    NativeTrustedAttemptError,
    recover_native_trusted_attempt,
)

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native deadline guardian")


def test_native_clock_maps_frozen_deadline_once_before_caller_clock(monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    calls = []

    def native_clock():
        calls.append("native")
        return 50_000_000_000

    def caller_clock():
        calls.append("caller")
        return 125

    monkeypatch.setattr(runner.time, "monotonic_ns", native_clock)
    assert runner._native_guard_deadline(128, caller_clock, None) == 53_000_000_000
    assert calls == ["native", "caller"]


@pytest.mark.parametrize("remaining", [float("nan"), float("inf"), 1e300, 1e20])
def test_native_clock_refuses_nonfinite_scaled_or_uint64_overflow(monkeypatch, remaining):
    import lunar_evolution.native_trusted_attempt as runner

    monkeypatch.setattr(runner.time, "monotonic_ns", lambda: 50_000_000_000)
    with pytest.raises(NativeTrustedAttemptError, match="native_trusted_attempt_clock_invalid"):
        runner._native_guard_deadline(remaining, lambda: 0, None)


@pytest.mark.parametrize("invalid", [True, 0, -1, 1.0, float("nan"), float("inf"), "1", 2**64])
def test_guard_command_refuses_invalid_absolute_nanoseconds(invalid):
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_deadline_invalid"):
        native_bootstrap_command(
            "fixture", control_fd=1, gate_fd=2, frame_fd=3,
            controller_lifeline_fd=4, deadline_monotonic_ns=invalid,
        )


def test_guard_command_requires_lifeline_for_deadline_and_preserves_integer():
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_deadline_invalid"):
        native_bootstrap_command(
            "fixture", control_fd=1, gate_fd=2, frame_fd=3, deadline_monotonic_ns=1,
        )
    deadline = 2**64 - 1
    command = native_bootstrap_command(
        "fixture", control_fd=1, gate_fd=2, frame_fd=3,
        controller_lifeline_fd=4, deadline_monotonic_ns=deadline,
    )
    assert command == (
        "fixture", "--control-fd", "1", "--gate-fd", "2", "--frame-fd", "3",
        "--controller-lifeline-fd", "4", "--deadline-monotonic-ns", str(deadline),
    )


@pytest.mark.parametrize("invalid", ["malformed", "0", "18446744073709551616", "-1", "1x", "missing-value", "missing-lifeline"])
def test_c_guard_refuses_malformed_zero_overflow_or_unowned_deadline(tmp_path, invalid):
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    control_r, control_w = os.pipe()
    gate_r, gate_w = os.pipe()
    frame_r, frame_w = os.pipe()
    owner_r, owner_w = os.pipe()
    try:
        command = [
            str(artifact.path), "--control-fd", str(control_r), "--gate-fd", str(gate_r),
            "--frame-fd", str(frame_w),
        ]
        if invalid != "missing-lifeline":
            command.extend(["--controller-lifeline-fd", str(owner_r)])
        command.append("--deadline-monotonic-ns")
        if invalid != "missing-value":
            command.append(str(time.monotonic_ns() + 5_000_000_000) if invalid == "missing-lifeline" else invalid)
        process = subprocess.Popen(
            command, pass_fds=(control_r, gate_r, frame_w, owner_r), start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": os.defpath},
        )
        os.close(frame_w)
        frame_w = None
        stdout, _stderr = process.communicate(timeout=5)
        assert process.returncode == 64
        assert stdout == b""
        assert os.read(frame_r, 8192) == b""
    finally:
        for fd in (control_r, control_w, gate_r, gate_w, frame_r, frame_w, owner_r, owner_w):
            if fd is not None:
                os.close(fd)


@contextmanager
def _deadline_guarded(tmp_path, source, *, send_control=True, allowance_seconds=3):
    source_path = tmp_path / "target.c"
    target = tmp_path / "target"
    source_path.write_text(source)
    compile_native_target(source_path, target)
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    control = encode_native_bootstrap_control(
        _launch(target), target_path=target, target_argv=(str(target),), target_cwd=tmp_path,
    )
    control_r, control_w = os.pipe()
    gate_r, gate_w = os.pipe()
    frame_r, frame_w = os.pipe()
    owner_r, owner_w = os.pipe()
    deadline_ns = time.monotonic_ns() + int(allowance_seconds * 1_000_000_000)
    process = subprocess.Popen(
        native_bootstrap_command(
            artifact, control_fd=control_r, gate_fd=gate_r, frame_fd=frame_w,
            controller_lifeline_fd=owner_r, deadline_monotonic_ns=deadline_ns,
        ),
        pass_fds=(control_r, gate_r, frame_w, owner_r), close_fds=True,
        start_new_session=True, env={"PATH": os.defpath}, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    for fd in (control_r, gate_r, frame_w, owner_r):
        os.close(fd)
    fixture = SimpleNamespace(
        process=process, control=control_w, gate=gate_w, frame=frame_r, owner=owner_w,
        deadline_ns=deadline_ns,
    )
    try:
        if send_control:
            os.write(fixture.control, control)
            os.close(fixture.control)
            fixture.control = None
        yield fixture
    finally:
        for fd in (fixture.control, fixture.gate, fixture.frame, fixture.owner):
            if fd is not None:
                os.close(fd)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
        process.stderr.close()


def _assert_deadline_exit(fixture):
    # The owner writer remains open; a pre-gate/control fixture retains its gate writer too.
    assert os.fstat(fixture.owner)
    if fixture.gate is not None:
        assert os.fstat(fixture.gate)
    remaining = max(0, (fixture.deadline_ns - time.monotonic_ns()) / 1_000_000_000)
    assert fixture.process.wait(timeout=remaining + 1.5) in {-signal.SIGKILL, 78}
    observed_ns = time.monotonic_ns()
    assert fixture.deadline_ns - 150_000_000 <= observed_ns <= fixture.deadline_ns + 1_500_000_000


@pytest.mark.parametrize("send_control", [False, True], ids=["control-not-written", "before-gate"])
def test_live_owner_deadline_covers_unwritten_control_and_pre_gate(tmp_path, send_control):
    source = '#include <fcntl.h>\nint main(void){return open("marker",O_CREAT|O_WRONLY,0600)<0;}\n'
    with _deadline_guarded(tmp_path, source, send_control=send_control) as fixture:
        if send_control:
            assert _frame(fixture.frame).kind == "bootstrap_ready"
        else:
            assert os.fstat(fixture.control)
        assert fixture.process.poll() is None
        _assert_deadline_exit(fixture)
        assert os.read(fixture.frame, 8192) == b""
        assert not (tmp_path / "marker").exists()


def test_already_expired_deadline_cannot_announce_ready_or_start_target(tmp_path):
    source = '#include <fcntl.h>\nint main(void){return open("marker",O_CREAT|O_WRONLY,0600)<0;}\n'
    with _deadline_guarded(tmp_path, source, send_control=False, allowance_seconds=-1) as fixture:
        assert fixture.process.wait(timeout=3) in {-signal.SIGKILL, 78}
        assert os.fstat(fixture.owner)
        assert os.read(fixture.frame, 8192) == b""
        assert not (tmp_path / "marker").exists()


def test_live_owner_absolute_deadline_stops_active_target_and_contained_child(tmp_path):
    source = (
        '#include <fcntl.h>\n#include <stdio.h>\n#include <unistd.h>\n'
        'int main(void){pid_t p=fork();if(p<0)return 2;if(p==0){sleep(30);return 0;}'
        'int fd=open("descendant",O_CREAT|O_WRONLY,0600);if(fd<0)return 3;'
        'char s[32];int n=snprintf(s,sizeof(s),"%ld",(long)p);'
        'if(write(fd,s,n)!=n)return 4;if(close(fd))return 5;sleep(30);return 0;}\n'
    )
    with _deadline_guarded(tmp_path, source, allowance_seconds=5) as fixture:
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        # Hold the gate for part of the original allowance. A new duration at gate release would
        # expire over two seconds late and cannot satisfy the original absolute deadline.
        until_release = fixture.deadline_ns - 2_500_000_000
        wait = max(0, (until_release - time.monotonic_ns()) / 1_000_000_000)
        assert not select.select([fixture.frame], [], [], wait)[0]
        assert fixture.process.poll() is None
        os.write(fixture.gate, b"1")
        os.close(fixture.gate)
        fixture.gate = None
        started = _frame(fixture.frame)
        assert started.kind == "target_started"
        marker = tmp_path / "descendant"
        marker_deadline = min(time.monotonic() + 2, fixture.deadline_ns / 1_000_000_000 - 0.25)
        while not marker.exists() or not marker.read_text():
            assert time.monotonic() < marker_deadline
            time.sleep(0.01)
        descendant = int(marker.read_text())
        assert os.getpgid(descendant) == fixture.process.pid == started.observed_pgid
        _assert_deadline_exit(fixture)
        _stopped(started.observed_pid)
        _stopped(descendant)
        assert os.read(fixture.frame, 8192) == b""


_STOPPED_CONTROLLER = r'''
import json
import signal
import sys
import time
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
original_parent_deadline = time.monotonic() + context["parent_allowance"]

def handshake(pid, pgid):
    print(json.dumps({"pid": pid, "pgid": pgid, "parent_deadline": original_parent_deadline}), flush=True)
    # Keep the controller inside the observation boundary even after SIGCONT. It must not
    # create a controller terminal receipt before the test performs final controller teardown.
    while True:
        signal.pause()

def registered(*args, **kwargs):
    published = publish(*args, **kwargs)
    if context["phase"] == "before_gate":
        handshake(None, published.registration["pgid"])
    return published

def observed(self, frame):
    result = accept(self, frame)
    if frame.kind == "target_started" and context["phase"] == "target_started":
        handshake(self.target_pid, self.target_pgid)
    return result

TrustedBootstrapSession.accept_frame = observed
runner.publish_trusted_bootstrap_registration = registered
runner.run_native_trusted_attempt(Path(context["workspace"]),
    producer_root=Path(context["producer_root"]), intent=intent,
    attestation=attestation, artifact=artifact, parent_deadline=original_parent_deadline)
'''


@pytest.mark.parametrize("phase", ["before_gate", "target_started"])
def test_formal_sigstopped_controller_cannot_extend_parent_deadline(tmp_path, monkeypatch, phase):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=12, target_sleep=30, mark_started_before_sleep=True,
    )
    context = {
        "workspace": str(workspace), "producer_root": str(producer_root),
        "intent": intent.to_dict(), "attestation": attestation.to_dict(),
        "descriptor": artifact.descriptor.to_dict(), "artifact": str(artifact.path),
        "phase": phase, "parent_allowance": 8,
    }
    controller = subprocess.Popen(
        [sys.executable, "-B", "-c", _STOPPED_CONTROLLER, json.dumps(context)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        env={"PYTHONPATH": str(Path(runner.__file__).resolve().parents[1])},
    )
    target = None
    try:
        assert select.select([controller.stdout], [], [], 8)[0], "formal launch did not reach pause boundary"
        line = controller.stdout.readline(4096)
        assert line, controller.stderr.read().decode()
        target = json.loads(line)
        assert controller.pid != target["pgid"]
        deadline = json.loads((batch / "native-trusted-attempt-deadline.json").read_bytes())
        assert deadline["deadline_monotonic"] == target["parent_deadline"]
        assert deadline["deadline_monotonic"] < deadline["started_monotonic"] + intent.wall_timeout_seconds
        marker = batch / "work" / "marker"
        if phase == "target_started":
            marker_deadline = time.monotonic() + 1.5
            while not marker.exists():
                assert time.monotonic() < marker_deadline
                time.sleep(0.01)
        else:
            assert not marker.exists()
        os.kill(controller.pid, signal.SIGSTOP)
        state_deadline = time.monotonic() + 1
        while not _state(controller.pid).startswith("T"):
            assert time.monotonic() < state_deadline
            time.sleep(0.01)
        bootstrap_state = _state(target["pgid"])
        assert bootstrap_state and not bootstrap_state.startswith("Z")
        # The stopped controller still owns its lifeline writer. No EOF can explain native exit.
        until_deadline = max(0, deadline["deadline_monotonic"] - time.monotonic() - 1.5)
        assert not select.select([controller.stdout], [], [], until_deadline)[0]
        bootstrap_state = _state(target["pgid"])
        assert bootstrap_state and not bootstrap_state.startswith("Z")
        _stopped(target["pgid"], timeout=max(0, deadline["deadline_monotonic"] - time.monotonic()) + 1.5)
        assert time.monotonic() <= deadline["deadline_monotonic"] + 1.5
        assert controller.poll() is None and _state(controller.pid).startswith("T")
        if target["pid"] is not None:
            _stopped(target["pid"])
        else:
            assert not marker.exists()
        assert not (batch / "native-trusted-process-terminal.json").exists()
        assert not (batch / "execution-receipt.json").exists()
        before = _inventory(batch)

        def forbidden(*_args, **_kwargs):
            raise AssertionError("read-only recovery cannot launch, clean up, or signal native work")

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
        os.kill(controller.pid, signal.SIGCONT)
        controller.kill()
        assert controller.wait(timeout=3) == -signal.SIGKILL
        assert _inventory(batch) == before
        assert not (batch / "native-trusted-process-terminal.json").exists()
    finally:
        if controller.poll() is None:
            controller.kill()
            controller.wait(timeout=3)
        state = _state(target["pgid"]) if target is not None else ""
        if state and not state.startswith("Z"):
            # Emergency fixture teardown only after product assertions finish.
            try:
                os.killpg(target["pgid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        controller.stdout.close()
        controller.stderr.close()
