from __future__ import annotations

import hashlib
import os
import select
import subprocess
from pathlib import Path

import pytest

from lunar_evolution.native_bootstrap import (
    NativeBootstrapError,
    build_native_bootstrap_artifact,
    encode_native_bootstrap_control,
    load_native_bootstrap_artifact,
    native_bootstrap_command,
)
from lunar_evolution.producer_bootstrap import (
    TrustedBootstrapLaunch,
    parse_bootstrap_handshake_frame,
)
from lunar_evolution.producer_isolation import build_producer_isolation_policy


def _launch(target: Path) -> TrustedBootstrapLaunch:
    return TrustedBootstrapLaunch(
        launch_id="launch-001", journal_id="journal-001", run_id="run-001",
        parent_task_id="parent-001", task_id="task-001", intent_sha256="a" * 64,
        attestation_sha256="b" * 64, bootstrap_descriptor_sha256="c" * 64,
        target_executable_identity=hashlib.sha256(target.read_bytes()).hexdigest(),
        gate_protocol="fd-read-one-byte-v1", gate_nonce="nonce-001",
    )


def _start(
    tmp_path: Path, *, gate_payload: bytes = b"1", target: Path | None = None,
    target_contents: str | None = None, isolation_policy: object | None = None,
    prepare_target: bool = True,
):
    target = target or (tmp_path / "target")
    marker = tmp_path / "marker"
    if prepare_target:
        target.write_text(
            target_contents or f'#!/bin/sh\nprintf started > "{marker}"\n', encoding="utf-8",
        )
        target.chmod(0o755)
    launch = _launch(target)
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    control = encode_native_bootstrap_control(
        launch, target_path=target, target_argv=(str(target),), target_cwd=tmp_path,
        isolation_policy=isolation_policy,
    )
    control_r, control_w = os.pipe()
    gate_r, gate_w = os.pipe()
    frame_r, frame_w = os.pipe()
    process = subprocess.Popen(
        native_bootstrap_command(artifact, control_fd=control_r, gate_fd=gate_r, frame_fd=frame_w),
        pass_fds=(control_r, gate_r, frame_w), close_fds=True,
        env={"PATH": os.defpath},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    os.close(control_r); os.close(gate_r); os.close(frame_w)
    os.write(control_w, control); os.close(control_w)
    return process, gate_w, frame_r, marker, artifact


def _read_frame(fd: int, timeout: float = 5.0):
    ready, _, _ = select.select([fd], [], [], timeout)
    assert ready, "native bootstrap did not emit a bounded handshake frame"
    line = os.read(fd, 8192)
    assert line.endswith(b"\n")
    return parse_bootstrap_handshake_frame(line[:-1])


@pytest.mark.skipif(__import__("sys").platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_artifact_is_exactly_allowlisted_and_target_waits_for_gate(tmp_path: Path):
    process, gate_w, frame_r, marker, artifact = _start(tmp_path)
    ready = _read_frame(frame_r)
    assert ready.kind == "bootstrap_ready"
    assert not marker.exists()
    os.write(gate_w, b"1")
    os.close(gate_w)
    started = _read_frame(frame_r)
    terminal = _read_frame(frame_r)
    assert started.kind == "target_started"
    assert terminal.kind == "terminal"
    assert process.wait(timeout=5) == 0
    assert marker.read_text(encoding="utf-8") == "started"
    loaded = load_native_bootstrap_artifact(
        artifact.path, descriptor=artifact.descriptor, allowlist_id=artifact.allowlist_id,
    )
    assert loaded.artifact_sha256 == artifact.artifact_sha256


@pytest.mark.skipif(__import__("sys").platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_artifact_rejects_duplicate_gate_token(tmp_path: Path):
    process, gate_w, frame_r, marker, _ = _start(tmp_path)
    assert _read_frame(frame_r).kind == "bootstrap_ready"
    os.write(gate_w, b"11")
    os.close(gate_w)
    assert process.wait(timeout=5) != 0
    assert not marker.exists()
    assert os.read(frame_r, 8192) == b""


@pytest.mark.skipif(__import__("sys").platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_artifact_load_rejects_replacement(tmp_path: Path):
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    artifact.path.write_bytes(artifact.path.read_bytes() + b"\x00")
    with pytest.raises(NativeBootstrapError) as exc:
        load_native_bootstrap_artifact(
            artifact.path, descriptor=artifact.descriptor, allowlist_id=artifact.allowlist_id,
        )
    assert exc.value.code == "native_bootstrap_artifact_changed"


def test_control_rejects_argv_path_that_was_not_hashed(tmp_path: Path):
    target = tmp_path / "target"
    other = tmp_path / "other"
    for item in (target, other):
        item.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        item.chmod(0o755)
    launch = _launch(target)
    with pytest.raises(NativeBootstrapError) as exc:
        encode_native_bootstrap_control(
            launch, target_path=target, target_argv=(str(other),), target_cwd=tmp_path,
        )
    assert exc.value.code == "native_bootstrap_target_binding_mismatch"


def test_control_binds_controller_isolation_policy(tmp_path: Path):
    target = tmp_path / "target"
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    policy = build_producer_isolation_policy(read_paths=[target], write_dirs=[work])
    control = encode_native_bootstrap_control(
        _launch(target), target_path=target, target_argv=(str(target),), target_cwd=tmp_path,
        isolation_policy=policy,
    )
    assert policy.profile.encode() in control
    assert str(work).encode() in control
    assert str(target).encode() in control
