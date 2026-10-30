"""Native producer-bundle publication transaction orchestration.

The producer adapters only provide material.  This module is the small, provider-free bridge
that evaluates those materials with Lunar's native multi-file pipeline and publishes the admitted
subset through Feature 153's durable staging protocol.
"""

from __future__ import annotations

import hashlib
import json
import time
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
from .candidate_evaluation_spec import strict_json
from .evolution import Candidate, CandidateArchive, CandidateDraft, PopulationStrategy
from .producer_bundle_admission import (
    ProducerBundleAdmissionPlan,
    build_producer_bundle_admission_plan,
)
from .producer_bundle_control import (
    bind_native_producer_bundle_checkpoint,
    bind_native_producer_bundle_control,
    native_producer_bundle_budget_sha256,
)
from .producer_bundle_deadline import persist_controlled_producer_bundle_intent
from .producer_bundle_intent import (
    persist_producer_bundle_prepared_intent,
    verify_producer_bundle_prepared_intent,
    verify_producer_bundle_python_handoff_anchor,
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
from .producer_process import (
    ProducerProcessError,
    parse_producer_execution_receipt,
)
from .python_producer_admission_anchor import (
    PythonProducerAdmissionAttemptAnchor,
    persist_python_producer_admission_attempt_anchor,
    project_python_producer_admission_attempt_anchor,
    read_python_producer_admission_attempt_anchor,
)
from .python_producer_admission_handoff import (
    PythonProducerAdmissionHandoffError,
    PythonProducerAdmissionHandoffFilePin,
    parse_python_producer_admission_handoff_file_pin,
    read_python_producer_admission_handoff_pinned,
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


def _validate_batch_identifier(value: object) -> str:
    """Reject path-bearing journal identifiers before deriving a batch path."""
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_journal_id_invalid"
        )
    if Path(value).name != value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_journal_id_invalid"
        )
    return value


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


def _verify_native_execution_receipt_link(
    root: Path,
    *,
    journal_id: str,
    run_id: str,
    parent_task_id: str,
    task_id: str,
    receipt_sha256: str | None,
) -> None:
    """Validate the optional native execution receipt before creating a publication journal."""
    if receipt_sha256 is None:
        return
    _validate_batch_identifier(journal_id)
    batch = root / "evolution" / "producer-batches" / journal_id
    path = batch / "execution-receipt.json"
    try:
        raw = strict_json(_files.read_regular_file(path, 256 * 1024), 256 * 1024)
    except Exception as exc:
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_execution_receipt_invalid"
        ) from exc
    try:
        parsed = parse_producer_execution_receipt(raw)
    except (ProducerProcessError, TypeError, ValueError) as exc:
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_execution_receipt_invalid"
        ) from exc
    trusted = parsed.trusted_execution
    if (
        parsed.protocol != "lunar-producer-process-execution-v1"
        or parsed.receipt_sha256 != receipt_sha256
        or any(getattr(parsed, key) != value for key, value in (
            ("journal_id", journal_id),
            ("run_id", run_id), ("parent_task_id", parent_task_id), ("task_id", task_id),
        ))
        or parsed.status != "completed"
        or parsed.exit_code != 0
        or parsed.gate_released is not True
        or parsed.cleanup_status not in {"cleaned", "already_exited"}
        or not isinstance(trusted, dict)
        or trusted.get("broker_coverage") != "brokered_requests_only"
    ):
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_execution_receipt_invalid"
        )


def _verify_python_handoff_link(
    root: Path,
    *,
    journal_id: str,
    run_id: str,
    parent_task_id: str,
    task_id: str,
    admission_plan: ProducerBundleAdmissionPlan,
    native_execution_receipt_sha256: str | None,
    python_handoff_sha256: str | None,
    python_handoff_file_pin: PythonProducerAdmissionHandoffFilePin | None,
    prepared_journal: ProducerBundlePublicationJournal | None = None,
) -> object | None:
    """Require a durable, canonical handoff before accepting the Python path.

    The journal field is an identity reference, not caller-provided authority.  A Python
    transaction therefore has to read the create-only handoff from the producer batch and
    compare every authority pin available at this boundary before it can evaluate or publish.
    Legacy native callers leave the optional field absent and retain their existing behavior.
    """
    if python_handoff_sha256 is None:
        if prepared_journal is not None:
            try:
                verify_producer_bundle_python_handoff_anchor(root, prepared_journal)
            except ValueError as exc:
                raise NativeProducerBundleTransactionError(
                    "producer_bundle_transaction_python_handoff_invalid"
                ) from exc
        return None
    _validate_batch_identifier(journal_id)
    if native_execution_receipt_sha256 is None:
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_python_handoff_execution_link_missing"
        )
    batch = root / "evolution" / "producer-batches" / journal_id
    path = batch / "python-producer-admission-handoff.json"
    try:
        if prepared_journal is not None:
            verify_producer_bundle_python_handoff_anchor(root, prepared_journal)
        sidecar = read_python_producer_admission_handoff_pinned(
            path, expected_file_pin=python_handoff_file_pin,
        )
        handoff = sidecar.handoff
        if sidecar.file_pin != python_handoff_file_pin or handoff.handoff_sha256 != python_handoff_sha256:
            raise ValueError("handoff pin mismatch")
        if prepared_journal is not None:
            verify_producer_bundle_python_handoff_anchor(root, prepared_journal)
    except (PythonProducerAdmissionHandoffError, TypeError, ValueError) as exc:
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_python_handoff_invalid"
        ) from exc
    if (
        handoff.run_id != run_id
        or handoff.journal_id != journal_id
        or handoff.parent_task_id != parent_task_id
        or handoff.task_id != task_id
        or handoff.native_execution_receipt_sha256 != native_execution_receipt_sha256
        or handoff.admission_plan_sha256 != admission_plan.digest()
        or handoff.contract_sha256 != admission_plan.contract_sha256
        or handoff.evaluator_sha256 != admission_plan.evaluator_fingerprint
        or handoff.runner_sha256 != admission_plan.runner_fingerprint
        or handoff.dependency_sha256 != admission_plan.dependency_sha256
        or handoff.environment_sha256 != admission_plan.environment_sha256
        or handoff.state != "prepared"
    ):
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_python_handoff_mismatch"
        )
    return handoff


