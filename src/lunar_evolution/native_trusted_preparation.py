"""Durable, non-publishing preparation receipt for native trusted producer output.

The receipt joins recovered process/capture/broker evidence to an explicit source grouping and
the exact native admission plan. It grants no provider-egress or publication authority.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .algorithm import AlgorithmProblemContract
from .candidate_evaluation_spec import canonical_json
from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_attempt import recover_native_trusted_attempt
from .native_trusted_capture import recover_native_trusted_output_capture
from .native_trusted_output import NativeTrustedOutputPreparation, prepare_native_trusted_output
from .producer_bundle_handoff import BundleGroup
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import ProducerProcessError, _atomic_json, _read_durable_json

_NAME = "native-trusted-preparation.json"
_PROTOCOL = "lunar-native-trusted-preparation-v1"
_BLOCKERS = ("complete_egress_authority", "publication_transaction", "delivery_verification")
_MAX_BYTES = 256 * 1024


class NativeTrustedPreparationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=_MAX_BYTES)).hexdigest()


@dataclass(frozen=True, slots=True)
class NativeTrustedPreparation:
    receipt_sha256: str
    receipt_path: Path
    output: NativeTrustedOutputPreparation
    publication_eligible: bool = False
    publication_blockers: tuple[str, ...] = _BLOCKERS


def _prepared(
    workspace: str | Path, *, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
    contract: AlgorithmProblemContract, groups: Sequence[BundleGroup],
) -> tuple[NativeTrustedOutputPreparation, dict[str, object]]:
    if type(intent) is not ProducerLaunchIntent or type(attestation) is not ProducerLaunchAttestation:
        raise NativeTrustedPreparationError("native_trusted_preparation_input_invalid")
    try:
        selected = tuple(BundleGroup(group.bundle_id, group.entrypoint, group.material_paths) for group in groups)
        output = prepare_native_trusted_output(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
            contract=contract, groups=selected, evaluator_kind=intent.evaluator_kind,
            evaluator_fingerprint=intent.evaluator_fingerprint,
            runner_fingerprint=intent.runner_fingerprint, dependency_sha256=intent.dependency_sha256,
            environment_sha256=intent.environment_sha256, require_same_attempt_capture=True,
        )
        terminal = recover_native_trusted_attempt(workspace, intent=intent, attestation=attestation, artifact=artifact)
        batch = Path(workspace).expanduser().absolute() / "evolution/producer-batches" / intent.journal_id
        capture = recover_native_trusted_output_capture(batch, intent=intent, terminal=terminal)
    except (ValueError, OSError, TypeError, AttributeError) as exc:
        raise NativeTrustedPreparationError("native_trusted_preparation_evidence_unverified") from exc
    broker = capture["broker_evidence"]
    if (not isinstance(broker, dict) or broker.get("complete") is not True
            or broker.get("declared_count_matches") is not True
            or broker.get("coverage") != "brokered_requests_only"):
        raise NativeTrustedPreparationError("native_trusted_preparation_broker_incomplete")
    if (output.process_terminal_sha256 != terminal["terminal_sha256"]
            or output.output_capture_sha256 != capture["capture_sha256"]
            or output.envelope_bytes_sha256 != capture["envelope_evidence"]["sha256"]
            or output.request_coverage != "brokered_requests_only"
            or output.publication_eligible is not False):
        raise NativeTrustedPreparationError("native_trusted_preparation_evidence_changed")
    body: dict[str, object] = {
        "schema_version": "1", "protocol": _PROTOCOL,
        **{name: getattr(intent, name) for name in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
        )},
        "attestation_sha256": attestation.digest(),
        "process_terminal_sha256": output.process_terminal_sha256,
        "output_capture_sha256": output.output_capture_sha256,
        "envelope_bytes_sha256": output.envelope_bytes_sha256,
        "broker_evidence_sha256": _digest(broker),
        "groups": [group.to_dict() for group in selected],
        "drafts": [draft.to_dict() for draft in output.drafts],
        "admission_plan": output.admission_plan.to_dict(),
        "admission_plan_sha256": output.admission_plan.digest(),
        "request_coverage": "brokered_requests_only",
        "receipt_scope": "post_attempt_preparation", "publication_eligible": False,
        "publication_blockers": list(_BLOCKERS),
    }
    return output, {**body, "receipt_sha256": _digest(body)}


def _read(path: Path) -> dict[str, object]:
    try:
        record = _read_durable_json(path, code="native_trusted_preparation_receipt_invalid")
        body = {key: value for key, value in record.items() if key != "receipt_sha256"}
        if record.get("protocol") != _PROTOCOL or record.get("receipt_sha256") != _digest(body):
            raise NativeTrustedPreparationError("native_trusted_preparation_receipt_invalid")
        return record
    except (ProducerProcessError, ValueError, TypeError) as exc:
        raise NativeTrustedPreparationError("native_trusted_preparation_receipt_invalid") from exc


def persist_native_trusted_preparation(
    workspace: str | Path, *, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
    contract: AlgorithmProblemContract, groups: Sequence[BundleGroup],
) -> NativeTrustedPreparation:
    """Create or exactly reuse an immutable preparation; never evaluate or publish candidates."""
    arguments = {"intent": intent, "attestation": attestation, "artifact": artifact,
                 "contract": contract, "groups": tuple(groups)}
    output, receipt = _prepared(workspace, **arguments)
    path = Path(workspace).expanduser().absolute() / "evolution/producer-batches" / intent.journal_id / _NAME
    try:
        _atomic_json(path, receipt, exclusive=True)
    except ProducerProcessError as exc:
        if exc.code != "producer_process_attestation_replayed":
            raise NativeTrustedPreparationError("native_trusted_preparation_write_unknown") from exc
    stored = _read(path)
    _, checked = _prepared(workspace, **arguments)
    if stored != receipt or checked != receipt:
        raise NativeTrustedPreparationError("native_trusted_preparation_receipt_mismatch")
    return NativeTrustedPreparation(str(receipt["receipt_sha256"]), path, output)


def recover_native_trusted_preparation(
    workspace: str | Path, *, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
    contract: AlgorithmProblemContract, groups: Sequence[BundleGroup],
    expected_receipt_sha256: str,
) -> NativeTrustedPreparation:
    """Read-only evidence replay requiring the caller's original receipt and explicit grouping."""
    path = Path(workspace).expanduser().absolute() / "evolution/producer-batches" / intent.journal_id / _NAME
    stored = _read(path)
    if stored.get("receipt_sha256") != expected_receipt_sha256:
        raise NativeTrustedPreparationError("native_trusted_preparation_receipt_mismatch")
    output, expected = _prepared(workspace, intent=intent, attestation=attestation, artifact=artifact,
                                 contract=contract, groups=groups)
    if expected != stored or _read(path) != stored:
        raise NativeTrustedPreparationError("native_trusted_preparation_receipt_mismatch")
    return NativeTrustedPreparation(str(stored["receipt_sha256"]), path, output)


__all__ = [
    "NativeTrustedPreparation", "NativeTrustedPreparationError",
    "persist_native_trusted_preparation", "recover_native_trusted_preparation",
]
