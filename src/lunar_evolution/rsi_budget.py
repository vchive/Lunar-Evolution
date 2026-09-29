"""Durable, fail-closed accounting for one RSI learning run.

The budget is intentionally a small protocol object.  It does not persist anything itself;
the controller stores :attr:`state` as part of its checkpoint.  A checkpoint contains the
planned limits, monotonic counters and derived remaining values.  Every mutating operation
validates the complete state before it starts and again before it returns, so a rejected
reservation cannot partially charge another counter.
"""

from __future__ import annotations

import copy
import hashlib
import math
import time
from collections.abc import Mapping
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import RSILearningError

_MAX_STATE_BYTES = 128 * 1024

# ``max_practice_episodes`` is retained as a separate, stricter episode ceiling.  The round and
# target limits are the user-facing DRS controls; the stage limits protect individual side effects.
_COUNTER_LIMITS: dict[str, str] = {
    "practice_rounds": "max_practice_rounds",
    "target_attempts": "max_target_attempts",
    "practice_episodes": "max_practice_episodes",
    "solver_invocations": "max_solver_invocations",
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
_EPISODE_KINDS = frozenset({"target", "practice"})


def _error(code: str) -> None:
    raise RSILearningError(code)


def _limit(value: object, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        _error(f"rsi_budget_{name}_invalid")
    return value


def _deadline(value: object) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float} or isinstance(value, bool):
        _error("rsi_budget_deadline_unix_invalid")
    result = float(value)
    if not math.isfinite(result):
        _error("rsi_budget_deadline_unix_invalid")
    return result


def _counter(value: object) -> int:
    if type(value) is not int or value < 0:
        _error("rsi_budget_checkpoint_invalid")
    return value


def _ancestry(value: object) -> tuple[str, ...]:
    # A tuple is required at this boundary: accepting a mutable list would allow the lineage
    # checked before launch to differ from the lineage written in the checkpoint.
    if not isinstance(value, tuple) or not value:
        _error("rsi_budget_depth_cycle")
    for item in value:
        if type(item) is not str or not item.strip() or any(char in item for char in "\x00\r\n"):
            _error("rsi_budget_depth_cycle")
    if len(set(value)) != len(value):
        _error("rsi_budget_depth_cycle")
    return value


class RSIRunBudget:
    """Canonical planned/consumed/remaining budget state for one RSI run."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self._validate()

    @classmethod
    def create(cls, value: Mapping[str, Any] | None = None) -> RSIRunBudget:
        if value is not None and not isinstance(value, Mapping):
            _error("rsi_budget_invalid")
        raw = dict(value or {})
        allowed = set(_LIMITS) | {"deadline_unix"}
        unknown = set(raw) - allowed
        if unknown:
            _error("rsi_budget_unknown_field")
        planned = {name: _limit(raw.get(name), name) for name in _LIMITS}
        planned["deadline_unix"] = _deadline(raw.get("deadline_unix"))
        consumed = dict.fromkeys(_COUNTER_LIMITS, 0)
        remaining = {
            counter: planned[limit_name]
            for counter, limit_name in _COUNTER_LIMITS.items()
        }
        return cls({"planned": planned, "consumed": consumed, "remaining": remaining})

    @classmethod
    def load(cls, value: object) -> RSIRunBudget:
        """Load a complete checkpoint without retaining a caller-owned mutable mapping."""
        if not isinstance(value, dict):
            _error("rsi_budget_checkpoint_invalid")
        try:
            state = copy.deepcopy(value)
        except (TypeError, ValueError, RecursionError):
            _error("rsi_budget_checkpoint_invalid")
        return cls(state)

    def _validate(self) -> None:
        if set(self.state) != {"planned", "consumed", "remaining"}:
            _error("rsi_budget_checkpoint_invalid")
        planned = self.state["planned"]
        consumed = self.state["consumed"]
        remaining = self.state["remaining"]
        if not isinstance(planned, dict) or set(planned) != {*_LIMITS, "deadline_unix"}:
            _error("rsi_budget_checkpoint_invalid")
        if not isinstance(consumed, dict) or set(consumed) != set(_COUNTER_LIMITS):
            _error("rsi_budget_checkpoint_invalid")
        if not isinstance(remaining, dict) or set(remaining) != set(_COUNTER_LIMITS):
            _error("rsi_budget_checkpoint_invalid")
        for name in _LIMITS:
            _limit(planned[name], name)
        _deadline(planned["deadline_unix"])
        for counter, limit_name in _COUNTER_LIMITS.items():
            used = _counter(consumed[counter])
            limit = planned[limit_name]
            expected = None if limit is None else limit - used
            if expected is not None and expected < 0:
                _error("rsi_budget_checkpoint_invalid")
            actual = remaining[counter]
            if expected is None:
                if actual is not None:
                    _error("rsi_budget_checkpoint_invalid")
            elif type(actual) is not int or actual != expected:
                _error("rsi_budget_checkpoint_invalid")
        try:
            canonical_json(self.state, maximum=_MAX_STATE_BYTES)
        except (TypeError, ValueError, OverflowError, RecursionError):
            _error("rsi_budget_checkpoint_invalid")

    def to_dict(self) -> dict[str, Any]:
        self._validate()
        return copy.deepcopy(self.state)

    def canonical_bytes(self) -> bytes:
        self._validate()
        try:
            return canonical_json(self.state, maximum=_MAX_STATE_BYTES)
        except (TypeError, ValueError, OverflowError, RecursionError):
            _error("rsi_budget_checkpoint_invalid")

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def check(
        self,
        *,
        counter: str | None = None,
        amount: int = 1,
        depth: int | None = None,
        ancestry: tuple[str, ...] | None = None,
        now: float | None = None,
    ) -> None:
        """Check a prospective reservation without changing counters."""
        self._validate()
        if type(amount) is not int or amount < 1:
            _error("rsi_budget_amount_invalid")
        if counter is not None:
            if counter not in _COUNTER_LIMITS:
                _error("rsi_budget_counter_invalid")
            limit = self.state["planned"][_COUNTER_LIMITS[counter]]
            used = self.state["consumed"][counter]
            if limit is not None and used + amount > limit:
                _error("rsi_budget_exhausted")
        if depth is not None or ancestry is not None:
            self._check_depth(depth, ancestry)
        deadline = self.state["planned"]["deadline_unix"]
        current = time.time() if now is None else now
        if type(current) not in {int, float} or isinstance(current, bool) or not math.isfinite(float(current)):
            _error("rsi_budget_now_invalid")
        if deadline is not None and float(current) >= deadline:
            _error("rsi_budget_exhausted")

    def _check_depth(self, depth: int | None, ancestry: tuple[str, ...] | None) -> None:
        if type(depth) is not int or depth < 0 or ancestry is None:
            _error("rsi_budget_depth_cycle")
        lineage = _ancestry(ancestry)
        if depth != len(lineage) - 1:
            _error("rsi_budget_depth_cycle")
        maximum = self.state["planned"]["max_depth"]
        if maximum is not None and depth > maximum:
            _error("rsi_budget_exhausted")

    def consume(self, counter: str, amount: int = 1) -> None:
        """Atomically consume a named counter after checking the run deadline and limit."""
        self.check(counter=counter, amount=amount)
        before = copy.deepcopy(self.state)
        try:
            self.state["consumed"][counter] += amount
            self._refresh()
        except Exception:
            self.state.clear()
            self.state.update(before)
            raise

    def _refresh(self) -> None:
        planned = self.state["planned"]
        consumed = self.state["consumed"]
        self.state["remaining"] = {
            counter: (
                None if planned[limit_name] is None
                else planned[limit_name] - consumed[counter]
            )
            for counter, limit_name in _COUNTER_LIMITS.items()
        }
        self._validate()

    def reserve_launch(
        self,
        *,
        episode_kind: str,
        depth: int,
        ancestry: tuple[str, ...],
    ) -> None:
        """Reserve one target/practice solver launch with depth and cycle protection."""
        if type(episode_kind) is not str or episode_kind not in _EPISODE_KINDS:
            _error("rsi_budget_episode_kind_invalid")
        self._validate()
        self._check_depth(depth, ancestry)
        counters = ["solver_invocations"]
        counters.append("target_attempts" if episode_kind == "target" else "practice_rounds")
        if episode_kind == "practice":
            counters.append("practice_episodes")
        for counter in counters:
            self.check(counter=counter)
        before = copy.deepcopy(self.state)
        try:
            for counter in counters:
                self.state["consumed"][counter] += 1
            self._refresh()
        except Exception:
            self.state.clear()
            self.state.update(before)
            raise

    def reserve_solver_invocation(self) -> None:
        self.consume("solver_invocations")

    def reserve_stage(self, stage: str) -> None:
        if type(stage) is not str or stage not in _STAGE_COUNTERS:
            _error("rsi_budget_stage_invalid")
        self.consume(_STAGE_COUNTERS[stage])

    def reserve_unknown_reconcile(self) -> None:
        self.consume("unknown_retries")

    def assert_matches(self, value: Mapping[str, Any] | None) -> None:
        expected = self.create(value)
        if expected.state["planned"] != self.state["planned"]:
            _error("rsi_resume_budget_drift")


__all__ = ["RSIRunBudget"]
