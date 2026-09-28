"""One-shot cooperative producer preparation with explicit evidence limits.

This entry point joins the existing process and multi-file handoff boundaries. It is
supporting evidence only: a directly executed producer can act before its work gate,
and its request count is a declaration rather than controller-observed traffic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import _benchmark_files as _files
from .algorithm import AlgorithmProblemContract
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
from .producer_handoff import ProducerHandoffError, ProducerResultEnvelope, parse_producer_envelope
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import (
    ProducerExecutionReceipt,
    recover_producer_process,
    run_producer_process,
)


class ProducerLifecycleError(ValueError):
    """Fixed-code preparation error without producer-controlled text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProducerLifecyclePreparation:
    receipt: ProducerExecutionReceipt
    envelope: ProducerResultEnvelope
    bundles: tuple[VerifiedProducerBundle, ...]
    drafts: tuple[ProducerBundleDraft, ...]
    admission_plan: ProducerBundleAdmissionPlan
    request_coverage: str = "cooperative_declaration_only"
    broker_coverage: str = "not_integrated"
    publication_status: str = "not_started"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProducerLifecycleError("producer_lifecycle_envelope_invalid")
        result[key] = value
    return result


def _read_bound_envelope(
    workspace: str | Path, intent: ProducerLaunchIntent, receipt: ProducerExecutionReceipt,
) -> tuple[Path, ProducerResultEnvelope]:
    evidence = receipt.envelope_evidence
    if evidence is None or evidence.read_status != "stable" or evidence.relative_path != intent.envelope_path:
        raise ProducerLifecycleError("producer_lifecycle_envelope_unbound")
    output = (
        Path(workspace).expanduser().absolute() / "evolution" / "producer-batches"
        / intent.journal_id / intent.output_directory
    )
    path = output / "producer-result.json"
    try:
        raw = _files.read_regular_file(path, intent.output_max_bytes)
        info = path.lstat()
    except (_files.BenchmarkFileError, OSError) as exc:
        raise ProducerLifecycleError("producer_lifecycle_envelope_unbound") from exc
    if (
        len(raw) != evidence.bytes or hashlib.sha256(raw).hexdigest() != evidence.sha256
        or (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns)
        != (evidence.device, evidence.inode, evidence.mtime_ns, evidence.ctime_ns)
    ):
        raise ProducerLifecycleError("producer_lifecycle_envelope_changed")
    try:
        envelope = parse_producer_envelope(json.loads(raw, object_pairs_hook=_unique_object))
    except (ProducerHandoffError, UnicodeError, ValueError, TypeError) as exc:
        raise ProducerLifecycleError("producer_lifecycle_envelope_invalid") from exc
    if (
        envelope.producer_id != intent.producer_id
        or envelope.producer_fingerprint != intent.producer_fingerprint
        or envelope.contract_sha256 != intent.contract_sha256
        or envelope.budget.get("requests") != receipt.request_count
    ):
        raise ProducerLifecycleError("producer_lifecycle_envelope_mismatch")
    return output, envelope


def run_producer_lifecycle(
    workspace: str | Path,
    *,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    producer_root: str | Path,
    contract: AlgorithmProblemContract,
    groups: tuple[BundleGroup, ...] | list[BundleGroup],
    evaluator_kind: str,
    evaluator_fingerprint: str,
    runner_fingerprint: str,
    dependency_sha256: str,
    environment_sha256: str,
    expected_run_id: str | None = None,
    expected_parent_task_id: str | None = None,
    expected_task_id: str | None = None,
) -> ProducerLifecyclePreparation:
    """Execute once, verify retained bytes, and prepare drafts without publication.

    This uses the cooperative direct-process path. It is deliberately not a
    production external-producer admission API until trusted bootstrap and a
    controller-owned request broker are integrated.
    """
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(contract, AlgorithmProblemContract):
        raise ProducerLifecycleError("producer_lifecycle_input_invalid")
    if contract.digest() != intent.contract_sha256 or (
        evaluator_kind != intent.evaluator_kind
        or evaluator_fingerprint != intent.evaluator_fingerprint
        or runner_fingerprint != intent.runner_fingerprint
        or dependency_sha256 != intent.dependency_sha256
        or environment_sha256 != intent.environment_sha256
    ):
        raise ProducerLifecycleError("producer_lifecycle_authority_mismatch")
    receipt = run_producer_process(
        workspace, intent=intent, attestation=attestation, producer_root=producer_root,
        expected_run_id=expected_run_id, expected_parent_task_id=expected_parent_task_id,
        expected_task_id=expected_task_id,
    )
    if receipt.status != "completed" or receipt.exit_code != 0 or not receipt.gate_released:
        raise ProducerLifecycleError("producer_lifecycle_process_incomplete")
    try:
        observed = recover_producer_process(workspace, journal_id=intent.journal_id)
    except Exception as exc:
        raise ProducerLifecycleError("producer_lifecycle_receipt_unbound") from exc
    if observed.get("receipt_sha256") != receipt.receipt_sha256:
        raise ProducerLifecycleError("producer_lifecycle_receipt_unbound")
    output, envelope = _read_bound_envelope(workspace, intent, receipt)
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
    return ProducerLifecyclePreparation(receipt, envelope, bundles, drafts, plan)


__all__ = ["ProducerLifecycleError", "ProducerLifecyclePreparation", "run_producer_lifecycle"]
