from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest
from test_producer_bootstrap import _attempt_records

from lunar_evolution import trusted_bootstrap_registration as registration_module
from lunar_evolution.native_deadline_binding import (
    DEADLINE_NAME,
    NATIVE_CONSUMPTION_PROTOCOL,
    persist_native_deadline_binding,
)
from lunar_evolution.producer_process import _recovery_lock
from lunar_evolution.trusted_bootstrap_registration import (
    TrustedBootstrapRegistrationError,
    consume_trusted_bootstrap_attestation,
)


def _inputs(tmp_path: Path):
    launch, descriptor, intent, attestation, claim, _, _ = _attempt_records(tmp_path)
    batch = tmp_path / "evolution" / "producer-batches" / launch.journal_id
    batch.mkdir(parents=True)
    producer_root = tmp_path / "producer-root"
    return batch, producer_root, launch, descriptor, intent, attestation, claim


def _consume(tmp_path: Path, inputs: tuple, lock_identity: tuple[int, int], *, deadline_binding=None):
    _, producer_root, launch, descriptor, intent, attestation, _ = inputs
    return consume_trusted_bootstrap_attestation(
        tmp_path, producer_root=producer_root, launch=launch,
        descriptor=descriptor, intent=intent, attestation=attestation,
        recovery_lock_identity=lock_identity, deadline=time.monotonic() + 5,
        deadline_binding=deadline_binding,
    )


def _deadline_fixture(batch: Path):
    record = {"schema_version": "1", "deadline_monotonic": 10.0}
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    record["deadline_sha256"] = hashlib.sha256(canonical).hexdigest()
    binding = persist_native_deadline_binding(batch, record=record)
    return record, binding


def _drift_deadline(batch: Path, kind: str = "bytes") -> None:
    path = batch / DEADLINE_NAME
    if kind == "missing":
        path.unlink()
    elif kind == "mode":
        path.chmod(0o640)
    elif kind == "replacement":
        replacement = batch / "replacement-deadline.json"
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o600)
        os.replace(replacement, path)
    else:
        record = json.loads(path.read_bytes())
        record["deadline_monotonic"] += 1
        record.pop("deadline_sha256")
        record["deadline_sha256"] = hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode(),
        ).hexdigest()
        path.write_bytes(json.dumps(record, sort_keys=True, separators=(",", ":")).encode())


def test_consumes_exact_claim_into_nonce_ledger_and_batch(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    batch, _, _, _, _, attestation, expected = inputs
    with _recovery_lock(batch) as lock_identity:
        claim = _consume(tmp_path, inputs, lock_identity)
    nonce_key = hashlib.sha256(attestation.nonce.encode("utf-8")).hexdigest()
    ledger = tmp_path / "evolution" / "producer-nonces" / f"{nonce_key}.json"
    assert claim == expected
    assert ledger.read_bytes() == (batch / "attestation-consumption.json").read_bytes()
    assert json.loads(ledger.read_bytes()) == claim


def test_native_claim_pins_original_deadline_in_both_durable_claims(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    batch, _, _, _, _, attestation, legacy = inputs
    _, binding = _deadline_fixture(batch)
    with _recovery_lock(batch) as lock_identity:
        claim = _consume(tmp_path, inputs, lock_identity, deadline_binding=binding)
    assert claim["schema_version"] == "2"
    assert claim["protocol"] == NATIVE_CONSUMPTION_PROTOCOL
    assert claim["deadline_binding"] == binding
    assert claim["consumption_sha256"] != legacy["consumption_sha256"]
    nonce_key = hashlib.sha256(attestation.nonce.encode()).hexdigest()
    ledger = tmp_path / "evolution" / "producer-nonces" / f"{nonce_key}.json"
    assert ledger.read_bytes() == (batch / "attestation-consumption.json").read_bytes()
    binding["inode"] += 1
    assert claim["deadline_binding"] != binding


@pytest.mark.parametrize("kind", ["bytes", "replacement", "missing", "mode"])
def test_native_claim_rejects_deadline_drift_before_consumption(tmp_path: Path, kind: str) -> None:
    inputs = _inputs(tmp_path)
    batch = inputs[0]
    _, binding = _deadline_fixture(batch)
    _drift_deadline(batch, kind)
    with _recovery_lock(batch) as lock_identity, pytest.raises(TrustedBootstrapRegistrationError) as failure:
        _consume(tmp_path, inputs, lock_identity, deadline_binding=binding)
    assert failure.value.code.startswith("trusted_registration_deadline_binding_")
    assert not (batch / "attestation-consumption.json").exists()
    assert not (tmp_path / "evolution" / "producer-nonces").exists()


@pytest.mark.parametrize("stage", ["nonce", "batch"])
@pytest.mark.parametrize("kind", ["bytes", "replacement", "missing", "mode"])
def test_native_claim_keeps_partial_publications_when_deadline_drifts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str, kind: str,
) -> None:
    inputs = _inputs(tmp_path)
    batch = inputs[0]
    _, binding = _deadline_fixture(batch)
    original = registration_module._atomic_json

    def drift_after_write(path: Path, value: dict[str, object], *, exclusive: bool = False):
        original(path, value, exclusive=exclusive)
        if (stage == "nonce" and path.parent.name == "producer-nonces") or (
            stage == "batch" and path.name == "attestation-consumption.json"
        ):
            _drift_deadline(batch, kind)

    monkeypatch.setattr(registration_module, "_atomic_json", drift_after_write)
    with _recovery_lock(batch) as lock_identity, pytest.raises(TrustedBootstrapRegistrationError) as failure:
        _consume(tmp_path, inputs, lock_identity, deadline_binding=binding)
    assert failure.value.code.startswith("trusted_registration_deadline_binding_")
    assert len(list((tmp_path / "evolution" / "producer-nonces").glob("*.json"))) == 1
    assert (batch / "attestation-consumption.json").exists() is (stage == "batch")


@pytest.mark.parametrize("verification", [2, 4])
def test_native_claim_rechecks_pin_immediately_before_each_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verification: int,
) -> None:
    inputs = _inputs(tmp_path)
    batch = inputs[0]
    _, binding = _deadline_fixture(batch)
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
        _consume(tmp_path, inputs, lock_identity, deadline_binding=binding)
    assert not (batch / "attestation-consumption.json").exists()
    ledger_count = len(list((tmp_path / "evolution" / "producer-nonces").glob("*.json")))
    assert ledger_count == (0 if verification == 2 else 1)


