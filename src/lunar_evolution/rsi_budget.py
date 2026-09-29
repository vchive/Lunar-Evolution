"""Durable, fail-closed budget accounting for one RSI controller run."""
from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any

from .rsi_learning import RSILearningError

_COUNTER_LIMITS = {
    "solver_invocations": "max_solver_invocations",
    "practice_episodes": "max_practice_episodes",
    "unknown_retries": "max_unknown_retries",
    "evaluator_invocations": "max_evaluator_invocations",
    "verifier_invocations": "max_verifier_invocations",
    "transfer_invocations": "max_transfer_invocations",
}
_LIMITS = ("max_depth", *_COUNTER_LIMITS.values())
_STAGE_COUNTERS = {
    "evaluator": "evaluator_invocations",
    "verifier": "verifier_invocations",
    "transfer": "transfer_invocations",
}
_LEGACY_COUNTERS = {"solver_invocations", "practice_episodes", "unknown_retries"}
_LEGACY_LIMITS = {"max_depth", "deadline_unix", *(f"max_{name}" for name in _LEGACY_COUNTERS)}


def _limit(value: object, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise RSILearningError(f"rsi_budget_{name}_invalid")
    return value


def _deadline(value: object) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float} or isinstance(value, bool) or not math.isfinite(float(value)):
        raise RSILearningError("rsi_budget_deadline_unix_invalid")
    return float(value)


class RSIRunBudget:
    """Canonical run budget stored in the controller checkpoint.

    Only absolute deadlines are accepted. A relative duration would be recomputed on resume and
    could silently extend an interrupted run.
    """

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self._validate()

    @classmethod
    def create(cls, value: Mapping[str, Any] | None) -> RSIRunBudget:
        if value is not None and not isinstance(value, Mapping):
            raise RSILearningError("rsi_budget_invalid")
        raw = dict(value or {})
        planned = {name: _limit(raw.get(name), name) for name in _LIMITS}
        planned["deadline_unix"] = _deadline(raw.get("deadline_unix"))
        consumed = {name: 0 for name in _COUNTER_LIMITS}
        return cls({
            "planned": planned,
            "consumed": consumed,
            "remaining": {name: planned[limit_name] for name, limit_name in _COUNTER_LIMITS.items()},
        })

    @classmethod
    def load(cls, value: object) -> RSIRunBudget:
        """Restore complete counters; legacy checkpoints require an evidence-based migration.

        Missing stage counters cannot safely become zero because the old checkpoint may have
        already completed evaluator, verifier, or transfer side effects.
        """
        if not isinstance(value, dict):
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        if (set(value) == {"planned", "consumed", "remaining"}
                and isinstance(value["planned"], dict)
                and set(value["planned"]) == _LEGACY_LIMITS
                and isinstance(value["consumed"], dict)
                and set(value["consumed"]) == _LEGACY_COUNTERS
                and isinstance(value["remaining"], dict)
                and set(value["remaining"]) == _LEGACY_COUNTERS):
            raise RSILearningError("rsi_budget_legacy_checkpoint_requires_migration")
        return cls(value)

    def _validate(self) -> None:
        if set(self.state) != {"planned", "consumed", "remaining"}:
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        planned = self.state["planned"]
        consumed = self.state["consumed"]
        remaining = self.state["remaining"]
        if not isinstance(planned, dict) or set(planned) != {*_LIMITS, "deadline_unix"}:
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        if not isinstance(consumed, dict) or set(consumed) != set(_COUNTER_LIMITS):
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        if not isinstance(remaining, dict) or set(remaining) != set(_COUNTER_LIMITS):
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        for name in _LIMITS:
            _limit(planned[name], name)
        _deadline(planned["deadline_unix"])
        for name, limit_name in _COUNTER_LIMITS.items():
            limit = planned[limit_name]
            if type(consumed[name]) is not int or consumed[name] < 0:
                raise RSILearningError("rsi_budget_checkpoint_invalid")
            expected = None if limit is None else limit - consumed[name]
            if ((expected is not None and (expected < 0 or type(remaining[name]) is not int))
                    or remaining[name] != expected):
                raise RSILearningError("rsi_budget_checkpoint_invalid")

    def _refresh(self) -> RSIRunBudget:
        planned = self.state["planned"]
        consumed = self.state["consumed"]
        self.state["remaining"] = {
            name: None if planned[limit_name] is None else planned[limit_name] - consumed[name]
            for name, limit_name in _COUNTER_LIMITS.items()
        }
        self._validate()
        return self

    def assert_matches(self, value: Mapping[str, Any] | None) -> None:
        expected = RSIRunBudget.create(value).state["planned"]
        if expected != self.state["planned"]:
            raise RSILearningError("rsi_resume_budget_drift")

    def reserve_stage(self, stage: str) -> None:
        """Charge one external stage invocation before its durable launch intent is written."""
        if type(stage) is not str or stage not in _STAGE_COUNTERS:
            raise RSILearningError("rsi_budget_stage_invalid")
        self._validate()
        planned = self.state["planned"]
        if planned["deadline_unix"] is not None and time.time() >= planned["deadline_unix"]:
            raise RSILearningError("rsi_budget_exhausted")
        counter = _STAGE_COUNTERS[stage]
        limit = planned[_COUNTER_LIMITS[counter]]
        if limit is not None and self.state["consumed"][counter] >= limit:
            raise RSILearningError("rsi_budget_exhausted")
        self.state["consumed"][counter] += 1
        self._refresh()

    def reserve_launch(self, *, episode_kind: str, depth: int, ancestry: tuple[str, ...]) -> None:
        if type(depth) is not int or depth < 0 or len(ancestry) != len(set(ancestry)):
            raise RSILearningError("rsi_budget_depth_cycle")
        planned = self.state["planned"]
        if planned["deadline_unix"] is not None and time.time() >= planned["deadline_unix"]:
            raise RSILearningError("rsi_budget_exhausted")
        if planned["max_depth"] is not None and depth > planned["max_depth"]:
            raise RSILearningError("rsi_budget_exhausted")
        if (planned["max_solver_invocations"] is not None
                and self.state["consumed"]["solver_invocations"] >= planned["max_solver_invocations"]):
            raise RSILearningError("rsi_budget_exhausted")
        if episode_kind == "practice":
            if (planned["max_practice_episodes"] is not None
                    and self.state["consumed"]["practice_episodes"] >= planned["max_practice_episodes"]):
                raise RSILearningError("rsi_budget_exhausted")
            self.state["consumed"]["practice_episodes"] += 1
        self.state["consumed"]["solver_invocations"] += 1
        self._refresh()

    def reserve_solver_invocation(self) -> None:
        """Reserve one solver gateway call outside the learning episode scheduler."""
        planned = self.state["planned"]
        if planned["deadline_unix"] is not None and time.time() >= planned["deadline_unix"]:
            raise RSILearningError("rsi_budget_exhausted")
        limit = planned["max_solver_invocations"]
        if limit is not None and self.state["consumed"]["solver_invocations"] >= limit:
            raise RSILearningError("rsi_budget_exhausted")
        self.state["consumed"]["solver_invocations"] += 1
        self._refresh()

    def reserve_unknown_reconcile(self) -> None:
        limit = self.state["planned"]["max_unknown_retries"]
        if limit is not None and self.state["consumed"]["unknown_retries"] >= limit:
            raise RSILearningError("rsi_budget_exhausted")
        self.state["consumed"]["unknown_retries"] += 1
        self._refresh()


__all__ = ["RSIRunBudget"]
