"""Controller-called, create-only DRS producer staging with no dispatch authority."""

from __future__ import annotations

import hashlib
import sqlite3
import stat
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, fields, replace
from pathlib import Path
from threading import get_ident
from typing import Any, NoReturn

from .candidate_evaluation_spec import canonical_json, strict_json
from .native_bootstrap import NativeBootstrapArtifact
from .producer_bundle_lineage import MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES
from .producer_launcher import (
    ProducerLaunchAttestation,
    ProducerLaunchIntent,
    parse_producer_launch_attestation,
)
from .producer_python_runtime_tree import verify_python_runtime_tree_manifest
from .python_producer_binding import build_python_producer_binding, parse_python_producer_binding
from .python_producer_binding_store import (
    PythonProducerBindingSidecar,
    persist_python_producer_binding,
    read_python_producer_binding_sidecar,
)
from .python_producer_checkpoint import PythonProducerCheckpointBinding
from .rsi_gateway import SolverRequest
from .rsi_identity import component_fingerprint
from .rsi_learning import MemorySnapshot, PracticeEpisode, RSILearningError
from .rsi_native_candidate import select_native_candidate
from .rsi_native_inputs import (
    NATIVE_RSI_INPUT_MARKER,
    bind_native_rsi_launch,
    prepare_native_rsi_inputs,
    validate_native_rsi_launch_inputs,
)
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_producer_staging_capsule import (
    MAX_READY_CAPSULE_BYTES,
    MAX_READY_CAPSULE_REFERENCE_BYTES,
    materialize_ready,
    persist_ready_capsule,
    retained_publication_evidence_bytes,
    retained_ready_capsule_bytes,
)
from .rsi_python_scheduler_inputs import _shape, _sidecar

PRODUCER_STAGING_PROTOCOL = "lunar-rsi-producer-episode-staging-v1"
MAX_STAGING_BINDING_BYTES = 32 * 1024
MAX_STAGING_INPUT_BYTES = 8 * 1024
MAX_STAGING_CHECKPOINT_BYTES = 112 * 1024
MAX_RESERVED_STAGING_CHECKPOINT_BYTES = 128 * 1024


def _checkpoint_maximum(state: object = None) -> int:
    """Return the snapshot wire cap for the active staging contract.

    Ordinary DRS staging remains pinned to the historical 112 KiB limit.  The
    original private reserved BRS serial composition already pins a separate
    128 KiB checkpoint contract, so only complete controller snapshots may use
    that larger bound.  Child DTOs (requests, bindings, ready evidence) keep
    their narrower limits regardless of mode.
    """
    if type(state) is dict:
        try:
            from .rsi_brs_serial_driver import reserved_brs_staging_mode

            if reserved_brs_staging_mode(state):
                return MAX_RESERVED_STAGING_CHECKPOINT_BYTES
        except (ImportError, AttributeError, TypeError, ValueError):
            # A malformed or partially initialized state must take the ordinary
            # conservative path; the authoritative BRS gate runs separately.
            pass
    return MAX_STAGING_CHECKPOINT_BYTES


def _fail(reason: str) -> NoReturn:
    raise RSILearningError("rsi_producer_episode_" + reason)


def _wire(value: object, maximum: int = MAX_STAGING_CHECKPOINT_BYTES) -> bytes:
    _shape(value)
    try:
        return canonical_json(value, maximum=maximum)
    except ValueError:
        _fail("wire_invalid")


def _sha(value: object) -> str:
    return hashlib.sha256(_wire(value)).hexdigest()


def _episode_wire(value: object) -> dict:
    # This staging slice accepts only the controller's planned, exact episode DTO.
    # Inspect declared data before serializers, without widening shared DTO gates.
    if type(value) is not PracticeEpisode:
        _fail("episode_invalid")
    declared = fields(PracticeEpisode)
    attributes = object.__getattribute__(value, "__dict__")
    if type(attributes) is not dict or set(attributes) - {item.name for item in declared}:
        _fail("episode_invalid")
    try:
        for item in declared:
            _shape(object.__getattribute__(value, item.name))
    except AttributeError:
        _fail("episode_invalid")
    if value.status != "planned" or value.verifier is not None or value.trace_events != ():
        _fail("episode_invalid")
    wire = PracticeEpisode.to_record_dict(value)
    _wire(wire)
    return wire