def test_nonce_and_journal_replay_are_rejected(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    batch = inputs[0]
    with _recovery_lock(batch) as lock_identity:
        _consume(tmp_path, inputs, lock_identity)
        with pytest.raises(TrustedBootstrapRegistrationError) as failure:
            _consume(tmp_path, inputs, lock_identity)
    assert failure.value.code == "trusted_registration_claim_conflict"


def test_changed_target_fails_before_claim_publication(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    batch, producer_root, _, _, _, attestation, _ = inputs
    replacement = producer_root / "replacement.py"
    replacement.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    replacement.chmod(0o755)
    os.replace(replacement, producer_root / "producer.py")
    with _recovery_lock(batch) as lock_identity, pytest.raises(TrustedBootstrapRegistrationError) as failure:
        _consume(tmp_path, inputs, lock_identity)
    nonce_key = hashlib.sha256(attestation.nonce.encode("utf-8")).hexdigest()
    assert failure.value.code == "trusted_registration_target_changed"
    assert not (batch / "attestation-consumption.json").exists()
    assert not (tmp_path / "evolution" / "producer-nonces" / f"{nonce_key}.json").exists()


def test_partial_claim_publication_remains_nonreplayable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path)
    batch, _, _, _, _, attestation, _ = inputs
    original = registration_module._atomic_json

    def fail_batch(path: Path, value: dict[str, object], *, exclusive: bool = False) -> None:
        if path.name == "attestation-consumption.json":
            raise registration_module.ProducerProcessError("producer_process_test_write_failed")
        original(path, value, exclusive=exclusive)

    with _recovery_lock(batch) as lock_identity:
        monkeypatch.setattr(registration_module, "_atomic_json", fail_batch)
        with pytest.raises(TrustedBootstrapRegistrationError) as failure:
            _consume(tmp_path, inputs, lock_identity)
        assert failure.value.code == "trusted_registration_claim_conflict"
        monkeypatch.setattr(registration_module, "_atomic_json", original)
        with pytest.raises(TrustedBootstrapRegistrationError) as replay:
            _consume(tmp_path, inputs, lock_identity)
        assert replay.value.code == "trusted_registration_claim_conflict"
    nonce_key = hashlib.sha256(attestation.nonce.encode("utf-8")).hexdigest()
    assert (tmp_path / "evolution" / "producer-nonces" / f"{nonce_key}.json").is_file()
    assert not (batch / "attestation-consumption.json").exists()


def test_wrong_lock_and_expired_deadline_do_not_consume(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    batch, producer_root, launch, descriptor, intent, attestation, _ = inputs
    with _recovery_lock(batch) as lock_identity:
        with pytest.raises(TrustedBootstrapRegistrationError) as failure:
            _consume(tmp_path, inputs, (lock_identity[0], lock_identity[1] + 1))
        assert failure.value.code == "trusted_registration_lock_mismatch"
        with pytest.raises(TrustedBootstrapRegistrationError) as failure:
            consume_trusted_bootstrap_attestation(
                tmp_path, producer_root=producer_root, launch=launch,
                descriptor=descriptor, intent=intent, attestation=attestation,
                recovery_lock_identity=lock_identity, deadline=time.monotonic() - 1,
            )
        assert failure.value.code == "trusted_registration_wall_timeout"
    assert not (batch / "attestation-consumption.json").exists()
