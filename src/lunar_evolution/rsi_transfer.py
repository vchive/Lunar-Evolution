"""Paired local native evaluation of empty and frozen RSI memory.

This is a bounded measurement adapter. It supplies read-only snapshot contents to a host-owned
candidate factory, uses the exact native independent verifier, and retains both arms' evidence.
A local fixture improvement does not establish production-model or cross-domain generalization.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import _benchmark_files as files
from ._candidate_workspace_io import DirectoryChain
from .bundle_evolution import _ensure_private_directory
from .candidate_evaluation_spec import canonical_json, strict_json
from .evolution import CandidateDraft
from .rsi_actor import _callable_identity
from .rsi_budget import RSIRunBudget
from .rsi_controller import EpisodeExecution, PracticeEpisodeRunner
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT,
    MemorySnapshot,
    PracticeEpisode,
    ReadOnlyMemorySnapshot,
    RSILearningError,
    VerifierCheck,
    VerifierDecision,
)
from .rsi_native import (
    _PROTOCOL as _NATIVE_PROTOCOL,
)
from .rsi_native import (
    NativeEvaluationProfile,
    NativeIndependentVerifier,
    NativePopulationGateway,
)
from .rsi_stage_accounting import (
    DurableStageAccounting,
    stage_accounting,
    validate_evaluator_intent,
    validate_stage_state,
)

_PROTOCOL = "lunar-rsi-native-transfer-v1"
_MAX = 2 * 1024 * 1024
_MAX_INTENT = 128 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")


def _fail(code: str) -> None:
    raise RSILearningError("rsi_transfer_" + code)


def _json(value: object) -> bytes:
    return canonical_json(value, maximum=_MAX)


def _sha(value: object) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _read(path: Path) -> dict:
    raw = files.read_regular_file(path, _MAX)
    value = strict_json(raw, maximum=_MAX)
    if not isinstance(value, dict) or _json(value) != raw:
        _fail("record_invalid")
    return value


def _write_new(path: Path, value: dict) -> None:
    """Durably retain one bounded panel; incomplete records never authorize a rerun."""
    content = _json(value)
    chain = DirectoryChain(path.parent, "rsi_transfer_directory_changed")
    descriptor = None
    try:
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=chain.fd)
        os.fsync(chain.fd)
        view = memoryview(content)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                _fail("record_write_failed")
            view = view[count:]
        os.fsync(descriptor)
        chain.check()
        os.fsync(chain.fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        chain.close()


def _write_replace(path: Path, value: dict) -> None:
    """Replace a private JSON record with fsync and no-follow parent checks."""
    content = _json(value)
    chain = DirectoryChain(path.parent, "rsi_transfer_directory_changed")
    temporary = None
    try:
        name = f".{path.name}.tmp-{os.getpid()}"
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=chain.fd)
        temporary = path.parent / name
        try:
            view = memoryview(content)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    _fail("record_write_failed")
                view = view[count:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        chain.check()
        os.replace(temporary, path)
        os.fsync(chain.fd)
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
        chain.close()


@dataclass(frozen=True)
class NativeTransferTask:
    """Host-declared fixed local task, with one profile and budget shared by both arms."""

    task_id: str
    profile: NativeEvaluationProfile
    direction: str = "maximize"
    budget: tuple[tuple[str, Any], ...] = ()
    charter: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self):
        if type(self.task_id) is not str or _ID.fullmatch(self.task_id) is None:
            _fail("task_id_invalid")
        if not isinstance(self.profile, NativeEvaluationProfile):
            _fail("profile_invalid")
        if self.direction not in {"maximize", "minimize"}:
            _fail("direction_invalid")
        for value in (self.budget, self.charter):
            if type(value) is not tuple or len(value) > 24:
                _fail("settings_invalid")
            mapping = dict(value)
            if len(mapping) != len(value) or any(type(key) is not str for key in mapping):
                _fail("settings_invalid")
            canonical_json(mapping, maximum=_MAX_INTENT)
        if set(dict(self.charter)) & {"curriculum_enabled", "memory_write_enabled"}:
            _fail("charter_reserved")

    def to_dict(self) -> dict:
        p = self.profile
        return {"task_id": self.task_id, "profile_sha256": p.fingerprint(),
                "contract_sha256": p.contract.digest(), "evaluator_sha256": p.pipeline.evaluator.digest(),
                "environment_sha256": p.pipeline.environment_sha256,
                "direction": self.direction, "budget": dict(self.budget), "charter": dict(self.charter)}


def _execution_dict(value: EpisodeExecution) -> dict:
    return {"episode": value.episode.to_record_dict(), "request": value.request.to_dict(),
            "result": value.result.to_dict(), "verifier": value.verifier.to_dict()}


def _execution(value: dict) -> EpisodeExecution:
    if not isinstance(value, dict) or set(value) != {"episode", "request", "result", "verifier"}:
        _fail("execution_invalid")
    episode = PracticeEpisode.from_dict(value["episode"])
    request = SolverRequest.from_dict(value["request"])
    result = SolverResult.from_dict(value["result"])
    raw = value["verifier"]
    verifier = VerifierDecision(**{**raw, "checks": tuple(VerifierCheck(**item) for item in raw["checks"])})
    if (episode.episode_id != request.episode_id or episode.request_sha256 != request.digest()
            or result.request_sha256 != request.digest() or result.episode_id != request.episode_id
            or verifier.episode_id != request.episode_id
            or episode.status != result.status or episode.trace_events != result.trace_events
            or episode.solver_fingerprint != _sha({"solver_id": request.solver_id, "settings": request.solver_settings})
            or (episode.status == "completed" and episode.verifier != verifier)):
        _fail("execution_identity_mismatch")
    for name in ("contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256", "solver_id"):
        if getattr(episode, name) != getattr(request, name):
            _fail("execution_identity_mismatch")
    for name in ("candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256",
                 "trace_digest", "candidate_source_sha256", "dependency_sha256", "actor_fingerprint"):
        if getattr(episode, name) != getattr(result, name):
            _fail("execution_result_mismatch")
    if episode.status != "completed" and episode.terminal_reason != result.terminal_reason:
        _fail("execution_result_mismatch")
    return EpisodeExecution(episode, request, result, verifier)


def _outcome(baseline: EpisodeExecution, frozen: EpisodeExecution, direction: str) -> dict:
    """Only independently verified scores are eligible for arithmetic."""
    if not baseline.passed or not frozen.passed:
        return {"effect": "unresolved", "oriented_score_delta": None,
                "baseline_verified": baseline.passed, "frozen_verified": frozen.passed}
    scores = (baseline.result.solver_score, frozen.result.solver_score)
    if any(isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) for score in scores):
        _fail("official_score_missing")
    delta = float(scores[1]) - float(scores[0])
    if direction == "minimize":
        delta = -delta
    if not math.isfinite(delta):
        _fail("official_score_overflow")
    return {"effect": "improved" if delta > 0 else "regressed" if delta < 0 else "unchanged",
            "oriented_score_delta": delta, "baseline_verified": True, "frozen_verified": True}


def _summary(rows: list[dict]) -> dict:
    effects = {row["outcome"]["effect"] for row in rows}
    effect = ("unresolved" if "unresolved" in effects else "mixed" if {"improved", "regressed"} <= effects
              else "improved" if "improved" in effects else "regressed" if "regressed" in effects else "unchanged")
    return {"effect": effect, "task_count": len(rows),
            "baseline_verified": sum(row["outcome"]["baseline_verified"] for row in rows),
            "frozen_verified": sum(row["outcome"]["frozen_verified"] for row in rows)}


@dataclass(frozen=True)
class FrozenTransferResult:
    comparison_id: str
    status: str
    effect: str
    receipt_sha256: str | None
    receipt_path: Path | None
    task_count: int
    baseline_verified: int = 0
    frozen_verified: int = 0


class _AccountingVerifier:
    """Transfer-local verifier wrapper; reserves before verifier side effects."""
    def __init__(self, verifier, *, comparison_id: str, task_id: str, arm: str):
        self._verifier = verifier
        self._owner = {"comparison_id": comparison_id, "task_id": task_id, "arm": arm}

    def fingerprint(self):
        return self._verifier.fingerprint()

    def verify(self, episode, request, result):
        from .rsi_stage_accounting import reserve_stage
        done = reserve_stage("verifier", {"episode_id": request.episode_id,
            "request_sha256": request.digest(), "verifier_fingerprint": self.fingerprint()})
        decision = self._verifier.verify(episode, request, result)
        done(decision.receipt_sha256)
        return decision

    def validate_retained(self, *args, **kwargs):
        return self._verifier.validate_retained(*args, **kwargs)


class FrozenMemoryTransferBenchmark:
    """Measure one fixed local panel and reopen terminal evidence without launching again."""

    def __init__(self, draft_factory: Callable[[SolverRequest, ReadOnlyMemorySnapshot], CandidateDraft],
                 workspace_root: str | Path, *, actor_fingerprint: str):
        if not callable(draft_factory):
            raise TypeError("draft_factory must be callable")
        if type(actor_fingerprint) is not str or re.fullmatch(r"[0-9a-f]{64}", actor_fingerprint) is None:
            _fail("actor_fingerprint_invalid")
        self.draft_factory = draft_factory
        self.workspace_root = files.absolute_path(workspace_root)
        self.actor_fingerprint = actor_fingerprint

    def fingerprint(self) -> str:
        return _sha({"protocol": _PROTOCOL, "workspace_root": str(self.workspace_root),
                     "actor_fingerprint": self.actor_fingerprint,
                     "draft_factory": _callable_identity(self.draft_factory)})

    def _request(self, identity: dict, task: NativeTransferTask, arm: str, snapshot: MemorySnapshot) -> SolverRequest:
        episode_id = "transfer-" + _sha({"comparison": identity, "task": task.task_id, "arm": arm})[:32]
        # Each actor receives a fresh copy of the persisted charter/budget. A nested setting
        # cannot mutate the intent or silently change the other arm's task through shared refs.
        fixed = strict_json(_json(next(item for item in identity["tasks"] if item["task_id"] == task.task_id)))
        return SolverRequest.build(
            episode_id=episode_id, contract_sha256=fixed["contract_sha256"],
            evaluator_sha256=fixed["evaluator_sha256"],
            environment_sha256=fixed["environment_sha256"],
            memory_snapshot_sha256=snapshot.digest(), solver_id="native_population",
            budget=fixed["budget"], practice_charter={**fixed["charter"],
                "curriculum_enabled": False, "memory_write_enabled": False},
        )

    def _adapter(self, task: NativeTransferTask, root: Path, snapshots: dict[str, MemorySnapshot]):
        def generate(request):
            snapshot = snapshots.get(request.memory_snapshot_sha256)
            if snapshot is None:
                _fail("memory_snapshot_mismatch")
            before = snapshot.digest()
            candidate = self.draft_factory(request, ReadOnlyMemorySnapshot(snapshot))
            if snapshot.digest() != before:
                _fail("memory_snapshot_changed")
            return candidate
        gateway = NativePopulationGateway(task.profile, generate, root,
                                          actor_fingerprint=self.fingerprint())
        return gateway, NativeIndependentVerifier(task.profile, root)

    def compare(self, *, comparison_id: str, tasks: Sequence[NativeTransferTask],
                snapshot: MemorySnapshot, budget: Mapping[str, Any] | None = None) -> FrozenTransferResult:
        if type(comparison_id) is not str or _ID.fullmatch(comparison_id) is None:
            _fail("comparison_id_invalid")
        if not isinstance(snapshot, MemorySnapshot) or not snapshot.items:
            _fail("approved_snapshot_required")
        tasks = tuple(tasks)
        if not tasks or len(tasks) > 16 or any(not isinstance(task, NativeTransferTask) for task in tasks):
            _fail("tasks_invalid")
        if len({task.task_id for task in tasks}) != len(tasks):
            _fail("task_duplicate")
        # The host must intentionally authorize portability; otherwise a memory created for
        # an incompatible solver/contract would be silently relabeled as transferred evidence.
        for item in snapshot.items:
            if "native_population" not in item.compatible_solvers:
                _fail("memory_solver_incompatible")
            if item.compatible_contracts and any(task.profile.contract.digest() not in item.compatible_contracts for task in tasks):
                _fail("memory_contract_incompatible")
        identity = {"protocol": _PROTOCOL, "comparison_id": comparison_id,
                    "benchmark_fingerprint": self.fingerprint(), "tasks": [task.to_dict() for task in tasks],
                    "snapshot": snapshot.to_dict(), "baseline": EMPTY_MEMORY_SNAPSHOT.to_dict()}
        if budget is not None:
            if not isinstance(budget, Mapping):
                _fail("budget_invalid")
            try:
                stage_budget = dict(budget)
                budget_state = RSIRunBudget.create(stage_budget).state
            except RSILearningError:
                _fail("budget_invalid")
            identity["stage_budget"] = stage_budget
        else:
            budget_state = None
        # Bound the full panel before executing or writing any state.
        identity = strict_json(canonical_json(identity, maximum=_MAX_INTENT))
        _ensure_private_directory(Path(self.workspace_root.anchor), tuple(self.workspace_root.parts[1:]))
        root = _ensure_private_directory(self.workspace_root, ("comparisons", comparison_id))
        intent, receipt = root / "intent.json", root / "comparison.json"
        if intent.exists() or intent.is_symlink():
            if _read(intent) != identity:
                _fail("comparison_identity_changed")
            if not receipt.exists():
                sidecar = root / "stage-accounting.json"
                if sidecar.exists() or sidecar.is_symlink():
                    retained = _read(sidecar)
                    if set(retained) != {"budget", "stages"}:
                        _fail("stage_accounting_invalid")
                    try:
                        validate_stage_state(retained["stages"])
                        budget_state = RSIRunBudget.load(retained["budget"])
                        budget_state.assert_matches(identity.get("stage_budget"))
                    except RSILearningError:
                        _fail("stage_accounting_invalid")
                return FrozenTransferResult(comparison_id, "unknown", "unresolved", None, None, len(tasks))
            return self._resume(root, identity, tasks, snapshot)
        if receipt.exists() or receipt.is_symlink():
            _fail("intent_missing")
        _write_new(intent, identity)
        accounting = None
        if budget_state is not None:
            accounting_path = root / "stage-accounting.json"
            stage_state = {"invocations": []}
            def persist_stage():
                _write_replace(accounting_path, {"budget": budget_state, "stages": stage_state})
            accounting = DurableStageAccounting(stage_state, budget_state, persist_stage)
            accounting.reserve("transfer", {"comparison_id": comparison_id, "identity_sha256": _sha(identity)})
        snapshots = {EMPTY_MEMORY_SNAPSHOT.digest(): EMPTY_MEMORY_SNAPSHOT, snapshot.digest(): snapshot}
        rows = []
        for task in tasks:
            task_root = _ensure_private_directory(root, ("tasks", task.task_id))
            gateway, verifier = self._adapter(task, task_root, snapshots)
            arms = []
            for arm, memory in (("baseline", EMPTY_MEMORY_SNAPSHOT), ("frozen", snapshot)):
                request = self._request(identity, task, arm, memory)
                episode = PracticeEpisode(request.episode_id, comparison_id, request.contract_sha256,
                                          request.evaluator_sha256, request.environment_sha256,
                                          memory.digest(), request.solver_id, "planned", episode_kind="target")
                scoped_verifier = verifier if accounting is None else _AccountingVerifier(
                    verifier, comparison_id=comparison_id, task_id=task.task_id, arm=arm,
                )
                runner = PracticeEpisodeRunner(gateway, scoped_verifier)
                if accounting is None:
                    execution = runner.run(episode, request)
                else:
                    with stage_accounting(accounting, {
                        "comparison_id": comparison_id, "task_id": task.task_id, "arm": arm,
                    }):
                        execution = runner.run(episode, request)
                arms.append(execution)
            if snapshot.to_dict() != identity["snapshot"]:
                _fail("memory_snapshot_changed")
            rows.append({"task_id": task.task_id, "baseline": _execution_dict(arms[0]),
                         "frozen": _execution_dict(arms[1]), "outcome": _outcome(*arms, task.direction)})
        body = {"protocol": _PROTOCOL, "intent_sha256": _sha(identity), "rows": rows, "summary": _summary(rows)}
        payload = {**body, "receipt_sha256": _sha(body)}
        _write_new(receipt, payload)
        if accounting is not None:
            accounting.complete(accounting.state["invocations"][0], payload["receipt_sha256"])
        return self._resume(root, identity, tasks, snapshot)

    def _resume(self, root: Path, identity: dict, tasks: tuple[NativeTransferTask, ...],
                snapshot: MemorySnapshot) -> FrozenTransferResult:
        payload = _read(root / "comparison.json")
        if set(payload) != {"protocol", "intent_sha256", "rows", "summary", "receipt_sha256"}:
            _fail("comparison_record_invalid")
        body = {key: value for key, value in payload.items() if key != "receipt_sha256"}
        if payload["protocol"] != _PROTOCOL or payload["intent_sha256"] != _sha(identity) or _sha(body) != payload["receipt_sha256"]:
            _fail("comparison_receipt_mismatch")
        stage_budget = identity.get("stage_budget")
        accounting_path = root / "stage-accounting.json"
        if stage_budget is not None:
            if not accounting_path.exists() or accounting_path.is_symlink():
                _fail("stage_accounting_missing")
            retained = _read(accounting_path)
            if set(retained) != {"budget", "stages"}:
                _fail("stage_accounting_invalid")
            try:
                budget_state = RSIRunBudget.load(retained["budget"])
                counts = validate_stage_state(retained["stages"])
            except RSILearningError:
                _fail("stage_accounting_invalid")
            budget_state.assert_matches(stage_budget)
            if counts["transfer"] != 1:
                _fail("stage_accounting_invalid")
            if any(budget_state.state["consumed"][name + "_invocations"] != counts[name] for name in ("transfer", "evaluator", "verifier")):
                _fail("stage_accounting_invalid")
            transfer_rows = [row for row in retained["stages"]["invocations"] if row["stage"] == "transfer"]
            if len(transfer_rows) != 1:
                _fail("stage_accounting_invalid")
            transfer_identity = transfer_rows[0]["identity"]
            expected_identity = {
                "comparison_id": identity["comparison_id"],
                "identity_sha256": _sha(identity),
            }
            if transfer_identity != expected_identity:
                _fail("stage_accounting_invalid")
            if transfer_rows[0]["evidence"] is None or transfer_rows[0]["evidence"]["receipt_sha256"] != payload["receipt_sha256"]:
                _fail("stage_accounting_invalid")
        elif accounting_path.exists() or accounting_path.is_symlink():
            _fail("stage_accounting_unexpected")
        rows = payload["rows"]
        if type(rows) is not list or len(rows) != len(tasks):
            _fail("comparison_tasks_mismatch")
        stage_rows = [] if stage_budget is None else retained["stages"]["invocations"]
        snapshots = {EMPTY_MEMORY_SNAPSHOT.digest(): EMPTY_MEMORY_SNAPSHOT, snapshot.digest(): snapshot}
        if stage_budget is not None:
            known_tasks = {task.task_id: task for task in tasks}
            for stage_row in stage_rows:
                if stage_row["stage"] == "transfer":
                    continue
                owner = stage_row["identity"].get("owner")
                if (not isinstance(owner, dict) or owner.get("comparison_id") != identity["comparison_id"]
                        or owner.get("task_id") not in known_tasks or owner.get("arm") not in {"baseline", "frozen"}):
                    _fail("stage_accounting_invalid")
                task = known_tasks[owner["task_id"]]
                if stage_row["stage"] == "verifier":
                    operation = stage_row["identity"].get("operation")
                    if not isinstance(operation, dict) or operation.get("verifier_fingerprint") != self._adapter(task, root / "tasks" / task.task_id, snapshots)[1].fingerprint():
                        _fail("stage_accounting_invalid")
                    continue
                operation = stage_row["identity"].get("operation")
                if (not isinstance(operation, dict) or operation.get("evaluator_sha256") != task.profile.pipeline.evaluator.digest()):
                    _fail("stage_accounting_invalid")
                validate_evaluator_intent(stage_row, evaluator_sha256=task.profile.pipeline.evaluator.digest())
        for task, row in zip(tasks, rows, strict=True):
            if set(row) != {"task_id", "baseline", "frozen", "outcome"} or row["task_id"] != task.task_id:
                _fail("comparison_task_mismatch")
            gateway, verifier = self._adapter(task, root / "tasks" / task.task_id, snapshots)
            arms = []
            for arm_name, memory in (("baseline", EMPTY_MEMORY_SNAPSHOT), ("frozen", snapshot)):
                arm = _execution(row[arm_name])
                if arm.request.to_dict() != self._request(identity, task, arm_name, memory).to_dict():
                    _fail("comparison_arm_identity_mismatch")
                if (arm.episode.run_id != identity["comparison_id"] or arm.episode.episode_kind != "target"
                        or arm.episode.wave != 0 or arm.episode.ordinal != 0
                        or arm.episode.parent_target_episode_id is not None
                        or arm.result.actor_fingerprint != self.fingerprint()
                        or arm.verifier.verifier_fingerprint != verifier.fingerprint()):
                    _fail("comparison_arm_identity_mismatch")
                episode_root = gateway.workspace_root / "episodes" / arm.request.episode_id
                retained = _read(episode_root / "native-result.json")
                if (set(retained) != {"protocol", "request", "result", "candidate_descriptor"}
                        or retained["protocol"] != _NATIVE_PROTOCOL
                        or retained["request"] != arm.request.to_dict()
                        or retained["result"] != arm.result.to_dict()
                        or _read(episode_root / "native-intent.json") != {
                            "protocol": _NATIVE_PROTOCOL, "request": arm.request.to_dict(),
                            "gateway_fingerprint": gateway.fingerprint(),
                        }):
                    _fail("comparison_native_record_mismatch")
                if arm.result.status == "completed":
                    verifier.validate_retained(arm.episode, arm.request, arm.result, arm.verifier)
                elif arm.verifier.outcome == "pass":
                    _fail("comparison_terminal_verifier_invalid")
                if stage_budget is not None:
                    owner_rows = [row for row in stage_rows if row["stage"] == "evaluator" and row["identity"]["owner"].get("task_id") == task.task_id and row["identity"]["owner"].get("arm") == arm_name]
                    expected_receipts = {arm.result.official_evaluation_receipt_sha256}
                    expected_receipts.update(check.receipt_sha256 for check in arm.verifier.checks if check.name in {"official_evaluator", "independent_rerun"} and check.receipt_sha256)
                    observed_receipts = {row["evidence"]["receipt_sha256"] for row in owner_rows if row["evidence"] is not None}
                    if not expected_receipts.issubset(observed_receipts):
                        _fail("stage_accounting_invalid")
                    verifier_rows = [row for row in stage_rows if row["stage"] == "verifier" and row["identity"]["owner"].get("task_id") == task.task_id and row["identity"]["owner"].get("arm") == arm_name]
                    if len(verifier_rows) != 1 or verifier_rows[0]["evidence"] is None or verifier_rows[0]["evidence"]["receipt_sha256"] != arm.verifier.receipt_sha256:
                        _fail("stage_accounting_invalid")
                arms.append(arm)
            if row["outcome"] != _outcome(*arms, task.direction):
                _fail("comparison_outcome_mismatch")
        summary = _summary(rows)
        if payload["summary"] != summary or _read(root / "intent.json") != identity:
            _fail("comparison_summary_mismatch")
        return FrozenTransferResult(identity["comparison_id"], "completed", summary["effect"],
                                    payload["receipt_sha256"], root / "comparison.json", len(tasks),
                                    summary["baseline_verified"], summary["frozen_verified"])


__all__ = ["FrozenMemoryTransferBenchmark", "FrozenTransferResult", "NativeTransferTask"]
