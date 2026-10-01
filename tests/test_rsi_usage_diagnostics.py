"""Read-only, provider-free usage diagnostics and evidence completeness."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_usage import (
    RSIUsageError,
    UsageLedger,
    UsagePricing,
    UsageReceipt,
    inspect_usage_ledger,
)


def ledger_fixture(path: Path) -> UsageLedger:
    ledger = UsageLedger(path, pricing=UsagePricing(100, 200))
    ledger.append(UsageReceipt(
        event_id="solver-1", run_id="run-1", episode_id="episode-1", adapter_stage="solver",
        request_count=2, input_tokens=4, output_tokens=6, wall_time_ms=10, cpu_time_ms=5,
    ))
    ledger.append(UsageReceipt(
        event_id="verifier-1", run_id="run-1", episode_id="episode-2", adapter_stage="verifier",
        wall_time_ms=7,
    ))
    ledger.append(UsageReceipt(
        event_id="other-1", run_id="run-2", episode_id="episode-other", adapter_stage="prepare",
        input_tokens=1, output_tokens=1, wall_time_ms=2, cpu_time_ms=1, estimated_cost_micros=9,
    ))
    return ledger


def test_partial_report_explains_unknown_metrics_and_retains_estimate_semantics(tmp_path: Path):
    path = tmp_path / "usage.json"
    ledger = ledger_fixture(path)
    report = inspect_usage_ledger(path, run_id="run-1")
    assert report["protocol"] == "rsi-usage-diagnostics-v1"
    assert report["head_sha256"] == ledger.head_sha256
    assert report["scope"] == {"run_id": "run-1", "episode_id": None, "adapter_stage": None}
    assert report["cost_basis"] == "estimate"
    assert report["request_count_semantics"] == "adapter_stage_receipts"
    aggregate = report["aggregate"]
    assert aggregate["evidence_status"] == "partial"
    assert aggregate["receipt_count"] == 2 and aggregate["request_count"] == 3
    assert aggregate["usage_complete"] is False
    assert aggregate["totals"] == {
        "input_tokens": None, "output_tokens": None, "total_tokens": None,
        "wall_time_ms": 17, "cpu_time_ms": None, "estimated_cost_micros": None,
    }
    assert aggregate["metric_completeness"]["total_tokens"] == {
        "known_receipt_count": 1, "unknown_receipt_count": 1,
    }
    assert aggregate["metric_completeness"]["wall_time_ms"] == {
        "known_receipt_count": 2, "unknown_receipt_count": 0,
    }
    assert [stage["adapter_stage"] for stage in report["stages"]] == ["solver", "verifier"]
    assert report["stages"][0]["evidence_status"] == "complete"
    assert report["stages"][0]["totals"]["estimated_cost_micros"] == 3
    assert report["stages"][1]["evidence_status"] == "partial"


def test_filters_intersect_and_complete_scope_uses_matching_receipts_only(tmp_path: Path):
    path = tmp_path / "usage.json"
    ledger_fixture(path)
    report = inspect_usage_ledger(path, run_id="run-2", episode_id="episode-other", adapter_stage="prepare")
    aggregate = report["aggregate"]
    assert aggregate["evidence_status"] == "complete"
    assert aggregate["usage_complete"] is True
    assert aggregate["receipt_count"] == aggregate["request_count"] == 1
    assert aggregate["totals"]["total_tokens"] == 2
    assert aggregate["totals"]["estimated_cost_micros"] == 9
    assert [stage["adapter_stage"] for stage in report["stages"]] == ["prepare"]

    no_match = inspect_usage_ledger(path, run_id="run-1", episode_id="episode-other")
    assert no_match["aggregate"]["evidence_status"] == "no_receipts"
    assert no_match["aggregate"]["usage_complete"] is False
    assert no_match["aggregate"]["receipt_count"] == no_match["aggregate"]["request_count"] == 0
    assert all(value is None for value in no_match["aggregate"]["totals"].values())
    assert no_match["stages"] == []


def test_valid_empty_file_reports_absent_evidence_instead_of_measured_zero(tmp_path: Path):
    path = tmp_path / "empty.json"
    path.write_bytes(canonical_json(UsageLedger(path).state()))
    report = inspect_usage_ledger(path)
    assert report["head_sha256"] is None
    assert report["aggregate"]["evidence_status"] == "no_receipts"
    assert report["aggregate"]["usage_complete"] is False
    assert set(report["aggregate"]["totals"].values()) == {None}
    assert all(value == {"known_receipt_count": 0, "unknown_receipt_count": 0}
               for value in report["aggregate"]["metric_completeness"].values())


def test_request_only_pricing_is_an_estimate_while_token_usage_remains_unknown(tmp_path: Path):
    path = tmp_path / "request-pricing.json"
    UsageLedger(path, pricing=UsagePricing(request_cost_micros=7)).append(UsageReceipt(
        event_id="unknown", run_id="run", adapter_stage="solver", request_count=2,
    ))
    report = inspect_usage_ledger(path)
    assert report["cost_basis"] == "estimate"
    assert report["aggregate"]["totals"]["estimated_cost_micros"] == 14
    assert report["aggregate"]["totals"]["total_tokens"] is None
    assert report["aggregate"]["evidence_status"] == "partial"


def test_repeated_reports_are_deterministic_and_create_or_change_no_files(tmp_path: Path):
    path = tmp_path / "usage.json"
    ledger_fixture(path)
    before_bytes = path.read_bytes()
    before_stat = path.stat()
    before_names = sorted(item.name for item in tmp_path.iterdir())
    expected = inspect_usage_ledger(path)
    assert inspect_usage_ledger(path) == expected
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert path.stat().st_ino == before_stat.st_ino
    assert sorted(item.name for item in tmp_path.iterdir()) == before_names


@pytest.mark.parametrize("kind", ["missing", "symlink", "dangling", "directory", "fifo", "oversized"])
def test_reader_rejects_unavailable_or_nonregular_paths_without_writing(tmp_path: Path, monkeypatch, kind: str):
    path = tmp_path / "input"
    if kind == "symlink":
        actual = tmp_path / "actual.json"
        ledger_fixture(actual)
        path.symlink_to(actual)
    elif kind == "dangling":
        path.symlink_to(tmp_path / "absent.json")
    elif kind == "directory":
        path.mkdir()
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "oversized":
        path.write_bytes(b"x" * 129)
        monkeypatch.setattr("lunar_evolution.rsi_usage._MAX_BYTES", 128)
    before = sorted(item.name for item in tmp_path.iterdir())
    with pytest.raises(RSIUsageError, match="rsi_usage_ledger_corrupt"):
        inspect_usage_ledger(path)
    assert sorted(item.name for item in tmp_path.iterdir()) == before


@pytest.mark.parametrize("change", ["receipt", "head", "duplicate_event", "extra", "duplicate_key", "invalid_json", "deep_json"])
def test_reader_validates_whole_ledger_before_filtering(tmp_path: Path, change: str):
    path = tmp_path / "usage.json"
    ledger_fixture(path)
    if change == "duplicate_key":
        path.write_text(path.read_text().replace('"schema_version":"1"', '"schema_version":"1","schema_version":"1"', 1))
    elif change == "invalid_json":
        path.write_text("{")
    elif change == "deep_json":
        path.write_text("[" * 2000 + "0" + "]" * 2000)
    else:
        state = json.loads(path.read_text())
        if change == "receipt":
            state["records"][-1]["receipt"]["wall_time_ms"] = 999
        elif change == "head":
            state["head_sha256"] = "0" * 64
        elif change == "duplicate_event":
            state["records"][-1]["receipt"]["event_id"] = "solver-1"
        else:
            state["unknown"] = True
        path.write_text(json.dumps(state))
    before = path.read_bytes()
    with pytest.raises(RSIUsageError, match="rsi_usage_ledger_corrupt"):
        inspect_usage_ledger(path, run_id="run-1")
    assert path.read_bytes() == before


@pytest.mark.parametrize("filters", [{"run_id": ""}, {"episode_id": "bad\nname"}, {"adapter_stage": 1}])
def test_invalid_filters_fail_without_opening_or_creating_files(tmp_path: Path, monkeypatch, filters):
    def unexpected_read(path):
        raise AssertionError("filters must be validated before file access")

    monkeypatch.setattr("lunar_evolution.rsi_usage._read_json", unexpected_read)
    with pytest.raises(RSIUsageError):
        inspect_usage_ledger(tmp_path / "missing.json", **filters)
    assert list(tmp_path.iterdir()) == []
