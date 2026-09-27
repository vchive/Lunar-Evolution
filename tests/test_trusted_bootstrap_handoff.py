from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_producer_bootstrap import _attempt_records, _rehash_record

from lunar_evolution.trusted_bootstrap_handoff import (
    TRUSTED_BOOTSTRAP_HANDOFF_PROTOCOL,
    TrustedBootstrapHandoffError,
    build_trusted_bootstrap_process_registration_handoff,
)


def _records(tmp_path: Path):
    return _attempt_records(tmp_path)


def test_handoff_binds_formal_records_and_returns_detached_receipt(tmp_path: Path):
    launch, descriptor, intent, attestation, claim, registration, _ = _records(tmp_path)
    receipt = build_trusted_bootstrap_process_registration_handoff(
        launch=launch, descriptor=descriptor, intent=intent, attestation=attestation,
        consumption=claim, registration=registration,
    )
    assert receipt["protocol"] == TRUSTED_BOOTSTRAP_HANDOFF_PROTOCOL
    assert receipt["launch_sha256"] == launch.launch_sha256
    assert receipt["descriptor_sha256"] == descriptor.descriptor_sha256
    assert receipt["consumption_sha256"] == claim["consumption_sha256"]
    assert receipt["registration_sha256"] == registration["registration_sha256"]
    digest = hashlib.sha256(
        json.dumps(receipt | {}, sort_keys=True, separators=(",", ":"), allow_nan=False)
        .replace(f',"handoff_sha256":"{receipt["handoff_sha256"]}"', "")
        .encode()
    ).hexdigest()
    # Recompute from the exact payload shape, independent of insertion order.
    unsigned = {key: value for key, value in receipt.items() if key != "handoff_sha256"}
    assert receipt["handoff_sha256"] == hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert digest  # keep the first canonicalization path exercised without relying on order


@pytest.mark.parametrize("field", ["launch_sha256", "target_snapshot_sha256"])
def test_handoff_rejects_registration_binding_drift(tmp_path: Path, field: str):
    launch, descriptor, intent, attestation, claim, registration, _ = _records(tmp_path)
    forged = dict(registration)
    forged[field] = "f" * 64
    _rehash_record(forged, "registration_sha256")
    with pytest.raises(TrustedBootstrapHandoffError) as failure:
        build_trusted_bootstrap_process_registration_handoff(
            launch=launch, descriptor=descriptor, intent=intent, attestation=attestation,
            consumption=claim, registration=forged,
        )
    assert failure.value.code.startswith("producer_bootstrap_")


def test_handoff_rejects_consumption_mismatch(tmp_path: Path):
    launch, descriptor, intent, attestation, claim, registration, _ = _records(tmp_path)
    forged = dict(claim)
    forged["journal_id"] = "journal-999"
    _rehash_record(forged, "consumption_sha256")
    with pytest.raises(TrustedBootstrapHandoffError) as failure:
        build_trusted_bootstrap_process_registration_handoff(
            launch=launch, descriptor=descriptor, intent=intent, attestation=attestation,
            consumption=forged, registration=registration,
        )
    assert failure.value.code == "producer_bootstrap_attempt_consumption_binding_mismatch"


def test_handoff_is_provider_free_and_does_not_touch_filesystem(tmp_path: Path, monkeypatch):
    records = _records(tmp_path)
    launch, descriptor, intent, attestation, claim, registration, _ = records
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("handoff must not perform filesystem or process operations")

    monkeypatch.setattr("os.open", forbidden)
    monkeypatch.setattr("os.stat", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    receipt = build_trusted_bootstrap_process_registration_handoff(
        launch=launch, descriptor=descriptor, intent=intent, attestation=attestation,
        consumption=claim, registration=registration,
    )
    assert receipt.get("status", "detached")
    assert before == sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
