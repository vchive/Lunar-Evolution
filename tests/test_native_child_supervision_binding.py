from __future__ import annotations

import sys
from dataclasses import replace

import pytest
from test_native_trusted_attempt import _attempt

from lunar_evolution.native_bootstrap import (
    LINUX_CHILD_SUPERVISION,
    LINUX_FD_CONTROL_IMPLEMENTATION,
    LINUX_FD_HANDOFF_IMPLEMENTATION,
    LINUX_GRANT_OBJECT_IMPLEMENTATION,
    LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION,
    LINUX_INPUT_MUTATION_IMPLEMENTATION,
    LINUX_IPC_CONTROL_IMPLEMENTATION,
    LINUX_SUBREAPER_IMPLEMENTATION,
    NativeBootstrapError,
    build_native_bootstrap_artifact,
    load_native_bootstrap_artifact,
    native_bootstrap_command,
)
from lunar_evolution.native_trusted_attempt import (
    NativeTrustedAttemptError,
    run_native_trusted_attempt,
)


def test_build_versions_actual_linux_independent_guardian_without_relabelling_darwin(tmp_path):
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    expected = LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION if sys.platform == "linux" else "native-bootstrap-v1"
    assert artifact.descriptor.implementation_version == expected


@pytest.mark.parametrize("version", [LINUX_SUBREAPER_IMPLEMENTATION, LINUX_INPUT_MUTATION_IMPLEMENTATION, LINUX_FD_HANDOFF_IMPLEMENTATION, LINUX_FD_CONTROL_IMPLEMENTATION, LINUX_GRANT_OBJECT_IMPLEMENTATION, LINUX_IPC_CONTROL_IMPLEMENTATION, LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION])
def test_build_cannot_label_darwin_as_linux_capability(tmp_path, monkeypatch, version):
    monkeypatch.setattr("lunar_evolution.native_bootstrap._platform_mode", lambda: "darwin-immutable-snapshot")
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_child_supervision_unsupported"):
        build_native_bootstrap_artifact(tmp_path / "install", implementation_version=version)
    assert not (tmp_path / "install").exists()


@pytest.mark.parametrize("mode", ["legacy", "guarded", "formal"])
@pytest.mark.parametrize("version", [LINUX_SUBREAPER_IMPLEMENTATION, LINUX_INPUT_MUTATION_IMPLEMENTATION, LINUX_FD_HANDOFF_IMPLEMENTATION, LINUX_FD_CONTROL_IMPLEMENTATION, LINUX_GRANT_OBJECT_IMPLEMENTATION, LINUX_IPC_CONTROL_IMPLEMENTATION, LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION])
def test_linux_artifact_command_negotiates_only_with_complete_guard(tmp_path, monkeypatch, mode, version):
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    artifact = replace(artifact, descriptor=replace(
        artifact.descriptor, implementation_version=version,
        platform_execution_mode="linux-fd-bound", descriptor_sha256=None,
    ))
    monkeypatch.setattr("lunar_evolution.native_bootstrap.platform.system", lambda: "Linux")
    kwargs = {} if mode == "legacy" else {"controller_lifeline_fd": 4}
    if mode == "formal":
        kwargs["deadline_monotonic_ns"] = 123456789
    command = native_bootstrap_command(artifact, control_fd=1, gate_fd=2, frame_fd=3, **kwargs)
    if mode == "formal":
        assert command[-2:] == ("--child-supervision", LINUX_CHILD_SUPERVISION)
        assert command[-4:-2] == ("--deadline-monotonic-ns", "123456789")
    else:
        assert "--child-supervision" not in command


@pytest.mark.parametrize("invalid", ["", "linux-subreaper-v2", True, 1])
def test_command_refuses_unrecognized_supervision(invalid, monkeypatch):
    monkeypatch.setattr("lunar_evolution.native_bootstrap.platform.system", lambda: "Linux")
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_child_supervision_invalid"):
        native_bootstrap_command(
            "fixture", control_fd=1, gate_fd=2, frame_fd=3,
            controller_lifeline_fd=4, deadline_monotonic_ns=123,
            child_supervision=invalid,
        )


