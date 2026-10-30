"""Explicit per-observation roots preserve fresh SQL and physical boundaries.

These empty-prefix SQLite fixtures exercise reader data flow, not producer or
worker authority. Original-owner callback checks reuse the existing inert native
owner fixture; no producer, evaluator, model or network process is launched.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from threading import get_ident
from types import SimpleNamespace

import pytest
import test_rsi_python_brs_native_dispatch as native_fixture
from test_rsi_brs_reserved_owner import _fixture, _read

from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution import rsi_brs_reserved_ledger as reserved_ledger
from lunar_evolution import rsi_brs_reserved_owner as reserved_owner
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger

inert_only = native_fixture.inert_only


@contextmanager
def _profile(callback):
    previous = sys.getprofile()
    sys.setprofile(callback)
    try:
        yield
    finally:
        sys.setprofile(previous)


def _empty_owner(tmp_path, *, wave):
    value = _fixture(tmp_path, ())
    # Keep a genuine older row so exit checks cannot accidentally become
    # comparisons of only the newest head/payload.
    value.state = {**deepcopy(value.state), "phase": "evaluated"}
    with value.ledger.controller_lock("observed"):
        value.head = value.ledger.write_controller_checkpoint("observed", value.state, expected_sha256=value.head)
        prefix, _batches = _read(value)
    owner = object.__new__(_BRSLineageCheckpointOwner)
    owner._workspace, owner._ledger, owner._run_id = value.workspace, value.ledger, "observed"
    owner._head, owner._payload, owner._state = value.head, canonical_json(value.state), value.state
    owner._ordinal, owner._reserved_prefix = 0, prefix
    owner._reserved_original_checkpoint, owner._reserved_lineage_bytes = value.original, None
    owner._reserved_capture_bytes = prefix.canonical_bytes
    owner._association = {key: item for key, item in value.wire.items()
                          if key not in {"batches", "head", "rejections"}}
    owner._wave = (SimpleNamespace(owner_thread=get_ident(), payload=owner._payload,
        checkpoint_sha256=value.head, checkpoint_transition=False) if wave else None)
    return value, owner


@pytest.mark.parametrize("wave", [False, True])
@pytest.mark.parametrize("explicit_state", [False, True])
def test_one_observation_keeps_two_full_history_reads_and_all_coherent_domain_reads(
    tmp_path, wave, explicit_state,
):
    value, owner = _empty_owner(tmp_path, wave=wave)
    counts, roots = Counter(), []
    targets = {RSILedger.controller_checkpoint_history.__code__: "history",
               reserved_ledger._read_reserved_rows.__code__: "domain",
               reserved_owner._original.__code__: "independent_original"}

    def observe(frame, event, _argument):
        if event == "call" and frame.f_code in targets:
            counts[targets[frame.f_code]] += 1
        if event == "call" and frame.f_code in {
            reserved_owner._original_history.__code__,
            reserved_owner._observe_reserved_brs_prefix_history.__code__,
            reserved_owner._compare_reserved_history_wires.__code__,
        }:
            roots.append(frame.f_locals["history"])

    with value.ledger.controller_lock("observed"), _profile(observe):
        reserved_owner.reserved_history(owner, value.state if explicit_state else None)
    assert counts == {"history": 2, "domain": 4}
    assert len(roots) == 3 and all(item is roots[0] for item in roots)
    assert value.ledger.controller_checkpoint("observed") == (value.head, value.state)


def test_same_head_older_row_mutation_after_physical_prefix_observation_is_refused(tmp_path):
    value, owner = _empty_owner(tmp_path, wave=True)
    changed = []

    def observe(frame, event, _argument):
        if (not changed and event == "return"
                and frame.f_code is reserved_owner._observe_reserved_brs_prefix_history.__code__):
            payload = json.loads(value.original[1])
            payload["fixture_older_row_drift"] = True
            with sqlite3.connect(value.ledger.database) as connection:
                connection.execute("UPDATE rsi_controller_journal SET payload=? WHERE run_id=? AND revision=0",
                                   (canonical_json(payload).decode(), "observed"))
                changed.append(tuple(connection.execute(
                    "SELECT checkpoint_sha256 FROM rsi_controller_journal WHERE run_id=? ORDER BY revision",
                    ("observed",))))

    with value.ledger.controller_lock("observed"), _profile(observe), pytest.raises(RSILearningError):
        reserved_owner.reserved_history(owner)
    assert len(changed) == 1 and changed[0][-1][0] == value.head
    assert changed[0][0][0] == value.original[0]


def test_later_observation_reads_current_rows_instead_of_retaining_previous_roots(tmp_path):
    value, owner = _empty_owner(tmp_path, wave=False)
    with value.ledger.controller_lock("observed"):
        reserved_owner.reserved_history(owner)
        changed = {**value.state, "phase": "another-valid-checkpoint"}
        value.ledger.write_controller_checkpoint("observed", changed, expected_sha256=value.head)
        with pytest.raises(RSILearningError, match="checkpoint_conflict"):
            reserved_owner.reserved_history(owner)


def test_generic_evidence_callback_keeps_original_return_and_exception_behavior():
    events, marker = [], object()

    def callback(stage):
        events.append(stage)
        return marker

    assert transaction._observe_native_producer_evidence(callback, None, "generic") is None
    assert events == ["generic"]
    error = ValueError("fixture callback failure")

    def failing(_stage):
        raise error

    with pytest.raises(ValueError) as raised:
        transaction._observe_native_producer_evidence(failing, None, "generic")
    assert raised.value is error


def test_callback_attributes_or_return_cannot_skip_exact_original_owner_postgate(tmp_path, monkeypatch):
    with native_fixture._waiting(tmp_path, monkeypatch) as value:
        events = []

        def callback(stage):
            events.append(("callback", stage))
            return {"owner_checked": True}

        callback.owner_checked = True
        callback.skip_postgate = True

        def observe(frame, event, _argument):
            if event == "call" and frame.f_code is _BRSLineageCheckpointOwner._success_fixed.__code__:
                events.append(("fixed", frame.f_locals["self"]))

        with _profile(observe):
            transaction._observe_native_producer_evidence(callback, value.owner, "fixture-evidence")
        assert events == [("callback", "fixture-evidence"), ("fixed", value.owner)]
        assert not value.owner._poisoned and not (value.batch / "journal.prepared.json").exists()


def test_original_owner_mutation_in_evidence_callback_refuses_before_prepared_effect(tmp_path, monkeypatch):
    with native_fixture._waiting(tmp_path, monkeypatch) as value:
        def callback(_stage):
            value.owner._poisoned = True

        with pytest.raises(RSILearningError):
            transaction._observe_native_producer_evidence(callback, value.owner, "fixture-evidence")
        assert not (value.batch / "journal.prepared.json").exists()
        assert not (value.batch / "python-producer-admission-anchor.json").exists()


def test_nonoriginal_owner_is_refused_after_callback_without_trusting_callback_claims():
    seen = []
    with pytest.raises(RSILearningError, match="owner_invalid"):
        transaction._observe_native_producer_evidence(lambda stage: seen.append(stage), object(), "foreign")
    assert seen == ["foreign"]
