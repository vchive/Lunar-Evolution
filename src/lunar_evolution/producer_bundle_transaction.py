"""Native producer-bundle publication transaction orchestration.

The producer adapters only provide material.  This module is the small, provider-free bridge
that evaluates those materials with Lunar's native multi-file pipeline and publishes the admitted
subset through Feature 153's durable staging protocol.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import _benchmark_files as _files
from .automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from .bundle_evolution import NativeDraftEvaluationResult
from .evolution import Candidate, CandidateArchive, CandidateDraft, PopulationStrategy
from .producer_bundle_admission import (
    ProducerBundleAdmissionPlan,
    build_producer_bundle_admission_plan,
)
from .producer_bundle_control import (
    bind_native_producer_bundle_control,
    native_producer_bundle_budget_sha256,
)
from .producer_bundle_intent import (
    persist_producer_bundle_prepared_intent,
    verify_producer_bundle_prepared_intent,
)
from .producer_bundle_population import ProducerBundleDraft
from .producer_bundle_preflight import (
    compute_archive_prefix_digest,
    derive_producer_bundle_candidate_id,
    preflight_producer_bundle_publication,
)
from .producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    ProducerBundlePublicationJournal,
    build_producer_bundle_publication_journal,
    parse_producer_bundle_publication_journal,
)
from .producer_bundle_receipts import build_native_producer_bundle_publication_artifact
from .producer_bundle_rejection import (
    finalize_producer_bundle_all_rejected,
    inspect_producer_bundle_all_rejected,
)
from .producer_bundle_staging import (
    ProducerBundlePublicationArtifact,
    ProducerBundlePublicationManifest,
    commit_producer_bundle_publication,
    stage_producer_bundle_publication,
)


class NativeProducerBundleTransactionError(RuntimeError):
    """A fixed transaction boundary error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as exc:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_canonical_invalid") from exc


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_optional(path: Path) -> bytes:
    if not path.exists():
        return b""
    try:
        return _files.read_regular_file(_files.absolute_path(path), 32 * 1024 * 1024)
    except Exception as exc:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_prefix_invalid") from exc


def _read_state(workspace: Path) -> tuple[bytes, dict[str, Any]]:
    raw = _read_optional(workspace / "evolution" / "state.json")
    if not raw:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_state_missing")
    try:
        state = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_state_invalid") from exc
    if not isinstance(state, dict) or state.get("strategy") != "population":
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_state_invalid")
    return raw, state


def _state_prefix(workspace: Path, archive: bytes, state_bytes: bytes, state: Mapping[str, Any]) -> str:
    config = state.get("config")
    active_ids = state.get("active_ids")
    if not isinstance(config, dict) or not isinstance(active_ids, dict):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_state_invalid")
    seed_commit = workspace / "evolution" / "seed-commit.json"
    seed_sha = _sha(_read_optional(seed_commit)) if seed_commit.exists() else None
    return compute_archive_prefix_digest(
        _sha(archive), _sha(state_bytes),
        seed_commit_sha256=seed_sha,
        strategy_config_sha256=_sha(_canonical(config)),
        active_ids_sha256=_sha(_canonical(active_ids)),
    )


def _candidate_from_artifact(artifact: ProducerBundlePublicationArtifact) -> Candidate:
    try:
        return Candidate.from_dict(dict(artifact.record))
    except Exception as exc:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_candidate_invalid") from exc


def _records_from_archive(archive: bytes) -> list[Candidate]:
    records: list[Candidate] = []
    for line in archive.splitlines():
        if not line:
            continue
        try:
            records.append(Candidate.from_dict(json.loads(line.decode("utf-8"))))
        except Exception as exc:
            raise NativeProducerBundleTransactionError("producer_bundle_transaction_archive_invalid") from exc
    return records


