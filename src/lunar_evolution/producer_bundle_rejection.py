"""Durable terminal inspection for a natively evaluated, entirely rejected batch.

Only local evidence is retained.  The terminal journal is written last and no population
archive, active state, final candidate tree, or publication marker is changed.  Partial writes
require recovery; an exact completed retry is read-only and never invokes an evaluator.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ._candidate_workspace_io import DirectoryChain
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .candidate_bundle import parse_candidate_source_bundle, verify_candidate_source_bundle
from .candidate_evaluation import inspect_candidate_evaluation
from .candidate_evaluation_spec import strict_json
from .candidate_execution import admit_candidate_execution
from .candidate_execution_evidence import inspect_candidate_execution_record
from .candidate_workspace_plan import parse_candidate_workspace_plan
from .evolution import MAX_ARCHIVE_BYTES, MAX_STATE_BYTES, CandidateIntegrityAuthority
from .producer_bundle_intent import verify_producer_bundle_prepared_intent
from .producer_bundle_preflight import (
    ProducerBundlePreflightReceipt,
    _authority_digest,
    parse_producer_bundle_preflight_receipt,
)
from .producer_bundle_publication import (
    MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES,
    ProducerBundlePublicationJournal,
    parse_producer_bundle_publication_journal,
)
from .producer_bundle_receipts import (
    ProducerBundleEvaluationReceipt,
    ProducerBundleExecutionReceipt,
    _collect_retained_evidence,
    build_native_producer_bundle_evaluation_receipt,
    build_native_producer_bundle_execution_receipt,
    build_native_producer_bundle_publication_artifact,
)
from .producer_bundle_staging import (
    _batch,
    _canonical,
    _confined,
    _directory,
    _file_descriptor,
    _fsync_dir,
    _locked,
    _present,
    _pretty,
    _read,
    _regular,
    _workspace,
    _write_new,
    verify_native_publication_intent,
)

_PROTOCOL = "lunar-producer-bundle-all-rejected-v1"
_MAX_BYTES = MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES
_EVIDENCE_FIELDS = {"candidate_id", "execution_receipt", "evaluation_receipt", "retained_evidence"}
_MANIFEST_FIELDS = {
    "schema_version", "protocol", "journal_id", "prepared_journal_sha256", "preflight",
    "candidate_ids", "entries", "archive_after_sha256", "state_after_sha256", "status",
    "terminal_marker_sha256",
}


class ProducerBundleRejectionError(ValueError):
    """A fixed error code for an absent, partial, or changed rejection decision."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ProducerBundleRejectionError(code)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _prepared(journal: ProducerBundlePublicationJournal) -> ProducerBundlePublicationJournal:
    if not isinstance(journal, ProducerBundlePublicationJournal):
        _fail("producer_bundle_rejection_journal_invalid")
    normalized = parse_producer_bundle_publication_journal(journal.to_dict())
    if normalized.state == "prepared":
        return normalized
    if normalized.state != "all_rejected":
        _fail("producer_bundle_rejection_journal_state_invalid")
    return replace(
        normalized, state="prepared", publication_phase="preflight", journal_sha256=None,
        terminal_marker_sha256=None, archive_after_sha256=None, state_after_sha256=None,
        candidates=tuple(replace(
            item, status="planned", execution_receipt_sha256=None,
            evaluation_receipt_sha256=None, publication_receipt_sha256=None,
        ) for item in normalized.candidates),
    )


def _preflight(
    value: object, journal: ProducerBundlePublicationJournal,
) -> ProducerBundlePreflightReceipt:
    receipt = parse_producer_bundle_preflight_receipt(value)
    if (
        receipt.journal_id != journal.journal_id or receipt.run_id != journal.run_id
        or receipt.task_id != journal.task_id or receipt.plan_sha256 != journal.admission_sha256
        or receipt.archive_prefix_sha256 != journal.archive_prefix_sha256
        or receipt.base_archive_sha256 != journal.base_archive_sha256
        or receipt.base_state_sha256 != journal.base_state_sha256
        or receipt.authority_sha256 != _authority_digest(journal)
        or receipt.candidate_ids != tuple(item.candidate_id for item in journal.candidates)
    ):
        _fail("producer_bundle_rejection_preflight_mismatch")
    return receipt


