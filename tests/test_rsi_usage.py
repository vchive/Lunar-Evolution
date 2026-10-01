from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_evolution.rsi_usage import (
    RSIUsageError,
    UsageLedger,
    UsagePricing,
    UsageReceipt,
)


def receipt(event: str, *, episode: str | None = "ep-1", tokens: bool = True, stage: str = "execute") -> UsageReceipt:
    return UsageReceipt(
        event_id=event,
        run_id="run-1",
        episode_id=episode,
        adapter_stage=stage,
        input_tokens=4 if tokens else None,
        output_tokens=6 if tokens else None,
        wall_time_ms=10,
        cpu_time_ms=5,
    )


def test_usage_receipt_derives_total_and_rejects_partial_tokens() -> None:
    assert receipt("e1").to_dict()["total_tokens"] == 10
    with pytest.raises(RSIUsageError, match="token_unknown_partial"):
        UsageReceipt(event_id="e", run_id="r", adapter_stage="execute", input_tokens=1)


def test_append_only_cas_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    ledger = UsageLedger(path, pricing=UsagePricing(100, 200))
    first = ledger.append(receipt("e1"))
    assert first == ledger.head_sha256
    second = ledger.append(receipt("e2", stage="verify"), expected_head_sha256=first)
    assert second != first
    reopened = UsageLedger(path)
    assert reopened.head_sha256 == second
    assert reopened.summary(run_id="run-1").to_dict() == {
        "run_id": "run-1", "episode_id": None, "adapter_stage": None,
        "request_count": 2, "input_tokens": 8, "output_tokens": 12,
        "total_tokens": 20, "wall_time_ms": 20, "cpu_time_ms": 10,
        "estimated_cost_micros": 6, "usage_complete": True, "receipt_count": 2,
    }
    with pytest.raises(RSIUsageError, match="cas_conflict"):
        reopened.append(receipt("e3"), expected_head_sha256=first)


def test_unknown_usage_is_preserved_and_budget_fails_closed(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path / "usage.json", pricing=UsagePricing(100, 200))
    ledger.append(receipt("known"))
    ledger.append(receipt("unknown", tokens=False))
    summary = ledger.summary(run_id="run-1")
    assert summary.request_count == 2
    assert summary.total_tokens is None
    assert summary.estimated_cost_micros is None
    assert summary.usage_complete is False
    with pytest.raises(RSIUsageError, match="usage_unknown"):
        ledger.budget_check(run_id="run-1", max_total_tokens=100)
    # Operators may inspect a partial report without treating it as a budget authorization.
    assert ledger.budget_check(run_id="run-1", require_complete=False).request_count == 2


def test_scope_summary_and_explicit_cost(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path / "usage.json")
    ledger.append(UsageReceipt(
        event_id="e", run_id="r", episode_id="ep", adapter_stage="execute",
        request_count=2, input_tokens=1, output_tokens=2, wall_time_ms=7,
        cpu_time_ms=3, estimated_cost_micros=9,
    ))
    assert ledger.summary(episode_id="ep", adapter_stage="execute").estimated_cost_micros == 9
    assert ledger.summary(run_id="other").request_count == 0


def test_tampering_is_rejected_on_reopen(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    ledger = UsageLedger(path)
    ledger.append(receipt("e"))
    payload = json.loads(path.read_text())
    payload["records"][0]["receipt"]["request_count"] = 2
    path.write_text(json.dumps(payload))
    with pytest.raises(RSIUsageError, match="ledger_corrupt"):
        UsageLedger(path)


def test_duplicate_event_is_idempotent_but_conflicting_event_fails(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path / "usage.json")
    item = receipt("same")
    first = ledger.append(item)
    assert ledger.append(item, expected_head_sha256=first) == first
    assert len(ledger.records()) == 1
    with pytest.raises(RSIUsageError, match="event_conflict"):
        ledger.append(UsageReceipt(
            event_id="same", run_id="r", adapter_stage="verify", wall_time_ms=10, cpu_time_ms=5,
        ), expected_head_sha256=first)


def test_stale_head_and_strict_receipt_serialization_fail_closed(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path / "usage.json")
    head = ledger.append(receipt("e1"))
    with pytest.raises(RSIUsageError, match="cas_conflict"):
        ledger.append(receipt("e2"), expected_head_sha256="0" * 64)
    payload = receipt("e").to_dict()
    payload["total_tokens"] = None
    with pytest.raises(RSIUsageError, match="receipt_invalid"):
        UsageReceipt.from_dict(payload)
    payload = receipt("e").to_dict()
    payload["total_tokens"] = True
    with pytest.raises(RSIUsageError, match="receipt_invalid"):
        UsageReceipt.from_dict(payload)
    payload = receipt("e", tokens=False).to_dict()
    payload["total_tokens"] = 0
    with pytest.raises(RSIUsageError, match="receipt_invalid"):
        UsageReceipt.from_dict(payload)
    assert ledger.head_sha256 == head


def test_duplicate_json_keys_unknown_fields_and_pricing_drift_reject_reopen(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    ledger = UsageLedger(path, pricing=UsagePricing(100, 200))
    ledger.append(receipt("e"))
    text = path.read_text()
    path.write_text(text.replace('"schema_version":"1"', '"schema_version":"1","schema_version":"1"', 1))
    with pytest.raises(RSIUsageError, match="ledger_corrupt"):
        UsageLedger(path)
    path.unlink()
    fresh = UsageLedger(path, pricing=UsagePricing(100, 200))
    fresh.append(receipt("e"))
    unknown = json.loads(path.read_text())
    unknown["extra"] = 1
    path.write_text(json.dumps(unknown))
    with pytest.raises(RSIUsageError, match="ledger_corrupt"):
        UsageLedger(path)
    # Rewrite a valid file, then alter its persisted pricing without changing the receipt chain.
    path.unlink()
    fresh = UsageLedger(path, pricing=UsagePricing(100, 200))
    fresh.append(receipt("e"))
    payload = json.loads(path.read_text())
    payload["pricing"]["request_cost_micros"] = 1
    path.write_text(json.dumps(payload))
    with pytest.raises(RSIUsageError, match="pricing_drift|ledger_corrupt"):
        UsageLedger(path, pricing=UsagePricing(100, 200))


def test_partial_token_pricing_is_rejected_and_request_only_is_explicit(tmp_path: Path) -> None:
    with pytest.raises(RSIUsageError, match="pricing_invalid"):
        UsagePricing(input_cost_per_1k_micros=100)
    pricing = UsagePricing(request_cost_micros=7)
    ledger = UsageLedger(tmp_path / "usage.json", pricing=pricing)
    ledger.append(receipt("unknown", tokens=False))
    summary = ledger.summary(run_id="run-1")
    assert summary.estimated_cost_micros == 7
    assert summary.usage_complete is False


def test_token_budget_does_not_require_optional_cost_pricing(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path / "usage.json")
    ledger.append(receipt("known"))
    summary = ledger.budget_check(run_id="run-1", max_total_tokens=20)
    assert summary.total_tokens == 10
    assert summary.estimated_cost_micros is None
