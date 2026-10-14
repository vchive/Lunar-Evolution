"""V2-T4: original owner/CAS rejects two ordered native candidates.

Only the retained producer observation and lowest process seams are inert.
Native envelope capture, explicit groups, handoff, receipts, C1/P/C2, claims,
mapping, independent inspection and terminal recovery remain original.
"""

from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_child_execution_flow import _InertNativeObservation, _successful_fixture
from test_rsi_producer_staging_controller import _run
from test_rsi_publication_lineage_rejection_owner import (
    _inert_rejection_evaluator,
    _original_c2,
)

from lunar_evolution import (
    RSILearningController,
    candidate_evaluation,
    candidate_execution_runner,
    native_trusted_output,
    native_trusted_scheduler,
)
from lunar_evolution.bundle_evolution import derive_native_draft_run_id
from lunar_evolution.producer_bundle_admission import parse_producer_bundle_admission_plan
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.producer_bundle_receipts import (
    ProducerBundleEvaluationReceipt,
    ProducerBundleExecutionReceipt,
)
from lunar_evolution.rsi_child_gateway import resolve_python_producer_episode_gateway
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_rejection import map_native_rejection_to_solver_result
from lunar_evolution.rsi_producer_gateway import (
    PythonProducerRSIExecutionConfig,
    PythonProducerRSISolverGateway,
)
from lunar_evolution.rsi_publication_lineage import RSIPublicationLineageV2Inspection
from lunar_evolution.rsi_python_scheduler_inputs import (
    PythonRSISchedulerInputContext,
    PythonRSISchedulerPlanFactory,
)


@pytest.fixture(autouse=True)
def _forbid_process_and_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("two-candidate rejection acceptance must remain inert and local")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


class _DualCandidateObservation(_InertNativeObservation):
    """Extend only the producer's source envelope before original capture runs."""

    def _write(self, path, payload):
        if self.attempts and self.controller is not None:
            intent = self.attempts[-1]
            batch = self.controller.producer_workspace / "evolution/producer-batches" / intent.journal_id
            if path == batch / intent.envelope_path:
                assert payload["status"] == "completed"
                assert [item["path"] for item in payload["materials"]] == ["solve/main.py"]
                source = b"# Second inert candidate source; never executed.\n"
                second = batch / intent.output_directory / "solve/second.py"
                with second.open("xb") as stream:
                    stream.write(source)
                second.chmod(0o600)
                payload = {**payload, "materials": [*payload["materials"], {
                    "kind": "candidate_source", "path": "solve/second.py", "size": len(source),
                    "sha256": hashlib.sha256(source).hexdigest(),
                }]}
        return super()._write(path, payload)


def _controller(value, stager):
    return RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.root, producer_stager=stager,
        producer_child_execution=True, producer_multi_episode_publication=True,
        producer_known_rejection=True,
    )


def _dual_rejection_fixture(tmp_path, monkeypatch):
    value, original, supplier, _observation = _successful_fixture(tmp_path, monkeypatch)
    assert value.native.groups == (BundleGroup("fixture", "solve/main.py", ("solve/main.py",)),)
    original_context_fingerprint = PythonRSISchedulerPlanFactory(value.context).rsi_fingerprint_config()
    observation = _DualCandidateObservation()
    second_group = BundleGroup("fixture-second", "solve/second.py", ("solve/second.py",))
    # A material alone would be ignored by the original explicit-group handoff.
    # Build a fresh context before any controller run; never mutate sealed groups.
    value.native = replace(
        value.native, python_handoff_after_execution=observation,
        groups=(*value.native.groups, second_group),
    )
    value.context = PythonRSISchedulerInputContext(value.native, value.sidecar, value.proof)
    assert PythonRSISchedulerPlanFactory(value.context).rsi_fingerprint_config() != original_context_fingerprint
    value.config = PythonProducerRSIExecutionConfig(value.request.solver_id, value.ledger, value.context)
    value.gateway = PythonProducerRSISolverGateway(value.config)
    monkeypatch.setattr(native_trusted_scheduler, "run_native_trusted_attempt", observation.attempt)
    monkeypatch.setattr(native_trusted_scheduler, "persist_native_trusted_execution_receipt", observation.persist_receipt)
    monkeypatch.setattr(native_trusted_scheduler, "recover_native_trusted_execution_receipt", observation.recover_receipt)
    monkeypatch.setattr(native_trusted_output, "recover_native_trusted_attempt", observation.terminal)
    monkeypatch.setattr(native_trusted_output, "recover_native_trusted_execution_receipt", observation.recover_receipt)
    candidate_process = candidate_execution_runner._bounded_process_bytes
    events = []

    def candidate(command, *, cwd, **kwargs):
        assert "evaluator.py" not in command
        events.append(("execution", Path(cwd)))
        return candidate_process(command, cwd=cwd, **kwargs)

    def evaluator(command, *, cwd, **kwargs):
        events.append(("evaluation", Path(cwd)))
        return _inert_rejection_evaluator(command, cwd=cwd, **kwargs)

    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", candidate)
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", evaluator)
    controller = _controller(value, original.producer_stager)
    observation.controller = controller
    return value, controller, supplier, observation, events


