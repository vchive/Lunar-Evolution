"""Explicit, durable generation admission and holdout scheduling for local RSI memory."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_callbacks import DurableCallbackJournal
from .rsi_identity import RSIIdentityError, component_fingerprint
from .rsi_learning import (
    MAX_MEMORY_ENTRIES,
    MemoryItem,
    MemorySnapshot,
    RSILearningError,
    VerifierCheck,
    VerifierDecision,
)
from .rsi_memory_governance import (
    MemoryAdmissionRecord,
    MemoryGovernanceError,
    MemoryGovernanceStore,
    _identifier,
    _mapping,
)
from .rsi_memory_promotion import MemoryPromotionAdapter, _validate_report
from .rsi_memory_snapshot_gate import _database_identity
from .rsi_parent_budget import ParentRunBudget
from .rsi_store import RSILedger
from .rsi_transfer_regression import (
    RegressionPolicy,
    TransferObservation,
    TransferRegressionReport,
    TransferRegressionSuite,
    TransferTask,
    TransferTrial,
)

_STAGES = ("observed", "verified", "candidate", "shadow", "approved", "active")
_PHASES = {"admitting", "holdout", "unknown", "active", "rejected", "revalidating", "quarantined"}


class GenerationGovernanceError(MemoryGovernanceError):
    """Fixed-code refusal at the trusted local generation boundary."""


def _fail(code: str) -> None:
    raise GenerationGovernanceError("rsi_generation_governance_" + code)


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=8 * 1024 * 1024)).hexdigest()


def _item_digest(item: MemoryItem) -> str:
    return _digest(item.to_dict())


def _proof(payload: Mapping[str, Any]) -> VerifierDecision:
    fields = dict(payload)
    fields["checks"] = tuple(VerifierCheck(**check) for check in fields["checks"])
    decision = VerifierDecision(**fields)
    if decision.to_dict() != payload:
        _fail("proof_invalid")
    return decision


@dataclass(frozen=True)
class GenerationGovernancePolicy:
    regression: RegressionPolicy = field(default_factory=RegressionPolicy)
    max_items: int = MAX_MEMORY_ENTRIES
    max_lineage_depth: int = 64

    def __post_init__(self) -> None:
        if (not isinstance(self.regression, RegressionPolicy)
                or type(self.max_items) is not int or not 1 <= self.max_items <= MAX_MEMORY_ENTRIES
                or type(self.max_lineage_depth) is not int or not 1 <= self.max_lineage_depth <= 256):
            _fail("policy_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {"protocol": "lunar-rsi-generation-policy-v1", "regression": self.regression.to_dict(),
                "max_items": self.max_items, "max_lineage_depth": self.max_lineage_depth}


@dataclass(frozen=True)
class GenerationRegressionRequest:
    generation_id: str
    parent_memory: MemorySnapshot
    current_memory: MemorySnapshot
    policy: RegressionPolicy
    admissions: Mapping[str, str]
    intent_sha256: str
    validation_id: str | None = None
    manifest: tuple[TransferTask, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "admissions", MappingProxyType(dict(self.admissions)))

    def to_dict(self) -> dict[str, Any]:
        return {"generation_id": self.generation_id, "parent_memory": self.parent_memory.to_dict(),
                "current_memory": self.current_memory.to_dict(), "policy": self.policy.to_dict(),
                "admissions": dict(self.admissions), "intent_sha256": self.intent_sha256,
                "validation_id": self.validation_id,
                "manifest": None if self.manifest is None else [task.to_dict() for task in self.manifest]}


@dataclass(frozen=True)
class GenerationAdmissionResult:
    generation_id: str
    status: str
    effective_snapshot: MemorySnapshot
    admissions: Mapping[str, str]
    report: TransferRegressionReport | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "admissions", MappingProxyType(dict(self.admissions)))


RegressionRunner = Callable[[GenerationRegressionRequest], TransferRegressionReport]


class RSIGovernanceCoordinator:
    """Freeze provenance, re-admit inherited items, and publish only complete active generations.

    Callbacks are trusted local code. Their child campaigns own trial reservations and the
    shared parent budget. An uncertain outer callback always requires explicit reconciliation.
    """

    def __init__(self, governance: MemoryGovernanceStore, *, ledger: RSILedger, scope: str,
                 compatibility: Mapping[str, object], policy: GenerationGovernancePolicy) -> None:
        if not isinstance(governance, MemoryGovernanceStore) or not isinstance(ledger, RSILedger):
            _fail("store_invalid")
        if not isinstance(policy, GenerationGovernancePolicy):
            _fail("policy_invalid")
        self.governance = governance
        self.ledger = ledger
        self.scope = _identifier(scope, "scope")
        self._compatibility = canonical_json(_mapping(compatibility), maximum=32 * 1024)
        self.policy = policy
        self._databases = (governance.database, ledger.database)
        self._identities = tuple(_database_identity(path) for path in self._databases)
        self._config = self.rsi_fingerprint_config()
        self._fingerprint = component_fingerprint(self)
        self.callbacks = DurableCallbackJournal(ledger)
        self.promotion = MemoryPromotionAdapter(governance)

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        return {"protocol": "lunar-rsi-generation-governance-v1", "scope": self.scope,
                "compatibility": json.loads(self._compatibility), "policy": self.policy.to_dict(),
                "databases": [{"path": str(path), "device": identity[0], "inode": identity[1]}
                              for path, identity in zip(self._databases, self._identities)]}

    def _check(self) -> None:
        if ((self.governance.database, self.ledger.database) != self._databases
                or tuple(_database_identity(path) for path in self._databases) != self._identities):
            _fail("database_changed")
        if self.rsi_fingerprint_config() != self._config or component_fingerprint(self) != self._fingerprint:
            _fail("fingerprint_drift")

    def _namespace(self, generation_id: str) -> str:
        return "rsi-generation:" + _digest({"scope": self.scope,
                                            "generation_id": _identifier(generation_id, "generation_id")})

    def _index_namespace(self, snapshot: MemorySnapshot) -> str:
        return "rsi-generation-index:" + _digest({"scope": self.scope, "snapshot": snapshot.digest()})

    def _snapshot_generation(self, snapshot: MemorySnapshot) -> str:
        history = self.ledger.controller_checkpoint_history(self._index_namespace(snapshot))
        if len(history) != 1:
            _fail("snapshot_unregistered")
        index = history[0][1]
        if (set(index) != {"protocol", "snapshot_sha256", "generation_id", "coordinator_sha256"}
                or index["protocol"] != "rsi-generation-index-v1"
                or index["snapshot_sha256"] != snapshot.digest()
                or index["coordinator_sha256"] != self._fingerprint):
            _fail("index_drift")
        return index["generation_id"]

    def _index(self, intent: Mapping[str, Any]) -> None:
        snapshot = MemorySnapshot.from_dict(intent["current_memory"])
        namespace = self._index_namespace(snapshot)
        entry = {"protocol": "rsi-generation-index-v1", "snapshot_sha256": snapshot.digest(),
                 "generation_id": intent["generation_id"], "coordinator_sha256": self._fingerprint}
        with self.ledger.controller_lock(namespace):
            history = self.ledger.controller_checkpoint_history(namespace)
            if history:
                if len(history) != 1 or history[0][1] != entry:
                    _fail("snapshot_generation_conflict")
            else:
                self.ledger.write_controller_checkpoint(namespace, entry, expected_sha256=None)

    def _source(self, item: MemoryItem, decision: VerifierDecision) -> None:
        pins = json.loads(self._compatibility)
        if (not isinstance(decision, VerifierDecision) or decision.outcome != "pass"
                or not decision.independent_of_actor or not decision.checks
                or any(check.outcome != "pass" for check in decision.checks)
                or item.episode_id != decision.episode_id or item.receipt_sha256 != decision.receipt_sha256
                or decision.contract_sha256 not in item.compatible_contracts
                or any(getattr(decision, name) is None for name in
                       ("contract_sha256", "evaluator_sha256", "environment_sha256"))):
            _fail("source_verifier_invalid")
        for name, aliases in (("contract_sha256", ("contract_sha256", "contract")),
                              ("evaluator_sha256", ("evaluator_sha256", "evaluator")),
                              ("environment_sha256", ("environment_sha256", "environment"))):
            for alias in aliases:
                if alias in pins and pins[alias] != getattr(decision, name):
                    _fail("source_compatibility_drift")
        if "solver" in pins and pins["solver"] not in item.compatible_solvers:
            _fail("source_compatibility_drift")

    @staticmethod
    def _runner_fingerprint(runner: object) -> str:
        owner = getattr(runner, "__self__", runner)
        if not any(callable(getattr(owner, name, None)) for name in
                   ("rsi_fingerprint_config", "fingerprint_config")):
            _fail("runner_hook_required")
        try:
            return component_fingerprint(runner)
        except RSIIdentityError as exc:
            raise GenerationGovernanceError("rsi_generation_governance_runner_invalid") from exc

    def _manifest(self, value: object) -> list[dict[str, str]] | None:
        if value is None:
            return None
        try:
            if type(value) is not list or len(value) * 3 * self.policy.regression.repetitions > 1024:
                raise ValueError("manifest bounds")
            tasks = tuple(TransferTask(**task) for task in value)
            TransferRegressionSuite._validate_tasks(tasks, self.policy.regression)
            if [task.to_dict() for task in tasks] != value:
                raise ValueError("manifest roundtrip")
            return deepcopy(value)
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            raise GenerationGovernanceError("rsi_generation_governance_manifest_invalid") from exc

    def _runner_manifest(self, runner: object, fingerprint: str) -> list[dict[str, str]] | None:
        owner = getattr(runner, "__self__", runner)
        hook = next(getattr(owner, name) for name in ("rsi_fingerprint_config", "fingerprint_config")
                    if callable(getattr(owner, name, None)))
        config = hook()
        manifest = self._manifest(config.get("manifest")) if isinstance(config, Mapping) else None
        if self._runner_fingerprint(runner) != fingerprint:
            _fail("runner_drift")
        return manifest

    @staticmethod
    def _runner_config(runner: object) -> Mapping[str, Any]:
        owner = getattr(runner, "__self__", runner)
        hook = next((getattr(owner, name) for name in ("rsi_fingerprint_config", "fingerprint_config")
                     if callable(getattr(owner, name, None))), None)
        if hook is None:
            _fail("runner_hook_required")
        config = hook()
        return config if isinstance(config, Mapping) else {}

    def _parent_shape(self, identity: object) -> dict[str, Any] | None:
        if identity is None:
            return None
        if (not isinstance(identity, dict)
                or set(identity) != {"run_id", "request_sha256", "ledger", "device", "inode", "planned_budget"}
                or identity["ledger"] != str(self.ledger.database)
                or (identity["device"], identity["inode"]) != self._identities[1]):
            _fail("parent_budget_identity_drift")
        return deepcopy(identity)

    def _parent(self, identity: object) -> ParentRunBudget | None:
        pin = self._parent_shape(identity)
        if pin is None:
            return None
        account = ParentRunBudget(self.ledger, pin["run_id"])
        if account.identity() != pin:
            _fail("parent_budget_identity_drift")
        return account

    @staticmethod
    def serialize_report(report: TransferRegressionReport) -> dict[str, Any]:
        """Persist the complete trial material needed to verify reports after restart."""
        try:
            _validate_report(report)
            report.validate_policy_evidence()
            return {"report": report.to_dict(),
                    "trials": [trial.to_dict() for summary in report.summaries for trial in summary.trials]}
        except (TypeError, ValueError, RSILearningError) as exc:
            raise GenerationGovernanceError("rsi_generation_governance_report_invalid") from exc

    @staticmethod
    def deserialize_report(value: Mapping[str, Any]) -> TransferRegressionReport:
        try:
            if set(value) != {"report", "trials"}:
                raise ValueError("shape")
            payload = value["report"]
            tasks = tuple(TransferTask(**task) for task in payload["tasks"])
            trials = []
            for trial in value["trials"]:
                observation = dict(trial["observation"])
                observation["accessed_task_ids"] = tuple(observation["accessed_task_ids"])
                observation["memory_ids_used"] = tuple(observation["memory_ids_used"])
                trials.append(TransferTrial(trial["arm"], TransferTask(**trial["task"]),
                                            trial["repetition"], TransferObservation(**observation)))
            summaries = tuple(TransferRegressionSuite._summary(
                summary["arm"], tuple(trial for trial in trials if trial.arm == summary["arm"]),
            ) for summary in payload["summaries"])
            report = TransferRegressionReport(
                tasks, payload["repetitions"], summaries, tuple(payload["contamination"]),
                payload["promotion_eligible"], tuple(payload["rejection_reasons"]),
                payload["holdout_receipt_sha256"], payload["baseline_receipt_sha256"],
                payload["report_sha256"], payload["old_memory_sha256"], payload["current_memory_sha256"],
                RegressionPolicy(**payload["policy"]),
            )
            if RSIGovernanceCoordinator.serialize_report(report) != value:
                raise ValueError("roundtrip")
            return report
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            raise GenerationGovernanceError("rsi_generation_governance_report_invalid") from exc

    def _report(self, value: Mapping[str, Any], request: GenerationRegressionRequest) -> TransferRegressionReport:
        report = self.deserialize_report(value)
        if (report.policy != request.policy or report.old_memory_sha256 != request.parent_memory.digest()
                or report.current_memory_sha256 != request.current_memory.digest()
                or request.manifest is not None and report.tasks != request.manifest):
            _fail("report_binding_drift")
        allowed = {"no_memory": set(), "old_memory": {item.memory_id for item in request.parent_memory.items},
                   "current_memory": {item.memory_id for item in request.current_memory.items}}
        inferred = set()
        for summary in report.summaries:
            for trial in summary.trials:
                inferred.update(f"{trial.arm}:{trial.task.task_id}:unexpected_memory:{memory_id}"
                                for memory_id in set(trial.observation.memory_ids_used) - allowed[trial.arm])
                inferred.update(f"{trial.arm}:{trial.task.task_id}:unexpected_task:{task_id}"
                                for task_id in set(trial.observation.accessed_task_ids) - {trial.task.task_id})
        if set(report.contamination) != inferred:
            _fail("report_contamination_drift")
        return report

    def _request(self, state: Mapping[str, Any], validation_id: str | None = None) -> GenerationRegressionRequest:
        intent = state["intent"]
        manifest = (intent["runner_manifest"] if validation_id is None
                    else state["validations"][validation_id]["runner_manifest"])
        return GenerationRegressionRequest(
            intent["generation_id"], MemorySnapshot.from_dict(intent["parent_memory"]),
            MemorySnapshot.from_dict(intent["current_memory"]), self.policy.regression,
            intent["admissions"], state["intent_sha256"], validation_id,
            None if manifest is None else tuple(TransferTask(**task) for task in manifest),
        )

    def _callback_report(self, state: Mapping[str, Any], result: Mapping[str, Any],
                         validation_id: str | None = None) -> None:
        intent = state["intent"]
        callback_id = "holdout" if validation_id is None else "revalidation:" + validation_id
        fingerprint = (intent["runner_fingerprint"] if validation_id is None
                       else state["validations"][validation_id]["runner_fingerprint"])
        callback = self.callbacks.inspect(self._namespace(intent["generation_id"]), callback_id)
        binding = {"request": self._request(state, validation_id).to_dict(), "runner_fingerprint": fingerprint}
        if (callback is None or callback[1]["status"] != "completed"
                or callback[1]["binding"] != binding or callback[1]["result"] != result):
            _fail("callback_evidence_drift")

    def _load(self, generation_id: str) -> tuple[str, dict[str, Any]] | None:
        self._check()
        history = self.ledger.controller_checkpoint_history(self._namespace(generation_id))
        previous = None
        edges = {"admitting": {"admitting", "holdout"}, "holdout": {"holdout", "unknown", "active", "rejected"},
                 "unknown": {"unknown", "active", "rejected"}, "active": {"active", "revalidating"},
                 "revalidating": {"revalidating", "active", "quarantined"},
                 "rejected": set(), "quarantined": set()}
        for _head, state in history:
            try:
                if (set(state) != {"protocol", "intent", "intent_sha256", "phase", "heads", "report", "validations", "pending_validation"}
                        or state["protocol"] != "rsi-generation-v1" or state["phase"] not in _PHASES):
                    raise ValueError("shape")
                intent = state["intent"]
                if set(intent) != {"generation_id", "coordinator_sha256", "parent_memory", "current_memory",
                                   "runner_fingerprint", "runner_manifest", "runner_parent", "lineage_depth", "provenance", "admissions"}:
                    raise ValueError("intent shape")
                if (intent["generation_id"] != generation_id or intent["coordinator_sha256"] != self._fingerprint
                        or state["intent_sha256"] != _digest(intent)):
                    _fail("fingerprint_drift")
                self._manifest(intent["runner_manifest"])
                self._parent_shape(intent["runner_parent"])
                parent = MemorySnapshot.from_dict(intent["parent_memory"])
                current = MemorySnapshot.from_dict(intent["current_memory"])
                if (current.parent_snapshot_sha256 != parent.digest() or current.digest() == parent.digest()
                        or len(current.items) > self.policy.max_items
                        or set(intent["admissions"]) != {item.memory_id for item in current.items}
                        or set(intent["provenance"]) != set(intent["admissions"])
                        or type(intent["lineage_depth"]) is not int
                        or not 1 <= intent["lineage_depth"] <= self.policy.max_lineage_depth
                        or set(state["heads"]) - set(intent["admissions"])):
                    raise ValueError("intent")
                for pin in (intent["runner_fingerprint"], *state["heads"].values()):
                    if type(pin) is not str or len(pin) != 64 or any(char not in "0123456789abcdef" for char in pin):
                        raise ValueError("pin")
                for item in current.items:
                    admission = "generation-item:" + _digest({"generation": generation_id,
                                                              "snapshot": current.digest(), "item": item.memory_id})
                    if intent["admissions"][item.memory_id] != admission:
                        raise ValueError("mapping")
                    origin = intent["provenance"][item.memory_id]
                    if origin["kind"] == "verified":
                        if set(origin) != {"kind", "verifier"}:
                            raise ValueError("source shape")
                        self._source(item, _proof(origin["verifier"]))
                    elif origin["kind"] == "inherited":
                        if set(origin) != {"kind", "parent_admission_id", "parent_admission_sha256"}:
                            raise ValueError("lineage shape")
                        old = next((entry for entry in parent.items if entry.memory_id == item.memory_id), None)
                        if old is None or old.to_dict() != item.to_dict() or not origin["parent_admission_sha256"]:
                            raise ValueError("lineage")
                    else:
                        raise ValueError("origin")
                if state["report"] is not None:
                    report = self._report(state["report"], self._request(state))
                    self._callback_report(state, state["report"])
                    if (state["phase"] in {"active", "revalidating", "quarantined"} and not report.promotion_eligible
                            or state["phase"] == "rejected" and report.promotion_eligible):
                        raise ValueError("phase evidence")
                if state["phase"] in {"active", "rejected", "revalidating", "quarantined"} and state["report"] is None:
                    raise ValueError("report missing")
                if type(state["validations"]) is not dict:
                    raise ValueError("validations")
                for identity, validation in state["validations"].items():
                    _identifier(identity, "validation_id")
                    if set(validation) != {"runner_fingerprint", "runner_manifest", "runner_parent", "status", "report"}:
                        raise ValueError("validation")
                    self._manifest(validation["runner_manifest"])
                    self._parent_shape(validation["runner_parent"])
                    if validation["status"] not in {"started", "completed"}:
                        raise ValueError("validation status")
                    if validation["status"] == "completed":
                        report = self._report(validation["report"], self._request(state, identity))
                        self._callback_report(state, validation["report"], identity)
                        if state["phase"] == "active" and not report.promotion_eligible:
                            raise ValueError("failed active validation")
                    elif validation["report"] is not None:
                        raise ValueError("started report")
                pending = state["pending_validation"]
                if ((state["phase"] == "revalidating") is not (pending is not None)
                        or pending is not None and pending not in state["validations"]
                        or any(entry["status"] == "started" and key != pending
                               for key, entry in state["validations"].items())):
                    raise ValueError("pending validation")
                if previous is None:
                    if state["phase"] != "admitting" or state["heads"] or state["report"] or state["validations"] or pending:
                        raise ValueError("initial")
                elif (previous["intent"] != intent or state["phase"] not in edges[previous["phase"]]
                      or (previous["report"] is not None and previous["report"] != state["report"])
                      or not set(previous["validations"]).issubset(state["validations"])
                      or any(entry["status"] == "completed" and state["validations"].get(key) != entry
                             for key, entry in previous["validations"].items())
                      or any(any(state["validations"][key][name] != entry[name]
                                 for name in ("runner_fingerprint", "runner_manifest", "runner_parent"))
                             for key, entry in previous["validations"].items())
                      or previous["pending_validation"] is not None
                      and pending not in {None, previous["pending_validation"]}):
                    raise ValueError("transition")
                previous = state
            except GenerationGovernanceError:
                raise
            except (KeyError, TypeError, ValueError, RSILearningError) as exc:
                raise GenerationGovernanceError("rsi_generation_governance_checkpoint_corrupt") from exc
        return history[-1] if history else None

    def inspect(self, generation_id: str) -> tuple[str, dict[str, Any]] | None:
        return deepcopy(self._load(generation_id))

    def _save(self, head: str | None, state: dict[str, Any]) -> str:
        self._check()
        return self.ledger.write_controller_checkpoint(self._namespace(state["intent"]["generation_id"]),
                                                        state, expected_sha256=head)

    def _record(self, state: Mapping[str, Any], item: MemoryItem) -> MemoryAdmissionRecord | None:
        intent = state["intent"]
        admission_id = intent["admissions"][item.memory_id]
        history = self.governance.history(admission_id)
        previous = None
        report = self._report(state["report"], self._request(state)) if state["report"] else None
        reason = "generation:" + state["intent_sha256"]
        for index, record in enumerate(history):
            if (record.revision != index or record.record_sha256 != record.digest()
                    or record.parent_record_sha256 != (previous.record_sha256 if previous else None)
                    or record.admission_id != admission_id
                    or record.memory_snapshot_sha256 != MemorySnapshot.from_dict(intent["current_memory"]).digest()
                    or record.parent_snapshot_sha256 != MemorySnapshot.from_dict(intent["parent_memory"]).digest()
                    or record.memory_item_sha256 != _item_digest(item) or record.source_episode_id != item.episode_id
                    or record.verifier_receipt_sha256 != item.receipt_sha256 or record.scope != self.scope
                    or dict(record.compatibility) != json.loads(self._compatibility) or record.episode_outcome != "pass"):
                _fail("admission_drift")
            if record.state == "revoked":
                validations = [self._report(entry["report"], self._request(state, key))
                               for key, entry in state["validations"].items() if entry["report"] is not None]
                if (previous is None or previous.state != "active"
                        or not any(not entry.promotion_eligible and
                                   record.reason == "transfer_regression_rejected:" + entry.report_sha256
                                   for entry in validations)):
                    _fail("revoked")
            elif index >= len(_STAGES) or record.state != _STAGES[index]:
                _fail("admission_state_drift")
            elif record.state in {"approved", "active"}:
                if (report is None or not report.promotion_eligible or not record.regression_passed
                        or record.holdout_receipt_sha256 != report.holdout_receipt_sha256
                        or record.baseline_receipt_sha256 != report.baseline_receipt_sha256
                        or record.reason != reason + ":report:" + report.report_sha256):
                    _fail("admission_evidence_drift")
            elif (record.reason != reason or record.regression_passed
                  or record.holdout_receipt_sha256 is not None or record.baseline_receipt_sha256 is not None):
                _fail("admission_evidence_drift")
            previous = record
        if item.memory_id in state["heads"] and not any(
            entry.record_sha256 == state["heads"][item.memory_id] for entry in history
        ):
            _fail("admission_head_drift")
        return previous

    def validate(self, snapshot: MemorySnapshot) -> None:
        self._check()
        self._validate(snapshot, frozenset(), set())

    def _validate(self, snapshot: MemorySnapshot, ancestors: frozenset[str], validated: set[str]) -> None:
        if not isinstance(snapshot, MemorySnapshot):
            _fail("snapshot_invalid")
        if not snapshot.items or snapshot.digest() in validated:
            return
        generation_id = self._snapshot_generation(snapshot)
        if generation_id in ancestors or len(ancestors) >= self.policy.max_lineage_depth:
            _fail("lineage_invalid")
        checkpoint = self._load(generation_id)
        if checkpoint is None:
            _fail("snapshot_unregistered")
        _head, state = checkpoint
        if state["phase"] != "active":
            _fail("inactive")
        if MemorySnapshot.from_dict(state["intent"]["current_memory"]).to_dict() != snapshot.to_dict():
            _fail("snapshot_drift")
        for item in snapshot.items:
            record = self._record(state, item)
            if record is None or record.state != "active" or state["heads"].get(item.memory_id) != record.record_sha256:
                _fail("inactive")
            origin = state["intent"]["provenance"][item.memory_id]
            if origin["kind"] == "inherited":
                parent = MemorySnapshot.from_dict(state["intent"]["parent_memory"])
                self._validate(parent, ancestors | {generation_id}, validated)
                parent_state = self._load(self._snapshot_generation(parent))[1]
                if origin["parent_admission_id"] != parent_state["intent"]["admissions"][item.memory_id]:
                    _fail("lineage_invalid")
                source = self.governance.get(origin["parent_admission_id"])
                if source is None or source.state != "active" or source.record_sha256 != origin["parent_admission_sha256"]:
                    _fail("lineage_inactive")
        self._check()
        validated.add(snapshot.digest())

    def _intent(self, generation_id: str, current: MemorySnapshot, parent: MemorySnapshot,
                proofs: Mapping[str, VerifierDecision], runner_fingerprint: str,
                runner_manifest: list[dict[str, str]] | None, runner_parent: dict[str, Any] | None) -> dict[str, Any]:
        self.validate(parent)
        if (current.parent_snapshot_sha256 != parent.digest() or current.digest() == parent.digest()
                or len(current.items) > self.policy.max_items):
            _fail("snapshot_parent_drift")
        old = {item.memory_id: item for item in parent.items}
        new_ids = {item.memory_id for item in current.items} - set(old)
        if not isinstance(proofs, Mapping) or set(proofs) != new_ids:
            _fail("proof_mapping_incomplete")
        parent_state = self._load(self._snapshot_generation(parent))[1] if parent.items else None
        provenance = {}
        for item in current.items:
            if item.memory_id in old:
                if item.to_dict() != old[item.memory_id].to_dict():
                    _fail("inherited_item_drift")
                admission_id = parent_state["intent"]["admissions"][item.memory_id]
                source = self.governance.get(admission_id)
                provenance[item.memory_id] = {"kind": "inherited", "parent_admission_id": admission_id,
                                             "parent_admission_sha256": source.record_sha256}
            else:
                self._source(item, proofs[item.memory_id])
                provenance[item.memory_id] = {"kind": "verified", "verifier": proofs[item.memory_id].to_dict()}
        depth = (parent_state["intent"]["lineage_depth"] if parent_state else 0) + 1
        if depth > self.policy.max_lineage_depth:
            _fail("lineage_limit")
        return {"generation_id": generation_id, "coordinator_sha256": self._fingerprint,
                "parent_memory": parent.to_dict(), "current_memory": current.to_dict(),
                "runner_fingerprint": runner_fingerprint, "runner_manifest": runner_manifest,
                "runner_parent": runner_parent,
                "lineage_depth": depth,
                "provenance": provenance,
                "admissions": {item.memory_id: "generation-item:" + _digest({"generation": generation_id,
                              "snapshot": current.digest(), "item": item.memory_id}) for item in current.items}}

    def _result(self, state: Mapping[str, Any], *, report: TransferRegressionReport | None = None) -> GenerationAdmissionResult:
        request = self._request(state)
        effective = request.current_memory if state["phase"] == "active" else request.parent_memory
        self.validate(effective)
        return GenerationAdmissionResult(request.generation_id, state["phase"], effective, request.admissions, report)

    def _shadow(self, head: str, state: dict[str, Any]) -> str:
        request = self._request(state)
        for item in request.current_memory.items:
            record = self._record(state, item)
            if record is None:
                self._check()
                record = self.governance.create(MemoryAdmissionRecord(
                    request.admissions[item.memory_id], request.current_memory.digest(), _item_digest(item),
                    item.episode_id, item.receipt_sha256, request.parent_memory.digest(), self.scope,
                    json.loads(self._compatibility), reason="generation:" + state["intent_sha256"],
                ))
                state["heads"][item.memory_id] = record.record_sha256
                head = self._save(head, state)
            while record.state != "shadow":
                if record.state not in _STAGES[:3]:
                    _fail("admission_state_drift")
                self._check()
                record = self.governance.transition(record.admission_id, _STAGES[_STAGES.index(record.state) + 1],
                                                     expected_record_sha256=record.record_sha256)
                state["heads"][item.memory_id] = record.record_sha256
                head = self._save(head, state)
            if state["heads"].get(item.memory_id) != record.record_sha256:
                state["heads"][item.memory_id] = record.record_sha256
                head = self._save(head, state)
        state["phase"] = "holdout"
        return self._save(head, state)

    def _finish(self, head: str, state: dict[str, Any], report: TransferRegressionReport,
                validation_id: str | None = None) -> GenerationAdmissionResult:
        if validation_id is None:
            if state["report"] is None:
                state["report"] = self.serialize_report(report)
                head = self._save(head, state)
            if report.promotion_eligible:
                for item in self._request(state).current_memory.items:
                    record = self._record(state, item)
                    if record is None:
                        _fail("admission_missing")
                    if record.state != "active":
                        self._check()
                        record = self.promotion.activate(
                            record.admission_id, report, expected_record_sha256=record.record_sha256,
                            compatibility=json.loads(self._compatibility),
                            approval_reason="generation:" + state["intent_sha256"] + ":report:" + report.report_sha256,
                        )
                    if state["heads"].get(item.memory_id) != record.record_sha256:
                        state["heads"][item.memory_id] = record.record_sha256
                        head = self._save(head, state)
                state["phase"] = "active"
            else:
                state["phase"] = "rejected"
        else:
            validation = state["validations"][validation_id]
            if validation["report"] is None:
                validation.update(status="completed", report=self.serialize_report(report))
                head = self._save(head, state)
            if report.promotion_eligible:
                state["phase"] = "active"
            else:
                for item in self._request(state).current_memory.items:
                    record = self._record(state, item)
                    if record is None:
                        _fail("admission_missing")
                    self._check()
                    record = self.promotion.quarantine_failed_report(
                        record.admission_id, report, expected_record_sha256=record.record_sha256,
                    )
                    if state["heads"].get(item.memory_id) != record.record_sha256:
                        state["heads"][item.memory_id] = record.record_sha256
                        head = self._save(head, state)
                state["phase"] = "quarantined"
            state["pending_validation"] = None
        self._save(head, state)
        return self._result(state, report=report)

    def _invoke(self, head: str, state: dict[str, Any], runner: RegressionRunner,
                validation_id: str | None = None) -> GenerationAdmissionResult:
        request = self._request(state, validation_id)
        fingerprint = (state["intent"]["runner_fingerprint"] if validation_id is None
                       else state["validations"][validation_id]["runner_fingerprint"])
        callback_id = "holdout" if validation_id is None else "revalidation:" + validation_id
        binding = {"request": request.to_dict(), "runner_fingerprint": fingerprint}

        def check() -> None:
            self._check()
            self.validate(request.parent_memory)
            if self._runner_fingerprint(runner) != fingerprint:
                _fail("runner_drift")

        def call() -> dict[str, Any]:
            check()
            report = runner(request)
            check()
            result = self.serialize_report(report)
            self._report(result, request)
            return result

        try:
            check()
            result = self.callbacks.invoke(self._namespace(request.generation_id), callback_id,
                                           binding=binding, call=call,
                                           validate=lambda value: self._report(value, request))
        except Exception as exc:
            callback = self.callbacks.inspect(self._namespace(request.generation_id), callback_id)
            if callback is None or callback[1]["status"] != "started":
                raise
            if validation_id is None and state["phase"] != "unknown":
                state["phase"] = "unknown"
                self._save(head, state)
            if isinstance(exc, RSILearningError) and exc.code != "rsi_callback_reconcile_required":
                raise
            return self._result(state)
        check()
        return self._finish(head, state, self._report(result, request), validation_id)

    def admit_generation(self, generation_id: str, current_memory: MemorySnapshot,
                         parent_memory: MemorySnapshot, source_verifiers: Mapping[str, VerifierDecision],
                         regression_runner: RegressionRunner) -> GenerationAdmissionResult:
        namespace = self._namespace(generation_id)
        runner_parent = self._parent_shape(self._runner_config(regression_runner).get("parent"))
        account = self._parent(runner_parent)
        with (account.guard() if account is not None else nullcontext()), self.ledger.controller_lock(namespace):
            fingerprint = self._runner_fingerprint(regression_runner)
            intent = self._intent(generation_id, current_memory, parent_memory, source_verifiers,
                                  fingerprint, self._runner_manifest(regression_runner, fingerprint), runner_parent)
            checkpoint = self._load(generation_id)
            if checkpoint is None:
                self._index(intent)
                state = {"protocol": "rsi-generation-v1", "intent": intent, "intent_sha256": _digest(intent),
                         "phase": "admitting", "heads": {}, "report": None, "validations": {},
                         "pending_validation": None}
                head = self._save(None, state)
            else:
                head, state = checkpoint
                if state["intent"] != intent:
                    _fail("intent_drift")
                self._index(intent)
            if state["phase"] in {"active", "rejected", "quarantined", "revalidating"}:
                return self._result(state, report=self._report(state["report"], self._request(state)))
            if state["phase"] == "admitting":
                head = self._shadow(head, state)
            return self._invoke(head, state, regression_runner)

    def revalidate_generation(self, generation_id: str, validation_id: str,
                              regression_runner: RegressionRunner) -> GenerationAdmissionResult:
        _identifier(validation_id, "validation_id")
        runner_parent = self._parent_shape(self._runner_config(regression_runner).get("parent"))
        account = self._parent(runner_parent)
        with (account.guard() if account is not None else nullcontext()), self.ledger.controller_lock(self._namespace(generation_id)):
            checkpoint = self._load(generation_id)
            if checkpoint is None:
                _fail("generation_missing")
            head, state = checkpoint
            fingerprint = self._runner_fingerprint(regression_runner)
            manifest = self._runner_manifest(regression_runner, fingerprint)
            if state["pending_validation"] not in {None, validation_id}:
                _fail("revalidation_pending")
            known = state["validations"].get(validation_id)
            if known is not None:
                if (known["runner_fingerprint"] != fingerprint or known["runner_manifest"] != manifest
                        or known["runner_parent"] != runner_parent):
                    _fail("runner_drift")
                if known["status"] == "completed" and state["phase"] in {"active", "quarantined"}:
                    return self._result(state, report=self._report(known["report"], self._request(state, validation_id)))
            else:
                if state["phase"] != "active":
                    _fail("revalidation_pending")
                self.validate(self._request(state).current_memory)
                state["validations"][validation_id] = {"runner_fingerprint": fingerprint,
                                                         "runner_manifest": manifest,
                                                         "runner_parent": runner_parent,
                                                         "status": "started", "report": None}
                state["phase"] = "revalidating"
                state["pending_validation"] = validation_id
                head = self._save(head, state)
            return self._invoke(head, state, regression_runner, validation_id)

    def reconcile_holdout(self, generation_id: str, *, expected_checkpoint_sha256: str,
                          report: TransferRegressionReport, evidence: Mapping[str, Any],
                          validation_id: str | None = None) -> GenerationAdmissionResult:
        """Register a bound, already-observed local report; never dispatch a callback."""
        initial = self._load(generation_id)
        if initial is None:
            _fail("generation_missing")
        try:
            runner_parent = (initial[1]["intent"]["runner_parent"] if validation_id is None
                             else initial[1]["validations"][validation_id]["runner_parent"])
        except KeyError as exc:
            raise GenerationGovernanceError("rsi_generation_governance_validation_missing") from exc
        account = self._parent(runner_parent)
        with (account.guard() if account is not None else nullcontext()), self.ledger.controller_lock(self._namespace(generation_id)):
            checkpoint = self._load(generation_id)
            if checkpoint is None:
                _fail("generation_missing")
            head, state = checkpoint
            request = self._request(state, validation_id)
            self.validate(request.parent_memory)
            if validation_id is None:
                fingerprint = state["intent"]["runner_fingerprint"]
                callback_id = "holdout"
            else:
                if validation_id not in state["validations"]:
                    _fail("validation_missing")
                if state["pending_validation"] not in {None, validation_id}:
                    _fail("revalidation_pending")
                fingerprint = state["validations"][validation_id]["runner_fingerprint"]
                callback_id = "revalidation:" + validation_id
            loaded_parent = (state["intent"]["runner_parent"] if validation_id is None
                             else state["validations"][validation_id]["runner_parent"])
            if loaded_parent != runner_parent:
                _fail("parent_budget_identity_drift")
            result = self.serialize_report(report)
            binding = {"request": request.to_dict(), "runner_fingerprint": fingerprint}
            self._report(result, request)
            clean_evidence = self.callbacks.validate_evidence(binding, result, evidence)
            callback = self.callbacks.inspect(self._namespace(generation_id), callback_id)
            if callback is None:
                raise RSILearningError("rsi_callback_not_started")
            callback_head, callback_state = callback
            self.callbacks._binding(callback_state, binding)
            if callback_state["status"] == "completed":
                if expected_checkpoint_sha256 not in {callback_head, callback_state["started_checkpoint_sha256"]}:
                    raise RSILearningError("rsi_callback_checkpoint_conflict")
                if (callback_state["reconciliation"] != clean_evidence
                        or callback_state["result_sha256"] != self.callbacks.digest(result)):
                    raise RSILearningError("rsi_callback_reconcile_conflict")
            elif expected_checkpoint_sha256 != callback_head:
                raise RSILearningError("rsi_callback_checkpoint_conflict")
            if account is not None:
                if account.identity() != runner_parent:
                    _fail("parent_budget_identity_drift")
                scope = self._namespace(generation_id)
                reservation = {"binding_sha256": self.callbacks.digest(binding),
                               "result_sha256": self.callbacks.digest(result),
                               "evidence_sha256": self.callbacks.digest(clean_evidence)}
                if callback_state["status"] == "completed":
                    event_id = self.callbacks.digest({"scope": scope, "callback_id": callback_id, "reconcile": True})
                    receipt = {"binding_sha256": self.callbacks.digest(reservation), "kind": "reconcile"}
                    parent_state = self.ledger.controller_checkpoint(account.run_id)[1]
                    if parent_state.get("external_budget_reservations", {}).get(event_id) != receipt:
                        _fail("parent_reconciliation_missing")
                else:
                    account.reserve(scope, callback_id, reservation, reconcile=True)
            self.callbacks.reconcile(self._namespace(generation_id), callback_id,
                                     expected_checkpoint_sha256=expected_checkpoint_sha256,
                                     binding=binding, result=result, evidence=evidence,
                                     validate=lambda value: self._report(value, request))
            if state["phase"] in {"active", "rejected", "quarantined"}:
                return self._result(state, report=self._report(result, request))
            return self._finish(head, state, self._report(result, request), validation_id)


__all__ = ["GenerationAdmissionResult", "GenerationGovernanceError", "GenerationGovernancePolicy",
           "GenerationRegressionRequest", "RSIGovernanceCoordinator"]
