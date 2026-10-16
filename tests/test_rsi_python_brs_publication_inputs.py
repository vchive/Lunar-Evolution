"""Inert real preparation -> detached request -> one-shot mailbox composition."""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_native_trusted_python_prepublication import _handoff, _prepare, _stages
from test_native_trusted_scheduler import _context
from test_rsi_python_brs_publication_mailbox import _handoff as _selected

import lunar_evolution.native_trusted_scheduler as scheduler
from lunar_evolution.producer_process import parse_producer_execution_receipt
from lunar_evolution.python_producer_admission_handoff import (
    PythonProducerAdmissionHandoffFilePin,
    PythonProducerAdmissionHandoffSidecar,
)
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_python_brs_publication_inputs import _request_from_native_preparation
from lunar_evolution.rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    context, events = _context(tmp_path), []
    receipt, output = _stages(context, monkeypatch, events)
    wire = receipt.to_dict()
    wire.update(launch_id=context.intent.launch_id, intent_sha256=context.intent.digest(),
                attestation_sha256=context.attestation.digest())
    wire["trusted_execution"]["broker_journal_identity"].update(
        launch_id=context.intent.launch_id, intent_sha256=context.intent.digest(),
    )
    wire["envelope_evidence"] = {
        "relative_path": "output/envelope.json", "sha256": output.envelope_bytes_sha256,
        "bytes": 1, "device": 1, "inode": 2, "mtime_ns": 3, "ctime_ns": 4,
        "identity_before": "fixture", "identity_after": "fixture", "read_status": "complete",
    }
    wire.pop("receipt_sha256")
    wire["receipt_sha256"] = hashlib.sha256(_json(wire)).hexdigest()
    receipt = parse_producer_execution_receipt(wire)
    admission = replace(output.admission_plan, contract_sha256=context.contract.digest(),
                        evaluator_kind="local", evaluator_fingerprint="e" * 64,
                        runner_fingerprint="f" * 64, dependency_sha256="1" * 64,
                        environment_sha256="2" * 64)
    output = replace(output, admission_plan=admission, execution_receipt_sha256=receipt.receipt_sha256,
                     envelope=replace(output.envelope, budget={"requests": 0}),
                     process_terminal_sha256=receipt.trusted_execution["terminal_sha256"],
                     output_capture_sha256=receipt.trusted_execution["output_capture_sha256"])
    context.preparation_receipt, context.preparation_output = receipt, output
    monkeypatch.setattr(scheduler, "persist_native_trusted_execution_receipt", lambda *_a, **_k: receipt)
    monkeypatch.setattr(scheduler, "prepare_native_trusted_output", lambda *_a, **_k: output)
    preparation = _prepare(context, python_handoff_after_execution=lambda *_: _handoff(
        context, envelope_sha256=output.envelope.envelope_sha256,
    ))
    request = SolverRequest.build(
        episode_id=context.intent.run_id + "-practice-0-0", contract_sha256=context.contract.digest(),
        evaluator_sha256="e" * 64, environment_sha256="2" * 64,
        memory_snapshot_sha256="9" * 64, solver_id="fixture",
    )
    plan = NativeRSIExecutionPlan.build(
        request=request, journal_id=context.intent.journal_id, launch_id=context.intent.launch_id,
        run_id=context.intent.run_id, parent_task_id=context.intent.parent_task_id,
        task_id=context.intent.task_id, intent_sha256=context.intent.digest(),
        attestation_sha256=context.attestation.digest(), bootstrap_descriptor_sha256="a" * 64,
        bootstrap_artifact_sha256="b" * 64, manifest_sha256="c" * 64,
        candidate_selector_sha256="d" * 64, evaluator_kind="local", evaluator_fingerprint="e" * 64,
    )
    selected = replace(_selected(), run_id=context.intent.run_id, episode_id=request.episode_id,
                       request_sha256=request.digest(), root_snapshot_sha256=request.memory_snapshot_sha256)

    def forbidden(*_a, **_k):
        pytest.fail("evidence projection performed an execution or transaction")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(scheduler, "recover_native_trusted_producer", forbidden)
    monkeypatch.setattr(scheduler, "run_native_producer_bundle_publication_transaction", forbidden)
    return SimpleNamespace(preparation=preparation, handoff=selected, plan=plan, workspace=tmp_path)


