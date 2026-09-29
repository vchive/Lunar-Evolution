"""Durable pre-execution reservations for native RSI evaluation and transfer.

A scope belongs to one controller episode or frozen transfer panel.  Its append-only
reservations and budget counters are persisted together before an external stage runs.
Pending intents never authorize replay; retained callers must use their existing read-only
recovery path.  The hook has no effect outside an explicitly installed RSI scope.
"""
from __future__ import annotations

import copy
import hashlib
import threading
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_budget import RSIRunBudget
from .rsi_learning import RSILearningError

_STAGES = {"evaluator", "verifier", "transfer"}
_SCOPE: ContextVar[tuple[DurableStageAccounting, dict[str, Any]] | None] = ContextVar(
    "rsi_stage_scope", default=None,
)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=8 * 1024 * 1024)).hexdigest()


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def validate_stage_state(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"invocations"}:
        raise RSILearningError("rsi_stage_checkpoint_invalid")
    rows = value["invocations"]
    if not isinstance(rows, list):
        raise RSILearningError("rsi_stage_checkpoint_invalid")
    counts = dict.fromkeys(_STAGES, 0)
    seen = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "stage", "identity", "intent_sha256", "evidence",
        }:
            raise RSILearningError("rsi_stage_checkpoint_invalid")
        stage = row["stage"]
        if (type(stage) is not str or stage not in _STAGES
                or not isinstance(row["identity"], Mapping)
                or row["intent_sha256"] != digest({"stage": stage, "identity": row["identity"]})
                or row["intent_sha256"] in seen):
            raise RSILearningError("rsi_stage_checkpoint_invalid")
        evidence = row["evidence"]
        if evidence is not None and (not isinstance(evidence, Mapping)
                                    or set(evidence) != {"receipt_sha256"}
                                    or not _sha(evidence["receipt_sha256"])):
            raise RSILearningError("rsi_stage_checkpoint_invalid")
        counts[stage] += 1
        seen.add(row["intent_sha256"])
    return counts


def validate_stage_history(previous: object, current: object) -> None:
    """Reject erased intents, changed identity and changed completed evidence."""
    old = previous if previous is not None else {"invocations": []}
    new = current if current is not None else {"invocations": []}
    validate_stage_state(old)
    validate_stage_state(new)
    if len(new["invocations"]) < len(old["invocations"]):
        raise RSILearningError("rsi_stage_checkpoint_invalid")
    for before, after in zip(old["invocations"], new["invocations"]):
        if any(before[name] != after[name] for name in ("stage", "identity", "intent_sha256")):
            raise RSILearningError("rsi_stage_checkpoint_invalid")
        if before["evidence"] is not None and before["evidence"] != after["evidence"]:
            raise RSILearningError("rsi_stage_checkpoint_invalid")


class DurableStageAccounting:
    """Mutate caller-owned state and atomically persist its budget and reservation."""

    def __init__(self, state: dict[str, Any], budget_state: dict[str, Any],
                 persist: Callable[[], Any], *, lock: Any = None):
        self.state = state
        self.budget_state = budget_state
        self.persist = persist
        self.lock = lock or threading.RLock()
        self._failed = False
        validate_stage_state(state)
        RSIRunBudget.load(budget_state)

    def reserve(self, stage: str, identity: Mapping[str, Any]) -> dict[str, Any]:
        if self._failed:
            raise RSILearningError("rsi_stage_accounting_poisoned")
        clean = dict(identity)
        pin = digest({"stage": stage, "identity": clean})
        with self.lock:
            validate_stage_state(self.state)
            if any(row["intent_sha256"] == pin for row in self.state["invocations"]):
                raise RSILearningError("rsi_stage_invocation_replay_forbidden")
            old_budget = copy.deepcopy(self.budget_state)
            old_rows = copy.deepcopy(self.state["invocations"])
            budget = RSIRunBudget.load(self.budget_state)
            budget.reserve_stage(stage)
            row = {"stage": stage, "identity": clean, "intent_sha256": pin, "evidence": None}
            self.state["invocations"].append(row)
            try:
                self.persist()
            except Exception:
                self._failed = True
                self.budget_state.clear()
                self.budget_state.update(old_budget)
                self.state["invocations"][:] = old_rows
                raise
            return row

    def complete(self, row: dict[str, Any], receipt_sha256: str) -> None:
        if not _sha(receipt_sha256):
            raise RSILearningError("rsi_stage_evidence_invalid")
        if self._failed:
            raise RSILearningError("rsi_stage_accounting_poisoned")
        with self.lock:
            if not any(value is row for value in self.state["invocations"]):
                raise RSILearningError("rsi_stage_intent_conflict")
            evidence = {"receipt_sha256": receipt_sha256}
            if row["evidence"] is not None:
                if row["evidence"] != evidence:
                    raise RSILearningError("rsi_stage_evidence_conflict")
                return
            previous = row["evidence"]
            row["evidence"] = evidence
            try:
                self.persist()
            except Exception:
                self._failed = True
                row["evidence"] = previous
                raise


