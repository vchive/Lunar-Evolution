"""Original C2 evidence through successive durable reconcile crash boundaries.

Only the original fixture's process observations and lowest evaluator seam are
inert. Owner, SQLite/CAS, native evidence, P pins and controller recovery are real.
"""

from __future__ import annotations

import socket
import subprocess
from dataclasses import replace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_child_execution_flow import _Crash
from test_rsi_producer_staging_controller import _run
from test_rsi_publication_lineage_rejection_owner import (
    _known_rejection_fixture,
    _original_c2,
)

from lunar_evolution import RSILearningController
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, RSILearningError
from lunar_evolution.rsi_native_gateway import NativeRSISolverGatewayError


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("rejection reconcile fixture attempted process or network")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def _restart(fixture):
    value = fixture.value
    return RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.root, producer_stager=fixture.controller.producer_stager,
        producer_child_execution=True, producer_multi_episode_publication=True,
        producer_known_rejection=True,
    )


def test_original_c2_reconcile_crash_sequence_reuses_one_budget_and_never_dispatches(tmp_path, monkeypatch):
    fixture = _known_rejection_fixture(tmp_path, monkeypatch)
    value = fixture.value

    def lose_owner_before_result(*_args, **_kwargs):
        raise _Crash("original C2 persisted; native result not saved")

    with monkeypatch.context() as patch:
        patch.setattr(value.ledger, "publish_native_episode_result", lose_owner_before_result)
        with pytest.raises(_Crash):
            _run(fixture.controller, value)
    held = _original_c2(value)
    assert held.claim.status == "started" and value.ledger.episode_result(held.request.episode_id) is None
    assert held.entry["state"] == "rejected" and held.entry["rejection_provenance"] is not None
    pins = {
        "expected_checkpoint_sha256": held.checkpoint_sha256,
        "expected_episode_record_sha256": held.episode.record_sha256,
        "expected_claim_sha256": held.claim.claim_sha256,
        "expected_provenance_file_pin": held.file_pin,
    }
    original_history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    original_budget = held.state["budget_state"]
    attempts = tuple(fixture.observation.attempts)
    supplier_calls = tuple(fixture.supplier.observations)
    original_files = _inventory(value.root)

    def reconcile(controller, supplied=pins):
        return controller.reconcile_native_rejection(value.binding.run_id, held.request.episode_id, **supplied)

    # Invalid independent pins cannot spend the evidence quota or change an episode.
    for key in pins:
        changed = replace(held.file_pin, inode=held.file_pin.inode + 1) if key.endswith("file_pin") else "f" * 64
        with pytest.raises((RSILearningError, NativeRSISolverGatewayError, ValueError)):
            reconcile(_restart(fixture), {**pins, key: changed})
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == original_history
        assert value.ledger.episode_result(held.request.episode_id) is None

    # These are successive interruptions of one original recovery transaction.
    # Each step retains the actual preceding durable write, rather than constructing
    # a synthetic C2/head or rerunning the producer for another crash case.
    for boundary in ("reservation", "result", "episode", "checkpoint"):
        controller = _restart(fixture)
        if boundary in {"reservation", "checkpoint"}:
            original = controller._save_flow

            def crash_after_checkpoint(record, state, *, _original=original, _boundary=boundary):
                _original(record, state)
                if _boundary == "reservation" or held.request.episode_id in state["executions"]:
                    raise _Crash(_boundary)

            target, name, crash = controller, "_save_flow", crash_after_checkpoint
        elif boundary == "result":
            original = value.ledger.publish_native_episode_result

            def crash_after_result(*args, _original=original, **kwargs):
                _original(*args, **kwargs)
                raise _Crash("result")

            target, name, crash = value.ledger, "publish_native_episode_result", crash_after_result
        else:
            original = value.ledger.reconcile_episode

            def crash_after_episode(*args, _original=original, **kwargs):
                _original(*args, **kwargs)
                raise _Crash("episode")

            target, name, crash = value.ledger, "reconcile_episode", crash_after_episode
        with monkeypatch.context() as patch:
            patch.setattr(target, name, crash)
            with pytest.raises(_Crash, match=boundary):
                reconcile(controller)
        current = value.ledger.controller_checkpoint(value.binding.run_id)[1]
        assert current["budget_state"]["consumed"]["unknown_retries"] == original_budget["consumed"]["unknown_retries"] + 1
        assert current["budget_state"]["consumed"]["solver_invocations"] == 1
        assert current["judgments"] == held.state["judgments"] and current["decisions"] == held.state["decisions"]
        assert current["phase"] == held.state["phase"] and current["status"] == held.state["status"]
        assert controller.snapshot == EMPTY_MEMORY_SNAPSHOT
        assert tuple(fixture.observation.attempts) == attempts
        assert tuple(fixture.supplier.observations) == supplier_calls
        assert _inventory(value.root) == original_files

    settled = reconcile(_restart(fixture))
    assert settled.result.status == "failed" and settled.result.terminal_reason == "native_all_rejected"
    assert not settled.passed and settled.request.memory_snapshot_sha256 == EMPTY_MEMORY_SNAPSHOT.digest()
    before = value.ledger.controller_checkpoint_history(value.binding.run_id)
    assert reconcile(_restart(fixture)) == settled
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == before
    assert len(value.ledger.episode_reconciliation(held.request.episode_id)) == 1
    assert tuple(fixture.observation.attempts) == attempts and tuple(fixture.supplier.observations) == supplier_calls
    assert _inventory(value.root) == original_files
