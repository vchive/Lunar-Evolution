"""Original C1/no-P and publishing-FD P/no-C2 reject recovery without adoption.

Only inert process observations and the scheduler's imported writer alias are
fault seams. Original owners, SQLite/CAS, source fingerprints and retained P
pins remain authoritative; no incomplete rejection authorizes another attempt.
"""

from __future__ import annotations

import socket
import subprocess
from types import SimpleNamespace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_child_execution_flow import _Crash
from test_rsi_controller_native_rejection import _restart
from test_rsi_producer_staging_controller import _run
from test_rsi_publication_lineage_rejection_owner import _known_rejection_fixture

from lunar_evolution import rsi_native_scheduler
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemorySnapshot, RSILearningError
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_native_rejection import (
    NATIVE_RSI_REJECTION_PROVENANCE_NAME,
    persist_native_rsi_rejection_provenance,
    read_native_rsi_rejection_provenance,
)
from lunar_evolution.rsi_producer_staging_capsule import materialize_ready
from lunar_evolution.rsi_publication_lineage import multi_episode_publication_policy


@pytest.fixture(autouse=True)
def _forbid_process_and_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("V2-T5 original interruption fixture must remain inert")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def _original_c1_child(value):
    """Read actual C1 data/capsule; this never reconstructs a live owner."""
    head, state = value.ledger.controller_checkpoint(value.binding.run_id)
    episode_id = state["current_episode_id"]
    staged = state["producer_episode_staging"][episode_id]
    request = SolverRequest.from_dict(staged["identity"]["intent"]["request"])
    memory = MemorySnapshot.from_dict(staged["identity"]["memory"])
    ready = materialize_ready(
        staged["ready"], allow_capsule=True, expected_workspace=value.root,
        expected_journal_id=staged["identity"]["journal_id"],
    )
    plan = NativeRSIExecutionPlan.from_dict(ready["plan"])
    claim = value.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
    episode = value.ledger.get_episode(episode_id)
    entry = state["producer_publication_lineage"]["batches"][-1]
    batch = value.root / "evolution/producer-batches" / plan.journal_id
    return SimpleNamespace(
        checkpoint_sha256=head, state=state, request=request, memory=memory,
        plan=plan, claim=claim, episode=episode, entry=entry, batch=batch,
    )


def _all_observations(value, fixture, child):
    """Independent observations for refusal; no P pin is refreshed from disk."""
    return (
        _inventory(value.root),
        value.ledger.controller_checkpoint_history(value.binding.run_id),
        value.ledger.history(value.binding.run_id),
        value.ledger.history(child.request.episode_id),
        value.ledger.inspect_native_episode_claim(child.request, plan_sha256=child.plan.plan_sha256),
        value.ledger.episode_result(child.request.episode_id),
        tuple(fixture.observation.attempts), tuple(fixture.supplier.observations),
    )


@pytest.mark.parametrize("boundary", ["C1-no-P", "P-no-C2"], ids=["V2-T5-C1", "V2-T5-P"])
def test_original_incomplete_rejection_cannot_resume_or_adopt_orphan_provenance(
    tmp_path, monkeypatch, boundary,
):
    fixture = _known_rejection_fixture(tmp_path, monkeypatch)
    value = fixture.value
    original_writer = rsi_native_scheduler.persist_native_rsi_rejection_provenance
    assert original_writer is persist_native_rsi_rejection_provenance
    original_policy = multi_episode_publication_policy(fixture.controller)
    returned = []

    def interrupt_publishing_alias(*args, **kwargs):
        # The policy fingerprints the original helper and immutable product
        # source, never this imported scheduler alias. No pin is reauthorized.
        assert multi_episode_publication_policy(fixture.controller) == original_policy
        if boundary == "C1-no-P":
            raise _Crash("original C1 durable before P writer")
        digest, file_pin = original_writer(*args, **kwargs)
        returned.append((digest, file_pin))
        raise _Crash("original publishing-FD P durable before original-owner C2")

    # Patch only the scheduler alias, not the fingerprinted original helper or
    # any owner/ledger method. Restoring the alias restores ordinary recovery.
    with monkeypatch.context() as patch:
        patch.setattr(
            rsi_native_scheduler, "persist_native_rsi_rejection_provenance", interrupt_publishing_alias,
        )
        assert multi_episode_publication_policy(fixture.controller) == original_policy
        with pytest.raises(_Crash):
            _run(fixture.controller, value)
    assert rsi_native_scheduler.persist_native_rsi_rejection_provenance is original_writer
    assert multi_episode_publication_policy(fixture.controller) == original_policy
    child = _original_c1_child(value)
    assert child.entry["state"] == "rejected" and child.entry["rejection_provenance"] is None
    assert child.claim.status == "started"
    assert value.ledger.episode_result(child.request.episode_id) is None
    assert child.state["producer_publication_lineage"]["head"] is None
    assert len(child.state["producer_publication_lineage"]["batches"]) == 1
    assert len(fixture.observation.attempts) == len(fixture.supplier.observations) == 1
    assert not child.state.get("native_rejection_reconciliation_reservations")
    provenance_path = child.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME
    if boundary == "C1-no-P":
        assert returned == [] and not provenance_path.exists()
        file_pin = None  # No independent original P pin exists; never invent one.
    else:
        assert len(returned) == 1
        digest, file_pin = returned[0]  # Original writer's publishing-FD pin only.
        evidence = read_native_rsi_rejection_provenance(child.batch, expected_file_pin=file_pin)
        assert evidence.provenance_sha256 == digest
        assert evidence.lineage.checkpoint_sha256 == child.checkpoint_sha256
        assert evidence.plan == child.plan and evidence.claim == child.claim
    before = _all_observations(value, fixture, child)
    budget = child.state["budget_state"]
    for operation in ("resume", "explicit-reconcile"):
        controller = _restart(fixture)
        with pytest.raises((RSILearningError, ValueError)):
            if operation == "resume":
                controller.resume(value.binding.run_id)
            else:
                controller.reconcile_native_rejection(
                    value.binding.run_id, child.request.episode_id,
                    expected_checkpoint_sha256=child.checkpoint_sha256,
                    expected_episode_record_sha256=child.episode.record_sha256,
                    expected_claim_sha256=child.claim.claim_sha256,
                    expected_provenance_file_pin=file_pin,
                )
        assert _all_observations(value, fixture, child) == before
        assert value.ledger.controller_checkpoint(value.binding.run_id)[1]["budget_state"] == budget
    assert child.entry["rejection_provenance"] is None
