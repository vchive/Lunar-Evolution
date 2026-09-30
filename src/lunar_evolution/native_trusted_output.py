"""Read-only output preparation for one completed native trusted producer attempt."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import _benchmark_files as _files
from .algorithm import AlgorithmProblemContract
from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_attempt import recover_native_trusted_attempt
from .native_trusted_capture import (
    NativeTrustedCaptureError,
    recover_native_trusted_output_capture,
)
from .native_trusted_receipt import (
    NativeTrustedReceiptError,
    recover_native_trusted_execution_receipt,
)
from .producer_bundle_admission import (
    ProducerBundleAdmissionPlan,
    build_producer_bundle_admission_plan,
)
from .producer_bundle_handoff import (
    BundleGroup,
    VerifiedProducerBundle,
    prepare_producer_bundle_manifest,
)
from .producer_bundle_population import ProducerBundleDraft, prepare_producer_bundle_drafts
from .producer_handoff import (
    MAX_PRODUCER_ENVELOPE_BYTES,
    ProducerHandoffError,
    ProducerResultEnvelope,
    parse_producer_envelope,
)
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import ProducerProcessError, _read_envelope


class NativeTrustedOutputError(ValueError):
    """Fixed-code output-preparation failure without producer-controlled text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NativeTrustedOutputPreparation:
    process_terminal_sha256: str
    output_capture_sha256: str | None
    envelope_bytes_sha256: str
    envelope: ProducerResultEnvelope
    bundles: tuple[VerifiedProducerBundle, ...]
    drafts: tuple[ProducerBundleDraft, ...]
    admission_plan: ProducerBundleAdmissionPlan
    execution_receipt_sha256: str | None = None
    request_coverage: str = "producer_declaration_only"
    publication_eligible: bool = False


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NativeTrustedOutputError("native_trusted_output_envelope_invalid")
        result[key] = value
    return result


