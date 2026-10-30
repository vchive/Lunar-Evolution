"""Original C1/P/C2 retains every callback boundary and one final fixed gate.

Profiling observes original implementations; it does not replace validators or
grant owner authority. The shared fixture keeps its inert worker waiting.
"""

from __future__ import annotations

import sys
from collections import Counter
from contextlib import contextmanager

import pytest
import test_rsi_brs_rejection_provenance as provenance_fixture

from lunar_evolution import rsi_brs_rejection_provenance as provenance
from lunar_evolution.rsi_fingerprint import RSIFingerprintError
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native_rejection import read_native_rsi_rejection_provenance
from lunar_evolution.rsi_store import RSILedger

inert_only = provenance_fixture.inert_only
tmp_path = provenance_fixture.tmp_path
sealed_launch = provenance_fixture.sealed_launch


@contextmanager
def _profile(callback):
    previous = sys.getprofile()
    sys.setprofile(callback)
    try:
        yield
    finally:
        sys.setprofile(previous)


def test_original_retention_keeps_one_complete_fixed_gate_per_observation(tmp_path, monkeypatch):
    with provenance_fixture.c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        captured = provenance_fixture.c1.owner_fixture._capture(value)
        original_files = provenance_fixture._original_files(value)
        counts, fixed_callers, fixed_sql = Counter(), [], []
        active_fixed = []
        targets = {getattr(provenance, name).__code__: name for name in (
            "_observe", "_fixed", "_fresh", "_control", "_policy_gate", "_readback",
        )}
        sql = RSILedger._controller_checkpoint_history_observation_tx.__code__

        def observe(frame, event, _argument):
            if event == "call" and frame.f_code in targets:
                name = targets[frame.f_code]
                counts[name] += 1
                if name == "_fixed":
                    fixed_callers.append(frame.f_back.f_code)
                    fixed_sql.append(0)
                    active_fixed.append(len(fixed_sql) - 1)
            elif event == "return" and frame.f_code is provenance._fixed.__code__:
                active_fixed.pop()
            if event == "call" and frame.f_code is sql:
                counts["complete_sql"] += 1
                if active_fixed:
                    fixed_sql[active_fixed[-1]] += 1

        with _profile(observe):
            value.owner.retain_rejection_provenance()

        # The five original observations retain their callbacks, fresh material
        # reads and final owner gates. Only three adjacent outer duplicates go.
        assert {name: counts[name] for name in targets.values()} == {
            "_observe": 5, "_fixed": 5, "_fresh": 5, "_control": 6,
            "_policy_gate": 3, "_readback": 2,
        }
        assert fixed_callers == [provenance._observe.__code__] * 5
        assert len(fixed_sql) == 5 and all(count > 0 for count in fixed_sql)
        assert counts["complete_sql"] >= sum(fixed_sql)
        owner = value.owner
        reference = value.wave.state[provenance_fixture._FIELD]["batches"][0]["rejection_provenance"]
        pin = owner._rejection_provenance_file_pin
        evidence = read_native_rsi_rejection_provenance(value.batch, expected_file_pin=pin)
        assert reference == {"provenance_sha256": evidence.provenance_sha256, "file_pin": pin.to_dict()}
        assert evidence.plan == value.plan and evidence.terminal == value.terminal
        assert owner._phase == "rejected-provenance" and not owner._poisoned
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        assert history[-2:] == [(captured[0], captured[2]), (owner._head, value.wave.state)]
        assert provenance_fixture._original_files(value) == original_files
        provenance_fixture.c1._quiet(value)


@pytest.mark.parametrize("fault", ["source", "cancelled"])
def test_original_observation_still_refuses_source_or_control_drift_before_p(tmp_path, monkeypatch, fault):
    with provenance_fixture.c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        captured = provenance_fixture.c1.owner_fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        original_files = provenance_fixture._original_files(value)
        observed, changed = [], []

        def observe(frame, event, _argument):
            if event == "call" and frame.f_code is provenance._observe.__code__:
                observed.append(frame)
                if len(observed) == 2 and fault == "source":
                    value.gateway.fingerprint = "changed-at-original-observation"
                    changed.append(fault)
            if (event == "return" and frame.f_code is provenance._control.__code__
                    and len(observed) == 2 and fault == "cancelled" and not changed):
                with value.owner._before_control._lock:
                    value.owner._before_control._cancelled = True
                changed.append(fault)

        expected_error = RSIFingerprintError if fault == "source" else RSILearningError
        with _profile(observe), pytest.raises(expected_error) as raised:
            value.owner.retain_rejection_provenance()

        if fault == "source":
            assert raised.value.code == "rsi_fingerprint_drift"
            assert raised.value.reasons == ("actor_fingerprint_changed",)
        else:
            assert str(raised.value) == "rsi_brs_rejection_provenance_cancelled"
        assert changed == [fault]
        provenance_fixture.c1.owner_fixture._unchanged(value, captured)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert provenance_fixture._original_files(value) == original_files
        assert not provenance_fixture._path(value).exists() and value.owner._poisoned
        assert value.owner._retaining_rejection_provenance is False
        assert value.owner._rejection_provenance_deadline is None
        provenance_fixture.c1._quiet(value)