def _snapshot_drafts(
    drafts: Sequence[ProducerBundleDraft], plan: ProducerBundleAdmissionPlan,
) -> tuple[ProducerBundleDraft, ...]:
    """Detach mutable inputs and verify the complete batch before its first side effect."""
    try:
        frozen = tuple(replace(item, draft=CandidateDraft(
            item.draft.source, item.draft.filename,
            json.loads(_canonical(item.draft.metadata)), dict(item.draft.source_files),
        )) for item in drafts)
        rebuilt = build_producer_bundle_admission_plan(
            frozen, contract_sha256=plan.contract_sha256,
            evaluator_kind=plan.evaluator_kind, evaluator_fingerprint=plan.evaluator_fingerprint,
            runner_fingerprint=plan.runner_fingerprint, dependency_sha256=plan.dependency_sha256,
            environment_sha256=plan.environment_sha256,
        )
        if rebuilt.digest() != plan.digest():
            raise ValueError("draft plan mismatch")
        return frozen
    except Exception as exc:
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_drafts_invalid"
        ) from exc


def _ensure_initial_population_window(
    state: Mapping[str, Any],
    records: Sequence[Candidate],
    strategy: PopulationStrategy,
) -> None:
    outcome_fields = {
        "outcome_schema_version", "outcome_start_iteration", "outcome_watermark",
        "outcome_watermark_sha256", "outcome_archive_baseline_sha256",
        "pending_offspring", "failed_offspring_iteration", "failed_offspring_sha256",
    }
    iteration = state.get("iteration")
    if (
        isinstance(iteration, bool)
        or iteration != 0
        or state.get("status") != "running"
        or "seed_admission" in state
        or outcome_fields.intersection(state)
        or strategy.archive.offspring_outcomes()
        or any(candidate.iteration != 0 for candidate in records)
        or any("seed_handoff" in candidate.metadata for candidate in records)
        or state.get("producer_admissions") is not None
        or any("producer_bundle" in candidate.metadata for candidate in records)
    ):
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_population_history_unsupported"
        )


def derive_population_state_after(
    base_state: Mapping[str, Any],
    base_archive: bytes,
    artifacts: Sequence[ProducerBundlePublicationArtifact],
    *,
    journal: ProducerBundlePublicationJournal,
    strategy: PopulationStrategy,
) -> dict[str, Any]:
    """Derive the initial native population projection from the frozen prefix and admissions."""

    if (
        not isinstance(base_state, Mapping)
        or not isinstance(journal, ProducerBundlePublicationJournal)
        or not isinstance(strategy, PopulationStrategy)
    ):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_state_invalid")
    config = base_state.get("config")
    active = base_state.get("active_ids")
    if not isinstance(config, dict) or not isinstance(active, dict):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_state_invalid")
    if config.get("strategy") != "population" or config.get("num_islands") != journal.num_islands:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_state_invalid")
    before = _records_from_archive(base_archive)
    added = [_candidate_from_artifact(item) for item in artifacts]
    all_records = before + added
    by_id = {item.candidate_id: item for item in all_records}
    if len(by_id) != len(all_records):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_candidate_collision")

    iteration = base_state.get("iteration")
    _ensure_initial_population_window(base_state, before, strategy)

    admission_ids = [item.candidate_id for item in added]
    projection_state = dict(base_state)
    projection_state["producer_admissions"] = {
        "schema_version": "1",
        "events": [{"after_iteration": iteration, "candidate_ids": admission_ids}],
    }

    source_overrides = {
        artifact.candidate_id: artifact.source_bytes()
        for artifact in artifacts
    }
    try:
        active_projection, best_candidate_id, migration_iteration, stagnation = (
            strategy._reconstruct_population_projection(
                projection_state, all_records, source_overrides=source_overrides,
            )
        )
    except Exception as exc:
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_population_projection_invalid"
        ) from exc
    active_after = {str(key): value for key, value in active_projection.items()}

    authority = base_state.get("candidate_integrity_authority")
    if authority != strategy.integrity_authority.to_dict():
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_state_invalid")
    state: dict[str, Any] = dict(base_state)
    state.update({
        "schema_version": "1", "strategy": "population", "status": "running",
        "iteration": iteration, "contract_sha256": journal.contract_sha256,
        "config": dict(config), "active_ids": active_after,
        "producer_admissions": projection_state["producer_admissions"],
        "best_candidate_id": best_candidate_id,
        "rng_seed": base_state.get("rng_seed", config.get("rng_seed")),
        "last_migration_iteration": migration_iteration,
        "stagnation": stagnation, "error": None,
        "candidate_integrity_schema_version": "1",
        "candidate_integrity_authority": authority,
    })
    ordinary = [item.to_dict() for item in all_records if "seed_handoff" not in item.metadata]
    state["candidate_archive_sha256"] = _sha(_canonical(ordinary))
    return state