def _admission_attempt_anchor(handoff: object) -> PythonProducerAdmissionAttemptAnchor:
    """Derive the immutable first-attempt projection from the retained handoff."""
    try:
        return project_python_producer_admission_attempt_anchor(handoff)
    except Exception as exc:
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_python_admission_anchor_invalid"
        ) from exc


def _persist_python_admission_attempt_anchor(root: Path, handoff: object) -> PythonProducerAdmissionAttemptAnchor:
    anchor = _admission_attempt_anchor(handoff)
    batch = root / "evolution" / "producer-batches" / handoff.journal_id
    try:
        return persist_python_producer_admission_attempt_anchor(batch, anchor=anchor)
    except Exception as exc:
        code = getattr(exc, "code", "producer_bundle_transaction_python_admission_anchor_invalid")
        raise NativeProducerBundleTransactionError(code) from exc


def _verify_python_admission_attempt_anchor(root: Path, handoff: object) -> PythonProducerAdmissionAttemptAnchor:
    expected = _admission_attempt_anchor(handoff)
    batch = root / "evolution" / "producer-batches" / handoff.journal_id
    try:
        observed = read_python_producer_admission_attempt_anchor(
            batch, expected_anchor_sha256=expected.anchor_sha256,
        )
        if not observed.matches(expected):
            raise ValueError("anchor drift")
        return observed
    except Exception as exc:
        code = getattr(exc, "code", "producer_bundle_transaction_python_admission_anchor_invalid")
        raise NativeProducerBundleTransactionError(code) from exc


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


def _validate_lineage_owner(
    producer_multi_episode_publication: bool, lineage_owner: object | None,
) -> None:
    if type(producer_multi_episode_publication) is not bool:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_multi_episode_configuration_invalid")
    if not producer_multi_episode_publication:
        if lineage_owner is not None:
            raise NativeProducerBundleTransactionError("producer_bundle_transaction_multi_episode_configuration_invalid")
        return
    if lineage_owner is None:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_multi_episode_configuration_invalid")
    from . import rsi_publication_lineage

    if type(lineage_owner) is not getattr(rsi_publication_lineage, "RSIPublicationLineage", None):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_multi_episode_configuration_invalid")


def _lineage_call(lineage_owner: object, method: str, *args: object, **kwargs: object) -> Any:
    """Resolve only an exact capsule's original class method, never an instance hook."""
    _validate_lineage_owner(True, lineage_owner)
    from .rsi_publication_lineage import RSIPublicationLineage

    return getattr(RSIPublicationLineage, method)(lineage_owner, *args, **kwargs)


def _validate_native_lineage_scope(public_multi: bool, owner: object | None, original_brs: object | None) -> None:
    if original_brs is None:
        _validate_lineage_owner(public_multi, owner)
        return
    if public_multi is not False or owner is not original_brs:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_brs_owner_invalid")
    from .rsi_python_brs_native_dispatch import _fixed_original_brs_owner

    _fixed_original_brs_owner(original_brs)


def _native_lineage_call(owner: object, original_brs: object | None, method: str,
                         *args: object, **kwargs: object) -> Any:
    if original_brs is None:
        return _lineage_call(owner, method, *args, **kwargs)
    if owner is not original_brs:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_brs_owner_invalid")
    from .rsi_python_brs_native_dispatch import _call_original_brs_owner

    return _call_original_brs_owner(original_brs, method, *args, **kwargs)