def test_original_two_candidate_rejection_order_receipts_and_readonly_replay(tmp_path, monkeypatch):
    value, controller, supplier, observation, events = _dual_rejection_fixture(tmp_path, monkeypatch)
    archive = value.root / "evolution/archive.jsonl"
    native_state_path = value.root / "evolution/state.json"
    genesis_archive = archive.read_bytes() if archive.exists() else None
    genesis_state = native_state_path.read_bytes()
    result = _run(controller, value)
    held = _original_c2(value)
    assert result.status == "failed" and len(result.target_attempts) == 1
    assert result.practice_episodes == () and result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT
    execution = result.target_attempts[0]
    assert execution.request == held.request and not execution.passed
    assert execution.result.status == "failed" and execution.result.terminal_reason == "native_all_rejected"
    assert execution.result.solver_score is None
    assert execution.result.official_evaluation_receipt_sha256 is None
    assert execution.result.candidate_source_sha256 is None
    assert map_native_rejection_to_solver_result(held.request, held.plan, held.evidence) == execution.result
    assert held.claim.status == "failed" and held.claim.claim_sha256 == held.evidence.claim.claim_sha256
    assert value.ledger.episode_result(held.request.episode_id) == (held.request, execution.result)
    with sqlite3.connect(value.ledger.database) as connection:
        assert connection.execute("SELECT episode_id FROM rsi_native_episode_claims").fetchall() == [
            (held.request.episode_id,),
        ]
    wire = held.state["producer_publication_lineage"]
    assert wire["protocol"] == "lunar-rsi-multi-episode-publication-v2"
    assert wire["head"] is None and len(wire["batches"]) == 1
    assert held.entry["state"] == "rejected"
    assert held.entry["before"]["previous_attempt_journal_id"] is None
    assert held.entry["before"]["published_predecessor_journal_id"] is None
    terminal = parse_producer_bundle_publication_journal(held.entry["rejected_journal"])
    prepared = parse_producer_bundle_publication_journal(held.entry["prepared_journal"])
    admission = parse_producer_bundle_admission_plan(held.entry["admission_plan"])
    assert terminal == held.evidence.terminal
    assert terminal.state == "all_rejected" and terminal.publication_phase == "committed"
    assert [item.bundle_id for item in admission.bundles] == ["fixture", "fixture-second"]
    assert [item.bundle_id for item in prepared.candidates] == ["fixture", "fixture-second"]
    assert [item.bundle_id for item in terminal.candidates] == ["fixture", "fixture-second"]
    candidate_ids = tuple(item.candidate_id for item in terminal.candidates)
    assert len(candidate_ids) == len(set(candidate_ids)) == 2
    assert candidate_ids == tuple(item.candidate_id for item in prepared.candidates)
    assert candidate_ids == held.evidence.lineage.candidate_ids == held.evidence.rejected.candidate_ids
    assert [kind for kind, _cwd in events] == ["execution", "evaluation", "execution", "evaluation"]
    execution_receipts, evaluation_receipts, retained_evidence = [], [], []
    for ordinal, candidate in enumerate(terminal.candidates):
        assert candidate.status == "rejected" and candidate.publication_receipt_sha256 is None
        retained = json.loads((held.batch / "rejections" / f"{candidate.candidate_id}.json").read_bytes())
        assert retained["candidate_id"] == candidate.candidate_id
        native_execution = ProducerBundleExecutionReceipt.from_dict(retained["execution_receipt"])
        native_evaluation = ProducerBundleEvaluationReceipt.from_dict(retained["evaluation_receipt"])
        assert native_execution.candidate_id == native_evaluation.candidate_id == candidate.candidate_id
        assert native_execution.digest() == candidate.execution_receipt_sha256
        assert native_evaluation.digest() == candidate.evaluation_receipt_sha256
        assert native_evaluation.report["validity"] == 0
        assert native_evaluation.python_handoff_sha256 == terminal.python_handoff_sha256
        execution_receipts.append(native_execution.digest())
        evaluation_receipts.append(native_evaluation.digest())
        retained_evidence.append(retained["retained_evidence"]["evidence_sha256"])
        run_id = derive_native_draft_run_id(held.plan.journal_id, candidate.candidate_id, candidate.bundle_sha256)
        run_root = value.root / "evolution/bundle-attempts" / f".bundle-run-{run_id}"
        for _kind, cwd in events[ordinal * 2:ordinal * 2 + 2]:
            assert cwd.is_relative_to(run_root)
        assert not (value.root / "evolution/candidates" / candidate.candidate_id).exists()
    assert tuple(execution_receipts) == held.evidence.execution_receipt_sha256s
    assert tuple(evaluation_receipts) == held.evidence.evaluation_receipt_sha256s
    assert tuple(retained_evidence) == held.evidence.retained_evidence_sha256s
    assert len(set(execution_receipts + evaluation_receipts)) == 4
    histories = value.ledger.controller_checkpoint_history(value.binding.run_id)
    c1 = [(ordinal, head, state) for ordinal, (head, state) in enumerate(histories)
          if state.get("producer_publication_lineage", {}).get("batches")
          and state["producer_publication_lineage"]["batches"][-1]["state"] == "rejected"
          and state["producer_publication_lineage"]["batches"][-1]["rejection_provenance"] is None]
    assert len(c1) == 1 and c1[0][1] == held.evidence.lineage.checkpoint_sha256
    c2 = [(ordinal, state) for ordinal, (_head, state) in enumerate(histories)
          if state.get("producer_publication_lineage", {}).get("batches")
          and state["producer_publication_lineage"]["batches"][-1]["state"] == "rejected"
          and state["producer_publication_lineage"]["batches"][-1]["rejection_provenance"] is not None]
    assert c2 and c2[0][0] > c1[0][0]
    assert c2[0][1]["producer_publication_lineage"]["batches"][-1]["rejection_provenance"]["file_pin"] == held.file_pin.to_dict()
    assert held.file_pin.mode == 0o400 and held.evidence.provenance_file_pin == held.file_pin
    assert held.file_pin.sha256 == hashlib.sha256((held.batch / held.file_pin.name).read_bytes()).hexdigest()
    assert (archive.read_bytes() if archive.exists() else None) == genesis_archive
    assert native_state_path.read_bytes() == genesis_state
    assert not json.loads(genesis_state).get("producer_admissions", {"events": []})["events"]
    assert terminal.archive_after_sha256 == terminal.base_archive_sha256
    assert terminal.state_after_sha256 == terminal.base_state_sha256
    assert not (held.batch / "manifest.json").exists()
    assert not (held.batch / "journal.published.json").exists()
    assert len(observation.attempts) == len(observation.handoffs) == len(supplier.observations) == 1
    assert held.state["budget_state"]["consumed"]["solver_invocations"] == 1
    assert held.state["budget_state"]["consumed"]["unknown_retries"] == 0
    inventory = _inventory(value.root)
    inspection = RSIPublicationLineageV2Inspection(controller, request=held.request,
        memory=held.memory, native_plan=held.plan)
    verified = inspection.inspect_rejection(value.root, admission, terminal)
    assert verified.terminal == terminal and verified.candidate_ids == candidate_ids
    assert verified.execution_receipt_sha256s == tuple(execution_receipts)
    assert verified.evaluation_receipt_sha256s == tuple(evaluation_receipts)
    assert verified.retained_evidence_sha256s == tuple(retained_evidence)
    assert verified.manifest_sha256 == held.evidence.lineage.rejection_manifest_sha256
    restarted = _controller(value, controller.producer_stager)
    child = resolve_python_producer_episode_gateway(restarted, held.request, held.memory)
    assert type(child) is PythonProducerRSISolverGateway
    assert child.validate_replay(held.request, held.memory, execution.result) == execution.result
    assert restarted.resume(value.binding.run_id) == result
    assert value.ledger.controller_checkpoint(value.binding.run_id) == (held.checkpoint_sha256, held.state)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == histories
    assert _inventory(value.root) == inventory
    assert len(observation.attempts) == len(observation.handoffs) == len(supplier.observations) == 1
    assert [kind for kind, _cwd in events] == ["execution", "evaluation", "execution", "evaluation"]
