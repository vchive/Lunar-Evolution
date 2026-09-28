from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest
from test_producer_bootstrap import _attempt_records

from lunar_evolution import trusted_bootstrap_registration as registration_module
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


def _consume(tmp_path: Path, inputs: tuple, lock_identity: tuple[int, int]):
    _, producer_root, launch, descriptor, intent, attestation, _ = inputs
    return consume_trusted_bootstrap_attestation(
        tmp_path, producer_root=producer_root, launch=launch,
        descriptor=descriptor, intent=intent, attestation=attestation,
        recovery_lock_identity=lock_identity, deadline=time.monotonic() + 5,
    )


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
