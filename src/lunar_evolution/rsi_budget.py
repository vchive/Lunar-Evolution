"""Durable, fail-closed budget accounting for one RSI controller run."""
from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any

from .rsi_learning import RSILearningError

_LIMITS = ("max_depth", "max_solver_invocations", "max_practice_episodes", "max_unknown_retries")


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
        consumed = {"solver_invocations": 0, "practice_episodes": 0, "unknown_retries": 0}
        return cls({
            "planned": planned,
            "consumed": consumed,
            "remaining": {"solver_invocations": planned["max_solver_invocations"],
                          "practice_episodes": planned["max_practice_episodes"],
                          "unknown_retries": planned["max_unknown_retries"]},
        })

    @classmethod
    def load(cls, value: object) -> RSIRunBudget:
        if not isinstance(value, dict):
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        return cls(value)

    def _validate(self) -> None:
        if set(self.state) != {"planned", "consumed", "remaining"}:
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        planned = self.state["planned"]
        consumed = self.state["consumed"]
        remaining = self.state["remaining"]
        if not isinstance(planned, dict) or set(planned) != {*_LIMITS, "deadline_unix"}:
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        if not isinstance(consumed, dict) or set(consumed) != {"solver_invocations", "practice_episodes", "unknown_retries"}:
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        if not isinstance(remaining, dict) or set(remaining) != {"solver_invocations", "practice_episodes", "unknown_retries"}:
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        for name in _LIMITS:
            _limit(planned[name], name)
        _deadline(planned["deadline_unix"])
        for name, limit in (("solver_invocations", planned["max_solver_invocations"]),
                            ("practice_episodes", planned["max_practice_episodes"]),
                            ("unknown_retries", planned["max_unknown_retries"])):
            if type(consumed[name]) is not int or consumed[name] < 0:
                raise RSILearningError("rsi_budget_checkpoint_invalid")
            expected = None if limit is None else limit - consumed[name]
            if expected is not None and expected < 0 or remaining[name] != expected:
                raise RSILearningError("rsi_budget_checkpoint_invalid")

    def _refresh(self) -> RSIRunBudget:
        planned = self.state["planned"]
        consumed = self.state["consumed"]
        self.state["remaining"] = {
            "solver_invocations": (None if planned["max_solver_invocations"] is None
                                    else planned["max_solver_invocations"] - consumed["solver_invocations"]),
            "practice_episodes": (None if planned["max_practice_episodes"] is None
                                  else planned["max_practice_episodes"] - consumed["practice_episodes"]),
            "unknown_retries": (None if planned["max_unknown_retries"] is None
                                else planned["max_unknown_retries"] - consumed["unknown_retries"]),
        }
        self._validate()
        return self

    def assert_matches(self, value: Mapping[str, Any] | None) -> None:
        expected = RSIRunBudget.create(value).state["planned"]
        if expected != self.state["planned"]:
            raise RSILearningError("rsi_resume_budget_drift")

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

    def reserve_unknown_reconcile(self) -> None:
        limit = self.state["planned"]["max_unknown_retries"]
        if limit is not None and self.state["consumed"]["unknown_retries"] >= limit:
            raise RSILearningError("rsi_budget_exhausted")
        self.state["consumed"]["unknown_retries"] += 1
        self._refresh()


__all__ = ["RSIRunBudget"]