@pytest.mark.parametrize("guard", [{}, {"controller_lifeline_fd": 4}])
def test_command_refuses_supervision_without_original_guard(guard, monkeypatch):
    monkeypatch.setattr("lunar_evolution.native_bootstrap.platform.system", lambda: "Linux")
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_child_supervision_invalid"):
        native_bootstrap_command(
            "fixture", control_fd=1, gate_fd=2, frame_fd=3,
            child_supervision=LINUX_CHILD_SUPERVISION, **guard,
        )


def test_darwin_command_refuses_linux_capability(monkeypatch):
    monkeypatch.setattr("lunar_evolution.native_bootstrap.platform.system", lambda: "Darwin")
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_child_supervision_unsupported"):
        native_bootstrap_command(
            "fixture", control_fd=1, gate_fd=2, frame_fd=3,
            controller_lifeline_fd=4, deadline_monotonic_ns=123,
            child_supervision=LINUX_CHILD_SUPERVISION,
        )


@pytest.mark.parametrize("version", [
    "native-bootstrap-v1", "fixture", "native-bootstrap-linux-subreaper-v2", LINUX_SUBREAPER_IMPLEMENTATION,
])
def test_formal_linux_refuses_old_or_unrecognized_descriptor_before_effects(tmp_path, monkeypatch, version):
    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path)
    artifact = replace(artifact, descriptor=replace(
        artifact.descriptor, implementation_version=version,
        platform_execution_mode="linux-fd-bound", descriptor_sha256=None,
    ))

    def forbidden(*args, **kwargs):
        pytest.fail("an unsupported descriptor must be rejected before any preflight or effects")

    monkeypatch.setattr("lunar_evolution.native_trusted_attempt._compose_attempt_budget", forbidden)
    monkeypatch.setattr("lunar_evolution.native_trusted_attempt.consume_trusted_bootstrap_attestation", forbidden)
    monkeypatch.setattr("lunar_evolution.native_trusted_attempt.subprocess.Popen", forbidden)
    with pytest.raises(NativeTrustedAttemptError, match="native_trusted_attempt_input_mutation_required"):
        run_native_trusted_attempt(
            workspace, producer_root=producer, intent=intent, attestation=attestation,
            artifact=artifact,
        )
    assert not batch.exists()


@pytest.mark.parametrize("version", [LINUX_SUBREAPER_IMPLEMENTATION, LINUX_INPUT_MUTATION_IMPLEMENTATION, LINUX_FD_HANDOFF_IMPLEMENTATION, LINUX_FD_CONTROL_IMPLEMENTATION, LINUX_GRANT_OBJECT_IMPLEMENTATION, LINUX_IPC_CONTROL_IMPLEMENTATION])
def test_historical_descriptor_load_preserves_original_scope(tmp_path, monkeypatch, version):
    # Loading retained artifacts remains read-only. It does not confer new formal
    # launch rights or upgrade historical evidence to the mutation capability.
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    descriptor = replace(
        artifact.descriptor, implementation_version=version,
        platform_execution_mode="linux-fd-bound", descriptor_sha256=None,
    )
    # Exercise the read-only Linux descriptor branch even on a Darwin test host;
    # this unit does not execute or relabel the binary as Linux enforcement.
    monkeypatch.setattr("lunar_evolution.native_bootstrap._platform_mode", lambda: "linux-fd-bound")
    observed = load_native_bootstrap_artifact(
        artifact.path, descriptor=descriptor, allowlist_id=artifact.allowlist_id,
    )
    assert observed.descriptor == descriptor
    assert observed.descriptor.implementation_version == version
    assert observed.descriptor.implementation_version != LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION


