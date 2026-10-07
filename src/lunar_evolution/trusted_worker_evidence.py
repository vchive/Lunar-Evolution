"""Read-only composition of trusted producer/worker lifecycle evidence.

This module is deliberately an evidence verifier, not a launcher or lease service.  It
rebinds the existing launch attestation, process registration, bootstrap handshake and native
process terminal/deadline/cleanup records, then returns an operational classification. It does no I/O,
process inspection, signal delivery, ledger writes or retries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .native_deadline_binding import verify_native_deadline_record_binding
from .native_trusted_attempt import (
    NativeTrustedAttemptError,
    _verify_terminal_record,
)
from .producer_bootstrap import (
    ProducerBootstrapError,
    TrustedBootstrapDescriptor,
    TrustedBootstrapLaunch,
    _parse_trusted_bootstrap_consumption,
    verify_trusted_bootstrap_attempt,
    verify_trusted_bootstrap_process_registration,
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
    terminal_sha256: str | None = None
    deadline_sha256: str | None = None
    cleanup_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "launch_sha256": self.launch_sha256,
            "registration_sha256": self.registration_sha256,
            "evidence_sha256": self.evidence_sha256,
            "terminal_sha256": self.terminal_sha256,
            "deadline_sha256": self.deadline_sha256,
            "cleanup_sha256": self.cleanup_sha256,
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
    terminal: object | None = None,
    deadline: object | None = None,
    cleanup: object | None = None,
) -> TrustedWorkerEvidenceResult:
    """Verify one persisted worker chain without granting execution authority.

    Handshake success does not establish completion. Terminal, original deadline and owner-checked
    cleanup must all match. Cancellation may bind unknown handshake evidence but cannot become
    successful completion. This pure check does not verify current boot or stream/output files;
    native filesystem recovery retains those additional checks.
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
        claim = _parse_trusted_bootstrap_consumption(consumption)
        if "deadline_binding" in claim and deadline is not None:
            # Pure bytes projection only. Native recovery separately observes the pinned inode.
            verify_native_deadline_record_binding(deadline, claim["deadline_binding"])
        if evidence is None:
            return TrustedWorkerEvidenceResult(
                "unknown_recovery_required", "bootstrap_evidence_missing", launch_sha,
                registration_sha, None,
            )
        attempt = verify_trusted_bootstrap_attempt(
            launch, descriptor, intent, attestation, consumption, registration,
            evidence=evidence,
        )
        evidence_sha = attempt.get("evidence_sha256")
        for record, reason in (
            (terminal, "process_terminal_missing"),
            (deadline, "original_deadline_missing"),
            (cleanup, "cleanup_evidence_missing"),
        ):
            if record is None:
                return TrustedWorkerEvidenceResult(
                    "unknown_recovery_required", reason, launch_sha, registration_sha,
                    evidence_sha if isinstance(evidence_sha, str) else None,
                )
        bound = {**attempt, "handoff_sha256": parsed_handoff["handoff_sha256"]}
        verified = _verify_terminal_record(
            terminal, registration=verify_trusted_bootstrap_process_registration(
                launch, descriptor, registration,
            ), bound=bound, deadline_record=deadline,
            cleanup_record=cleanup, intent=intent,
        )
        status = "trusted_completed" if verified["process_status"] == "exited_zero" else "trusted_failed"
        return TrustedWorkerEvidenceResult(
            status, "verified", launch_sha, registration_sha,
            evidence_sha if isinstance(evidence_sha, str) else None,
            str(verified["terminal_sha256"]), str(verified["deadline_sha256"]),
            str(verified["cleanup_sha256"]),
        )
    except (ProducerBootstrapError, TrustedBootstrapHandoffError, NativeTrustedAttemptError,
            TypeError, ValueError) as exc:
        # The verifier intentionally turns any source/identity drift into a non-authoritative
        # result.  Callers can log the fixed reason while the original records remain immutable.
        code = getattr(exc, "code", None) or "trusted_worker_identity_drift"
        return TrustedWorkerEvidenceResult("identity_drift", str(code), launch_sha, None, None)


__all__ = [
    "TrustedWorkerEvidenceError",
    "TrustedWorkerEvidenceResult",
    "verify_trusted_worker_evidence",
]
