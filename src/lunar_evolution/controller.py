"""Durable local scheduler for Hermes-inspired agent sessions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .agent_loop import AgentInputRequired
from .agents import (
    AgentAdapter,
    AgentInvocationError,
    AgentRegistry,
    AgentRequest,
    AgentResult,
    AgentSelectionError,
    RuntimeAgentAdapter,
)
from .algorithm import (
    ACTIVE_EVOLUTION_STRATEGIES,
    LOOP_STRATEGY_RETIRED_MESSAGE,
    MAX_INPUT_FILE_BYTES,
    MAX_INPUT_FILES,
    AlgorithmProblemContract,
    OutputSpec,
    materialize_algorithm_workspace,
)
from .artifacts import ArtifactError, ArtifactStore
from .automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from .budget import BudgetExceeded, BudgetSpec
from .config import Config
from .conversational import (
    CompilationResult,
    ContractCompilationError,
    ContractCompiler,
    build_algorithm_plan,
)
from .evaluator import (
    MAX_ARTIFACT_BYTES,
    Evaluation,
    Evaluator,
    acceptance_evaluator,
    evaluate_output_contract,
)
from .evolution import (
    CANDIDATE_INTEGRITY_SCHEMA_VERSION,
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_LINE_BYTES,
    MAX_SOURCE_BYTES,
    MAX_STATE_BYTES,
    ORDINARY_RECEIPT_FILENAME,
    ORDINARY_RECORD_FILENAME,
    Candidate,
    CandidateArchive,
    CandidateEvaluator,
    CandidateExecution,
    CandidateGenerator,
    CandidateIntegrityAuthority,
    CandidateReceipt,
    CommandCandidateRunner,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    PopulationStrategy,
    StrategyResult,
    _canonical_json_bytes,
    _read_bounded_regular_file,
    build_strategy,
)
from .materialization_delivery import (
    MaterializationDeliveryUncertain,
    delivery_authority,
    finish_materialization_delivery,
    inspect_materialization_delivery,
)
from .materialization_execution import (
    MaterializationExecutionUncertain,
    inspect_materialization_execution,
    publish_materialization_execution,
    recover_materialization_execution,
)
from .materialization_launch import (
    MaterializationLaunchUncertain,
    inspect_launch_intent,
    materialization_lock,
    prepare_launch_intent,
)
from .materialization_publication import (
    publish_materialization_result,
    recover_materialization_result,
)
from .memory import MemoryStore
from .models import Run, RunStatus
from .output_publication import (
    OutputPublicationUncertain,
    publish_outputs,
    recover_output_batch,
    recover_outputs,
)
from .policy import MasterPolicy, PlanDocument, PlanPatch, PolicyDecision
from .process_ownership import (
    ProcessCleanupStatus,
    RegisteredProcess,
    cleanup_registered_processes,
)
from .profiles import ProfileRegistry
from .recovery import RecoveryPolicy, RecoveryProposal
from .routing import DomainRouter, RouteDecision
from .runtime import Runtime, RuntimeExecutionError
from .seed_handoff import SeedAdmissionError, SeedManifest, admit_seed_manifest
from .store import Store
from .worker_ownership import WorkerOwnerLock
from .workers import WorkerService

if TYPE_CHECKING:
    from .bundle_delivery import BundleDeliveryResult
    from .bundle_evolution import MultiFileCandidatePipeline


@dataclass(frozen=True)
class _AutomaticCancelDecision:
    """Cancellation authority selected from one parent lifecycle marker."""

    child_id: str | None = None
    targets: tuple[RegisteredProcess, ...] = ()
    verified: bool = False


class WorkerObservationTimeout(AgentInvocationError):
    """A foreground caller stopped observing a still-active bound worker."""

    def __init__(self, worker_id: str) -> None:
        super().__init__("worker wait timeout; execution remains running")
        self.worker_id = worker_id


class LocalController:
    _RETRY_FEEDBACK_RULES = frozenset(
        {
            "result_contains",
            "artifact_exists",
            "artifact_text_contains",
            "json_parse",
            "json_has_keys",
            "output_valid",
            "artifact_valid",
            "data_profile_valid",
            "evaluation_report_valid",
            "all",
            "any",
        }
    )
    _MAX_RETRY_FEEDBACK_VALUES = 16
    _MAX_RETRY_FEEDBACK_BYTES = 8_000
    _MAX_MATERIALIZATION_RESULT_BYTES = 64 * 1024
    _MAX_WORKER_MATERIALIZED_ARTIFACT_BYTES = 8 * 1024 * 1024
    _MATERIALIZATION_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

    def __init__(
        self,
        config: Config,
        runtime: Runtime,
        evaluator: Evaluator | None = None,
        store: Store | None = None,
        memory: MemoryStore | None = None,
        router: DomainRouter | None = None,
        profiles: ProfileRegistry | None = None,
        runtime_factory: Callable[[], Runtime] | None = None,
        agent_registry: AgentRegistry | None = None,
        max_workers: int = 1,
    ) -> None:
        if not isinstance(max_workers, int) or isinstance(max_workers, bool) or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        if max_workers > 1 and runtime_factory is None:
            raise ValueError("runtime_factory is required when max_workers is greater than 1")
        self.config = config
        self.config.ensure()
        self.store = store or Store(config.database)
        self.store.initialize()
        self.memory = memory or MemoryStore(config.database)
        self.memory.initialize()
        self.runtime = runtime
        self.runtime_factory = runtime_factory
        self.max_workers = max_workers
        # Result delivery and parent cancellation share this lock.  This gives the controller a
        # single winner at the task boundary: cancellation either happens before any handoff
        # artifact is published, or after the task has settled.
        self._active_lock = threading.RLock()
        self._active_runtimes: dict[str, Runtime] = {}
        self._active_agents: dict[str, AgentAdapter] = {}
        # The automatic WorkerService bridge is the sole owner of this composable callback
        # scope.  A controller may nest native runtime scopes on the owning thread, while a
        # second thread is rejected before it can replace the bridge's callbacks.
        self._automatic_observation_lock = threading.RLock()
        self._automatic_observation_owner: int | None = None
        self._automatic_observation_depth = 0
        self._automatic_observation_local = threading.local()
        self._automatic_process_releases: dict[tuple[str, int, int], Callable[[], None]] = {}
        self._runtime_observation_callbacks = threading.local()
        self.evaluator = evaluator
        self.router = router or DomainRouter()
        self.profiles = profiles or ProfileRegistry()
        self.policy = MasterPolicy()
        self.recovery_policy = RecoveryPolicy()
        self.agent_registry = agent_registry or AgentRegistry([
            RuntimeAgentAdapter(runtime, runtime_factory=runtime_factory),
        ])
        self.workers = WorkerService(self.store, self.agent_registry, config.home / "worker-sessions")

    # Explicit worker-session control plane. These methods intentionally do not alter the
    # existing task scheduler or run status semantics.
    def dispatch_worker(self, owner_id: str, **kwargs: Any):
        return self.workers.dispatch(owner_id, **kwargs)

    def send_worker(self, owner_id: str, worker_id: str, content: str):
        return self.workers.send(owner_id, worker_id, content)

    def list_workers(self, owner_id: str, *, running_only: bool = False):
        return self.workers.list(owner_id, running_only=running_only)

    def wait_worker(self, owner_id: str, worker_id: str, timeout: float | None = None):
        return self.workers.wait(owner_id, worker_id, timeout)

    def cancel_worker(self, owner_id: str, worker_id: str):
        return self.workers.cancel(owner_id, worker_id)

    def resume_worker(self, owner_id: str, worker_id: str, **kwargs: Any):
        return self.workers.resume(owner_id, worker_id, **kwargs)

    def read_worker_result(self, owner_id: str, worker_id: str):
        return self.workers.read_result(owner_id, worker_id)

    def dispatch_automatic_solve_worker(self, continuation, *, timeout: float | None = None):
        """Explicitly opt into the native automatic-solve WorkerService bridge."""
        from .automatic_solve_worker_adapter import AutomaticSolveWorkerBridge

        return AutomaticSolveWorkerBridge(self.config, self).dispatch(
            continuation.run_id, continuation, timeout=timeout,
        )

    def read_automatic_solve_worker(self, owner_id: str, worker_id: str):
        from .automatic_solve_worker_adapter import AutomaticSolveWorkerBridge

        return AutomaticSolveWorkerBridge(self.config, self).read(owner_id, worker_id)

    @staticmethod
    def _active_algorithm_contract(
        document: PlanDocument,
    ) -> AlgorithmProblemContract | None:
        """Return a new plan's active contract, rejecting historical loop execution."""
        if document.algorithm_problem is None:
            return None
        contract = AlgorithmProblemContract.from_dict(document.algorithm_problem)
        if contract.evolution.strategy == "loop":
            raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
        return contract

    def _register_algorithm_workspace(self, run: Run, document: PlanDocument) -> None:
        """Materialize the fixed role workspace for a validated algorithm contract."""
        contract = self._active_algorithm_contract(document)
        if contract is None:
            return
        manifest = materialize_algorithm_workspace(run.workspace, contract, document.plan_id, document.version)
        tasks = self.store.list_tasks(run.id)
        if tasks:
            ArtifactStore(run.workspace, self.store, run.id).record(
                manifest, tasks[0].id, kind="algorithm_manifest"
            )
        self.store.append_event(
            run.id,
            "algorithm_contract_registered",
            {
                "problem_id": contract.problem_id,
                "plan_id": document.plan_id,
                "plan_version": document.version,
                "contract_sha256": contract.digest(),
                "evolution_strategy": contract.evolution.strategy,
            },
            event_id=f"event-algorithm-contract-{document.plan_id}-{document.version}",
        )

    def decide(self, goal: str) -> PolicyDecision:
        """Return a bounded deterministic Master decision without creating durable work."""
        return self.policy.decide(goal)

    def create_evolution_run(
        self,
        contract: AlgorithmProblemContract,
        *,
        workspace: str | Path | None = None,
    ) -> Run:
        """Create a ledger-backed run for a local evolution strategy.

        Candidate generation/evaluation is intentionally supplied later by ``run_evolution`` so
        creating a detached handle never needs to instantiate an agent runtime.  The validated
        contract is copied into the run workspace and becomes the immutable local source of truth.
        """
        if not isinstance(contract, AlgorithmProblemContract):
            raise TypeError("contract must be an AlgorithmProblemContract")
        if contract.evolution.strategy == "loop":
            raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
        existing_contract = False
        if workspace is not None:
            # A new ledger row and its canonical contract are both mutations. Inspect an explicit
            # destination first so historical or partial evolution evidence cannot be relabelled.
            existing_contract = CandidateArchive.preflight_new_run_workspace(
                workspace,
                contract,
            )
        run = self.store.create_run(
            f"Evolve algorithm problem {contract.problem_id}",
            workspace=workspace,
            tasks=[
                {
                    "id": "evolution",
                    "title": f"Evolve {contract.problem_id}",
                    "prompt": contract.statement,
                    "acceptance": None,
                }
            ],
        )
        evolution_root = Path(run.workspace) / "evolution"
        if evolution_root.exists() and evolution_root.is_symlink():
            raise EvolutionError("evolution directory must not be a symlink")
        evolution_root.mkdir(parents=True, exist_ok=True)
        contract_path = evolution_root / "contract.json"
        if contract_path.exists() and contract_path.is_symlink():
            raise EvolutionError("evolution contract must not be a symlink")
        if not existing_contract:
            contract_path.write_text(
                json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
        task = self.store.list_tasks(run.id)[0]
        ArtifactStore(run.workspace, self.store, run.id).record(
            contract_path, task.id, kind="evolution_contract"
        )
        self.store.append_event(
            run.id,
            "evolution_configured",
            {
                "problem_id": contract.problem_id,
                "contract_sha256": contract.digest(),
                "strategy": contract.evolution.strategy,
                "workspace": "evolution",
            },
            task_id=task.id,
        )
        return run

    def copy_staged_inputs(self, source_run_id: str, target_run_id: str) -> tuple[str, ...]:
        """Copy verified run inputs into another local run without carrying source paths.

        The target must already have a task (evolution runs do); copied rows use the existing
        ``input_data`` artifact kind and retain the source bytes' digest/size. Repeating the
        operation with identical bytes is idempotent, while a conflicting target file fails
        before any strategy can consume it.
        """
        source_run = self.store.get_run(source_run_id)
        target_run = self.store.get_run(target_run_id)
        if source_run is None or target_run is None:
            raise ValueError("source and target runs must exist")
        target_tasks = self.store.list_tasks(target_run.id)
        if not target_tasks:
            raise EvolutionError("target run has no task to own copied inputs")
        source_root = Path(source_run.workspace).expanduser().resolve(strict=False)
        target_root = Path(target_run.workspace).expanduser().resolve(strict=False)
        target_task = target_tasks[0]
        artifact_store = ArtifactStore(target_root, self.store, target_run.id)
        copied: list[str] = []
        for item in self.store.list_artifacts(source_run.id):
            if item.get("kind") != "input_data":
                continue
            relative = item.get("path")
            expected_digest = item.get("sha256")
            expected_size = item.get("size")
            if (
                not isinstance(relative, str)
                or not relative.startswith("data/raw/")
                or not isinstance(expected_digest, str)
                or not isinstance(expected_size, int)
                or expected_size < 0
                or expected_size > MAX_INPUT_FILE_BYTES
            ):
                raise ArtifactError("source input artifact metadata is malformed")
            source = self._confined_regular_file(source_root, relative)
            if source is None:
                raise ArtifactError(f"source input is missing or unsafe: {relative}")
            content = source.read_bytes()
            if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_digest:
                raise ArtifactError(f"source input digest does not match the ledger: {relative}")
            target = target_root / relative
            if self._raw_path_has_symlink(target_root, target):
                raise ArtifactError(f"target input path is symlinked: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected_digest:
                    raise ArtifactError(f"target input already contains different data: {relative}")
            else:
                temporary = target.with_name(f".{target.name}.tmp")
                temporary.write_bytes(content)
                temporary.replace(target)
            if not any(
                existing.get("path") == relative
                and existing.get("kind") == "input_data"
                and existing.get("sha256") == expected_digest
                for existing in self.store.list_artifacts(target_run.id)
            ):
                artifact_store.record(target, target_task.id, kind="input_data")
            self.store.append_event(
                target_run.id,
                "algorithm_input_copied",
                {"path": relative, "size": expected_size, "sha256": expected_digest},
                task_id=target_task.id,
                event_id=(
                    "event-algorithm-input-copy-"
                    + hashlib.sha256(f"{source_run.id}\0{relative}".encode()).hexdigest()
                ),
            )
            copied.append(relative)
        return tuple(copied)

    def _index_evolution_candidate_integrity_artifacts(
        self,
        run: Run,
        task_id: str,
        ordinary_strategy: PopulationStrategy | None = None,
        *,
        allow_uncommitted_state: bool = False,
    ) -> None:
        """Index published candidate record/receipt sidecars exactly once.

        Candidate sidecars are durable evidence rather than executable outputs.  The archive is
        the authority for which candidate directories are visible, so orphan files under
        ``evolution/candidates`` are ignored.  Imported ``seed-*`` records retain their existing
        artifact kinds; ordinary records receive distinct kinds so consumers cannot confuse a
        verified seed receipt with a native population receipt.  Repeated controller resumes use
        the same ``(path, kind)`` key and do not append duplicate ledger rows.  A changed digest
        for an already indexed key is treated as an integrity conflict and is never silently
        replaced.
        """

        if not isinstance(run, Run):
            raise EvolutionError("evolution candidate artifact run is invalid")
        archive = CandidateArchive(run.workspace)
        workspace = Path(run.workspace).expanduser().resolve(strict=False)
        candidates_root = archive.candidates_root
        records = archive.records()
        if candidates_root.is_symlink() or not candidates_root.is_dir():
            if records:
                raise EvolutionError("evolution candidate artifact tree is invalid")
            return

        ordinary_records = [
            candidate
            for candidate in records
            if candidate.strategy == "population" and not archive._is_seed_candidate(candidate)
        ]
        if ordinary_records:
            if allow_uncommitted_state:
                if ordinary_strategy is not None:
                    state = ordinary_strategy._load_state()
                    authority = ordinary_strategy.integrity_authority
                    try:
                        ordinary_strategy._validate_outcome_history(state)
                    except EvolutionError:
                        # A candidate archive line can be durable while the following outcome or
                        # state write fails. Index only the prefix already bound by the last state
                        # digest; leave the unjournaled suffix invisible to the evidence ledger.
                        marker_names = {
                            "candidate_integrity_schema_version",
                            "candidate_integrity_authority",
                            "candidate_archive_sha256",
                        }
                        if (
                            marker_names.intersection(state) != marker_names
                            or state.get("candidate_integrity_schema_version")
                            != CANDIDATE_INTEGRITY_SCHEMA_VERSION
                        ):
                            raise
                        state_authority = CandidateIntegrityAuthority.from_dict(
                            state["candidate_integrity_authority"]
                        )
                        if state_authority.to_dict() != authority.to_dict():
                            raise EvolutionError(
                                "ordinary_candidate_integrity_authority_mismatch"
                            )
                        committed_digest = state.get("candidate_archive_sha256")
                        prefix_lengths = [
                            length
                            for length in range(len(records) + 1)
                            if archive._candidate_archive_digest(records[:length])
                            == committed_digest
                        ]
                        if not prefix_lengths:
                            raise EvolutionError("ordinary_candidate_archive_mismatch")
                        records = records[: max(prefix_lengths)]
                        pending = ordinary_strategy._pending_offspring(state)
                        committed_outcomes = archive.offspring_outcomes()
                        if pending is not None:
                            committed_outcomes = tuple(
                                item
                                for item in committed_outcomes
                                if item.iteration < pending[0]
                            )
                        ordinary_strategy._validate_outcome_history(
                            state,
                            records=records,
                            outcomes=committed_outcomes,
                        )
                    allowed_delayed_roots = ordinary_strategy._allowed_delayed_root_ids(
                        state,
                        records,
                        outcome_history_validated=True,
                    )
                else:
                    projection = ordinary_records[0].integrity
                    authority_names = {
                        "schema_version",
                        "contract_sha256",
                        "evaluator_kind",
                        "evaluator_fingerprint",
                        "dependency_sha256",
                        "environment_sha256",
                        "runner_fingerprint",
                        "generator_fingerprint",
                    }
                    if not isinstance(projection, dict) or not authority_names <= set(projection):
                        raise EvolutionError("ordinary_candidate_integrity_state_invalid")
                    authority = CandidateIntegrityAuthority.from_dict(
                        {name: projection[name] for name in authority_names}
                    )
                    allowed_delayed_roots = frozenset()
                archive.validate_candidate_integrity(
                    authority=authority,
                    allowed_delayed_root_ids=allowed_delayed_roots,
                    records=records,
                )
            elif ordinary_strategy is not None:
                if ordinary_strategy.archive.workspace != archive.workspace:
                    raise EvolutionError("evolution candidate artifact strategy is invalid")
                ordinary_strategy.validate_ordinary_resume_integrity()
            else:
                # Keep the private hook safe for maintenance callers that do not have the strategy
                # instance.  Normal controller paths pass it so delayed-root journal rules are
                # validated by the full population preflight.
                state = archive.read_state()
                marker_names = {
                    "candidate_integrity_schema_version",
                    "candidate_integrity_authority",
                    "candidate_archive_sha256",
                }
                if marker_names.intersection(state) != marker_names or (
                    state.get("candidate_integrity_schema_version")
                    != CANDIDATE_INTEGRITY_SCHEMA_VERSION
                ):
                    raise EvolutionError("ordinary_candidate_integrity_state_invalid")
                try:
                    authority = CandidateIntegrityAuthority.from_dict(
                        state["candidate_integrity_authority"]
                    )
                except (TypeError, ValueError, EvolutionError) as exc:
                    raise EvolutionError("ordinary_candidate_integrity_state_invalid") from exc
                archive.validate_candidate_integrity(authority=authority)
                if state.get("candidate_archive_sha256") != archive._candidate_archive_digest(
                    records
                ):
                    raise EvolutionError("ordinary_candidate_archive_mismatch")

        sidecar_kinds = {
            "seed": {
                ORDINARY_RECORD_FILENAME: "evolution_seed_record",
                ORDINARY_RECEIPT_FILENAME: "evolution_seed_receipt",
            },
            "ordinary": {
                ORDINARY_RECORD_FILENAME: "evolution_candidate_record",
                ORDINARY_RECEIPT_FILENAME: "evolution_candidate_receipt",
            },
        }
        candidate_artifact_kinds = {
            kind for kinds in sidecar_kinds.values() for kind in kinds.values()
        }

        # Snapshot rows once.  ``Store.add_artifact`` is append-only and gives each insertion a
        # random ID, so path/kind is the stable idempotency key at this boundary.  Historical or
        # concurrent duplicate rows are tolerable only when their exact evidence identity agrees;
        # otherwise a later valid row must not hide a conflicting one through insertion order.
        existing_rows = self.store.list_artifacts(run.id)
        existing: dict[tuple[str, str], dict[str, Any]] = {}
        for row in existing_rows:
            path = row.get("path")
            kind = row.get("kind")
            if (
                not isinstance(path, str)
                or not isinstance(kind, str)
                or kind not in candidate_artifact_kinds
            ):
                continue
            key = (path, kind)
            prior = existing.get(key)
            if prior is not None and (
                prior.get("sha256") != row.get("sha256")
                or prior.get("size") != row.get("size")
            ):
                raise EvolutionError("evolution candidate artifact digest mismatch")
            existing.setdefault(key, row)

        artifacts = ArtifactStore(workspace, self.store, run.id)

        for candidate in records:
            # ``CandidateArchive`` validates candidate IDs and code paths while parsing the
            # append-only archive.  Derive the sidecar directory from the recorded source path so
            # nested filenames (for example ``src/main.py``) are indexed correctly.
            candidate_id = candidate.candidate_id
            is_seed = archive._is_seed_candidate(candidate)
            if is_seed and candidate.strategy == "population":
                # Population seed evidence has a separate commit gate in
                # ``record_committed_seed_admission``. Archive metadata alone is never authority
                # to publish seed sidecars into the evidence ledger, including on the controller
                # exception path. OpenEvolve's seed-shaped terminal candidate retains this generic
                # indexing path because it uses a different strategy transaction.
                continue
            kinds = sidecar_kinds["seed" if is_seed else "ordinary"]
            source_path = workspace / candidate.code_path
            candidate_root = candidates_root / candidate_id
            try:
                source_path.relative_to(candidate_root)
                source_path.relative_to(workspace)
            except ValueError:
                # A malformed or tampered archive is handled by the strategy resume gate.  Do
                # not let optional artifact indexing turn it into a path traversal operation.
                if not is_seed:
                    raise EvolutionError("ordinary_candidate_source_invalid")
                continue
            if self._raw_path_has_symlink(workspace, source_path) or not source_path.is_file():
                if not is_seed:
                    raise EvolutionError("ordinary_candidate_source_invalid")
                continue
            sidecar_dir = source_path.parent
            try:
                sidecar_dir.relative_to(candidate_root)
            except ValueError:
                if not is_seed:
                    raise EvolutionError("ordinary_candidate_source_invalid")
                continue
            for filename, kind in kinds.items():
                path = sidecar_dir / filename
                relative = path.relative_to(workspace).as_posix()
                if self._raw_path_has_symlink(workspace, path):
                    # Symlinked evidence is intentionally not indexed.  The integrity gate will
                    # reject it before a resume can invoke a generator or evaluator.
                    if not is_seed:
                        raise EvolutionError(f"ordinary_candidate_{filename.removesuffix('.json')}_invalid")
                    continue
                if not path.is_file():
                    if not is_seed:
                        raise EvolutionError(f"ordinary_candidate_{filename.removesuffix('.json')}_missing")
                    continue
                if is_seed:
                    try:
                        size = path.stat().st_size
                    except OSError:
                        continue
                    if size > MAX_ARCHIVE_LINE_BYTES:
                        continue
                    content = path.read_bytes()
                else:
                    error = f"ordinary_candidate_{filename.removesuffix('.json')}_invalid"
                    content = _read_bounded_regular_file(
                        path,
                        MAX_ARCHIVE_LINE_BYTES,
                        error=error,
                    )
                    size = len(content)
                    try:
                        payload = json.loads(content.decode("utf-8"))
                        if filename == ORDINARY_RECORD_FILENAME:
                            if _canonical_json_bytes(payload) != _canonical_json_bytes(
                                candidate.to_dict()
                            ):
                                raise EvolutionError("ordinary_candidate_record_mismatch")
                        else:
                            receipt = CandidateReceipt.from_dict(payload)
                            if receipt.receipt_sha256 != candidate.receipt_sha256:
                                raise EvolutionError("ordinary_candidate_receipt_mismatch")
                    except EvolutionError:
                        raise
                    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                        raise EvolutionError(error) from exc
                digest = hashlib.sha256(content).hexdigest()
                prior = existing.get((relative, kind))
                if prior is not None:
                    if prior.get("sha256") != digest or prior.get("size") != size:
                        raise EvolutionError("evolution candidate artifact digest mismatch")
                    continue
                if is_seed:
                    artifact_id = artifacts.record(path, task_id, kind=kind)
                else:
                    # Record the exact no-follow bounded snapshot validated above; a second
                    # path.read_bytes() would reopen a race before the ledger insert.
                    artifact_id = self.store.add_artifact(
                        run.id,
                        task_id,
                        relative,
                        digest,
                        size,
                        kind,
                    )
                existing[(relative, kind)] = {
                    "id": artifact_id,
                    "path": relative,
                    "kind": kind,
                    "sha256": digest,
                    "size": size,
                }

    def run_evolution(
        self,
        run_id: str,
        contract: AlgorithmProblemContract,
        generator: CandidateGenerator,
        evaluator: CandidateEvaluator,
        evolution_config: EvolutionConfig,
        *,
        resume: bool = False,
        seed_manifest: SeedManifest | Mapping[str, Any] | str | os.PathLike[str] | None = None,
        seed_evaluator_kind: str = "exact_harness",
        seed_dependency_sha256: str | None = None,
        seed_environment_sha256: str | None = None,
        bundle_pipeline: MultiFileCandidatePipeline | None = None,
        remaining_timeout: Callable[[str], float] | None = None,
        automatic_parent_id: str | None = None,
    ) -> tuple[Run, StrategyResult]:
        """Execute or resume an evolution strategy while retaining SQLite run authority."""
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        if not isinstance(contract, AlgorithmProblemContract):
            raise TypeError("contract must be an AlgorithmProblemContract")
        if contract.evolution.strategy == "loop":
            raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
        if bundle_pipeline is not None:
            from .bundle_evolution import MultiFileCandidatePipeline

            if not isinstance(bundle_pipeline, MultiFileCandidatePipeline):
                raise TypeError("bundle_pipeline must be a MultiFileCandidatePipeline")
            if seed_manifest is not None:
                raise EvolutionError("bundle_population_seed_import_unsupported")
            evolution_config = bundle_pipeline.configure(evolution_config)
        contract_path = Path(run.workspace) / "evolution" / "contract.json"
        if not contract_path.is_file():
            raise EvolutionError("evolution run is missing its canonical contract")
        try:
            stored_contract = AlgorithmProblemContract.from_dict(
                json.loads(contract_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("canonical evolution contract is invalid") from exc
        if stored_contract.digest() != contract.digest():
            raise EvolutionError("supplied contract does not match the run contract")
        task = self.store.list_tasks(run.id)
        if len(task) != 1:
            raise EvolutionError("evolution run must contain exactly one task")
        evolution_task = task[0]
        process_observer = process_released = None
        attempt = None

        def continuation_guard() -> None:
            if automatic_parent_id is None:
                return
            authority = self._automatic_cancel_targets(automatic_parent_id)
            parent = self.store.get_run(automatic_parent_id)
            current = self.store.get_run(run_id)
            if (authority is None or not authority.verified or authority.child_id != run_id
                    or parent is None or parent.status in {RunStatus.CANCELLED, RunStatus.FAILED}
                    or current is None or current.status == RunStatus.CANCELLED):
                raise SolveExecutionCancelled("evolution")
            if attempt is not None:
                self.ensure_attempt_process_released(run_id, attempt.id, parent_id=automatic_parent_id)

        if seed_manifest is None and (
            seed_dependency_sha256 is not None
            or seed_environment_sha256 is not None
            or seed_evaluator_kind != "exact_harness"
        ):
            raise EvolutionError("seed_manifest_required_for_seed_identity")

        def append_seed_summary_event(event_type: str, summary: dict[str, Any]) -> None:
            summary_digest = hashlib.sha256(
                json.dumps(
                    {"run_id": run.id, "summary": summary},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.store.append_event(
                run.id,
                event_type,
                summary,
                task_id=evolution_task.id,
                event_id=f"event-{event_type.replace('_', '-')}-{summary_digest}",
            )

        def adjudicate_initial_seeds() -> tuple[tuple[Any, ...], dict[str, Any] | None]:
            if seed_manifest is None:
                return (), None
            if evolution_config.strategy != "population":
                raise EvolutionError("verified seeds are supported only by population evolution")
            if evolution_config.evaluator_fingerprint is None:
                raise EvolutionError("verified seeds require a pinned evaluator fingerprint")
            if seed_dependency_sha256 is None or seed_environment_sha256 is None:
                raise EvolutionError(
                    "verified seeds require dependency and environment fingerprints"
                )
            archive = CandidateArchive(run.workspace)
            existing_state = archive.read_state()
            existing_records = archive.records()
            if existing_state or existing_records:
                seed_summary = existing_state.get("seed_admission")
                if not isinstance(seed_summary, dict):
                    raise EvolutionError("verified_seed_cannot_modify_existing_population")

                # Re-admitting a manifest invokes the exact evaluator.  Validate every existing
                # ordinary candidate and its journal first with inert callback boundaries so a
                # tampered mixed archive cannot cause evaluator work before failing closed.
                def reject_preflight_generation(request):
                    del request
                    raise EvolutionError("ordinary integrity preflight generated")

                def reject_preflight_evaluation(path, supplied):
                    del path, supplied
                    raise EvolutionError("ordinary integrity preflight evaluated")

                preflight = PopulationStrategy(
                    EvolutionContext(
                        contract=contract,
                        workspace=Path(run.workspace),
                        generate=reject_preflight_generation,
                        evaluate=reject_preflight_evaluation,
                        config=evolution_config,
                        evaluator_kind=seed_evaluator_kind,
                        dependency_sha256=seed_dependency_sha256,
                        environment_sha256=seed_environment_sha256,
                    )
                )
                preflight.validate_ordinary_resume_integrity()
                marker = read_bounded_evolution_json(
                    archive.seed_commit_path,
                    "verified_seed_commit_evidence_mismatch",
                )
                if marker.get("admission_sha256") != seed_summary.get("admission_sha256"):
                    raise EvolutionError("verified_seed_commit_evidence_mismatch")
            try:
                admission = admit_seed_manifest(
                    seed_manifest,
                    contract,
                    evaluator,
                    evaluator_kind=seed_evaluator_kind,
                    evaluator_fingerprint=evolution_config.evaluator_fingerprint,
                    dependency_sha256=seed_dependency_sha256,
                    environment_sha256=seed_environment_sha256,
                    staging_root=Path(run.workspace) / "evolution",
                    num_islands=evolution_config.num_islands,
                )
            except SeedAdmissionError as exc:
                failure = {
                    "schema_version": "1",
                    "code": exc.code,
                    "rejected": [
                        {
                            "index": item.index,
                            "identity": item.identity,
                            "code": item.code,
                        }
                        for item in (exc.result.rejected if exc.result is not None else ())
                    ],
                }
                failure_digest = hashlib.sha256(
                    json.dumps(
                        {"run_id": run.id, "failure": failure},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                self.store.append_event(
                    run.id,
                    "seed_admission_failed",
                    failure,
                    task_id=evolution_task.id,
                    event_id=f"event-seed-admission-failed-{failure_digest}",
                )
                raise EvolutionError(exc.code) from exc
            admitted = tuple(sorted(admission.admitted, key=lambda item: item.candidate_id))
            summary: dict[str, Any] = {
                "schema_version": "1",
                "admitted": [
                    {
                        "candidate_id": item.candidate_id,
                        "handoff_sha256": item.handoff_sha256,
                        "receipt_sha256": item.receipt.receipt_sha256,
                    }
                    for item in admitted
                ],
                "rejected": [
                    {"index": item.index, "identity": item.identity, "code": item.code}
                    for item in admission.rejected
                ],
            }
            append_seed_summary_event("seed_admission_adjudicated", summary)
            return admitted, summary

        def read_bounded_evolution_json(path: Path, code: str) -> dict[str, Any]:
            try:
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or path.stat().st_size > MAX_STATE_BYTES
                ):
                    raise EvolutionError(code)
                payload = json.loads(
                    _read_bounded_regular_file(path, MAX_STATE_BYTES, error=code).decode("utf-8")
                )
            except EvolutionError:
                raise
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvolutionError(code) from exc
            if not isinstance(payload, dict):
                raise EvolutionError(code)
            return payload

        def record_committed_seed_admission(summary: dict[str, Any] | None) -> None:
            if summary is None:
                return
            evolution_root = Path(run.workspace) / "evolution"
            state = read_bounded_evolution_json(
                evolution_root / "state.json", "verified_seed_commit_evidence_mismatch"
            )
            marker = read_bounded_evolution_json(
                evolution_root / "seed-commit.json", "verified_seed_commit_evidence_mismatch"
            )
            seed_admission = state.get("seed_admission")
            state_seeds = seed_admission.get("seeds") if isinstance(seed_admission, dict) else None
            if not isinstance(state_seeds, list):
                raise EvolutionError("verified_seed_commit_evidence_mismatch")
            persisted = []
            for item in state_seeds:
                if not isinstance(item, dict):
                    raise EvolutionError("verified_seed_commit_evidence_mismatch")
                projected = {
                    "candidate_id": item.get("candidate_id"),
                    "handoff_sha256": item.get("handoff_sha256"),
                    "receipt_sha256": item.get("receipt_sha256"),
                }
                if any(not isinstance(value, str) for value in projected.values()):
                    raise EvolutionError("verified_seed_commit_evidence_mismatch")
                persisted.append(projected)
            persisted.sort(key=lambda item: item["candidate_id"])
            admitted = summary.get("admitted")
            candidate_ids = [item["candidate_id"] for item in persisted]
            if (
                persisted != admitted
                or marker.get("candidate_ids") != candidate_ids
                or marker.get("admission_sha256") != seed_admission.get("admission_sha256")
            ):
                raise EvolutionError("verified_seed_commit_evidence_mismatch")

            artifacts = ArtifactStore(run.workspace, self.store, run.id)
            archived = {
                candidate.candidate_id: candidate
                for candidate in CandidateArchive(run.workspace).records()
            }
            if any(candidate_id not in archived for candidate_id in candidate_ids):
                raise EvolutionError("verified_seed_commit_evidence_mismatch")
            evidence_paths = [("evolution/seed-commit.json", "evolution_seed_commit")]
            for candidate_id in candidate_ids:
                source = Path(run.workspace) / archived[candidate_id].code_path
                try:
                    sidecar_parent = source.parent.relative_to(Path(run.workspace)).as_posix()
                except ValueError as exc:
                    raise EvolutionError("verified_seed_commit_evidence_mismatch") from exc
                evidence_paths.extend(
                    (
                        (f"{sidecar_parent}/record.json", "evolution_seed_record"),
                        (f"{sidecar_parent}/receipt.json", "evolution_seed_receipt"),
                    )
                )
            existing = {
                (item["path"], item["kind"])
                for item in self.store.list_artifacts(run.id)
            }
            for relative, kind in evidence_paths:
                path = Path(run.workspace) / relative
                if (relative, kind) not in existing:
                    artifacts.record(path, evolution_task.id, kind=kind)
            append_seed_summary_event("seed_admission_committed", summary)

        def require_terminal_strategy_state(terminal_run: Run) -> None:
            state_path = Path(terminal_run.workspace) / "evolution" / "state.json"
            if not state_path.exists() and not state_path.is_symlink():
                raise EvolutionError("terminal_evolution_state_missing")
            state = read_bounded_evolution_json(
                state_path, "terminal_evolution_state_invalid"
            )
            expected_statuses = {
                RunStatus.SUCCEEDED: {"completed", "stagnated"},
                RunStatus.FAILED: {"failed"},
                RunStatus.CANCELLED: {"cancelled"},
            }
            if (
                terminal_run.status not in expected_statuses
                or state.get("status") not in expected_statuses[terminal_run.status]
                or state.get("strategy") != evolution_config.strategy
                or state.get("contract_sha256") != contract.digest()
                or state.get("config") != evolution_config.to_dict()
            ):
                raise EvolutionError("terminal_evolution_state_mismatch")
            if evolution_config.strategy == "population":
                has_seed_state = isinstance(state.get("seed_admission"), dict)
                if has_seed_state != (seed_manifest is not None):
                    raise EvolutionError("terminal_evolution_seed_manifest_mismatch")
                marker_path = state_path.with_name("seed-commit.json")
                has_seed_marker = marker_path.exists() or marker_path.is_symlink()
                if has_seed_marker != has_seed_state:
                    raise EvolutionError("terminal_evolution_seed_state_mismatch")
                if has_seed_state:
                    marker = read_bounded_evolution_json(
                        marker_path, "terminal_evolution_seed_state_mismatch"
                    )
                    if marker.get("admission_sha256") != state["seed_admission"].get(
                        "admission_sha256"
                    ):
                        raise EvolutionError("terminal_evolution_seed_state_mismatch")

        def configured_strategy(
            admitted_seeds: tuple[Any, ...],
            adjudication_summary: dict[str, Any] | None,
        ):
            def observe(event: str, payload: dict[str, Any]) -> None:
                self._observe_evolution(run_id, evolution_task.id, event, payload)
                if event == "state" and "seed_admission" in payload:
                    record_committed_seed_admission(adjudication_summary)

            context = EvolutionContext(
                contract=contract,
                workspace=Path(run.workspace),
                generate=generator,
                evaluate=evaluator,
                config=evolution_config,
                initial_seeds=admitted_seeds,
                bundle_pipeline=bundle_pipeline,
                # Bind native offspring receipts to the same evaluator/dependency/environment
                # authority as an admitted seed batch.  For ordinary runs these remain unset and
                # the evolution layer resolves its path-free native protocol defaults.
                evaluator_kind=seed_evaluator_kind if admitted_seeds else None,
                dependency_sha256=seed_dependency_sha256 if admitted_seeds else None,
                environment_sha256=seed_environment_sha256 if admitted_seeds else None,
                cancelled=lambda: (
                    (latest := self.store.get_run(run_id)) is None
                    or latest.status == RunStatus.CANCELLED
                ),
                observe=observe,
                remaining_timeout=remaining_timeout,
                process_observer=process_observer,
                process_released=process_released,
                continuation_guard=continuation_guard if automatic_parent_id is not None else None,
            )
            return build_strategy(context)

        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            try:
                require_terminal_strategy_state(run)
                admitted_seeds, summary = adjudicate_initial_seeds()
                strategy = configured_strategy(admitted_seeds, summary)
                result = strategy.resume()
                record_committed_seed_admission(summary)
                self._index_evolution_candidate_integrity_artifacts(
                    run,
                    evolution_task.id,
                    strategy if isinstance(strategy, PopulationStrategy) else None,
                )
                return run, result
            except EvolutionError:
                raise
            except Exception as exc:
                raise EvolutionError("terminal_evolution_resume_failed") from exc
        if resume:
            self.store.recover_running(run.id)
        attempt = self.store.claim_task(evolution_task.id, f"evolution:{evolution_config.strategy}")
        if attempt is None:
            latest = self.store.get_run(run.id)
            if latest is not None and latest.status == RunStatus.CANCELLED:
                try:
                    require_terminal_strategy_state(latest)
                    admitted_seeds, summary = adjudicate_initial_seeds()
                    strategy = configured_strategy(admitted_seeds, summary)
                    result = strategy.resume()
                    record_committed_seed_admission(summary)
                    self._index_evolution_candidate_integrity_artifacts(
                        latest,
                        evolution_task.id,
                        strategy if isinstance(strategy, PopulationStrategy) else None,
                    )
                    return latest, result
                except EvolutionError:
                    raise
                except Exception as exc:
                    raise EvolutionError("terminal_evolution_resume_failed") from exc
            raise EvolutionError("evolution task is already claimed or not runnable")
        self.store.append_event(
            run.id,
            "evolution_started",
            {
                "strategy": evolution_config.strategy,
                "resume": resume,
                "contract_sha256": contract.digest(),
            },
            task_id=evolution_task.id,
        )
        strategy = None
        if automatic_parent_id is not None:
            process_observer, process_released = self.attempt_process_observers(
                run.id, attempt.id, parent_id=automatic_parent_id,
            )
        runtime_scope = self.observe_attempt_runtime(
            run.id, attempt.id, parent_id=automatic_parent_id,
        ) if automatic_parent_id is not None else None
        try:
            if runtime_scope is not None:
                runtime_scope.__enter__()
            continuation_guard()
            admitted_seeds, summary = adjudicate_initial_seeds()
            strategy = configured_strategy(admitted_seeds, summary)
            result = strategy.resume() if resume else strategy.run()
            continuation_guard()
            record_committed_seed_admission(summary)
            self._index_evolution_candidate_integrity_artifacts(
                run,
                evolution_task.id,
                strategy if isinstance(strategy, PopulationStrategy) else None,
            )
            result_path = Path(run.workspace) / "evolution" / "result.json"
            result_path.write_text(
                json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            artifacts = ArtifactStore(run.workspace, self.store, run.id)
            execution_root = Path(run.workspace) / "evolution" / "candidates"
            if execution_root.is_dir() and not execution_root.is_symlink():
                for execution_path in sorted(execution_root.glob("*/execution.json")):
                    if execution_path.is_symlink() or not execution_path.is_file():
                        continue
                    relative = execution_path.resolve(strict=False).relative_to(
                        Path(run.workspace).resolve()
                    )
                    if not any(
                        item["path"] == relative.as_posix()
                        and item["kind"] == "candidate_execution"
                        for item in self.store.list_artifacts(run.id)
                    ):
                        artifacts.record(
                            execution_path,
                            evolution_task.id,
                            kind="candidate_execution",
                        )
                    try:
                        execution = CandidateExecution.from_dict(
                            json.loads(execution_path.read_text(encoding="utf-8"))
                        )
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                        continue
                    for declared in execution.artifacts:
                        declared_path = execution_path.parent / declared
                        if declared_path.is_symlink() or not declared_path.is_file():
                            continue
                        try:
                            declared_path.resolve(strict=False).relative_to(
                                Path(run.workspace).resolve()
                            )
                        except ValueError:
                            continue
                        relative_declared = declared_path.resolve(strict=False).relative_to(
                            Path(run.workspace).resolve()
                        )
                        if not any(
                            item["path"] == relative_declared.as_posix()
                            and item["kind"] == "candidate_execution_output"
                            for item in self.store.list_artifacts(run.id)
                        ):
                            artifacts.record(
                                declared_path,
                                evolution_task.id,
                                kind="candidate_execution_output",
                            )
            for relative, kind in (
                ("evolution/archive.jsonl", "evolution_archive"),
                ("evolution/offspring-outcomes.jsonl", "evolution_offspring_outcomes"),
                ("evolution/seed-commit.json", "evolution_seed_commit"),
                ("evolution/state.json", "evolution_state"),
                ("evolution/result.json", "result"),
            ):
                path = Path(run.workspace) / relative
                if path.is_file() and not any(
                    item["path"] == relative and item["kind"] == kind
                    for item in self.store.list_artifacts(run.id)
                ):
                    artifacts.record(path, evolution_task.id, kind=kind)
            self.store.append_event(
                run.id,
                "evolution_finished",
                result.to_dict(),
                task_id=evolution_task.id,
            )
            if result.status == "failed":
                self.store.append_event(
                    run.id,
                    "evolution_failed",
                    result.to_dict(),
                    task_id=evolution_task.id,
                )
            success = result.status in {"completed", "stagnated"} and result.best_candidate_id is not None
            if result.status == "cancelled":
                # A concurrent ``cancel`` already settled the task; do not overwrite it.
                self.store.append_event(run.id, "evolution_cancelled", result.to_dict(), task_id=evolution_task.id)
            else:
                self.store.finish_task(
                    evolution_task.id,
                    attempt.id,
                    success,
                    result_path="evolution/result.json",
                    error=result.error if not success else None,
                )
            settled = self.store.settle_run(run.id)
            return settled or run, result
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            # The automatic parent owns stop classification and terminal precedence. Do not
            # turn its shared deadline into an ordinary candidate/evolution failure.
            raise
        except Exception as exc:
            try:
                self._index_evolution_candidate_integrity_artifacts(
                    run,
                    evolution_task.id,
                    strategy if isinstance(strategy, PopulationStrategy) else None,
                    allow_uncommitted_state=True,
                )
            except Exception as indexing_exc:  # noqa: BLE001 - preserve the original failure
                # Preserve the strategy/storage failure. This best-effort pass only prevents a
                # fully validated published prefix from disappearing from the evidence ledger.
                del indexing_exc
            error = " ".join(str(exc).split())[-2_000:] or "evolution failed"
            self.store.append_event(
                run.id,
                "evolution_failed",
                {"error": error, "strategy": evolution_config.strategy},
                task_id=evolution_task.id,
            )
            self.store.finish_task(
                evolution_task.id,
                attempt.id,
                False,
                result_path=None,
                error=error,
            )
            settled = self.store.settle_run(run.id)
            raise EvolutionError(error) from exc
        finally:
            if runtime_scope is not None:
                runtime_scope.__exit__(None, None, None)

    def deliver_bundle_evolution(
        self, run_id: str, destination_root: str | Path,
    ) -> BundleDeliveryResult:
        """Copy selected source and scored snapshots into a new portable private directory."""
        from .bundle_delivery import publish_bundle_delivery

        identity, materials, _ = self._verified_bundle_evolution_delivery(run_id)
        run = self.store.get_run(run_id)
        try:
            destination = Path(destination_root).expanduser().absolute()
            evidence_root = Path(run.workspace) / "evolution"
            if any(parent.samefile(evidence_root) for parent in (destination, *destination.parents)):
                raise EvolutionError("bundle_delivery_destination_conflict")
            return publish_bundle_delivery(destination, identity=identity, materials=materials)
        except (OSError, TypeError, ValueError) as exc:
            raise EvolutionError("bundle_delivery_invalid") from exc

    def _verified_bundle_evolution_delivery(self, run_id: str):
        """Read the ledger-bound selected bundle without allocating a delivery or running code."""
        from .bundle_evolution import read_bundle_delivery_materials

        run = self.store.get_run(run_id)
        if run is None or run.status != RunStatus.SUCCEEDED:
            raise EvolutionError("bundle_delivery_requires_successful_run")
        workspace = Path(run.workspace)
        try:
            # Store artifact rows bind the completed selection, preventing a later archive/state
            # rewrite from silently choosing a different candidate for the same finished run.
            snapshots = self._materialization_artifact_snapshots(run, workspace)
            contract_path = workspace / "evolution" / "contract.json"
            contract_bytes = _read_bounded_regular_file(
                contract_path, MAX_STATE_BYTES, error="bundle_delivery_contract_invalid",
            )
            contract_rows = [row for row in self.store.list_artifacts(run.id)
                             if row.get("path") == "evolution/contract.json"
                             and row.get("kind") == "evolution_contract"]
            if not contract_rows or any(
                row.get("sha256") != hashlib.sha256(contract_bytes).hexdigest()
                or row.get("size") != len(contract_bytes) for row in contract_rows
            ):
                raise EvolutionError("bundle_delivery_contract_invalid")
            contract = AlgorithmProblemContract.from_dict(json.loads(contract_bytes))
            state = json.loads(snapshots["evolution/state.json"])
            payload = json.loads(snapshots["evolution/result.json"])
            result = StrategyResult(**payload)
            if (result.strategy != "population" or result.status not in {"completed", "stagnated"}
                    or state.get("status") != result.status
                    or state.get("iteration") != result.iterations):
                raise EvolutionError("bundle_delivery_selection_invalid")
            stored_config = dict(state["config"])
            if stored_config.pop("command_sha256", None) is not None:
                raise EvolutionError("bundle_delivery_configuration_invalid")
            config = EvolutionConfig(**stored_config)

            def inactive(*args):
                del args
                raise EvolutionError("bundle_delivery_execution_forbidden")

            strategy = PopulationStrategy(EvolutionContext(
                contract=contract, workspace=workspace, generate=inactive, evaluate=inactive,
                config=config,
            ), read_only=True)
            strategy.validate_ordinary_resume_integrity()
            archive = strategy.archive
            canonical_result = archive.result(
                result.strategy, result.status, result.iterations, result.error,
            )
            if _canonical_json_bytes(canonical_result.to_dict()) != _canonical_json_bytes(payload):
                raise EvolutionError("bundle_delivery_selection_invalid")
            self._validate_materialization_child_events(run, contract, result)
            selected = archive.best()
            if selected is None or selected.bundle_evidence is None:
                raise EvolutionError("bundle_delivery_requires_bundle_candidate")
            sidecars = {
                (Path(candidate.code_path).parent / filename).as_posix(): (kind, MAX_ARCHIVE_LINE_BYTES)
                for candidate in archive.records()
                for filename, kind in (
                    (ORDINARY_RECORD_FILENAME, "evolution_candidate_record"),
                    (ORDINARY_RECEIPT_FILENAME, "evolution_candidate_receipt"),
                )
            }
            bound = self._materialization_artifact_snapshots(run, workspace, additional=sidecars)
            if any(bound[name] != content for name, content in snapshots.items()):
                raise EvolutionError("bundle_delivery_selection_invalid")
            snapshots = bound
            materials = read_bundle_delivery_materials(
                workspace, selected, authority=strategy.integrity_authority,
            )
            # Material reads must not let an intervening selection rewrite escape the original
            # ledger-bound snapshots. Publication receives immutable bytes after this check.
            if snapshots != self._materialization_artifact_snapshots(run, workspace, additional=sidecars):
                raise EvolutionError("bundle_delivery_selection_invalid")
            identity = {
                "candidate_id": selected.candidate_id,
                "contract_sha256": contract.digest(),
                "bundle_sha256": selected.bundle_evidence["bundle_sha256"],
                "receipt_sha256": selected.receipt_sha256,
                "evaluation_sha256": selected.bundle_evidence["evaluation_sha256"],
            }
            return identity, materials, canonical_result
        except EvolutionError:
            raise
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise EvolutionError("bundle_delivery_invalid") from exc

    def deliver_bundle_to_parent(
        self, parent_id: str, child_id: str, contract: AlgorithmProblemContract,
        result: StrategyResult,
        *, continuation_guard: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Publish an already scored bundle through the parent run's recoverable output batch."""
        from .bundle_parent_delivery import finish_bundle_parent_delivery

        return finish_bundle_parent_delivery(
            self, parent_id, child_id, contract, result,
            continuation_guard=continuation_guard,
        )

    @staticmethod
    def _decode_materialization_identity_json(
        content: bytes,
        error: str,
    ) -> dict[str, Any]:
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvolutionError(error) from exc
        if not isinstance(payload, dict):
            raise EvolutionError(error)
        return payload

    def _materialization_artifact_snapshots(
        self,
        child: Run,
        child_root: Path,
        *,
        additional: dict[str, tuple[str, int]] | None = None,
    ) -> dict[str, bytes]:
        """Read terminal evidence only when its immutable ledger identity still agrees."""

        specifications = {
            "evolution/archive.jsonl": ("evolution_archive", MAX_ARCHIVE_BYTES),
            "evolution/state.json": ("evolution_state", MAX_STATE_BYTES),
            "evolution/result.json": ("result", MAX_STATE_BYTES),
            **(additional or {}),
        }
        tasks = self.store.list_tasks(child.id)
        if len(tasks) != 1:
            raise EvolutionError("materialization evolution task identity is invalid")
        task_id = tasks[0].id
        rows = self.store.list_artifacts(child.id)
        snapshots: dict[str, bytes] = {}
        for relative, (kind, limit) in specifications.items():
            matching = [
                row
                for row in rows
                if row.get("path") == relative and row.get("kind") == kind
            ]
            if not matching or any(row.get("task_id") != task_id for row in matching):
                raise EvolutionError("materialization evolution artifact ledger is incomplete")
            identities = {
                (row.get("sha256"), row.get("size")) for row in matching
            }
            if len(identities) != 1:
                raise EvolutionError("materialization evolution artifact ledger is inconsistent")
            path = self._confined_regular_file(child_root, relative)
            if path is None:
                raise EvolutionError("materialization evolution artifact is missing or unsafe")
            content = _read_bounded_regular_file(
                path,
                limit,
                error="materialization evolution artifact is missing or unsafe",
            )
            expected_digest, expected_size = next(iter(identities))
            if (
                not isinstance(expected_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
                or isinstance(expected_size, bool)
                or not isinstance(expected_size, int)
                or expected_size != len(content)
                or expected_digest != hashlib.sha256(content).hexdigest()
            ):
                raise EvolutionError("materialization evolution artifact digest mismatch")
            snapshots[relative] = content
        return snapshots

    @staticmethod
    def _materialization_archive_records(content: bytes) -> tuple[Candidate, ...]:
        """Parse the exact archive snapshot authenticated by the child artifact ledger."""

        records: list[Candidate] = []
        seen: set[str] = set()
        try:
            for line in content.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                if len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES:
                    raise EvolutionError("materialization candidate archive is invalid")
                payload = json.loads(line)
                candidate = Candidate.from_dict(payload)
                if candidate.bundle_evidence is not None:
                    raise EvolutionError("bundle_candidate_requires_bundle_delivery")
                if isinstance(payload, dict) and {
                    "source_sha256",
                    "receipt_sha256",
                    "integrity",
                }.intersection(payload):
                    expected_fields = {
                        "candidate_id",
                        "code_path",
                        "parent_id",
                        "generation",
                        "iteration",
                        "strategy",
                        "island_id",
                        "evaluation",
                        "metadata",
                        "created_at",
                        "source_sha256",
                        "receipt_sha256",
                        "integrity",
                    }
                    if set(payload) != expected_fields or _canonical_json_bytes(
                        payload
                    ) != _canonical_json_bytes(candidate.to_dict()):
                        raise EvolutionError("materialization candidate archive is invalid")
                if candidate.candidate_id in seen:
                    raise EvolutionError("materialization candidate archive is invalid")
                seen.add(candidate.candidate_id)
                records.append(candidate)
        except EvolutionError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("materialization candidate archive is invalid") from exc
        return tuple(records)

    def _validate_materialization_child_events(
        self,
        child: Run,
        contract: AlgorithmProblemContract,
        result: StrategyResult,
    ) -> None:
        events = self.store.list_events(child.id)
        started = [
            event.get("payload")
            for event in events
            if event.get("type") == "evolution_started"
        ]
        if not started or any(
            not isinstance(payload, dict)
            or payload.get("strategy") != result.strategy
            or payload.get("contract_sha256") != contract.digest()
            for payload in started
        ):
            raise EvolutionError("materialization evolution start event does not match the result")
        finished = [
            event.get("payload")
            for event in events
            if event.get("type") == "evolution_finished"
        ]
        try:
            expected = _canonical_json_bytes(result.to_dict())
            if not finished or any(
                not isinstance(payload, dict)
                or _canonical_json_bytes(payload) != expected
                for payload in finished
            ):
                raise EvolutionError(
                    "materialization evolution finish event does not match the result"
                )
        except (TypeError, ValueError) as exc:
            raise EvolutionError("materialization evolution finish event is invalid") from exc

    def _validate_materialization_links(
        self,
        parent: Run,
        child: Run,
        contract: AlgorithmProblemContract,
        strategy: str,
    ) -> None:
        parent_links = [
            event.get("payload")
            for event in self.store.list_events(parent.id)
            if event.get("type") == "evolution_linked"
        ]
        if parent_links:
            matching = [
                payload
                for payload in parent_links
                if isinstance(payload, dict)
                and payload.get("evolution_run_id") == child.id
            ]
            if not matching or any(
                payload.get("contract_sha256") != contract.digest()
                or payload.get("strategy") != strategy
                for payload in matching
            ):
                raise EvolutionError("materialization evolution link does not match the result")

        child_links = [
            event.get("payload")
            for event in self.store.list_events(child.id)
            if event.get("type") == "evolution_parent_linked"
        ]
        if child_links:
            matching = [
                payload
                for payload in child_links
                if isinstance(payload, dict) and payload.get("parent_run_id") == parent.id
            ]
            if not matching or any(
                payload.get("contract_sha256") != contract.digest()
                or (
                    payload.get("strategy") is not None
                    and payload.get("strategy") != strategy
                )
                for payload in matching
            ):
                raise EvolutionError("materialization parent link does not match the result")

    def _validate_materialization_result_identity(
        self,
        child: Run,
        contract: AlgorithmProblemContract,
        result: StrategyResult,
    ) -> bytes:
        child_root = Path(child.workspace).expanduser().resolve(strict=False)
        snapshots = self._materialization_artifact_snapshots(child, child_root)
        state = self._decode_materialization_identity_json(
            snapshots["evolution/state.json"],
            "materialization evolution state is missing or invalid",
        )
        state_strategy = state.get("strategy")
        if state_strategy == "loop":
            raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
        if (
            state_strategy != result.strategy
            or state.get("contract_sha256") != contract.digest()
            or state.get("status") != result.status
            or state.get("iteration") != result.iterations
            or state.get("best_candidate_id") != result.best_candidate_id
            or state.get("error") != result.error
            or not isinstance(state.get("config"), dict)
            or state["config"].get("strategy") != result.strategy
        ):
            raise EvolutionError("materialization evolution state does not match the result")

        persisted_result = self._decode_materialization_identity_json(
            snapshots["evolution/result.json"],
            "materialization evolution result is missing or invalid",
        )
        try:
            if _canonical_json_bytes(persisted_result) != _canonical_json_bytes(result.to_dict()):
                raise EvolutionError("materialization result does not match the child run")
        except (TypeError, ValueError) as exc:
            raise EvolutionError("materialization evolution result is invalid") from exc

        self._validate_materialization_child_events(child, contract, result)

        try:
            archive = CandidateArchive(child_root)
            expected_archive_path = archive.archive_path.relative_to(child_root).as_posix()
            if result.archive_path != expected_archive_path:
                raise EvolutionError("materialization archive path does not match the child run")
            records = self._materialization_archive_records(
                snapshots["evolution/archive.jsonl"]
            )
            strategies = {candidate.strategy for candidate in records}
            if "loop" in strategies:
                raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
            if strategies != {result.strategy}:
                raise EvolutionError(
                    "materialization candidate strategy does not match the result"
                )
            valid = [candidate for candidate in records if candidate.evaluation.validity == 1]
            best = max(valid, key=lambda candidate: candidate.evaluation.combined_score)
            candidate = self._confined_regular_file(child_root, best.code_path)
            expected_source_sha256 = best.source_sha256
            if expected_source_sha256 is None:
                handoff = best.metadata.get("seed_handoff")
                if (
                    not isinstance(handoff, dict)
                    or handoff.get("candidate_id") != best.candidate_id
                    or handoff.get("contract_sha256") != contract.digest()
                    or not isinstance(handoff.get("source_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", handoff["source_sha256"])
                ):
                    raise EvolutionError(
                        "materialization candidate does not match the child archive"
                    )
                expected_source_sha256 = handoff["source_sha256"]
            if (
                candidate is None
                or best.candidate_id != result.best_candidate_id
                or best.code_path != result.best_candidate_path
            ):
                raise EvolutionError("materialization candidate does not match the child archive")
            candidate_root = (
                child_root / "evolution" / "candidates" / best.candidate_id
            ).resolve(strict=False)
            try:
                candidate.relative_to(candidate_root)
            except ValueError as exc:
                raise EvolutionError(
                    "materialization candidate does not match the child archive"
                ) from exc
            candidate_bytes = _read_bounded_regular_file(
                candidate,
                MAX_SOURCE_BYTES,
                error="materialization candidate source is missing or invalid",
            )
            if hashlib.sha256(candidate_bytes).hexdigest() != expected_source_sha256:
                raise EvolutionError("materialization candidate digest does not match its archive")
            canonical = StrategyResult(
                strategy=result.strategy,
                status=result.status,
                iterations=result.iterations,
                evaluated_candidates=len(records),
                valid_candidates=len(valid),
                best_candidate_id=best.candidate_id,
                best_score=best.evaluation.combined_score,
                archive_path=expected_archive_path,
                error=result.error,
                best_candidate_path=best.code_path,
            )
            if _canonical_json_bytes(canonical.to_dict()) != _canonical_json_bytes(
                result.to_dict()
            ):
                raise EvolutionError("materialization candidate does not match the child archive")
            return candidate_bytes
        except EvolutionError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("materialization candidate archive is invalid") from exc

    def materialize_evolved_outputs(
        self,
        parent_run_id: str,
        evolution_run_id: str,
        contract: AlgorithmProblemContract,
        result: StrategyResult,
        *,
        timeout_seconds: float = 900.0,
    ) -> dict[str, Any]:
        """Execute one selected Python candidate and promote independently verified data.

        Evolution scores select source; they do not authorize delivery.  This phase therefore
        copies the selected source and hashed inputs into a deterministic child-run attempt,
        executes it with a minimal environment, applies the immutable parent ``OutputSpec``
        contract, and promotes only matching bytes.  Durable launch intent prevents automatic
        relaunch; complete terminal evidence reuses success or failure across ``solve --resume``.
        """
        if not isinstance(contract, AlgorithmProblemContract):
            raise TypeError("contract must be an AlgorithmProblemContract")
        if not isinstance(result, StrategyResult):
            raise TypeError("result must be a StrategyResult")
        if contract.evolution.strategy == "loop" or result.strategy == "loop":
            raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
        if result.strategy not in ACTIVE_EVOLUTION_STRATEGIES:
            raise EvolutionError("unsupported evolution result strategy")
        if not contract.outputs:
            return {
                "schema_version": "1",
                "status": "skipped",
                "reason": "algorithm contract declares no outputs",
            }
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
            or timeout_seconds > 86_400
        ):
            raise ValueError("materialization timeout must be between 0 and 86400 seconds")

        _parent, child, _candidate = self._validate_materialization_request(
            parent_run_id, evolution_run_id, contract, result,
        )
        with materialization_lock(child):
            # State may have changed between the read-only entry validation and lock acquisition.
            parent, current_child, candidate_bytes = self._validate_materialization_request(
                parent_run_id, evolution_run_id, contract, result,
            )
            if current_child.workspace != child.workspace:
                raise EvolutionError("materialization workspace changed before lock acquisition")
            return self._materialize_evolved_outputs_locked(
                parent, current_child, contract, result, candidate_bytes,
                timeout_seconds=float(timeout_seconds),
            )

    def _validate_materialization_request(
        self,
        parent_run_id: str,
        evolution_run_id: str,
        contract: AlgorithmProblemContract,
        result: StrategyResult,
    ) -> tuple[Run, Run, bytes]:
        parent = self.store.get_run(parent_run_id)
        child = self.store.get_run(evolution_run_id)
        if parent is None or child is None:
            raise ValueError("parent and evolution runs must exist")
        parent_contract = self._algorithm_contract(parent)
        if parent_contract is None or parent_contract.digest() != contract.digest():
            raise EvolutionError("materialization contract does not match the parent run")
        child_contract_path = Path(child.workspace) / "evolution" / "contract.json"
        child_contract = self._confined_regular_file(
            Path(child.workspace), "evolution/contract.json"
        )
        if child_contract is None or child_contract != child_contract_path.resolve(strict=False):
            raise EvolutionError("evolution run is missing its canonical contract")
        try:
            stored_child_contract = AlgorithmProblemContract.from_dict(
                json.loads(child_contract.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("canonical evolution contract is invalid") from exc
        if stored_child_contract.digest() != contract.digest():
            raise EvolutionError("materialization contract does not match the evolution run")
        if (
            child.status != RunStatus.SUCCEEDED
            or result.status not in {"completed", "stagnated"}
            or result.best_candidate_id is None
            or result.best_candidate_path is None
        ):
            raise EvolutionError("materialization requires a successful evolution result")
        if not self._MATERIALIZATION_CANDIDATE_ID.fullmatch(result.best_candidate_id):
            raise EvolutionError("best candidate ID is invalid")

        self._validate_materialization_links(parent, child, contract, result.strategy)
        candidate_bytes = self._validate_materialization_result_identity(
            child, contract, result
        )
        return parent, child, candidate_bytes

    def _materialize_evolved_outputs_locked(
        self,
        parent: Run,
        child: Run,
        contract: AlgorithmProblemContract,
        result: StrategyResult,
        candidate_bytes: bytes,
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        child_root = Path(child.workspace).expanduser().resolve(strict=False)
        candidate_digest = hashlib.sha256(candidate_bytes).hexdigest()
        attempt_relative = (
            "evolution/materialization/"
            f"{result.best_candidate_id}-{candidate_digest[:12]}"
        )
        materialization_root = child_root / "evolution" / "materialization"
        if self._raw_path_has_symlink(child_root, materialization_root):
            raise EvolutionError("materialization directory must not contain a symlink")
        if materialization_root.exists() and not materialization_root.is_dir():
            raise EvolutionError("materialization directory could not be prepared")
        marker = materialization_root / "result.json"
        temporary_marker = materialization_root / ".result.json.tmp"
        if marker.is_symlink():
            raise EvolutionError("materialization result must not be a symlink")
        child_tasks = self.store.list_tasks(child.id)
        if len(child_tasks) != 1:
            raise EvolutionError("materialization evolution task identity is invalid")
        child_task = child_tasks[0]
        launch_identity = {
            "schema_version": "1", "parent_run_id": parent.id, "evolution_run_id": child.id,
            "task_id": child_task.id, "contract_sha256": contract.digest(),
            "strategy": result.strategy, "candidate_id": result.best_candidate_id,
            "candidate_path": result.best_candidate_path, "candidate_sha256": candidate_digest,
            "attempt_path": attempt_relative,
        }
        launch = inspect_launch_intent(self.store, child, launch_identity)
        modern_execution = recover_materialization_execution(self.store, parent, child, launch_identity)
        if launch is not None:
            # No publication may conceal an unknown process launch. Require its independently
            # recorded execution before allowing existing output/terminal recovery to mutate.
            try:
                evidence_relative = f"{attempt_relative}/execution.json"
                evidence_path = self._confined_regular_file(child_root, evidence_relative)
                if evidence_path is None:
                    raise EvolutionError("materialization execution evidence is missing or unsafe")
                execution_data = json.loads(_read_bounded_regular_file(
                    evidence_path, MAX_STATE_BYTES,
                    error="materialization execution evidence is missing or unsafe",
                ))
                previous_execution = CandidateExecution.from_dict(execution_data)
                self._validate_materialization_execution_evidence(
                    {
                        "candidate_id": result.best_candidate_id,
                        "candidate_sha256": candidate_digest,
                        "execution": {
                            "status": previous_execution.status,
                            "exit_code": previous_execution.exit_code,
                            "duration_ms": previous_execution.duration_ms,
                            "evidence_path": evidence_relative,
                        },
                    },
                    parent, child, attempt_relative, candidate_digest,
                )
            except (EvolutionError, OSError, TypeError, ValueError) as exc:
                raise MaterializationLaunchUncertain(
                    "materialization marker is missing from a recorded attempt"
                    if not marker.exists() else "materialization_launch_outcome_unknown"
                ) from exc

        def validate_terminal(payload: dict[str, Any]) -> None:
            current_launch = inspect_launch_intent(self.store, child, launch_identity)
            inspect_materialization_execution(self.store, parent, child, launch_identity)
            if current_launch is not None and not payload.get("execution", {}).get("evidence_path"):
                raise MaterializationLaunchUncertain("materialization_launch_outcome_unknown")
            if modern_execution is not None and delivery is None:
                # An old prepared terminal authorizes its own recovery, but cannot
                # authorize rolling back an unrelated pending output publication.
                status, outputs = recover_output_batch(
                    self.store, parent, child.id, contract.outputs, reconcile=False,
                )
                if payload.get("status") == "succeeded":
                    if ((payload.get("outputs") and (status != "committed" or list(outputs) != payload["outputs"]))
                        or (not payload.get("outputs") and status is not None)):
                        raise MaterializationDeliveryUncertain("materialization_delivery_evidence_invalid")
                elif status not in {None, "rolled_back"}:
                    raise MaterializationDeliveryUncertain("materialization_delivery_evidence_invalid")
            self._validate_materialization_replay(
                payload, parent, child, contract, result, candidate_digest, attempt_relative,
            )

        delivery = inspect_materialization_delivery(self.store, parent, child, launch_identity)
        if delivery is not None:
            if modern_execution is None:
                raise MaterializationDeliveryUncertain("materialization_delivery_evidence_invalid")
            return self._resume_materialization_delivery(
                parent, child, contract, result, launch_identity, modern_execution, validate_terminal,
            )

        # Modern execution without a plan may recover an exact old terminal, or
        # prepare delivery only after proving no downstream evidence exists.
        if modern_execution is None:
            recover_outputs(self.store, parent, child.id, contract.outputs)
        recovered = recover_materialization_result(
            self.store, parent, child, validate=validate_terminal,
        )
        if recovered is not None:
            return recovered
        if marker.exists():
            payload = self._read_materialization_result(marker)
            validate_terminal(payload)
            self._record_materialization_result(
                parent,
                child,
                payload,
                marker,
                require_existing_artifacts=True,
                require_existing_event=True,
            )
            return payload

        if modern_execution is not None:
            return self._resume_materialization_delivery(
                parent, child, contract, result, launch_identity, modern_execution, validate_terminal,
            )
        self._validate_absent_materialization_marker(
            parent, child, result.best_candidate_id, candidate_digest, attempt_relative
        )
        if launch is not None:
            raise MaterializationLaunchUncertain("materialization_launch_outcome_unknown")
        if temporary_marker.exists() or temporary_marker.is_symlink():
            raise EvolutionError("materialization temporary result already exists")
        try:
            materialization_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise EvolutionError("materialization directory could not be prepared") from exc

        attempt = child_root / attempt_relative
        if attempt.exists() or attempt.is_symlink():
            if attempt.is_symlink() or not attempt.is_dir():
                raise EvolutionError("materialization attempt path is unsafe")
            try:
                attempt.resolve(strict=False).relative_to(materialization_root.resolve())
            except ValueError as exc:
                raise EvolutionError("materialization attempt escapes its workspace") from exc
            shutil.rmtree(attempt)
        attempt.mkdir(parents=True, exist_ok=False)
        candidate_copy = attempt / "candidate.py"
        temporary_candidate = attempt / ".candidate.py.tmp"
        temporary_candidate.write_bytes(candidate_bytes)
        temporary_candidate.replace(candidate_copy)

        execution: CandidateExecution | None = None
        launch_entered = False
        validation = Evaluation(False, (), "candidate execution did not start", {"kind": "output"})
        outputs: tuple[dict[str, Any], ...] = ()
        error: str | None = None
        try:
            self._materialize_task_input_data(child, attempt)
            if Path(result.best_candidate_path).suffix.lower() != ".py":
                raise EvolutionError(
                    "automatic output materialization requires a .py candidate"
                )
            runner = CommandCandidateRunner(
                (sys.executable, "-I"),
                timeout_seconds=float(timeout_seconds),
                environment={
                    "PYTHONHASHSEED": "0",
                    "PYTHONIOENCODING": "utf-8",
                },
            )
            prepare_launch_intent(self.store, child, launch_identity, runner)
            launch_entered = True
            try:
                execution = runner.run(candidate_copy, attempt)
            except Exception as exc:
                raise MaterializationLaunchUncertain(
                    "materialization_launch_outcome_unknown"
                ) from exc
            publish_materialization_execution(self.store, parent, child, launch_identity, execution)
            return self._resume_materialization_delivery(
                parent, child, contract, result, launch_identity, execution, validate_terminal,
            )
        except (
            OutputPublicationUncertain, MaterializationLaunchUncertain,
            MaterializationExecutionUncertain, MaterializationDeliveryUncertain,
        ):
            # Unknown launch/commit state or unsafe rollback cannot become a terminal failure
            # claiming no execution or outputs. Preserve the attempt and its durable evidence.
            raise
        except (ArtifactError, EvolutionError, OSError, TypeError, ValueError) as exc:
            if launch_entered and execution is None:
                raise MaterializationLaunchUncertain("materialization_launch_outcome_unknown") from exc
            error = self._sanitize_error(exc)

        execution_path = attempt / "execution.json"
        execution_payload: dict[str, object] = {
            "status": execution.status if execution is not None else "failed",
            "exit_code": execution.exit_code if execution is not None else None,
            "duration_ms": execution.duration_ms if execution is not None else 0,
            "evidence_path": (
                execution_path.relative_to(child_root).as_posix()
                if execution_path.is_file() and not execution_path.is_symlink()
                else None
            ),
        }
        payload: dict[str, Any] = {
            "schema_version": "1",
            "status": "succeeded" if error is None else "failed",
            "parent_run_id": parent.id,
            "evolution_run_id": child.id,
            "contract_sha256": contract.digest(),
            "candidate_id": result.best_candidate_id,
            "candidate_path": result.best_candidate_path,
            "candidate_sha256": candidate_digest,
            "attempt_path": attempt_relative,
            "execution": execution_payload,
            "validation": validation.as_dict(),
            "outputs": list(outputs),
            "error": error,
        }
        return publish_materialization_result(
            self.store, parent, child, payload, validate=validate_terminal,
        )

    def _resume_materialization_delivery(
        self, parent: Run, child: Run, contract: AlgorithmProblemContract, result: StrategyResult,
        identity: dict[str, Any], execution: CandidateExecution, validate_terminal,
    ) -> dict[str, Any]:
        attempt = Path(child.workspace) / identity["attempt_path"]

        def build_plan() -> dict[str, Any]:
            _, _, authority = delivery_authority(self.store, parent, child, identity)
            validation = Evaluation(False, (), "candidate execution did not start", {"kind": "output"})
            error = None
            metadata = []
            if execution.status == "timed_out":
                error = "candidate process timed out"
            elif execution.status != "succeeded":
                error = f"candidate process failed: {execution.error or execution.exit_code}"
            else:
                validation = self._evaluate_evolved_outputs(contract.outputs, attempt)
                if not validation.passed:
                    error = validation.reason
                else:
                    for spec in contract.outputs:
                        source = self._confined_regular_file(attempt, spec.path)
                        if source is None:
                            if spec.required:
                                raise MaterializationDeliveryUncertain("materialization_delivery_evidence_invalid")
                            continue
                        content = _read_bounded_regular_file(
                            source, MAX_ARTIFACT_BYTES, error="materialization_delivery_evidence_invalid",
                        )
                        metadata.append({
                            "path": spec.path, "format": spec.format, "fields": list(spec.fields),
                            "required": spec.required, "size": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                        })
            payload = {
                "schema_version": "1", "status": "succeeded" if error is None else "failed",
                "parent_run_id": parent.id, "evolution_run_id": child.id,
                "contract_sha256": contract.digest(), "candidate_id": result.best_candidate_id,
                "candidate_path": result.best_candidate_path, "candidate_sha256": identity["candidate_sha256"],
                "attempt_path": identity["attempt_path"],
                "execution": {"status": execution.status, "exit_code": execution.exit_code,
                              "duration_ms": execution.duration_ms,
                              "evidence_path": identity["attempt_path"] + "/execution.json"},
                "validation": validation.as_dict(), "outputs": [], "error": error,
            }
            return {**authority, "result": payload, "outputs": metadata}

        return finish_materialization_delivery(
            self.store, parent, child, identity, execution, specs=contract.outputs,
            build_plan=build_plan,
            promote=lambda: self._promote_evolved_outputs(parent, child.id, attempt, contract.outputs),
            validate=validate_terminal, sanitize=self._sanitize_error,
        )

    def _read_materialization_result(self, path: Path) -> dict[str, Any]:
        try:
            content = _read_bounded_regular_file(
                path,
                self._MAX_MATERIALIZATION_RESULT_BYTES,
                error="materialization result is unsafe or oversized",
            )
            payload = json.loads(content.decode("utf-8"))
        except EvolutionError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvolutionError("materialization result is invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("status") not in {"succeeded", "failed"}:
            raise EvolutionError("materialization result has an invalid status")
        return payload

    def _validate_absent_materialization_marker(
        self,
        parent: Run,
        child: Run,
        candidate_id: str,
        candidate_digest: str,
        attempt_relative: str,
    ) -> None:
        """A missing terminal marker must never replay already recorded execution."""

        attempt_path = Path(child.workspace) / attempt_relative
        execution_paths = (
            attempt_path / "execution.json",
            attempt_path / ".execution.json.tmp",
        )
        # Preserve the caller's fixed error for an obstructing materialization-root file. Once the
        # root is a directory, any execution node or uninspectable attempt path means a process may
        # already have run and the attempt must remain intact.
        if attempt_path.parent.is_dir():
            for execution_path in execution_paths:
                try:
                    os.lstat(execution_path)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    # An uninspectable or structurally abnormal attempt is not proven
                    # pre-execution staging. Keep it intact for diagnosis instead of deleting it
                    # and invoking the candidate again.
                    raise EvolutionError(
                        "materialization marker is missing from a recorded attempt"
                    ) from exc
                else:
                    # CommandCandidateRunner creates .execution.json.tmp only after the process
                    # has returned, then atomically publishes execution.json. A crash anywhere in
                    # that evidence-write interval must not turn the completed process launch back
                    # into a fresh attempt on replay. lstat also catches broken links and special
                    # files without following the final path component.
                    raise EvolutionError(
                        "materialization marker is missing from a recorded attempt"
                    )

        materialization_id = "event-evolved-materialization-" + hashlib.sha256(
            f"{parent.id}\0{child.id}".encode()
        ).hexdigest()
        execution_id = "event-evolved-candidate-executed-" + hashlib.sha256(
            f"{parent.id}\0{child.id}\0{candidate_digest}".encode()
        ).hexdigest()
        promotion_id = "event-evolved-outputs-promoted-" + hashlib.sha256(
            f"{parent.id}\0{child.id}".encode()
        ).hexdigest()
        recorded_artifacts = any(
            item.get("path") in {
                "evolution/materialization/result.json",
                f"{attempt_relative}/execution.json",
            }
            for item in self.store.list_artifacts(child.id)
        )
        recorded_child_execution = any(
            event.get("id") == execution_id
            or (
                event.get("type") == "evolved_candidate_executed"
                and isinstance(event.get("payload"), dict)
                and event["payload"].get("candidate_id") == candidate_id
            )
            for event in self.store.list_events(child.id)
        )
        recorded_parent_result = any(
            event.get("id") in {materialization_id, promotion_id}
            or (
                event.get("type") in {
                    "evolved_candidate_materialized",
                    "evolved_outputs_promoted",
                }
                and isinstance(event.get("payload"), dict)
                and event["payload"].get("evolution_run_id") == child.id
            )
            for event in self.store.list_events(parent.id)
        )
        if recorded_artifacts or recorded_child_execution or recorded_parent_result:
            raise EvolutionError("materialization marker is missing from a recorded attempt")

    def _validate_materialization_replay(
        self,
        payload: dict[str, Any],
        parent: Run,
        child: Run,
        contract: AlgorithmProblemContract,
        result: StrategyResult,
        candidate_digest: str,
        attempt_relative: str,
    ) -> None:
        expected = {
            "schema_version": "1",
            "parent_run_id": parent.id,
            "evolution_run_id": child.id,
            "contract_sha256": contract.digest(),
            "candidate_id": result.best_candidate_id,
            "candidate_path": result.best_candidate_path,
            "candidate_sha256": candidate_digest,
            "attempt_path": attempt_relative,
        }
        if set(payload) != {
            *expected,
            "status",
            "execution",
            "validation",
            "outputs",
            "error",
        }:
            raise EvolutionError("materialization result has an invalid shape")
        for key, value in expected.items():
            if payload.get(key) != value:
                label = "candidate digest" if key == "candidate_sha256" else key.replace("_", " ")
                raise EvolutionError(f"materialization {label} does not match current state")
        if not isinstance(payload.get("execution"), dict):
            raise EvolutionError("materialization execution evidence is malformed")
        if not isinstance(payload.get("validation"), dict) or not isinstance(payload.get("outputs"), list):
            raise EvolutionError("materialization validation evidence is malformed")
        attempt_candidate = self._confined_regular_file(
            Path(child.workspace), f"{attempt_relative}/candidate.py"
        )
        if (
            attempt_candidate is None
            or hashlib.sha256(
                _read_bounded_regular_file(
                    attempt_candidate,
                    MAX_SOURCE_BYTES,
                    error="materialization candidate copy is invalid",
                )
            ).hexdigest()
            != candidate_digest
        ):
            raise EvolutionError("materialization candidate copy does not match its digest")

        self._validate_materialization_attempt_evidence(
            payload,
            parent,
            child,
            contract,
            attempt_relative,
            candidate_digest,
        )

    @staticmethod
    def _validate_exact_materialization_event(
        events: list[dict[str, Any]],
        *,
        event_id: str,
        event_type: str,
        task_id: str | None,
        payload: dict[str, Any],
        identity_key: str,
        identity_value: object,
        required: bool,
        error: str,
    ) -> None:
        logical = [
            event
            for event in events
            if event.get("id") == event_id
            or (
                event.get("type") == event_type
                and isinstance(event.get("payload"), dict)
                and event["payload"].get(identity_key) == identity_value
            )
        ]
        if not required:
            if logical:
                raise EvolutionError(error)
            return
        try:
            if (
                len(logical) != 1
                or logical[0].get("id") != event_id
                or logical[0].get("type") != event_type
                or logical[0].get("task_id") != task_id
                or _canonical_json_bytes(logical[0].get("payload"))
                != _canonical_json_bytes(payload)
            ):
                raise EvolutionError(error)
        except (TypeError, ValueError) as exc:
            raise EvolutionError(error) from exc

    def _validate_materialization_artifact_identity(
        self,
        run_id: str,
        task_ids: set[str],
        relative: str,
        kind: str,
        content: bytes,
        *,
        artifact_id: str | None = None,
    ) -> None:
        rows = [
            item
            for item in self.store.list_artifacts(run_id)
            if item.get("path") == relative and item.get("kind") == kind
        ]
        digest = hashlib.sha256(content).hexdigest()
        matching = [
            item
            for item in rows
            if (artifact_id is None or item.get("id") == artifact_id)
            and item.get("task_id") in task_ids
            and item.get("sha256") == digest
            and item.get("size") == len(content)
        ]
        if len(rows) != 1 or len(matching) != 1:
            raise EvolutionError("materialization artifact ledger digest mismatch")

    def _validate_materialization_execution_evidence(
        self,
        payload: dict[str, Any],
        parent: Run,
        child: Run,
        attempt_relative: str,
        candidate_digest: str,
    ) -> CandidateExecution | None:
        execution_payload = payload["execution"]
        if set(execution_payload) != {
            "status",
            "exit_code",
            "duration_ms",
            "evidence_path",
        }:
            raise EvolutionError("materialization execution evidence is malformed")
        evidence_relative = execution_payload.get("evidence_path")
        expected_relative = f"{attempt_relative}/execution.json"
        child_tasks = self.store.list_tasks(child.id)
        if len(child_tasks) != 1:
            raise EvolutionError("materialization evolution task identity is invalid")
        task_id = child_tasks[0].id
        event_id = "event-evolved-candidate-executed-" + hashlib.sha256(
            f"{parent.id}\0{child.id}\0{candidate_digest}".encode()
        ).hexdigest()
        events = self.store.list_events(child.id)

        if evidence_relative is None:
            if execution_payload != {
                "status": "failed",
                "exit_code": None,
                "duration_ms": 0,
                "evidence_path": None,
            }:
                raise EvolutionError("failed materialization has inconsistent execution evidence")
            attempt_path = Path(child.workspace) / attempt_relative
            for raw_evidence in (
                attempt_path / "execution.json",
                attempt_path / ".execution.json.tmp",
            ):
                try:
                    os.lstat(raw_evidence)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise EvolutionError(
                        "failed materialization has unexpected execution evidence"
                    ) from exc
                else:
                    raise EvolutionError(
                        "failed materialization has unexpected execution evidence"
                    )
            if any(
                item.get("path") == expected_relative
                and item.get("kind") == "evolved_candidate_execution"
                for item in self.store.list_artifacts(child.id)
            ):
                raise EvolutionError("failed materialization has unexpected execution ledger")
            self._validate_exact_materialization_event(
                events,
                event_id=event_id,
                event_type="evolved_candidate_executed",
                task_id=task_id,
                payload={},
                identity_key="candidate_id",
                identity_value=payload["candidate_id"],
                required=False,
                error="failed materialization has unexpected execution event",
            )
            return None

        if not isinstance(evidence_relative, str) or evidence_relative != expected_relative:
            raise EvolutionError("materialization execution path does not match its attempt")
        evidence_path = self._confined_regular_file(Path(child.workspace), evidence_relative)
        if evidence_path is None:
            raise EvolutionError("materialization execution evidence is missing or unsafe")
        evidence_content = _read_bounded_regular_file(
            evidence_path,
            MAX_STATE_BYTES,
            error="materialization execution evidence is missing or unsafe",
        )
        try:
            raw_execution = json.loads(evidence_content.decode("utf-8"))
            execution = CandidateExecution.from_dict(raw_execution)
            if _canonical_json_bytes(raw_execution) != _canonical_json_bytes(execution.to_dict()):
                raise EvolutionError("materialization execution evidence is invalid")
        except EvolutionError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("materialization execution evidence is invalid") from exc
        if execution_payload != {
            "status": execution.status,
            "exit_code": execution.exit_code,
            "duration_ms": execution.duration_ms,
            "evidence_path": evidence_relative,
        }:
            raise EvolutionError("materialization execution evidence does not match its result")
        self._validate_materialization_artifact_identity(
            child.id,
            {task_id},
            evidence_relative,
            "evolved_candidate_execution",
            evidence_content,
        )
        event_payload = {
            "candidate_id": payload["candidate_id"],
            "candidate_sha256": candidate_digest,
            "status": execution.status,
            "exit_code": execution.exit_code,
            "duration_ms": execution.duration_ms,
            "evidence_path": evidence_relative,
        }
        self._validate_exact_materialization_event(
            events,
            event_id=event_id,
            event_type="evolved_candidate_executed",
            task_id=task_id,
            payload=event_payload,
            identity_key="candidate_id",
            identity_value=payload["candidate_id"],
            required=True,
            error="materialization execution event does not match its evidence",
        )
        return execution

    def _validate_materialization_outputs(
        self,
        payload: dict[str, Any],
        parent: Run,
        child: Run,
        contract: AlgorithmProblemContract,
    ) -> None:
        outputs = payload["outputs"]
        if not isinstance(outputs, list):
            raise EvolutionError("materialization output evidence is malformed")
        event_id = "event-evolved-outputs-promoted-" + hashlib.sha256(
            f"{parent.id}\0{child.id}".encode()
        ).hexdigest()
        parent_events = self.store.list_events(parent.id)
        if payload["status"] != "succeeded":
            if outputs:
                raise EvolutionError("failed materialization has inconsistent output evidence")
            self._validate_exact_materialization_event(
                parent_events,
                event_id=event_id,
                event_type="evolved_outputs_promoted",
                task_id=None,
                payload={},
                identity_key="evolution_run_id",
                identity_value=child.id,
                required=False,
                error="failed materialization has unexpected output promotion event",
            )
            return

        expected_keys = {
            "artifact_id",
            "path",
            "format",
            "fields",
            "required",
            "size",
            "sha256",
        }
        if any(not isinstance(item, dict) or set(item) != expected_keys for item in outputs):
            raise EvolutionError("materialization output evidence is malformed")
        paths = [item["path"] for item in outputs]
        if len(paths) != len(set(paths)):
            raise EvolutionError("materialization output paths must be unique")
        specs = {spec.path: spec for spec in contract.outputs}
        if any(path not in specs for path in paths) or any(
            spec.required and spec.path not in paths for spec in contract.outputs
        ):
            raise EvolutionError("materialization output paths do not match the contract")
        if paths != [spec.path for spec in contract.outputs if spec.path in paths]:
            raise EvolutionError("materialization output order does not match the contract")

        tasks = self.store.list_tasks(parent.id)
        owner = next(
            (task for task in tasks if (task.plan_task_id or task.id) in {"solve", "solver"}),
            tasks[0] if tasks else None,
        )
        if owner is None:
            raise EvolutionError("parent run has no task for materialized outputs")
        parent_artifacts = self.store.list_artifacts(parent.id)
        latest = self._latest_artifacts_by_path(
            [item for item in parent_artifacts if item.get("kind") == "output"]
        )
        for item in outputs:
            spec = specs[item["path"]]
            digest = item.get("sha256")
            size = item.get("size")
            artifact_id = item.get("artifact_id")
            path = self._confined_regular_file(Path(parent.workspace), spec.path)
            if (
                path is None
                or not isinstance(artifact_id, str)
                or not artifact_id
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
                or item.get("format") != spec.format
                or item.get("fields") != list(spec.fields)
                or item.get("required") is not spec.required
            ):
                raise EvolutionError(f"materialized output identity does not match: {spec.path}")
            content = _read_bounded_regular_file(
                path,
                MAX_ARTIFACT_BYTES,
                error=f"materialized output is missing or unsafe: {spec.path}",
            )
            if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                raise EvolutionError(f"materialized output digest does not match: {spec.path}")
            self._validate_materialization_artifact_identity(
                parent.id,
                {task.id for task in tasks},
                spec.path,
                "output",
                content,
                artifact_id=artifact_id,
            )
            if latest.get(spec.path, {}).get("id") != artifact_id:
                raise EvolutionError(f"materialized output ledger is not current: {spec.path}")

        self._validate_exact_materialization_event(
            parent_events,
            event_id=event_id,
            event_type="evolved_outputs_promoted",
            task_id=owner.id,
            payload={"evolution_run_id": child.id, "outputs": outputs},
            identity_key="evolution_run_id",
            identity_value=child.id,
            required=bool(outputs),
            error="materialization output promotion event does not match its result",
        )

    def _validate_materialization_attempt_evidence(
        self,
        payload: dict[str, Any],
        parent: Run,
        child: Run,
        contract: AlgorithmProblemContract,
        attempt_relative: str,
        candidate_digest: str,
    ) -> None:
        if not isinstance(payload.get("execution"), dict):
            raise EvolutionError("materialization execution evidence is malformed")
        validation = payload.get("validation")
        if (
            not isinstance(validation, dict)
            or set(validation) != {"passed", "evidence", "reason", "details"}
            or not isinstance(validation.get("passed"), bool)
            or not isinstance(validation.get("evidence"), list)
            or any(not isinstance(item, str) for item in validation["evidence"])
            or not isinstance(validation.get("reason"), str)
            or not isinstance(validation.get("details"), dict)
        ):
            raise EvolutionError("materialization validation evidence is malformed")
        execution = self._validate_materialization_execution_evidence(
            payload, parent, child, attempt_relative, candidate_digest
        )
        if execution is None or execution.status != "succeeded":
            expected_validation = Evaluation(
                False,
                (),
                "candidate execution did not start",
                {"kind": "output"},
            ).as_dict()
        else:
            expected_validation = self._evaluate_evolved_outputs(
                contract.outputs,
                Path(child.workspace) / attempt_relative,
            ).as_dict()
        try:
            if _canonical_json_bytes(validation) != _canonical_json_bytes(expected_validation):
                raise EvolutionError("materialization validation does not match its attempt")
        except (TypeError, ValueError) as exc:
            raise EvolutionError("materialization validation evidence is malformed") from exc

        if payload["status"] == "succeeded":
            if (
                execution is None
                or execution.status != "succeeded"
                or validation["passed"] is not True
                or payload.get("error") is not None
            ):
                raise EvolutionError("successful materialization has inconsistent evidence")
        elif (
            not isinstance(payload.get("error"), str)
            or not payload["error"]
            or payload["outputs"]
        ):
            raise EvolutionError("failed materialization has inconsistent evidence")
        self._validate_materialization_outputs(payload, parent, child, contract)

    def _record_materialization_result(
        self,
        parent: Run,
        child: Run,
        payload: dict[str, Any],
        marker: Path,
        *,
        require_existing_artifacts: bool = False,
        require_existing_event: bool = False,
    ) -> None:
        child_tasks = self.store.list_tasks(child.id)
        if len(child_tasks) != 1:
            raise EvolutionError("evolution run has no task for materialization evidence")
        task_id = child_tasks[0].id

        def bind_artifact(
            relative: str,
            kind: str,
            content: bytes,
        ) -> None:
            digest = hashlib.sha256(content).hexdigest()
            rows = [
                item
                for item in self.store.list_artifacts(child.id)
                if item.get("path") == relative and item.get("kind") == kind
            ]
            if not rows:
                if require_existing_artifacts:
                    raise EvolutionError("materialization artifact ledger is incomplete")
                self.store.add_artifact(
                    child.id,
                    task_id,
                    relative,
                    digest,
                    len(content),
                    kind,
                )
                rows = [
                    item
                    for item in self.store.list_artifacts(child.id)
                    if item.get("path") == relative and item.get("kind") == kind
                ]
            if len(rows) != 1 or any(
                item.get("task_id") != task_id
                or item.get("sha256") != digest
                or item.get("size") != len(content)
                for item in rows
            ):
                raise EvolutionError("materialization artifact ledger digest mismatch")

        execution = payload.get("execution")
        evidence_relative = execution.get("evidence_path") if isinstance(execution, dict) else None
        if isinstance(evidence_relative, str):
            evidence_path = self._confined_regular_file(Path(child.workspace), evidence_relative)
            if evidence_path is None:
                raise EvolutionError("materialization execution evidence is missing or unsafe")
            evidence_content = _read_bounded_regular_file(
                evidence_path,
                MAX_STATE_BYTES,
                error="materialization execution evidence is missing or unsafe",
            )
            bind_artifact(
                evidence_relative,
                "evolved_candidate_execution",
                evidence_content,
            )
        relative_marker = marker.relative_to(Path(child.workspace)).as_posix()
        marker_content = _read_bounded_regular_file(
            marker,
            self._MAX_MATERIALIZATION_RESULT_BYTES,
            error="materialization result is unsafe or oversized",
        )
        try:
            marker_payload = json.loads(marker_content.decode("utf-8"))
            if _canonical_json_bytes(marker_payload) != _canonical_json_bytes(payload):
                raise EvolutionError("materialization result changed before it was recorded")
        except EvolutionError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("materialization result is invalid JSON") from exc
        bind_artifact(relative_marker, "evolved_materialization", marker_content)
        event_payload = {
            key: payload.get(key)
            for key in (
                "status",
                "evolution_run_id",
                "contract_sha256",
                "candidate_id",
                "candidate_path",
                "candidate_sha256",
                "attempt_path",
                "execution",
                "validation",
                "outputs",
                "error",
            )
        }
        event_id = (
            "event-evolved-materialization-"
            + hashlib.sha256(f"{parent.id}\0{child.id}".encode()).hexdigest()
        )
        events = self.store.list_events(parent.id)
        logical = [
            event
            for event in events
            if event.get("id") == event_id
            or (
                event.get("type") == "evolved_candidate_materialized"
                and isinstance(event.get("payload"), dict)
                and event["payload"].get("evolution_run_id") == child.id
            )
        ]
        if require_existing_event:
            self._validate_exact_materialization_event(
                events,
                event_id=event_id,
                event_type="evolved_candidate_materialized",
                task_id=None,
                payload=event_payload,
                identity_key="evolution_run_id",
                identity_value=child.id,
                required=True,
                error="materialization event ledger does not match its result",
            )
            return
        if not logical:
            self.store.append_event(
                parent.id,
                "evolved_candidate_materialized",
                event_payload,
                event_id=event_id,
            )
            events = self.store.list_events(parent.id)
        self._validate_exact_materialization_event(
            events,
            event_id=event_id,
            event_type="evolved_candidate_materialized",
            task_id=None,
            payload=event_payload,
            identity_key="evolution_run_id",
            identity_value=child.id,
            required=True,
            error="materialization event ledger does not match its result",
        )

    @staticmethod
    def _evaluate_evolved_outputs(
        specs: tuple[OutputSpec, ...], workspace: Path
    ) -> Evaluation:
        return evaluate_output_contract(specs, workspace)

    def _promote_evolved_outputs(
        self,
        parent: Run,
        evolution_run_id: str,
        attempt: Path,
        specs: tuple[OutputSpec, ...],
    ) -> tuple[dict[str, Any], ...]:
        """Preflight every output, then publish its recoverable file/ledger batch."""
        root = Path(parent.workspace).expanduser().resolve(strict=False)
        tasks = self.store.list_tasks(parent.id)
        owner = next(
            (task for task in tasks if (task.plan_task_id or task.id) in {"solve", "solver"}),
            tasks[0] if tasks else None,
        )
        if owner is None:
            raise EvolutionError("parent run has no task to own materialized outputs")
        promotion_event_id = "event-evolved-outputs-promoted-" + hashlib.sha256(
            f"{parent.id}\0{evolution_run_id}".encode()
        ).hexdigest()
        self._validate_exact_materialization_event(
            self.store.list_events(parent.id),
            event_id=promotion_event_id,
            event_type="evolved_outputs_promoted",
            task_id=owner.id,
            payload={},
            identity_key="evolution_run_id",
            identity_value=evolution_run_id,
            required=False,
            error="materialization output promotion event already exists",
        )
        latest = self._latest_artifacts_by_path(
            [item for item in self.store.list_artifacts(parent.id) if item["kind"] == "output"]
        )
        prepared: list[tuple[OutputSpec, Path, Path, bytes, str]] = []
        for output in specs:
            source = self._confined_regular_file(attempt, output.path)
            if source is None:
                if output.required:
                    raise ArtifactError(f"required algorithm output is missing or unsafe: {output.path}")
                continue
            size = source.stat().st_size
            if size > MAX_ARTIFACT_BYTES:
                raise ArtifactError(
                    f"algorithm output exceeds {MAX_ARTIFACT_BYTES} bytes: {output.path}"
                )
            content = source.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            target = self._confined_output_target(root, output.path)
            existing = latest.get(output.path)
            if target.exists() or target.is_symlink():
                current = self._confined_regular_file(root, output.path)
                if current is None or hashlib.sha256(current.read_bytes()).hexdigest() != digest:
                    raise ArtifactError(
                        f"parent output already contains different data: {output.path}"
                    )
            if existing is not None and (
                existing.get("sha256") != digest or existing.get("size") != size
            ):
                raise ArtifactError(
                    f"parent output ledger contains different data: {output.path}"
                )
            prepared.append((output, source, target, content, digest))

        current_artifact_bytes = sum(
            int(item["size"]) for item in self.store.list_artifacts(parent.id)
        )
        additional_artifact_bytes = sum(
            len(content)
            for output, _source, _target, content, _digest in prepared
            if latest.get(output.path) is None
        )
        artifact_limit = (parent.budget or BudgetSpec()).max_artifact_bytes
        if current_artifact_bytes + additional_artifact_bytes > artifact_limit:
            raise ArtifactError(
                "materialized outputs would exceed the parent artifact byte budget"
            )

        return publish_outputs(
            self.store, parent, evolution_run_id, owner.id,
            [(output, content) for output, _source, _target, content, _digest in prepared],
            artifact_limit,
        )

    def _observe_evolution(
        self, run_id: str, task_id: str, event: str, payload: dict[str, object]
    ) -> None:
        if event == "candidate":
            self.store.append_event(run_id, "evolution_candidate_archived", payload, task_id=task_id)
        elif event == "state" and payload.get("status") == "running":
            self.store.append_event(run_id, "evolution_iteration", payload, task_id=task_id)
        elif event == "agent_artifact":
            self._record_evolution_agent_artifact(run_id, task_id, payload)
        elif event == "agent_candidate_generation":
            try:
                self.store.append_candidate_generation_event(run_id, task_id, payload)
            except (TypeError, ValueError) as exc:
                # A malformed or conflicting receipt must stop the native run.  Retaining a
                # best-effort diagnostic here would make downstream completion unverifiable.
                raise EvolutionError("candidate-generation receipt admission failed") from exc
        elif event in {
            "agent_model_turn",
            "agent_tool_result",
            "agent_step_limit_reached",
            "agent_runtime_failure",
        }:
            # RuntimeAgentAdapter has already reduced this payload to bounded scalar metadata.
            # Keep the original event name so status/events consumers can distinguish model,
            # tool, and failure phases without inspecting a provider-specific trace.
            self.store.append_event(run_id, event, payload, task_id=task_id)

    def _record_evolution_agent_artifact(
        self, run_id: str, task_id: str, payload: dict[str, object]
    ) -> None:
        path_value = payload.get("path")
        kind = payload.get("kind")
        if not isinstance(path_value, str) or not isinstance(kind, str):
            raise EvolutionError("evolution Agent artifact evidence is malformed")
        if kind not in {"evolution_agent_transcript", "evolution_agent_artifact"}:
            raise EvolutionError("evolution Agent artifact kind is unsupported")
        run = self.store.get_run(run_id)
        if run is None:
            raise EvolutionError("evolution Agent artifact references an unknown run")
        root = Path(run.workspace).expanduser().resolve(strict=False)
        raw = root / path_value
        current = raw
        while True:
            if current.exists() and current.is_symlink():
                raise EvolutionError("evolution Agent artifact must not be a symlink")
            if current == root:
                break
            try:
                current.relative_to(root)
            except ValueError as exc:
                raise EvolutionError("evolution Agent artifact escapes the run workspace") from exc
            parent = current.parent
            if parent == current:
                raise EvolutionError("evolution Agent artifact escapes the run workspace")
            current = parent
        resolved = raw.resolve(strict=False)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise EvolutionError("evolution Agent artifact escapes the run workspace") from exc
        if relative != path_value or not resolved.is_file() or resolved.is_symlink():
            raise EvolutionError("evolution Agent artifact must be a regular run-relative file")
        if resolved.stat().st_size > 1 * 1024 * 1024:
            raise EvolutionError("evolution Agent artifact exceeds the bounded evidence size")
        artifacts = ArtifactStore(root, self.store, run_id)
        existing = next(
            (
                item
                for item in self.store.list_artifacts(run_id)
                if item["path"] == relative and item["kind"] == kind
            ),
            None,
        )
        artifact_id = existing["id"] if existing is not None else artifacts.record(
            resolved, task_id, kind=kind
        )
        event_id = "event-evolution-agent-artifact-" + hashlib.sha256(
            f"{relative}\0{kind}".encode()
        ).hexdigest()
        self.store.append_event(
            run_id,
            "evolution_agent_artifact",
            {
                "artifact_id": artifact_id,
                "path": relative,
                "kind": kind,
                "size": resolved.stat().st_size,
                "role": payload.get("role"),
                "adapter": payload.get("adapter"),
                "agent_task_id": payload.get("task_id"),
            },
            task_id=task_id,
            event_id=event_id,
        )

    def start_plan(self, document: PlanDocument, decision: PolicyDecision | None = None) -> Run:
        if decision is None:
            decision = PolicyDecision(
                "execute_plan",
                "A caller supplied a validated multi-step plan",
                1.0,
                plan_id=document.plan_id,
                plan_version=document.version,
                evidence=("explicit plan document",),
            )
        elif decision.action != "execute_plan":
            raise ValueError("a planned run requires an execute_plan decision")
        elif decision.plan_id is None:
            decision = PolicyDecision(
                decision.action,
                decision.rationale,
                decision.confidence,
                decision.questions,
                document.plan_id,
                document.version,
                decision.evidence,
                decision.plan,
            )
        elif (decision.plan_id, decision.plan_version) != (document.plan_id, document.version):
            raise ValueError("execute_plan decision does not reference the supplied plan revision")
        self._active_algorithm_contract(document)
        route = self.router.route(document.goal)
        if document.budget != BudgetSpec():
            route = RouteDecision(route.domain, route.reason, route.confidence, route.required_capabilities,
                                  route.solver_profile, route.evaluator_profile, document.budget, route.evidence)
        self._validate_route(route)
        run = self.store.create_run_with_plan(document, decision, route=route)
        self._register_algorithm_workspace(run, document)
        return self.resume(run.id)

    def patch_plan(self, run_id: str, patch: PlanPatch) -> PlanDocument:
        current = self.store.get_current_plan(run_id)
        if current is None:
            raise ValueError("run has no current plan")
        self._active_algorithm_contract(current)
        return self.store.patch_plan(run_id, patch)

    def replan(self, run_id: str, document: PlanDocument, reason: str, evidence: tuple[str, ...] = ()) -> PlanDocument:
        current = self.store.get_current_plan(run_id)
        if current is None:
            raise ValueError("run has no current plan")
        self._active_algorithm_contract(current)
        if document.plan_id != current.plan_id:
            raise ValueError("replan must retain the current plan id")
        self._active_algorithm_contract(document)
        inherited_budget = current.budget if document.budget == BudgetSpec() else document.budget
        if document.parent_version is None:
            document = PlanDocument(
                goal=document.goal, tasks=document.tasks, plan_id=document.plan_id,
                version=current.version + 1, parent_version=current.version,
                schema_version=document.schema_version, hard_constraints=document.hard_constraints,
                soft_constraints=document.soft_constraints, objective=document.objective,
                evidence=document.evidence, assumptions=document.assumptions,
                acceptance=document.acceptance, verification=document.verification, delivery=document.delivery,
                budget=inherited_budget, algorithm_problem=document.algorithm_problem,
            )
        elif inherited_budget != document.budget:
            document = PlanDocument(
                goal=document.goal, tasks=document.tasks, plan_id=document.plan_id,
                version=document.version, parent_version=document.parent_version,
                schema_version=document.schema_version, hard_constraints=document.hard_constraints,
                soft_constraints=document.soft_constraints, objective=document.objective,
                evidence=document.evidence, assumptions=document.assumptions,
                acceptance=document.acceptance, verification=document.verification, delivery=document.delivery,
                budget=inherited_budget, algorithm_problem=document.algorithm_problem,
            )
        committed = self.store.commit_plan_revision(run_id, document, reason, evidence, action="replan")
        run = self.store.get_run(run_id)
        if run is not None:
            self._register_algorithm_workspace(run, committed)
        return committed

    def deliver(self, run_id: str) -> PolicyDecision:
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        tasks = self.store.list_tasks(run_id)
        artifacts = self.store.list_artifacts(run_id)
        events = self.store.list_events(run_id)
        evaluations = [event for event in events if event["type"] == "task_evaluated"]
        passed = bool(tasks) and run.status == RunStatus.SUCCEEDED and all(
            any(item.get("task_id") == task.id and item["payload"].get("passed") is True for item in evaluations)
            for task in tasks if task.state.value == "succeeded"
        )
        # Algorithm data outputs are promoted to stable run-level paths only after the Solver
        # attempt passes independent evaluation.  Keep the latest record for each path because a
        # replan/retry may leave older audit rows in the append-only artifact ledger.
        output_artifacts = self._latest_artifacts_by_path(
            [item for item in artifacts if item["kind"] == "output"]
        )
        contract = self._algorithm_contract(run)
        evolution_link = next(
            (
                event["payload"]
                for event in reversed(events)
                if event["type"] == "evolution_linked"
                and isinstance(event.get("payload"), dict)
            ),
            None,
        )
        materialization = next(
            (
                event["payload"]
                for event in reversed(events)
                if event["type"] == "evolved_candidate_materialized"
                and isinstance(event.get("payload"), dict)
            ),
            None,
        )
        bundle_terminal = next((event["payload"] for event in reversed(events)
                                if event["type"] == "bundle_candidate_delivered"
                                and isinstance(event.get("payload"), dict)), None)
        bundle_delivery = contract is not None and evolution_link is not None and bundle_terminal is not None
        evolved_delivery = contract is not None and evolution_link is not None and (
            bool(contract.outputs) or bundle_delivery
        )
        bundle_artifacts = []
        if bundle_delivery:
            from .bundle_parent_delivery import inspect_bundle_parent_delivery

            child_id = evolution_link.get("evolution_run_id")
            if not isinstance(child_id, str):
                raise ValueError("run has no successful bundle delivery to deliver")
            materialization = inspect_bundle_parent_delivery(self, run.id, child_id, contract)
            if materialization["status"] != "succeeded":
                raise ValueError("run has no successful bundle delivery to deliver")
            prefix = materialization["delivery_path"] + "/"
            preferred = [prefix + "delivery.json", prefix + "source-bundle.json",
                         materialization["evaluation_report_path"]]
            bundle_artifacts = [next(item for item in artifacts if item["path"] == path)
                                for path in preferred]
            bundle_artifacts.extend(item for item in artifacts if item["path"].startswith(prefix)
                                    and item["path"] not in preferred)
            passed = True
        elif evolved_delivery:
            child_id = evolution_link.get("evolution_run_id")
            child = self.store.get_run(child_id) if isinstance(child_id, str) else None
            if (
                materialization is None
                or materialization.get("status") != "succeeded"
                or materialization.get("contract_sha256") != contract.digest()
                or materialization.get("evolution_run_id") != child_id
                or child is None
                or child.status != RunStatus.SUCCEEDED
                or not isinstance(materialization.get("execution"), dict)
                or materialization["execution"].get("status") != "succeeded"
                or not isinstance(materialization.get("validation"), dict)
                or materialization["validation"].get("passed") is not True
                or not isinstance(materialization.get("outputs"), list)
                or materialization.get("error") is not None
            ):
                raise ValueError("run has no successful evolved output materialization to deliver")
            # The intake compiler and skipped fixed DAG intentionally have no ordinary task
            # evaluations.  The process evidence plus exact OutputSpec validation is the
            # equivalent independent success boundary for this execution path.
            passed = run.status == RunStatus.SUCCEEDED

        role_artifacts = [item for item in artifacts if item["kind"] == "role_evidence"]
        role_requirements: list[str] = []
        for task in tasks if not evolved_delivery else ():
            for rule, relative in self._role_evidence_specs(task.acceptance):
                result_path = str(task.result_path) if task.result_path is not None else ""
                attempt_prefix = result_path.rsplit("/", 1)[0] + "/" if "/" in result_path else ""
                present = any(
                    item.get("task_id") == task.id
                    and item.get("path", "").endswith(f"/{relative}")
                    and (not attempt_prefix or item.get("path", "").startswith(attempt_prefix))
                    for item in role_artifacts
                )
                if not present:
                    role_requirements.append(f"{task.plan_task_id or task.id}/{relative}")
        if role_requirements:
            raise ValueError(
                "run is missing verified role evidence: " + ", ".join(role_requirements[:16])
            )
        if contract is not None and contract.outputs:
            missing = [
                output.path
                for output in contract.outputs
                if output.required and output.path not in output_artifacts
            ]
            if missing:
                raise ValueError(
                    "run is missing verified algorithm outputs: " + ", ".join(missing[:16])
                )
            for output in contract.outputs:
                artifact = output_artifacts.get(output.path)
                if artifact is None:
                    continue
                if evolved_delivery:
                    materialized_outputs = [
                        item
                        for item in materialization["outputs"]
                        if isinstance(item, dict) and item.get("path") == output.path
                    ]
                    if len(materialized_outputs) != 1 or (
                        materialized_outputs[0].get("sha256") != artifact.get("sha256")
                        or materialized_outputs[0].get("size") != artifact.get("size")
                        or materialized_outputs[0].get("format") != output.format
                        or materialized_outputs[0].get("fields") != list(output.fields)
                        or materialized_outputs[0].get("required") is not output.required
                    ):
                        raise ValueError(
                            f"evolved output metadata does not match its artifact: {output.path}"
                        )
                path = self._confined_regular_file(Path(run.workspace), output.path)
                if (
                    path is None
                    or path.stat().st_size != artifact.get("size")
                    or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256")
                ):
                    raise ValueError(
                        f"verified algorithm output no longer matches its digest: {output.path}"
                    )
        usable = [
            *bundle_artifacts,
            *output_artifacts.values(),
            *role_artifacts,
            *[item for item in artifacts if item["kind"] in {"result", "runtime"}],
        ]
        if not passed or not usable:
            raise ValueError("run has no fully verified artifacts to deliver")
        evidence = tuple(item["path"] for item in usable[:16])
        reason = (
            "Selected bundle passed independent evaluation; source, report and published outputs are verified"
            if bundle_delivery
            else "All tasks passed evaluation and have hashed result/runtime/output artifacts"
        )
        return PolicyDecision(
            "deliver", reason, 1.0,
            plan_id=run.current_plan_id, plan_version=run.current_plan_version, evidence=evidence,
        )

    def start(self, goal: str, plan_tasks: list[dict[str, Any]] | None = None) -> Run:
        run = self.create(goal, plan_tasks)
        return self.resume(run.id)

    def create(self, goal: str, plan_tasks: list[dict[str, Any]] | None = None) -> Run:
        """Persist a run and its initial task without executing it."""
        route = self.router.route(goal)
        self._validate_route(route)
        run = self.store.create_run(goal, tasks=plan_tasks, route=route)
        Path(run.workspace).mkdir(parents=True, exist_ok=True)
        return run

    def start_conversational(
        self,
        goal: str,
        compiler: ContractCompiler,
        *,
        workspace: str | Path | None = None,
        compiler_fingerprint: str | None = None,
        run_id: str | None = None,
        plan_factory: Callable[[str, AlgorithmProblemContract], PlanDocument] | None = None,
        execute_plan: bool = True,
    ) -> Run:
        """Compile an algorithm mission and promote the same durable run to a plan.

        The first task is an intake task owned by the controller.  A compiler may pause it through
        ``awaiting_input``; after ``answer_input`` the same method is called again and the task is
        resumed with the verified answer artifact.  Once a contract is accepted, generated plan
        tasks are attached to this run and the ordinary scheduler takes over unless
        ``execute_plan=False`` is used for an explicit orchestration handoff.
        """
        if not hasattr(compiler, "compile") or not callable(compiler.compile):
            raise TypeError("compiler must implement ContractCompiler")
        if run_id is None:
            run = self.create_conversational_run(
                goal, workspace=workspace, compiler_fingerprint=compiler_fingerprint
            )
        else:
            run = self.store.get_run(run_id)
            if run is None:
                raise ValueError(f"unknown run: {run_id}")
            if not any(event["type"] == "conversation_started" for event in self.store.list_events(run_id)):
                raise ValueError("run is not a conversational algorithm mission")
            if run.goal != goal.strip():
                raise ValueError("supplied goal does not match the existing conversational run")
            if run.current_plan_id is not None:
                return self.resume(run.id) if execute_plan else run
        return self._compile_conversational_run(
            run,
            compiler,
            compiler_fingerprint,
            plan_factory=plan_factory,
            execute_plan=execute_plan,
        )

    def create_conversational_run(
        self,
        goal: str,
        *,
        workspace: str | Path | None = None,
        compiler_fingerprint: str | None = None,
    ) -> Run:
        """Create an intake-only run for a detached or parent-Agent solve invocation."""
        route = self.router.route(goal)
        self._validate_route(route)
        run = self.store.create_run(
            goal,
            workspace=workspace,
            tasks=[
                {
                    "id": "contract-intake",
                    "title": "Compile algorithm contract",
                    "prompt": goal,
                    "acceptance": None,
                }
            ],
            route=route,
        )
        self.store.append_event(
            run.id,
            "conversation_started",
            {"compiler_fingerprint": compiler_fingerprint},
        )
        return run

    def _compile_conversational_run(
        self,
        run: Run,
        compiler: ContractCompiler,
        compiler_fingerprint: str | None,
        *,
        plan_factory: Callable[[str, AlgorithmProblemContract], PlanDocument] | None = None,
        execute_plan: bool = True,
        solve_control: SolveExecutionControl | None = None,
    ) -> Run:
        """Run one intake attempt and either pause for input or install the generated plan."""
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run
        task = next(
            (item for item in self.store.list_tasks(run.id) if item.plan_task_id is None), None
        )
        if task is None:
            return self.resume(run.id) if execute_plan else (self.store.get_run(run.id) or run)
        if task.state.value == "waiting":
            return run
        if solve_control is not None:
            solve_control.check("contract")
        attempt = self.store.claim_task(task.id, "contract-compiler")
        if attempt is None:
            latest = self.store.get_run(run.id)
            return latest or run
        task_root = Path(run.workspace) / "tasks" / task.id / attempt.id
        artifacts = ArtifactStore(run.workspace, self.store, run.id)
        artifacts.write_text(
            f"tasks/{task.id}/{attempt.id}/prompt.md",
            "Compile a strict algorithm contract from the user goal.\n\n" + run.goal,
            task.id,
            kind="prompt",
        )
        answer: str | None = None
        if task.input_answer_path:
            answer_path = (Path(run.workspace) / task.input_answer_path).resolve(strict=False)
            try:
                answer_path.relative_to(Path(run.workspace).resolve())
                answer_payload = json.loads(answer_path.read_text(encoding="utf-8"))
                if isinstance(answer_payload, dict) and isinstance(answer_payload.get("answer"), str):
                    answer = answer_payload["answer"]
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                answer = None
            if answer is None:
                error = "input answer artifact is malformed"
                self.store.finish_task(task.id, attempt.id, False, error=error)
                return self.store.settle_run(run.id) or run
        compiler_runtime = getattr(compiler, "runtime", None)
        automatic_scope = self._automatic_cancel_targets(run.id)
        if compiler_runtime is not None:
            with self._active_lock:
                self._active_runtimes[attempt.id] = compiler_runtime
            set_observer = getattr(compiler_runtime, "set_process_observer", None)
            if callable(set_observer):
                try:
                    if automatic_scope is not None and automatic_scope.verified:
                        observe, release = self.attempt_process_observers(run.id, attempt.id)
                        set_observer(observe)
                        def guard() -> None:
                            current = self.store.get_run(run.id)
                            if current is None or current.status in {RunStatus.CANCELLED, RunStatus.FAILED}:
                                raise SolveExecutionCancelled("contract")
                            if solve_control is not None:
                                solve_control.check("contract")
                            self.ensure_attempt_process_released(run.id, attempt.id)
                        set_guard = getattr(compiler_runtime, "set_continuation_guard", None)
                        if callable(set_guard):
                            set_guard(guard)
                        set_released = getattr(compiler_runtime, "set_process_released", None)
                        if callable(set_released):
                            set_released(release)
                    else:
                        set_observer(
                            lambda pid, pgid, attempt_id=attempt.id: self.store.set_attempt_process(
                                attempt_id, pid, pgid
                            )
                        )
                except Exception as observer_error:  # noqa: BLE001 - observer must not block intake
                    del observer_error
        try:
            result = compiler.compile(
                run.goal,
                task_root,
                answer=answer,
                timeout=(solve_control.effective_timeout(self.config.runtime_timeout, stage="contract")
                         if solve_control is not None else self.config.runtime_timeout),
            )
            if automatic_scope is not None and automatic_scope.verified:
                self.ensure_attempt_process_released(run.id, attempt.id)
            if solve_control is not None:
                solve_control.check("contract")
            if not self._task_is_running(task.id):
                self._discard_late_result(run.id, task.id, attempt.id)
                return self.store.get_run(run.id) or run
            if not isinstance(result, CompilationResult):
                raise ContractCompilationError("compiler returned an invalid result")
            if result.status == "needs_input":
                question = result.questions[0]
                request_payload = {
                    "status": "awaiting_input",
                    "run_id": run.id,
                    "task_id": task.id,
                    "attempt_id": attempt.id,
                    "question": question.question,
                    "options": list(question.options),
                    "questions": [item.to_dict() for item in result.questions],
                }
                request_path = artifacts.write_text(
                    f"tasks/{task.id}/{attempt.id}/input-request.json",
                    json.dumps(request_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    task.id,
                    kind="input",
                )
                self._write_compiler_manifest(
                    run,
                    task.id,
                    status="needs_input",
                    compiler_fingerprint=compiler_fingerprint,
                    plan_kind="role_dag" if plan_factory is not None else "legacy",
                    evidence=result.evidence,
                )
                self.store.await_input(
                    task.id,
                    attempt.id,
                    str(request_path.relative_to(Path(run.workspace))),
                    question.question,
                    question.options,
                )
                return self.store.get_run(run.id) or run
            assert result.contract is not None
            contract = result.contract
            if contract.evolution.strategy == "loop":
                raise ContractCompilationError(LOOP_STRATEGY_RETIRED_MESSAGE)
            plan = result.plan or (plan_factory or build_algorithm_plan)(run.goal, contract)
            if plan.algorithm_problem is None:
                raise ContractCompilationError("generated plan is missing algorithm_problem")
            try:
                attached_contract = AlgorithmProblemContract.from_dict(plan.algorithm_problem)
            except (TypeError, ValueError) as exc:
                raise ContractCompilationError("generated plan contains an invalid algorithm contract") from exc
            if attached_contract.digest() != contract.digest() or plan.goal != run.goal:
                raise ContractCompilationError("generated plan does not match the compiled contract or goal")
            contract_path = artifacts.write_text(
                "solve/contract.json",
                json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                task.id,
                kind="algorithm_contract",
            )
            plan_path = artifacts.write_text(
                "solve/plan.json",
                json.dumps(plan.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                task.id,
                kind="algorithm_plan",
            )
            decision = PolicyDecision(
                "execute_plan",
                "A strict algorithm contract was compiled from the conversational intake",
                1.0,
                plan_id=plan.plan_id,
                plan_version=plan.version,
                evidence=result.evidence or ("validated contract compiler response",),
                plan=plan.to_dict(),
            )
            self.store.attach_plan_to_run(run.id, plan, decision)
            self._register_algorithm_workspace(run, plan)
            self._write_compiler_manifest(
                run,
                task.id,
                status="compiled",
                compiler_fingerprint=compiler_fingerprint,
                plan_kind="role_dag" if plan_factory is not None else "legacy",
                contract_sha256=contract.digest(),
                plan=plan,
                contract_path=str(contract_path.relative_to(Path(run.workspace))),
                plan_path=str(plan_path.relative_to(Path(run.workspace))),
                evidence=result.evidence,
            )
            self.store.append_event(
                run.id,
                "contract_compiled",
                {
                    "contract_sha256": contract.digest(),
                    "plan_id": plan.plan_id,
                    "plan_version": plan.version,
                    "evidence": list(result.evidence),
                },
                task_id=task.id,
            )
            if solve_control is not None:
                solve_control.check("contract")
            self.store.finish_task(
                task.id,
                attempt.id,
                True,
                str(contract_path.relative_to(Path(run.workspace))),
            )
            self.store.settle_run(run.id)
            return self.resume(run.id) if execute_plan else (self.store.get_run(run.id) or run)
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            raise
        except ContractCompilationError as exc:
            if solve_control is not None:
                solve_control.check("contract")
            error = str(exc)[-2_000:] or "contract compilation failed"
        except Exception as exc:  # noqa: BLE001 - compiler is an untrusted boundary
            if solve_control is not None:
                solve_control.check("contract")
            error = self._sanitize_error(exc)
        finally:
            if compiler_runtime is not None:
                reset_observer = getattr(compiler_runtime, "set_process_observer", None)
                if callable(reset_observer):
                    try:
                        reset_observer(None)
                    except Exception as observer_error:  # noqa: BLE001 - cleanup must not mask result
                        del observer_error
                with self._active_lock:
                    self._active_runtimes.pop(attempt.id, None)
                for name in ("set_process_released", "set_continuation_guard"):
                    reset_hook = getattr(compiler_runtime, name, None)
                    if callable(reset_hook):
                        try:
                            reset_hook(None)
                        except Exception:  # noqa: BLE001, S110 - cleanup cannot mask the result
                            pass
        self.store.finish_task(task.id, attempt.id, False, error=error)
        settled = self.store.settle_run(run.id)
        return settled or run

    def resume_conversational(
        self,
        run_id: str,
        compiler: ContractCompiler,
        *,
        compiler_fingerprint: str | None = None,
        plan_factory: Callable[[str, AlgorithmProblemContract], PlanDocument] | None = None,
        execute_plan: bool = True,
        solve_control: SolveExecutionControl | None = None,
    ) -> Run:
        """Resume intake or generated tasks; optionally stop after contract attachment."""
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        if not any(event["type"] == "conversation_started" for event in self.store.list_events(run_id)):
            raise ValueError("run is not a conversational algorithm mission")
        if run.current_plan_id is not None:
            return self.resume(run_id) if execute_plan else run
        return self._compile_conversational_run(
            run,
            compiler,
            compiler_fingerprint,
            plan_factory=plan_factory,
            execute_plan=execute_plan,
            solve_control=solve_control,
        )

    def _write_compiler_manifest(
        self,
        run: Run,
        task_id: str,
        *,
        status: str,
        compiler_fingerprint: str | None,
        plan_kind: str = "legacy",
        evidence: tuple[str, ...] = (),
        contract_sha256: str | None = None,
        plan: PlanDocument | None = None,
        contract_path: str | None = None,
        plan_path: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "schema_version": "1",
            "status": status,
            "goal_sha256": hashlib.sha256(run.goal.encode("utf-8")).hexdigest(),
            "runtime_fingerprint": compiler_fingerprint,
            "plan_kind": plan_kind,
            "evidence": list(evidence),
        }
        if contract_sha256 is not None:
            payload["contract_sha256"] = contract_sha256
        if plan is not None:
            payload.update({"plan_id": plan.plan_id, "plan_version": plan.version})
        if contract_path is not None:
            payload["contract_path"] = contract_path
        if plan_path is not None:
            payload["plan_path"] = plan_path
        artifacts = ArtifactStore(run.workspace, self.store, run.id)
        manifest = artifacts.write_text(
            "solve/compiler-manifest.json",
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            task_id,
            kind="compiler_manifest",
        )
        del manifest

    def run_agent(
        self,
        run_id: str,
        *,
        role: str = "solver",
        prompt: str | None = None,
        required_capabilities: tuple[str, ...] | list[str] = (),
        preferred_adapter: str | None = None,
        task_id: str | None = None,
        timeout: float | None = None,
    ) -> tuple[Run, AgentResult]:
        """Delegate one ready task to an explicitly registered Agent adapter.

        This entry point intentionally mirrors the normal scheduler's durable lifecycle while
        keeping the worker ignorant of Store handles.  It is synchronous for library callers; a
        parent process that needs detachment can invoke the JSON ``delegate`` CLI and later use
        ``status``/``resume``.
        """
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            raise ValueError(f"run is already terminal: {run_id}")
        if run.status == RunStatus.RUNNING and self._runner_is_stale(run):
            self.store.recover_running(run_id)
            run = self.store.get_run(run_id)
            if run is None:
                raise ValueError(f"run disappeared while recovering: {run_id}")
        started = time.monotonic()
        budget = run.budget or BudgetSpec()
        task = self.store.get_task(task_id) if task_id else self.store.next_task(run_id)
        if task is None or task.run_id != run_id:
            raise ValueError("run has no ready task to delegate")
        requested = tuple(required_capabilities) or tuple(run.route_required_capabilities)
        try:
            adapter = self.agent_registry.select(role, requested, preferred_adapter)
        except (AgentSelectionError, TypeError, ValueError):
            self.store.append_event(
                run_id,
                "agent_selection_failed",
                {
                    "role": role,
                    "required_capabilities": list(requested)[:64],
                    "preferred_adapter": preferred_adapter,
                },
                task_id=task.id,
            )
            raise
        effective_prompt = prompt if prompt is not None else self._build_task_prompt(run, task)
        if not effective_prompt.strip() or "\x00" in effective_prompt:
            raise ValueError("delegation prompt must be non-empty and NUL-free")
        if len(effective_prompt.encode("utf-8")) > 64 * 1024:
            raise ValueError("delegation prompt exceeds 65536 bytes")
        effective_timeout = self.config.runtime_timeout if timeout is None else timeout
        if (
            isinstance(effective_timeout, bool)
            or not isinstance(effective_timeout, (int, float))
            or effective_timeout <= 0
            or effective_timeout > 24 * 60 * 60
        ):
            raise ValueError("delegation timeout must be between 0 and 86400 seconds")
        self._check_budget(run.id, budget, started, before_claim=True)
        attempt = self.store.claim_task(task.id, adapter.name)
        if attempt is None:
            raise ValueError("task was claimed or cancelled concurrently; retry after inspecting status")
        task_root = Path(run.workspace) / "tasks" / task.id / attempt.id
        artifacts = ArtifactStore(run.workspace, self.store, run.id)
        try:
            self._materialize_task_input_data(run, task_root)
            request_timeout = self._remaining_runtime_timeout(
                run.id, budget, started, effective_timeout
            )
            request = AgentRequest(
                run_id=run.id,
                task_id=task.id,
                role=role,
                prompt=effective_prompt,
                required_capabilities=requested,
                workspace=task_root,
                timeout=request_timeout,
            )
        except (TypeError, ValueError) as exc:
            error = self._sanitize_error(exc)
            self.store.finish_task(task.id, attempt.id, False, error=error)
            self.store.settle_run(run.id)
            raise AgentInvocationError(error) from exc
        self.store.append_event(
            run.id,
            "agent_selected",
            {
                "attempt_id": attempt.id,
                "adapter": adapter.name,
                "role": role,
                "required_capabilities": list(request.required_capabilities),
            },
            task_id=task.id,
        )
        self.store.append_event(
            run.id,
            "agent_started",
            {"attempt_id": attempt.id, "adapter": adapter.name, "role": role},
            task_id=task.id,
        )
        artifacts.write_text(
            f"tasks/{task.id}/{attempt.id}/prompt.md", effective_prompt, task.id, kind="prompt"
        )
        with self._active_lock:
            self._active_agents[attempt.id] = adapter
        try:
            adapter.set_process_observer(
                lambda pid, pgid: self.store.set_attempt_process(attempt.id, pid, pgid)
            )
            if not self._task_is_running(task.id):
                self._discard_late_result(run.id, task.id, attempt.id)
                raise AgentInvocationError("task was cancelled before agent start")
            result = adapter.run(request)
            if not isinstance(result, AgentResult):
                raise AgentInvocationError("agent returned an invalid result")
            if result.adapter_name != adapter.name or result.role != request.role:
                raise AgentInvocationError("agent result identity does not match the selected adapter")
            if not self._task_is_running(task.id):
                self._discard_late_result(run.id, task.id, attempt.id)
                raise AgentInvocationError("agent result discarded because the task was cancelled")
            result_path = artifacts.write_text(
                f"tasks/{task.id}/{attempt.id}/result.txt", result.text, task.id, kind="result"
            )
            for relative_path in result.artifacts:
                runtime_path = self._runtime_artifact_path(task_root, relative_path)
                artifacts.record(runtime_path, task.id, kind="runtime")
            self._record_role_evidence(run, task, task_root)
            self._check_budget(run.id, budget, started)
            result_payload = {
                "attempt_id": attempt.id,
                "adapter": result.adapter_name,
                "role": result.role,
                "status": result.status,
                "artifacts": list(result.artifacts),
                "metadata": result.metadata,
                "error": result.error,
            }
            self.store.append_event(
                run.id,
                "agent_finished" if result.status == "succeeded" else "agent_failed",
                result_payload,
                task_id=task.id,
            )
            evaluation = self._evaluate(run, task, result.text, task_root)
            evaluation_payload = {
                "attempt_id": attempt.id,
                "passed": evaluation.passed,
                "reason": evaluation.reason,
                "evidence": list(evaluation.evidence),
                "details": evaluation.details,
            }
            self.store.append_event(run.id, "task_evaluated", evaluation_payload, task_id=task.id)
            if result.status != "succeeded":
                error = result.error or f"agent returned {result.status}"
                self.store.finish_task(task.id, attempt.id, False, str(result_path.relative_to(run.workspace)), error)
            elif evaluation.passed:
                self._promote_algorithm_outputs(run, task, task_root, attempt_id=attempt.id)
                self.store.finish_task(task.id, attempt.id, True, str(result_path.relative_to(run.workspace)))
            elif self._can_retry(task.attempts + 1):
                self.store.retry_task(task.id, attempt.id, evaluation.reason)
            else:
                self.store.finish_task(
                    task.id,
                    attempt.id,
                    False,
                    str(result_path.relative_to(run.workspace)),
                    evaluation.reason,
                )
            settled = self.store.settle_run(run.id)
            if settled is None:
                raise ValueError(f"run disappeared while delegating: {run.id}")
            return settled, result
        except BudgetExceeded:
            self.store.settle_run(run.id)
            raise
        except AgentInvocationError as exc:
            error = self._sanitize_error(exc)
            self.store.append_event(
                run.id,
                "agent_failed",
                {"attempt_id": attempt.id, "adapter": adapter.name, "role": role, "error": error},
                task_id=task.id,
            )
            if self._task_is_running(task.id):
                if self._can_retry(task.attempts + 1):
                    self.store.retry_task(task.id, attempt.id, error)
                else:
                    self.store.finish_task(task.id, attempt.id, False, error=error)
            self.store.settle_run(run.id)
            raise
        except Exception as exc:
            error = self._sanitize_error(exc)
            self.store.append_event(
                run.id,
                "agent_failed",
                {"attempt_id": attempt.id, "adapter": adapter.name, "role": role, "error": error},
                task_id=task.id,
            )
            if self._task_is_running(task.id):
                if self._can_retry(task.attempts + 1):
                    self.store.retry_task(task.id, attempt.id, error)
                else:
                    self.store.finish_task(task.id, attempt.id, False, error=error)
            self.store.settle_run(run.id)
            raise AgentInvocationError(error) from exc
        finally:
            try:
                adapter.set_process_observer(None)
            except Exception as cleanup_error:  # noqa: BLE001 - cleanup must not mask result
                del cleanup_error
            with self._active_lock:
                self._active_agents.pop(attempt.id, None)

    def _worker_delivery_lock(self, worker_id: str, *, create: bool = False):
        owner = "worker-owner-" + hashlib.sha256(worker_id.encode("utf-8")).hexdigest()[:32]
        return WorkerOwnerLock.acquire(self.store.database, owner, create=create)

    def run_worker_agent(
        self,
        run_id: str,
        *,
        role: str = "solver",
        prompt: str | None = None,
        required_capabilities: tuple[str, ...] | list[str] = (),
        preferred_adapter: str | None = None,
        task_id: str | None = None,
        timeout: float | None = None,
        wait_timeout: float | None = None,
    ) -> tuple[Run, AgentResult]:
        """Run one explicitly delegated task through the durable worker control plane."""
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            raise ValueError(f"run is already terminal: {run_id}")
        self._reconcile_worker_run(run_id)
        run = self.store.get_run(run_id)
        assert run is not None
        started = time.monotonic()
        budget = run.budget or BudgetSpec()
        active_bindings = [
            item for item in self.store.list_worker_bindings(run_id)
            if item.status in {"active", "delivering"}
        ]
        if len(active_bindings) > 1:
            raise AgentInvocationError("run has more than one active worker binding")
        existing_binding = active_bindings[0] if active_bindings else None
        if existing_binding is not None:
            if task_id is not None and task_id != existing_binding.task_id:
                raise ValueError("run already has an active worker for a different task")
            task = self.store.get_task(existing_binding.task_id)
            attempt = self.store.get_attempt(existing_binding.task_attempt_id)
            worker = self.store.get_worker(existing_binding.worker_id)
            if task is None or attempt is None or worker is None or task.run_id != run_id:
                raise AgentInvocationError("active worker binding is incomplete")
            if task.state.value != "running" or attempt.task_id != task.id or attempt.status != "running":
                raise AgentInvocationError("active worker binding is not paired with a running attempt")
            role = worker.role
            adapter_name = worker.agent_type
            adapter = None
        else:
            task = self.store.get_task(task_id) if task_id else self.store.next_task(run_id)
            if task is None or task.run_id != run_id:
                raise ValueError("run has no ready task to delegate")
            if task.state.value not in {"ready", "uncertain"}:
                raise ValueError("task is not ready for delegation")
            requested = tuple(required_capabilities) or tuple(run.route_required_capabilities)
            adapter = self.agent_registry.select(role, requested, preferred_adapter)
            adapter_name = adapter.name
            effective_prompt = prompt if prompt is not None else self._build_task_prompt(run, task)
            if not effective_prompt.strip() or "\x00" in effective_prompt:
                raise ValueError("delegation prompt must be non-empty and NUL-free")
            if len(effective_prompt.encode("utf-8")) > 64 * 1024:
                raise ValueError("delegation prompt exceeds 65536 bytes")
            effective_timeout = self.config.runtime_timeout if timeout is None else timeout
            if (
                isinstance(effective_timeout, bool)
                or not isinstance(effective_timeout, (int, float))
                or effective_timeout <= 0
                or effective_timeout > 24 * 60 * 60
            ):
                raise ValueError("delegation timeout must be between 0 and 86400 seconds")
        if wait_timeout is not None and (isinstance(wait_timeout, bool) or not isinstance(wait_timeout, (int, float)) or wait_timeout < 0):
            raise ValueError("wait timeout must be non-negative")
        if existing_binding is not None:
            active_timeout = existing_binding.active_timeout
        else:
            self._check_budget(run.id, budget, started, before_claim=True)
            active_timeout = self._remaining_runtime_timeout(run.id, budget, started, effective_timeout)
            attempt = self.store.claim_task(task.id, adapter_name)
            if attempt is None:
                raise ValueError("task was claimed or cancelled concurrently; retry after inspecting status")
        if existing_binding is None:
            worker = None
        delivery_lock_held = False
        delivery_owner_lock = None

        def active_bound_worker_id() -> str | None:
            """Find a binding created before worker dispatch returned to this caller."""
            for candidate in self.store.list_worker_bindings(run.id, status="active"):
                if candidate.task_attempt_id == attempt.id:
                    return candidate.worker_id
            return None

        try:
            def bind(created, worker_attempt):
                self.store.bind_worker(
                    worker_id=created.id,
                    worker_attempt_id=worker_attempt.id,
                    run_id=run.id,
                    task_id=task.id,
                    task_attempt_id=attempt.id,
                    service_owner_id=worker_attempt.service_owner_id or self.workers.service_owner_id,
                    active_timeout=active_timeout,
                )
                worker_root = self.workers.workspace / "workers" / created.id / worker_attempt.id
                self._materialize_task_input_data(run, worker_root)

            if existing_binding is None:
                worker = self.workers.dispatch(
                    run.id,
                    role=role,
                    prompt=effective_prompt,
                    description=task.title,
                    required_capabilities=requested,
                    preferred_adapter=preferred_adapter,
                    timeout=active_timeout,
                    before_start=bind,
                )
                self.store.append_event(
                    run.id, "agent_selected",
                    {"attempt_id": attempt.id, "adapter": adapter_name, "role": role,
                     "required_capabilities": list(requested)}, task_id=task.id,
                )
                self.store.append_event(
                    run.id, "agent_started",
                    {"attempt_id": attempt.id, "adapter": adapter_name, "role": role}, task_id=task.id,
                )
            observed = self.workers.wait(run.id, worker.id, timeout=wait_timeout)
            if observed.phase.value == "running":
                raise WorkerObservationTimeout(worker.id)
            # Do not hold the controller lock while another delivery owner is active:
            # observation may time out, and cancellation must remain available to other threads.
            observation_deadline = (
                started + wait_timeout if wait_timeout is not None else
                time.monotonic() + max(1.0, min(active_timeout or 30.0, 30.0))
            )
            while True:
                binding = self.store.get_worker_binding(worker.id)
                if binding is None or binding.task_attempt_id != attempt.id:
                    raise AgentInvocationError("worker binding is missing or mismatched")
                if binding.status == "settled":
                    envelope = self.store.get_worker_result(
                        worker.id, binding.worker_attempt_id, owner_id=run.id,
                    )
                    if envelope is None:
                        # This observer owns no staging and must not clean the committed result.
                        raise WorkerObservationTimeout(worker.id)
                    settled = self.store.get_run(run.id)
                    if settled is None:
                        raise ValueError(f"run disappeared while delegating: {run.id}")
                    return settled, envelope.to_agent_result()
                if binding.status not in {"active", "delivering"}:
                    raise AgentInvocationError("worker binding is no longer active")
                try:
                    delivery_owner_lock = self._worker_delivery_lock(
                        worker.id, create=binding.status == "active",
                    )
                except (OSError, ValueError):
                    # Missing or unsafe liveness evidence cannot authorize cleanup or takeover.
                    raise WorkerObservationTimeout(worker.id) from None
                if delivery_owner_lock is not None:
                    # The status read before taking the OS lock may already be stale. Never
                    # stage or discard anything based on that snapshot.
                    binding = self.store.get_worker_binding(worker.id)
                    if binding is not None and binding.status == "delivering":
                        self.store.recover_worker_binding_delivery(
                            worker_id=worker.id, worker_attempt_id=binding.worker_attempt_id,
                            stale_after=max(1.0, min(binding.active_timeout or 30.0, 30.0)),
                        )
                        binding = self.store.get_worker_binding(worker.id)
                    if binding is not None and binding.status == "active":
                        self._active_lock.acquire()
                        delivery_lock_held = True
                        claimed = self.store.claim_worker_binding_delivery(
                            worker_id=worker.id, worker_attempt_id=binding.worker_attempt_id,
                            run_id=run.id, task_id=task.id, task_attempt_id=attempt.id,
                        )
                        if claimed:
                            # A crashed materializer may have written only part of its batch.
                            # This exact attempt is still uncommitted and its owner lock is held;
                            # remove staging before reconstructing it from the durable envelope.
                            self._discard_late_result(
                                run.id, task.id, attempt.id, record_event=False,
                            )
                            break
                        self._active_lock.release()
                        delivery_lock_held = False
                    delivery_owner_lock.close()
                    delivery_owner_lock = None
                    if binding is not None and binding.status not in {"active", "delivering"}:
                        continue
                remaining = observation_deadline - time.monotonic()
                if remaining <= 0:
                    raise WorkerObservationTimeout(worker.id)
                time.sleep(min(0.01, remaining))
            self.store.append_event(
                run.id, "worker_finished_observed", {"attempt_id": attempt.id}, task_id=task.id,
            )
            envelope = self.store.get_worker_result(
                worker.id, binding.worker_attempt_id, owner_id=run.id,
            )
            if envelope is None:
                raise AgentInvocationError("worker result envelope is missing")
            result = envelope.to_agent_result()
            if result.adapter_name != adapter_name or result.role != role:
                raise AgentInvocationError("worker result identity does not match the selected adapter")
            task_root = Path(run.workspace) / "tasks" / task.id / attempt.id
            task_root.mkdir(parents=True, exist_ok=True)
            artifacts = ArtifactStore(run.workspace, self.store, run.id)
            # Refuse a budget-expired delivery before publishing task artifacts.
            self._check_budget(run.id, budget, started)
            result_path = artifacts.write_text(
                f"tasks/{task.id}/{attempt.id}/result.txt", result.text, task.id, kind="result"
            )
            worker_root = self.workers.workspace / "workers" / worker.id / binding.worker_attempt_id
            manifest = {item["path"]: item for item in envelope.artifact_manifest}
            for relative_path in result.artifacts:
                item = manifest.get(relative_path)
                size = item.get("size") if item else None
                digest = item.get("sha256") if item else None
                if (
                    not isinstance(size, int)
                    or isinstance(size, bool)
                    or size < 0
                    or size > self._MAX_WORKER_MATERIALIZED_ARTIFACT_BYTES
                    or not isinstance(digest, str)
                ):
                    raise ArtifactError(f"worker artifact manifest is invalid: {relative_path}")
                source = self._confined_regular_file(worker_root, relative_path)
                if source is None:
                    raise ArtifactError(f"worker artifact is missing or not regular: {relative_path}")
                content = source.read_bytes()
                if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                    raise ArtifactError(f"worker artifact integrity check failed: {relative_path}")
                raw_destination = Path(run.workspace) / "tasks" / task.id / attempt.id / relative_path
                if self._raw_path_has_symlink(Path(run.workspace).resolve(), raw_destination):
                    raise ArtifactError(f"worker artifact destination is symlinked: {relative_path}")
                destination = artifacts.safe_path(f"tasks/{task.id}/{attempt.id}/{relative_path}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                artifacts.record(destination, task.id, kind="runtime")
            # Result/runtime artifacts are ledgered before evaluation.  Re-check the run budget
            # after those writes so an artifact ceiling cannot be bypassed by one worker delivery.
            self._check_budget(run.id, budget, started)
            self._record_role_evidence(run, task, task_root)
            evaluation = self._evaluate(run, task, result.text, task_root)
            evaluation_payload = {
                "attempt_id": attempt.id, "passed": evaluation.passed,
                "reason": evaluation.reason, "evidence": list(evaluation.evidence),
                "details": evaluation.details,
            }
            agent_event_type = "agent_finished" if result.status == "succeeded" else "agent_failed"
            agent_payload = {
                "attempt_id": attempt.id, "adapter": result.adapter_name, "role": result.role,
                "status": result.status, "artifacts": list(result.artifacts),
                "metadata": result.metadata, "error": result.error,
            }
            if result.status != "succeeded":
                completion = "failed"
                completion_error = result.error
            elif evaluation.passed:
                self._promote_algorithm_outputs(
                    run, task, task_root, attempt_id=attempt.id, worker_delivery=True,
                )
                completion = "succeeded"
                completion_error = None
            elif self._can_retry(task.attempts + 1):
                completion = "retry"
                completion_error = evaluation.reason
            else:
                completion = "failed"
                completion_error = evaluation.reason
            self._check_budget(run.id, budget, started)
            delivered = self.store.complete_worker_binding(
                worker_id=worker.id,
                worker_attempt_id=binding.worker_attempt_id,
                run_id=run.id,
                task_id=task.id,
                task_attempt_id=attempt.id,
                outcome=completion,
                result_path=str(result_path.relative_to(run.workspace)),
                error=completion_error,
                agent_event_type=agent_event_type,
                agent_payload=agent_payload,
                evaluation_payload=evaluation_payload,
            )
            if not delivered:
                # A second observer may arrive after another controller has already committed
                # this exact worker attempt.  Treat that case as idempotent delivery: preserve
                # the winner's result/runtime/output evidence instead of deleting it as late.
                current_binding = self.store.get_worker_binding(worker.id)
                current_attempt = self.store.get_attempt(attempt.id)
                if (
                    current_binding is not None
                    and current_binding.worker_attempt_id == binding.worker_attempt_id
                    and current_binding.status == "settled"
                    and current_attempt is not None
                    and current_attempt.status in {"succeeded", "failed"}
                ):
                    settled = self.store.get_run(run.id)
                    if settled is None:
                        raise ValueError(f"run disappeared while delegating: {run.id}")
                    self._active_lock.release()
                    delivery_lock_held = False
                    return settled, result
                self._discard_late_result(run.id, task.id, attempt.id)
                self.store.settle_worker_binding(worker.id, "discarded")
                raise AgentInvocationError("worker result discarded because its binding is no longer active")
            settled = self.store.get_run(run.id)
            if settled is None:
                raise ValueError(f"run disappeared while delegating: {run.id}")
            self._active_lock.release()
            delivery_lock_held = False
            return settled, result
        except WorkerObservationTimeout:
            # Observation timeout is deliberately non-terminal: the binding and the exact
            # worker remain active for an explicit later wait, cancel, or recovery action.
            raise
        except BudgetExceeded:
            if delivery_lock_held:
                self._active_lock.release()
                delivery_lock_held = False
            worker_id = worker.id if worker is not None else active_bound_worker_id()
            if worker_id is not None:
                try:
                    self.workers.cancel(run.id, worker_id)
                except (PermissionError, ValueError):
                    pass
                self.store.settle_worker_binding(worker_id, "discarded")
            self._discard_late_result(run.id, task.id, attempt.id)
            self.store.settle_run(run.id)
            raise
        except Exception as exc:
            if delivery_lock_held:
                self._active_lock.release()
                delivery_lock_held = False
            if existing_binding is not None and delivery_owner_lock is None:
                # An attaching observer never owns the other controller's staging.
                raise
            current = self.store.get_worker_binding(worker.id) if worker is not None else None
            if current is not None and current.status == "settled":
                raise
            error = self._sanitize_error(exc)
            worker_id = worker.id if worker is not None else active_bound_worker_id()
            if worker_id is not None:
                try:
                    self.workers.cancel(run.id, worker_id)
                except (PermissionError, ValueError):
                    pass
                self.store.settle_worker_binding(worker_id, "discarded")
            if self._task_is_running(task.id):
                self.store.finish_task(task.id, attempt.id, False, error=error)
                # Validation failures can occur after result/runtime rows were staged.  Always
                # remove this attempt's staged evidence, even when the task transition wins.
                self._discard_late_result(run.id, task.id, attempt.id, error)
            else:
                self._discard_late_result(run.id, task.id, attempt.id, error)
            self.store.settle_run(run.id)
            raise
        finally:
            if delivery_lock_held:
                self._active_lock.release()
            if delivery_owner_lock is not None:
                delivery_owner_lock.close()

    def resume(self, run_id: str) -> Run:
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        current_plan = self.store.get_current_plan(run.id)
        if current_plan is not None:
            self._active_algorithm_contract(current_plan)
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run

        self.store.recover_running(run_id)
        run = self.store.get_run(run_id)
        assert run is not None
        started = time.monotonic()
        budget = run.budget or BudgetSpec()
        executor: ThreadPoolExecutor | None = None
        active_attempt_ids: set[str] = set()
        if self.max_workers > 1:
            executor = ThreadPoolExecutor(
                max_workers=self.max_workers,
                thread_name_prefix="lunar-worker",
            )
        try:
            while True:
                futures: list[Future[None]] = []
                claimed = 0
                while claimed < self.max_workers:
                    task = self.store.next_task(run_id)
                    if task is None:
                        break
                    self._check_budget(run_id, budget, started, before_claim=True)
                    try:
                        runtime = self._new_runtime()
                    except Exception as exc:  # noqa: BLE001 - factory is a runtime boundary
                        attempt = self.store.claim_task(task.id, getattr(self.runtime, "name", "runtime"))
                        if attempt is not None:
                            claimed += 1
                            self._record_task_failure(run, task, attempt, self._sanitize_error(exc))
                        continue
                    attempt = self.store.claim_task(task.id, getattr(runtime, "name", "runtime"))
                    if attempt is None:
                        continue
                    claimed += 1
                    active_attempt_ids.add(attempt.id)
                    with self._active_lock:
                        self._active_runtimes[attempt.id] = runtime
                    if executor is None:
                        self._execute_task(run, task, attempt, runtime, budget, started)
                    else:
                        futures.append(
                            executor.submit(
                                self._execute_task, run, task, attempt, runtime, budget, started
                            )
                        )
                if not claimed:
                    break
                budget_error: BudgetExceeded | None = None
                for future in futures:
                    try:
                        future.result()
                    except BudgetExceeded as exc:
                        budget_error = budget_error or exc
                with self._active_lock:
                    for attempt_id in active_attempt_ids:
                        self._active_runtimes.pop(attempt_id, None)
                active_attempt_ids.clear()
                if budget_error is not None:
                    raise budget_error
        except BudgetExceeded:
            # The ledger already contains the structured failure; return the failed run handle.
            pass
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
            with self._active_lock:
                for attempt_id in active_attempt_ids:
                    self._active_runtimes.pop(attempt_id, None)
            # A synchronous controller has no runner identity; a detached child clears only its
            # own PID so a newer runner cannot be accidentally cleared.
            self.store.clear_runner_process(run_id, os.getpid())
        settled = self.store.settle_run(run_id)
        assert settled is not None
        return settled

    def _new_runtime(self) -> Runtime:
        if self.max_workers > 1:
            assert self.runtime_factory is not None
            return self.runtime_factory()
        return self.runtime

    def _record_task_failure(self, run: Run, task: Any, attempt: Any, error: str) -> None:
        """Persist a failure for a task that could not enter its runtime worker."""
        del run
        if not self._task_is_running(task.id):
            return
        if self._can_retry(task.attempts + 1):
            self.store.retry_task(task.id, attempt.id, error)
        else:
            self.store.finish_task(task.id, attempt.id, False, error=error)

    def _execute_task(
        self,
        run: Run,
        task: Any,
        attempt: Any,
        runtime: Runtime,
        budget: BudgetSpec,
        started: float,
    ) -> None:
        """Execute one claimed task using only its private runtime and callback closures."""
        task_root = Path(run.workspace) / "tasks" / task.id / attempt.id
        artifacts = ArtifactStore(run.workspace, self.store, run.id)
        prompt = self._build_task_prompt(run, task)
        artifacts.write_text(
            f"tasks/{task.id}/{attempt.id}/prompt.md", prompt, task.id, kind="prompt"
        )
        with self._active_lock:
            self._active_runtimes[attempt.id] = runtime
        try:
            try:
                self._materialize_task_input_data(run, task_root)
                set_context = getattr(runtime, "set_context", None)
                if callable(set_context):
                    set_context(run.id, task.id, run.goal)
                set_session_path = getattr(runtime, "set_session_path", None)
                if callable(set_session_path):
                    set_session_path(Path(run.workspace) / "sessions" / task.id / "transcript.jsonl")
                set_event_sink = getattr(runtime, "set_event_sink", None)
                if callable(set_event_sink):
                    set_event_sink(
                        lambda event_type, payload, run_id=run.id, task_id=task.id: self.store.append_event(
                            run_id, event_type, payload, task_id=task_id
                        )
                    )
                set_observer = getattr(runtime, "set_process_observer", None)
                if callable(set_observer):
                    set_observer(
                        lambda pid, pgid, attempt_id=attempt.id: self.store.set_attempt_process(
                            attempt_id, pid, pgid
                        )
                    )
                if not self._task_is_running(task.id):
                    self._discard_late_result(run.id, task.id, attempt.id)
                    return
                runtime_timeout = self._remaining_runtime_timeout(
                    run.id, budget, started, self.config.runtime_timeout
                )
                result = runtime.run(prompt, task_root, runtime_timeout)
                if not self._task_is_running(task.id):
                    self._discard_late_result(run.id, task.id, attempt.id)
                    return
                self._record_session_artifact(run, task.id, runtime)
                result_path = artifacts.write_text(
                    f"tasks/{task.id}/{attempt.id}/result.txt", result.text, task.id
                )
                for relative_path in result.artifacts:
                    runtime_path = self._runtime_artifact_path(task_root, relative_path)
                    artifacts.record(runtime_path, task.id, kind="runtime")
                self._record_role_evidence(run, task, task_root)
                self._check_budget(run.id, budget, started)
                evaluation = self._evaluate(run, task, result.text, task_root)
                evaluation_payload = {
                    "attempt_id": attempt.id,
                    "passed": evaluation.passed,
                    "reason": evaluation.reason,
                    "evidence": list(evaluation.evidence),
                    "details": evaluation.details,
                }
                self.store.append_event(run.id, "task_evaluated", evaluation_payload, task_id=task.id)
                evaluation_path = artifacts.safe_path(f"tasks/{task.id}/{attempt.id}/evaluation.json")
                evaluation_path.parent.mkdir(parents=True, exist_ok=True)
                evaluation_path.write_text(
                    json.dumps(evaluation_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
                if not self._task_is_running(task.id):
                    self._discard_late_result(run.id, task.id, attempt.id)
                    return
                relative_result = str(result_path.relative_to(Path(run.workspace)))
                if evaluation.passed:
                    self._promote_algorithm_outputs(run, task, task_root, attempt_id=attempt.id)
                    finished = self.store.finish_task(task.id, attempt.id, True, relative_result)
                    if not finished:
                        self._discard_late_result(run.id, task.id, attempt.id)
                elif self._can_retry(task.attempts + 1):
                    self.store.retry_task(task.id, attempt.id, evaluation.reason)
                else:
                    finished = self.store.finish_task(
                        task.id, attempt.id, False, relative_result, evaluation.reason
                    )
                    if not finished:
                        self._discard_late_result(run.id, task.id, attempt.id, evaluation.reason)
            except BudgetExceeded:
                raise
            except AgentInputRequired as exc:
                if not self._task_is_running(task.id):
                    self._discard_late_result(run.id, task.id, attempt.id)
                    return
                self._record_session_artifact(run, task.id, runtime)
                request_payload = {
                    "status": "awaiting_input",
                    "run_id": run.id,
                    "task_id": task.id,
                    "attempt_id": attempt.id,
                    "question": exc.question,
                    "options": list(exc.options),
                }
                request_path = artifacts.write_text(
                    f"tasks/{task.id}/{attempt.id}/input-request.json",
                    json.dumps(request_payload, ensure_ascii=False, indent=2) + "\n",
                    task.id,
                    kind="input",
                )
                self.store.await_input(
                    task.id,
                    attempt.id,
                    str(request_path.relative_to(Path(run.workspace))),
                    exc.question,
                    exc.options,
                )
            except Exception as exc:  # noqa: BLE001 - runtime boundary must persist all failures
                if self._task_is_running(task.id):
                    self._enforce_runtime_deadline(run.id, budget, started)
                error = self._sanitize_error(exc)
                if self._task_is_running(task.id):
                    self._record_session_artifact(run, task.id, runtime)
                if not self._task_is_running(task.id):
                    self._discard_late_result(run.id, task.id, attempt.id, error)
                elif self._can_retry(task.attempts + 1):
                    self.store.retry_task(task.id, attempt.id, error)
                else:
                    self.store.finish_task(task.id, attempt.id, False, error=error)
        finally:
            if callable(getattr(runtime, "set_event_sink", None)):
                runtime.set_event_sink(None)
            if callable(getattr(runtime, "set_process_observer", None)):
                runtime.set_process_observer(None)
            with self._active_lock:
                self._active_runtimes.pop(attempt.id, None)

    def _attempt_registration(self, attempt_id: str, pid: int, pgid: int) -> RegisteredProcess:
        return RegisteredProcess(
            pid, pgid,
            owner_check=lambda: (
                (current := self.store.get_attempt(attempt_id)) is not None
                and current.pid == pid and current.pgid == pgid
            ),
            label=f"attempt:{attempt_id}",
        )

    def _cleanup_process_registrations(self, registrations) -> None:
        # A foreground coordinator must finish its own terminal bookkeeping. External cancel
        # callers still terminate detached coordinators, after all registered work groups.
        targets = tuple(reg for reg in registrations if not (
            reg.label.startswith("run:") and reg.pid == os.getpid()
        ))
        results = cleanup_registered_processes(targets)
        for registration, result in zip(targets, results, strict=True):
            if result.status not in {ProcessCleanupStatus.CLEANED, ProcessCleanupStatus.ALREADY_EXITED}:
                continue
            if registration.label.startswith("run:"):
                self.store.clear_runner_process(
                    registration.label.removeprefix("run:"), registration.pid, registration.pgid,
                )
            elif registration.label.startswith("attempt:"):
                attempt_id = registration.label.removeprefix("attempt:")
                with self._active_lock:
                    release = self._automatic_process_releases.get((attempt_id, registration.pid, registration.pgid))
                if release is None:
                    self.store.clear_attempt_process(attempt_id, registration.pid, registration.pgid)
                else:
                    try:
                        release()
                    except Exception:  # noqa: BLE001, S110 - retain native registration after outer release failure
                        pass

    def attempt_process_observers(self, run_id: str, attempt_id: str, *, parent_id: str | None = None):
        """Register sequential local work and reject a launch that lost its execution owner.

        Registration precedes the terminal-state check: cancellation either observes this row,
        or the registering thread observes cancellation and cleans this exact process itself.
        """
        def observe_native(pid: int, pgid: int | None) -> None:
            attempt = self.store.get_attempt(attempt_id)
            task = self.store.get_task(attempt.task_id) if attempt is not None else None
            if task is None or task.run_id != run_id:
                raise ValueError("process attempt does not belong to run")
            if (isinstance(attempt.pid, int) and isinstance(attempt.pgid, int)
                    and (attempt.pid, attempt.pgid) != (pid, pgid)):
                # Sequential work must not overwrite a registration retained after failed
                # cleanup. Retry that exact owner; if still unresolved, stop the just-spawned
                # private group while keeping the original durable record available.
                self._cleanup_process_registrations((
                    self._attempt_registration(attempt_id, attempt.pid, attempt.pgid),
                ))
                retained = self.store.get_attempt(attempt_id)
                if retained is not None and retained.pid is not None:
                    if isinstance(pgid, int):
                        cleanup_registered_processes((RegisteredProcess(
                            pid, pgid, owner_check=lambda: True, label="unregistered-launch",
                        ),))
                    return
            self.store.set_attempt_process(attempt_id, pid, pgid)
            current = self.store.get_run(run_id)
            latest = self.store.get_attempt(attempt_id)
            stopped = (current is None or current.status in {
                RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.SUCCEEDED,
            } or latest is None or latest.status != "running")
            if parent_id is not None:
                parent = self.store.get_run(parent_id)
                authority = self._automatic_cancel_targets(parent_id)
                stopped = stopped or (parent is None or parent.status in {
                    RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.SUCCEEDED,
                } or authority is None or not authority.verified or authority.child_id != run_id)
            if stopped and isinstance(pgid, int):
                self._cleanup_process_registrations((self._attempt_registration(attempt_id, pid, pgid),))

        def release_native(pid: int, pgid: int | None) -> None:
            if pgid is not None:
                return self.store.clear_attempt_process(attempt_id, pid, pgid)
            return True

        scope = self._current_automatic_observation()
        if scope is None:
            return observe_native, release_native
        scope.validate_run(run_id, parent_id)
        registered: set[tuple[int, int]] = set()
        released: set[tuple[int, int]] = set()

        def release_owned(pid: int, pgid: int) -> None:
            scope.require_active()
            scope.validate_run(run_id, parent_id)
            attempt = self.store.get_attempt(attempt_id)
            task = self.store.get_task(attempt.task_id) if attempt is not None else None
            if task is None or task.run_id != run_id:
                raise ValueError("process attempt does not belong to run")
            if (attempt.pid, attempt.pgid) != (pid, pgid):
                raise ValueError("automatic worker process release is stale")
            try:
                if scope.released(run_id, attempt_id, pid, pgid) is False:
                    raise ValueError("outer process release was not confirmed")
                if not self.store.clear_attempt_process(attempt_id, pid, pgid):
                    raise ValueError("native process release was not confirmed")
            except Exception:
                scope.failed = True
                raise
            released.add((pid, pgid))
            with self._active_lock:
                self._automatic_process_releases.pop((attempt_id, pid, pgid), None)

        def observe(pid: int, pgid: int | None) -> None:
            scope.require_current()
            scope.validate_run(run_id, parent_id)
            if any(type(value) is not int or value <= 1 for value in (pid, pgid)):
                scope.failed = True
                raise ValueError("automatic worker process identity is invalid")
            attempt = self.store.get_attempt(attempt_id)
            task = self.store.get_task(attempt.task_id) if attempt is not None else None
            if task is None or task.run_id != run_id:
                scope.failed = True
                raise ValueError("process attempt does not belong to run")
            if (attempt.pid, attempt.pgid) != (None, None) and (attempt.pid, attempt.pgid) != (pid, pgid):
                if type(attempt.pid) is int and type(attempt.pgid) is int:
                    self._cleanup_process_registrations((
                        self._attempt_registration(attempt_id, attempt.pid, attempt.pgid),
                    ))
                retained = self.store.get_attempt(attempt_id)
                if retained is not None and (retained.pid, retained.pgid) != (None, None):
                    scope.failed = True
                    cleanup_registered_processes((RegisteredProcess(
                        pid, pgid, owner_check=lambda: True, label="unregistered-launch",
                    ),))
                    raise ValueError("automatic worker attempt still owns another process")
            try:
                if not self.store.set_attempt_process(attempt_id, pid, pgid):
                    raise ValueError("native process registration was not confirmed")
                registered.add((pid, pgid))
                released.discard((pid, pgid))
                with self._active_lock:
                    self._automatic_process_releases[(attempt_id, pid, pgid)] = lambda: release_owned(pid, pgid)
                if scope.observer(run_id, attempt_id, pid, pgid) is False:
                    raise ValueError("outer process registration was not confirmed")
                scope.check()
                current = self.store.get_run(run_id)
                latest = self.store.get_attempt(attempt_id)
                parent = self.store.get_run(scope.parent_id)
                if (current is None or current.status in {RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.SUCCEEDED}
                        or latest is None or latest.status != "running" or parent is None
                        or parent.status in {RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.SUCCEEDED}):
                    raise SolveExecutionCancelled("runtime")
            except Exception:
                scope.failed = True
                # The native registration is retained before calling the outer observer, so
                # cleanup uses one exact native ownership decision even after partial failure.
                current = self.store.get_attempt(attempt_id)
                if current is not None and (current.pid, current.pgid) == (pid, pgid):
                    self._cleanup_process_registrations((self._attempt_registration(attempt_id, pid, pgid),))
                else:
                    cleanup_registered_processes((RegisteredProcess(
                        pid, pgid, owner_check=lambda: True, label="unregistered-launch",
                    ),))
                raise

        def release(pid: int, pgid: int | None) -> None:
            scope.require_current()
            scope.validate_run(run_id, parent_id)
            if (pid, pgid) not in registered:
                raise ValueError("automatic worker process release is stale")
            if (pid, pgid) not in released:
                release_owned(pid, pgid)

        return observe, release

    class _AutomaticWorkerObservationScope:
        __slots__ = ("active", "controller", "failed", "guard", "observer", "parent_id", "released")

        def __init__(self, controller, parent_id, observer, released, guard) -> None:
            self.controller = controller
            self.parent_id = parent_id
            self.observer = observer
            self.released = released
            self.guard = guard
            self.active = True
            self.failed = False

        def require_active(self) -> None:
            if not self.active:
                raise ValueError("automatic worker observation scope is no longer active")

        def require_current(self) -> None:
            self.require_active()
            if self.controller._current_automatic_observation() is not self:
                raise ValueError("automatic worker observation scope is not current")

        def validate_run(self, run_id: str, parent_id: str | None) -> None:
            authority = self.controller._automatic_cancel_targets(self.parent_id)
            if authority is None or not authority.verified:
                raise ValueError("automatic worker native ownership cannot be verified")
            if run_id == self.parent_id and parent_id is None:
                return
            if parent_id != self.parent_id or authority.child_id != run_id:
                raise ValueError("automatic worker child ownership cannot be verified")

        def check(self) -> None:
            self.require_current()
            self.guard()
            if self.failed:
                raise SolveExecutionCancelled("worker_observation")

    def _current_automatic_observation(self):
        if (self._automatic_observation_owner is not None
                and self._automatic_observation_owner != threading.get_ident()):
            raise RuntimeError("automatic controller runtime is owned by another thread")
        scope = getattr(self._automatic_observation_local, "scope", None)
        return scope if scope is not None and scope.active else None

    @contextmanager
    def _automatic_observation_ownership(self):
        if not self._automatic_observation_lock.acquire(blocking=False):
            raise RuntimeError("automatic controller runtime is owned by another thread")
        self._automatic_observation_owner = threading.get_ident()
        self._automatic_observation_depth += 1
        try:
            yield
        finally:
            self._automatic_observation_depth -= 1
            if self._automatic_observation_depth == 0:
                self._automatic_observation_owner = None
            self._automatic_observation_lock.release()

    @contextmanager
    def automatic_worker_observation(self, parent_id: str, observer, released, guard):
        """Compose one exact worker owner around native attempt observation and cleanup.

        Native runtime scopes may nest on the owning thread.  Another thread cannot replace
        this controller's hooks, and callbacks retained beyond this context are revoked.  Native
        cleanup remains the sole signalling authority; outer release must confirm the exact
        process before its native registration can be cleared.
        """
        if not isinstance(parent_id, str) or not parent_id.strip():
            raise ValueError("automatic worker parent ID must be non-empty")
        if not all(callable(callback) for callback in (observer, released, guard)):
            raise TypeError("automatic worker observation callbacks must be callable")
        with self._automatic_observation_ownership():
            prior = self._current_automatic_observation()
            scope = self._AutomaticWorkerObservationScope(self, parent_id, observer, released, guard)
            scope.validate_run(parent_id, None)
            self._automatic_observation_local.scope = scope
            try:
                yield scope
                if scope.failed:
                    raise SolveExecutionCancelled("worker_observation")
            finally:
                scope.active = False
                self._automatic_observation_local.scope = prior

    def _automatic_worker_guard(self, run_id: str, parent_id: str | None = None) -> None:
        scope = self._current_automatic_observation()
        if scope is not None:
            scope.validate_run(run_id, parent_id)
            scope.check()

    def ensure_attempt_process_released(self, run_id: str, attempt_id: str, *, parent_id: str | None = None) -> None:
        """A sequential automatic stage cannot continue past unresolved local cleanup."""
        attempt = self.store.get_attempt(attempt_id)
        if attempt is None or attempt.pid is None or attempt.pgid is None:
            return
        self._cleanup_process_registrations((
            self._attempt_registration(attempt.id, attempt.pid, attempt.pgid),
        ))
        current = self.store.get_attempt(attempt_id)
        if current is None or current.pid is None:
            return
        self.store.finish_task(attempt.task_id, attempt.id, False, error="automatic process cleanup failed")
        self.store.settle_run(run_id)
        if parent_id is not None:
            parent_run = self.store.get_run(parent_id)
            if parent_run is not None and parent_run.status not in {
                RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.SUCCEEDED,
            }:
                self.store.fail_budget(
                    parent_id, "automatic_process_cleanup", 1.0, 0.0,
                    "automatic process cleanup failed",
                )
            for task in self.store.list_tasks(parent_id):
                active = self.store.active_attempt(task.id) if task.orchestration else None
                if active is not None:
                    self.store.finish_task(task.id, active.id, False, error="automatic process cleanup failed")
            self.store.settle_run(parent_id)
        raise SolveExecutionCancelled("process_cleanup")

    @contextmanager
    def observe_attempt_runtime(self, run_id: str, attempt_id: str, *, parent_id: str | None = None):
        """Bind the existing runtime and optional local tools to one automatic attempt."""
        observe, release = self.attempt_process_observers(run_id, attempt_id, parent_id=parent_id)
        scope = self._current_automatic_observation()

        def native_guard() -> None:
            for target in (run_id, parent_id):
                if target is None:
                    continue
                current = self.store.get_run(target)
                if current is None or current.status in {
                    RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.SUCCEEDED,
                }:
                    raise SolveExecutionCancelled("runtime")
            self.ensure_attempt_process_released(run_id, attempt_id, parent_id=parent_id)

        def guard() -> None:
            if scope is not None:
                scope.validate_run(run_id, parent_id)
                scope.check()
            native_guard()

        callback_key = id(self.runtime)
        callback_map = getattr(self._runtime_observation_callbacks, "values", None)
        if callback_map is None:
            callback_map = {}
            self._runtime_observation_callbacks.values = callback_map
        prior_callbacks = callback_map.get(callback_key)
        if prior_callbacks is None:
            prior_callbacks = tuple(
                getattr(self.runtime, name, None)
                for name in ("_process_observer", "_process_released", "_continuation_guard")
            )
        callback_map[callback_key] = (observe, release, guard)
        with self._active_lock:
            prior_runtime = self._active_runtimes.get(attempt_id)
            self._active_runtimes[attempt_id] = self.runtime
        try:
            for name, callback in (("set_process_observer", observe), ("set_process_released", release),
                                   ("set_continuation_guard", guard)):
                setter = getattr(self.runtime, name, None)
                if callable(setter):
                    setter(callback)
            yield observe, release
        finally:
            for name, callback in zip(
                ("set_process_observer", "set_process_released", "set_continuation_guard"),
                prior_callbacks,
                strict=True,
            ):
                setter = getattr(self.runtime, name, None)
                if callable(setter):
                    try:
                        setter(callback)
                    except Exception:  # noqa: BLE001, S110 - fan-out must survive adapter failure
                        pass
            with self._active_lock:
                if prior_runtime is None:
                    self._active_runtimes.pop(attempt_id, None)
                else:
                    self._active_runtimes[attempt_id] = prior_runtime
            if prior_callbacks == (None, None, None):
                callback_map.pop(callback_key, None)
            else:
                callback_map[callback_key] = prior_callbacks

    def _cancel_active_callbacks(self, run_ids: set[str] | None = None) -> None:
        with self._active_lock:
            active = [*self._active_runtimes.items(), *self._active_agents.items()]
        cancellables = []
        for attempt_id, runtime in active:
            attempt = self.store.get_attempt(attempt_id)
            task = self.store.get_task(attempt.task_id) if attempt is not None else None
            if run_ids is None or (task is not None and task.run_id in run_ids):
                cancellables.append(runtime)
        if run_ids is None and not cancellables:
            cancellables = [self.runtime]
        seen: set[int] = set()
        for runtime in cancellables:
            if id(runtime) in seen:
                continue
            seen.add(id(runtime))
            try:
                runtime.cancel()
            except Exception:  # noqa: BLE001, S110 - one adapter must not prevent remaining cleanup
                pass

    def cleanup_automatic_solve(self, parent_id: str) -> None:
        """Clean owned work even after a terminal Store write changed attempt statuses."""
        scope = self._automatic_cancel_targets(parent_id)
        if scope is None or not scope.verified:
            return
        run_ids = {parent_id}
        if scope.child_id is not None:
            run_ids.add(scope.child_id)
        attempts = tuple(reg for reg in scope.targets if reg.label.startswith("attempt:"))
        runners = tuple(reg for reg in scope.targets if reg.label.startswith("run:"))
        self._cleanup_process_registrations(attempts)
        self._cancel_active_callbacks(run_ids)
        self._cleanup_process_registrations(runners)

    def cancel(self, run_id: str) -> bool:
        with self._active_lock:
            cancelled = self.store.cancel_run(run_id)
            run = self.store.get_run(run_id)
            if not cancelled and (run is None or run.status != RunStatus.CANCELLED):
                return False
            # A delegated scheduler attempt has one durable reciprocal binding.  Stop only those
            # workers rather than treating every worker owned by the run as a cancellation target.
            for binding in self.store.list_worker_bindings(run_id):
                if binding.status not in {"active", "delivering"}:
                    continue
                try:
                    self.workers.cancel(run_id, binding.worker_id)
                except (PermissionError, ValueError):
                    continue
                self.store.settle_worker_binding(binding.worker_id, "discarded")
        # Snapshot after stopping admission. Late registrations independently recheck the stop.
        scope = self._automatic_cancel_targets(run_id)
        if scope is None:
            if cancelled and run is not None:
                self._cancel_active_callbacks()
                self._terminate_process_group(run.runner_pid, run.runner_pgid)
                self.store.clear_runner_process(run_id)
        elif scope.verified:
            if scope.child_id is not None:
                self.store.cancel_run(scope.child_id)
            self.cleanup_automatic_solve(run_id)
        for binding in self.store.list_worker_bindings(run_id, status="discarded"):
            try:
                lock = self._worker_delivery_lock(binding.worker_id)
            except (OSError, ValueError):
                continue
            if lock is None:
                continue  # The live delivery owner will discard before releasing its lock.
            try:
                self._discard_late_result(
                    run_id, binding.task_id, binding.task_attempt_id, record_event=False,
                )
            finally:
                lock.close()
        return cancelled

    def _automatic_cancel_targets(self, parent_id: str) -> _AutomaticCancelDecision | None:
        """Select parent work and, only with exact reciprocal evidence, child work.

        No marker selects legacy behavior. Any malformed marker/link fails closed. Before a
        child is linked, the exact lifecycle marker still authorizes the parent's own work.
        """
        parent = self.store.get_run(parent_id)
        if parent is None:
            return None
        events = self.store.list_events(parent_id)
        requests = [e.get("payload") for e in events if e.get("type") == "evolution_requested"]
        if not requests:
            return None
        marked = [r for r in requests if isinstance(r, dict) and "automatic_lifecycle_version" in r]
        if not marked:
            return None
        if len(requests) != 1 or not isinstance(requests[0], dict):
            return _AutomaticCancelDecision()
        request = requests[-1]
        if (request.get("bundle_mode") != "compiled"
                or type(request.get("automatic_lifecycle_version")) is not int
                or request["automatic_lifecycle_version"] != 1):
            return _AutomaticCancelDecision()
        links = [e.get("payload") for e in events if e.get("type") == "evolution_linked"]
        child = None
        if links:
            try:
                contract = self._algorithm_contract(parent)
            except (ValueError, TypeError, KeyError):
                return _AutomaticCancelDecision()
            if contract is None or len(links) != 1 or not isinstance(links[0], dict):
                return _AutomaticCancelDecision()
            digest = contract.digest()
            child_id = links[0].get("evolution_run_id")
            if (not isinstance(child_id, str) or not child_id or child_id == parent_id
                    or links[0] != {"evolution_run_id": child_id, "contract_sha256": digest,
                                    "strategy": "population"}):
                return _AutomaticCancelDecision()
            child = self.store.get_run(child_id)
            reverse = [e.get("payload") for e in self.store.list_events(child_id)
                       if e.get("type") == "evolution_parent_linked"]
            if child is None or reverse != [{"parent_run_id": parent_id, "contract_sha256": digest}]:
                return _AutomaticCancelDecision()
        registrations: list[RegisteredProcess] = []
        runs = [parent] + ([child] if child is not None else [])
        for run in runs:
            for row in self.store.list_attempt_processes(run.id):
                pid, pgid, attempt_id = row.get("pid"), row.get("pgid"), row.get("id")
                if isinstance(pid, int) and isinstance(pgid, int) and isinstance(attempt_id, str):
                    registrations.append(self._attempt_registration(attempt_id, pid, pgid))
        # A detached parent coordinates the whole execution and must be stopped last.
        for run in reversed(runs):
            if not isinstance(run.runner_pid, int) or not isinstance(run.runner_pgid, int):
                continue
            run_id, pid, pgid = run.id, run.runner_pid, run.runner_pgid
            registrations.append(RegisteredProcess(
                pid, pgid,
                owner_check=lambda run_id=run_id, pid=pid, pgid=pgid: (
                    (current := self.store.get_run(run_id)) is not None
                    and current.runner_pid == pid and current.runner_pgid == pgid
                ),
                label=f"run:{run_id}",
            ))
        return _AutomaticCancelDecision(
            child_id=child.id if child is not None else None, targets=tuple(registrations), verified=True,
        )

    def recover(self, run_id: str) -> RecoveryProposal:
        """Persist an advisory recovery proposal without changing execution state.

        This is deliberately separate from :meth:`resume`: a parent Agent or owner decides whether
        to apply a patch/replan, answer input, or resume a runtime after inspecting the evidence.
        """
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        tasks = self.store.list_tasks(run.id)
        proposal = self.recovery_policy.propose(
            run, tasks, self.store.list_events(run.id), self.store.pending_input(run.id)
        )
        target_task_id = proposal.task_id or (tasks[0].id if tasks else None)
        if target_task_id is None:
            raise ValueError("run has no task to own the recovery artifact")
        relative_path = f"recovery/proposals/{proposal.fingerprint}.json"
        persisted = proposal.with_artifact_path(relative_path)
        artifacts = ArtifactStore(run.workspace, self.store, run.id)
        if not any(
            item["path"] == relative_path and item["kind"] == "recovery"
            for item in self.store.list_artifacts(run.id)
        ):
            artifacts.write_text(
                relative_path,
                json.dumps(persisted.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                target_task_id,
                kind="recovery",
            )
        self.store.append_event(
            run.id,
            "recovery_proposed",
            {"proposal": persisted.to_dict()},
            task_id=proposal.task_id,
            event_id=proposal.event_id,
        )
        return persisted

    def _task_is_running(self, task_id: str) -> bool:
        task = self.store.get_task(task_id)
        return task is not None and task.state.value == "running"

    def _reconcile_worker_run(self, run_id: str) -> None:
        """Recover abandoned worker ownership and settle its scheduler binding."""
        self.workers.reconcile(run_id)
        for binding in self.store.list_worker_bindings(run_id, status="lost"):
            task = self.store.get_task(binding.task_id)
            attempt = self.store.get_attempt(binding.task_attempt_id)
            if task is None or attempt is None or task.state.value != "running":
                continue
            error = "worker_lost"
            if self.store.finish_task(task.id, attempt.id, False, error=error):
                self.store.append_event(
                    run_id,
                    "worker_lost_settled",
                    {"worker_id": binding.worker_id, "attempt_id": attempt.id, "error": error},
                    task_id=task.id,
                )
        self.store.settle_run(run_id)

    @staticmethod
    def _runner_is_stale(run: Run) -> bool:
        """Return whether it is safe for a delegation caller to recover running tasks."""
        if run.runner_pid is None:
            return True
        if run.runner_pid == os.getpid():
            return True
        try:
            os.kill(run.runner_pid, 0)
        except (OSError, ProcessLookupError):
            return True
        return False

    def _validate_route(self, route: RouteDecision) -> None:
        """Reject missing profile configuration before any durable work is created."""
        self.profiles.solver(route.solver_profile)
        if self.evaluator is None:
            self.profiles.evaluator(route.evaluator_profile)

    def _record_session_artifact(self, run: Run, task_id: str, runtime: Runtime | None = None) -> None:
        runtime = runtime or self.runtime
        get_session_path = getattr(runtime, "session_path", None)
        if not callable(get_session_path):
            return
        path = get_session_path()
        if path is None or not Path(path).is_file():
            return
        try:
            relative = str(Path(path).resolve().relative_to(Path(run.workspace).resolve()))
        except ValueError:
            return
        if any(
            artifact["path"] == relative and artifact["kind"] == "session"
            for artifact in self.store.list_artifacts(run.id)
        ):
            return
        ArtifactStore(run.workspace, self.store, run.id).record(path, task_id, kind="session")

    @staticmethod
    def _latest_artifacts_by_path(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Return the newest ledger row for each path without mutating append-only history."""
        latest: dict[str, dict[str, Any]] = {}
        for artifact in artifacts:
            path = artifact.get("path")
            if isinstance(path, str):
                latest[path] = artifact
        return latest

    def _algorithm_contract(self, run: Run) -> AlgorithmProblemContract | None:
        plan = self.store.get_current_plan(run.id)
        if plan is None or plan.algorithm_problem is None:
            return None
        return AlgorithmProblemContract.from_dict(plan.algorithm_problem)

    def _task_output_specs(self, run: Run, task: Any) -> tuple[OutputSpec, ...]:
        """Return declared outputs for the Solver task, if this run has an algorithm contract.

        Output paths are logical paths relative to an attempt workspace.  Only the built-in
        ``solve``/``solver`` plan roles are allowed to publish them; discovery and verification
        roles may inspect the resulting run-level files but cannot accidentally overwrite them.
        """
        if (task.plan_task_id or task.id) not in {"solve", "solver"}:
            return ()
        contract = self._algorithm_contract(run)
        return contract.outputs if contract is not None else ()

    @staticmethod
    def _role_evidence_specs(value: object) -> tuple[tuple[str, str], ...]:
        """Extract explicitly declared role-evidence paths from a task acceptance contract."""
        found: list[tuple[str, str]] = []

        def visit(item: object) -> None:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except (TypeError, json.JSONDecodeError):
                    return
            if isinstance(item, dict):
                if len(item) == 1:
                    rule, payload = next(iter(item.items()))
                    if rule in {"artifact_valid", "data_profile_valid", "evaluation_report_valid"}:
                        path = payload.get("path") if isinstance(payload, dict) else payload
                        if isinstance(path, str):
                            pair = (rule, path)
                            if pair not in found:
                                found.append(pair)
                for child in item.values():
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(value)
        return tuple(found[:16])

    def _record_role_evidence(self, run: Run, task: Any, task_root: Path) -> tuple[dict[str, Any], ...]:
        """Hash present role hand-off files, including invalid files for retry/audit evidence."""
        specs = self._role_evidence_specs(task.acceptance)
        if not specs:
            return ()
        root = Path(run.workspace).expanduser().resolve(strict=False)
        artifacts = ArtifactStore(root, self.store, run.id)
        recorded: list[dict[str, Any]] = []
        for rule, relative in specs:
            source = self._confined_regular_file(task_root, relative)
            if source is None:
                continue
            size = source.stat().st_size
            if size > MAX_ARTIFACT_BYTES:
                raise ArtifactError(f"role evidence exceeds {MAX_ARTIFACT_BYTES} bytes: {relative}")
            artifact_id = artifacts.record(source, task.id, kind="role_evidence")
            recorded.append({"artifact_id": artifact_id, "rule": rule, "path": str(source.relative_to(root)), "size": size})
        if recorded:
            self.store.append_event(
                run.id,
                "role_evidence_recorded",
                {"artifacts": recorded},
                task_id=task.id,
            )
        return tuple(recorded)

    def _materialize_task_input_data(self, run: Run, task_root: Path) -> tuple[str, ...]:
        """Copy hashed run inputs into a private attempt workspace.

        Runtime and Agent adapters are intentionally confined to ``task_root``.  Copying verified
        input artifacts to the same relative ``data/raw/...`` path gives every attempt deterministic
        read access without granting it access to the run ledger or another attempt's files.
        """
        input_artifacts = [
            item
            for item in self.store.list_artifacts(run.id)
            if item["kind"] == "input_data"
        ]
        if len(input_artifacts) > MAX_INPUT_FILES:
            raise ArtifactError(f"run has more than {MAX_INPUT_FILES} staged input files")
        if not input_artifacts:
            return ()
        root = Path(run.workspace).expanduser().resolve(strict=False)
        task_root = task_root.expanduser().resolve(strict=False)
        copied: list[str] = []
        for artifact in input_artifacts:
            relative = artifact.get("path")
            expected_digest = artifact.get("sha256")
            expected_size = artifact.get("size")
            if (
                not isinstance(relative, str)
                or not relative.startswith("data/raw/")
                or not isinstance(expected_digest, str)
                or not isinstance(expected_size, int)
                or expected_size > MAX_INPUT_FILE_BYTES
            ):
                raise ArtifactError("staged input artifact metadata is malformed")
            source = self._confined_regular_file(root, relative)
            if source is None:
                raise ArtifactError(f"staged input is missing or unsafe: {relative}")
            content = source.read_bytes()
            if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_digest:
                raise ArtifactError(f"staged input digest does not match the ledger: {relative}")
            target = (task_root / relative).resolve(strict=False)
            try:
                target.relative_to(task_root)
            except ValueError as exc:
                raise ArtifactError(f"staged input escapes task workspace: {relative}") from exc
            if self._raw_path_has_symlink(task_root, target):
                raise ArtifactError(f"staged input target is symlinked: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_bytes(content)
            temporary.replace(target)
            copied.append(relative)
        return tuple(copied)

    @staticmethod
    def _raw_path_has_symlink(root: Path, path: Path) -> bool:
        """Check every existing component without following a symlink."""
        current = path
        while True:
            # ``Path.exists`` is false for a dangling symlink; inspect the link itself first so a
            # target cannot be swapped after validation or escape through a broken link.
            if current.is_symlink():
                return True
            if current == root:
                return False
            if current.parent == current:
                return True
            current = current.parent

    def _confined_regular_file(self, root: Path, relative_path: str) -> Path | None:
        """Resolve a regular, non-symlink file below ``root`` or return ``None``."""
        root = root.expanduser().resolve(strict=False)
        if root.is_symlink() or "\x00" in relative_path:
            return None
        raw = root / relative_path
        if self._raw_path_has_symlink(root, raw):
            return None
        resolved = raw.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            return None
        if not resolved.is_file() or resolved.is_symlink():
            return None
        return resolved

    def _promote_algorithm_outputs(
        self, run: Run, task: Any, task_root: Path, *, attempt_id: str | None = None,
        worker_delivery: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        """Copy verified Solver data files to stable run-level output paths and hash them.

        The runtime receives an attempt-local workspace so retries and parallel tasks remain
        isolated.  Promotion happens only after the complete evaluation passes, which gives
        callers a stable ``<run>/output/...`` location and prevents unverified files from being
        delivered.  Optional outputs are promoted when present; required outputs must already
        have passed the independent output evaluator.
        """
        specs = self._task_output_specs(run, task)
        if not specs:
            return ()
        root = Path(run.workspace).expanduser().resolve(strict=False)
        promoted: list[dict[str, Any]] = []
        artifacts = ArtifactStore(root, self.store, run.id)
        for output in specs:
            source = self._confined_regular_file(task_root, output.path)
            if source is None:
                if output.required:
                    raise ArtifactError(f"required algorithm output is missing: {output.path}")
                continue
            # Keep the same bounded inspection/ledger limit used by output_valid.  This prevents
            # a successful model turn from smuggling an unbounded binary into the run archive.
            size = source.stat().st_size
            if size > MAX_ARTIFACT_BYTES:
                raise ArtifactError(
                    f"algorithm output exceeds {MAX_ARTIFACT_BYTES} bytes: {output.path}"
                )
            artifact_id = None
            if worker_delivery:
                identity = json.dumps([run.id, task.id, attempt_id, output.path]).encode("utf-8")
                artifact_id = "artifact-worker-output-" + hashlib.sha256(identity).hexdigest()
                # Persist exact output ownership before the first filesystem write. Recovery
                # can clean even a crash between replacing the file and recording its ledger.
                self.store.append_event(
                    run.id, "worker_delivery_output_prepared",
                    {"attempt_id": attempt_id, "path": output.path, "artifact_id": artifact_id},
                    task_id=task.id, event_id="event-" + artifact_id,
                )
            target = self._confined_output_target(root, output.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_bytes(source.read_bytes())
            temporary.replace(target)
            if worker_delivery:
                artifact_id = artifacts.record(target, task.id, kind="output", artifact_id=artifact_id)
            else:
                artifact_id = artifacts.record(target, task.id, kind="output")
            promoted.append(
                {
                    "artifact_id": artifact_id,
                    "path": output.path,
                    "format": output.format,
                    "fields": list(output.fields),
                    "required": output.required,
                    "size": size,
                }
            )
        if promoted:
            payload: dict[str, Any] = {"outputs": promoted}
            if attempt_id is not None:
                payload["attempt_id"] = attempt_id
            self.store.append_event(
                run.id,
                "algorithm_outputs_promoted",
                payload,
                task_id=task.id,
            )
        return tuple(promoted)

    def _confined_output_target(self, root: Path, relative_path: str) -> Path:
        """Resolve a run-level output target while rejecting symlinked directories."""
        root = root.expanduser().resolve(strict=False)
        raw = root / relative_path
        output_root = root / "output"
        if self._raw_path_has_symlink(root, output_root) or self._raw_path_has_symlink(root, raw):
            raise ArtifactError(f"algorithm output path is symlinked: {relative_path}")
        resolved = raw.resolve(strict=False)
        try:
            resolved.relative_to(root)
            resolved.relative_to(output_root.resolve(strict=False))
        except ValueError as exc:
            raise ArtifactError(f"algorithm output escapes run workspace: {relative_path}") from exc
        if resolved == output_root:
            raise ArtifactError("algorithm output path must name a file")
        return resolved

    def _evaluate(self, run: Run, task: Any, result: str, workspace: Path) -> Evaluation:
        evaluator = self.evaluator or self.profiles.evaluator(run.evaluator_profile or "general")
        base = evaluator.evaluate(result, workspace)
        criterion = acceptance_evaluator(task.acceptance)
        output_specs = self._task_output_specs(run, task)
        if criterion is None and not output_specs:
            return base
        acceptance = criterion.evaluate(result, workspace) if criterion is not None else None
        # Custom alternatives cannot waive the algorithm's declared output contract.
        outputs = evaluate_output_contract(output_specs, workspace) if output_specs else None
        checks = [item for item in (acceptance, outputs) if item is not None]
        evidence = tuple(base.evidence) + tuple(
            evidence_item for item in checks for evidence_item in item.evidence
        )
        details: dict[str, object] = {"base": base.details}
        if acceptance is not None:
            details["acceptance"] = acceptance.details
        if outputs is not None:
            details["outputs"] = outputs.details
        if base.passed and all(item.passed for item in checks):
            reasons = "; ".join([base.reason, *(item.reason for item in checks)])
            return Evaluation(True, evidence, reasons, details)
        reasons = [
            reason
            for passed, reason in [
                (base.passed, base.reason),
                *((item.passed, item.reason) for item in checks),
            ]
            if not passed
        ]
        return Evaluation(False, evidence, "; ".join(reasons), details)

    def _check_budget(self, run_id: str, budget: BudgetSpec, started: float, *, before_claim: bool = False) -> None:
        tasks = self.store.list_tasks(run_id)
        attempts = sum(task.attempts for task in tasks)
        if len(tasks) > budget.max_tasks:
            self._budget_fail(run_id, "max_tasks", len(tasks), budget.max_tasks)
        if before_claim and attempts >= budget.max_attempts:
            self._budget_fail(run_id, "max_attempts", attempts, budget.max_attempts)
        elapsed = time.monotonic() - started
        if elapsed > budget.max_runtime_seconds:
            self._budget_fail(run_id, "max_runtime_seconds", elapsed, budget.max_runtime_seconds)
        tool_steps = sum(1 for event in self.store.list_events(run_id) if event["type"] == "agent_tool_result")
        if tool_steps > budget.max_tool_steps:
            self._budget_fail(run_id, "max_tool_steps", tool_steps, budget.max_tool_steps)
        artifact_bytes = sum(int(item["size"]) for item in self.store.list_artifacts(run_id))
        if artifact_bytes > budget.max_artifact_bytes:
            self._budget_fail(run_id, "max_artifact_bytes", artifact_bytes, budget.max_artifact_bytes)

    def _remaining_runtime_timeout(
        self,
        run_id: str,
        budget: BudgetSpec,
        started: float,
        configured_timeout: float | None,
    ) -> float:
        """Return the request timeout left in the shared run wall-clock budget."""
        elapsed = max(0.0, time.monotonic() - started)
        remaining = float(budget.max_runtime_seconds) - elapsed
        if remaining <= 0:
            self._budget_fail(
                run_id,
                "max_runtime_seconds",
                elapsed,
                budget.max_runtime_seconds,
            )
        if configured_timeout is None:
            return remaining
        return min(float(configured_timeout), remaining)

    def _enforce_runtime_deadline(
        self, run_id: str, budget: BudgetSpec, started: float
    ) -> None:
        """Persist a wall-clock failure when a running worker crossed its deadline."""
        elapsed = max(0.0, time.monotonic() - started)
        if elapsed >= budget.max_runtime_seconds:
            self._budget_fail(
                run_id,
                "max_runtime_seconds",
                elapsed,
                budget.max_runtime_seconds,
            )

    def _budget_fail(self, run_id: str, limit: str, actual: float, maximum: float) -> None:
        reason = str(BudgetExceeded(limit, actual, maximum))
        self.store.fail_budget(run_id, limit, actual, maximum, reason)
        raise BudgetExceeded(limit, actual, maximum)

    def _discard_late_result(
        self, run_id: str, task_id: str, attempt_id: str, error: str | None = None,
        *, record_event: bool = True,
    ) -> None:
        run = self.store.get_run(run_id)
        if run is not None:
            output_artifact_ids = []
            prepared_paths = []
            for event in self.store.list_events(run_id):
                if (event.get("type") not in {"algorithm_outputs_promoted", "worker_delivery_output_prepared"}
                        or event.get("task_id") != task_id):
                    continue
                payload = event.get("payload")
                if not isinstance(payload, dict) or payload.get("attempt_id") != attempt_id:
                    continue
                if event["type"] == "worker_delivery_output_prepared":
                    if isinstance(payload.get("artifact_id"), str) and isinstance(payload.get("path"), str):
                        output_artifact_ids.append(payload["artifact_id"])
                        prepared_paths.append(payload["path"])
                    continue
                outputs = payload.get("outputs")
                if isinstance(outputs, list):
                    output_artifact_ids.extend(
                        item["artifact_id"] for item in outputs
                        if isinstance(item, dict) and isinstance(item.get("artifact_id"), str)
                    )
            discarded_paths = self.store.discard_attempt_outputs(
                run_id, task_id, attempt_id, tuple(dict.fromkeys(output_artifact_ids))
            )
            for relative_path in prepared_paths:
                try:
                    target = self._confined_output_target(Path(run.workspace), relative_path)
                    target.unlink(missing_ok=True)
                    target.with_name(f".{target.name}.tmp").unlink(missing_ok=True)
                except (OSError, ValueError):
                    pass
            for relative_path in discarded_paths:
                path = (Path(run.workspace) / relative_path).resolve(strict=False)
                try:
                    path.relative_to(Path(run.workspace).resolve())
                    path.unlink(missing_ok=True)
                except (OSError, ValueError):
                    # The ledger is authoritative; a file disappearing concurrently is harmless.
                    pass
        if not record_event:
            return
        self.store.append_event(
            run_id,
            "task_result_discarded",
            {
                "attempt_id": attempt_id,
                "reason": "run_cancelled_or_task_no_longer_running",
                "error": error,
            },
            task_id=task_id,
        )

    def _build_task_prompt(self, run: Run, task: Any) -> str:
        dependencies = self.store.dependency_artifacts(task.id)
        staged_inputs = [
            item["path"]
            for item in self.store.list_artifacts(run.id)
            if item["kind"] == "input_data" and isinstance(item.get("path"), str)
        ][:MAX_INPUT_FILES]
        answer_path = task.input_answer_path
        answer_content = ""
        if answer_path:
            candidate = (Path(run.workspace) / answer_path).resolve(strict=False)
            try:
                candidate.relative_to(Path(run.workspace).resolve())
                if candidate.is_file() and candidate.stat().st_size <= 20_000:
                    answer_content = candidate.read_text(encoding="utf-8")[:8_000]
            except (OSError, UnicodeDecodeError, ValueError):
                answer_content = "<answer artifact could not be read>"
        output_specs = self._task_output_specs(run, task)
        input_instructions: list[str] = []
        if staged_inputs:
            input_instructions = [
                "Staged input data (read-only copies are available at these task-relative paths):"
            ]
            input_instructions.extend(f"- {path}" for path in staged_inputs)
        output_instructions: list[str] = []
        if output_specs:
            output_instructions = [
                "Declared algorithm data outputs (write these files; a prose answer alone is not sufficient):"
            ]
            output_instructions.extend(
                "- {path} | format={format} | fields={fields} | {required}".format(
                    path=output.path,
                    format=output.format,
                    fields=", ".join(output.fields) if output.fields else "untyped",
                    required="required" if output.required else "optional",
                )
                for output in output_specs
            )
        role_evidence_specs = self._role_evidence_specs(task.acceptance)
        envelope_instructions: list[str] = []
        if output_specs or role_evidence_specs:
            envelope_instructions = [
                "If this runtime cannot call file tools, you may return one strict JSON artifact envelope instead:",
                '{"text":"...", "artifacts":[{"path":"relative/path", "content":"UTF-8 text"}]}.',
                "Use only the declared relative paths; the controller will validate each file before delivery.",
            ]
            if role_evidence_specs:
                envelope_instructions.append(
                    "Declared role hand-off paths: "
                    + ", ".join(path for _, path in role_evidence_specs)
                    + "."
                )
        if not dependencies and not answer_content:
            sections = [*input_instructions, *output_instructions, *envelope_instructions, task.prompt]
        else:
            sections = [*input_instructions, *output_instructions, *envelope_instructions, task.prompt]
            if answer_content:
                sections.extend(
                    [
                        "",
                        "User/parent-Agent answer (from a verified run-relative artifact):",
                        answer_content,
                    ]
                )
            if dependencies:
                sections.extend(["", "Verified dependency artifacts (run-relative paths):"])
                for artifact in dependencies:
                    relative = str(artifact["path"])
                    sections.append(f"- task {artifact['task_id']}: {relative}")
                    artifact_path = Path(run.workspace) / relative
                    if artifact_path.is_file() and artifact_path.stat().st_size <= 20_000:
                        try:
                            content = artifact_path.read_text(encoding="utf-8")
                        except UnicodeDecodeError:
                            content = "<binary artifact; read it from the path>"
                        sections.extend(["  preview:", content[:8_000]])
        feedback = self._retry_feedback(run.id, task)
        if feedback:
            sections.extend(["", feedback])
        return "\n".join(sections)

    def _retry_feedback(self, run_id: str, task: Any) -> str | None:
        """Render bounded, task-scoped evidence for an attempt after the first one."""
        # The scheduler passes the task snapshot captured immediately before the next claim.
        # Therefore ``attempts == 1`` means the prompt belongs to attempt two and must include
        # feedback from attempt one.
        if getattr(task, "attempts", 0) < 1:
            return None
        latest: dict[str, Any] | None = None
        try:
            events = self.store.list_events(run_id)
        except Exception:  # noqa: BLE001 - legacy/corrupt evidence must not block retry
            events = []
        for event in reversed(events):
            if event.get("task_id") != task.id or event.get("type") != "task_evaluated":
                continue
            payload = event.get("payload")
            if isinstance(payload, dict) and payload.get("passed") is False:
                latest = payload
                break
        previous_attempt = int(task.attempts)
        if latest is None:
            return (
                f"Retry feedback from the previous attempt (attempt {previous_attempt}):\n"
                "- source: runtime_failure\n"
                "- status: failed\n"
                "- instruction: The previous attempt did not complete successfully. Inspect the "
                "task workspace, retry the requested work, and return a complete result."
            )
        rules = self._failed_acceptance_rules(latest.get("details"))
        evidence = ["evaluation_failed"]
        if rules:
            evidence.append("acceptance_check_failed")
            evidence.extend(f"acceptance_rule:{rule}" for rule in rules)
        evidence = list(dict.fromkeys(evidence))[: self._MAX_RETRY_FEEDBACK_VALUES]
        lines = [
            f"Retry feedback from the previous verified attempt (attempt {previous_attempt}):",
            "- source: evaluation",
            "- status: failed",
            f"- evidence: {', '.join(evidence)}",
            (
                "- instruction: Correct the verified failure and produce a complete result. Do not "
                "claim success until the required artifacts satisfy the task acceptance checks."
            ),
        ]
        rendered = "\n".join(lines)
        return rendered[: self._MAX_RETRY_FEEDBACK_BYTES]

    @classmethod
    def _failed_acceptance_rules(cls, details: object) -> tuple[str, ...]:
        found: list[str] = []

        def visit(value: object) -> None:
            if isinstance(value, dict):
                rule = value.get("rule")
                if rule in cls._RETRY_FEEDBACK_RULES and value.get("passed") is False:
                    assert isinstance(rule, str)
                    if rule not in found:
                        found.append(rule)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        if isinstance(details, dict):
            visit(details.get("acceptance"))
            visit(details.get("outputs"))
        return tuple(found[: cls._MAX_RETRY_FEEDBACK_VALUES])

    @staticmethod
    def _runtime_artifact_path(task_root: Path, relative_path: str) -> Path:
        candidate = (task_root / relative_path).resolve(strict=False)
        try:
            candidate.relative_to(task_root.resolve())
        except ValueError as exc:
            raise ArtifactError(f"runtime artifact escapes task workspace: {relative_path}") from exc
        return candidate

    @staticmethod
    def _terminate_process_group(pid: int | None, pgid: int | None) -> None:
        if not pid or pid <= 1 or pid == os.getpid():
            return
        try:
            current_pgid = os.getpgrp()
        except OSError:
            current_pgid = None
        if pgid and pgid > 1 and pgid != current_pgid:
            try:
                os.killpg(pgid, signal.SIGTERM)
                return
            except (ProcessLookupError, PermissionError):
                pass
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def _can_retry(self, attempts_after_current: int) -> bool:
        return attempts_after_current < self.config.max_retries

    @staticmethod
    def _sanitize_error(error: Exception) -> str:
        if isinstance(error, RuntimeExecutionError):
            return str(error)[-2000:]
        return f"{type(error).__name__}: {str(error)[-1800:]}"
