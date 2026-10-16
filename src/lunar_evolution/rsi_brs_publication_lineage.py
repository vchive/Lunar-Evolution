"""Private original-BRS checkpoint primitives, without an online publication facade.

The first before/prepared pair and adjacent success staged/terminal observations
are supported. Rejection, recovery, successor and online owner composition remain
separate. This module never dispatches, evaluates, stages or publishes artifacts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, replace
from pathlib import Path
from threading import get_ident
from typing import Any

from . import _benchmark_files as _files
from . import producer_bundle_recovery as recovery
from . import rsi_publication_lineage as lineage
from .algorithm import ALGORITHM_FAMILY_REPERTOIRES as _ORIGINAL_FAMILY_REPERTOIRES
from .candidate_evaluation_spec import canonical_json
from .producer_bundle_admission import parse_producer_bundle_admission_plan
from .producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_BATCHES,
    LineageSnapshotPin,
    ProducerLineageBeforeIntent,
    ProducerLineageStagedTransition,
    ProducerLineageTerminal,
    capture_lineage_snapshot_pin,
    verify_persisted_lineage_snapshot,
)
from .producer_bundle_publication import parse_producer_bundle_publication_journal
from .rsi_budget import RSIRunBudget
from .rsi_gateway import SolverRequest
from .rsi_identity import component_fingerprint
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_plan import NativeRSIExecutionPlan

_FIELD = "producer_publication_lineage"
_PROTOCOL = "lunar-rsi-brs-lineage-checkpoint-v1"
_RUN_POLICY_FIELD = "producer_brs_checkpoint_policy"


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_brs_publication_lineage_" + reason)


def _native_shape(value: object, *, depth: int = 0) -> None:
    """Reject nested DTO shadows before any original or live serializer call."""
    from .algorithm import (
        AlgorithmProblemContract,
        ConstraintSpec,
        EvolutionSpec,
        InputSpec,
        MetricSpec,
        ObjectiveSpec,
        OutputSpec,
        SourceCheckSpec,
    )
    from .evolution import CandidateIntegrityAuthority, EvolutionConfig
    from .rsi_python_admission import validate_rsi_python_admission_shapes

    if depth > 48:
        _fail("native_strategy_shape_invalid")
    kind = type(value)
    if kind in {AlgorithmProblemContract, ConstraintSpec, EvolutionSpec, InputSpec,
                MetricSpec, ObjectiveSpec, OutputSpec, SourceCheckSpec,
                CandidateIntegrityAuthority, EvolutionConfig}:
        # Read the trusted class declaration: fields(instance) itself can be shadowed.
        declared = fields(kind)
        attributes = object.__getattribute__(value, "__dict__")
        if (type(attributes) is not dict or any(type(key) is not str for key in attributes)
                or set(attributes) != {item.name for item in declared}):
            _fail("native_strategy_shape_invalid")
        for item in declared:
            _native_shape(object.__getattribute__(value, item.name), depth=depth + 1)
    elif kind in {tuple, list, dict}:
        if kind is dict:
            if any(type(key) is not str for key in value):
                _fail("native_strategy_shape_invalid")
            items = value.values()
        else:
            items = value
        for item in items:
            _native_shape(item, depth=depth + 1)
    else:
        validate_rsi_python_admission_shapes(value)


def _native_snapshot(config: object, authority: object, contract: object) -> bytes:
    from .algorithm import AlgorithmProblemContract
    from .evolution import CandidateIntegrityAuthority, EvolutionConfig

    if (type(config) is not EvolutionConfig or type(authority) is not CandidateIntegrityAuthority
            or type(contract) is not AlgorithmProblemContract):
        _fail("native_strategy_invalid")
    _native_shape((config, authority, contract))
    return lineage._raw({"config": EvolutionConfig.to_dict(config),
                         "authority": CandidateIntegrityAuthority.to_dict(authority),
                         "contract_sha256": AlgorithmProblemContract.digest(contract)})


def _family_repertoires() -> dict[str, list[str]]:
    from . import evolution

    value = evolution.ALGORITHM_FAMILY_REPERTOIRES
    # The retained module constant is a trusted mapping proxy over primitive data.
    # Do not inspect a caller-substituted proxy which could wrap callback mapping.
    if (value is not _ORIGINAL_FAMILY_REPERTOIRES or any(type(key) is not str or type(item) is not tuple
            or any(type(family) is not str for family in item) for key, item in value.items())):
        _fail("population_repertoires_invalid")
    return {key: list(item) for key, item in value.items()}


def _policy_required(controller: Any, *, mode: object, plan: object) -> bool:
    """Select non-authorizing metadata without observing source/configuration hooks."""
    from .python_producer_binding_store import PythonProducerBindingSidecar

    return (type(mode) is str and mode == "brs" and type(plan) is dict
            and plan.get("mode") == "brs" and type(plan.get("max_workers")) is int
            and plan["max_workers"] == 1
            and type(controller.producer_sidecar) is PythonProducerBindingSidecar)


def _run_policy(controller: Any, *, mode: object = None, plan: object = None) -> dict[str, Any] | None:
    """Pin only new sidecar-bound, single-worker BRS runs; never enable execution."""
    return _policy() if _policy_required(controller, mode=mode, plan=plan) else None


def _validate_persisted_policy(
    controller: Any, *, run_id: str, state: Any = None, expected: dict[str, Any] | None = None,
) -> None:
    """Compare original JSON pins only; source/configuration hooks belong outside locks.

    Every retained record and checkpoint must carry the original policy. A later
    state cannot supply a missing original pin, and this reader never migrates it.
    """
    with controller.ledger.read_only_observations():
        history = controller.ledger.history(run_id)
        checkpoints = controller.ledger.controller_checkpoint_history(run_id)
    if not history:
        _fail("persisted_policy_original_missing")
    original = history[0].payload
    required = _policy_required(controller, mode=original.get("mode"), plan=original.get("plan"))
    policy = original.get(_RUN_POLICY_FIELD)
    snapshots = [record.payload for record in history] + [payload for _head, payload in checkpoints]
    if state is not None:
        snapshots.append(state)
    if not required:
        if expected is not None or any(_RUN_POLICY_FIELD in snapshot for snapshot in snapshots):
            _fail("persisted_policy_scope_invalid")
        return
    if (type(policy) is not dict or policy.get("protocol") != _PROTOCOL
            or policy.get("mode") != "brs" or type(policy.get("max_workers")) is not int
            or policy["max_workers"] != 1 or policy.get("online_publication") is not False
            or policy.get("production_admission") is not False):
        _fail("persisted_policy_original_invalid")
    if expected is not None and policy != expected:
        _fail("persisted_policy_drift")
    for snapshot in snapshots:
        if (snapshot.get(_RUN_POLICY_FIELD) != policy
                or not _policy_required(controller, mode=snapshot.get("mode"), plan=snapshot.get("plan"))):
            _fail("persisted_policy_drift")
    for record in history:
        fingerprints = record.payload.get("fingerprints", {})
        fingerprint = fingerprints.get("run_fingerprint", {}) if type(fingerprints) is dict else {}
        settings = fingerprint.get("solver_settings", {}) if type(fingerprint) is dict else {}
        if type(settings) is not dict or settings.get(_RUN_POLICY_FIELD) != policy:
            _fail("persisted_policy_fingerprint_invalid")


def _policy() -> dict[str, Any]:
    """Original-run and constructor BRS identity pin, never a dispatch permission."""
    from . import evolution
    from . import rsi_python_scheduler_inputs as scheduler_inputs
    from .algorithm import (
        AlgorithmProblemContract,
        ConstraintSpec,
        EvolutionSpec,
        InputSpec,
        MetricSpec,
        ObjectiveSpec,
        OutputSpec,
        SourceCheckSpec,
    )
    from .candidate_bundle import CandidateSourceBundle, parse_candidate_source_bundle
    from .evolution import (
        Candidate,
        CandidateArchive,
        CandidateIntegrityAuthority,
        EvolutionConfig,
        PopulationStrategy,
    )
    from .producer_bundle_transaction import _records_from_archive
    from .rsi_python_scheduler_inputs import _context

    return {
        "protocol": _PROTOCOL, "mode": "brs", "max_workers": 1,
        "production_admission": False, "online_publication": False,
        "max_batches": MAX_LINEAGE_BATCHES,
        "max_checkpoint_bytes": lineage._MAX_CHECKPOINT_BYTES,
        "max_aggregate_snapshot_bytes": MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
        "dependencies": {
            "policy": component_fingerprint(_policy),
            "failure": component_fingerprint(_fail),
            "selection": component_fingerprint(_policy_required),
            "run_policy": component_fingerprint(_run_policy),
            "persisted_policy": component_fingerprint(_validate_persisted_policy),
            "native_shape": component_fingerprint(_native_shape),
            "native_snapshot": component_fingerprint(_native_snapshot),
            "family_repertoires": {"reader": component_fingerprint(_family_repertoires),
                                   "value": _family_repertoires()},
            "module_sources": {name: hashlib.sha256(_files.read_regular_file(Path(__file__).parent / name, 1024 * 1024)).hexdigest()
                               for name in ("rsi_brs_publication_lineage.py", "rsi_publication_lineage.py",
                                            "rsi_controller.py", "rsi_store.py", "producer_bundle_lineage.py",
                                            "producer_bundle_admission.py", "producer_bundle_publication.py",
                                            "rsi_python_admission.py", "rsi_python_brs_handoff.py",
                                            "rsi_producer_staging_capsule.py", "producer_bundle_recovery.py",
                                            "producer_bundle_staging.py", "evolution.py", "algorithm.py",
                                            "candidate_bundle.py", "producer_bundle_transaction.py",
                                            "rsi_python_scheduler_inputs.py")},
            "owner": component_fingerprint(_BRSLineageCheckpointOwner, config={}),
            "methods": {name: component_fingerprint(getattr(_BRSLineageCheckpointOwner, name)) for name in (
                "__init__", "_identity", "_check_owner", "_running", "_before_entry", "_write",
                "checkpoint_before", "acknowledge_prepared", "_accept_prepared_reference",
                "_native_strategy", "_strategy_identity", "_history", "_success_entry",
                "_initial_window", "_candidate_materials", "_verify_staged_projection",
                "checkpoint_staged", "checkpoint_terminal",
            )},
            "readers": {name: component_fingerprint(getattr(lineage._LineageEvidenceReader, name)) for name in (
                "_is_v2", "_validate_entry_shape", "_validate_source_pin_maps", "_verify_descriptor", "_snapshot_bytes",
                "_verify_terminal_entry", "_verify_transition_projection",
            )},
            "checkpoint_delta": component_fingerprint(lineage._publication_lineage_checkpoint_delta),
            "checkpoint_readback": component_fingerprint(lineage._validate_publication_lineage_checkpoint_readback),
            "root_pin": component_fingerprint(lineage._root_pin),
            "source_pin_check": component_fingerprint(lineage.RSIPublicationLineage._verify_before_source_pins),
            "after_source_pin_check": component_fingerprint(lineage.RSIPublicationLineage._verify_after_source_pins),
            "marker_absence": component_fingerprint(lineage._require_marker_absent),
            "native_context_reader": component_fingerprint(_context),
            "native_context_helpers": {name: component_fingerprint(getattr(scheduler_inputs, name)) for name in (
                "_checkpoint", "_sidecar", "_native", "_projection", "_shape", "_broker", "_request_memory", "_path",
            )},
            "population_projection": {name: component_fingerprint(getattr(PopulationStrategy, name)) for name in (
                "_reconstruct_population_projection", "_producer_admission_events", "_apply_producer_admissions",
                "_trim", "_capacity", "_candidates", "_rank", "_family_elites", "_candidate_family",
            )},
            "population_serializers": {
                "config": component_fingerprint(EvolutionConfig.to_dict),
                "authority": component_fingerprint(CandidateIntegrityAuthority.to_dict),
                "novelty": component_fingerprint(evolution._novelty),
                "tokens": component_fingerprint(evolution._tokens),
                "archive_reader": component_fingerprint(_records_from_archive),
                "seed_predicate": component_fingerprint(CandidateArchive._is_seed_candidate),
                "candidate_read": component_fingerprint(Candidate.from_dict, config={}),
                "candidate_write": component_fingerprint(Candidate.to_dict),
                "bundle_read": component_fingerprint(parse_candidate_source_bundle),
                "bundle_digest": component_fingerprint(CandidateSourceBundle.digest),
                "contract_digest": component_fingerprint(AlgorithmProblemContract.digest),
                "contract_canonical": component_fingerprint(AlgorithmProblemContract.canonical_json),
                "contract_serializers": {kind.__name__: component_fingerprint(kind.to_dict) for kind in (
                    AlgorithmProblemContract, ConstraintSpec, EvolutionSpec, InputSpec,
                    MetricSpec, ObjectiveSpec, OutputSpec, SourceCheckSpec,
                )},
            },
            "recovery": {name: component_fingerprint(getattr(recovery, name)) for name in (
                "_batch", "_read_json", "_read_journal", "_check_preflight", "_manifest",
                "_verify_python_handoff", "_verify_manifest_files", "_verify_terminal_batch_evidence", "_marker", "_path",
            )},
            "shape_check": component_fingerprint(lineage._publication_shapes),
            "admission_parser": component_fingerprint(parse_producer_bundle_admission_plan),
            "journal_parser": component_fingerprint(parse_producer_bundle_publication_journal),
            "capture_pin": component_fingerprint(capture_lineage_snapshot_pin),
            "verify_pin": component_fingerprint(verify_persisted_lineage_snapshot),
            "shared_retained_bytes": component_fingerprint(lineage.RSIPublicationLineage._retained_bytes),
        },
    }


class _BRSLineageCheckpointOwner(lineage._LineageEvidenceReader):
    """Exact original BRS owner for bounded first-batch success checkpoints.

    Caller-owned wire is checked against genuine descriptor/snapshot/source files
    and the original request/claim/plan. No arbitrary lineage delta, DRS context,
    completed result, rejection event or latest-head refresh is accepted.
    Instances are ephemeral and cannot be reconstructed from retained evidence.
    """

    __slots__ = (
        "_association",
        "_before_bytes",
        "_budget_bytes",
        "_channel",
        "_claim",
        "_controller",
        "_episode_head",
        "_gateway",
        "_handoff",
        "_handoff_bytes",
        "_head",
        "_ledger",
        "_memory",
        "_native",
        "_native_config",
        "_native_inputs",
        "_payload",
        "_phase",
        "_plan",
        "_poisoned",
        "_policy_bytes",
        "_prepared",
        "_provided_memory",
        "_provided_plan",
        "_provided_request",
        "_request",
        "_run_head",
        "_run_id",
        "_selected_context",
        "_selected_context_bytes",
        "_sidecar",
        "_state",
        "_strategy",
        "_strategy_archive",
        "_strategy_authority",
        "_strategy_bytes",
        "_strategy_config",
        "_strategy_context",
        "_strategy_contract",
        "_thread",
        "_wave",
        "_workspace",
    )

    def __init__(self, controller: Any, wave: Any, *, request: SolverRequest,
                 memory: MemorySnapshot, native_plan: NativeRSIExecutionPlan) -> None:
        from .rsi_controller import RSILearningController, _PythonAdmissionBRSWave
        from .rsi_python_admission import validate_rsi_python_admission_shapes
        from .rsi_python_brs_handoff import BRSChildHandoffContext, BRSSelectedChildHandoff
        from .rsi_python_scheduler_inputs import _request_memory
        from .rsi_store import RSILedger

        if (type(self) is not _BRSLineageCheckpointOwner or type(controller) is not RSILearningController
                or type(wave) is not _PythonAdmissionBRSWave or type(controller.ledger) is not RSILedger):
            _fail("owner_invalid")
        controller._python_admission_assert_brs_wave(wave, owner=True)
        handoff, context = wave.selected_handoff, wave.selected_context
        if type(handoff) is not BRSSelectedChildHandoff or type(context) is not BRSChildHandoffContext:
            _fail("selection_required")
        controller._python_admission_selected_brs_identity(wave, handoff)
        parsed_request, parsed_memory = _request_memory(request, memory)
        validate_rsi_python_admission_shapes(native_plan, dto_types=(NativeRSIExecutionPlan, SolverRequest))
        if type(native_plan) is not NativeRSIExecutionPlan:
            _fail("plan_invalid")
        plan = NativeRSIExecutionPlan.from_dict(NativeRSIExecutionPlan.to_dict(native_plan))
        if (plan.request != parsed_request or plan.memory_snapshot_sha256 != parsed_memory.digest()
                or parsed_request.digest() != handoff.request_sha256 or plan.run_id != wave.run_id
                or parsed_memory.digest() != handoff.root_snapshot_sha256 or handoff.ordinal != 0):
            _fail("inputs_invalid")
        previous = getattr(controller._python_admission_brs_local, "lineage_checkpoint_owner", None)
        if type(previous) is _BRSLineageCheckpointOwner and previous._wave is wave:
            _fail("owner_already_created")
        self._controller, self._wave, self._state = controller, wave, wave.state
        self._ledger, self._gateway = controller.ledger, controller.gateway
        self._workspace, self._sidecar, self._thread = wave.workspace, wave.sidecar, get_ident()
        self._channel, self._handoff, self._selected_context = wave.channel, handoff, context
        self._budget_bytes = controller._python_admission_flow_payload(wave.budget_state)
        self._handoff_bytes = BRSSelectedChildHandoff.canonical_bytes.fget(handoff)
        self._selected_context_bytes = canonical_json(BRSChildHandoffContext.to_dict(context))
        self._provided_request, self._provided_memory, self._provided_plan = request, memory, native_plan
        self._request, self._memory, self._plan = parsed_request, parsed_memory, plan
        self._run_id, self._head, self._payload = plan.run_id, wave.checkpoint_sha256, wave.payload
        self._policy_bytes = lineage._raw(_policy())
        with self._ledger.read_only_observations():
            original = self._ledger.history(self._run_id)[0]
            run = self._ledger.get_run(self._run_id)
            claim = self._ledger.inspect_native_episode_claim(parsed_request, plan_sha256=plan.plan_sha256)
            episode = self._ledger.get_episode(parsed_request.episode_id)
            result = self._ledger.episode_result(parsed_request.episode_id)
        if (run is None or run.state != "running" or episode is None or episode.state != "running"
                or claim is None or claim.status != "started" or result is not None
                or episode.request_sha256 != parsed_request.digest()):
            _fail("running_claim_required")
        self._run_head, self._claim, self._episode_head = run.record_sha256, claim, episode.record_sha256
        self._association = {
            "protocol": _PROTOCOL, "run_id": self._run_id, "workspace": lineage._root_pin(self._workspace),
            "run_request_sha256": original.request_sha256,
            "root_proof_sha256": lineage._sha(lineage._raw(original.payload.get("producer_checkpoint_binding"))),
            "policy_sha256": lineage._sha(self._policy_bytes), "max_batches": MAX_LINEAGE_BATCHES,
        }
        config = getattr(self._gateway, "producer_config", None)
        self._native_config = config
        self._native_inputs = self._native = self._strategy = None
        self._strategy_context = self._strategy_config = self._strategy_authority = None
        self._strategy_archive = self._strategy_contract = None
        self._strategy_bytes = None
        if config is not None:
            from .evolution import (
                CandidateIntegrityAuthority,
                EvolutionConfig,
                EvolutionContext,
                PopulationStrategy,
            )
            from .rsi_native_scheduler import NativeRSISchedulerContext
            from .rsi_producer_gateway import PythonProducerRSIExecutionConfig
            from .rsi_python_scheduler_inputs import PythonRSISchedulerInputContext

            if (type(config) is not PythonProducerRSIExecutionConfig or config.ledger is not self._ledger
                    or type(config.inputs) is not PythonRSISchedulerInputContext
                    or type(config.inputs.native_context) is not NativeRSISchedulerContext
                    or type(config.inputs.native_context.strategy) is not PopulationStrategy):
                _fail("native_strategy_invalid")
            self._native_inputs, self._native = config.inputs, config.inputs.native_context
            self._strategy = self._native.strategy
            self._strategy_context, self._strategy_config = self._strategy.context, self._strategy.config
            self._strategy_authority = self._strategy.integrity_authority
            if (type(self._strategy_context) is not EvolutionContext
                    or type(self._strategy_config) is not EvolutionConfig
                    or type(self._strategy_authority) is not CandidateIntegrityAuthority):
                _fail("native_strategy_invalid")
            self._strategy_archive, self._strategy_contract = self._strategy.archive, self._strategy_context.contract
            self._strategy_bytes = _native_snapshot(
                self._strategy_config, self._strategy_authority, self._strategy_contract,
            )
        self._phase, self._poisoned, self._prepared, self._before_bytes = "new", False, None, None
        self._check_owner(registered=False)
        if self._state.get(_FIELD) is not None:
            _fail("fresh_lineage_required")
        controller._python_admission_brs_local.lineage_checkpoint_owner = self

    def _identity(self, *, captured: bool = True, registered: bool = True) -> None:
        from .rsi_controller import RSILearningController, _PythonAdmissionBRSWave
        from .rsi_python_admission import validate_rsi_python_admission_shapes
        from .rsi_python_brs_handoff import BRSChildHandoffContext, BRSSelectedChildHandoff
        from .rsi_python_scheduler_inputs import _request_memory

        controller, wave = self._controller, self._wave
        if (type(self) is not _BRSLineageCheckpointOwner or self._poisoned
                or type(controller) is not RSILearningController or type(wave) is not _PythonAdmissionBRSWave
                or type(wave.run_id) is not str or wave.run_id != self._run_id
                or type(wave.owner_thread) is not int or wave.owner_thread != self._thread
                or type(wave.checkpoint_sha256) is not str or type(wave.payload) is not bytes
                or get_ident() != self._thread or controller.ledger is not self._ledger
                or controller.gateway is not self._gateway or wave.state is not self._state
                or controller.producer_workspace is not self._workspace or controller.producer_sidecar is not self._sidecar
                or wave.channel is not self._channel or wave.selected_handoff is not self._handoff
                or wave.selected_context is not self._selected_context or wave.selected_worker_started is not True
                or wave.selected_return is not None or wave.selected_settlement_started is not False
                or (registered and getattr(controller._python_admission_brs_local, "lineage_checkpoint_owner", None) is not self)):
            _fail("owner_drift")
        controller._python_admission_assert_brs_wave(wave, owner=True)
        controller._python_admission_selected_brs_identity(wave, self._handoff)
        if (BRSSelectedChildHandoff.canonical_bytes.fget(self._handoff) != self._handoff_bytes
                or canonical_json(BRSChildHandoffContext.to_dict(self._selected_context)) != self._selected_context_bytes
                or lineage._root_pin(self._workspace) != self._association["workspace"]
                or self._state.get("plan", {}).get("max_workers") != 1
                or self._state.get("root_snapshot") != self._memory.to_dict()
                or self._state.get("intents", {}).get(self._request.episode_id, {}).get("request") != self._request.to_dict()
                or self._request.episode_id in self._state.get("executions", {})
                or self._controller._python_admission_flow_payload(wave.budget_state) != self._budget_bytes
                or self._controller._python_admission_flow_payload(self._state["budget_state"]) != self._budget_bytes
                or (captured and (wave.checkpoint_sha256 != self._head or wave.payload != self._payload))):
            _fail("checkpoint_drift")
        if lineage._raw(_policy()) != self._policy_bytes:
            _fail("policy_drift")
        self._strategy_identity()
        _validate_persisted_policy(
            controller, run_id=self._run_id, state=self._state, expected=json.loads(self._policy_bytes),
        )
        request, memory = _request_memory(self._provided_request, self._provided_memory)
        validate_rsi_python_admission_shapes(self._provided_plan, dto_types=(NativeRSIExecutionPlan, SolverRequest))
        plan = NativeRSIExecutionPlan.from_dict(NativeRSIExecutionPlan.to_dict(self._provided_plan))
        if request != self._request or memory.to_bytes() != self._memory.to_bytes() or plan != self._plan:
            _fail("inputs_drift")
        binding = self._sidecar.binding
        if ((plan.run_id, plan.journal_id, plan.launch_id, plan.parent_task_id, plan.task_id, plan.intent_sha256,
             plan.attestation_sha256, plan.deadline_unix) !=
                (binding.run_id, binding.intent.journal_id, binding.intent.launch_id, binding.parent_task_id,
                 binding.task_id, binding.intent_sha256, binding.attestation_sha256, binding.deadline_unix)):
            _fail("plan_binding_drift")
        RSIRunBudget.load(self._wave.budget_state).check()
        RSIRunBudget.load(self._state["budget_state"]).check()

    def _running(self) -> None:
        run = self._ledger.get_run(self._run_id)
        episode = self._ledger.get_episode(self._request.episode_id)
        claim = self._ledger.inspect_native_episode_claim(self._request, plan_sha256=self._plan.plan_sha256)
        if (run is None or run.state != "running" or run.record_sha256 != self._run_head
                or episode is None or episode.state != "running" or episode.record_sha256 != self._episode_head
                or episode.request_sha256 != self._request.digest() or claim != self._claim or claim.status != "started"
                or self._ledger.episode_result(self._request.episode_id) is not None):
            _fail("running_claim_drift")
        original = self._ledger.history(self._run_id)[0]
        if (original.request_sha256 != self._association["run_request_sha256"]
                or lineage._sha(lineage._raw(original.payload.get("producer_checkpoint_binding")))
                != self._association["root_proof_sha256"]):
            _fail("root_proof_drift")

    def _check_owner(self, *, captured: bool = True, registered: bool = True) -> dict[str, Any]:
        self._identity(captured=captured, registered=registered)
        # Source/configuration callbacks can wait for another observer. They must
        # finish outside the short observation mutex and any workspace write lock.
        self._controller._python_admission_assert_selected_brs(self._wave, self._handoff)
        self._identity(captured=captured, registered=registered)
        if self._native is not None:
            self._native_strategy()
        with self._ledger.read_only_observations():
            self._running()
            self._controller._python_admission_active_brs_owner(self._wave)
            self._history()
        return self._state

    def _strategy_identity(self) -> None:
        if getattr(self._gateway, "producer_config", None) is not self._native_config:
            _fail("native_strategy_drift")
        if self._native_config is None:
            return
        from .algorithm import AlgorithmProblemContract
        from .evolution import (
            CandidateArchive,
            CandidateIntegrityAuthority,
            EvolutionConfig,
            EvolutionContext,
            PopulationStrategy,
        )
        from .rsi_native_scheduler import NativeRSISchedulerContext
        from .rsi_producer_gateway import PythonProducerRSIExecutionConfig
        from .rsi_python_scheduler_inputs import PythonRSISchedulerInputContext

        if (type(self._native_config) is not PythonProducerRSIExecutionConfig
                or self._native_config.ledger is not self._ledger
                or self._native_config.inputs is not self._native_inputs
                or type(self._native_inputs) is not PythonRSISchedulerInputContext
                or self._native_inputs.native_context is not self._native
                or type(self._native) is not NativeRSISchedulerContext
                or self._native.strategy is not self._strategy
                or type(self._strategy) is not PopulationStrategy
                or self._strategy.context is not self._strategy_context
                or type(self._strategy_context) is not EvolutionContext
                or self._strategy_context.contract is not self._strategy_contract
                or type(self._strategy_contract) is not AlgorithmProblemContract
                or self._strategy.config is not self._strategy_config
                or self._strategy_context.config is not self._strategy_config
                or type(self._strategy_config) is not EvolutionConfig
                or self._strategy.integrity_authority is not self._strategy_authority
                or type(self._strategy_authority) is not CandidateIntegrityAuthority
                or self._strategy.archive is not self._strategy_archive
                or type(self._strategy_archive) is not CandidateArchive
                or type(self._strategy_archive.workspace) is not type(self._workspace)
                or self._strategy_archive.workspace != self._workspace
                or any(callable(item) for item in vars(self._strategy).values())
                or any(name in vars(self._strategy_archive) for name in ("_is_seed_candidate",))
                or type(self._strategy_context.workspace) is not type(self._workspace)
                or self._strategy_context.workspace.expanduser().absolute() != self._workspace
                or type(self._native.workspace) not in {str, type(self._workspace)}
                or Path(self._native.workspace).expanduser().absolute() != self._workspace
                or _native_snapshot(self._strategy_config, self._strategy_authority,
                                    self._strategy_contract) != self._strategy_bytes):
            _fail("native_strategy_drift")

    def _native_strategy(self) -> None:
        self._strategy_identity()
        if self._native is None:
            _fail("native_strategy_required")
        from .rsi_python_scheduler_inputs import _context

        _native, sidecar = _context(self._native_inputs)
        binding = self._sidecar.binding
        authority = self._strategy_authority
        if (sidecar != self._sidecar or self._native.failure_ledger is not self._ledger
                or self._strategy_context.contract.digest() != binding.contract_sha256
                or (authority.contract_sha256, authority.evaluator_kind, authority.evaluator_fingerprint,
                    authority.runner_fingerprint, authority.dependency_sha256, authority.environment_sha256) !=
                (binding.contract_sha256, binding.evaluator_kind, binding.evaluator_fingerprint,
                 binding.intent.runner_fingerprint, binding.dependency_sha256, binding.environment_sha256)):
            _fail("native_strategy_binding_invalid")

    def _history(self, state: dict[str, Any] | None = None) -> None:
        # The DRS history reader requires its public opt-in. Use the same strict
        # single-batch progression with BRS's existing pure capacity accounting;
        # never manufacture that DRS flag in real or synthetic state.
        previous = None
        for _head, snapshot in self._ledger.controller_checkpoint_history(self._run_id):
            wire = snapshot.get(_FIELD)
            if wire is None:
                if previous is not None:
                    _fail("history_drift")
                continue
            if (type(wire) is not dict or set(wire) != {*self._association, "batches", "head", "rejections"}
                    or any(wire[key] != item for key, item in self._association.items())
                    or type(wire["batches"]) is not list or len(wire["batches"]) != 1
                    or wire["rejections"] != []):
                _fail("history_drift")
            entry = wire["batches"][0]
            if type(entry) is not dict or entry.get("state") not in {"before", "staged", "terminal"}:
                _fail("history_drift")
            self._validate_entry_shape(entry)
            lineage.RSIPublicationLineage._retained_bytes(wire, snapshot)
            terminal = entry.get("terminal")
            expected_head = None if terminal is None else {
                "journal_id": entry["journal_id"], "terminal_sha256": terminal["terminal_sha256"],
                "lineage_sha256": terminal["descriptor_sha256"],
            }
            if wire["head"] != expected_head:
                _fail("history_drift")
            if previous is None:
                if entry["state"] != "before" or entry["evidence_pins"] != {}:
                    _fail("history_drift")
            else:
                old = previous["batches"][0]
                phases = ("before", "staged", "terminal")
                if not 0 <= phases.index(entry["state"]) - phases.index(old["state"]) <= 1:
                    _fail("history_drift")
                for key, item in old.items():
                    if key in {"snapshots", "evidence_pins"}:
                        if any(entry[key].get(name) != pin for name, pin in item.items()):
                            _fail("history_drift")
                    elif key != "state" and entry.get(key) != item:
                        _fail("history_drift")
                if (old["state"] == "before" and entry["state"] == "staged"
                        and set(old["evidence_pins"]) != {"journal.prepared.json"}):
                    _fail("history_drift")
            previous = wire
        if (self._state if state is None else state).get(_FIELD) != previous:
            _fail("history_drift")

    def _initial_window(self, archive: bytes, state_bytes: bytes) -> None:
        from .producer_bundle_transaction import _records_from_archive

        state, records = json.loads(state_bytes), _records_from_archive(archive)
        outcome_fields = {"outcome_schema_version", "outcome_start_iteration", "outcome_watermark",
            "outcome_watermark_sha256", "outcome_archive_baseline_sha256", "pending_offspring",
            "failed_offspring_iteration", "failed_offspring_sha256"}
        if (type(state.get("iteration")) is not int or state["iteration"] != 0
                or state.get("status") != "running" or "seed_admission" in state
                or outcome_fields.intersection(state) or state.get("producer_admissions") is not None
                or any(item.iteration != 0 or "seed_handoff" in item.metadata or "producer_bundle" in item.metadata
                       for item in records)):
            _fail("success_initial_window_required")
        # Read-only counterpart of the native initial-window gate. Avoid the
        # archive's mutation/recovery facade while a staged marker may exist.
        for filename in ("seed-commit.json", "offspring-outcomes.jsonl"):
            path = self._workspace / "evolution" / filename
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            if filename == "seed-commit.json" or _files.read_regular_file(path, lineage.MAX_LINEAGE_SNAPSHOT_BYTES).strip():
                _fail("success_initial_window_required")

    def _candidate_materials(self, entry, files, archive_after: bytes, *, staged: bool):
        """Bind archive rows to verified materials and retain exact source bytes."""
        from .candidate_bundle import parse_candidate_source_bundle
        from .evolution import Candidate
        from .producer_bundle_transaction import _records_from_archive

        records = {record.candidate_id: record for record in _records_from_archive(archive_after)}
        overrides = {}
        for cid, material in files.items():
            root = (recovery._path(self._workspace, f"stage/candidates/{cid}", directory=
                                  recovery._batch(self._workspace, self._plan.journal_id)) if staged else
                    recovery._path(self._workspace, f"evolution/candidates/{cid}"))
            descriptors = {}
            for descriptor in material["paths"]:
                name = descriptor["path"]
                prefix = f"stage/candidates/{cid}/"
                name = name.removeprefix(prefix)
                if name in descriptors:
                    _fail("candidate_materials_invalid")
                descriptors[name] = descriptor
            record_names = [name for name in descriptors if name == "record.json" or name.endswith("/record.json")]
            if len(record_names) != 1 or cid not in records:
                _fail("candidate_materials_invalid")
            raw = _files.read_regular_file(recovery._path(self._workspace, record_names[0], directory=root), 64 * 1024)
            record = Candidate.from_dict(json.loads(raw))
            if (lineage._sha(raw) != material["record_sha256"]
                    or record.candidate_id != cid or record.to_dict() != records[cid].to_dict()):
                _fail("archive_material_record_drift")
            live_root = f"evolution/candidates/{cid}/"
            if not record.code_path.startswith(live_root):
                _fail("candidate_materials_invalid")
            if record.bundle_evidence is None:
                paths = (record.code_path[len(live_root):],)
                declarations = None
            else:
                evidence = record.bundle_evidence
                if evidence["source_root"] != live_root[:-1] or not evidence["bundle_path"].startswith(live_root):
                    _fail("candidate_materials_invalid")
                name = evidence["bundle_path"][len(live_root):]
                if name not in descriptors:
                    _fail("candidate_materials_invalid")
                bundle_raw = _files.read_regular_file(recovery._path(self._workspace, name, directory=root), 256 * 1024)
                bundle = parse_candidate_source_bundle(json.loads(bundle_raw))
                planned = next((candidate for candidate in self._prepared.candidates if candidate.candidate_id == cid), None)
                if (lineage._sha(bundle_raw) != descriptors[name]["sha256"]
                        or planned is None or bundle.digest() != evidence["bundle_sha256"]
                        or evidence["bundle_sha256"] != planned.bundle_sha256
                        or bundle.contract_sha256 != self._prepared.contract_sha256
                        or record.code_path != live_root + bundle.entrypoint):
                    _fail("candidate_materials_invalid")
                paths = tuple(item.path for item in bundle.files)
                declarations = {item.path: item for item in bundle.files}
            sources = {}
            for name in paths:
                if name not in descriptors:
                    _fail("candidate_materials_invalid")
                descriptor = descriptors[name]
                content = _files.read_regular_file(recovery._path(self._workspace, name, directory=root), descriptor["size"] + 1)
                if len(content) != descriptor["size"] or lineage._sha(content) != descriptor["sha256"]:
                    _fail("candidate_material_source_drift")
                if declarations is not None and (len(content) != declarations[name].size
                        or lineage._sha(content) != declarations[name].sha256):
                    _fail("candidate_bundle_source_drift")
                sources[name] = content
            overrides[cid] = sources
        if tuple(overrides) != tuple(entry["staged"]["candidate_ids"]):
            _fail("candidate_materials_invalid")
        return overrides

    def _verify_staged_projection(self, entry, raw, source_overrides) -> None:
        """Verify the first transition while new candidate source is still staged."""
        from .evolution import CandidateIntegrityAuthority, EvolutionConfig, PopulationStrategy
        from .producer_bundle_transaction import _records_from_archive

        before, after = raw["archive-before"], raw["archive-after"]
        if not after.startswith(before):
            _fail("archive_prefix_drift")
        before_records, after_records = _records_from_archive(before), _records_from_archive(after)
        ids = tuple(entry["staged"]["candidate_ids"])
        if tuple(item.candidate_id for item in after_records) != (*tuple(item.candidate_id for item in before_records), *ids):
            _fail("archive_additions_drift")
        base, observed = json.loads(raw["state-before"]), json.loads(raw["state-after"])
        if (base.get("config") != EvolutionConfig.to_dict(self._strategy_config)
                or base.get("candidate_integrity_authority") != CandidateIntegrityAuthority.to_dict(self._strategy_authority)
                or base.get("contract_sha256") != self._prepared.contract_sha256):
            _fail("native_configuration_drift")
        events = {"schema_version": "1", "events": [{"after_iteration": 0, "candidate_ids": list(ids)}]}
        active, best, migration, stagnation = PopulationStrategy._reconstruct_population_projection(
            self._strategy, base | {"producer_admissions": events}, after_records, source_overrides=source_overrides,
        )
        expected = base | {
            "schema_version": "1", "strategy": "population", "status": "running", "iteration": 0,
            "contract_sha256": self._prepared.contract_sha256, "config": dict(base["config"]),
            "active_ids": {str(key): item for key, item in active.items()}, "producer_admissions": events,
            "best_candidate_id": best, "rng_seed": base.get("rng_seed", base["config"].get("rng_seed")),
            "last_migration_iteration": migration, "stagnation": stagnation, "error": None,
            "candidate_integrity_schema_version": "1", "candidate_integrity_authority": base["candidate_integrity_authority"],
            "candidate_archive_sha256": lineage._sha(canonical_json(
                [item.to_dict() for item in after_records], maximum=16 * 1024 * 1024,
            )),
        }
        if observed != expected or lineage._sha(raw["state-after"]) != entry["state_projection_sha256"]:
            _fail("state_projection_drift")

    def _success_entry(self, wire: object, *, phase: str) -> dict[str, Any]:
        from .rsi_python_admission import validate_rsi_python_admission_shapes

        validate_rsi_python_admission_shapes(wire)
        self._native_strategy()
        # The shared terminal schema binds its task directly to this episode.
        # Legacy root-task before/prepared evidence cannot mint that association.
        if self._plan.task_id != self._request.episode_id:
            _fail("success_episode_task_required")
        if type(wire) is not dict or phase not in {"staged", "terminal"}:
            _fail("success_invalid")
        detached = json.loads(lineage._raw(wire))
        if (set(detached) != {*self._association, "batches", "head", "rejections"}
                or any(detached[key] != value for key, value in self._association.items())
                or detached["rejections"] != [] or type(detached["batches"]) is not list
                or len(detached["batches"]) != 1):
            _fail("success_invalid")
        entry = detached["batches"][0]
        if type(entry) is not dict or entry.get("state") != phase:
            _fail("success_invalid")
        self._validate_entry_shape(entry)
        old = json.loads(self._payload).get(_FIELD)
        if (type(old) is not dict or (self._phase, phase) not in {
                ("prepared-evidence", "staged"), ("staged", "terminal")
        } or old != self._state.get(_FIELD)):
            _fail("success_unavailable")
        previous = old["batches"][0]
        for key, value in previous.items():
            if key in {"snapshots", "evidence_pins"}:
                if any(entry[key].get(name) != pin for name, pin in value.items()):
                    _fail("success_delta_invalid")
            elif key != "state" and entry.get(key) != value:
                _fail("success_delta_invalid")
        before_wire = json.loads(self._before_bytes)
        before_wire["batches"][0] = {
            key: entry[key] for key in before_wire["batches"][0]
        }
        before_wire["batches"][0].update(
            state="before", snapshots={name: entry["snapshots"][name] for name in ("archive-before", "state-before")},
            evidence_pins={"journal.prepared.json": entry["evidence_pins"]["journal.prepared.json"]},
        )
        self._before_entry(before_wire, live_sources=phase == "staged")
        lineage.RSIPublicationLineage._retained_bytes(detached, self._state)
        transition = self._verify_descriptor(entry, "staged")
        before = ProducerLineageBeforeIntent.from_dict(entry["before"])
        if (type(transition) is not ProducerLineageStagedTransition
                or (transition.run_id, transition.journal_id, transition.ordinal, transition.before_sha256) !=
                (self._run_id, self._plan.journal_id, 0, before.digest())):
            _fail("staged_binding_invalid")
        batch = recovery._batch(self._workspace, self._plan.journal_id)
        staged = recovery._read_journal(batch / "journal.staged.json")
        original = replace(
            staged, state="prepared", publication_phase="preflight", terminal_marker_sha256=None,
            archive_after_sha256=None, state_after_sha256=None, journal_sha256=None,
            candidates=tuple(replace(item, status="planned", execution_receipt_sha256=None,
                                     evaluation_receipt_sha256=None, publication_receipt_sha256=None)
                             for item in staged.candidates),
        )
        if (original != self._prepared or staged.state != "publishing"
                or staged.digest() != transition.journal_sha256
                or staged.population_config_sha256 != lineage._sha(lineage._raw(self._strategy_config.to_dict()))
                or staged.num_islands != self._strategy_config.num_islands):
            _fail("staged_journal_drift")
        preflight = recovery._read_json(batch / "preflight.json", 128 * 1024)
        preflight_sha = recovery._check_preflight(preflight, staged, parse_producer_bundle_admission_plan(entry["admission_plan"]))
        manifest = recovery._read_json(batch / "manifest.json", 256 * 1024)
        manifest_sha, ids, _paths, files = recovery._manifest(manifest, staged, preflight_sha)
        if (manifest.get("status") != "staged" or manifest_sha != transition.manifest_sha256
                or ids != transition.candidate_ids
                or manifest["base_archive_sha256"] != self._prepared.base_archive_sha256
                or manifest["base_state_sha256"] != self._prepared.base_state_sha256
                or manifest["archive_after_sha256"] != transition.archive_after_sha256
                or manifest["state_after_sha256"] != transition.state_after_sha256):
            _fail("staged_manifest_drift")
        if phase == "terminal":
            terminal = ProducerLineageTerminal.from_dict(entry["terminal"])
            if detached["head"] != {
                "journal_id": self._plan.journal_id, "terminal_sha256": terminal.terminal_sha256,
                "lineage_sha256": terminal.digest(),
            }:
                _fail("terminal_head_invalid")
            archive, state_bytes = self._verify_terminal_entry(entry, ordinal=0, previous=None)
            self._initial_window(
                self._snapshot_bytes(self._plan.journal_id, entry["snapshots"]["archive-before"], name="archive-before"),
                self._snapshot_bytes(self._plan.journal_id, entry["snapshots"]["state-before"], name="state-before"),
            )
            self._candidate_materials(entry, files, archive, staged=False)
            lineage._require_marker_absent(self._workspace)
            for name, expected in (("archive", archive), ("state", state_bytes)):
                path = self._workspace / "evolution" / (name + (".jsonl" if name == "archive" else ".json"))
                pin = LineageSnapshotPin.from_dict(entry["head_sources"][name])
                verify_persisted_lineage_snapshot(path, pin)
                if _files.read_regular_file(path, lineage.MAX_LINEAGE_SNAPSHOT_BYTES) != expected:
                    _fail("terminal_head_drift")
                verify_persisted_lineage_snapshot(path, pin)
        else:
            if detached["head"] is not None:
                _fail("staged_head_invalid")
            lineage.RSIPublicationLineage._verify_after_source_pins(self, entry)
            snapshots = entry["snapshots"]
            raw = {name: self._snapshot_bytes(self._plan.journal_id, pin, name=name)
                   for name, pin in snapshots.items()}
            if (lineage._sha(raw["archive-after"]) != transition.archive_after_sha256
                    or lineage._sha(raw["state-after"]) != transition.state_after_sha256):
                _fail("staged_snapshot_drift")
            self._initial_window(raw["archive-before"], raw["state-before"])
            plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
            recovery._verify_python_handoff(batch, staged, plan)
            recovery._verify_manifest_files(self._workspace, batch, files, staged)
            overrides = self._candidate_materials(entry, files, raw["archive-after"], staged=True)
            self._verify_staged_projection(entry, raw, overrides)
            recovery._verify_manifest_files(self._workspace, batch, files, staged)
            recovery._marker(self._workspace, staged)
            lineage.RSIPublicationLineage._verify_before_source_pins(self, entry)
            lineage.RSIPublicationLineage._verify_after_source_pins(self, entry)
        for name, held_pin in entry["evidence_pins"].items():
            verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(held_pin))
        return detached

    def _before_entry(self, wire: object, *, live_sources: bool = True) -> dict[str, Any]:
        from .rsi_python_admission import validate_rsi_python_admission_shapes

        validate_rsi_python_admission_shapes(wire)
        if type(wire) is not dict:
            _fail("before_invalid")
        detached = json.loads(lineage._raw(wire))
        if (set(detached) != {*self._association, "batches", "head", "rejections"}
                or any(detached[key] != value for key, value in self._association.items())
                or detached["head"] is not None or detached["rejections"] != []
                or type(detached["batches"]) is not list or len(detached["batches"]) != 1):
            _fail("before_invalid")
        entry = detached["batches"][0]
        if type(entry) is not dict or entry.get("state") != "before":
            _fail("before_invalid")
        self._validate_entry_shape(entry)
        before = ProducerLineageBeforeIntent.from_dict(entry["before"])
        plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
        journal = parse_producer_bundle_publication_journal(entry["prepared_journal"])
        if ((entry["journal_id"], entry["ordinal"], entry["episode_id"], entry["request_sha256"],
             entry["memory_snapshot_sha256"], entry["native_plan_sha256"]) !=
                (self._plan.journal_id, 0, self._request.episode_id, self._request.digest(),
                 self._memory.digest(), self._plan.plan_sha256)
                or (before.run_id, before.journal_id, before.ordinal, before.predecessor_terminal_sha256,
                    before.predecessor_lineage_sha256) != (self._run_id, self._plan.journal_id, 0, None, None)
                or journal.state != "prepared" or journal.admission_sha256 != plan.digest()
                or (journal.run_id, journal.journal_id, journal.parent_task_id, journal.task_id) !=
                (self._run_id, self._plan.journal_id, self._plan.parent_task_id, self._plan.task_id)
                or before.archive.to_dict() != entry["snapshots"]["archive-before"]
                or before.state.to_dict() != entry["snapshots"]["state-before"]
                or before.archive.sha256 != journal.base_archive_sha256 or before.state.sha256 != journal.base_state_sha256):
            _fail("before_binding_invalid")
        binding = self._sidecar.binding
        authority = (binding.contract_sha256, self._plan.evaluator_kind, binding.evaluator_fingerprint,
                     binding.intent.runner_fingerprint, binding.dependency_sha256, binding.environment_sha256)
        if ((plan.contract_sha256, plan.evaluator_kind, plan.evaluator_fingerprint, plan.runner_fingerprint,
             plan.dependency_sha256, plan.environment_sha256) != authority
                or (journal.contract_sha256, journal.evaluator_kind, journal.evaluator_fingerprint,
                    journal.runner_fingerprint, journal.dependency_sha256, journal.environment_sha256) != authority
                or tuple((candidate.bundle_id, candidate.bundle_sha256) for candidate in journal.candidates) !=
                tuple((item.bundle_id, item.bundle_sha256) for item in plan.bundles)):
            _fail("before_authority_invalid")
        # Preserve the common ready-capsule + lineage snapshot budget before
        # observing retained files. This BRS protocol uses the pure V1 accounting
        # branch; it neither installs nor impersonates a DRS publication flag.
        lineage.RSIPublicationLineage._retained_bytes(detached, self._state)
        if self._verify_descriptor(entry, "before") != before:
            _fail("before_descriptor_drift")
        for name in ("archive-before", "state-before"):
            self._snapshot_bytes(entry["journal_id"], entry["snapshots"][name], name=name)
        if live_sources:
            lineage.RSIPublicationLineage._verify_before_source_pins(self, entry)
        if entry["evidence_pins"]:
            path = self._workspace / "evolution/producer-batches" / self._plan.journal_id / "journal.prepared.json"
            pin = LineageSnapshotPin.from_dict(entry["evidence_pins"]["journal.prepared.json"])
            verify_persisted_lineage_snapshot(path, pin)
            raw = _files.read_regular_file(path, lineage._MAX_CHECKPOINT_BYTES)
            if parse_producer_bundle_publication_journal(json.loads(raw)) != journal:
                _fail("prepared_journal_drift")
            verify_persisted_lineage_snapshot(path, pin)
        return detached

    def _write(self, wire: dict[str, Any]) -> str:
        self._check_owner()
        phase = wire["batches"][0]["state"]
        wire = self._before_entry(wire) if phase == "before" else self._success_entry(wire, phase=phase)
        if self._phase == "new":
            if self._state.get(_FIELD) is not None or wire["batches"][0]["evidence_pins"]:
                _fail("before_unavailable")
        elif self._phase == "prepared-reference":
            original = json.loads(self._before_bytes)
            pins = wire["batches"][0]["evidence_pins"]
            original["batches"][0]["evidence_pins"] = pins
            if set(pins) != {"journal.prepared.json"} or original != wire:
                _fail("prepared_evidence_delta_invalid")
        elif (self._phase, phase) in {("prepared-evidence", "staged"), ("staged", "terminal")}:
            pass  # Exact adjacent evidence delta was checked by _success_entry.
        else:
            _fail("checkpoint_unavailable")
        expected = lineage._publication_lineage_checkpoint_delta(self._payload, wire)
        payload = self._controller._python_admission_flow_payload(expected)
        self._identity()
        head = self._ledger.write_controller_checkpoint(self._run_id, expected, expected_sha256=self._head)
        with self._ledger.read_only_observations():
            observed = self._ledger.controller_checkpoint(self._run_id)
            observed_head = None if observed is None else observed[0]
            observed_payload = None
            if observed is not None and observed_head == head:
                observed_payload = self._controller._python_admission_flow_payload(observed[1])
            lineage._validate_publication_lineage_checkpoint_readback(
                expected_head=head, expected_payload=payload, observed_head=observed_head, observed_payload=observed_payload,
            )
            self._identity()
            self._running()
            self._controller._validate_original_run_checkpoint_producer_binding(
                self._ledger.get_run(self._run_id), expected,
            )
            self._history(expected)
        # No shared state or captured authority advances before the entire readback.
        with self._controller._python_admission_brs_observations():
            # Keep source fingerprints and all configuration hooks out of this
            # short observation mutex. The complete gate just ran above.
            self._controller._python_admission_assert_brs_wave(self._wave, owner=True)
            if (self._wave.state is not self._state or self._wave.selected_handoff is not self._handoff
                    or self._wave.selected_context is not self._selected_context
                    or self._wave.checkpoint_sha256 != self._head or self._wave.payload != self._payload
                    or self._controller.ledger is not self._ledger or self._controller.gateway is not self._gateway
                    or self._controller.producer_workspace is not self._workspace
                    or self._controller.producer_sidecar is not self._sidecar):
                _fail("owner_drift")
            self._state[_FIELD] = json.loads(lineage._raw(wire))
            self._wave.checkpoint_sha256, self._wave.payload = head, payload
            self._head, self._payload = head, payload
        return head

    def checkpoint_before(self, wire: object) -> str:
        """CAS one genuine first-before observation; no descriptor creation/publication."""
        try:
            self._check_owner()
            if self._phase != "new" or self._state.get(_FIELD) is not None:
                _fail("before_unavailable")
            detached = self._before_entry(wire)
            if detached["batches"][0]["evidence_pins"]:
                _fail("before_invalid")
            head = self._write(detached)
            self._before_bytes = lineage._raw(detached)
            self._prepared = parse_producer_bundle_publication_journal(detached["batches"][0]["prepared_journal"])
            self._phase = "before"
            return head
        except BaseException:
            self._poisoned = True
            raise

    def _accept_prepared_reference(self, journal: object, record_sha256: object) -> None:
        from .producer_bundle_publication import ProducerBundlePublicationJournal
        lineage._publication_shapes(journal, record_sha256)
        if (self._phase != "before" or type(journal) is not ProducerBundlePublicationJournal
                or ProducerBundlePublicationJournal.to_dict(journal) != self._prepared.to_dict()
                or type(record_sha256) is not str or len(record_sha256) != 64
                or any(char not in "0123456789abcdef" for char in record_sha256)):
            _fail("prepared_reference_invalid")
        self._check_owner(captured=False)
        reference_head, reference_payload = self._wave.checkpoint_sha256, self._wave.payload
        captured, current = json.loads(self._payload), json.loads(reference_payload)
        refs = current.get("python_admission_refs", {})
        reference = refs.get(self._request.episode_id)
        if (type(reference) is not dict or reference.get("record_sha256") != record_sha256
                or reference.get("native_plan") != self._plan.to_dict()
                or reference.get("prepared_journal") != self._prepared.to_dict()
                or self._request.episode_id in captured.get("python_admission_refs", {})):
            _fail("prepared_reference_invalid")
        expected = json.loads(self._payload)
        expected["python_admission_refs"] = captured.get("python_admission_refs", {}) | {self._request.episode_id: reference}
        if expected != current or self._controller._python_admission_flow_payload(expected) != self._wave.payload:
            _fail("prepared_reference_delta_invalid")
        with self._ledger.read_only_observations():
            history = self._ledger.controller_checkpoint_history(self._run_id)
            if (len(history) < 2 or history[-2] != (self._head, captured)
                    or history[-1] != (reference_head, current)):
                _fail("prepared_reference_revision_invalid")
            retained = self._ledger.python_admission_record(
                self._run_id, self._request.episode_id, self._plan.journal_id, expected_record_sha256=record_sha256,
            )
            if retained.native_plan_sha256 != self._plan.plan_sha256:
                _fail("prepared_reference_invalid")
            self._controller._validate_python_admission_references(self._run_id, current)
        self._check_owner(captured=False)
        if (self._wave.checkpoint_sha256 != reference_head or self._wave.payload != reference_payload
                or reference_payload != self._controller._python_admission_flow_payload(current)):
            _fail("prepared_reference_delta_invalid")
        with self._ledger.read_only_observations():
            repeated = self._ledger.controller_checkpoint_history(self._run_id)
            if (repeated != history or repeated[-2] != (self._head, captured)
                    or repeated[-1] != (reference_head, current)):
                _fail("prepared_reference_revision_invalid")
        # Advance only to the originally observed adjacent reference, never a
        # same-payload later revision introduced by a reentrant hook.
        self._head, self._payload = reference_head, reference_payload
        self._phase = "prepared-reference"

    def acknowledge_prepared(self, journal: object, record_sha256: object) -> str:
        """Observe the exact reference CAS, then perform a separate evidence CAS."""
        try:
            self._identity(captured=False)
            self._accept_prepared_reference(journal, record_sha256)
            wire = self._before_entry(json.loads(self._before_bytes))
            path = self._workspace / "evolution/producer-batches" / self._plan.journal_id / "journal.prepared.json"
            pin = capture_lineage_snapshot_pin(path, name="journal.prepared.json")
            raw = _files.read_regular_file(path, lineage._MAX_CHECKPOINT_BYTES)
            if parse_producer_bundle_publication_journal(json.loads(raw)) != self._prepared:
                _fail("prepared_journal_drift")
            verify_persisted_lineage_snapshot(path, pin)
            wire["batches"][0]["evidence_pins"] = {"journal.prepared.json": pin.to_dict()}
            self._before_entry(wire)
            head = self._write(wire)
            self._phase = "prepared-evidence"
            return head
        except BaseException:
            self._poisoned = True
            raise

    def checkpoint_staged(self, wire: object) -> str:
        """Acknowledge existing staged success evidence, without staging artifacts."""
        try:
            self._check_owner()
            detached = self._success_entry(wire, phase="staged")
            head = self._write(detached)
            self._phase = "staged"
            return head
        except BaseException:
            self._poisoned = True
            raise

    def checkpoint_terminal(self, wire: object) -> str:
        """Acknowledge an existing success terminal while the claim is still started."""
        try:
            self._check_owner()
            detached = self._success_entry(wire, phase="terminal")
            head = self._write(detached)
            self._phase = "terminal"
            return head
        except BaseException:
            self._poisoned = True
            raise