def _prefix(root: Path, journal: ProducerBundlePublicationJournal) -> None:
    evolution = root / "evolution"
    if _present(evolution / "producer-publication.json"):
        _fail("producer_bundle_rejection_recovery_required")
    archive_path, state_path = evolution / "archive.jsonl", evolution / "state.json"
    archive = _read(archive_path, MAX_ARCHIVE_BYTES) if _present(archive_path) else b""
    state = _read(state_path, MAX_STATE_BYTES) if _present(state_path) else b""
    if _sha(archive) != journal.base_archive_sha256 or _sha(state) != journal.base_state_sha256:
        _fail("producer_bundle_rejection_prefix_drift")
    for item in journal.candidates:
        if _present(_confined(root, f"evolution/candidates/{item.candidate_id}")):
            _fail("producer_bundle_rejection_candidate_conflict")


def _json(path: Path) -> dict[str, Any]:
    _regular(path)
    content = _read(path, _MAX_BYTES)
    value = strict_json(content, _MAX_BYTES)
    if not isinstance(value, dict) or _pretty(value, _MAX_BYTES) != content:
        _fail("producer_bundle_rejection_evidence_invalid")
    return value


def _verify_receipts(
    root: Path, journal: ProducerBundlePublicationJournal, item: object, value: object,
) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != _EVIDENCE_FIELDS:
        _fail("producer_bundle_rejection_evidence_invalid")
    execution = ProducerBundleExecutionReceipt.from_dict(value["execution_receipt"])
    evaluation = ProducerBundleEvaluationReceipt.from_dict(value["evaluation_receipt"])
    if (
        value["candidate_id"] != item.candidate_id
        or execution.candidate_id != item.candidate_id
        or evaluation.candidate_id != item.candidate_id
        or execution.bundle_sha256 != item.bundle_sha256
        or evaluation.bundle_sha256 != item.bundle_sha256
        or execution.plan_sha256 != evaluation.plan_sha256
        or execution.admission_sha256 != evaluation.admission_sha256
        or execution.completion_sha256 != evaluation.completion_sha256
        or evaluation.python_handoff_sha256 != journal.python_handoff_sha256
        or evaluation.report["validity"] != 0
    ):
        _fail("producer_bundle_rejection_adjudication_invalid")
    evidence = verify_native_publication_intent(
        root, journal, item.candidate_id, value["retained_evidence"],
    )
    if evidence is None:
        _fail("producer_bundle_rejection_evidence_invalid")
    binding_path = root / "evolution" / "producer-batches" / journal.journal_id / "native-drafts" / item.candidate_id / "draft-binding.json"
    binding = strict_json(_read(binding_path, 16 * 1024), 16 * 1024)
    if (
        binding.get("plan_sha256") != execution.plan_sha256
        or binding.get("admission_sha256") != execution.admission_sha256
    ):
        _fail("producer_bundle_rejection_evidence_invalid")
    # Portable receipt digests are declarations. Rebuild every receipt field from the retained
    # local records so recomputing a portable digest cannot change the terminal adjudication.
    from .bundle_evolution import _draft_binding, _runner_digest, derive_native_draft_run_id

    source_relative = f"evolution/producer-batches/{journal.journal_id}/native-drafts/{item.candidate_id}/source"
    run_id = derive_native_draft_run_id(journal.journal_id, item.candidate_id, item.bundle_sha256)
    run_relative = f"evolution/bundle-attempts/.bundle-run-{run_id}"
    source_root, run_root = _confined(root, source_relative), _confined(root, run_relative)
    bundle = parse_candidate_source_bundle(source_root / "bundle-manifest.json")
    verify_candidate_source_bundle(
        bundle, source_root=source_root, contract_sha256=journal.contract_sha256,
        expected_bundle_sha256=item.bundle_sha256,
    )
    plan = parse_candidate_workspace_plan(run_root / "plan.json")
    admission = admit_candidate_execution(
        _read(run_root / "admission.json", _MAX_BYTES), plan=plan,
        expected_plan_sha256=plan.digest(), expected_bundle_sha256=bundle.digest(),
        expected_contract_sha256=journal.contract_sha256,
    ).admission
    if (
        admission.evaluator.kind != journal.evaluator_kind
        or admission.evaluator.fingerprint != journal.evaluator_fingerprint
        or admission.dependency_sha256 != journal.dependency_sha256
        or admission.environment_sha256 != journal.environment_sha256
        or _runner_digest(plan, admission.inputs) != journal.runner_fingerprint
    ):
        _fail("producer_bundle_rejection_authority_mismatch")
    source_stat, run_stat = os.lstat(source_root), os.lstat(run_root)
    expected_binding = _draft_binding(
        journal_id=journal.journal_id, candidate_id=item.candidate_id, run_id=run_id,
        bundle_id=item.bundle_id, bundle_sha256=item.bundle_sha256,
        ordinal=next(index for index, candidate in enumerate(journal.candidates) if candidate == item),
        parent_id=item.parent_id, generation=item.generation, iteration=item.iteration,
        island_id=item.island_id, source_root=source_relative,
        source_identity=(source_stat.st_dev, source_stat.st_ino), run_root=run_relative,
        run_identity=(run_stat.st_dev, run_stat.st_ino), plan_sha256=plan.digest(),
        admission_sha256=admission.digest(), journal_sha256=journal.digest(),
    )
    if binding != expected_binding:
        _fail("producer_bundle_rejection_evidence_invalid")
    recorded = inspect_candidate_execution_record(
        run_root / "attempt", plan=plan, admission=admission,
        expected_admission_sha256=admission.digest(), expected_plan_sha256=plan.digest(),
        expected_bundle_sha256=bundle.digest(), expected_contract_sha256=journal.contract_sha256,
    )
    evaluations = tuple((run_root / "evaluations").iterdir())
    if (len(evaluations) != 1 or evaluations[0].is_symlink() or not evaluations[0].is_dir()
            or re.fullmatch(r"\.candidate-evaluation-[0-9a-f]{24}", evaluations[0].name) is None):
        _fail("producer_bundle_rejection_evidence_invalid")
    evaluated = inspect_candidate_evaluation(evaluations[0])
    expected_evaluation_binding = {
        "workspace_plan_sha256": plan.digest(), "admission_sha256": admission.digest(),
        "bundle_sha256": bundle.digest(), "contract_sha256": journal.contract_sha256,
        "source_file_table_sha256": plan.file_table_sha256,
        "input_file_table_sha256": _sha(_canonical([item.to_dict() for item in admission.inputs])),
        "launch_intent_sha256": recorded.launch_intent_sha256,
        "completion_sha256": recorded.completion_sha256,
        "evaluator_fingerprint": journal.evaluator_fingerprint,
        "output_contract_sha256": admission.output_contract_sha256,
    }
    if evaluated.to_dict()["binding"] != expected_evaluation_binding:
        _fail("producer_bundle_rejection_evidence_invalid")
    inspected = SimpleNamespace(
        candidate_id=item.candidate_id, bundle=bundle, plan=plan, admission=admission,
        execution=recorded, evaluation=evaluated,
    )
    if (
        build_native_producer_bundle_execution_receipt(inspected) != execution
        or build_native_producer_bundle_evaluation_receipt(
            inspected, python_handoff_sha256=journal.python_handoff_sha256,
        ) != evaluation
        or _collect_retained_evidence(root, (
            source_root, run_root, binding_path,
            root / "evolution" / "producer-batches" / journal.journal_id / "journal.prepared.json",
        )) != evidence
    ):
        _fail("producer_bundle_rejection_receipt_mismatch")
    return execution.digest(), evaluation.digest()


