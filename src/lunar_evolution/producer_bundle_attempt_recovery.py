"""Read-only inspection of an incomplete native producer draft."""

from __future__ import annotations

import hashlib
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from . import _benchmark_files as files
from .bundle_evolution import (
    _DRAFT_BINDING_NAME,
    _directory_identity,
    _draft_binding,
    derive_native_draft_run_id,
)
from .candidate_bundle import parse_candidate_source_bundle, verify_candidate_source_bundle
from .candidate_evaluation import _request_values, inspect_candidate_evaluation
from .candidate_evaluation_spec import canonical_json, strict_json
from .candidate_execution import admit_candidate_execution
from .candidate_execution_evidence import inspect_candidate_execution_record
from .candidate_process_interruption import build_process_interruption_receipt
from .candidate_workspace_plan import parse_candidate_workspace_plan
from .producer_bundle_admission import ProducerBundleAdmissionPlan
from .producer_bundle_intent import verify_producer_bundle_prepared_intent
from .producer_bundle_publication import ProducerBundlePublicationJournal


class NativeProducerAttemptRecoveryError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise NativeProducerAttemptRecoveryError(code)


def _read(path: Path, maximum: int = 256 * 1024) -> bytes:
    return files.read_regular_file(files.absolute_path(path), maximum)


def _json(path: Path, maximum: int = 256 * 1024) -> tuple[bytes, dict]:
    raw = _read(path, maximum)
    value = strict_json(raw, maximum=maximum)
    if not isinstance(value, dict) or canonical_json(value, maximum=maximum) != raw:
        _fail("producer_attempt_recovery_evidence_invalid")
    return raw, value


