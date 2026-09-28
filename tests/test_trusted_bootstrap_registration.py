from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_producer_bootstrap import _attempt_records

from lunar_evolution.producer_bootstrap import BootstrapHandshakeFrame
from lunar_evolution.producer_process import (
    ProducerExecutableSnapshot,
    _atomic_json,
    _recovery_lock,
)
from lunar_evolution.trusted_bootstrap_binding import BoundExecutable, TrustedExecutablePair
from lunar_evolution.trusted_bootstrap_registration import (
    TrustedBootstrapRegistrationError,
    publish_trusted_bootstrap_registration,
)


def _inputs(workspace: Path):
    launch, descriptor, intent, attestation, claim, _registration, _evidence = _attempt_records(workspace)
    batch = workspace / "evolution" / "producer-batches" / launch.journal_id
    batch.mkdir(parents=True)
    nonce_key = hashlib.sha256(attestation.nonce.encode()).hexdigest()
    _atomic_json(batch / "attestation-consumption.json", claim, exclusive=True)
    _atomic_json(workspace / "evolution" / "producer-nonces" / f"{nonce_key}.json", claim, exclusive=True)
    binding = "darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-sealed-memfd"
    pair = TrustedExecutablePair(
        bootstrap=BoundExecutable("bootstrap", ProducerExecutableSnapshot(
            ".producer-snapshots/bootstrap" if sys.platform == "darwin" else None,
            descriptor.bootstrap_sha256, descriptor.size, binding,
        )),
        target=BoundExecutable("target", ProducerExecutableSnapshot(
            ".producer-snapshots/target" if sys.platform == "darwin" else None,
            intent.executable_sha256, intent.executable_size, binding,
        )),
    )
    ready = BootstrapHandshakeFrame(
        sequence=1, kind="bootstrap_ready", launch_sha256=launch.launch_sha256,
        intent_sha256=launch.intent_sha256,
    )
    return batch, launch, descriptor, intent, attestation, pair, ready


@pytest.fixture
def blocked_process():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="requires process owner identity")
def test_publishes_formal_registration_and_handoff_before_gate_release(tmp_path: Path, blocked_process):
    batch, launch, descriptor, intent, attestation, pair, ready = _inputs(tmp_path)
    with _recovery_lock(batch) as lock_identity:
        result = publish_trusted_bootstrap_registration(
            tmp_path, launch=launch, descriptor=descriptor, intent=intent,
            attestation=attestation, pair=pair, process=blocked_process,
            ready_frame=ready, recovery_lock_identity=lock_identity,
            deadline=time.monotonic() + 5,
        )
    assert result.registration["pid"] == blocked_process.pid
    assert result.registration["pgid"] == blocked_process.pid
    assert result.handoff["registration_sha256"] == result.registration["registration_sha256"]
    assert (batch / "process-registration.json").is_file()
    assert (batch / "trusted-bootstrap-handoff.json").is_file()
    assert blocked_process.poll() is None


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="requires process owner identity")
def test_rejects_deadline_and_ready_drift_without_registration(tmp_path: Path, blocked_process):
    batch, launch, descriptor, intent, attestation, pair, ready = _inputs(tmp_path)
    with _recovery_lock(batch) as lock_identity:
        for frame, deadline, expected in (
            (ready, time.monotonic() - 1, "trusted_registration_wall_timeout"),
            (BootstrapHandshakeFrame(
                sequence=1, kind="bootstrap_ready", launch_sha256="f" * 64,
                intent_sha256=launch.intent_sha256,
            ), time.monotonic() + 5, "trusted_registration_ready_mismatch"),
        ):
            with pytest.raises(TrustedBootstrapRegistrationError) as failure:
                publish_trusted_bootstrap_registration(
                    tmp_path, launch=launch, descriptor=descriptor, intent=intent,
                    attestation=attestation, pair=pair, process=blocked_process,
                    ready_frame=frame, recovery_lock_identity=lock_identity,
                    deadline=deadline,
                )
            assert failure.value.code == expected
    assert not (batch / "process-registration.json").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="requires process owner identity")
def test_rejects_target_binding_drift_and_duplicate_registration(tmp_path: Path, blocked_process):
    batch, launch, descriptor, intent, attestation, pair, ready = _inputs(tmp_path)
    wrong_pair = TrustedExecutablePair(
        pair.bootstrap,
        BoundExecutable("target", ProducerExecutableSnapshot(
            pair.target.snapshot.relative_path, "f" * 64,
            pair.target.snapshot.size, pair.target.snapshot.binding,
        )),
    )
    with _recovery_lock(batch) as lock_identity:
        with pytest.raises(ValueError):
            publish_trusted_bootstrap_registration(
                tmp_path, launch=launch, descriptor=descriptor, intent=intent,
                attestation=attestation, pair=wrong_pair, process=blocked_process,
                ready_frame=ready, recovery_lock_identity=lock_identity,
                deadline=time.monotonic() + 5,
            )
        assert not (batch / "process-registration.json").exists()
        publish_trusted_bootstrap_registration(
            tmp_path, launch=launch, descriptor=descriptor, intent=intent,
            attestation=attestation, pair=pair, process=blocked_process,
            ready_frame=ready, recovery_lock_identity=lock_identity,
            deadline=time.monotonic() + 5,
        )
        with pytest.raises(TrustedBootstrapRegistrationError) as failure:
            publish_trusted_bootstrap_registration(
                tmp_path, launch=launch, descriptor=descriptor, intent=intent,
                attestation=attestation, pair=pair, process=blocked_process,
                ready_frame=ready, recovery_lock_identity=lock_identity,
                deadline=time.monotonic() + 5,
            )
        assert failure.value.code == "trusted_registration_publication_unknown"
