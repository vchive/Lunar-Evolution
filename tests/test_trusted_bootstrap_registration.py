from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_producer_bootstrap import _attempt_records, _rehash_record
from test_trusted_bootstrap_claim import _deadline_fixture, _drift_deadline

from lunar_evolution import trusted_bootstrap_registration as registration_module
from lunar_evolution.native_deadline_binding import NATIVE_CONSUMPTION_PROTOCOL
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


def _native_inputs(workspace: Path):
    inputs = _inputs(workspace)
    batch, _, _, _, attestation, _, _ = inputs
    _, binding = _deadline_fixture(batch)
    claim = json.loads((batch / "attestation-consumption.json").read_bytes())
    claim.update({
        "schema_version": "2", "protocol": NATIVE_CONSUMPTION_PROTOCOL,
        "deadline_binding": binding,
    })
    _rehash_record(claim, "consumption_sha256")
    nonce_key = hashlib.sha256(attestation.nonce.encode()).hexdigest()
    _atomic_json(batch / "attestation-consumption.json", claim)
    _atomic_json(workspace / "evolution" / "producer-nonces" / f"{nonce_key}.json", claim)
    return inputs, binding


def _publish_native(workspace: Path, inputs: tuple, lock_identity: tuple, process, binding):
    _, launch, descriptor, intent, attestation, pair, ready = inputs
    return publish_trusted_bootstrap_registration(
        workspace, launch=launch, descriptor=descriptor, intent=intent,
        attestation=attestation, pair=pair, process=process, ready_frame=ready,
        recovery_lock_identity=lock_identity, deadline=time.monotonic() + 5,
        expected_deadline_binding=binding,
    )


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
@pytest.mark.parametrize("supply_expected", [False, True])
def test_native_registration_binds_both_claims_to_the_frozen_deadline(
    tmp_path: Path, blocked_process, supply_expected: bool,
):
    inputs, binding = _native_inputs(tmp_path)
    batch = inputs[0]
    with _recovery_lock(batch) as lock_identity:
        result = _publish_native(
            tmp_path, inputs, lock_identity, blocked_process,
            binding if supply_expected else None,
        )
    claim = json.loads((batch / "attestation-consumption.json").read_bytes())
    assert result.registration["consumption_sha256"] == claim["consumption_sha256"]
    assert result.handoff["consumption_sha256"] == claim["consumption_sha256"]
    assert blocked_process.poll() is None


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="requires process owner identity")
@pytest.mark.parametrize("kind", ["bytes", "replacement", "missing", "mode", "expected_pin", "legacy"])
def test_native_registration_refuses_prepublication_deadline_drift(
    tmp_path: Path, blocked_process, kind: str,
):
    if kind == "legacy":
        inputs = _inputs(tmp_path)
        _, binding = _deadline_fixture(inputs[0])
    else:
        inputs, binding = _native_inputs(tmp_path)
        if kind == "expected_pin":
            binding = {**binding, "inode": binding["inode"] + 1}
        else:
            _drift_deadline(inputs[0], kind)
    batch = inputs[0]
    with _recovery_lock(batch) as lock_identity, pytest.raises(TrustedBootstrapRegistrationError) as failure:
        _publish_native(tmp_path, inputs, lock_identity, blocked_process, binding)
    assert failure.value.code.startswith("trusted_registration_deadline_binding_")
    assert not (batch / "process-registration.json").exists()
    assert not (batch / "trusted-bootstrap-handoff.json").exists()
    assert blocked_process.poll() is None


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="requires process owner identity")
@pytest.mark.parametrize("stage", ["registration", "handoff"])
@pytest.mark.parametrize("kind", ["bytes", "replacement", "missing", "mode"])
def test_native_registration_retains_partial_records_after_deadline_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocked_process, stage: str, kind: str,
):
    inputs, binding = _native_inputs(tmp_path)
    batch = inputs[0]
    original = registration_module._atomic_json
    selected_name = "process-registration.json" if stage == "registration" else "trusted-bootstrap-handoff.json"

    def drift_after_write(path: Path, value: dict[str, object], *, exclusive: bool = False):
        original(path, value, exclusive=exclusive)
        if path.name == selected_name:
            _drift_deadline(batch, kind)

    monkeypatch.setattr(registration_module, "_atomic_json", drift_after_write)
    with _recovery_lock(batch) as lock_identity, pytest.raises(TrustedBootstrapRegistrationError) as failure:
        _publish_native(tmp_path, inputs, lock_identity, blocked_process, binding)
    assert failure.value.code.startswith("trusted_registration_deadline_binding_")
    assert (batch / "process-registration.json").exists()
    assert (batch / "trusted-bootstrap-handoff.json").exists() is (stage == "handoff")
    assert blocked_process.poll() is None


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="requires process owner identity")
@pytest.mark.parametrize("verification", [2, 4])
def test_native_registration_rechecks_pin_immediately_before_each_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocked_process, verification: int,
):
    inputs, binding = _native_inputs(tmp_path)
    batch = inputs[0]
    original = registration_module.verify_native_deadline_binding
    calls = 0

    def drift_before_verify(path: Path, *, binding):
        nonlocal calls
        calls += 1
        if calls == verification:
            _drift_deadline(batch)
        return original(path, binding=binding)

    monkeypatch.setattr(registration_module, "verify_native_deadline_binding", drift_before_verify)
    with _recovery_lock(batch) as lock_identity, pytest.raises(TrustedBootstrapRegistrationError):
        _publish_native(tmp_path, inputs, lock_identity, blocked_process, binding)
    assert (batch / "process-registration.json").exists() is (verification == 4)
    assert not (batch / "trusted-bootstrap-handoff.json").exists()
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
