"""Original controller refusal at native-record and rejected-terminal early gaps.

The fault injection does not replace owner/ledger/checkpoint or add
receipt/recovery seams; the original fixture keeps its inert native process
observations. The terminal-before-C1 case calls the original finalizer and loses
its stack before the original owner can retain C1.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from types import SimpleNamespace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_child_execution_flow import _Crash
from test_rsi_controller_native_rejection import _restart
from test_rsi_producer_staging_controller import _run
from test_rsi_publication_lineage_rejection_owner import _known_rejection_fixture

from lunar_evolution import producer_bundle_rejection, producer_bundle_transaction
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemorySnapshot, RSILearningError
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_native_provenance_names import NATIVE_RSI_PROVENANCE_NAMES
from lunar_evolution.rsi_producer_staging_capsule import materialize_ready
from lunar_evolution.rsi_publication_lineage import multi_episode_publication_policy


@pytest.fixture(autouse=True)
def _forbid_process_and_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("V2-T5 early interruption fixture must remain inert")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def _original_interrupted_child(value):
    """Read actual durable ready data; never manufacture a C1 or native owner."""
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
    batch = value.root / "evolution/producer-batches" / plan.journal_id
    return SimpleNamespace(
        checkpoint_sha256=head, state=state, request=request, memory=memory,
        plan=plan, claim=claim, episode=episode, batch=batch,
    )


def _all_observations(value, fixture, child):
    return (
        _inventory(value.root),
        value.ledger.controller_checkpoint_history(value.binding.run_id),
        value.ledger.history(value.binding.run_id),
        value.ledger.history(child.request.episode_id),
        value.ledger.inspect_native_episode_claim(child.request, plan_sha256=child.plan.plan_sha256),
        value.ledger.episode_result(child.request.episode_id),
        tuple(fixture.observation.attempts), tuple(fixture.supplier.observations),
        tuple(fixture.observation.handoffs),
    )


@pytest.mark.parametrize(
    "boundary", ["no-native-terminal", "partial-native-terminal", "terminal-before-C1"],
    ids=["V2-T5-NO-TERMINAL", "V2-T5-PARTIAL", "V2-T5-TERMINAL-BEFORE-C1"],
)
def test_original_early_interruption_retains_started_and_refuses_recovery(
    tmp_path, monkeypatch, boundary,
):
    fixture = _known_rejection_fixture(tmp_path, monkeypatch)
    value = fixture.value
    observation = fixture.observation
    original_policy = multi_episode_publication_policy(fixture.controller)
    interrupted = []
    terminals = []
    partial_raw = b'{"protocol":"lunar-native-trusted-process-terminal-v1"'
    original_write = observation._write
    original_finalizer = producer_bundle_transaction.finalize_producer_bundle_all_rejected
    assert original_finalizer is producer_bundle_rejection.finalize_producer_bundle_all_rejected

    def interrupt_native_record(path, payload):
        if path.name != "native-trusted-process-terminal.json":
            return original_write(path, payload)
        assert multi_episode_publication_policy(fixture.controller) == original_policy
        interrupted.append(boundary)
        if boundary == "partial-native-terminal":
            # This lowest inert process observation retains a real incomplete
            # file, with no invented identity/digest or successful terminal pin.
            with path.open("xb") as stream:
                stream.write(partial_raw)
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(0o600)
        raise _Crash(boundary)

    def interrupt_before_c1(*args, **kwargs):
        assert multi_episode_publication_policy(fixture.controller) == original_policy
        terminal = original_finalizer(*args, **kwargs)
        terminals.append(terminal)
        interrupted.append(boundary)
        # Native/candidate receipts and the rejection terminal are original.
        # The imported alias returns no terminal to the original owner/CAS.
        raise _Crash(boundary)

    with monkeypatch.context() as patch:
        if boundary == "terminal-before-C1":
            patch.setattr(
                producer_bundle_transaction, "finalize_producer_bundle_all_rejected", interrupt_before_c1,
            )
        else:
            patch.setattr(observation, "_write", interrupt_native_record)
        assert multi_episode_publication_policy(fixture.controller) == original_policy
        with pytest.raises(_Crash, match=boundary):
            _run(fixture.controller, value)
    assert interrupted == [boundary]
    assert producer_bundle_transaction.finalize_producer_bundle_all_rejected is original_finalizer
    assert multi_episode_publication_policy(fixture.controller) == original_policy

    child = _original_interrupted_child(value)
    assert child.claim.status == "started" and child.episode.state == "running"
    assert value.ledger.get_run(value.binding.run_id).state == "running"
    assert value.ledger.episode_result(child.request.episode_id) is None
    assert child.state["budget_state"]["consumed"]["solver_invocations"] == 1
    assert not child.state.get("native_rejection_reconciliation_reservations")
    assert len(observation.attempts) == len(fixture.supplier.observations) == 1
    assert not any((child.batch / name).exists() for name in NATIVE_RSI_PROVENANCE_NAMES)

    terminal_path = child.batch / "native-trusted-process-terminal.json"
    lineage = child.state.get("producer_publication_lineage")
    if boundary == "terminal-before-C1":
        assert len(terminals) == 1
        assert json.loads((child.batch / "journal.json").read_bytes()) == terminals[0].to_dict()
        assert terminals[0].state == "all_rejected" and terminal_path.is_file()
        assert (child.batch / "execution-receipt.json").is_file()
        assert (child.batch / "rejections.json").is_file()
        assert lineage["head"] is None and lineage["rejections"] == []
        assert len(lineage["batches"]) == 1 and lineage["batches"][0]["state"] == "before"
        assert "rejection_provenance" not in lineage["batches"][0]
        assert len(observation.handoffs) == 1
    else:
        assert terminals == [] and lineage is None
        assert not (child.batch / "execution-receipt.json").exists()
        assert not (child.batch / "journal.prepared.json").exists()
        assert observation.handoffs == []
        assert terminal_path not in observation.pins
        if boundary == "partial-native-terminal":
            assert terminal_path.read_bytes() == partial_raw
        else:
            assert not terminal_path.exists()
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
                    expected_provenance_file_pin=None,  # No original P exists; do not invent its pin.
                )
        assert _all_observations(value, fixture, child) == before
        assert value.ledger.controller_checkpoint(value.binding.run_id)[1]["budget_state"] == budget
