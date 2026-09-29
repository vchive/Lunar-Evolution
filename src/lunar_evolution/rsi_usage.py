"""Durable, provider-neutral usage receipts for RSI episodes and runs.

The RSI controller persists opaque solver results today.  This module defines the bounded usage
projection an adapter may attach to those results without treating a missing provider report as
zero consumption.  Amounts use integer milliseconds and micro-USD so a persisted receipt can be
checked and aggregated without floating-point drift.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .rsi_learning import RSILearningError

MAX_USAGE_VALUE = 2**63 - 1
_FIELDS = frozenset(
    {
        "request_count",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "wall_elapsed_ms",
        "cpu_elapsed_ms",
        "gpu_elapsed_ms",
        "input_cost_per_1k_micros",
        "output_cost_per_1k_micros",
        "estimated_cost_micros",
    }
)


def _integer(value: object, name: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or value < 0 or value > MAX_USAGE_VALUE:
        raise RSILearningError(f"rsi_usage_{name}_invalid")
    return value


@dataclass(frozen=True)
class RSIUsageReceipt:
    """One immutable usage observation for an RSI episode or a completed run.

    Request and token counters are ``None`` when the backing adapter cannot establish complete
    provider usage. CPU and GPU measurements are independently optional because a provider may
    expose either, neither, or both. ``wall_elapsed_ms`` is always an observed local duration.
    A configured price is included in the receipt itself, so ``estimated_cost_micros`` remains
    reproducible after a provider changes its public pricing.
    """

    request_count: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    wall_elapsed_ms: int
    cpu_elapsed_ms: int | None = None
    gpu_elapsed_ms: int | None = None
    input_cost_per_1k_micros: int | None = None
    output_cost_per_1k_micros: int | None = None
    estimated_cost_micros: int | None = None

    def __post_init__(self) -> None:
        _integer(self.request_count, "request_count", optional=True)
        _integer(self.wall_elapsed_ms, "wall_elapsed_ms")
        for value, name in (
            (self.cpu_elapsed_ms, "cpu_elapsed_ms"),
            (self.gpu_elapsed_ms, "gpu_elapsed_ms"),
            (self.input_cost_per_1k_micros, "input_cost_per_1k_micros"),
            (self.output_cost_per_1k_micros, "output_cost_per_1k_micros"),
            (self.estimated_cost_micros, "estimated_cost_micros"),
        ):
            _integer(value, name, optional=True)

        tokens = (self.input_tokens, self.output_tokens, self.total_tokens)
        if any(value is None for value in tokens):
            if any(value is not None for value in tokens):
                raise RSILearningError("rsi_usage_tokens_incomplete")
        else:
            input_tokens, output_tokens, total_tokens = (
                _integer(self.input_tokens, "input_tokens"),
                _integer(self.output_tokens, "output_tokens"),
                _integer(self.total_tokens, "total_tokens"),
            )
            if input_tokens + output_tokens != total_tokens:
                raise RSILearningError("rsi_usage_tokens_inconsistent")

        rates = (self.input_cost_per_1k_micros, self.output_cost_per_1k_micros)
        if (rates[0] is None) != (rates[1] is None):
            raise RSILearningError("rsi_usage_cost_rates_incomplete")
        if self.estimated_cost_micros is not None:
            if any(value is None for value in tokens) or any(value is None for value in rates):
                raise RSILearningError("rsi_usage_estimate_unverifiable")
            expected = self.estimate_cost(
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                input_cost_per_1k_micros=self.input_cost_per_1k_micros,
                output_cost_per_1k_micros=self.output_cost_per_1k_micros,
            )
            if self.estimated_cost_micros != expected:
                raise RSILearningError("rsi_usage_estimate_mismatch")
        elif rates[0] is not None and all(value is not None for value in tokens):
            raise RSILearningError("rsi_usage_estimate_missing")

    @staticmethod
    def estimate_cost(
        *,
        input_tokens: int,
        output_tokens: int,
        input_cost_per_1k_micros: int,
        output_cost_per_1k_micros: int,
    ) -> int:
        """Compute an integer micro-USD estimate with per-direction round-up."""
        for value, name in (
            (input_tokens, "input_tokens"),
            (output_tokens, "output_tokens"),
            (input_cost_per_1k_micros, "input_cost_per_1k_micros"),
            (output_cost_per_1k_micros, "output_cost_per_1k_micros"),
        ):
            _integer(value, name)
        return (input_tokens * input_cost_per_1k_micros + 999) // 1_000 + (
            output_tokens * output_cost_per_1k_micros + 999
        ) // 1_000

    @classmethod
    def observed(
        cls,
        *,
        request_count: int | None,
        wall_elapsed_ms: int,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        cpu_elapsed_ms: int | None = None,
        gpu_elapsed_ms: int | None = None,
        input_cost_per_1k_micros: int | None = None,
        output_cost_per_1k_micros: int | None = None,
    ) -> RSIUsageReceipt:
        """Build a receipt and calculate cost only when its evidence is complete."""
        estimate = None
        if (
            input_tokens is not None
            and output_tokens is not None
            and total_tokens is not None
            and input_cost_per_1k_micros is not None
            and output_cost_per_1k_micros is not None
        ):
            estimate = cls.estimate_cost(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_cost_per_1k_micros=input_cost_per_1k_micros,
                output_cost_per_1k_micros=output_cost_per_1k_micros,
            )
        return cls(
            request_count=request_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            wall_elapsed_ms=wall_elapsed_ms,
            cpu_elapsed_ms=cpu_elapsed_ms,
            gpu_elapsed_ms=gpu_elapsed_ms,
            input_cost_per_1k_micros=input_cost_per_1k_micros,
            output_cost_per_1k_micros=output_cost_per_1k_micros,
            estimated_cost_micros=estimate,
        )

    def to_dict(self) -> dict[str, int | None]:
        return {
            "request_count": self.request_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "wall_elapsed_ms": self.wall_elapsed_ms,
            "cpu_elapsed_ms": self.cpu_elapsed_ms,
            "gpu_elapsed_ms": self.gpu_elapsed_ms,
            "input_cost_per_1k_micros": self.input_cost_per_1k_micros,
            "output_cost_per_1k_micros": self.output_cost_per_1k_micros,
            "estimated_cost_micros": self.estimated_cost_micros,
        }

    @classmethod
    def from_dict(cls, value: object) -> RSIUsageReceipt:
        if not isinstance(value, dict) or set(value) != _FIELDS:
            raise RSILearningError("rsi_usage_schema_invalid")
        return cls(**value)


UsageReceiptProvider = Callable[[object, object, int], RSIUsageReceipt | None]


def usage_receipt_from(
    provider: object,
    request: object,
    result: object,
    *,
    wall_elapsed_ms: int,
) -> RSIUsageReceipt | None:
    """Read an optional adapter-side receipt without changing the solver result schema.

    The provider must return a fully validated receipt for the immutable request/result pair or
    ``None`` when it cannot report usage.  The controller records its own elapsed wall clock on
    every receipt, so an adapter cannot replace the locally observed duration with an arbitrary
    remote value.
    """
    source = getattr(provider, "usage_receipt", None)
    if source is None:
        return None
    if not callable(source):
        raise RSILearningError("rsi_usage_provider_invalid")
    observed = source(request, result, wall_elapsed_ms)
    if observed is None:
        return None
    if not isinstance(observed, RSIUsageReceipt):
        raise RSILearningError("rsi_usage_provider_invalid")
    if observed.wall_elapsed_ms != wall_elapsed_ms:
        raise RSILearningError("rsi_usage_wall_elapsed_mismatch")
    return observed


def aggregate_usage(
    receipts: Iterable[RSIUsageReceipt | None],
    *,
    wall_elapsed_ms: int,
) -> RSIUsageReceipt:
    """Aggregate completed episode receipts into a run receipt.

    ``wall_elapsed_ms`` is the observed run wall clock, supplied by the controller.  It is not
    the sum of episode wall times because BRS episodes may overlap.  A total is omitted whenever
    any component omitted that measurement; this prevents partial provider telemetry from being
    reported as a complete per-run amount.
    """
    items = tuple(receipts)
    if any(item is not None and not isinstance(item, RSIUsageReceipt) for item in items):
        raise RSILearningError("rsi_usage_receipt_invalid")

    def total(name: str) -> int | None:
        values = [getattr(item, name) if item is not None else None for item in items]
        return None if not values or any(value is None for value in values) else sum(values)

    rates = {
        (item.input_cost_per_1k_micros, item.output_cost_per_1k_micros)
        for item in items
        if item is not None
    }
    token_totals = (total("input_tokens"), total("output_tokens"), total("total_tokens"))
    cost_rates = rates.pop() if len(rates) == 1 and all(
        item is not None and item.input_cost_per_1k_micros is not None
        for item in items
    ) else (None, None)
    input_rate, output_rate = cost_rates
    return RSIUsageReceipt.observed(
        request_count=total("request_count"),
        wall_elapsed_ms=wall_elapsed_ms,
        input_tokens=token_totals[0],
        output_tokens=token_totals[1],
        total_tokens=token_totals[2],
        cpu_elapsed_ms=total("cpu_elapsed_ms"),
        gpu_elapsed_ms=total("gpu_elapsed_ms"),
        input_cost_per_1k_micros=input_rate,
        output_cost_per_1k_micros=output_rate,
    )


__all__ = [
    "MAX_USAGE_VALUE",
    "RSIUsageReceipt",
    "UsageReceiptProvider",
    "aggregate_usage",
    "usage_receipt_from",
]
