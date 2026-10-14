"""V2-T1/T2/T3 original mixed DRS acceptance, with a short basetemp.

 Only retained inert native observations and the lowest process
seams are synthetic; controller, owner/CAS, P pins, receipts, claims, capsules,
memory promotion and historical replay remain original.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
from pathlib import Path

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_multi_episode_publication_flow import (
    _fixture,
    _judged_controller,
    _ReceiptThresholdJudge,
)

from lunar_evolution import RSILearningController, candidate_evaluation
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.evolution import CandidateArchive
from lunar_evolution.producer_bundle_lineage import MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.rsi_child_gateway import resolve_python_producer_episode_gateway
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT_SHA256, MemorySnapshot
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_native_rejection import (
    NativeRSIRejectionFilePin,
    map_native_rejection_to_solver_result,
    read_native_rsi_rejection_provenance,
)
from lunar_evolution.rsi_producer_staging_capsule import (
    materialize_ready,
    retained_publication_evidence_bytes,
)

_EPISODES = ("run-1-target-0", "run-1-practice-0-0", "run-1-target-1")
_SCORES = dict(zip(_EPISODES, (0, 9, 9), strict=True))


@pytest.fixture(autouse=True)
def _forbid_process_and_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("mixed V2 acceptance must remain inert and local")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def _v2_controller(value, *, original=None):
    """Fresh or restarted exact controller; no owner/proof/ledger seam."""
    if original is None:
        original, supplier = _judged_controller(value)
    else:
        supplier = None
    assert type(original.target_judge) is _ReceiptThresholdJudge
    return RSILearningController(
        value.gateway, ledger=value.ledger, producer_workspace=value.root,
        producer_sidecar=value.sidecar, producer_stager=original.producer_stager,
        producer_child_execution=True, producer_multi_episode_publication=True,
        producer_known_rejection=True, target_judge=original.target_judge,
    ), supplier


def _mixed_fixture(tmp_path, monkeypatch, outcomes):
    value, original, supplier, observation = _fixture(tmp_path, monkeypatch)
    controller, _unused = _v2_controller(value, original=original)
    observation.controller = controller
    passed_process = candidate_evaluation._bounded_process_bytes
    intended = dict(zip(_EPISODES, outcomes, strict=True))
    evaluations = []

    def evaluator(command, *, cwd, process_observer=None, process_released=None,
                  process_exit_observed=None, continuation_guard=None, **kwargs):
        assert "evaluator.py" in command
        _head, state = value.ledger.controller_checkpoint(value.binding.run_id)
        episode_id = state["current_episode_id"]
        assert episode_id in intended
        evaluations.append((episode_id, intended[episode_id]))
        if intended[episode_id] == "P":
            # Retain the original native pass report and all original receipts.
            return passed_process(
                command, cwd=cwd, process_observer=process_observer,
                process_released=process_released, process_exit_observed=process_exit_observed,
                continuation_guard=continuation_guard, **kwargs,
            )
        root = Path(cwd)
        assert json.loads((root / "output/result.json").read_bytes()) == {"value": _SCORES[episode_id]}
        if continuation_guard is not None:
            continuation_guard()
        if process_observer is not None:
            process_observer(4242, 4242)
        stdout = canonical_json({
            "schema_version": "1", "evaluator_id": "bundle-population-fixture",
            "validity": 0, "quality": None, "combined_score": 0.0,
            "detailed_scores": {},
            "error_info": [{"code": "fixture_rejected", "message": "Inert candidate rejected."}],
        })
        if process_exit_observed is not None:
            process_exit_observed(0)
        if process_released is not None:
            process_released(4242, 4242)
        if continuation_guard is not None:
            continuation_guard()
        return stdout, b"", "succeeded", 0, None

    # No shape, receipt builder, mapper, owner, CAS or evidence reader is patched.
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", evaluator)
    return value, controller, supplier, observation, evaluations


def _held_child(value, state, execution):
    staged = state["producer_episode_staging"][execution.request.episode_id]
    memory = MemorySnapshot.from_dict(staged["identity"]["memory"])
    ready = materialize_ready(
        staged["ready"], allow_capsule=True, expected_workspace=value.root,
        expected_journal_id=staged["identity"]["journal_id"],
    )
    plan = NativeRSIExecutionPlan.from_dict(ready["plan"])
    claim = value.ledger.inspect_native_episode_claim(execution.request, plan_sha256=plan.plan_sha256)
    assert plan.request == execution.request and memory.digest() == execution.request.memory_snapshot_sha256
    assert value.ledger.episode_result(execution.request.episode_id) == (execution.request, execution.result)
    return memory, plan, claim


@pytest.mark.parametrize("outcomes", ["RPP", "PRP", "RRR"],
                         ids=["V2-T1-RPP", "V2-T2-PRP", "V2-T3-RRR"])
def test_original_three_attempt_mixed_drs_and_terminal_readonly_replay(tmp_path, monkeypatch, outcomes):
    value, controller, supplier, observation, evaluations = _mixed_fixture(tmp_path, monkeypatch, outcomes)
    original_gateway, original_sidecar = controller.gateway, controller.producer_sidecar
    archive_path = value.root / "evolution/archive.jsonl"
    genesis_archive = archive_path.read_bytes() if archive_path.exists() else None
    genesis_state = (value.root / "evolution/state.json").read_bytes()
    result = controller.run_drs(
        run_id=value.binding.run_id, contract_sha256=value.request.contract_sha256,
        evaluator_sha256=value.request.evaluator_sha256,
        environment_sha256=value.request.environment_sha256,
        solver_id=value.request.solver_id, max_practice_rounds=1, max_target_attempts=2,
        budget=dict(value.request.budget),
    )
    assert result.status == ("failed" if outcomes == "RRR" else "completed")
    assert len(result.target_attempts) == 2 and len(result.practice_episodes) == 1
    executions = (result.target_attempts[0], result.practice_episodes[0], result.target_attempts[1])
    assert tuple(item.request.episode_id for item in executions) == _EPISODES
    assert tuple("R" if item.result.status == "failed" else "P" for item in executions) == tuple(outcomes)
    assert evaluations == list(zip(_EPISODES, outcomes, strict=True))
    assert all(item.result.solver_score is None for item in executions)
    if outcomes == "RPP":
        assert result.practice_episodes[0].passed
        assert len(result.memory_snapshot.items) == 1
        assert result.memory_snapshot.items[0].memory_id == "memory-run-1-practice-0-0"
        assert result.memory_snapshot.digest() != EMPTY_MEMORY_SNAPSHOT_SHA256
        expected_memories = (EMPTY_MEMORY_SNAPSHOT_SHA256, EMPTY_MEMORY_SNAPSHOT_SHA256,
                             result.memory_snapshot.digest())
    else:
        assert not result.practice_episodes[0].passed
        assert result.memory_snapshot.items == ()
        assert result.memory_snapshot.digest() == EMPTY_MEMORY_SNAPSHOT_SHA256
        expected_memories = (EMPTY_MEMORY_SNAPSHOT_SHA256,) * 3
    assert tuple(item.request.memory_snapshot_sha256 for item in executions) == expected_memories
    assert controller.gateway is original_gateway and controller.producer_sidecar is original_sidecar
    assert controller._producer_publication_dispatch is None
    assert controller._python_admission_flow_local.active is None
    assert len(observation.attempts) == len(observation.handoffs) == len(supplier.observations) == 3
    assert len({intent.journal_id for intent in observation.attempts}) == 3
    assert len({intent.launch_id for intent in observation.attempts}) == 3
    with sqlite3.connect(value.ledger.database) as connection:
        claims = connection.execute("SELECT episode_id FROM rsi_native_episode_claims").fetchall()
    assert set(claims) == {(episode_id,) for episode_id in _EPISODES}
    head, state = value.ledger.controller_checkpoint(value.binding.run_id)
    wire = state["producer_publication_lineage"]
    assert wire["protocol"] == "lunar-rsi-multi-episode-publication-v2"
    assert [entry["episode_id"] for entry in wire["batches"]] == list(_EPISODES)
    assert [entry["state"] for entry in wire["batches"]] == ["rejected" if item == "R" else "terminal" for item in outcomes]
    histories = value.ledger.controller_checkpoint_history(value.binding.run_id)
    published_candidates, rejected_candidates, held_children = [], [], []
    for ordinal, (execution, entry, outcome) in enumerate(zip(executions, wire["batches"], outcomes, strict=True)):
        memory, plan, claim = _held_child(value, state, execution)
        held_children.append((execution, memory, plan))
        assert entry["ordinal"] == ordinal and entry["journal_id"] == plan.journal_id
        assert claim.status == ("failed" if outcome == "R" else "completed")
        before = entry["before"]
        if ordinal == 0:
            assert before["previous_attempt_journal_id"] is None
        else:
            prior = wire["batches"][ordinal - 1]
            assert before["previous_attempt_journal_id"] == prior["journal_id"]
            assert before["previous_attempt_outcome"] == ("all_rejected" if outcomes[ordinal - 1] == "R" else "published")
        prior_published = [old for old in wire["batches"][:ordinal] if old["state"] == "terminal"]
        assert before["published_predecessor_journal_id"] == (prior_published[-1]["journal_id"] if prior_published else None)
        batch = value.root / "evolution/producer-batches" / plan.journal_id
        if outcome == "R":
            assert execution.result.terminal_reason == "native_all_rejected" and not execution.passed
            assert execution.result.official_evaluation_receipt_sha256 is None
            assert execution.result.candidate_source_sha256 is None
            reference = entry["rejection_provenance"]
            pin = NativeRSIRejectionFilePin.from_dict(reference["file_pin"])
            evidence = read_native_rsi_rejection_provenance(batch, expected_file_pin=pin)
            assert pin.mode == 0o400 and evidence.provenance_file_pin == pin
            assert evidence.provenance_sha256 == reference["provenance_sha256"]
            assert map_native_rejection_to_solver_result(execution.request, plan, evidence) == execution.result
            assert evidence.claim.claim_sha256 == claim.claim_sha256
            c1 = [(checkpoint, snapshot) for checkpoint, snapshot in histories
                  if len(snapshot.get("producer_publication_lineage", {}).get("batches", [])) > ordinal
                  and snapshot["producer_publication_lineage"]["batches"][ordinal]["state"] == "rejected"
                  and snapshot["producer_publication_lineage"]["batches"][ordinal]["rejection_provenance"] is None]
            assert len(c1) == 1 and evidence.lineage.checkpoint_sha256 == c1[0][0]
            terminal = parse_producer_bundle_publication_journal(entry["rejected_journal"])
            assert terminal.state == "all_rejected"
            assert terminal.archive_after_sha256 == terminal.base_archive_sha256
            assert terminal.state_after_sha256 == terminal.base_state_sha256
            rejected_candidates.extend(evidence.candidate_ids)
            for candidate_id in evidence.candidate_ids:
                assert not (value.root / "evolution/candidates" / candidate_id).exists()
            assert not (batch / "journal.published.json").exists()
            assert not (batch / "manifest.json").exists()
        else:
            assert execution.result.status == "completed" and execution.passed
            assert controller.target_judge.quality(execution) == float(_SCORES[execution.request.episode_id])
            terminal = parse_producer_bundle_publication_journal(entry["published_journal"])
            assert terminal.state == "published"
            published_candidates.extend(entry["staged"]["candidate_ids"])
    attempted_candidates = published_candidates + rejected_candidates
    assert len(attempted_candidates) == len(set(attempted_candidates)) == 3
    native_state = json.loads((value.root / "evolution/state.json").read_bytes())
    events = native_state.get("producer_admissions", {"events": []})["events"]
    assert len(events) == outcomes.count("P")
    assert all(event["after_iteration"] == 0 for event in events)
    assert [candidate for event in events for candidate in event["candidate_ids"]] == published_candidates
    published_entries = [entry for entry in wire["batches"] if entry["state"] == "terminal"]
    if published_entries:
        latest = published_entries[-1]
        assert wire["head"] == {"journal_id": latest["journal_id"],
                                "terminal_sha256": latest["terminal"]["terminal_sha256"],
                                "lineage_sha256": latest["terminal"]["descriptor_sha256"]}
        archive = CandidateArchive(value.root, requested_strategy="population", read_only=True)
        records = archive.records()
        archive.validate_candidate_integrity(require_all=True, records=records)
        assert [record.candidate_id for record in records] == published_candidates
    else:
        assert wire["head"] is None
        assert (archive_path.read_bytes() if archive_path.exists() else None) == genesis_archive
        assert (value.root / "evolution/state.json").read_bytes() == genesis_state
    assert wire["rejections"] == [
        {"ordinal": entry["ordinal"], "journal_id": entry["journal_id"],
         "rejected_sha256": entry["rejected"]["descriptor_sha256"]}
        for entry in wire["batches"] if entry["state"] == "rejected"
    ]
    assert state["budget_state"]["consumed"] == {
        "practice_rounds": 1, "target_attempts": 2, "practice_episodes": 1,
        "solver_invocations": 3, "unknown_retries": 0, "evaluator_invocations": 3,
        "verifier_invocations": 3, "transfer_invocations": 0,
    }
    assert all(len(canonical_json(snapshot)) <= 112 * 1024 for _digest, snapshot in histories)
    assert all(retained_publication_evidence_bytes(snapshot) <= MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES
               for _digest, snapshot in histories)
    assert MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES == 64 * 1024 * 1024
    assert all(set(staged["ready"]) == {"protocol", "workspace", "journal_id", "workspace_identity", "file_pin"}
               for staged in state["producer_episode_staging"].values())
    inventory = _inventory(value.root)
    restarted, fresh_supplier = _v2_controller(value)
    # Earlier R/P receipts are read against their own historical approved memory,
    # after the later legitimate P has already changed the live archive/state.
    for execution, memory, _plan in held_children[:2]:
        child = resolve_python_producer_episode_gateway(restarted, execution.request, memory)
        assert child.validate_replay(execution.request, memory, execution.result) == execution.result
    replayed = restarted.resume(value.binding.run_id)
    assert replayed == result
    assert value.ledger.controller_checkpoint(value.binding.run_id) == (head, state)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == histories
    assert _inventory(value.root) == inventory
    assert state["budget_state"]["consumed"]["unknown_retries"] == 0
    assert fresh_supplier.observations == []
    assert len(observation.attempts) == len(observation.handoffs) == len(supplier.observations) == 3
    assert evaluations == list(zip(_EPISODES, outcomes, strict=True))
