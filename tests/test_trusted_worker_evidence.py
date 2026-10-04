from __future__ import annotations

import hashlib
import json

from test_producer_bootstrap import _attempt_records

from lunar_evolution.trusted_bootstrap_handoff import (
    build_trusted_bootstrap_process_registration_handoff,
)
from lunar_evolution.trusted_worker_evidence import verify_trusted_worker_evidence


def _chain(tmp_path):
    launch, descriptor, intent, attestation, claim, registration, evidence = _attempt_records(tmp_path)
    handoff = build_trusted_bootstrap_process_registration_handoff(
        launch=launch, descriptor=descriptor, intent=intent, attestation=attestation,
        consumption=claim, registration=registration,
    )
    return launch, descriptor, intent, attestation, claim, registration, handoff, evidence


def test_unified_verifier_accepts_completed_chain_without_side_effects(tmp_path):
    launch, descriptor, intent, attestation, claim, registration, handoff, evidence = _chain(tmp_path)
    result = verify_trusted_worker_evidence(
        launch=launch, descriptor=descriptor, intent=intent, attestation=attestation,
        consumption=claim, registration=registration, handoff=handoff, evidence=evidence,
    )
    assert result.status == "trusted_completed"
    assert result.reason_code == "verified"
    assert result.registration_sha256 == registration["registration_sha256"]


def test_unified_verifier_keeps_missing_terminal_unknown(tmp_path):
    launch, descriptor, intent, attestation, claim, registration, handoff, _ = _chain(tmp_path)
    result = verify_trusted_worker_evidence(
        launch=launch, descriptor=descriptor, intent=intent, attestation=attestation,
        consumption=claim, registration=registration, handoff=handoff, evidence=None,
    )
    assert result.status == "unknown_recovery_required"
    assert result.reason_code == "terminal_evidence_missing"


def test_unified_verifier_rejects_registration_drift_as_non_authoritative(tmp_path):
    launch, descriptor, intent, attestation, claim, registration, handoff, evidence = _chain(tmp_path)
    forged = dict(handoff)
    forged["registration_sha256"] = "f" * 64
    forged["handoff_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in forged.items() if key != "handoff_sha256"},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()
    ).hexdigest()
    result = verify_trusted_worker_evidence(
        launch=launch, descriptor=descriptor, intent=intent, attestation=attestation,
        consumption=claim, registration=registration, handoff=forged, evidence=evidence,
    )
    assert result.status == "identity_drift"
    assert result.registration_sha256 is None