@contextmanager
def stage_accounting(accounting: DurableStageAccounting, owner: Mapping[str, Any]):
    """Install thread-local accounting; parallel episodes never share their identity."""
    token = _SCOPE.set((accounting, dict(owner)))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def accounting_available() -> bool:
    return _SCOPE.get() is not None


def validate_evaluator_intent(row: Mapping[str, Any], *, evaluator_sha256: str) -> None:
    """Reopen completed official evidence; inspecting it cannot launch an evaluator."""
    from pathlib import Path

    from .candidate_evaluation import inspect_candidate_evaluation

    operation = row["identity"].get("operation")
    if not isinstance(operation, Mapping) or set(operation) != {
        "admission_sha256", "plan_sha256", "completion_sha256", "evaluator_sha256", "evaluation_root",
    } or operation["evaluator_sha256"] != evaluator_sha256:
        raise RSILearningError("rsi_stage_evaluator_binding_invalid")
    if any(not _sha(operation[key]) for key in (
        "admission_sha256", "plan_sha256", "completion_sha256", "evaluator_sha256",
    )) or type(operation["evaluation_root"]) is not str:
        raise RSILearningError("rsi_stage_evaluator_binding_invalid")
    if row["evidence"] is None:
        return
    root = Path(operation["evaluation_root"])
    if not root.is_absolute() or root.is_symlink():
        raise RSILearningError("rsi_stage_evaluator_binding_invalid")
    entries = list(root.iterdir())
    if len(entries) != 1 or entries[0].is_symlink() or not entries[0].is_dir():
        raise RSILearningError("rsi_stage_evaluator_binding_invalid")
    retained = inspect_candidate_evaluation(
        entries[0], expected_evaluation_sha256=row["evidence"]["receipt_sha256"],
    )
    binding = retained.to_dict()["binding"]
    if any(binding[key] != operation[name] for key, name in (
        ("admission_sha256", "admission_sha256"), ("workspace_plan_sha256", "plan_sha256"),
        ("completion_sha256", "completion_sha256"), ("evaluator_fingerprint", "evaluator_sha256"),
    )):
        raise RSILearningError("rsi_stage_evaluator_binding_invalid")


def reserve_stage(stage: str, identity: Mapping[str, Any]) -> Callable[[str], None]:
    """Persist the intent before work; return a completion callback binding its receipt."""
    scope = _SCOPE.get()
    if scope is None:
        return lambda receipt_sha256: None
    accounting, owner = scope
    row = accounting.reserve(stage, {"owner": owner, "operation": dict(identity)})
    return lambda receipt_sha256: accounting.complete(row, receipt_sha256)


__all__ = ["DurableStageAccounting", "accounting_available", "reserve_stage", "stage_accounting",
           "validate_evaluator_intent", "validate_stage_history", "validate_stage_state"]
