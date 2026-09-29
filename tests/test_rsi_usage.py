import pytest

from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_usage import RSIUsageReceipt, aggregate_usage


def test_usage_receipt_persists_exact_metering_and_reproducible_cost() -> None:
    receipt = RSIUsageReceipt.observed(
        request_count=2,
        input_tokens=1_001,
        output_tokens=2,
        total_tokens=1_003,
        wall_elapsed_ms=345,
        cpu_elapsed_ms=200,
        gpu_elapsed_ms=17,
        input_cost_per_1k_micros=17,
        output_cost_per_1k_micros=23,
    )

    assert receipt.estimated_cost_micros == 19
    assert RSIUsageReceipt.from_dict(receipt.to_dict()) == receipt


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            {"input_tokens": 1, "output_tokens": None, "total_tokens": None},
            "rsi_usage_tokens_incomplete",
        ),
        (
            {"input_tokens": 1, "output_tokens": 2, "total_tokens": 2},
            "rsi_usage_tokens_inconsistent",
        ),
        (
            {"input_cost_per_1k_micros": 1, "output_cost_per_1k_micros": None},
            "rsi_usage_cost_rates_incomplete",
        ),
        ({"estimated_cost_micros": 1}, "rsi_usage_estimate_unverifiable"),
    ],
)
def test_usage_receipt_rejects_partial_or_unverifiable_claims(payload, code) -> None:
    base = RSIUsageReceipt.observed(request_count=1, wall_elapsed_ms=0).to_dict()
    base.update(payload)
    with pytest.raises(RSILearningError, match=code):
        RSIUsageReceipt.from_dict(base)


def test_usage_receipt_keeps_unavailable_tokens_distinct_from_zero() -> None:
    receipt = RSIUsageReceipt.observed(request_count=1, wall_elapsed_ms=9)
    assert receipt.to_dict() == {
        "request_count": 1,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "wall_elapsed_ms": 9,
        "cpu_elapsed_ms": None,
        "gpu_elapsed_ms": None,
        "input_cost_per_1k_micros": None,
        "output_cost_per_1k_micros": None,
        "estimated_cost_micros": None,
    }


def test_aggregate_usage_uses_controller_wall_clock_and_refuses_partial_totals() -> None:
    first = RSIUsageReceipt.observed(
        request_count=1,
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        wall_elapsed_ms=200,
        cpu_elapsed_ms=100,
        input_cost_per_1k_micros=1_000,
        output_cost_per_1k_micros=2_000,
    )
    second = RSIUsageReceipt.observed(
        request_count=2,
        input_tokens=200,
        output_tokens=30,
        total_tokens=230,
        wall_elapsed_ms=300,
        cpu_elapsed_ms=250,
        input_cost_per_1k_micros=1_000,
        output_cost_per_1k_micros=2_000,
    )
    combined = aggregate_usage((first, second), wall_elapsed_ms=350)
    assert combined.to_dict() == {
        "request_count": 3,
        "input_tokens": 300,
        "output_tokens": 50,
        "total_tokens": 350,
        "wall_elapsed_ms": 350,
        "cpu_elapsed_ms": 350,
        "gpu_elapsed_ms": None,
        "input_cost_per_1k_micros": 1_000,
        "output_cost_per_1k_micros": 2_000,
        "estimated_cost_micros": 400,
    }

    partial = aggregate_usage(
        (first, RSIUsageReceipt.observed(request_count=1, wall_elapsed_ms=1)), wall_elapsed_ms=201
    )
    assert partial.input_tokens is partial.estimated_cost_micros is None
