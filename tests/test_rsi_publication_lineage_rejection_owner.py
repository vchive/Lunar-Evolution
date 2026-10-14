"""Original controller/owner/CAS rejection flow with only inert process seams."""

from __future__ import annotations

import json
import socket
import subprocess
from types import SimpleNamespace

import pytest
from test_rsi_child_execution_flow import _Crash, _successful_fixture
from test_rsi_producer_staging_controller import _run

from lunar_evolution import RSILearningController, candidate_evaluation
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_admission import parse_producer_bundle_admission_plan
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemorySnapshot
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_native_rejection import (
    NativeRSIRejectionError,
    NativeRSIRejectionFilePin,
    read_native_rsi_rejection_provenance,
)
from lunar_evolution.rsi_producer_staging_capsule import materialize_ready
from lunar_evolution.rsi_publication_lineage import (
    RSIPublicationLineageV2Inspection,
    StartedRSIRejectionInspection,
)


@pytest.fixture(autouse=True)
def _forbid_process_and_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("original rejection owner fixture must remain inert")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def _inert_rejection_evaluator(command, *, cwd, process_observer=None,
                              process_released=None, process_exit_observed=None,
                              continuation_guard=None, **_kwargs):
    """Lowest evaluator seam; original receipts and immutable proof stay real."""
    from pathlib import Path

    assert "evaluator.py" in command
    assert json.loads((Path(cwd) / "output/result.json").read_bytes()) == {"value": 9}
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


def _known_rejection_fixture(tmp_path, monkeypatch):
    """Reusable original graph, before run; no owner/SQLite/provenance seam."""
    value, old, supplier, observation = _successful_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", _inert_rejection_evaluator)
    controller = RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.root, producer_stager=old.producer_stager,
        producer_child_execution=True, producer_multi_episode_publication=True,
        producer_known_rejection=True,
    )
    observation.controller = controller
    return SimpleNamespace(value=value, controller=controller, supplier=supplier,
                           observation=observation)


def _original_c2(value):
    """Read held references from actual original checkpoint history, never synthesize."""
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    episode_id = state["current_episode_id"]
    staged = state["producer_episode_staging"][episode_id]
    request = SolverRequest.from_dict(staged["identity"]["intent"]["request"])
    memory = MemorySnapshot.from_dict(staged["identity"]["memory"])
    ready = materialize_ready(staged["ready"], allow_capsule=True,
        expected_workspace=value.root, expected_journal_id=staged["identity"]["journal_id"])
    plan = NativeRSIExecutionPlan.from_dict(ready["plan"])
    claim = value.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
    entry = state["producer_publication_lineage"]["batches"][-1]
    pin = NativeRSIRejectionFilePin.from_dict(entry["rejection_provenance"]["file_pin"])
    batch = value.root / "evolution/producer-batches" / plan.journal_id
    evidence = read_native_rsi_rejection_provenance(batch, expected_file_pin=pin)
    head = value.ledger.controller_checkpoint(value.binding.run_id)[0]
    episode = value.ledger.get_episode(request.episode_id)
    return SimpleNamespace(state=state, entry=entry, request=request, memory=memory,
                           plan=plan, claim=claim, file_pin=pin, evidence=evidence,
                           checkpoint_sha256=head, episode=episode, batch=batch)