def prepare_native_trusted_output(
    workspace: str | Path,
    *,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact,
    contract: AlgorithmProblemContract,
    groups: Sequence[BundleGroup],
    evaluator_kind: str,
    evaluator_fingerprint: str,
    runner_fingerprint: str,
    dependency_sha256: str,
    environment_sha256: str,
    require_same_attempt_capture: bool = False,
    require_execution_receipt: bool = False,
) -> NativeTrustedOutputPreparation:
    """Verify current producer files, without granting durable execution or publication authority.

    The process terminal is independently recovered before output is read. Production callers
    require the same-attempt capture; the default remains a read-only supporting inspection.
    """
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(contract, AlgorithmProblemContract):
        raise NativeTrustedOutputError("native_trusted_output_input_invalid")
    if type(require_same_attempt_capture) is not bool or type(require_execution_receipt) is not bool:
        raise NativeTrustedOutputError("native_trusted_output_input_invalid")
    if (
        contract.digest() != intent.contract_sha256
        or evaluator_kind != intent.evaluator_kind
        or evaluator_fingerprint != intent.evaluator_fingerprint
        or runner_fingerprint != intent.runner_fingerprint
        or dependency_sha256 != intent.dependency_sha256
        or environment_sha256 != intent.environment_sha256
    ):
        raise NativeTrustedOutputError("native_trusted_output_authority_mismatch")
    try:
        terminal = recover_native_trusted_attempt(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    except (ValueError, OSError) as exc:
        raise NativeTrustedOutputError("native_trusted_output_process_unverified") from exc
    if (
        terminal.get("protocol") != "lunar-native-trusted-process-terminal-v1"
        or terminal.get("process_status") != "exited_zero"
        or terminal.get("cleanup_status") not in {"cleaned", "already_exited"}
        or terminal.get("gate_released") is not True
        or terminal.get("target_started") is not True
        or not isinstance(terminal.get("terminal_sha256"), str)
    ):
        raise NativeTrustedOutputError("native_trusted_output_process_incomplete")
    batch = Path(workspace).expanduser().absolute() / "evolution" / "producer-batches" / intent.journal_id
    execution_receipt = None
    if require_execution_receipt:
        try:
            execution_receipt = recover_native_trusted_execution_receipt(
                workspace, intent=intent, attestation=attestation, artifact=artifact,
            )
        except NativeTrustedReceiptError as exc:
            raise NativeTrustedOutputError("native_trusted_output_receipt_unverified") from exc
    capture: dict[str, object] | None = None
    if require_same_attempt_capture or require_execution_receipt:
        try:
            capture = recover_native_trusted_output_capture(
                batch, intent=intent, terminal=terminal,
            )
        except NativeTrustedCaptureError as exc:
            raise NativeTrustedOutputError("native_trusted_output_capture_unverified") from exc
        broker = capture["broker_evidence"]
        if broker is not None and (
            broker["complete"] is not True or broker["declared_count_matches"] is not True
        ):
            raise NativeTrustedOutputError("native_trusted_output_broker_incomplete")
    path = batch / intent.envelope_path
    limit = min(intent.output_max_bytes, MAX_PRODUCER_ENVELOPE_BYTES)
    try:
        # This is a bounded read-only inspection budget, not a renewed producer wall deadline.
        evidence, declared_requests = _read_envelope(
            path, relative_path=intent.envelope_path, limit=limit,
            deadline=time.monotonic() + 5.0, monotonic=time.monotonic,
        )
        raw = _files.read_regular_file(path, limit)
        info = path.lstat()
    except (ProducerProcessError, _files.BenchmarkFileError, OSError) as exc:
        raise NativeTrustedOutputError("native_trusted_output_envelope_unverified") from exc
    if (
        len(raw) != evidence.bytes
        or hashlib.sha256(raw).hexdigest() != evidence.sha256
        or (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
        != (evidence.device, evidence.inode, evidence.mtime_ns, evidence.ctime_ns, 1)
    ):
        raise NativeTrustedOutputError("native_trusted_output_envelope_changed")
    try:
        envelope = parse_producer_envelope(json.loads(raw, object_pairs_hook=_unique_object))
    except (ProducerHandoffError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise NativeTrustedOutputError("native_trusted_output_envelope_invalid") from exc
    if (
        envelope.producer_id != intent.producer_id
        or envelope.producer_fingerprint != intent.producer_fingerprint
        or envelope.contract_sha256 != intent.contract_sha256
        or envelope.budget.get("requests") != declared_requests
        or declared_requests > intent.max_requests
    ):
        raise NativeTrustedOutputError("native_trusted_output_envelope_mismatch")
    output = batch / intent.output_directory
    bundles = prepare_producer_bundle_manifest(
        output, envelope, groups, contract, intent.producer_fingerprint, intent.producer_id,
    )
    drafts = prepare_producer_bundle_drafts(output, bundles)
    plan = build_producer_bundle_admission_plan(
        drafts, contract_sha256=intent.contract_sha256,
        evaluator_kind=intent.evaluator_kind, evaluator_fingerprint=intent.evaluator_fingerprint,
        runner_fingerprint=intent.runner_fingerprint, dependency_sha256=intent.dependency_sha256,
        environment_sha256=intent.environment_sha256,
    )
    if capture is not None:
        try:
            current = recover_native_trusted_output_capture(
                batch, intent=intent, terminal=terminal,
            )
        except NativeTrustedCaptureError as exc:
            raise NativeTrustedOutputError("native_trusted_output_capture_changed") from exc
        if current != capture or evidence.sha256 != capture["envelope_evidence"]["sha256"]:
            raise NativeTrustedOutputError("native_trusted_output_capture_changed")
    if execution_receipt is not None:
        try:
            current_receipt = recover_native_trusted_execution_receipt(
                workspace, intent=intent, attestation=attestation, artifact=artifact,
            )
        except NativeTrustedReceiptError as exc:
            raise NativeTrustedOutputError("native_trusted_output_receipt_changed") from exc
        if current_receipt != execution_receipt:
            raise NativeTrustedOutputError("native_trusted_output_receipt_changed")
    return NativeTrustedOutputPreparation(
        process_terminal_sha256=str(terminal["terminal_sha256"]),
        output_capture_sha256=(str(capture["capture_sha256"]) if capture is not None else None),
        envelope_bytes_sha256=evidence.sha256, envelope=envelope,
        bundles=bundles, drafts=drafts, admission_plan=plan,
        execution_receipt_sha256=(
            execution_receipt.receipt_sha256 if execution_receipt is not None else None
        ),
        request_coverage=(
            "brokered_requests_only"
            if capture is not None and capture["broker_evidence"] is not None
            else "producer_declaration_only"
        ),
    )


__all__ = [
    "NativeTrustedOutputError", "NativeTrustedOutputPreparation", "prepare_native_trusted_output",
]