@dataclass(frozen=True, slots=True)
class NativeProducerBundleTransactionResult:
    journal: ProducerBundlePublicationJournal
    preflight: Any
    evaluations: tuple[NativeDraftEvaluationResult, ...]
    admitted_candidate_ids: tuple[str, ...]
    rejected_candidate_ids: tuple[str, ...]
    artifacts: tuple[ProducerBundlePublicationArtifact, ...]
    manifest: ProducerBundlePublicationManifest | None
    published_journal: ProducerBundlePublicationJournal | None
    publication_status: str
    terminal_journal: ProducerBundlePublicationJournal | None = None


def run_native_producer_bundle_publication_transaction(
    workspace: str | Path,
    strategy: PopulationStrategy,
    drafts: Sequence[ProducerBundleDraft],
    admission_plan: ProducerBundleAdmissionPlan,
    *,
    journal_id: str,
    run_id: str | None = None,
    parent_task_id: str = "producer",
    task_id: str = "native-bundle-publication",
    budget_sha256: str | None = None,
    execution_control: SolveExecutionControl | None = None,
) -> NativeProducerBundleTransactionResult:
    """Evaluate imported material and atomically publish the valid native subset.

    A supplied control is owned by the caller and must be retained across in-process retries.
    It never refreshes a deadline here. Cancellation stops new stages; once commit crosses its
    durable unknown marker, it finishes publication or preserves the existing unknown outcome.
    Cross-process budget restoration is not implemented by this active-execution API.
    """
    if not isinstance(strategy, PopulationStrategy):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_strategy_invalid")
    options = {"journal_id": journal_id, "run_id": run_id, "parent_task_id": parent_task_id,
               "task_id": task_id, "budget_sha256": budget_sha256}
    derived_budget = native_producer_bundle_budget_sha256(strategy, execution_control)
    if budget_sha256 is not None and budget_sha256 != derived_budget:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_budget_mismatch")
    options["budget_sha256"] = derived_budget
    if execution_control is not None:
        with bind_native_producer_bundle_control(strategy, execution_control) as checkpoint:
            return _run_native_producer_bundle_publication_transaction(
                workspace, strategy, drafts, admission_plan, checkpoint=checkpoint, **options,
            )

    def checkpoint(stage: str) -> None:
        if strategy._cancelled():
            raise SolveExecutionCancelled(stage)
        strategy._check_stage(stage)

    return _run_native_producer_bundle_publication_transaction(
        workspace, strategy, drafts, admission_plan, checkpoint=checkpoint, **options,
    )