def _request(value, **changes):
    options = {
        "native_plan": value.plan, "expected_head_sha256": value.handoff.head_sha256,
        "expected_state_sha256": value.handoff.state_sha256,
    }
    options.update(changes)
    return _request_from_native_preparation(value.preparation, value.handoff, **options)


def test_actual_preparation_projects_original_evidence_and_composes_mailbox(prepared):
    before = {path: path.read_bytes() for path in prepared.workspace.rglob("*") if path.is_file()}
    request = _request(prepared)
    payload = json.loads(request.payload)
    assert payload["native_plan_sha256"] == prepared.plan.plan_sha256
    assert payload["python_handoff_file_pin"] == prepared.preparation.handoff.file_pin.to_dict()
    assert payload["native_execution_receipt_sha256"] == prepared.preparation.run.receipt.receipt_sha256
    assert payload["output"]["admission_plan_sha256"] == prepared.preparation.run.output.admission_plan.digest()
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker_id = pool.submit(threading.get_ident).result(timeout=5)
        mailbox = BRSOwnerPublicationMailbox(prepared.handoff, worker_thread=worker_id)
        try:
            pending = pool.submit(mailbox.request, request, check=lambda: None)
            assert mailbox.service(lambda observed: _json({"request": observed.request_sha256}),
                                   check=lambda: None, timeout=5)
            assert json.loads(pending.result(timeout=5).payload) == {"request": request.request_sha256}
        finally:
            mailbox.close()
    assert {path: path.read_bytes() for path in prepared.workspace.rglob("*") if path.is_file()} == before


def test_request_is_detached_from_original_nested_receipt(prepared):
    request = _request(prepared)
    raw = request.payload
    prepared.preparation.run.receipt.owner_identity["pid"] = 999
    assert request.payload == raw
    with pytest.raises(RSILearningError, match="evidence_invalid"):
        _request(prepared)


@pytest.mark.parametrize("target,field,value,code", [
    ("run", "status", "published", "state_invalid"),
    ("run", "publication", {}, "state_invalid"),
    ("run", "deadline_scope", [], "state_invalid"),
    ("output", "publication_eligible", False, "state_invalid"),
    ("output", "request_coverage", "producer_declaration_only", "state_invalid"),
    ("output", "execution_receipt_sha256", "8" * 64, "output_mismatch"),
    ("output", "process_terminal_sha256", "8" * 64, "capture_mismatch"),
    ("output", "output_capture_sha256", "8" * 64, "capture_mismatch"),
    ("output", "envelope_bytes_sha256", "8" * 64, "capture_mismatch"),
])
def test_mutated_preparation_never_becomes_usable_request(prepared, target, field, value, code):
    owner = prepared.preparation.run if target == "run" else prepared.preparation.run.output
    object.__setattr__(owner, field, value)
    with pytest.raises(RSILearningError, match=code):
        _request(prepared)


@pytest.mark.parametrize("field,value,code", [
    ("run_id", "foreign-run", "selection_mismatch"),
    ("launch_id", "foreign-launch", "launch_mismatch"),
    ("journal_id", "foreign-journal", "launch_mismatch"),
    ("parent_task_id", "foreign-parent", "launch_mismatch"),
    ("task_id", "foreign-child", "launch_mismatch"),
    ("intent_sha256", "8" * 64, "launch_mismatch"),
    ("attestation_sha256", "8" * 64, "launch_mismatch"),
    ("evaluator_fingerprint", "8" * 64, "output_mismatch"),
])
def test_revalid_native_plan_with_foreign_binding_refuses(prepared, field, value, code):
    foreign = replace(prepared.plan, **{field: value}, plan_sha256=None)
    with pytest.raises(RSILearningError, match=code):
        _request(prepared, native_plan=foreign)


@pytest.mark.parametrize("field", ["head", "state"])
def test_explicit_capture_is_checked_by_original_mailbox_not_refreshed(prepared, field):
    request = _request(prepared, **{"expected_" + field + "_sha256": "8" * 64})
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker_id = pool.submit(threading.get_ident).result(timeout=5)
        box = BRSOwnerPublicationMailbox(prepared.handoff, worker_thread=worker_id)
        try:
            with pytest.raises(RSILearningError, match="capture_mismatch"):
                pool.submit(box.request, request, check=lambda: None).result(timeout=5)
            assert box.status == "open"
        finally:
            box.close()