def _observe_native_producer_evidence(
    evidence_revalidator: Callable[[str], None], original_brs: object | None, stage: str,
) -> None:
    """Own the full original BRS post-observation gate at every evidence call site.

    A callback is never trusted to have checked the owner, regardless of its
    type, attributes or return value. Generic transactions retain their original
    callback behavior. The exact original-owner path always observes fresh
    SQL, retained files and policy after the callback returns.
    """
    evidence_revalidator(stage)
    if original_brs is not None:
        from .rsi_python_brs_native_dispatch import _fixed_original_brs_owner

        _fixed_original_brs_owner(original_brs)


def _ensure_append_population_window(
    state: Mapping[str, Any], records: Sequence[Candidate], strategy: PopulationStrategy,
    *, prior_events: tuple[tuple[str, ...], ...],
) -> None:
    """Narrow native shape check after the original owner's predecessor proof passed."""
    if type(prior_events) is not tuple or len(prior_events) > 7 or any(
        type(group) is not tuple or not group or len(group) > 32
        or any(type(candidate_id) is not str for candidate_id in group)
        for group in prior_events
    ):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_lineage_prefix_invalid")
    stripped_state = dict(state)
    stripped_state.pop("producer_admissions", None)
    ordinary = tuple(candidate for candidate in records if "producer_bundle" not in candidate.metadata)
    _ensure_initial_population_window(stripped_state, ordinary, strategy)
    seed_commit = strategy.context.workspace / "evolution" / "seed-commit.json"
    if (any(candidate.iteration != 0 or "seed_handoff" in candidate.metadata for candidate in records)
            or seed_commit.exists() or seed_commit.is_symlink()):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_population_history_unsupported")
    try:
        observed = strategy._producer_admission_events(state, records)
    except Exception as exc:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_lineage_prefix_invalid") from exc
    if observed != tuple((0, candidate_ids) for candidate_ids in prior_events):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_lineage_prefix_invalid")


