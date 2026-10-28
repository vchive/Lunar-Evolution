"""Synthetic original-evidence joins, never actual solver/runtime acceptance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_python_producer_admission_gate import D, _chain
from test_static_python_fixed_profile import _raw
from test_static_python_fixed_runtime_observation import _runtime_vector

from lunar_evolution import static_python_fixed_producer_evidence as evidence
from lunar_evolution.native_trusted_attempt import NativeTrustedAttemptObservation
from lunar_evolution.native_trusted_output import NativeTrustedOutputPreparation
from lunar_evolution.native_trusted_scheduler import NativeTrustedProducerRun
from lunar_evolution.producer_broker_ipc import ProducerBrokerObservation
from lunar_evolution.producer_launcher import build_producer_launch_attestation
from lunar_evolution.producer_request_transport import (
    HostRequestEvent,
    HostRequestJournalIdentity,
    HostRequestSnapshot,
)


def _fixture(tmp_path):
    # Rebind explicit inert records; none of these images is executed.
    chain = _chain(tmp_path, "openevolve")
    binding, receipt, plan, result = chain[0], chain[5], chain[6], chain[8]
    request, payload = _runtime_vector()
    intent = replace(
        binding.intent, executable_sha256=hashlib.sha256(request.image).hexdigest(),
        executable_size=len(request.image), executable_device=19, executable_inode=77,
        intent_sha256=None,
    )
    intent = replace(intent, intent_sha256=intent.digest())
    attestation = build_producer_launch_attestation(intent, "inert-evidence-only")
    trusted = dict(receipt.trusted_execution)
    trusted["broker_journal_identity"] = {
        **trusted["broker_journal_identity"], "intent_sha256": intent.intent_sha256,
    }
    receipt = replace(
        receipt, intent_sha256=intent.intent_sha256, attestation_sha256=attestation.attestation_sha256,
        executable_identity=evidence._sha({
            "sha256": intent.executable_sha256, "size": intent.executable_size,
            "device": intent.executable_device, "inode": intent.executable_inode,
            "mtime_ns": intent.executable_mtime_ns, "ctime_ns": intent.executable_ctime_ns,
        }), execution_snapshot_sha256=intent.executable_sha256,
        execution_snapshot_size=intent.executable_size, trusted_execution=trusted, receipt_sha256=None,
    )
    broker = ProducerBrokerObservation(
        HostRequestSnapshot((HostRequestEvent(1, "request-1", "completed", 1),), 1, 0,
                            intent.request_timeout_seconds, intent.max_requests),
        tmp_path / "original-broker-journal",
        HostRequestJournalIdentity(**trusted["broker_journal_identity"]),
        trusted["broker_journal_sha256"], trusted["broker_journal_bytes"], True, "completed", (1, 2),
    )
    observed = request.compare(
        _raw(payload) + b"\n", image_device=19, image_inode=77,
        target_pid=receipt.pid, manifest_sha256=payload["manifest_sha256"],
    )
    attempt = NativeTrustedAttemptObservation(
        intent.launch_id, intent.journal_id, "recovery_required", "inert-test-only",
        receipt.registration_sha256, True, True, 0, "cleaned", D, D, D,
        broker_observation=broker, live_modules_observation=observed,
    )
    output = NativeTrustedOutputPreparation(
        D, D, receipt.envelope_evidence.sha256, result, (), (), plan,
        receipt.receipt_sha256, "brokered_requests_only", False,
    )
    run = NativeTrustedProducerRun(attempt, receipt, output)
    return SimpleNamespace(run=run, request=request, intent=intent, attestation=attestation)


def _compose(value, **updates):
    return evidence.compose_fixed_python_producer_evidence(
        value.run, intent=value.intent, attestation=value.attestation,
        request=value.request, **updates,
    )


def test_original_startup_native_join_exports_missing_lifecycle_without_authority(tmp_path):
    value = _fixture(tmp_path)
    composed = _compose(value)
    report = composed.to_dict()
    assert composed.run is value.run and composed.request is value.request
    assert composed.facts.live_modules_observation is not None
    assert report["protocol"] == evidence.PROTOCOL and report["status"] == "incomplete"
    assert report["missing_evidence"] == list(evidence.MISSING_EVIDENCE)
    assert report["execution_receipt_sha256"] == value.run.receipt.receipt_sha256
    assert report["process_terminal_sha256"] == value.run.attempt.terminal_sha256
    assert report["startup_observation_sha256"] == value.run.attempt.live_modules_observation.observation_sha256
    assert report["startup_observation"]["runtime"]["stdio"][-1]["errors"] == "backslashreplace"
    assert all(report[name] is False for name in (
        "live_runtime_authenticated", "immutable_custody_verified", "production_admission", "online_publication",
    ))
    assert "computation_sha256" not in report and "pycache_absent" not in report
    digest = report.pop("evidence_sha256")
    assert evidence._sha(report) == digest
    assert b"inert-evidence-only" not in composed.to_json()


@pytest.mark.parametrize("fault", [
    "run_copy", "attempt_copy", "receipt_copy", "output_copy", "observation_copy", "raw_copy",
    "request_copy", "intent_copy", "attestation_copy", "facts_copy", "wire_copy",
    "sink_source_copy", "receipt_nested", "broker_identity", "helper_code", "helper_replacement",
    "helper_defaults", "helper_kwdefaults", "helper_closure",
])
def test_retained_join_rejects_same_value_replacement_and_drift(tmp_path, monkeypatch, fault):
    value = _fixture(tmp_path)
    composed = _compose(value)
    if fault in {"run_copy", "request_copy", "intent_copy", "attestation_copy", "facts_copy"}:
        field = fault.removesuffix("_copy")
        object.__setattr__(composed, field, replace(getattr(composed, field)))
    elif fault in {"attempt_copy", "receipt_copy", "output_copy"}:
        field = fault.removesuffix("_copy")
        object.__setattr__(value.run, field, replace(getattr(value.run, field)))
    elif fault == "observation_copy":
        object.__setattr__(value.run.attempt, "live_modules_observation",
                           replace(value.run.attempt.live_modules_observation))
    elif fault == "raw_copy":
        observed = value.run.attempt.live_modules_observation
        object.__setattr__(observed, "canonical_bytes", bytes(bytearray(observed.canonical_bytes)))
    elif fault == "wire_copy":
        object.__setattr__(composed, "_wire", bytes(bytearray(composed._wire)))
    elif fault == "sink_source_copy":
        object.__setattr__(value.request, "runtime_main_source", bytes(bytearray(value.request.runtime_main_source)))
    elif fault == "receipt_nested":
        value.run.receipt.owner_identity["unexpected"] = True
    elif fault == "broker_identity":
        object.__setattr__(value.run.attempt.broker_observation.journal_identity, "wall_deadline_ns", 42)
    elif fault == "helper_code":
        monkeypatch.setattr(evidence.runtime._runtime_facts, "__code__", (lambda *_args: None).__code__)
    elif fault == "helper_defaults":
        monkeypatch.setattr(evidence._capture_pin, "__defaults__", (1,))
    elif fault == "helper_kwdefaults":
        monkeypatch.setitem(evidence.openevolve._open_flags.__kwdefaults__, "directory", True)
    elif fault == "helper_closure":
        cell = evidence.ProducerResultEnvelope.__init__.__closure__[0]
        monkeypatch.setattr(cell, "cell_contents", type("ForeignConstructorCapture", (), {}))
    else:
        original = evidence.runtime.validate_fixed_python_runtime_observation_policy
        monkeypatch.setattr(evidence.runtime, "validate_fixed_python_runtime_observation_policy",
                            lambda *args, **kwargs: original(*args, **kwargs))
    with pytest.raises(evidence.FixedPythonProducerEvidenceError):
        composed.to_json()


@pytest.mark.parametrize("fault", [
    "pid", "image_device", "intent", "attestation", "terminal", "stream_capture", "output_capture",
    "broker_sha", "broker_deadline", "broker_file", "broker_count", "broker_incomplete", "output_claim",
    "result_run", "result_budget", "publication", "status", "legacy_sink",
])
def test_foreign_or_incomplete_native_inputs_refuse_instead_of_filling_facts(tmp_path, fault):
    value = _fixture(tmp_path)
    run = value.run
    if fault in {"pid", "image_device"}:
        field = "target_pid" if fault == "pid" else fault
        observed = run.attempt.live_modules_observation
        object.__setattr__(observed, field, getattr(observed, field) + 1)
    elif fault == "intent":
        value.intent = replace(value.intent, task_id="other-task", intent_sha256=None)
    elif fault == "attestation":
        value.attestation = replace(value.attestation, intent_sha256="f" * 64, attestation_sha256=None)
    elif fault in {"terminal", "stream_capture", "output_capture"}:
        field = {"terminal": "terminal_sha256", "stream_capture": "stream_capture_sha256",
                 "output_capture": "output_capture_sha256"}[fault]
        object.__setattr__(run.attempt, field, "f" * 64)
    elif fault.startswith("broker_"):
        broker = run.attempt.broker_observation
        if fault == "broker_deadline":
            object.__setattr__(broker.journal_identity, "wall_deadline_ns", None)
        elif fault == "broker_count":
            object.__setattr__(broker.snapshot, "admitted_count", 0)
        else:
            field, update = {"broker_sha": ("journal_sha256", "f" * 64),
                             "broker_file": ("journal_file_identity", (1, 3)),
                             "broker_incomplete": ("complete", False)}[fault]
            object.__setattr__(broker, field, update)
    elif fault == "output_claim":
        object.__setattr__(run.output, "publication_eligible", True)
    elif fault in {"result_run", "result_budget"}:
        field, update = ("producer_run_id", "foreign") if fault == "result_run" else ("budget", {"requests": 2})
        object.__setattr__(run.output.envelope, field, update)
    elif fault == "publication":
        object.__setattr__(run, "publication", object())
    elif fault == "status":
        object.__setattr__(run, "status", "published")
    else:
        object.__setattr__(value.request, "source_profile", "fixed-live-private-sink-v1")
    with pytest.raises(evidence.FixedPythonProducerEvidenceError):
        _compose(value)


def test_export_checks_actual_source_materials_without_closing_missing_lifecycle(tmp_path):
    value = _fixture(tmp_path)
    root = tmp_path / "completed"
    root.mkdir()
    (root / "candidate.py").write_text("answer = 1\n")
    (root / "result.json").write_text(json.dumps({
        "candidate_path": "candidate.py", "evaluation": {"combined_score": 3},
    }))
    _, path, source, present, score_present, digest = evidence.openevolve._read_openevolve_snapshot(
        root, "result.json",
    )
    material = evidence.ProducerMaterial(
        kind="candidate_source", path=path, size=len(source), sha256=hashlib.sha256(source).hexdigest(),
        external_evidence={"present": present, "score_present": score_present, "payload_sha256": digest},
    )
    result = replace(value.run.output.envelope, materials=(material,))
    value.run = replace(value.run, output=replace(value.run.output, envelope=result))
    composed = _compose(value)
    original = composed.to_json()
    assert evidence.read_fixed_python_producer_evidence_export(composed, root) == original
    assert json.loads(original)["missing_evidence"] == list(evidence.MISSING_EVIDENCE)
    (root / "candidate.py").write_text("answer = 2\n")
    with pytest.raises(evidence.FixedPythonProducerEvidenceError):
        evidence.read_fixed_python_producer_evidence_export(composed, root)


def test_export_refuses_changed_originals_before_source_read(tmp_path, monkeypatch):
    value = _fixture(tmp_path)
    composed = _compose(value)
    object.__setattr__(value.run, "receipt", replace(value.run.receipt))
    monkeypatch.setattr(evidence.openevolve, "_external_root",
                        lambda *_args: pytest.fail("source I/O before original checks"))
    with pytest.raises(evidence.FixedPythonProducerEvidenceError):
        evidence.read_fixed_python_producer_evidence_export(composed, tmp_path)


def test_export_never_accepts_detached_report_as_original_evidence(tmp_path):
    report = _compose(_fixture(tmp_path)).to_json()
    for value in (report, json.loads(report), SimpleNamespace(to_json=lambda: report)):
        with pytest.raises(evidence.FixedPythonProducerEvidenceError):
            evidence.read_fixed_python_producer_evidence_export(value, tmp_path)


@pytest.mark.parametrize("replacement", ["copy", "method", "staticmethod", "to_dict"])
def test_export_refuses_copied_container_or_replaced_class_methods_before_source(tmp_path, monkeypatch, replacement):
    composed = _compose(_fixture(tmp_path))
    if replacement == "copy":
        composed = replace(composed)
    else:
        method = "to_dict" if replacement == "to_dict" else "to_json"
        function = lambda *_args: b'{"production_admission":true}'
        monkeypatch.setattr(evidence.FixedPythonProducerEvidence, method,
                            staticmethod(function) if replacement == "staticmethod" else function)
    monkeypatch.setattr(evidence.openevolve, "_external_root",
                        lambda *_args: pytest.fail("source I/O before container/helper checks"))
    with pytest.raises(evidence.FixedPythonProducerEvidenceError):
        evidence.read_fixed_python_producer_evidence_export(composed, tmp_path)
