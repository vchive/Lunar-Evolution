"""Compose one caller-owned deadline across native producer publication stages.

The caller's control remains unchanged. A transaction may attach its retained monotonic deadline
to the yielded checkpoint after the prepared intent is fixed. Both deadlines and cancellation
sources then constrain every stage; this module never refreshes either allowance.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from .automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from .bundle_evolution import MultiFileCandidatePipeline
from .evolution import PopulationStrategy


class ProducerBundleControlError(ValueError):
    """A fixed-code invalid control boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _pipeline(strategy: PopulationStrategy) -> MultiFileCandidatePipeline:
    if not isinstance(strategy, PopulationStrategy):
        raise ProducerBundleControlError("producer_bundle_transaction_strategy_invalid")
    pipeline = strategy.context.bundle_pipeline
    if not isinstance(pipeline, MultiFileCandidatePipeline):
        raise ProducerBundleControlError("producer_bundle_transaction_pipeline_invalid")
    return pipeline


def native_producer_bundle_budget_sha256(
    strategy: PopulationStrategy, execution_control: SolveExecutionControl | None = None,
) -> str:
    """Pin the declared native limits, including the caller's shared wall-clock allowance.

    Preparation makes no provider requests in this native material-import path. Operational
    remaining time can only narrow these limits; the monotonic start time is deliberately absent
    from this portable policy digest.
    """
    pipeline = _pipeline(strategy)
    if execution_control is not None and not isinstance(execution_control, SolveExecutionControl):
        raise ProducerBundleControlError("producer_bundle_transaction_control_invalid")
    policy = {
        "protocol": "lunar-native-producer-bundle-budget-v1",
        "preparation_requests": 0,
        "candidate_execution": pipeline.budget.to_dict(),
        "evaluation_timeout_seconds": pipeline.evaluator.timeout_seconds,
        "wall_timeout_seconds": execution_control.timeout_seconds if execution_control is not None else None,
    }
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _distinct_callbacks(*callbacks):
    seen: set[int] = set()
    for callback in callbacks:
        if callback is not None and id(callback) not in seen:
            seen.add(id(callback))
            yield callback


@contextmanager
def bind_native_producer_bundle_control(
    strategy: PopulationStrategy,
    execution_control: SolveExecutionControl,
) -> Iterator[Callable[[str], float]]:
    """Temporarily bind one shared deadline without widening any parent control.

    The yielded checkpoint must also be called before preparing, staging, and committing the
    batch, including paths that reuse retained evidence. Native subprocesses receive the positive
    remaining time as their timeout. Cancellation is checked at each stage boundary; this helper
    does not introduce a separate process watcher. Previous pipeline hooks are restored even when
    a draft or checkpoint raises.
    """
    pipeline = _pipeline(strategy)
    if not isinstance(execution_control, SolveExecutionControl):
        raise ProducerBundleControlError("producer_bundle_transaction_control_invalid")
    previous_timeout = pipeline._remaining_timeout
    previous_guard = pipeline._continuation_guard
    timeout_callbacks = tuple(_distinct_callbacks(previous_timeout, strategy.context.remaining_timeout))
    guards = tuple(_distinct_callbacks(previous_guard, strategy.context.continuation_guard))
    if any(not callable(callback) for callback in (*timeout_callbacks, *guards)):
        raise ProducerBundleControlError("producer_bundle_transaction_parent_control_invalid")

    retained_deadlines: list[Callable[[str], float]] = []

    def bind_retained_deadline(callback: Callable[[str], float]) -> None:
        if not callable(callback):
            raise ProducerBundleControlError("producer_bundle_transaction_control_invalid")
        retained_deadlines.append(callback)

    def check(stage: str) -> float:
        if strategy._cancelled():
            raise SolveExecutionCancelled(stage)
        for guard in guards:
            guard()
        remaining = execution_control.check(stage)
        parent_observations: list[tuple[float, float]] = []
        for callback in (*timeout_callbacks, *retained_deadlines):
            sampled_at = execution_control._now()
            parent_remaining = callback(stage)
            if (isinstance(parent_remaining, bool) or not isinstance(parent_remaining, (int, float))
                    or not math.isfinite(float(parent_remaining)) or parent_remaining <= 0):
                raise ProducerBundleControlError("producer_bundle_transaction_parent_budget_invalid")
            parent_observations.append((sampled_at, float(parent_remaining)))
        # Parent callbacks may consume time or observe cancellation. Recheck before admitting work.
        if strategy._cancelled():
            raise SolveExecutionCancelled(stage)
        remaining = min(remaining, execution_control.check(stage))
        observed_at = execution_control._now()
        for sampled_at, parent_remaining in parent_observations:
            deadline = sampled_at + parent_remaining
            adjusted_remaining = deadline - observed_at
            if adjusted_remaining <= 0:
                raise SolveExecutionBudgetExceeded(
                    stage, started_at=sampled_at, deadline=deadline, observed_at=observed_at,
                )
            remaining = min(remaining, adjusted_remaining)
        return remaining

    check.bind_retained_deadline = bind_retained_deadline
    pipeline.set_remaining_timeout(check)
    pipeline.set_continuation_guard(None)
    try:
        yield check
    finally:
        pipeline.set_remaining_timeout(previous_timeout)
        pipeline.set_continuation_guard(previous_guard)


__all__ = [
    "ProducerBundleControlError",
    "bind_native_producer_bundle_control",
    "native_producer_bundle_budget_sha256",
]