def derive_population_state_after(
    base_state: Mapping[str, Any],
    base_archive: bytes,
    artifacts: Sequence[ProducerBundlePublicationArtifact],
    *,
    journal: ProducerBundlePublicationJournal,
    strategy: PopulationStrategy,
    lineage_owner: object | None = None,
    base_state_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Derive the native projection through the unchanged public DRS-only gate."""
    return _derive_population_state_after(
        base_state, base_archive, artifacts, journal=journal, strategy=strategy,
        lineage_owner=lineage_owner, base_state_bytes=base_state_bytes,
    )


def _derive_population_state_after(
    base_state: Mapping[str, Any],
    base_archive: bytes,
    artifacts: Sequence[ProducerBundlePublicationArtifact],
    *,
    journal: ProducerBundlePublicationJournal,
    strategy: PopulationStrategy,
    lineage_owner: object | None = None,
    base_state_bytes: bytes | None = None,
    _original_brs_owner: object | None = None,
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
    if lineage_owner is None:
        _ensure_initial_population_window(base_state, before, strategy)
        prior_events = ()
    else:
        _validate_native_lineage_scope(_original_brs_owner is None, lineage_owner, _original_brs_owner)
        if type(base_state_bytes) is not bytes or _sha(base_state_bytes) != journal.base_state_sha256:
            raise NativeProducerBundleTransactionError("producer_bundle_transaction_lineage_prefix_invalid")
        prior_events = _native_lineage_call(lineage_owner, _original_brs_owner, "validate_before", journal, base_archive, base_state_bytes, strategy)
        _ensure_append_population_window(base_state, before, strategy, prior_events=prior_events)

    admission_ids = [item.candidate_id for item in added]
    projection_state = dict(base_state)
    projection_state["producer_admissions"] = {
        "schema_version": "1",
        "events": [{"after_iteration": 0, "candidate_ids": list(group)} for group in prior_events]
        + [{"after_iteration": iteration, "candidate_ids": admission_ids}],
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
    native_execution_receipt_sha256: str | None = None,
    python_handoff_sha256: str | None = None,
    python_handoff_file_pin: PythonProducerAdmissionHandoffFilePin | None = None,
    execution_control: SolveExecutionControl | None = None,
    continuation_guard: Callable[[str], None] | None = None,
    evidence_revalidator: Callable[[str], None] | None = None,
    prepared_observer: Callable[[ProducerBundlePublicationJournal], None] | None = None,
    producer_multi_episode_publication: bool = False,
    lineage_owner: object | None = None,
) -> NativeProducerBundleTransactionResult:
    """Evaluate and publish through the unchanged public DRS-only owner gate."""
    _validate_lineage_owner(producer_multi_episode_publication, lineage_owner)
    return _run_bound_native_producer_bundle_publication_transaction(
        workspace, strategy, drafts, admission_plan, journal_id=journal_id,
        run_id=run_id, parent_task_id=parent_task_id, task_id=task_id,
        budget_sha256=budget_sha256, native_execution_receipt_sha256=native_execution_receipt_sha256,
        python_handoff_sha256=python_handoff_sha256, python_handoff_file_pin=python_handoff_file_pin,
        execution_control=execution_control, continuation_guard=continuation_guard,
        evidence_revalidator=evidence_revalidator, prepared_observer=prepared_observer,
        producer_multi_episode_publication=producer_multi_episode_publication, lineage_owner=lineage_owner,
    )


def _run_bound_native_producer_bundle_publication_transaction(
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
    native_execution_receipt_sha256: str | None = None,
    python_handoff_sha256: str | None = None,
    python_handoff_file_pin: PythonProducerAdmissionHandoffFilePin | None = None,
    execution_control: SolveExecutionControl | None = None,
    continuation_guard: Callable[[str], None] | None = None,
    evidence_revalidator: Callable[[str], None] | None = None,
    prepared_observer: Callable[[ProducerBundlePublicationJournal], None] | None = None,
    producer_multi_episode_publication: bool = False,
    lineage_owner: object | None = None,
    _original_brs_owner: object | None = None,
    _original_brs_receipt_pin: object | None = None,
) -> NativeProducerBundleTransactionResult:
    """Evaluate imported material and atomically publish the valid native subset.

    A supplied control is owned by the caller and must be retained across in-process retries.
    It never refreshes a deadline here. Cancellation stops new stages; once commit crosses its
    durable unknown marker, it finishes publication or preserves the existing unknown outcome.
    The original monotonic deadline is retained with the prepared intent. A new process-local
    control can only narrow it; restart in a different boot fails closed.
    """
    if not isinstance(strategy, PopulationStrategy):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_strategy_invalid")
    if continuation_guard is not None and not callable(continuation_guard):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_guard_invalid")
    if evidence_revalidator is not None and not callable(evidence_revalidator):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_evidence_revalidator_invalid")
    if prepared_observer is not None and not callable(prepared_observer):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_prepared_observer_invalid")
    _validate_native_lineage_scope(producer_multi_episode_publication, lineage_owner, _original_brs_owner)
    if _original_brs_owner is not None:
        from .producer_bundle_lineage import LineageSnapshotPin

        if type(_original_brs_receipt_pin) is not LineageSnapshotPin:
            raise NativeProducerBundleTransactionError("producer_bundle_transaction_brs_receipt_pin_invalid")
    elif _original_brs_receipt_pin is not None:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_brs_receipt_pin_invalid")
    if _original_brs_owner is not None and (
            type(workspace) is not type(_original_brs_owner._workspace)
            or workspace != _original_brs_owner._workspace or strategy is not _original_brs_owner._strategy
            or execution_control is not _original_brs_owner._before_control
            or (run_id, journal_id, parent_task_id, task_id) != (
                _original_brs_owner._run_id, _original_brs_owner._plan.journal_id,
                _original_brs_owner._plan.parent_task_id, _original_brs_owner._plan.task_id)
            or continuation_guard is not None or evidence_revalidator is None or prepared_observer is None):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_brs_inputs_invalid")
    if python_handoff_sha256 is not None and native_execution_receipt_sha256 is None:
        raise NativeProducerBundleTransactionError(
            "producer_bundle_transaction_python_handoff_execution_link_missing"
        )
    if python_handoff_sha256 is not None or python_handoff_file_pin is not None:
        try:
            if type(python_handoff_file_pin) is not PythonProducerAdmissionHandoffFilePin:
                raise ValueError("original handoff pin required")
            parsed_pin = parse_python_producer_admission_handoff_file_pin(python_handoff_file_pin)
            if (parsed_pin != python_handoff_file_pin or parsed_pin.handoff_sha256 != python_handoff_sha256
                    or (parsed_pin.run_id, parsed_pin.journal_id, parsed_pin.parent_task_id, parsed_pin.task_id)
                    != (journal_id if run_id is None else run_id, journal_id, parent_task_id, task_id)):
                raise ValueError("handoff pin mismatch")
        except (PythonProducerAdmissionHandoffError, TypeError, ValueError) as exc:
            raise NativeProducerBundleTransactionError(
                "producer_bundle_transaction_python_handoff_invalid"
            ) from exc
    options = {"journal_id": journal_id, "run_id": run_id, "parent_task_id": parent_task_id,
               "task_id": task_id, "budget_sha256": budget_sha256,
               "native_execution_receipt_sha256": native_execution_receipt_sha256,
               "python_handoff_sha256": python_handoff_sha256,
               "python_handoff_file_pin": python_handoff_file_pin,
               "evidence_revalidator": evidence_revalidator,
               "prepared_observer": prepared_observer,
               "producer_multi_episode_publication": producer_multi_episode_publication,
               "lineage_owner": lineage_owner, "_original_brs_owner": _original_brs_owner,
               "_original_brs_receipt_pin": _original_brs_receipt_pin}
    derived_budget = native_producer_bundle_budget_sha256(strategy, execution_control)
    if budget_sha256 is not None and budget_sha256 != derived_budget:
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_budget_mismatch")
    options["budget_sha256"] = derived_budget
    if execution_control is not None:
        with bind_native_producer_bundle_control(strategy, execution_control) as checkpoint:
            if continuation_guard is not None:
                original_checkpoint = checkpoint

                def checkpoint(stage: str) -> object:
                    continuation_guard(stage)
                    return original_checkpoint(stage)

                checkpoint.bind_retained_deadline = original_checkpoint.bind_retained_deadline
                checkpoint.revalidate_after_observation = original_checkpoint.revalidate_after_observation
                checkpoint.observe_checkpoint_before_evidence = original_checkpoint.observe_checkpoint_before_evidence
                checkpoint.observe_cancellation_before_evidence = original_checkpoint.observe_cancellation_before_evidence
                strategy.context.bundle_pipeline.set_remaining_timeout(checkpoint)
            return _run_native_producer_bundle_publication_transaction(
                workspace, strategy, drafts, admission_plan, checkpoint=checkpoint,
                execution_control=execution_control, **options,
            )

    def checkpoint(stage: str) -> None:
        if continuation_guard is not None:
            continuation_guard(stage)
        if strategy._cancelled():
            raise SolveExecutionCancelled(stage)
        strategy._check_stage(stage)

    with bind_native_producer_bundle_checkpoint(strategy, checkpoint):
        timeout_check = strategy.context.bundle_pipeline._remaining_timeout
        if hasattr(timeout_check, "revalidate_after_observation"):
            checkpoint.revalidate_after_observation = timeout_check.revalidate_after_observation
            checkpoint.observe_checkpoint_before_evidence = timeout_check.observe_checkpoint_before_evidence
            checkpoint.observe_cancellation_before_evidence = timeout_check.observe_cancellation_before_evidence
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
    native_execution_receipt_sha256: str | None,
    python_handoff_sha256: str | None,
    python_handoff_file_pin: PythonProducerAdmissionHandoffFilePin | None,
    checkpoint: Callable[[str], object],
    execution_control: SolveExecutionControl | None = None,
    evidence_revalidator: Callable[[str], None] | None = None,
    prepared_observer: Callable[[ProducerBundlePublicationJournal], None] | None = None,
    producer_multi_episode_publication: bool = False,
    lineage_owner: object | None = None,
    _original_brs_owner: object | None = None,
    _original_brs_receipt_pin: object | None = None,
) -> NativeProducerBundleTransactionResult:
    _validate_native_lineage_scope(producer_multi_episode_publication, lineage_owner, _original_brs_owner)
    checkpoint("producer_preparation")
    if evidence_revalidator is not None:
        checkpoint.observe_checkpoint_before_evidence("producer_preparation")
        _observe_native_producer_evidence(evidence_revalidator, _original_brs_owner, "producer_preparation")
        if hasattr(checkpoint, "revalidate_after_observation"):
            checkpoint.revalidate_after_observation("producer_preparation")
            if _original_brs_owner is not None:
                from .rsi_python_brs_native_dispatch import _original_brs_numeric_tail

                _original_brs_numeric_tail(_original_brs_owner)
        elif strategy._cancelled():
            raise SolveExecutionCancelled("producer_preparation")

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
    _verify_native_execution_receipt_link(
        root,
        journal_id=journal_id,
        run_id=run_id,
        parent_task_id=parent_task_id,
        task_id=task_id,
        receipt_sha256=native_execution_receipt_sha256,
    )
    python_handoff = _verify_python_handoff_link(
        root,
        journal_id=journal_id,
        run_id=run_id,
        parent_task_id=parent_task_id,
        task_id=task_id,
        admission_plan=admission_plan,
        native_execution_receipt_sha256=native_execution_receipt_sha256,
        python_handoff_sha256=python_handoff_sha256,
        python_handoff_file_pin=python_handoff_file_pin,
    )
    # Re-read the create-only handoff after every caller-owned checkpoint.  A continuation
    # guard may mutate or remove the batch file while it is deciding whether to continue; the
    # boundary check must run after that callback and before any evaluator, stage, or commit.
    original_checkpoint = checkpoint
    anchored_journal: ProducerBundlePublicationJournal | None = None
    admission_anchor: PythonProducerAdmissionAttemptAnchor | None = None

    def prepared_intent_present() -> bool:
        intent_path = root / "evolution" / "producer-batches" / journal_id / "journal.prepared.json"
        try:
            intent_path.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise NativeProducerBundleTransactionError(
                "producer_bundle_transaction_python_admission_anchor_invalid"
            ) from exc
        return True

    if python_handoff is not None and prepared_intent_present():
        # A retained intent proves the first registration boundary already passed.
        # Its missing anchor is uncertainty, never permission to create a fresh one.
        admission_anchor = _verify_python_admission_attempt_anchor(root, python_handoff)

    def observe_original_handoff() -> None:
        _verify_native_execution_receipt_link(
            root, journal_id=journal_id, run_id=run_id, parent_task_id=parent_task_id,
            task_id=task_id, receipt_sha256=native_execution_receipt_sha256,
        )
        _verify_python_handoff_link(
            root, journal_id=journal_id, run_id=run_id, parent_task_id=parent_task_id,
            task_id=task_id, admission_plan=admission_plan,
            native_execution_receipt_sha256=native_execution_receipt_sha256,
            python_handoff_sha256=python_handoff_sha256,
            python_handoff_file_pin=python_handoff_file_pin, prepared_journal=anchored_journal,
        )
        if admission_anchor is not None and python_handoff is not None:
            _verify_python_admission_attempt_anchor(root, python_handoff)
        if _original_brs_owner is not None:
            from .producer_bundle_lineage import verify_persisted_lineage_snapshot

            verify_persisted_lineage_snapshot(
                root / "evolution/producer-batches" / journal_id / "execution-receipt.json",
                _original_brs_receipt_pin,
            )

    retained_revalidate = getattr(original_checkpoint, "revalidate_after_observation", None)
    if _original_brs_owner is not None and not callable(retained_revalidate):
        raise NativeProducerBundleTransactionError("producer_bundle_transaction_brs_control_invalid")

    def checkpoint_with_handoff(stage: str) -> object:
        if _original_brs_owner is not None:
            from .producer_bundle_staging import (
                _HELD_PUBLICATION_LOCKS,
                _LOCK_NAME,
                _check_held_publication_lock,
            )
            from .rsi_python_brs_native_dispatch import (
                _fixed_original_brs_owner,
                _original_brs_numeric_tail,
            )

            # Waiting for the lock is still an unlocked full-observation boundary.
            # Only the actual acquired lock selects this callback-free projection.
            held_locks = _HELD_PUBLICATION_LOCKS.get()
            if held_locks:
                current_lock = root / "evolution" / _LOCK_NAME
                if not any(lock == current_lock for lock, _descriptor, _info in held_locks):
                    raise NativeProducerBundleTransactionError("producer_bundle_transaction_brs_foreign_lock")
                _check_held_publication_lock()
                _fixed_original_brs_owner(_original_brs_owner)
                observe_original_handoff()
                result = retained_revalidate(stage)
                _original_brs_numeric_tail(_original_brs_owner)
                return result
            original_checkpoint(stage)
            original_checkpoint.observe_checkpoint_before_evidence(stage)
            if evidence_revalidator is not None:
                _observe_native_producer_evidence(evidence_revalidator, _original_brs_owner, stage)
            else:
                _fixed_original_brs_owner(_original_brs_owner)
            observe_original_handoff()
            result = retained_revalidate(stage)
            _original_brs_numeric_tail(_original_brs_owner)
            return result
        result = original_checkpoint(stage)
        if evidence_revalidator is not None:
            original_checkpoint.observe_checkpoint_before_evidence(stage)
        _verify_python_handoff_link(
            root,
            journal_id=journal_id,
            run_id=run_id,
            parent_task_id=parent_task_id,
            task_id=task_id,
            admission_plan=admission_plan,
            native_execution_receipt_sha256=native_execution_receipt_sha256,
            python_handoff_sha256=python_handoff_sha256,
            python_handoff_file_pin=python_handoff_file_pin,
            prepared_journal=anchored_journal,
        )
        if admission_anchor is not None and python_handoff is not None:
            _verify_python_admission_attempt_anchor(root, python_handoff)
        if evidence_revalidator is not None:
            _observe_native_producer_evidence(evidence_revalidator, _original_brs_owner, stage)
            if hasattr(original_checkpoint, "revalidate_after_observation"):
                result = original_checkpoint.revalidate_after_observation(stage)
            elif strategy._cancelled():
                raise SolveExecutionCancelled(stage)
        return result

    if hasattr(original_checkpoint, "bind_retained_deadline"):
        checkpoint_with_handoff.bind_retained_deadline = original_checkpoint.bind_retained_deadline
    if hasattr(original_checkpoint, "revalidate_after_observation"):
        checkpoint_with_handoff.revalidate_after_observation = original_checkpoint.revalidate_after_observation
        checkpoint_with_handoff.observe_checkpoint_before_evidence = original_checkpoint.observe_checkpoint_before_evidence
        checkpoint_with_handoff.observe_cancellation_before_evidence = original_checkpoint.observe_cancellation_before_evidence
    checkpoint = checkpoint_with_handoff
    # The bundle evaluator samples the pipeline timeout directly between explicit
    # transaction checkpoints.  Keep that numeric timeout callback on a handoff-aware
    # wrapper so a caller continuation guard cannot remove or replace the create-only
    # handoff after the last explicit checkpoint and still let evaluation proceed.
    pipeline = strategy.context.bundle_pipeline
    pipeline_timeout = pipeline._remaining_timeout

    def timeout_with_handoff(stage: str) -> float:
        remaining = pipeline_timeout(stage)
        sampled_at = execution_control._now() if execution_control is not None else time.monotonic()
        if evidence_revalidator is not None:
            original_checkpoint.observe_cancellation_before_evidence(stage)
        _verify_python_handoff_link(
            root,
            journal_id=journal_id,
            run_id=run_id,
            parent_task_id=parent_task_id,
            task_id=task_id,
            admission_plan=admission_plan,
            native_execution_receipt_sha256=native_execution_receipt_sha256,
            python_handoff_sha256=python_handoff_sha256,
            python_handoff_file_pin=python_handoff_file_pin,
            prepared_journal=anchored_journal,
        )
        if admission_anchor is not None and python_handoff is not None:
            _verify_python_admission_attempt_anchor(root, python_handoff)
        if evidence_revalidator is not None:
            _observe_native_producer_evidence(evidence_revalidator, _original_brs_owner, stage)
            if _original_brs_owner is not None:
                observe_original_handoff()
            revalidate = getattr(original_checkpoint, "revalidate_after_observation", None)
            observed_at = execution_control._now() if execution_control is not None else time.monotonic()
            deadline = sampled_at + remaining
            stale_remaining = remaining - max(0.0, observed_at - sampled_at)
            if callable(revalidate):
                # This callback returns a remainder sampled after evidence I/O. Charge
                # that current value directly; subtracting elapsed time again would
                # double-count the evidence latency.
                remaining = min(stale_remaining, revalidate(stage))
            else:
                remaining = stale_remaining
            if remaining <= 0:
                raise SolveExecutionBudgetExceeded(
                    stage, started_at=sampled_at, deadline=deadline, observed_at=observed_at,
                )
            if _original_brs_owner is not None:
                from .rsi_python_brs_native_dispatch import _original_brs_numeric_tail

                _original_brs_numeric_tail(_original_brs_owner)
        return remaining

    pipeline.set_remaining_timeout(timeout_with_handoff)
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
        native_execution_receipt_sha256=native_execution_receipt_sha256,
        python_handoff_sha256=python_handoff_sha256,
        python_handoff_file_pin=python_handoff_file_pin,
    )
    try:
        preflight = preflight_producer_bundle_publication(root, admission_plan, journal, budget_sha256=budget_sha256)
    except Exception as exc:
        code = getattr(exc, "code", "producer_bundle_transaction_preflight_failed")
        raise NativeProducerBundleTransactionError(code) from exc
    try:
        if lineage_owner is None:
            _ensure_initial_population_window(base_state, _records_from_archive(base_archive), strategy)
        else:
            prior_events = _native_lineage_call(lineage_owner, _original_brs_owner, "validate_before", journal, base_archive, base_state_bytes, strategy,
                                         admission_plan=admission_plan)
            _ensure_append_population_window(base_state, _records_from_archive(base_archive), strategy,
                                             prior_events=prior_events)
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
    if lineage_owner is not None:
        _native_lineage_call(lineage_owner, _original_brs_owner, "retain_before", journal, base_archive, base_state_bytes)
    try:
        checkpoint("producer_prepared_intent")
        if python_handoff is not None:
            if admission_anchor is None:
                if prepared_intent_present():
                    admission_anchor = _verify_python_admission_attempt_anchor(root, python_handoff)
                else:
                    # Retain the admission request before its prepared intent.
                    # A crash on either side of the intent write can then replay
                    # the same anchor instead of reconstructing a missing one.
                    admission_anchor = _persist_python_admission_attempt_anchor(root, python_handoff)
            else:
                _verify_python_admission_attempt_anchor(root, python_handoff)
        if execution_control is None:
            journal_sha256 = persist_producer_bundle_prepared_intent(root, journal, checkpoint=checkpoint)
        else:
            retained = persist_controlled_producer_bundle_intent(
                root, journal, execution_control, checkpoint=checkpoint,
                native_numeric_revalidate=(
                    getattr(checkpoint, "revalidate_after_observation", None)
                    if _original_brs_owner is not None else None
                ),
            )
            checkpoint.bind_retained_deadline(retained.check)
            checkpoint("producer_prepared_intent")
            journal_sha256 = journal.digest()
        anchored_journal = journal
        verify_producer_bundle_python_handoff_anchor(root, journal)
        if prepared_observer is not None:
            # The earlier prepared-intent checkpoint may run before its durable write.
            # Notify once only after the immutable original authority is retained.
            checkpoint("producer_prepared_admission")
            prepared_observer(parse_producer_bundle_publication_journal(journal.to_dict()))
            verify_producer_bundle_prepared_intent(root, journal)
            checkpoint("producer_prepared_admission")
        terminal = inspect_producer_bundle_all_rejected(
            root, journal, preflight=preflight, checkpoint=checkpoint,
        )
        if terminal is not None:
            if lineage_owner is not None:
                _native_lineage_call(lineage_owner, _original_brs_owner, "retain_terminal", terminal, None)
            if evidence_revalidator is not None:
                checkpoint.observe_cancellation_before_evidence("producer_terminal_replay")
                _observe_native_producer_evidence(evidence_revalidator, _original_brs_owner,
                                                 "producer_terminal_replay")
                revalidate = getattr(checkpoint, "revalidate_after_observation", None)
                if callable(revalidate):
                    revalidate("producer_terminal_replay")
                elif strategy._cancelled():
                    raise SolveExecutionCancelled("producer_terminal_replay")
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
                python_handoff_sha256=python_handoff_sha256,
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
        _verify_python_handoff_link(
            root,
            journal_id=journal_id,
            run_id=run_id,
            parent_task_id=parent_task_id,
            task_id=task_id,
            admission_plan=admission_plan,
            native_execution_receipt_sha256=native_execution_receipt_sha256,
            python_handoff_sha256=python_handoff_sha256,
            python_handoff_file_pin=python_handoff_file_pin,
            prepared_journal=anchored_journal,
        )
        if admission_anchor is not None and python_handoff is not None:
            _verify_python_admission_attempt_anchor(root, python_handoff)
        if evidence_revalidator is not None:
            checkpoint.observe_cancellation_before_evidence("producer_all_rejected")
            _observe_native_producer_evidence(evidence_revalidator, _original_brs_owner, "producer_all_rejected")
            revalidate = getattr(checkpoint, "revalidate_after_observation", None)
            if callable(revalidate):
                revalidate("producer_all_rejected")
            elif strategy._cancelled():
                raise SolveExecutionCancelled("producer_all_rejected")
        if lineage_owner is not None:
            _native_lineage_call(lineage_owner, _original_brs_owner, "retain_terminal", terminal, None)
        return NativeProducerBundleTransactionResult(
            journal=journal, preflight=preflight, evaluations=tuple(evaluations),
            admitted_candidate_ids=(), rejected_candidate_ids=tuple(rejected), artifacts=(),
            manifest=None, published_journal=None, publication_status="all_rejected",
            terminal_journal=terminal,
        )

    projection_options = {
        "journal": journal, "strategy": strategy, "lineage_owner": lineage_owner,
        "base_state_bytes": base_state_bytes if lineage_owner is not None else None,
    }
    if _original_brs_owner is None:
        state_after = derive_population_state_after(base_state, base_archive, artifacts, **projection_options)
    else:
        state_after = _derive_population_state_after(
            base_state, base_archive, artifacts, **projection_options, _original_brs_owner=_original_brs_owner,
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
        if producer_multi_episode_publication or _original_brs_owner is not None:
            _native_lineage_call(lineage_owner, _original_brs_owner, "retain_staged", staged, manifest)
        checkpoint("producer_commit")
        if lineage_owner is None:
            published = commit_producer_bundle_publication(root, staged, checkpoint=checkpoint)
        elif _original_brs_owner is not None:
            from .producer_bundle_staging import _commit_original_brs_producer_bundle_publication

            published = _commit_original_brs_producer_bundle_publication(
                root, staged, checkpoint=checkpoint, lineage_owner=_original_brs_owner,
                original_receipt_pin=_original_brs_receipt_pin,
            )
            _native_lineage_call(lineage_owner, _original_brs_owner, "retain_terminal", published, manifest)
        else:
            published = commit_producer_bundle_publication(root, staged, checkpoint=checkpoint,
                                                            lineage_owner=lineage_owner)
            _native_lineage_call(lineage_owner, _original_brs_owner, "retain_terminal", published, manifest)
        _verify_python_handoff_link(
            root,
            journal_id=journal_id,
            run_id=run_id,
            parent_task_id=parent_task_id,
            task_id=task_id,
            admission_plan=admission_plan,
            native_execution_receipt_sha256=native_execution_receipt_sha256,
            python_handoff_sha256=python_handoff_sha256,
            python_handoff_file_pin=python_handoff_file_pin,
            prepared_journal=anchored_journal,
        )
        if admission_anchor is not None and python_handoff is not None:
            _verify_python_admission_attempt_anchor(root, python_handoff)
        if evidence_revalidator is not None:
            # Commit has already crossed its durable unknown marker. This read-only
            # refusal preserves committed evidence; do not interrupt or roll it back.
            _observe_native_producer_evidence(evidence_revalidator, _original_brs_owner, "producer_postcommit")
        archive = CandidateArchive(root, requested_strategy="population", read_only=True)
        records = tuple(archive.records())
        archive.validate_candidate_integrity(require_all=True, records=records)
        committed_state = archive.read_state()
        if committed_state != state_after:
            raise NativeProducerBundleTransactionError("producer_bundle_transaction_readback_invalid")
        strategy._validate_candidate_integrity_state(committed_state)
        strategy._active(committed_state)
        _verify_python_handoff_link(
            root,
            journal_id=journal_id,
            run_id=run_id,
            parent_task_id=parent_task_id,
            task_id=task_id,
            admission_plan=admission_plan,
            native_execution_receipt_sha256=native_execution_receipt_sha256,
            python_handoff_sha256=python_handoff_sha256,
            python_handoff_file_pin=python_handoff_file_pin,
            prepared_journal=anchored_journal,
        )
        if admission_anchor is not None and python_handoff is not None:
            _verify_python_admission_attempt_anchor(root, python_handoff)
        if evidence_revalidator is not None:
            _observe_native_producer_evidence(evidence_revalidator, _original_brs_owner, "producer_return")
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
