"""Private original-BRS checkpoint primitives, without an online publication facade.

Only a first ``before`` descriptor and its exact prepared-reference/evidence pair
are supported. Staged, terminal, rejection, recovery and successor execution need
separate owner composition. This module never dispatches, evaluates or publishes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import get_ident
from typing import Any

from . import _benchmark_files as _files
from . import rsi_publication_lineage as lineage
from .candidate_evaluation_spec import canonical_json
from .producer_bundle_admission import parse_producer_bundle_admission_plan
from .producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_BATCHES,
    LineageSnapshotPin,
    ProducerLineageBeforeIntent,
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
            "module_sources": {name: hashlib.sha256(_files.read_regular_file(Path(__file__).parent / name, 1024 * 1024)).hexdigest()
                               for name in ("rsi_brs_publication_lineage.py", "rsi_publication_lineage.py",
                                            "rsi_controller.py", "rsi_store.py", "producer_bundle_lineage.py",
                                            "producer_bundle_admission.py", "producer_bundle_publication.py",
                                            "rsi_python_admission.py", "rsi_python_brs_handoff.py",
                                            "rsi_producer_staging_capsule.py")},
            "owner": component_fingerprint(_BRSLineageCheckpointOwner, config={}),
            "methods": {name: component_fingerprint(getattr(_BRSLineageCheckpointOwner, name)) for name in (
                "__init__", "_identity", "_check_owner", "_running", "_before_entry", "_write",
                "checkpoint_before", "acknowledge_prepared", "_accept_prepared_reference",
            )},
            "readers": {name: component_fingerprint(getattr(lineage._LineageEvidenceReader, name)) for name in (
                "_is_v2", "_validate_entry_shape", "_validate_source_pin_maps", "_verify_descriptor", "_snapshot_bytes",
            )},
            "checkpoint_delta": component_fingerprint(lineage._publication_lineage_checkpoint_delta),
            "checkpoint_readback": component_fingerprint(lineage._validate_publication_lineage_checkpoint_readback),
            "root_pin": component_fingerprint(lineage._root_pin),
            "source_pin_check": component_fingerprint(lineage.RSIPublicationLineage._verify_before_source_pins),
            "shape_check": component_fingerprint(lineage._publication_shapes),
            "admission_parser": component_fingerprint(parse_producer_bundle_admission_plan),
            "journal_parser": component_fingerprint(parse_producer_bundle_publication_journal),
            "capture_pin": component_fingerprint(capture_lineage_snapshot_pin),
            "verify_pin": component_fingerprint(verify_persisted_lineage_snapshot),
            "shared_retained_bytes": component_fingerprint(lineage.RSIPublicationLineage._retained_bytes),
        },
    }


class _BRSLineageCheckpointOwner(lineage._LineageEvidenceReader):
    """Exact original BRS owner for a bounded first-before/prepared checkpoint.

    Caller-owned wire is checked against genuine descriptor/snapshot/source files
    and the original request/claim/plan. No arbitrary lineage delta, DRS context,
    completed result, staged/terminal event or latest-head refresh is accepted.
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
        with self._ledger.read_only_observations():
            self._running()
            self._controller._python_admission_active_brs_owner(self._wave)
        return self._state

    def _before_entry(self, wire: object) -> dict[str, Any]:
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
        wire = self._before_entry(wire)
        if self._phase == "new":
            if self._state.get(_FIELD) is not None or wire["batches"][0]["evidence_pins"]:
                _fail("before_unavailable")
        elif self._phase == "prepared-reference":
            original = json.loads(self._before_bytes)
            pins = wire["batches"][0]["evidence_pins"]
            original["batches"][0]["evidence_pins"] = pins
            if set(pins) != {"journal.prepared.json"} or original != wire:
                _fail("prepared_evidence_delta_invalid")
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
