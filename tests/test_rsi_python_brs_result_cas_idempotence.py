"""Focused owner-side native result CAS idempotence and conflict gates.

These tests exercise the PB-03 selected owner boundary after the worker has
already returned. They keep the existing inert fixture and do not launch a
producer or evaluator.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest
from test_rsi_python_brs_selected_service import _fixture, _wave

from lunar_evolution import RSILearningError
from lunar_evolution.candidate_evaluation_spec import canonical_json


def _mutate_result_payload(value, episode_id: str) -> None:
    """Simulate a stale writer replacing only the immutable result bytes."""
    with sqlite3.connect(value.ledger.database) as connection:
        row = connection.execute(
            "SELECT result_payload FROM rsi_episode_results WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["solver_score"] = 9.0
        wire = canonical_json(payload, maximum=128 * 1024).decode("utf-8")
        digest = hashlib.sha256(wire.encode("utf-8")).hexdigest()
        connection.execute(
            "UPDATE rsi_episode_results SET result_payload = ?, result_sha256 = ? WHERE episode_id = ?",
            (wire, digest, episode_id),
        )


def test_selected_owner_result_cas_accepts_identical_retry_without_second_write(
    tmp_path, monkeypatch,
):
    value = _fixture(tmp_path, monkeypatch)
    original = value.ledger.accept_native_episode_result
    calls = []

    def accept_twice(request, **kwargs):
        first = original(request, **kwargs)
        second = original(request, **kwargs)
        calls.append((first, second))
        return second

    monkeypatch.setattr(value.ledger, "accept_native_episode_result", accept_twice)
    with _wave(value) as wave:
        execution = value.controller._python_admission_run_selected_brs_intent(wave)

    assert len(calls) == 1
    first, second = calls[0]
    assert first == second
    assert value.ledger.episode_result(value.episode_id) == (execution.request, execution.result)


def test_selected_owner_result_cas_rejects_existing_payload_drift(
    tmp_path, monkeypatch,
):
    value = _fixture(tmp_path, monkeypatch)
    original = value.ledger.accept_native_episode_result
    calls = []

    def accept_then_drift(request, **kwargs):
        accepted = original(request, **kwargs)
        _mutate_result_payload(value, request.episode_id)
        calls.append(accepted)
        return original(request, **kwargs)

    monkeypatch.setattr(value.ledger, "accept_native_episode_result", accept_then_drift)
    with _wave(value) as wave, pytest.raises(RSILearningError, match="selected_result_invalid"):
        value.controller._python_admission_run_selected_brs_intent(wave)

    assert len(calls) == 1
    saved = value.ledger.episode_result(value.episode_id)
    assert saved is not None
    assert saved[0].episode_id == value.episode_id
    assert saved[1].solver_score == 9.0