@dataclass(frozen=True, slots=True)
class PythonProducerEpisodeStagingConfig:
    workspace: Path
    root_sidecar: PythonProducerBindingSidecar
    artifact: NativeBootstrapArtifact
    attestation_supplier: Callable[[ProducerLaunchIntent], ProducerLaunchAttestation]
    max_episodes: int = 8

    def __post_init__(self) -> None:
        _shape(self.root_sidecar)
        proof = PythonProducerCheckpointBinding.from_sidecar(self.root_sidecar)
        _sidecar(self.root_sidecar, proof)
        if type(self.workspace) is not Path and type(self.workspace) is not type(Path()):
            _fail("workspace_invalid")
        path = self.workspace.expanduser().absolute()
        if len(str(path)) > 512 or path.name.startswith(".env"):
            _fail("workspace_invalid")
        object.__setattr__(self, "workspace", path)
        if type(self.artifact) is not NativeBootstrapArtifact:
            _fail("artifact_invalid")
        if type(self.artifact.path) is not type(Path()):
            _fail("artifact_invalid")
        for value in (
            self.artifact.source_sha256, self.artifact.artifact_sha256, self.artifact.compiler,
            self.artifact.platform_execution_mode, self.artifact.allowlist_id,
        ):
            if type(value) is not str or not value or len(value) > 4096:
                _fail("artifact_invalid")
        _shape(self.artifact.descriptor)
        self.artifact.descriptor.__post_init__()
        if type(self.max_episodes) is not int or not 1 <= self.max_episodes <= 8:
            _fail("capacity_invalid")
        if not callable(self.attestation_supplier):
            _fail("attestation_supplier_invalid")
        _wire(self.root_sidecar.binding.to_dict(), MAX_STAGING_BINDING_BYTES)
        component_fingerprint(self.attestation_supplier)