def _inspect(
    root: Path, batch: Path, journal: ProducerBundlePublicationJournal,
    preflight: ProducerBundlePreflightReceipt | None,
) -> ProducerBundlePublicationJournal | None:
    prepared = _prepared(journal)
    terminal_path, evidence_path = batch / "journal.json", batch / "rejections.json"
    present = tuple(_present(path) for path in (terminal_path, evidence_path, batch / "rejections"))
    if not any(present):
        return None
    if not all(present):
        _fail("producer_bundle_rejection_recovery_required")
    durable = parse_producer_bundle_publication_journal(terminal_path)
    if durable.state != "all_rejected" or _prepared(durable) != prepared:
        _fail("producer_bundle_rejection_journal_mismatch")
    if journal.state == "all_rejected" and journal != durable:
        _fail("producer_bundle_rejection_journal_mismatch")
    if any(_present(batch / name) for name in (
        "stage", "manifest.json", "journal.staged.json", "journal.published.json", "terminal.json",
    )):
        _fail("producer_bundle_rejection_recovery_required")
    verify_producer_bundle_prepared_intent(root, prepared)
    _prefix(root, prepared)
    manifest = _json(evidence_path)
    if set(manifest) != _MANIFEST_FIELDS:
        _fail("producer_bundle_rejection_terminal_invalid")
    payload = {key: value for key, value in manifest.items() if key != "terminal_marker_sha256"}
    if (
        manifest["schema_version"] != "1" or manifest["protocol"] != _PROTOCOL
        or manifest["status"] != "all_rejected" or manifest["journal_id"] != journal.journal_id
        or manifest["prepared_journal_sha256"] != prepared.digest()
        or manifest["terminal_marker_sha256"] != _sha(_canonical(payload))
        or manifest["terminal_marker_sha256"] != durable.terminal_marker_sha256
        or manifest["archive_after_sha256"] != prepared.base_archive_sha256
        or manifest["state_after_sha256"] != prepared.base_state_sha256
        or manifest["candidate_ids"] != [item.candidate_id for item in prepared.candidates]
    ):
        _fail("producer_bundle_rejection_terminal_mismatch")
    receipt = _preflight(manifest["preflight"], prepared)
    if preflight is not None and receipt != _preflight(preflight.to_dict(), prepared):
        _fail("producer_bundle_rejection_preflight_mismatch")
    entries = manifest["entries"]
    if not isinstance(entries, list) or len(entries) != len(prepared.candidates):
        _fail("producer_bundle_rejection_evidence_invalid")
    _directory(batch / "rejections")
    expected_names = {item.candidate_id + ".json" for item in prepared.candidates}
    if {path.name for path in (batch / "rejections").iterdir()} != expected_names:
        _fail("producer_bundle_rejection_evidence_invalid")
    for candidate, terminal_candidate, entry in zip(prepared.candidates, durable.candidates, entries, strict=True):
        relative = "rejections/" + candidate.candidate_id + ".json"
        path = _confined(batch, relative)
        raw = _read(path, _MAX_BYTES)
        if entry != _file_descriptor(path, relative, raw):
            _fail("producer_bundle_rejection_evidence_changed")
        execution, evaluation = _verify_receipts(root, prepared, candidate, _json(path))
        if (terminal_candidate.execution_receipt_sha256 != execution
                or terminal_candidate.evaluation_receipt_sha256 != evaluation):
            _fail("producer_bundle_rejection_receipt_mismatch")
    return durable


