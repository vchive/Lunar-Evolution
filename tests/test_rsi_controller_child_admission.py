"""Controller admission resolves a staged child sidecar without replacing root authority."""

from __future__ import annotations

import hashlib
import os

import pytest
from test_rsi_producer_launch import _ready

import lunar_evolution.rsi_producer_launch as producer_launch
from lunar_evolution import RSILearningError
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_intent import _intent_content
from lunar_evolution.producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    build_producer_bundle_publication_journal,
)
from lunar_evolution.python_producer_admission_anchor import (
    persist_python_producer_admission_attempt_anchor,
    project_python_producer_admission_attempt_anchor,
)
from lunar_evolution.python_producer_admission_handoff import (
    build_python_producer_admission_handoff,
    persist_python_producer_admission_handoff_pinned,
)
from lunar_evolution.python_producer_binding import parse_python_producer_binding
from lunar_evolution.python_producer_checkpoint import PythonProducerCheckpointBinding
from lunar_evolution.rsi_learning import PracticeEpisode
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan


def _staged(tmp_path, monkeypatch):
    # The fixture binding is intentionally larger than the conservative production
    # staging bound on this host; widening only keeps this test provider-free.
    monkeypatch.setattr(producer_launch, "MAX_STAGING_BINDING_BYTES", 64 * 1024)
    return _ready(tmp_path, monkeypatch)


def test_controller_resolves_episode_sidecar_and_retains_root_pin(tmp_path, monkeypatch):
    value, _supplier, controller, state, entry = _staged(tmp_path, monkeypatch)
    episode_id = state["current_episode_id"]
    root_sidecar = controller.producer_sidecar

    child_sidecar, child_proof = controller._python_admission_sidecar(
        value.binding.run_id, episode_id,
    )

    assert child_proof == PythonProducerCheckpointBinding.from_dict(
        entry["ready"]["producer_checkpoint"],
    )
    assert child_sidecar.binding.intent.journal_id == entry["identity"]["journal_id"]
    assert child_sidecar.binding.task_id == episode_id
    assert child_sidecar != root_sidecar
    assert controller.producer_sidecar is root_sidecar
    assert PythonProducerCheckpointBinding.from_sidecar(root_sidecar).journal_id != child_proof.journal_id


def test_controller_child_sidecar_refuses_file_pin_drift(tmp_path, monkeypatch):
    value, _supplier, controller, state, _entry = _staged(tmp_path, monkeypatch)
    episode_id = state["current_episode_id"]
    child, _proof = controller._python_admission_sidecar(value.binding.run_id, episode_id)
    path = value.root / "evolution" / "producer-batches" / child.binding.intent.journal_id / "python-producer-binding.json"
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))

    with pytest.raises(RSILearningError, match="child_proof_invalid"):
        controller._python_admission_sidecar(value.binding.run_id, episode_id)


def test_register_admission_uses_child_proof_and_sidecar(tmp_path, monkeypatch):
    value, _supplier, controller, state, entry = _staged(tmp_path, monkeypatch)
    episode_id = state["current_episode_id"]
    request = value.request.__class__.from_dict(entry["identity"]["intent"]["request"])
    child_binding = parse_python_producer_binding(canonical_json(entry["ready"]["binding"]))
    child_sidecar, child_proof = controller._python_admission_sidecar(value.binding.run_id, episode_id)
    assert child_sidecar.binding == child_binding
    plan = NativeRSIExecutionPlan.from_dict(entry["ready"]["plan"])

    # Create only the durable running/claim records needed by the late admission
    # gate; no producer, evaluator, or model is executed.
    planned = PracticeEpisode.from_dict(entry["identity"]["intent"]["episode"])
    controller.ledger.create_episode_record(planned.transition("running", request_sha256=request.digest()))
    claim = controller.ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
    batch = value.root / "evolution" / "producer-batches" / child_binding.intent.journal_id
    handoff = build_python_producer_admission_handoff(
        run_id=value.binding.run_id, journal_id=child_binding.intent.journal_id,
        parent_task_id=child_binding.parent_task_id, task_id=child_binding.task_id,
        binding_sha256=child_binding.binding_sha256, sidecar_raw_sha256=child_sidecar.raw_sha256,
        sidecar_pin_sha256=hashlib.sha256(canonical_json(dict(child_proof.sidecar_pin))).hexdigest(),
        launch_intent_sha256=child_binding.intent_sha256,
        attestation_sha256=child_binding.attestation_sha256,
        runtime_manifest_sha256=child_binding.runtime_manifest_sha256,
        runtime_tree_sha256=child_binding.runtime_tree_sha256,
        executable_owner_sha256="a" * 64, native_execution_receipt_sha256="a" * 64,
        terminal_sha256="a" * 64, runtime_observation_sha256="a" * 64,
        broker_transcript_sha256="a" * 64, envelope_sha256="a" * 64, materials_sha256="a" * 64,
        contract_sha256=child_binding.contract_sha256,
        evaluator_sha256=child_binding.evaluator_fingerprint,
        runner_sha256=child_binding.intent.runner_fingerprint,
        dependency_sha256=child_binding.dependency_sha256,
        environment_sha256=child_binding.environment_sha256,
        admission_plan_sha256="b" * 64, request_budget=child_binding.request_budget,
        wall_timeout_seconds=child_binding.wall_timeout_seconds,
        deadline_unix=child_binding.deadline_unix,
    )
    pinned = persist_python_producer_admission_handoff_pinned(batch, handoff=handoff)
    candidate = ProducerBundlePublicationCandidate(
        candidate_id="candidate-child", bundle_id="bundle-child", bundle_sha256="a" * 64,
        parent_id=None, generation=0, iteration=0, island_id=0,
        preparation_receipt_sha256="a" * 64,
    )
    journal = build_producer_bundle_publication_journal(
        journal_id=child_binding.intent.journal_id, run_id=value.binding.run_id,
        parent_task_id=child_binding.parent_task_id, task_id=child_binding.task_id,
        admission_sha256="b" * 64, archive_prefix_sha256="a" * 64,
        base_archive_sha256="a" * 64, base_state_sha256="a" * 64,
        contract_sha256=child_binding.contract_sha256, evaluator_kind=child_binding.evaluator_kind,
        evaluator_fingerprint=child_binding.evaluator_fingerprint,
        runner_fingerprint=child_binding.intent.runner_fingerprint,
        dependency_sha256=child_binding.dependency_sha256,
        environment_sha256=child_binding.environment_sha256, budget_sha256="a" * 64,
        strategy="population", population_config_sha256="a" * 64, num_islands=1,
        candidates=(candidate,), native_execution_receipt_sha256="a" * 64,
        python_handoff_sha256=handoff.handoff_sha256, python_handoff_file_pin=pinned.file_pin,
    )
    (batch / "journal.prepared.json").write_bytes(_intent_content(journal)[0])
    (batch / "journal.prepared.json").chmod(0o600)
    anchor = project_python_producer_admission_attempt_anchor(handoff)
    persist_python_producer_admission_attempt_anchor(batch, anchor=anchor)

    record = controller.register_python_admission(
        value.binding.run_id, episode_id, native_plan=plan, prepared_journal=journal,
        expected_anchor_sha256=anchor.anchor_sha256,
    )
    assert record.producer_checkpoint_sha256 == hashlib.sha256(child_proof.to_json()).hexdigest()
    assert record.episode_request_sha256 == request.digest()
    assert record.native_claim_sha256 == claim.claim_sha256
