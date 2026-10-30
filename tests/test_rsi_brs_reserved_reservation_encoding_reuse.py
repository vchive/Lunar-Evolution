"""Reservation walks retain fresh rows while reusing only local baseline bytes."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

import pytest
from test_rsi_brs_reserved_reservation import _read, _setup

from lunar_evolution import rsi_brs_reserved_ledger as reserved_ledger
from lunar_evolution import rsi_brs_reserved_reservation as reservation
from lunar_evolution.rsi_learning import RSILearningError


def _with_idle_history(tmp_path):
    controller, ids, state, history = _setup(tmp_path)
    head = history[-1][0]
    with controller.ledger.controller_lock("reserved-brs"):
        for _ in range(3):
            later = deepcopy(state)
            later.update(phase="selected", current_episode_id=ids[0])
            head = controller.ledger.write_controller_checkpoint(
                "reserved-brs", later, expected_sha256=head,
            )
    return controller, ids, head


def test_baseline_encoding_is_local_and_each_history_value_is_encoded(tmp_path, monkeypatch):
    controller, ids, head = _with_idle_history(tmp_path)
    history_size = len(controller.ledger.controller_checkpoint_history("reserved-brs"))
    original_decode, original_raw = reservation.strict_json, reservation._raw
    original_rows = reserved_ledger._read_reserved_rows
    decoded, encoded, row_reads = [], [], []

    def decode(value, **options):
        result = original_decode(value, **options)
        decoded.append(result)
        return result

    def raw(value):
        encoded.append(value)
        return original_raw(value)

    def rows(*args, **kwargs):
        row_reads.append(None)
        return original_rows(*args, **kwargs)

    monkeypatch.setattr(reservation, "strict_json", decode)
    monkeypatch.setattr(reservation, "_raw", raw)
    monkeypatch.setattr(reserved_ledger, "_read_reserved_rows", rows)
    first_plans = []
    for _ in range(2):
        decoded.clear()
        encoded.clear()
        row_reads.clear()
        with controller.ledger.controller_lock("reserved-brs"):
            observed = _read(controller, ids, head)
        assert observed.ledger.checkpoint_sha256 == head
        # Reservation decodes the H journal rows, followed by the original run.
        assert len(decoded) == history_size + 1
        plans = [state["plan"] for state in decoded[:history_size]]
        first_plans.append(plans[0])
        counts = Counter(id(value) for value in encoded)
        # The first actual and its baseline retain the original two encodings.
        assert counts[id(plans[0])] == 2
        assert all(counts[id(plan)] == 1 for plan in plans[1:])
        # Both ledger observations still perform both independent raw snapshots.
        assert len(row_reads) == 4
    assert first_plans[0] is not first_plans[1]


def test_later_actual_fixed_field_is_not_replaced_by_baseline_bytes(tmp_path, monkeypatch):
    controller, ids, head = _with_idle_history(tmp_path)
    original_decode, original_raw = reservation.strict_json, reservation._raw
    decoded, encoded = [], []

    def decode(value, **options):
        result = original_decode(value, **options)
        if len(decoded) == 1:
            result["memory_snapshot"] = {"later": "different"}
        decoded.append(result)
        return result

    def raw(value):
        encoded.append(value)
        return original_raw(value)

    monkeypatch.setattr(reservation, "strict_json", decode)
    monkeypatch.setattr(reservation, "_raw", raw)
    with controller.ledger.controller_lock("reserved-brs"), pytest.raises(
        RSILearningError, match="rsi_brs_reserved_reservation_original_drift",
    ):
        _read(controller, ids, head)
    assert any(value is decoded[1]["memory_snapshot"] for value in encoded)


@pytest.mark.parametrize("fault, code", [
    ("control", "control_changed"),
    ("attempt", "attempt_shape_invalid"),
])
def test_first_row_refusals_precede_invalid_future_baseline_encoding(
    tmp_path, monkeypatch, fault, code,
):
    controller, ids, head = _with_idle_history(tmp_path)
    original_decode = reservation.strict_json
    decoded = []

    def decode(value, **options):
        result = original_decode(value, **options)
        if not decoded:
            # This is a detached decode fault: the lower ledger observer still
            # reads the genuine fixture. No invalid JSON is written to SQLite.
            result["memory_snapshot"] = {"invalid_utf8": "\ud800"}
            if fault == "control":
                result["status"] = "completed"
            else:
                result["executions"] = []
        decoded.append(result)
        return result

    monkeypatch.setattr(reservation, "strict_json", decode)
    with controller.ledger.controller_lock("reserved-brs"), pytest.raises(
        RSILearningError, match="rsi_brs_reserved_reservation_" + code,
    ):
        _read(controller, ids, head)


def test_earlier_fixed_drift_precedes_later_field_encoding(tmp_path, monkeypatch):
    controller, ids, head = _with_idle_history(tmp_path)
    original_decode = reservation.strict_json
    decoded = []

    def decode(value, **options):
        result = original_decode(value, **options)
        if len(decoded) == 1:
            result["run_id"] = "changed-run"
            result["memory_snapshot"] = {"invalid_utf8": "\ud800"}
        decoded.append(result)
        return result

    monkeypatch.setattr(reservation, "strict_json", decode)
    with controller.ledger.controller_lock("reserved-brs"), pytest.raises(
        RSILearningError, match="rsi_brs_reserved_reservation_original_drift",
    ):
        _read(controller, ids, head)