class PythonProducerEpisodeStager:
    """Stage only after the controller durably retains an episode's original intent.

    Registry entries live exclusively in the existing controller journal. Ready
    evidence can only be read back; this class never runs a gateway or solver.
    """

    def __init__(self, config: PythonProducerEpisodeStagingConfig) -> None:
        if type(config) is not PythonProducerEpisodeStagingConfig:
            _fail("configuration_invalid")
        config.__post_init__()
        self.config = config
        self._original_config = config
        self._supplier = config.attestation_supplier
        self._artifact = config.artifact
        self._root_sidecar = config.root_sidecar
        self._projection = self._config_wire()
        self._config_signature = self._signature()
        # The staging policy's component fingerprint walks the immutable runtime
        # manifest and dependency graph.  Admission checks may call ``policy``
        # repeatedly while a mailbox is in flight; retain that exact digest for
        # this immutable stager instance while `_assert_config` continues to
        # reject mutable configuration drift.
        self._policy_fingerprint: str | None = None
        self._fingerprint_config_cache: dict[str, Any] | None = None

    def _config_wire(self) -> bytes:
        self.config.__post_init__()
        artifact = self.config.artifact
        return _wire({
            "protocol": PRODUCER_STAGING_PROTOCOL, "production_admission": False,
            "workspace": str(self.config.workspace), "max_episodes": self.config.max_episodes,
            "root_checkpoint": PythonProducerCheckpointBinding.from_sidecar(self.config.root_sidecar).to_dict(),
            "root_binding_sha256": self.config.root_sidecar.binding.digest(),
            "artifact": {
                "path": str(artifact.path), "source_sha256": artifact.source_sha256,
                "artifact_sha256": artifact.artifact_sha256, "compiler": artifact.compiler,
                "platform_execution_mode": artifact.platform_execution_mode,
                "allowlist_id": artifact.allowlist_id, "descriptor": artifact.descriptor.to_dict(),
            },
            "attestation_supplier_sha256": component_fingerprint(self.config.attestation_supplier),
        })

    def _assert_config(self) -> None:
        if (self.config is not self._original_config
                or self.config.attestation_supplier is not self._supplier
                or self.config.artifact is not self._artifact or self.config.root_sidecar is not self._root_sidecar
                or self._signature() != self._config_signature):
            _fail("configuration_drift")

    def _signature(self) -> tuple[object, ...]:
        """Cheap immutable-config identity used on hot admission checks."""
        config = self.config
        return (
            config.workspace, id(config.root_sidecar), id(config.artifact),
            id(config.attestation_supplier), config.max_episodes,
        )

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        self._assert_config()
        if self._fingerprint_config_cache is None:
            self._fingerprint_config_cache = {
            "protocol": PRODUCER_STAGING_PROTOCOL,
            "configuration_sha256": hashlib.sha256(self._projection).hexdigest(),
            "production_admission": False,
            "limits": {
                "binding_bytes": MAX_STAGING_BINDING_BYTES, "input_bytes": MAX_STAGING_INPUT_BYTES,
                "checkpoint_bytes": MAX_STAGING_CHECKPOINT_BYTES,
            },
            "dependencies": {
                "config": component_fingerprint(PythonProducerEpisodeStagingConfig, config={}),
                "prepare": component_fingerprint(prepare_native_rsi_inputs),
                "bind": component_fingerprint(bind_native_rsi_launch),
                "binding_builder": component_fingerprint(build_python_producer_binding),
                "sidecar_persist": component_fingerprint(persist_python_producer_binding),
                "input_validator": component_fingerprint(validate_native_rsi_launch_inputs),
                "sidecar_reader": component_fingerprint(read_python_producer_binding_sidecar),
                "wire": component_fingerprint(_wire), "sha": component_fingerprint(_sha),
                "episode_wire": component_fingerprint(_episode_wire),
                "shape": component_fingerprint(_shape), "sidecar": component_fingerprint(_sidecar),
                "runtime_verifier": component_fingerprint(verify_python_runtime_tree_manifest),
                "attestation_parser": component_fingerprint(parse_producer_launch_attestation),
                "binding_parser": component_fingerprint(parse_python_producer_binding),
                "candidate_selector": component_fingerprint(select_native_candidate),
                "canonical_json": component_fingerprint(canonical_json),
                "strict_json": component_fingerprint(strict_json),
                "plan_type": component_fingerprint(NativeRSIExecutionPlan, config={}),
                "proof_type": component_fingerprint(PythonProducerCheckpointBinding, config={}),
                "request_type": component_fingerprint(SolverRequest, config={}),
                "memory_type": component_fingerprint(MemorySnapshot, config={}),
                "episode_type": component_fingerprint(PracticeEpisode, config={}),
                "ready_capsule_writer": component_fingerprint(persist_ready_capsule),
                "ready_capsule_reader": component_fingerprint(materialize_ready),
                "ready_capsule_budget": component_fingerprint(retained_ready_capsule_bytes),
                "retained_evidence_budget": component_fingerprint(retained_publication_evidence_bytes),
            },
            }
        return deepcopy(self._fingerprint_config_cache)

    def policy(self) -> dict[str, Any]:
        self._assert_config()
        fingerprint = self._policy_fingerprint
        if fingerprint is None:
            fingerprint = component_fingerprint(self)
            self._policy_fingerprint = fingerprint
        return {
            "protocol": PRODUCER_STAGING_PROTOCOL,
            "fingerprint": fingerprint,
            "root_checkpoint_sha256": _sha(PythonProducerCheckpointBinding.from_sidecar(self.config.root_sidecar).to_dict()),
            "production_admission": False,
        }

    def _root(self) -> None:
        self._assert_config()
        sidecar = self.config.root_sidecar
        read_python_producer_binding_sidecar(self.config.workspace, binding=sidecar.binding, expected_sidecar=sidecar)
        binding = sidecar.binding
        verify_python_runtime_tree_manifest(
            binding.runtime_tree, expected_tree_sha256=binding.runtime_tree_sha256,
            expected_manifest_sha256=binding.runtime_manifest_sha256, expected_target=binding.target,
        )

    def pure_preflight(self, state: dict, episode: PracticeEpisode, request: SolverRequest, memory: MemorySnapshot) -> int:
        """Bound the prospective ready checkpoint before any reservation or staging."""
        self._assert_config()
        _shape(state)
        if type(state) is not dict:
            _fail("registry_invalid")
        episode_wire = _episode_wire(episode)
        _shape(request)
        _shape(memory)
        if type(request) is not SolverRequest or type(memory) is not MemorySnapshot:
            _fail("request_memory_invalid")
        request_raw = _wire(request.to_dict(), MAX_STAGING_INPUT_BYTES)
        memory_raw = _wire(memory.to_dict(), MAX_STAGING_INPUT_BYTES)
        if request.episode_id != episode.episode_id or request.memory_snapshot_sha256 != memory.digest():
            _fail("request_memory_mismatch")
        root = self.config.root_sidecar.binding
        if (episode.run_id != root.run_id or request.solver_id != root.producer_id
                or request.contract_sha256 != root.contract_sha256
                or request.evaluator_sha256 != root.evaluator_fingerprint
                or request.environment_sha256 != root.environment_sha256
                or dict(request.budget).get("deadline_unix") != root.deadline_unix):
            _fail("original_policy_mismatch")
        entries = state.get("producer_episode_staging", {})
        if type(entries) is not dict:
            _fail("registry_invalid")
        if episode.episode_id in entries:
            return 0
        if len(entries) >= self.config.max_episodes:
            _fail("capacity_exhausted")
        publication = state.get("producer_multi_episode_publication")
        if publication is not None and publication is not True:
            _fail("original_mode_mismatch")
        if publication is True:
            if retained_publication_evidence_bytes(state) + MAX_READY_CAPSULE_BYTES > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
                _fail("capacity_exhausted")
            # Only the independently acknowledged capsule reference enters the
            # checkpoint. Reserve the exact identity projection plus its bounded
            # reference; the original full binding limit remains active.
            token = _sha({"run_id": episode.run_id, "episode_id": episode.episode_id,
                          "request": request.digest()})[:32]
            identity = {
                "run_id": episode.run_id, "episode_id": episode.episode_id,
                "original_run_request_sha256": "f" * 64,
                "original_run_record_sha256": "f" * 64,
                "origin_checkpoint_sha256": "f" * 64,
                "intent": {"episode": episode_wire, "request": request.to_dict()},
                "request_sha256": request.digest(), "memory": memory.to_dict(),
                "memory_snapshot_sha256": memory.digest(), "journal_id": "rsi-stage-" + token,
                "launch_id": "rsi-launch-" + token, "policy": self.policy(),
            }
            growth = len(_wire({"state": "ready", "identity": identity, "ready": None,
                                "failure_code": None})) + MAX_READY_CAPSULE_REFERENCE_BYTES
        else:
            growth = len(_wire(root.to_dict(), MAX_STAGING_BINDING_BYTES)) + 3 * (len(request_raw) + len(memory_raw)) + 16 * 1024
        # Before reservation, include the exact pending intent plus bounded budget,
        # current-episode and phase growth. Once intent is durable those bytes are
        # already in state, so the second preflight cannot newly reject that growth.
        pending = 0 if episode.episode_id in state.get("intents", {}) else (
            len(_wire({"episode": episode_wire, "request": request.to_dict()})) + 4096
        )
        checkpoint_maximum = _checkpoint_maximum(state)
        if len(_wire(state, checkpoint_maximum)) + pending + growth + 512 > checkpoint_maximum:
            _fail("checkpoint_capacity_exhausted")
        return growth

    def identity(self, controller: Any, state: dict, request: SolverRequest, memory: MemorySnapshot) -> dict:
        original = controller.ledger.history(state["run_id"])[0]
        checkpoint = controller.ledger.controller_checkpoint(state["run_id"])
        if checkpoint is None or checkpoint[1] != state:
            _fail("durable_intent_required")
        intent = state["intents"][request.episode_id]
        if SolverRequest.from_dict(intent["request"]) != request:
            _fail("durable_intent_mismatch")
        token = _sha({"run_id": state["run_id"], "episode_id": request.episode_id, "request": request.digest()})[:32]
        return {
            "run_id": state["run_id"], "episode_id": request.episode_id,
            "original_run_request_sha256": original.request_sha256,
            "original_run_record_sha256": original.record_sha256,
            "origin_checkpoint_sha256": checkpoint[0], "intent": intent,
            "request_sha256": request.digest(), "memory": memory.to_dict(),
            "memory_snapshot_sha256": memory.digest(), "journal_id": "rsi-stage-" + token,
            "launch_id": "rsi-launch-" + token, "policy": self.policy(),
        }

    def assert_unattempted(self, controller: Any, episode_id: str) -> None:
        if controller.ledger.get_episode(episode_id) is not None or controller.ledger.episode_result(episode_id) is not None:
            _fail("existing_episode_effects")
        with sqlite3.connect(controller.ledger.database.as_uri() + "?mode=ro", uri=True) as connection:
            if connection.execute(
                "SELECT 1 FROM rsi_native_episode_claims WHERE episode_id = ?", (episode_id,),
            ).fetchone() is not None:
                _fail("existing_episode_effects")

    def _expected_intent(self, identity: dict, inputs: Any) -> ProducerLaunchIntent:
        original = self.config.root_sidecar.binding
        argv = original.intent.argv
        if NATIVE_RSI_INPUT_MARKER in argv:
            if len(argv) < 2 or argv[-2] != NATIVE_RSI_INPUT_MARKER or argv.count(NATIVE_RSI_INPUT_MARKER) != 1:
                _fail("original_argv_invalid")
            argv = argv[:-2]
        argv = argv + inputs.argv_fragment
        intent = replace(
            original.intent, journal_id=identity["journal_id"], launch_id=identity["launch_id"],
            task_id=identity["episode_id"], argv=argv, argv_sha256=_sha(list(argv)), intent_sha256=None,
        )
        return replace(intent, intent_sha256=intent.digest())

    def stage(
        self, controller: Any, state: dict, *, expected_checkpoint_sha256: str,
        request: SolverRequest, memory: MemorySnapshot,
    ) -> dict:
        """Actual create-only native input/launch/sidecar staging, never dispatch."""
        from .rsi_controller import RSILearningController
        from .rsi_store import RSILedger

        if type(controller) is not RSILearningController or type(controller.ledger) is not RSILedger:
            _fail("owner_required")
        permit = controller._producer_staging_permit
        if (type(permit) is not tuple or len(permit) != 4 or permit[0] is not self
                or permit[1] is not state or type(permit[2]) is not str or type(permit[3]) is not int
                or permit[2] != expected_checkpoint_sha256 or permit[3] != get_ident()):
            _fail("owner_required")
        # This one-call permit exists only in the adjacent successful preparing-CAS
        # stack frame. Restart/readback cannot reconstruct it from durable evidence.
        controller._producer_staging_permit = None
        _shape(state)
        _shape(request)
        _shape(memory)
        if type(state) is not dict or type(request) is not SolverRequest or type(memory) is not MemorySnapshot:
            _fail("request_memory_invalid")
        original_ledger = controller.ledger
        ledger_stat = original_ledger.database.lstat()
        if not stat.S_ISREG(ledger_stat.st_mode) or ledger_stat.st_nlink != 1:
            _fail("owner_required")
        ledger_identity = ledger_stat.st_dev, ledger_stat.st_ino
        from .rsi_brs_serial_driver import reserved_brs_staging_mode

        if (controller.producer_stager is not self or not controller.ledger.controller_lock_held(state["run_id"])
                or (state.get("mode") != "drs" and not reserved_brs_staging_mode(state))):
            _fail("owner_required")
        checkpoint = controller.ledger.controller_checkpoint(state["run_id"])
        if checkpoint is None or checkpoint != (expected_checkpoint_sha256, state):
            _fail("staging_checkpoint_conflict")
        self.validate_state(controller, state)
        _shape(request)
        _shape(memory)
        if type(request) is not SolverRequest or type(memory) is not MemorySnapshot:
            _fail("request_memory_invalid")
        entry = state.get("producer_episode_staging", {}).get(request.episode_id)
        if type(entry) is not dict or entry.get("state") != "preparing":
            _fail("durable_preparing_required")
        identity = entry["identity"]
        if request.to_dict() != identity["intent"]["request"] or memory.to_dict() != identity["memory"]:
            _fail("durable_intent_mismatch")
        self.assert_unattempted(controller, request.episode_id)
        self._root()
        inputs = prepare_native_rsi_inputs(self.config.workspace, journal_id=identity["journal_id"], request=request, memory=memory)
        original = self.config.root_sidecar.binding
        intent = self._expected_intent(identity, inputs)
        original_intent_wire = _wire(intent.to_dict())
        attestation = self.config.attestation_supplier(intent)
        _shape(intent)
        if _wire(intent.to_dict()) != original_intent_wire:
            _fail("attestation_intent_drift")
        self._root()
        if controller.ledger.controller_checkpoint(state["run_id"]) != (expected_checkpoint_sha256, state):
            _fail("staging_checkpoint_conflict")
        self.assert_unattempted(controller, request.episode_id)
        _shape(attestation)
        if type(attestation) is not ProducerLaunchAttestation:
            _fail("attestation_invalid")
        attestation = parse_producer_launch_attestation(attestation.to_dict())
        inputs = bind_native_rsi_launch(
            self.config.workspace, intent=intent, attestation=attestation,
            artifact=self.config.artifact, inputs=inputs,
        )
        binding = build_python_producer_binding(
            runtime_manifest=original.runtime_manifest, runtime_tree=original.runtime_tree,
            intent=intent, attestation=attestation, deadline_unix=original.deadline_unix,
            budget=dict(request.budget), fixture_case=original.fixture_case,
        )
        _wire(binding.to_dict(), MAX_STAGING_BINDING_BYTES)
        sidecar = persist_python_producer_binding(self.config.workspace, binding=binding)
        proof = PythonProducerCheckpointBinding.from_sidecar(sidecar)
        plan = NativeRSIExecutionPlan.from_native_inputs(
            request=request, memory=memory, inputs=inputs, intent=intent,
            attestation=attestation, artifact=self.config.artifact,
            candidate_selector_id="native-selector-v1", candidate_selector_sha256=component_fingerprint(select_native_candidate),
            evaluator_kind=intent.evaluator_kind, evaluator_fingerprint=intent.evaluator_fingerprint,
        )
        ready = {
            "binding": binding.to_dict(), "producer_checkpoint": proof.to_dict(),
            "plan": plan.to_dict(), "inputs": inputs.to_dict(),
            "input_manifest": strict_json(inputs.manifest_json),
        }
        self.validate_ready(identity, ready)
        if state.get("producer_multi_episode_publication") is True:
            self._assert_staging_owner(controller, state, expected_checkpoint_sha256,
                                       original_ledger, ledger_identity)
            retained_bytes = retained_publication_evidence_bytes(state)
            ready = persist_ready_capsule(
                self.config.workspace, identity["journal_id"], ready, retained_bytes=retained_bytes,
            )
            self._assert_staging_owner(controller, state, expected_checkpoint_sha256,
                                       original_ledger, ledger_identity)
        return ready

    def _assert_staging_owner(self, controller: Any, state: dict, expected_head: str,
                              original_ledger: Any, ledger_identity: tuple[int, int]) -> None:
        self._assert_config()
        if (controller.producer_stager is not self
                or controller.ledger is not original_ledger
                or controller.producer_sidecar is not self.config.root_sidecar
                or Path(controller.producer_workspace).absolute() != self.config.workspace
                or controller.producer_multi_episode_publication is not True):
            _fail("staging_checkpoint_conflict")
        current_stat = original_ledger.database.lstat()
        if (not stat.S_ISREG(current_stat.st_mode) or current_stat.st_nlink != 1
                or (current_stat.st_dev, current_stat.st_ino) != ledger_identity):
            _fail("staging_checkpoint_conflict")
        if (not controller.ledger.controller_lock_held(state["run_id"])
                or controller.ledger.controller_checkpoint(state["run_id"]) != (expected_head, state)):
            _fail("staging_checkpoint_conflict")
        self._root()
        for episode_id, entry in state["producer_episode_staging"].items():
            if entry["state"] == "preparing":
                self.assert_unattempted(controller, episode_id)

    def validate_ready(self, identity: dict, ready: dict) -> None:
        try:
            self._validate_ready(identity, ready)
        except RSILearningError:
            raise
        except Exception:  # noqa: BLE001 - never expose malformed child evidence prose
            _fail("ready_invalid")

    def _validate_ready(self, identity: dict, ready: dict) -> None:
        self._root()
        _wire(identity)
        _wire(ready)
        if type(ready) is not dict or set(ready) != {"binding", "producer_checkpoint", "plan", "inputs", "input_manifest"}:
            _fail("ready_invalid")
        binding = parse_python_producer_binding(_wire(ready["binding"], MAX_STAGING_BINDING_BYTES))
        proof = PythonProducerCheckpointBinding.from_dict(ready["producer_checkpoint"])
        sidecar = PythonProducerBindingSidecar(binding=binding, **dict(proof.sidecar_pin))
        proof.validate_sidecar(sidecar)
        read_python_producer_binding_sidecar(self.config.workspace, binding=binding, expected_sidecar=sidecar)
        root = self.config.root_sidecar.binding
        if (binding.run_id != identity["run_id"] or binding.intent.journal_id != identity["journal_id"]
                or binding.intent.launch_id != identity["launch_id"] or binding.task_id != identity["episode_id"]
                or binding.runtime_manifest != root.runtime_manifest or binding.runtime_tree != root.runtime_tree
                or binding.deadline_unix != root.deadline_unix or binding.producer_id != root.producer_id):
            _fail("ready_binding_mismatch")
        inputs = validate_native_rsi_launch_inputs(
            self.config.workspace, intent=binding.intent, attestation=binding.attestation,
            artifact=self.config.artifact, require_unexpired=False,
        )
        expected_binding = build_python_producer_binding(
            runtime_manifest=root.runtime_manifest, runtime_tree=root.runtime_tree,
            intent=self._expected_intent(identity, inputs), attestation=binding.attestation,
            deadline_unix=root.deadline_unix, budget=dict(inputs.request.budget), fixture_case=root.fixture_case,
        )
        if binding.to_dict() != expected_binding.to_dict():
            _fail("ready_binding_mismatch")
        if (inputs.to_dict() != ready["inputs"] or strict_json(inputs.manifest_json) != ready["input_manifest"]
                or inputs.request.to_dict() != identity["intent"]["request"]
                or inputs.request.digest() != identity["request_sha256"]
                or inputs.memory.to_dict() != identity["memory"]):
            _fail("ready_input_drift")
        expected = NativeRSIExecutionPlan.from_native_inputs(
            request=inputs.request, memory=inputs.memory, inputs=inputs, intent=binding.intent,
            attestation=binding.attestation, artifact=self.config.artifact,
            candidate_selector_id="native-selector-v1", candidate_selector_sha256=component_fingerprint(select_native_candidate),
            evaluator_kind=binding.evaluator_kind, evaluator_fingerprint=binding.evaluator_fingerprint,
        )
        if expected.to_dict() != ready["plan"]:
            _fail("ready_plan_drift")

    def validate_state(self, controller: Any, state: dict) -> None:
        """Require original policy and every earliest staging obligation in history."""
        self._assert_config()
        if (controller.producer_sidecar is not self.config.root_sidecar
                or Path(controller.producer_workspace).absolute() != self.config.workspace):
            _fail("controller_root_mismatch")
        original = controller.ledger.history(state["run_id"])[0]
        publication = original.payload.get("producer_multi_episode_publication")
        if publication is not None and publication is not True:
            _fail("original_mode_mismatch")
        if (state.get("producer_multi_episode_publication") is not publication
                or controller.producer_multi_episode_publication is not (publication is True)):
            _fail("original_mode_mismatch")
        # A durable state already carries the policy digest captured when the
        # stager was created.  Seed the immutable in-process cache from that
        # digest before walking historical entries; the full run fingerprint
        # gate independently verifies source/code drift at admission boundaries.
        persisted_policy = state.get("producer_staging_policy") if type(state) is dict else None
        if (self._policy_fingerprint is None and type(persisted_policy) is dict
                and type(persisted_policy.get("fingerprint")) is str):
            self._policy_fingerprint = persisted_policy["fingerprint"]
        policy = self.policy()
        if original.payload.get("producer_staging_policy") != policy or state.get("producer_staging_policy") != policy:
            _fail("original_mode_mismatch")
        history = controller.ledger.controller_checkpoint_history(state["run_id"])
        snapshots = list(history)
        if not snapshots or snapshots[-1][1] != state:
            snapshots.append((None, state))
        origins = dict(history)
        retained: dict[str, dict] = {}
        nonces = set()
        journals = {self.config.root_sidecar.binding.intent.journal_id}
        launches = {self.config.root_sidecar.binding.intent.launch_id}
        previous_digest = None
        for snapshot_digest, snapshot in snapshots:
            if (snapshot.get("producer_staging_policy") != policy
                    or snapshot.get("producer_multi_episode_publication") is not publication):
                _fail("original_mode_mismatch")
            entries = snapshot.get("producer_episode_staging", {})
            if type(entries) is not dict or len(entries) > self.config.max_episodes or not retained.keys() <= entries.keys():
                _fail("history_missing")
            _wire(snapshot, _checkpoint_maximum(snapshot))
            retained_publication_evidence_bytes(snapshot)
            for episode_id, entry in entries.items():
                if (type(entry) is not dict or set(entry) != {"state", "identity", "ready", "failure_code"}
                        or type(entry["state"]) is not str
                        or entry["state"] not in {"preparing", "ready", "unknown"}):
                    _fail("history_invalid")
                identity = entry["identity"]
                if type(identity) is not dict or set(identity) != {
                    "run_id", "episode_id", "original_run_request_sha256", "original_run_record_sha256",
                    "origin_checkpoint_sha256", "intent", "request_sha256", "memory",
                    "memory_snapshot_sha256", "journal_id", "launch_id", "policy",
                }:
                    _fail("history_identity_drift")
                if any(type(identity[name]) is not str for name in (
                    "run_id", "episode_id", "original_run_request_sha256", "original_run_record_sha256",
                    "origin_checkpoint_sha256", "request_sha256", "memory_snapshot_sha256", "journal_id", "launch_id",
                )):
                    _fail("history_identity_drift")
                origin = origins.get(identity.get("origin_checkpoint_sha256"))
                if (origin is None or origin.get("intents", {}).get(episode_id) != identity.get("intent")
                        or identity.get("original_run_record_sha256") != original.record_sha256
                        or identity.get("original_run_request_sha256") != original.request_sha256
                        or identity.get("run_id") != state["run_id"] or identity.get("episode_id") != episode_id
                        or identity.get("policy") != policy):
                    _fail("history_identity_drift")
                try:
                    if type(identity["intent"]) is not dict or set(identity["intent"]) != {"episode", "request"}:
                        _fail("history_identity_drift")
                    request = SolverRequest.from_dict(identity["intent"]["request"])
                    memory = MemorySnapshot.from_dict(identity["memory"])
                    episode = PracticeEpisode.from_dict(identity["intent"]["episode"])
                    token = _sha({"run_id": state["run_id"], "episode_id": episode_id, "request": request.digest()})[:32]
                    if (request.episode_id != episode_id or episode.episode_id != episode_id
                            or episode.run_id != state["run_id"] or episode.status != "planned"
                            or request.digest() != identity["request_sha256"]
                            or memory.digest() != identity["memory_snapshot_sha256"]
                            or request.memory_snapshot_sha256 != memory.digest()
                            or episode.memory_snapshot_sha256 != memory.digest()
                            or origin.get("memory_snapshot") != memory.to_dict()
                            or identity["journal_id"] != "rsi-stage-" + token
                            or identity["launch_id"] != "rsi-launch-" + token):
                        _fail("history_identity_drift")
                    self.pure_preflight(origin, episode, request, memory)
                except RSILearningError:
                    raise
                except Exception:  # noqa: BLE001 - fixed refusal for malformed historical evidence
                    _fail("history_identity_drift")
                previous = retained.get(episode_id)
                if previous is None:
                    if entry["state"] != "preparing" or entry["ready"] is not None or entry["failure_code"] is not None:
                        _fail("history_retrofit")
                    if (identity["origin_checkpoint_sha256"] != previous_digest
                            or origin.get("producer_episode_staging", {}).get(episode_id) is not None
                            or snapshot.get("intents", {}).get(episode_id) != identity["intent"]):
                        _fail("history_origin_drift")
                    if identity["journal_id"] in journals or identity["launch_id"] in launches:
                        _fail("launch_identity_reused")
                    journals.add(identity["journal_id"])
                    launches.add(identity["launch_id"])
                elif previous["identity"] != identity or (previous["state"] != "preparing" and previous != entry):
                    _fail("history_drift")
                if entry["state"] == "preparing" and (entry["ready"] is not None or entry["failure_code"] is not None):
                    _fail("history_invalid")
                if entry["state"] == "unknown" and (entry["ready"] is not None or entry["failure_code"] != "staging_failed"):
                    _fail("history_invalid")
                if entry["state"] == "ready":
                    if entry["failure_code"] is not None:
                        _fail("history_invalid")
                    if previous is None or previous["state"] == "preparing":
                        ready = materialize_ready(
                            entry["ready"], allow_capsule=publication is True,
                            expected_workspace=self.config.workspace,
                            expected_journal_id=identity["journal_id"],
                        )
                        if (type(ready) is not dict or type(ready.get("binding")) is not dict
                                or type(ready["binding"].get("attestation")) is not dict
                                or type(ready["binding"]["attestation"].get("nonce")) is not str):
                            _fail("ready_invalid")
                        nonce = ready["binding"]["attestation"]["nonce"]
                        if nonce in nonces or nonce == self.config.root_sidecar.binding.attestation.nonce:
                            _fail("nonce_reused")
                        nonces.add(nonce)
                    retained[episode_id] = entry
                else:
                    retained[episode_id] = entry
            previous_digest = snapshot_digest
        for entry in retained.values():
            if entry["state"] == "ready":
                ready = materialize_ready(
                    entry["ready"], allow_capsule=publication is True,
                    expected_workspace=self.config.workspace,
                    expected_journal_id=entry["identity"]["journal_id"],
                )
                self.validate_ready(entry["identity"], ready)


__all__ = ["PythonProducerEpisodeStager", "PythonProducerEpisodeStagingConfig"]
