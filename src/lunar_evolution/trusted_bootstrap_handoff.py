"""Provider-free handoff between trusted bootstrap admission and Feature 156 registration.

The adapter deliberately has no process, filesystem, clock, or provider effects.  It verifies
that the records a production runner is about to publish describe one exact trusted launch and
returns a detached, self-authenticating handoff receipt.  Publishing, gate release, cleanup, and
recovery remain responsibilities of the production runner.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from .producer_bootstrap import (
    ProducerBootstrapError,
    TrustedBootstrapDescriptor,
    TrustedBootstrapLaunch,
    build_trusted_bootstrap_launch,
    verify_trusted_bootstrap_attempt,
    verify_trusted_bootstrap_process_registration,
)
from .producer_launcher import (
    ProducerLaunchAttestation,
    ProducerLaunchError,
    ProducerLaunchIntent,
    parse_producer_launch_attestation,
    parse_producer_launch_intent,
)

TRUSTED_BOOTSTRAP_HANDOFF_PROTOCOL = "lunar-trusted-producer-bootstrap-handoff-v1"
TRUSTED_BOOTSTRAP_HANDOFF_SCHEMA_VERSION = "1"
_MAX_HANDOFF_BYTES = 256 * 1024


class TrustedBootstrapHandoffError(ValueError):
    """Fixed-code failure while binding trusted bootstrap records."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise TrustedBootstrapHandoffError(code)


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise TrustedBootstrapHandoffError("trusted_bootstrap_handoff_canonical_invalid") from exc
    if len(encoded) > _MAX_HANDOFF_BYTES:
        _fail("trusted_bootstrap_handoff_too_large")
    return encoded


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha(value: object, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        _fail(code)
    return value


def _int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail(code)
    return value


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail(code)
    return value


def _handoff_payload(
    *,
    launch: TrustedBootstrapLaunch,
    descriptor: TrustedBootstrapDescriptor,
    consumption: Mapping[str, object],
    registration: Mapping[str, object],
) -> dict[str, object]:
    # The process-registration verifier has already checked platform-specific values and
    # exact target/bootstrap bindings. Copy only those checked fields into the receipt so
    # producer-controlled or future extension fields cannot become an implicit authority.
    return {
        "schema_version": TRUSTED_BOOTSTRAP_HANDOFF_SCHEMA_VERSION,
        "protocol": TRUSTED_BOOTSTRAP_HANDOFF_PROTOCOL,
        "launch_sha256": launch.launch_sha256 or launch.digest(),
        "descriptor_sha256": descriptor.descriptor_sha256 or descriptor.digest(),
        "intent_sha256": launch.intent_sha256,
        "attestation_sha256": launch.attestation_sha256,
        "consumption_sha256": consumption["consumption_sha256"],
        "registration_sha256": registration["registration_sha256"],
        "pid": registration["pid"],
        "pgid": registration["pgid"],
        "bootstrap_execution_binding": registration["execution_binding"],
        "bootstrap_snapshot_relative_path": registration["execution_snapshot_relative_path"],
        "bootstrap_snapshot_sha256": registration["execution_snapshot_sha256"],
        "bootstrap_snapshot_size": registration["execution_snapshot_size"],
        "target_execution_binding": registration["target_execution_binding"],
        "target_snapshot_relative_path": registration["target_execution_snapshot_relative_path"],
        "target_snapshot_sha256": registration["target_execution_snapshot_sha256"],
        "target_snapshot_size": registration["target_execution_snapshot_size"],
    }


def build_trusted_bootstrap_process_registration_handoff(
    *,
    launch: TrustedBootstrapLaunch,
    descriptor: TrustedBootstrapDescriptor,
    intent: ProducerLaunchIntent | object,
    attestation: ProducerLaunchAttestation | object,
    consumption: Mapping[str, object] | object,
    registration: Mapping[str, object] | object,
) -> dict[str, object]:
    """Validate and detach one trusted-bootstrap/Feature 156 registration handoff.

    The returned mapping is canonicalizable and carries a ``handoff_sha256`` self-digest.
    This function performs no I/O and does not imply that registration was published, that
    the gate was released, or that the target bytes executed.
    """
    if not isinstance(launch, TrustedBootstrapLaunch):
        _fail("trusted_bootstrap_handoff_launch_invalid")
    if not isinstance(descriptor, TrustedBootstrapDescriptor):
        _fail("trusted_bootstrap_handoff_descriptor_invalid")
    try:
        parsed_intent = (
            intent if isinstance(intent, ProducerLaunchIntent)
            else parse_producer_launch_intent(intent)
        )
        parsed_attestation = (
            attestation if isinstance(attestation, ProducerLaunchAttestation)
            else parse_producer_launch_attestation(attestation)
        )
        expected_launch = build_trusted_bootstrap_launch(
            parsed_intent, parsed_attestation, descriptor, gate_nonce=launch.gate_nonce,
        )
    except (ProducerBootstrapError, ProducerLaunchError, TypeError, ValueError) as exc:
        raise TrustedBootstrapHandoffError("trusted_bootstrap_handoff_admission_invalid") from exc
    if expected_launch != launch:
        _fail("trusted_bootstrap_handoff_launch_mismatch")

    consumption_map = _mapping(consumption, "trusted_bootstrap_handoff_consumption_invalid")
    registration_map = _mapping(registration, "trusted_bootstrap_handoff_registration_invalid")
    try:
        # Keep both validators explicit: the first checks the formal registration's platform
        # binding; the second checks its relationship to the one-time target claim and launch.
        verified_registration = verify_trusted_bootstrap_process_registration(
            launch, descriptor, registration_map,
        )
        verified_attempt = verify_trusted_bootstrap_attempt(
            launch, descriptor, parsed_intent, parsed_attestation,
            consumption_map, verified_registration, evidence=None,
        )
    except ProducerBootstrapError as exc:
        raise TrustedBootstrapHandoffError(exc.code) from exc
    if verified_attempt.get("status") != "recovery_required":
        _fail("trusted_bootstrap_handoff_attempt_state_invalid")

    payload = _handoff_payload(
        launch=launch,
        descriptor=descriptor,
        consumption=consumption_map,
        registration=verified_registration,
    )
    _sha(payload["launch_sha256"], "trusted_bootstrap_handoff_launch_digest_invalid")
    _sha(payload["descriptor_sha256"], "trusted_bootstrap_handoff_descriptor_digest_invalid")
    _sha(payload["intent_sha256"], "trusted_bootstrap_handoff_intent_digest_invalid")
    _sha(payload["attestation_sha256"], "trusted_bootstrap_handoff_attestation_digest_invalid")
    _sha(payload["consumption_sha256"], "trusted_bootstrap_handoff_consumption_digest_invalid")
    _sha(payload["registration_sha256"], "trusted_bootstrap_handoff_registration_digest_invalid")
    _int(payload["pid"], "trusted_bootstrap_handoff_process_identity_invalid")
    _int(payload["pgid"], "trusted_bootstrap_handoff_process_identity_invalid")
    _int(payload["bootstrap_snapshot_size"], "trusted_bootstrap_handoff_binding_invalid")
    _int(payload["target_snapshot_size"], "trusted_bootstrap_handoff_binding_invalid")
    payload["handoff_sha256"] = _digest(payload)
    return payload


__all__ = [
    "TRUSTED_BOOTSTRAP_HANDOFF_PROTOCOL",
    "TRUSTED_BOOTSTRAP_HANDOFF_SCHEMA_VERSION",
    "TrustedBootstrapHandoffError",
    "build_trusted_bootstrap_process_registration_handoff",
]