def inspect_producer_bundle_all_rejected(
    workspace: str | Path, journal: ProducerBundlePublicationJournal,
    *, preflight: ProducerBundlePreflightReceipt | None = None,
    checkpoint: Callable[[str], object] | None = None,
) -> ProducerBundlePublicationJournal | None:
    """Inspect one exact terminal rejection, or return ``None`` before any terminal write."""
    try:
        root = _workspace(workspace)
        batch = _batch(root, journal.journal_id)
        with _locked(root, checkpoint=checkpoint):
            if checkpoint is not None:
                checkpoint("producer_rejection_inspect_locked")
            result = _inspect(root, batch, journal, preflight)
            if checkpoint is not None:
                checkpoint("producer_rejection_inspected")
            return result
    except (ProducerBundleRejectionError, SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except Exception as exc:
        raise ProducerBundleRejectionError("producer_bundle_rejection_evidence_invalid") from exc


def finalize_producer_bundle_all_rejected(
    workspace: str | Path, journal: ProducerBundlePublicationJournal,
    preflight: ProducerBundlePreflightReceipt, evaluations: Sequence[object],
    *, authority: CandidateIntegrityAuthority,
    checkpoint: Callable[[str], object] | None = None,
) -> ProducerBundlePublicationJournal:
    """Retain locally verified rejection evidence and write its terminal journal last."""
    try:
        prepared = _prepared(journal)
        if journal != prepared or not isinstance(preflight, ProducerBundlePreflightReceipt):
            _fail("producer_bundle_rejection_input_invalid")
        receipt = _preflight(preflight.to_dict(), prepared)
        if isinstance(evaluations, (str, bytes)) or len(evaluations) != len(prepared.candidates):
            _fail("producer_bundle_rejection_adjudication_invalid")
        root = _workspace(workspace)
        batch = _batch(root, prepared.journal_id)
        chain = DirectoryChain(batch, "producer_bundle_rejection_path_invalid")
        try:
            with _locked(root, checkpoint=checkpoint):
                chain.check()
                if checkpoint is not None:
                    checkpoint("all_rejected")
                existing = _inspect(root, batch, prepared, receipt)
                if existing is not None:
                    if checkpoint is not None:
                        checkpoint("all_rejected")
                    return existing
                verify_producer_bundle_prepared_intent(root, prepared)
                _prefix(root, prepared)
                evidence: list[dict[str, Any]] = []
                terminal_candidates = []
                for ordinal, (candidate, result) in enumerate(zip(prepared.candidates, evaluations, strict=True)):
                    if (
                        result.candidate_id != candidate.candidate_id or result.ordinal != ordinal
                        or result.journal_sha256 != prepared.digest() or result.report.validity != 0
                    ):
                        _fail("producer_bundle_rejection_adjudication_invalid")
                    artifact = build_native_producer_bundle_publication_artifact(
                        root, result, authority=authority,
                        python_handoff_sha256=prepared.python_handoff_sha256,
                    )
                    value = {
                        "candidate_id": candidate.candidate_id,
                        "execution_receipt": artifact.execution_receipt,
                        "evaluation_receipt": artifact.evaluation_receipt,
                        "retained_evidence": artifact.retained_evidence,
                    }
                    execution, evaluation = _verify_receipts(root, prepared, candidate, value)
                    evidence.append(value)
                    terminal_candidates.append(replace(
                        candidate, status="rejected", execution_receipt_sha256=execution,
                        evaluation_receipt_sha256=evaluation,
                    ))
                chain.check()
                (batch / "rejections").mkdir(mode=0o700)
                _fsync_dir(batch)
                entries = []
                for candidate, value in zip(prepared.candidates, evidence, strict=True):
                    relative = "rejections/" + candidate.candidate_id + ".json"
                    content = _pretty(value, _MAX_BYTES)
                    _write_new(batch / relative, content, maximum=_MAX_BYTES)
                    entries.append(_file_descriptor(batch / relative, relative, content))
                payload = {
                    "schema_version": "1", "protocol": _PROTOCOL,
                    "journal_id": prepared.journal_id, "prepared_journal_sha256": prepared.digest(),
                    "preflight": receipt.to_dict(), "candidate_ids": list(receipt.candidate_ids),
                    "entries": entries, "archive_after_sha256": prepared.base_archive_sha256,
                    "state_after_sha256": prepared.base_state_sha256, "status": "all_rejected",
                }
                terminal_sha = _sha(_canonical(payload))
                _write_new(batch / "rejections.json", _pretty({
                    **payload, "terminal_marker_sha256": terminal_sha,
                }, _MAX_BYTES), maximum=_MAX_BYTES)
                terminal = replace(
                    prepared, candidates=tuple(terminal_candidates), state="all_rejected",
                    publication_phase="committed", terminal_marker_sha256=terminal_sha,
                    archive_after_sha256=prepared.base_archive_sha256,
                    state_after_sha256=prepared.base_state_sha256, journal_sha256=None,
                )
                if checkpoint is not None:
                    checkpoint("all_rejected")
                _write_new(batch / "journal.json", _pretty(terminal.to_dict(), _MAX_BYTES), maximum=_MAX_BYTES)
                chain.check()
                inspected = _inspect(root, batch, terminal, receipt)
                if inspected != terminal:
                    _fail("producer_bundle_rejection_terminal_mismatch")
                return terminal
        finally:
            chain.close()
    except (ProducerBundleRejectionError, SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except Exception as exc:
        raise ProducerBundleRejectionError("producer_bundle_rejection_evidence_invalid") from exc


__all__ = [
    "ProducerBundleRejectionError", "finalize_producer_bundle_all_rejected",
    "inspect_producer_bundle_all_rejected",
]