def test_formal_linux_refuses_input_mutation_only_descriptor_before_effects(tmp_path, monkeypatch):
    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path)
    artifact = replace(artifact, descriptor=replace(
        artifact.descriptor, implementation_version=LINUX_INPUT_MUTATION_IMPLEMENTATION,
        platform_execution_mode="linux-fd-bound", descriptor_sha256=None,
    ))

    def forbidden(*args, **kwargs):
        pytest.fail("descriptor rejection must precede budget, input staging, nonce and spawn")

    for name in ("_compose_attempt_budget", "_native_launch_inputs", "consume_trusted_bootstrap_attestation", "subprocess.Popen"):
        monkeypatch.setattr("lunar_evolution.native_trusted_attempt." + name, forbidden)
    with pytest.raises(NativeTrustedAttemptError, match="native_trusted_attempt_fd_handoff_required"):
        run_native_trusted_attempt(
            workspace, producer_root=producer, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert not batch.exists()


def test_formal_linux_refuses_handoff_only_descriptor_before_effects(tmp_path, monkeypatch):
    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path)
    artifact = replace(artifact, descriptor=replace(
        artifact.descriptor, implementation_version=LINUX_FD_HANDOFF_IMPLEMENTATION,
        platform_execution_mode="linux-fd-bound", descriptor_sha256=None,
    ))

    def forbidden(*args, **kwargs):
        pytest.fail("fd control rejection must precede budget, input staging, nonce and spawn")

    for name in ("_compose_attempt_budget", "_native_launch_inputs", "consume_trusted_bootstrap_attestation", "subprocess.Popen"):
        monkeypatch.setattr("lunar_evolution.native_trusted_attempt." + name, forbidden)
    with pytest.raises(NativeTrustedAttemptError, match="native_trusted_attempt_fd_control_required"):
        run_native_trusted_attempt(
            workspace, producer_root=producer, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert not batch.exists()


@pytest.mark.parametrize("fds", [(3, 3, 5), (3, 5, 3), (5, 3, 3)])
def test_command_refuses_protocol_fd_aliases(fds):
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_fd_invalid"):
        native_bootstrap_command("fixture", control_fd=fds[0], gate_fd=fds[1], frame_fd=fds[2])


def test_formal_linux_refuses_fd_control_only_descriptor_before_effects(tmp_path, monkeypatch):
    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path)
    artifact = replace(artifact, descriptor=replace(
        artifact.descriptor, implementation_version=LINUX_FD_CONTROL_IMPLEMENTATION,
        platform_execution_mode="linux-fd-bound", descriptor_sha256=None,
    ))

    def forbidden(*args, **kwargs):
        pytest.fail("grant rejection must precede budget, input staging, nonce and spawn")

    for name in ("_compose_attempt_budget", "_native_launch_inputs", "_persist_deadline",
                 "consume_trusted_bootstrap_attestation", "subprocess.Popen"):
        monkeypatch.setattr("lunar_evolution.native_trusted_attempt." + name, forbidden)
    with pytest.raises(NativeTrustedAttemptError, match="native_trusted_attempt_grant_objects_required"):
        run_native_trusted_attempt(
            workspace, producer_root=producer, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert not batch.exists()


def test_formal_linux_refuses_grant_objects_only_descriptor_before_effects(tmp_path, monkeypatch):
    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path)
    artifact = replace(artifact, descriptor=replace(
        artifact.descriptor, implementation_version=LINUX_GRANT_OBJECT_IMPLEMENTATION,
        platform_execution_mode="linux-fd-bound", descriptor_sha256=None,
    ))

    def forbidden(*args, **kwargs):
        pytest.fail("IPC rejection must precede budget, input staging, nonce and spawn")

    for name in ("_compose_attempt_budget", "_native_launch_inputs", "_persist_deadline",
                 "consume_trusted_bootstrap_attestation", "subprocess.Popen"):
        monkeypatch.setattr("lunar_evolution.native_trusted_attempt." + name, forbidden)
    with pytest.raises(NativeTrustedAttemptError, match="native_trusted_attempt_ipc_control_required"):
        run_native_trusted_attempt(
            workspace, producer_root=producer, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert not batch.exists()


def test_formal_linux_refuses_ipc_only_descriptor_before_effects(tmp_path, monkeypatch):
    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path)
    artifact = replace(artifact, descriptor=replace(
        artifact.descriptor, implementation_version=LINUX_IPC_CONTROL_IMPLEMENTATION,
        platform_execution_mode="linux-fd-bound", descriptor_sha256=None,
    ))

    def forbidden(*args, **kwargs):
        pytest.fail("guardian rejection must precede cancellation, budget, input, nonce and spawn")

    for name in ("_observe_cancellation", "_compose_attempt_budget", "_native_launch_inputs", "_persist_deadline",
                 "consume_trusted_bootstrap_attestation", "subprocess.Popen"):
        monkeypatch.setattr("lunar_evolution.native_trusted_attempt." + name, forbidden)
    with pytest.raises(NativeTrustedAttemptError, match="native_trusted_attempt_guardian_required"):
        run_native_trusted_attempt(
            workspace, producer_root=producer, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert not batch.exists()
