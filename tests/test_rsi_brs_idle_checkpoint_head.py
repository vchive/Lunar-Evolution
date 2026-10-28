"""An idle tail observation never substitutes for a complete admission gate."""
from __future__ import annotations

import sqlite3

import pytest
from test_rsi_python_brs_owner import _brs_fixture, _wave

from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger


def test_idle_owner_observes_fresh_tail_without_rewalking_admission_history(tmp_path, monkeypatch):
    value = _brs_fixture(tmp_path)
    with _wave(value) as wave:
        expected = value.controller._python_admission_active_brs_owner(wave)
        original = RSILedger._controller_checkpoint_history_tx

        def forbidden(*args, **kwargs):
            pytest.fail("idle-only tail check unexpectedly walked the complete history")

        with monkeypatch.context() as patch:
            patch.setattr(RSILedger, "_controller_checkpoint_history_tx", forbidden)
            for _ in range(2):
                assert value.controller._python_admission_active_brs_owner(wave, idle_poll=True) == expected
        assert RSILedger._controller_checkpoint_history_tx is original
        assert value.controller._python_admission_active_brs_owner(wave) == expected


@pytest.mark.parametrize("field,value", [("payload", "{}"), ("checkpoint_sha256", "a" * 64),
                                         ("parent_sha256", "b" * 64)])
def test_idle_refuses_actual_tail_drift_before_return(tmp_path, field, value):
    fixture = _brs_fixture(tmp_path)
    with _wave(fixture) as wave:
        with sqlite3.connect(fixture.ledger.database) as connection:
            connection.execute(
                f"UPDATE rsi_controller_journal SET {field} = ? WHERE run_id = ? AND revision = "
                "(SELECT MAX(revision) FROM rsi_controller_journal WHERE run_id = ?)",
                (value, wave.run_id, wave.run_id),
            )
        with pytest.raises(RSILearningError):
            fixture.controller._python_admission_active_brs_owner(wave, idle_poll=True)


def test_unchanged_tail_never_approves_corrupt_middle_history(tmp_path):
    value = _brs_fixture(tmp_path)
    with _wave(value) as wave:
        expected = value.controller._python_admission_active_brs_owner(wave)
        with sqlite3.connect(value.ledger.database) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM rsi_controller_journal WHERE run_id = ?", (wave.run_id,),
            ).fetchone()[0]
            assert count > 1
            connection.execute(
                "UPDATE rsi_controller_journal SET payload = '{}' WHERE run_id = ? AND revision = 0",
                (wave.run_id,),
            )
        assert value.controller._python_admission_active_brs_owner(wave, idle_poll=True) == expected
        # This is the unchanged full gate used for a pending event/final join.
        # Idle returned no ACK, receipt or admission capability.
        with pytest.raises(RSILearningError, match="checkpoint_corrupt"):
            value.controller._python_admission_active_brs_owner(wave)


def test_idle_reader_requires_original_controller_lock(tmp_path):
    value = _brs_fixture(tmp_path)
    with pytest.raises(RSILearningError, match="controller_lock_required"):
        value.ledger._controller_checkpoint_idle_head(value.binding.run_id)


def test_idle_result_is_fresh_and_not_a_retained_mutable_payload(tmp_path):
    value = _brs_fixture(tmp_path)
    with _wave(value) as wave:
        first = value.ledger._controller_checkpoint_idle_head(wave.run_id)
        second = value.ledger._controller_checkpoint_idle_head(wave.run_id)
        assert first == second and first[1] is not second[1]
        first[1].clear()
        assert value.ledger._controller_checkpoint_idle_head(wave.run_id) == second