def test_original_rejected_controller_keeps_c1_then_original_p_then_c2(tmp_path, monkeypatch):
    fixture = _known_rejection_fixture(tmp_path, monkeypatch)
    value, controller = fixture.value, fixture.controller
    result = _run(controller, value)
    held = _original_c2(value)
    assert result.status == "failed"
    assert held.entry["state"] == "rejected" and held.state["producer_publication_lineage"]["head"] is None
    assert held.claim.status == "failed"
    assert value.ledger.episode_result(held.request.episode_id)[1].status == "failed"
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    c1 = [(head, state) for head, state in history
          if (state.get("producer_publication_lineage") or {}).get("batches")
          and state["producer_publication_lineage"]["batches"][-1]["state"] == "rejected"
          and state["producer_publication_lineage"]["batches"][-1]["rejection_provenance"] is None]
    assert len(c1) == 1 and held.evidence.lineage.checkpoint_sha256 == c1[0][0]
    assert held.file_pin.mode == 0o400 and held.evidence.provenance_file_pin == held.file_pin
    assert len(fixture.observation.attempts) == len(fixture.supplier.observations) == 1
    for name, extension in (("archive", "jsonl"), ("state", "json")):
        assert (value.root / f"evolution/{name}.{extension}").read_bytes() == (
            held.batch / f"lineage/{name}-before.snapshot").read_bytes()
    inspection = RSIPublicationLineageV2Inspection(controller, request=held.request,
        memory=held.memory, native_plan=held.plan)
    assert inspection.rejection_provenance_binding() == held.evidence.lineage
    assert inspection.rejection_provenance_file_pin() == held.file_pin
    terminal = parse_producer_bundle_publication_journal(held.entry["rejected_journal"])
    admission = parse_producer_bundle_admission_plan(held.entry["admission_plan"])
    assert inspection.inspect_rejection(value.root, admission, terminal).terminal == terminal


def test_original_c2_started_inspection_is_read_only_before_result(tmp_path, monkeypatch):
    fixture = _known_rejection_fixture(tmp_path, monkeypatch)
    value = fixture.value

    def owner_stack_loss(*_args, **_kwargs):
        raise _Crash()

    monkeypatch.setattr(value.ledger, "publish_native_episode_result", owner_stack_loss)
    with pytest.raises(_Crash):
        _run(fixture.controller, value)
    held = _original_c2(value)
    assert held.claim.status == "started"
    assert value.ledger.episode_result(held.request.episode_id) is None
    with value.ledger.controller_lock(value.binding.run_id):
        observation = StartedRSIRejectionInspection(
            fixture.controller, request=held.request, memory=held.memory, native_plan=held.plan,
            expected_checkpoint_sha256=held.checkpoint_sha256,
            expected_episode_record_sha256=held.episode.record_sha256,
            expected_claim_sha256=held.claim.claim_sha256,
            expected_provenance_file_pin=held.file_pin,
        )
        assert observation.rejection_provenance_binding() == held.evidence.lineage
        assert observation.rejection_provenance_file_pin() == held.file_pin
    assert value.ledger.controller_checkpoint(value.binding.run_id)[0] == held.checkpoint_sha256
    assert value.ledger.episode_result(held.request.episode_id) is None


@pytest.mark.parametrize("inspection", [RSIPublicationLineageV2Inspection, StartedRSIRejectionInspection])
def test_inspector_refuses_nested_plan_request_callback_before_policy_or_ledger(
    tmp_path, monkeypatch, inspection,
):
    fixture = _known_rejection_fixture(tmp_path, monkeypatch)
    value = fixture.value
    plan = value.gateway._plan(value.request, value.memory)
    clean_request = SolverRequest.from_dict(plan.request.to_dict())

    def callback():
        pytest.fail("hostile nested DTO method executed")

    object.__setattr__(plan.request, "to_dict", callback)
    monkeypatch.setattr(value.ledger, "controller_lock_held", callback)
    monkeypatch.setattr(value.ledger, "read_only_observations", callback)
    monkeypatch.setattr("lunar_evolution.rsi_publication_lineage.multi_episode_publication_policy", callback)
    arguments = {}
    if inspection is StartedRSIRejectionInspection:
        arguments = {"expected_checkpoint_sha256": "a" * 64,
                     "expected_episode_record_sha256": "b" * 64,
                     "expected_claim_sha256": "c" * 64,
                     "expected_provenance_file_pin": NativeRSIRejectionFilePin(
                         "native-rsi.rejection-provenance.json", "d" * 64, 41,
                         1, 2, 1, 3, mtime_ns=4, ctime_ns=5)}
    with pytest.raises(NativeRSIRejectionError, match="shape_invalid"):
        inspection(fixture.controller, request=clean_request, memory=value.memory,
                   native_plan=plan, **arguments)