class _Decoy:
    def __eq__(self, _other):
        pytest.fail("callback equality ran")

    def __iter__(self):
        pytest.fail("callback iterator ran")

    def to_dict(self):
        pytest.fail("callback serializer ran")

    def values(self):
        pytest.fail("dataclass field callback ran")


@pytest.mark.parametrize("where", ["request", "receipt_map", "admission", "sidecar", "scalar"])
def test_callback_inputs_refuse_before_serializer_or_comparison(prepared, where):
    if where == "request":
        object.__setattr__(prepared.plan.request, "solver_settings", _Decoy())
    elif where == "receipt_map":
        object.__setattr__(prepared.preparation.run.receipt, "owner_identity", _Decoy())
    elif where == "admission":
        object.__setattr__(prepared.preparation.run.output, "admission_plan", _Decoy())
    elif where == "sidecar":
        object.__setattr__(prepared.preparation.handoff, "file_pin", _Decoy())
    else:
        object.__setattr__(prepared.preparation.run, "status", _Decoy())
    with pytest.raises(RSILearningError, match="shape_invalid|evidence_invalid"):
        _request(prepared)


def test_unused_worker_objects_are_never_serialized_or_invoked(prepared):
    object.__setattr__(prepared.preparation.run, "attempt", _Decoy())
    object.__setattr__(prepared.preparation.run.output, "drafts", _Decoy())
    object.__setattr__(prepared.preparation.run.output, "bundles", _Decoy())
    assert _request(prepared).request_sha256


def test_original_sidecar_raw_pin_cannot_be_replaced_by_foreign_pin(prepared):
    sidecar = prepared.preparation.handoff
    wire = sidecar.file_pin.to_dict()
    wire["handoff_sha256"] = "8" * 64
    wire.pop("pin_sha256")
    wire["pin_sha256"] = hashlib.sha256(_json(wire)).hexdigest()
    changed = PythonProducerAdmissionHandoffFilePin.from_dict(wire)
    object.__setattr__(sidecar, "file_pin", changed)
    with pytest.raises(RSILearningError, match="evidence_invalid"):
        _request(prepared)


def test_malformed_primitive_envelope_normalizes_existing_runtime_error(prepared):
    object.__setattr__(prepared.preparation.run.output.envelope, "status", "invalid")
    with pytest.raises(RSILearningError, match="evidence_invalid"):
        _request(prepared)


def test_rehashed_receipt_with_non_string_cleanup_refuses_with_fixed_code(prepared):
    malformed = replace(prepared.preparation.run.receipt, cleanup_status=[], receipt_sha256=None)
    object.__setattr__(prepared.preparation.run, "receipt", malformed)
    with pytest.raises(RSILearningError, match="state_invalid"):
        _request(prepared)


def test_dto_subclass_refuses_before_overridden_serializer(prepared):
    class ForeignPlan(NativeRSIExecutionPlan):
        def to_dict(self, **_kwargs):
            pytest.fail("subclass serializer ran")

    foreign = object.__new__(ForeignPlan)
    with pytest.raises(RSILearningError, match="shape_invalid"):
        _request(prepared, native_plan=foreign)


@pytest.mark.parametrize("method", ["to_dict", "digest", "__dataclass_fields__"])
def test_request_instance_serializer_shadow_refuses_without_callback(prepared, method):
    def forbidden(*_args, **_kwargs):
        pytest.fail("instance serializer shadow ran")

    object.__setattr__(prepared.plan.request, method, _Decoy() if method == "__dataclass_fields__" else forbidden)
    with pytest.raises(RSILearningError, match="evidence_invalid"):
        _request(prepared)


def test_sidecar_shape_requires_exact_original_dto(prepared):
    original = prepared.preparation.handoff
    assert type(original) is PythonProducerAdmissionHandoffSidecar
    object.__setattr__(prepared.preparation, "handoff", SimpleNamespace(
        handoff=original.handoff, file_pin=original.file_pin,
    ))
    with pytest.raises(RSILearningError, match="shape_invalid"):
        _request(prepared)
