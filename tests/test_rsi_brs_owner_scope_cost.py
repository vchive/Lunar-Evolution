"""Owner scope retains row reuse and complete wire/physical observations."""
from __future__ import annotations

from threading import get_ident, local

import pytest
from test_rsi_brs_reserved_history_projection import _calls, _case, _compare

from lunar_evolution import rsi_brs_reserved_owner as reserved
from lunar_evolution.rsi_controller import RSILearningController, _PythonAdmissionBRSWave
from lunar_evolution.rsi_store import RSILedger


def _scope(tmp_path):
    controller = object.__new__(RSILearningController)
    controller._python_admission_brs_local = local()
    controller.ledger = RSILedger(tmp_path / "ledger")
    owner, history, prefixes, observations = _case(tmp_path)
    wave = _PythonAdmissionBRSWave(
        controller, {}, "run", (), controller.ledger, tmp_path, object(),
        get_ident(), "a" * 64, b"{}", object(), {},
    )
    owner._wave = wave
    return controller, wave, owner, history, prefixes, observations


def test_owner_scope_does_all_wire_and_shape_work_without_optional_graph_cache(tmp_path, monkeypatch):
    controller, wave, owner, history, prefixes, observations = _scope(tmp_path)
    monkeypatch.setattr(reserved, "_reserved_history_projection_guard",
                        lambda: pytest.fail("optional policy graph must not be enabled by owner scope"))
    with controller._python_admission_brs_full_gate_scope(wave, owner._handoff):
        assert controller.ledger._checkpoint_projection_local.cache is not None
        assert getattr(reserved._HISTORY_PROJECTION_LOCAL, "cache", None) is None
        with _calls(observations) as counts:
            _compare(owner, history, prefixes)
            _compare(owner, history, prefixes)
        # The profiler reports a generator call on initial entry and each
        # resumption: two yielded shape entries plus exhaustion per comparison.
        assert counts["wire"] == 6
        assert counts["c1"] == counts["c2"] == 2
        assert counts["shape"] == counts["source_maps"] == 4
        assert observations == [history[0][1]["producer_publication_lineage"]["batches"][-1],
                                history[1][1]["producer_publication_lineage"]["batches"][-1]] * 2


@pytest.mark.parametrize("interrupt", [False, True])
def test_nested_owner_scope_retains_row_cache_and_releases_both_caches(tmp_path, interrupt):
    controller, wave, owner, _history, _prefixes, _observations = _scope(tmp_path)
    cache = None
    try:
        with controller._python_admission_brs_full_gate_scope(wave, owner._handoff):
            full = controller._python_admission_brs_local.full_gate_scope
            cache = controller.ledger._checkpoint_projection_local.cache
            cache["entries"]["inert"] = ("inert", 1)
            cache["retained_units"] = 1
            with controller._python_admission_brs_full_gate_scope(wave, owner._handoff):
                assert controller._python_admission_brs_local.full_gate_scope is full
                assert controller.ledger._checkpoint_projection_local.cache is cache
                assert getattr(reserved._HISTORY_PROJECTION_LOCAL, "cache", None) is None
                if interrupt:
                    raise KeyboardInterrupt
    except KeyboardInterrupt:
        assert interrupt
    assert cache is not None and not cache["entries"] and cache["retained_units"] == 0
    assert controller.ledger._checkpoint_projection_local.cache is None
    assert controller._python_admission_brs_local.full_gate_scope is None
    assert getattr(reserved._HISTORY_PROJECTION_LOCAL, "cache", None) is None