def _present(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail("producer_attempt_recovery_evidence_changed")
    return True


def _interruption(path: Path, request_sha256: str, stage: str) -> tuple[str, str]:
    _raw, value = _json(path, 8192)
    fields = {
        "reason", "stage", "pid", "pgid", "exit_code", "cleanup", "ownership_release", "observed_ms",
    }
    if set(value) != fields | {"protocol", "request_sha256", "receipt_sha256"}:
        _fail("producer_attempt_recovery_interruption_invalid")
    try:
        rebuilt = build_process_interruption_receipt(
            {key: value[key] for key in fields}, request_sha256=request_sha256, stage=stage,
        )
    except ValueError as exc:
        raise NativeProducerAttemptRecoveryError("producer_attempt_recovery_interruption_invalid") from exc
    if value != rebuilt:
        _fail("producer_attempt_recovery_interruption_invalid")
    return value["reason"], value["cleanup"]


@dataclass(frozen=True, slots=True)
class NativeProducerUnknownAttempt:
    candidate_id: str
    run_id: str
    stage: str
    reason: str
    cleanup: str
    status: str = "unknown"


def inspect_native_producer_bundle_unknown_attempt(
    workspace: str | Path,
    plan: ProducerBundleAdmissionPlan,
    journal: ProducerBundlePublicationJournal,
    *,
    candidate_id: str,
) -> NativeProducerUnknownAttempt:
    """Inspect a retained incomplete attempt without granting retry or publication authority."""
    if not isinstance(plan, ProducerBundleAdmissionPlan) or not isinstance(journal, ProducerBundlePublicationJournal):
        _fail("producer_attempt_recovery_request_invalid")
    if journal.state != "prepared" or journal.admission_sha256 != plan.digest():
        _fail("producer_attempt_recovery_request_invalid")
    if not isinstance(candidate_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", candidate_id) is None:
        _fail("producer_attempt_recovery_candidate_invalid")
    candidates = [
        (ordinal, item) for ordinal, item in enumerate(journal.candidates)
        if item.candidate_id == candidate_id
    ]
    if len(candidates) != 1:
        _fail("producer_attempt_recovery_candidate_invalid")
    ordinal, candidate = candidates[0]
    if (ordinal >= len(plan.bundles) or candidate.bundle_id != plan.bundles[ordinal].bundle_id
            or candidate.bundle_sha256 != plan.bundles[ordinal].bundle_sha256):
        _fail("producer_attempt_recovery_request_invalid")
    try:
        root = files.absolute_path(workspace)
        verify_producer_bundle_prepared_intent(root, journal)
        batch = root / "evolution" / "producer-batches" / journal.journal_id
        if _present(batch / "journal.json"):
            _fail("producer_attempt_recovery_stage_advanced")
        draft_root = batch / "native-drafts" / candidate_id
        source = draft_root / "source"
        run_id = derive_native_draft_run_id(journal.journal_id, candidate_id, candidate.bundle_sha256)
        run = root / "evolution" / "bundle-attempts" / (".bundle-run-" + run_id)
        draft_identity = _directory_identity(draft_root)
        source_identity = _directory_identity(source)
        run_identity = _directory_identity(run)
        _binding_bytes, binding = _json(draft_root / _DRAFT_BINDING_NAME, 16 * 1024)
        _manifest_bytes, source_manifest = _json(source / "bundle-manifest.json", 256 * 1024)
        bundle = parse_candidate_source_bundle(source_manifest)
        if bundle.digest() != candidate.bundle_sha256:
            _fail("producer_attempt_recovery_evidence_changed")
        verify_candidate_source_bundle(
            bundle, source_root=source, contract_sha256=journal.contract_sha256,
            expected_bundle_sha256=candidate.bundle_sha256,
        )
        _plan_bytes, plan_value = _json(run / "plan.json")
        execution_plan = parse_candidate_workspace_plan(plan_value)
        admission_bytes = _read(run / "admission.json")
        admission = admit_candidate_execution(
            admission_bytes, plan=execution_plan,
            expected_plan_sha256=execution_plan.digest(), expected_bundle_sha256=bundle.digest(),
            expected_contract_sha256=journal.contract_sha256,
        ).admission
        expected = _draft_binding(
            journal_id=journal.journal_id, candidate_id=candidate_id, run_id=run_id,
            bundle_id=candidate.bundle_id, bundle_sha256=bundle.digest(), ordinal=ordinal,
            parent_id=candidate.parent_id, generation=candidate.generation,
            iteration=candidate.iteration, island_id=candidate.island_id,
            source_root=source.relative_to(root).as_posix(), source_identity=source_identity,
            run_root=run.relative_to(root).as_posix(), run_identity=run_identity,
            plan_sha256=execution_plan.digest(), admission_sha256=admission.digest(),
            journal_sha256=journal.digest(),
        )
        if binding != expected:
            _fail("producer_attempt_recovery_evidence_changed")

        def recheck() -> None:
            verify_producer_bundle_prepared_intent(root, journal)
            if (_present(batch / "journal.json")
                    or _directory_identity(draft_root) != draft_identity
                    or _directory_identity(source) != source_identity
                    or _directory_identity(run) != run_identity
                    or _read(draft_root / _DRAFT_BINDING_NAME, 16 * 1024) != _binding_bytes
                    or _read(source / "bundle-manifest.json") != _manifest_bytes
                    or _read(run / "plan.json") != _plan_bytes
                    or _read(run / "admission.json") != admission_bytes):
                _fail("producer_attempt_recovery_evidence_changed")
            verify_candidate_source_bundle(
                bundle, source_root=source, contract_sha256=journal.contract_sha256,
                expected_bundle_sha256=candidate.bundle_sha256,
            )
        attempt = run / "attempt"
        record = inspect_candidate_execution_record(
            attempt, plan=execution_plan, admission=admission,
            expected_admission_sha256=admission.digest(),
            expected_plan_sha256=execution_plan.digest(),
            expected_bundle_sha256=bundle.digest(),
            expected_contract_sha256=journal.contract_sha256,
        )
        if record.status != "recorded":
            interrupted = attempt / "interrupted.json"
            reason, cleanup = ("missing_terminal_evidence", "unknown")
            if _present(interrupted):
                if record.launch_intent_sha256 is None:
                    _fail("producer_attempt_recovery_interruption_invalid")
                reason, cleanup = _interruption(
                    interrupted, record.launch_intent_sha256, "candidate_execution",
                )
            recheck()
            return NativeProducerUnknownAttempt(candidate_id, run_id, "candidate_execution", reason, cleanup)
        if record.to_dict()["runner_result"]["status"] != "succeeded":
            _fail("producer_attempt_recovery_known_terminal")
        evaluations = run / "evaluations"
        _directory_identity(evaluations)
        entries = list(evaluations.iterdir())
        if not entries:
            recheck()
            return NativeProducerUnknownAttempt(
                candidate_id, run_id, "evaluation", "missing_terminal_evidence", "unknown",
            )
        if len(entries) != 1 or re.fullmatch(r"\.candidate-evaluation-[0-9a-f]{24}", entries[0].name) is None:
            _fail("producer_attempt_recovery_evaluation_mapping_invalid")
        evaluation = entries[0]
        _directory_identity(evaluation)
        request_raw, request = _json(evaluation / "request.json")
        expected_binding = {
            "workspace_plan_sha256": execution_plan.digest(),
            "admission_sha256": admission.digest(),
            "bundle_sha256": bundle.digest(),
            "contract_sha256": journal.contract_sha256,
            "source_file_table_sha256": execution_plan.file_table_sha256,
            "input_file_table_sha256": hashlib.sha256(
                canonical_json([item.to_dict() for item in admission.inputs])
            ).hexdigest(),
            "launch_intent_sha256": record.launch_intent_sha256,
            "completion_sha256": record.completion_sha256,
            "evaluator_fingerprint": admission.evaluator.fingerprint,
            "output_contract_sha256": admission.output_contract_sha256,
        }
        _request_values(request)
        if request.get("binding") != expected_binding:
            _fail("producer_attempt_recovery_evidence_changed")
        interrupted = evaluation / "interrupted.json"
        if _present(interrupted):
            if _present(evaluation / "evaluation.json"):
                _fail("producer_attempt_recovery_interruption_invalid")
            reason, cleanup = _interruption(interrupted, hashlib.sha256(request_raw).hexdigest(), "evaluation")
        elif _present(evaluation / "evaluation.json"):
            inspect_candidate_evaluation(evaluation)
            _fail("producer_attempt_recovery_known_terminal")
        else:
            reason, cleanup = "missing_terminal_evidence", "unknown"
        if _read(evaluation / "request.json") != request_raw:
            _fail("producer_attempt_recovery_evidence_changed")
        recheck()
        return NativeProducerUnknownAttempt(candidate_id, run_id, "evaluation", reason, cleanup)
    except NativeProducerAttemptRecoveryError:
        raise
    except Exception as exc:
        raise NativeProducerAttemptRecoveryError("producer_attempt_recovery_evidence_changed") from exc


__all__ = [
    "NativeProducerAttemptRecoveryError",
    "NativeProducerUnknownAttempt",
    "inspect_native_producer_bundle_unknown_attempt",
]
