"""Exact internal observation order; fixtures do not grant execution authority.

The controller matcher and owner compositions are real. History/material
providers are deliberately small fixtures so these tests assert which fresh
read is reused, where rejection happens, and which independent read remains.
Actual SQLite, source/physical drift and complete reserved flows have their
separate regression suites.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from threading import get_ident
from types import MethodType, SimpleNamespace

import pytest

from lunar_evolution import rsi_brs_reserved_owner as reserved
from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_learning import RSILearningError


def _fixture(monkeypatch):
    events = []
    state = {"run_id": "fixture-owner", "mode": "brs", "status": "running"}
    payload = RSILearningController._python_admission_flow_payload(state)
    wave = SimpleNamespace(state=state, payload=payload, checkpoint_sha256="b" * 64,
                           active=True, owner_thread=get_ident(), checkpoint_transition=False)

    class Ledger:
        def __init__(self):
            self.history = [("a" * 64, {"initial": True}), (wave.checkpoint_sha256, deepcopy(state))]
            self.reads = 0

        def controller_checkpoint_history(self, run_id):
            assert run_id == state["run_id"]
            self.reads += 1
            events.append("history:" + str(self.reads))
            return deepcopy(self.history)

        @contextmanager
        def read_only_observations(self):
            events.append("read_scope:enter")
            try:
                yield
            finally:
                events.append("read_scope:exit")

    ledger = Ledger()
    controller = SimpleNamespace()

    def assert_wave(actual, *, owner):
        events.append("assert_wave")
        assert actual is wave and owner is True
        if not wave.active:
            raise RSILearningError("rsi_python_brs_admission_identity_invalid")

    controller._python_admission_assert_brs_wave = assert_wave
    controller._python_admission_flow_payload = RSILearningController._python_admission_flow_payload
    controller._python_admission_match_brs_owner_checkpoint = MethodType(
        RSILearningController._python_admission_match_brs_owner_checkpoint, controller)
    controller._python_admission_active_brs_owner = lambda actual: events.append("legacy_active_owner")
    controller._python_admission_assert_selected_brs = lambda *_a: events.append("selected_gate")
    prefix = SimpleNamespace(domain_bytes=b'{"episode_ids":[],"request_sha256s":[]}')
    owner = SimpleNamespace(_run_id=state["run_id"], _head=wave.checkpoint_sha256, _payload=payload,
        _ledger=ledger, _controller=controller, _wave=wave, _state=state, _ordinal=0,
        _reserved_prefix=prefix, _reserved_original_checkpoint=("a" * 64, b"{}"),
        _reserved_lineage_bytes=None, _workspace=object(), _retaining_success=None,
        _success_deadline=None, _native=None, _handoff=object())
    owner._identity = lambda **_k: events.append("identity")
    owner._success_allowance = lambda: events.append("allowance")
    owner._running = lambda: events.append("running")
    owner._before_channel = lambda: events.append("channel")
    owner._history = lambda: events.append("legacy_history")
    monkeypatch.setattr(reserved, "reserved_prefix_identity", lambda _owner: events.append("prefix_identity"))
    monkeypatch.setattr(reserved.RSILedger, "_assert_controller_lock",
                        lambda _ledger, _run_id: events.append("controller_lock"))
    monkeypatch.setattr(reserved, "_original_checkpoint", lambda value: value)
    monkeypatch.setattr(reserved, "_original_history", lambda _capture, original, history: (original, (), history))

    def observe(_ledger, _workspace, **_kwargs):
        events.append("physical")
        return prefix, ()

    monkeypatch.setattr(reserved, "_observe_reserved_brs_prefix_history", observe)
    monkeypatch.setattr(reserved, "_validate_brs_reserved_prefixes", lambda **_kwargs: ())
    monkeypatch.setattr(reserved, "_compare_reserved_history_wires", lambda *_a: events.append("compare_wires"))
    return owner, events


@pytest.mark.parametrize("method", ["_check_owner", "_success_fixed"])
def test_reserved_owner_reuses_one_complete_fresh_history_and_keeps_independent_final_read(monkeypatch, method):
    owner, events = _fixture(monkeypatch)
    assert getattr(_BRSLineageCheckpointOwner, method)(owner) is owner._state
    assert owner._ledger.reads == 2
    assert "legacy_active_owner" not in events and "legacy_history" not in events
    first = events.index("history:1")
    assert events[first + 1:first + 3] == ["assert_wave", "assert_wave"]
    assert events.index("assert_wave") < first < events.index("physical") < events.index("history:2")
    assert events.count("physical") == 1
    assert events.index("read_scope:enter") < first < events.index("history:2") < events.index("read_scope:exit")


@pytest.mark.parametrize("method", ["_check_owner", "_success_fixed"])
def test_nonreserved_owner_keeps_its_existing_active_owner_and_history_checks(monkeypatch, method):
    owner, events = _fixture(monkeypatch)
    owner._reserved_prefix = None
    assert getattr(_BRSLineageCheckpointOwner, method)(owner) is owner._state
    assert events.index("legacy_active_owner") < events.index("legacy_history")
    assert owner._ledger.reads == 0
    assert "physical" not in events


@pytest.mark.parametrize("axis", ["head", "payload", "empty", "inactive"])
def test_mismatched_fresh_head_refuses_before_any_physical_observation(monkeypatch, axis):
    owner, events = _fixture(monkeypatch)
    if axis == "head":
        owner._ledger.history[-1] = ("c" * 64, owner._ledger.history[-1][1])
    elif axis == "payload":
        owner._ledger.history[-1][1]["status"] = "unknown"
    elif axis == "empty":
        owner._ledger.history = []
    else:
        owner._wave.active = False
    with pytest.raises(RSILearningError, match="rsi_python_brs_admission_(stale|identity_invalid)"):
        reserved.reserved_history(owner, match_active_owner=True)
    assert owner._ledger.reads == 1
    assert "physical" not in events and "compare_wires" not in events


@pytest.mark.parametrize("method", ["_check_owner", "_success_fixed"])
def test_inactive_original_wave_is_rejected_before_the_reused_history_read(monkeypatch, method):
    owner, events = _fixture(monkeypatch)
    owner._wave.active = False
    with pytest.raises(RSILearningError, match="identity_invalid"):
        getattr(_BRSLineageCheckpointOwner, method)(owner)
    assert owner._ledger.reads == 0
    assert "physical" not in events


def test_physical_observer_mutating_an_older_row_is_rejected_by_independent_final_history(monkeypatch):
    owner, events = _fixture(monkeypatch)
    original_observer = reserved._observe_reserved_brs_prefix_history

    def mutate_middle(*args, **kwargs):
        result = original_observer(*args, **kwargs)
        owner._ledger.history[0][1]["initial"] = False
        return result

    monkeypatch.setattr(reserved, "_observe_reserved_brs_prefix_history", mutate_middle)
    with pytest.raises(RSILearningError, match="history_observation_changed"):
        reserved.reserved_history(owner, match_active_owner=True)
    assert owner._ledger.reads == 2
    assert events.index("physical") < events.index("history:2")
    assert owner._ledger.history[-1][0] == owner._wave.checkpoint_sha256


def test_explicit_readback_state_accepts_adjacent_durable_successor_before_wave_adoption(monkeypatch):
    owner, events = _fixture(monkeypatch)
    successor = {**deepcopy(owner._state), "python_admission_refs": {"fixture": "pinned"}}
    owner._ledger.history.append(("c" * 64, successor))
    reserved.reserved_history(owner, successor)
    assert owner._ledger.reads == 2
    assert "assert_wave" not in events
    assert owner._wave.checkpoint_sha256 == owner._head == "b" * 64
    assert owner._ledger.history[-1][0] == "c" * 64
    assert events.index("history:1") < events.index("physical") < events.index("history:2")


def test_default_no_state_reader_keeps_legal_original_cas_transition_without_matching_old_wave(monkeypatch):
    owner, events = _fixture(monkeypatch)
    owner._wave.checkpoint_transition = True
    successor = {**deepcopy(owner._state), "python_admission_refs": {"fixture": "pinned"}}
    owner._ledger.history.append(("c" * 64, successor))
    # The real retained-head helper sees the original owner pair immediately
    # before the fresh durable successor, while the live wave is still old.
    assert reserved._retained_observation_head_from_history(owner, owner._ledger.history) == "c" * 64
    reserved.reserved_history(owner)
    assert owner._ledger.reads == 2
    assert "assert_wave" not in events
    assert owner._wave.checkpoint_sha256 == "b" * 64
    assert owner._wave.payload == owner._payload


@pytest.mark.parametrize("flag,state", [(1, None), (None, None), (True, {})])
def test_internal_observation_scope_refuses_ambiguous_matching_or_readback_flags(monkeypatch, flag, state):
    owner, events = _fixture(monkeypatch)
    with pytest.raises(RSILearningError, match="history_observation_scope_invalid"):
        reserved.reserved_history(owner, state, match_active_owner=flag)
    assert owner._ledger.reads == 0
    assert "physical" not in events


def test_matcher_performs_no_extra_read_and_rechecks_original_wave_after_payload(monkeypatch):
    owner, events = _fixture(monkeypatch)
    original_payload = owner._controller._python_admission_flow_payload

    def payload_then_invalidate(value):
        result = original_payload(value)
        owner._wave.active = False
        return result

    owner._controller._python_admission_flow_payload = payload_then_invalidate
    with pytest.raises(RSILearningError, match="identity_invalid"):
        owner._controller._python_admission_match_brs_owner_checkpoint(
            owner._wave, (owner._head, json.loads(owner._payload)))
    assert events == ["assert_wave", "assert_wave"]
    assert owner._ledger.reads == 0
