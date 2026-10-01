"""Read verified, already published native materials for future RSI verification.

Native launch/publication records do not bind an RSI request or memory snapshot. This module
therefore exposes detached evidence only; it is neither a solver gateway nor a learning verdict.
All underlying readers inspect existing local evidence without executing or repairing it.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, NoReturn

from . import _benchmark_files as files
from .algorithm import AlgorithmProblemContract
from .bundle_evolution import read_bundle_delivery_materials
from .candidate_bundle import parse_candidate_source_bundle
from .candidate_evaluation_spec import canonical_json, strict_json
from .evolution import Candidate, CandidateArchive
from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_scheduler import NativeTrustedProducerRecovery, recover_native_trusted_producer
from .producer_bundle_handoff import BundleGroup
from .producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    ProducerBundlePublicationJournal,
    parse_producer_bundle_publication_journal,
)
from .producer_bundle_receipts import (
    ProducerBundleEvaluationReceipt,
    ProducerBundleExecutionReceipt,
    build_producer_bundle_evaluation_receipt,
    build_producer_bundle_execution_receipt,
)
from .producer_bundle_recovery import resume_producer_bundle_publication
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent

_PROTOCOL = "lunar-rsi-native-retained-candidate-v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class NativeRetainedEvidenceError(ValueError):
    """Fixed public refusal codes; no producer-controlled error text is returned."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(reason: str) -> NoReturn:
    raise NativeRetainedEvidenceError("rsi_native_retained_" + reason)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return canonical_json(value, maximum=1024 * 1024)


@dataclass(frozen=True, slots=True)
class NativeRetainedCandidateEvidence:
    """Detached immutable material, with distinct native digest meanings.

    ``native_dependency_sha256`` is the native dependency pin, not an AgentLoop dependency
    manifest. The local evaluation report is provenance, not RSI memory or official acceptance.
    ``provenance_json`` describes native records and does not fabricate an Actor execution trace.
    Instances constructed by callers do not gain the reader's validation authority.
    """

    workspace: Path
    launch_id: str
    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    candidate_id: str
    bundle_id: str
    source_entrypoint: str
    contract_sha256: str
    evaluator_kind: str
    evaluator_fingerprint: str
    runner_fingerprint: str
    native_dependency_sha256: str
    environment_sha256: str
    publication_journal_sha256: str
    producer_execution_receipt_sha256: str
    candidate_publication_receipt_sha256: str
    candidate_execution_receipt_sha256: str
    candidate_completion_sha256: str
    candidate_evaluation_receipt_sha256: str
    candidate_evaluation_sha256: str
    source_bundle_sha256: str
    entrypoint_source_sha256: str
    process_terminal_sha256: str
    output_capture_sha256: str
    envelope_bytes_sha256: str
    portable_materials: tuple[tuple[str, bytes], ...]
    evaluation_report_json: bytes
    provenance_json: bytes

    def to_dict(self) -> dict[str, Any]:
        """Return fresh JSON metadata and material descriptors, without raw source bytes."""
        excluded = {"workspace", "portable_materials", "evaluation_report_json", "provenance_json"}
        result = {item.name: getattr(self, item.name) for item in fields(self) if item.name not in excluded}
        return {
            "schema_version": "1", "protocol": _PROTOCOL, "workspace": str(self.workspace),
            **result,
            "portable_materials": [
                {"path": path, "size": len(content), "sha256": _sha(content)}
                for path, content in self.portable_materials
            ],
            "evaluation_report": json.loads(self.evaluation_report_json),
            "provenance": json.loads(self.provenance_json),
        }

    def digest(self) -> str:
        return _sha(_canonical(self.to_dict()))


@dataclass(frozen=True, slots=True)
class _Snapshot:
    recovery: NativeTrustedProducerRecovery
    journal: ProducerBundlePublicationJournal
    slot: ProducerBundlePublicationCandidate
    candidate: Candidate
    execution: ProducerBundleExecutionReceipt
    evaluation: ProducerBundleEvaluationReceipt
    binding_json: bytes


def _workspace_identity(root: Path) -> tuple[int, int]:
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode):
        _fail("workspace_invalid")
    return info.st_dev, info.st_ino