def _run_native_producer_bundle_publication_transaction(
    workspace: str | Path,
    strategy: PopulationStrategy,
    drafts: Sequence[ProducerBundleDraft],
    admission_plan: ProducerBundleAdmissionPlan,
    *,
    journal_id: str,
    run_id: str | None,
    parent_task_id: str,
    task_id: str,
    budget_sha256: str | None,
    checkpoint: Callable[[str], object],
) -> NativeProducerBundleTransactionResult:
    checkpoint("producer_preparation")

    if not isinstance(strategy, PopulationStrategy):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_strategy_invalid")
    if not isinstance(admission_plan, ProducerBundleAdmissionPlan):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_plan_invalid")
    if isinstance(drafts, (str, bytes)) or not isinstance(drafts, Sequence) or len(drafts) != len(admission_plan.bundles):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_drafts_invalid")
    drafts = _snapshot_drafts(drafts, admission_plan)
    root = Path(workspace).expanduser().absolute()
    if root != strategy.context.workspace.expanduser().absolute():
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_workspace_invalid")
    if run_id is None:
        run_id = journal_id
    base_state_bytes, base_state = _read_state(root)
    base_archive = _read_optional(root / "evolution" / "archive.jsonl")
    try:
        loaded_state = strategy._load_state()
    except Exception as exc:
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_state_invalid"
        ) from exc
    if loaded_state != base_state:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_prefix_invalid")
    state_authority = base_state.get("candidate_integrity_authority")
    try:
        expected_authority = strategy.integrity_authority.to_dict()
    except Exception as exc:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_state_invalid") from exc
    if not isinstance(state_authority, dict) or state_authority != expected_authority:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_state_invalid")
    num_islands = base_state.get("config", {}).get("num_islands") if isinstance(base_state.get("config"), dict) else None
    if isinstance(num_islands, bool) or not isinstance(num_islands, int) or num_islands < 1:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_state_invalid")
    authority_fields = (
        "contract_sha256", "evaluator_kind", "evaluator_fingerprint",
        "runner_fingerprint", "dependency_sha256", "environment_sha256",
    )
    if any(
        getattr(strategy.integrity_authority, field) != getattr(admission_plan, field)
        for field in authority_fields
    ):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_authority_invalid")
    candidates: list[ProducerBundlePublicationCandidate] = []
    for ordinal, (draft, item) in enumerate(zip(drafts, admission_plan.bundles, strict=True)):
        if not isinstance(draft, ProducerBundleDraft) or draft.bundle_id != item.bundle_id:
            raise NativeProducerBundleTransactionError("producer_bundle_transaction_drafts_invalid")
        candidate_id = derive_producer_bundle_candidate_id(journal_id, ordinal, item.bundle_id, item.bundle_sha256)
        preparation = _sha(_canonical({"plan_sha256": admission_plan.digest(), "bundle_id": item.bundle_id, "ordinal": ordinal}))
        candidates.append(ProducerBundlePublicationCandidate(
            candidate_id=candidate_id, bundle_id=item.bundle_id, bundle_sha256=item.bundle_sha256,
            parent_id=None, generation=0, iteration=0, island_id=ordinal % num_islands,
            preparation_receipt_sha256=preparation,
        ))
    journal = build_producer_bundle_publication_journal(
        journal_id=journal_id, run_id=run_id, parent_task_id=parent_task_id, task_id=task_id,
        admission_sha256=admission_plan.digest(), archive_prefix_sha256=_state_prefix(root, base_archive, base_state_bytes, base_state),
        base_archive_sha256=_sha(base_archive), base_state_sha256=_sha(base_state_bytes),
        contract_sha256=admission_plan.contract_sha256, evaluator_kind=admission_plan.evaluator_kind,
        evaluator_fingerprint=admission_plan.evaluator_fingerprint, runner_fingerprint=admission_plan.runner_fingerprint,
        dependency_sha256=admission_plan.dependency_sha256, environment_sha256=admission_plan.environment_sha256,
        budget_sha256=budget_sha256, strategy="population", population_config_sha256=_sha(_canonical(base_state["config"])),
        num_islands=num_islands, candidates=tuple(candidates),
    )
    try:
        preflight = preflight_producer_bundle_publication(root, admission_plan, journal, budget_sha256=budget_sha256)
    except Exception as exc:
        code = getattr(exc, "code", "producer_bundle_transaction_preflight_failed")
        raise NativeProducerBundleTransactionError(code) from exc
    try:
        _ensure_initial_population_window(base_state, _records_from_archive(base_archive), strategy)
        strategy._validate_candidate_integrity_state(base_state)
        strategy._active(dict(base_state))
    except NativeProducerBundleTransactionError:
        raise
    except Exception as exc:
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_population_projection_invalid"
        ) from exc

    evaluations: list[NativeDraftEvaluationResult] = []
    artifacts: list[ProducerBundlePublicationArtifact] = []
    rejected: list[str] = []
    try:
        checkpoint("producer_prepared_intent")
        journal_sha256 = persist_producer_bundle_prepared_intent(root, journal, checkpoint=checkpoint)
        terminal = inspect_producer_bundle_all_rejected(
            root, journal, preflight=preflight, checkpoint=checkpoint,
        )
        if terminal is not None:
            return NativeProducerBundleTransactionResult(
                journal=journal, preflight=preflight, evaluations=(), admitted_candidate_ids=(),
                rejected_candidate_ids=tuple(item.candidate_id for item in terminal.candidates),
                artifacts=(), manifest=None, published_journal=None,
                publication_status="all_rejected", terminal_journal=terminal,
            )
    except (SolveExecutionCancelled, SolveExecutionBudgetExceeded):
        raise
    except Exception as exc:
        code = getattr(exc, "code", "producer_bundle_transaction_recovery_required")
        raise NativeProducerBundleTransactionError(code) from exc
    for ordinal, (draft, planned) in enumerate(zip(drafts, candidates, strict=True)):
        try:
            checkpoint("producer_draft_evaluation")
            result = strategy.context.bundle_pipeline.evaluate_draft_non_publishing(
                strategy, draft.draft, journal_id=journal_id, ordinal=ordinal,
                journal_candidate=planned, admission_plan=admission_plan,
                journal_sha256=journal_sha256,
            )
            checkpoint("producer_draft_adjudication")
        except (SolveExecutionCancelled, SolveExecutionBudgetExceeded):
            raise
        except Exception as exc:
            code = getattr(exc, "code", "producer_bundle_transaction_recovery_required")
            raise NativeProducerBundleTransactionError(code) from exc
        evaluations.append(result)
        if result.report.validity != 1:
            rejected.append(planned.candidate_id)
            continue
        try:
            artifacts.append(build_native_producer_bundle_publication_artifact(
                root, result, authority=strategy.integrity_authority,
            ))
        except Exception as exc:
            code = getattr(exc, "code", "producer_bundle_transaction_recovery_required")
            raise NativeProducerBundleTransactionError(code) from exc

    try:
        checkpoint("producer_adjudication")
        verify_producer_bundle_prepared_intent(root, journal)
    except (SolveExecutionCancelled, SolveExecutionBudgetExceeded):
        raise
    except Exception as exc:
        code = getattr(exc, "code", "producer_bundle_transaction_recovery_required")
        raise NativeProducerBundleTransactionError(code) from exc
    admitted = tuple(item.candidate_id for item in candidates if item.candidate_id not in set(rejected))
    if not artifacts:
        try:
            terminal = finalize_producer_bundle_all_rejected(
                root, journal, preflight, tuple(evaluations),
                authority=strategy.integrity_authority, checkpoint=checkpoint,
            )
        except (SolveExecutionCancelled, SolveExecutionBudgetExceeded):
            raise
        except Exception as exc:
            code = getattr(exc, "code", "producer_bundle_transaction_recovery_required")
            raise NativeProducerBundleTransactionError(code) from exc
        return NativeProducerBundleTransactionResult(
            journal=journal, preflight=preflight, evaluations=tuple(evaluations),
            admitted_candidate_ids=(), rejected_candidate_ids=tuple(rejected), artifacts=(),
            manifest=None, published_journal=None, publication_status="all_rejected",
            terminal_journal=terminal,
        )

    state_after = derive_population_state_after(
        base_state, base_archive, artifacts, journal=journal, strategy=strategy,
    )
    try:
        checkpoint("producer_staging")
        manifest = stage_producer_bundle_publication(
            root, journal, preflight, tuple(artifacts), state_after=state_after,
            rejected_candidate_ids=tuple(rejected),
            checkpoint=checkpoint,
        )
        staged = parse_producer_bundle_publication_journal(
            root / "evolution" / "producer-batches" / journal_id / "journal.json",
        )
        checkpoint("producer_commit")
        published = commit_producer_bundle_publication(root, staged, checkpoint=checkpoint)
        archive = CandidateArchive(root, requested_strategy="population", read_only=True)
        records = tuple(archive.records())
        archive.validate_candidate_integrity(require_all=True, records=records)
        committed_state = archive.read_state()
        if committed_state != state_after:
            raise NativeProducerBundleTransactionError("producer_bundle_transaction_readback_invalid")
        strategy._validate_candidate_integrity_state(committed_state)
        strategy._active(committed_state)
    except (NativeProducerBundleTransactionError, SolveExecutionCancelled, SolveExecutionBudgetExceeded):
        raise
    except Exception as exc:
        code = getattr(exc, "code", "producer_bundle_transaction_recovery_required")
        raise NativeProducerBundleTransactionError(code) from exc
    return NativeProducerBundleTransactionResult(
        journal=journal, preflight=preflight, evaluations=tuple(evaluations),
        admitted_candidate_ids=admitted, rejected_candidate_ids=tuple(rejected),
        artifacts=tuple(artifacts), manifest=manifest, published_journal=published,
        publication_status="published",
        terminal_journal=published,
    )


__all__ = [
    "NativeProducerBundleTransactionError",
    "NativeProducerBundleTransactionResult",
    "derive_population_state_after",
    "run_native_producer_bundle_publication_transaction",
]
