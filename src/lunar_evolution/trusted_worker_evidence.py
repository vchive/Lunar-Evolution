"""Read-only composition of trusted producer/worker lifecycle evidence.

This module is deliberately an evidence verifier, not a launcher or lease service.  It
rebinds the existing launch attestation, process registration, bootstrap handoff and terminal
evidence records, then returns a small operational classification.  It performs no I/O,
process inspection, signal delivery, ledger writes or retries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .producer_bootstrap import (
    ProducerBootstrapError,
    TrustedBootstrapDescriptor,
    TrustedBootstrapLaunch,
    verify_trusted_bootstrap_attempt,
)
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .trusted_bootstrap_handoff import (
    TrustedBootstrapHandoffError,
    verify_trusted_bootstrap_process_registration_handoff,
)


class TrustedWorkerEvidenceError(ValueError):
    """Fixed-code error for invalid verifier inputs."""


@dataclass(frozen=True, slots=True)
class TrustedWorkerEvidenceResult:
    """Detached classification of one complete local worker evidence set."""

    status: str
    reason_code: str
    launch_sha256: str
    registration_sha256: str | None
    evidence_sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "launch_sha256": self.launch_sha256,
            "registration_sha256": self.registration_sha256,
            "evidence_sha256": self.evidence_sha256,
        }


def verify_trusted_worker_evidence(
    *,
    launch: TrustedBootstrapLaunch,
    descriptor: TrustedBootstrapDescriptor,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation | object,
    consumption: object,
    registration: object,
    handoff: object,
    evidence: object | None,
) -> TrustedWorkerEvidenceResult:
    """Verify one persisted worker chain without granting execution authority.

    ``unknown`` and missing terminal evidence both remain ``unknown_recovery_required``.
    A successful classification requires the independent bootstrap evidence to say ``passed``;
    no score, declaration, or caller-provided status can upgrade an unknown record.
    """
    if not isinstance(launch, TrustedBootstrapLaunch):
        raise TrustedWorkerEvidenceError("trusted_worker_launch_invalid")
    if not isinstance(descriptor, TrustedBootstrapDescriptor):
        raise TrustedWorkerEvidenceError("trusted_worker_descriptor_invalid")
    launch_sha = launch.launch_sha256 or launch.digest()
    try:
        parsed_handoff = verify_trusted_bootstrap_process_registration_handoff(
            handoff,
            launch=launch,
            descriptor=descriptor,
            intent=intent,
            attestation=attestation,
            consumption=consumption,
            registration=registration,
        )
        registration_sha = parsed_handoff["registration_sha256"]
        if evidence is None:
            return TrustedWorkerEvidenceResult(
                "unknown_recovery_required", "terminal_evidence_missing", launch_sha,
                registration_sha, None,
            )
        attempt = verify_trusted_bootstrap_attempt(
            launch, descriptor, intent, attestation, consumption, registration,
            evidence=evidence,
        )
        evidence_sha = attempt.get("evidence_sha256")
        if attempt.get("status") != "evidence_available":
            return TrustedWorkerEvidenceResult(
                "unknown_recovery_required", str(attempt.get("reason", "evidence_unknown")),
                launch_sha, registration_sha, evidence_sha if isinstance(evidence_sha, str) else None,
            )
        bootstrap_status = attempt.get("bootstrap_status")
        if bootstrap_status == "passed":
            status = "trusted_completed"
        elif bootstrap_status == "failed":
            status = "trusted_failed"
        else:
            status = "unknown_recovery_required"
        return TrustedWorkerEvidenceResult(
            status, "verified", launch_sha, registration_sha,
            evidence_sha if isinstance(evidence_sha, str) else None,
        )
    except (ProducerBootstrapError, TrustedBootstrapHandoffError, TypeError, ValueError) as exc:
        # The verifier intentionally turns any source/identity drift into a non-authoritative
        # result.  Callers can log the fixed reason while the original records remain immutable.
        code = getattr(exc, "code", None) or "trusted_worker_identity_drift"
        return TrustedWorkerEvidenceResult("identity_drift", str(code), launch_sha, None, None)


__all__ = [
    "TrustedWorkerEvidenceError",
    "TrustedWorkerEvidenceResult",
    "verify_trusted_worker_evidence",
]