def _inspect(
    root: Path, *, candidate_id: str, expected_journal_sha256: str,
    expected_producer_execution_receipt_sha256: str, recovery_pins: dict[str, Any],
) -> _Snapshot:
    recovery = recover_native_trusted_producer(root, **recovery_pins)
    if (recovery.status != "recovered" or recovery.receipt.status != "completed"
            or recovery.receipt.receipt_sha256 != expected_producer_execution_receipt_sha256
            or recovery.output.execution_receipt_sha256 != expected_producer_execution_receipt_sha256
            or recovery.output.output_capture_sha256 is None):
        _fail("producer_receipt_mismatch")
    intent = recovery_pins["intent"]
    batch = root / "evolution" / "producer-batches" / intent.journal_id
    journal = parse_producer_bundle_publication_journal(batch / "journal.published.json")
    if (journal.state != "published" or journal.digest() != expected_journal_sha256
            or journal.native_execution_receipt_sha256 != expected_producer_execution_receipt_sha256
            or journal.strategy != "population"):
        _fail("publication_mismatch")
    authority = (
        "journal_id", "run_id", "parent_task_id", "task_id", "contract_sha256",
        "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint",
        "dependency_sha256", "environment_sha256",
    )
    if any(getattr(journal, key) != getattr(intent, key) for key in authority):
        _fail("publication_authority_mismatch")
    publication = resume_producer_bundle_publication(root, recovery.output.admission_plan, journal)
    if (publication.status != "published" or publication.journal_sha256 != expected_journal_sha256
            or candidate_id not in publication.candidate_ids):
        _fail("candidate_not_published")
    slots = [item for item in journal.candidates if item.candidate_id == candidate_id]
    if len(slots) != 1 or slots[0].status != "admitted":
        _fail("candidate_not_admitted")
    slot = slots[0]
    # Published evidence must come from the final archive, never a surviving staged fallback.
    staged = batch / "stage" / "candidates" / candidate_id
    if staged.exists() or staged.is_symlink():
        _fail("publication_incomplete")
    archive = CandidateArchive(root, requested_strategy="population", read_only=True)
    records = archive.records()
    archive.validate_candidate_integrity(require_all=True, records=records)
    selected = [item for item in records if item.candidate_id == candidate_id]
    if len(selected) != 1:
        _fail("candidate_archive_mismatch")
    candidate = selected[0]
    evidence = candidate.bundle_evidence
    if (candidate.strategy != "population" or evidence is None
            or candidate.receipt_sha256 != slot.publication_receipt_sha256
            or evidence["bundle_sha256"] != slot.bundle_sha256
            or any(getattr(candidate, key) != getattr(slot, key) for key in
                   ("parent_id", "generation", "iteration", "island_id"))):
        _fail("candidate_archive_mismatch")
    bundles = [item for item in recovery.output.bundles if item.bundle_id == slot.bundle_id]
    if len(bundles) != 1 or bundles[0].bundle_sha256 != slot.bundle_sha256:
        _fail("candidate_source_binding_mismatch")
    native_authority = candidate.integrity
    if (native_authority is None
            or any(native_authority[key] != getattr(journal, key) for key in authority[4:])):
        _fail("candidate_authority_mismatch")
    execution = build_producer_bundle_execution_receipt(root, candidate)
    evaluation = build_producer_bundle_evaluation_receipt(root, candidate)
    if (execution.digest() != slot.execution_receipt_sha256
            or evaluation.digest() != slot.evaluation_receipt_sha256
            or execution.completion_sha256 != evidence["completion_sha256"]
            or evaluation.evaluation_sha256 != evidence["evaluation_sha256"]):
        _fail("candidate_receipt_mismatch")
    binding = {
        "journal": journal.to_dict(), "candidate": candidate.to_dict(),
        "producer_receipt": recovery.receipt.to_dict(),
        "execution": execution.to_dict(), "evaluation": evaluation.to_dict(),
        "process_terminal_sha256": recovery.output.process_terminal_sha256,
        "output_capture_sha256": recovery.output.output_capture_sha256,
        "envelope_bytes_sha256": recovery.output.envelope_bytes_sha256,
    }
    return _Snapshot(recovery, journal, slot, candidate, execution, evaluation, _canonical(binding))


