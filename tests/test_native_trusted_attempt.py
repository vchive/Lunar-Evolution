from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.native_trusted_attempt import (
    NativeTrustedAttemptError,
    run_native_trusted_attempt,
)
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.trusted_bootstrap_registration import TrustedBootstrapRegistrationError


def _attempt(tmp_path: Path, *, timeout: int = 8, target_sleep: int = 0):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    producer_root = tmp_path / "producer"
    producer_root.mkdir()
    target = producer_root / "target"
    source = producer_root / "target.c"
    marker = workspace / "evolution" / "producer-batches" / "journal-001" / "work" / "marker"
    source.write_text(
        '#include <fcntl.h>\n#include <unistd.h>\n'
        'int main(void) { '
        f'sleep({target_sleep}); '
        f'int fd = open("{marker}", O_CREAT | O_WRONLY, 0600); '
        'if (fd < 0) return 2; '
        'if (write(fd, "started", 7) != 7) return 3; '
        'return close(fd) == 0 ? 0 : 4; }\n',
        encoding="utf-8",
    )
    subprocess.run(["/usr/bin/clang", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target)],
                   check=True, capture_output=True)
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    digest = "a" * 64
    intent = build_producer_launch_intent(
        producer_root=producer_root, launch_id="launch-001", journal_id="journal-001",
        run_id="run-001", parent_task_id="parent-001", task_id="task-001",
        contract_sha256=digest, evaluator_kind="local", evaluator_fingerprint=digest,
        runner_fingerprint=digest, generator_fingerprint=digest,
        dependency_sha256=digest, environment_sha256=digest,
        producer_id="fixture", producer_fingerprint=digest,
        executable_relative="target", argv=("target",),
        working_directory="work", output_directory="output",
        request_timeout_seconds=1, max_requests=1, output_max_bytes=1024,
        wall_timeout_seconds=timeout,
    )
    attestation = build_producer_launch_attestation(intent, "nonce-001")
    batch = workspace / "evolution" / "producer-batches" / intent.journal_id
    return workspace, producer_root, intent, attestation, artifact, batch


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_registers_before_release_but_remains_unpublishable(tmp_path: Path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    marker = batch / "work" / "marker"
    publish = runner.publish_trusted_bootstrap_registration

    def checked_publish(*args, **kwargs):
        assert not marker.exists()
        result = publish(*args, **kwargs)
        assert (batch / "process-registration.json").is_file()
        assert (batch / "trusted-bootstrap-handoff.json").is_file()
        assert not marker.exists()
        return result

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", checked_publish)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.status == "recovery_required"
    assert result.reason == "native_trusted_attempt_terminal_receipt_missing"
    assert result.registration_sha256 is not None
    assert result.gate_released and result.target_started
    assert result.exit_code == 0
    assert marker.read_text(encoding="utf-8") == "started"
    assert not (batch / "execution-receipt.json").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_registration_failure_keeps_gate_closed_and_target_unstarted(tmp_path: Path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)

    def fail_publish(*args, **kwargs):
        raise TrustedBootstrapRegistrationError("trusted_registration_publication_unknown")

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", fail_publish)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.status == "recovery_required"
    assert result.reason == "trusted_registration_publication_unknown"
    assert not result.gate_released and not result.target_started
    assert not (batch / "work" / "marker").exists()
    assert (batch / "attestation-consumption.json").exists()
    assert not (batch / "process-registration.json").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_consumed_nonce_cannot_start_second_native_attempt(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    with pytest.raises(NativeTrustedAttemptError) as failure:
        run_native_trusted_attempt(
            workspace, producer_root=producer_root, intent=intent,
            attestation=attestation, artifact=artifact,
        )
    assert failure.value.code == "native_trusted_attempt_claim_failed"
    assert (batch / "work" / "marker").read_text(encoding="utf-8") == "started"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_changed_bootstrap_artifact_is_rejected_before_nonce_consumption(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    artifact.path.write_bytes(artifact.path.read_bytes() + b"\x00")
    with pytest.raises(NativeTrustedAttemptError) as failure:
        run_native_trusted_attempt(
            workspace, producer_root=producer_root, intent=intent,
            attestation=attestation, artifact=artifact,
        )
    assert failure.value.code == "native_trusted_attempt_preflight_invalid"
    assert not (batch / "attestation-consumption.json").exists()
    assert not (batch / "work" / "marker").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_timeout_keeps_unknown_and_cleans_owned_group(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=1, target_sleep=3,
    )
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.status == "recovery_required"
    assert result.reason == "native_trusted_attempt_wall_timeout"
    assert result.gate_released and result.target_started
    assert result.cleanup_status in {"cleaned", "already_exited"}
    assert not (batch / "work" / "marker").exists()