def read_native_retained_candidate(
    workspace: str | Path, *, candidate_id: str, expected_journal_sha256: str,
    expected_producer_execution_receipt_sha256: str,
    intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact, contract: AlgorithmProblemContract,
    groups: Sequence[BundleGroup], evaluator_kind: str, evaluator_fingerprint: str,
    runner_fingerprint: str, dependency_sha256: str, environment_sha256: str,
    require_broker: bool = True,
) -> NativeRetainedCandidateEvidence:
    """Read exactly one already published candidate, without execution or RSI attribution.

    The original native recovery pins and both expected digests are mandatory. The caller must
    choose a candidate ID; this reader neither selects the current best nor substitutes another.
    Revalidate native execution, publication and archive after copying the portable materials.
    Returned material is detached supporting evidence, not an RSI completed result or verdict.
    """
    if (type(candidate_id) is not str or _IDENTIFIER.fullmatch(candidate_id) is None
            or type(expected_journal_sha256) is not str
            or _SHA256.fullmatch(expected_journal_sha256) is None
            or type(expected_producer_execution_receipt_sha256) is not str
            or _SHA256.fullmatch(expected_producer_execution_receipt_sha256) is None
            or not isinstance(intent, ProducerLaunchIntent)
            or not isinstance(attestation, ProducerLaunchAttestation)
            or not isinstance(artifact, NativeBootstrapArtifact)
            or not isinstance(contract, AlgorithmProblemContract)
            or isinstance(groups, (str, bytes)) or not isinstance(groups, Sequence)
            or any(not isinstance(group, BundleGroup) for group in groups)
            or type(require_broker) is not bool):
        _fail("input_invalid")
    try:
        root = files.absolute_path(workspace)
        identity = _workspace_identity(root)
        recovery_pins = {
            "intent": intent, "attestation": attestation, "artifact": artifact,
            "contract": contract, "groups": tuple(groups), "evaluator_kind": evaluator_kind,
            "evaluator_fingerprint": evaluator_fingerprint, "runner_fingerprint": runner_fingerprint,
            "dependency_sha256": dependency_sha256, "environment_sha256": environment_sha256,
            "require_broker": require_broker,
        }
        pins = {
            "candidate_id": candidate_id, "expected_journal_sha256": expected_journal_sha256,
            "expected_producer_execution_receipt_sha256": expected_producer_execution_receipt_sha256,
            "recovery_pins": recovery_pins,
        }
        before = _inspect(root, **pins)
        material = read_bundle_delivery_materials(root, before.candidate)
        portable = tuple(sorted(material.items()))
        bundle = parse_candidate_source_bundle(strict_json(material["source-bundle.json"]))
        source_paths = {"source/" + item.path for item in bundle.files}
        if (bundle.digest() != before.slot.bundle_sha256
                or source_paths != {path for path in material if path.startswith("source/")}
                or any(len(material["source/" + item.path]) != item.size
                       or _sha(material["source/" + item.path]) != item.sha256 for item in bundle.files)
                or _sha(material["source/" + bundle.entrypoint]) != before.candidate.source_sha256):
            _fail("materials_mismatch")
        after = _inspect(root, **pins)
        if before.binding_json != after.binding_json or _workspace_identity(root) != identity:
            _fail("evidence_changed")
        provenance = {
            "protocol": _PROTOCOL, "observation": "retained-native-publication",
            "rsi_request_attribution": "not_bound", "memory_authority": "none",
            "broker_coverage": before.recovery.output.request_coverage,
            "launch_intent_sha256": intent.digest(), "attestation_sha256": attestation.digest(),
            "bootstrap_artifact_sha256": artifact.artifact_sha256,
            "producer_id": intent.producer_id, "producer_fingerprint": intent.producer_fingerprint,
            "lineage": {key: getattr(before.candidate, key) for key in
                        ("parent_id", "generation", "iteration", "island_id")},
        }
        return NativeRetainedCandidateEvidence(
            workspace=root, launch_id=intent.launch_id, journal_id=intent.journal_id,
            run_id=intent.run_id, parent_task_id=intent.parent_task_id, task_id=intent.task_id,
            candidate_id=candidate_id, bundle_id=before.slot.bundle_id, source_entrypoint=bundle.entrypoint,
            contract_sha256=before.journal.contract_sha256, evaluator_kind=before.journal.evaluator_kind,
            evaluator_fingerprint=before.journal.evaluator_fingerprint,
            runner_fingerprint=before.journal.runner_fingerprint,
            native_dependency_sha256=before.journal.dependency_sha256,
            environment_sha256=before.journal.environment_sha256,
            publication_journal_sha256=expected_journal_sha256,
            producer_execution_receipt_sha256=expected_producer_execution_receipt_sha256,
            candidate_publication_receipt_sha256=before.candidate.receipt_sha256,
            candidate_execution_receipt_sha256=before.execution.digest(),
            candidate_completion_sha256=before.execution.completion_sha256,
            candidate_evaluation_receipt_sha256=before.evaluation.digest(),
            candidate_evaluation_sha256=before.evaluation.evaluation_sha256,
            source_bundle_sha256=bundle.digest(), entrypoint_source_sha256=before.candidate.source_sha256,
            process_terminal_sha256=before.recovery.output.process_terminal_sha256,
            output_capture_sha256=before.recovery.output.output_capture_sha256,
            envelope_bytes_sha256=before.recovery.output.envelope_bytes_sha256,
            portable_materials=portable, evaluation_report_json=_canonical(before.evaluation.report),
            provenance_json=_canonical(provenance),
        )
    except NativeRetainedEvidenceError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as exc:
        raise NativeRetainedEvidenceError("rsi_native_retained_evidence_invalid") from exc


__all__ = [
    "NativeRetainedCandidateEvidence", "NativeRetainedEvidenceError", "read_native_retained_candidate",
]
