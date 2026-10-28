"""Actual bounded envelope acquisition with inert process/receipt boundaries."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import time
from dataclasses import asdict, fields, replace
from types import SimpleNamespace

import pytest
from test_native_trusted_output import _fixture
from test_static_python_fixed_producer_evidence import _compose
from test_static_python_fixed_producer_evidence import _fixture as _evidence_fixture

from lunar_evolution import native_trusted_output as output_module
from lunar_evolution import producer_process
from lunar_evolution.native_trusted_output import (
    NativeTrustedOutputError,
    NativeTrustedOutputPreparation,
    _native_output_envelope_pin,
    prepare_native_trusted_output,
)


def test_original_read_and_parse_are_retained_without_durable_wire_change(tmp_path, monkeypatch):
    output, _, arguments = _fixture(tmp_path, monkeypatch)
    reads = []
    read_code = output_module._files.read_regular_file.__code__
    previous = sys.getprofile()

    def observe(frame, event, returned):
        if (event == "return" and frame.f_code is read_code
                and frame.f_locals.get("path") == output / "producer-result.json"
                and type(returned) is bytes):
            reads.append(returned)

    # Observe the original reader; replacing its shared alias also changes the
    # downstream bundle root policy and would refuse before this assertion.
    sys.setprofile(observe)
    try:
        prepared = prepare_native_trusted_output(tmp_path, **arguments)
    finally:
        sys.setprofile(previous)
    pin = _native_output_envelope_pin(prepared)
    assert pin is not None and pin[2] is reads[-1]
    assert pin[4] is prepared.envelope
    assert pin[2] == (output / "producer-result.json").read_bytes()
    assert hashlib.sha256(pin[2]).hexdigest() == prepared.envelope_bytes_sha256
    assert "_original_envelope_acquisition" not in {field.name for field in fields(prepared)}
    # Existing asdict payloads, durable comparisons and detached recovery still
    # contain only DTO fields and never serialize process-local provenance.
    payload = asdict(prepared)
    assert "_original_envelope_acquisition" not in payload
    json.dumps(payload)
    assert prepared.publication_eligible is False


def test_dto_constructor_and_detached_copies_do_not_acquire_original_guarantee(tmp_path, monkeypatch):
    _, _, arguments = _fixture(tmp_path, monkeypatch)
    prepared = prepare_native_trusted_output(tmp_path, **arguments)
    assert _native_output_envelope_pin(replace(prepared)) is None
    detached = NativeTrustedOutputPreparation(**{
        field.name: getattr(prepared, field.name) for field in fields(prepared)
    })
    assert _native_output_envelope_pin(detached) is None
    with pytest.raises(TypeError):
        NativeTrustedOutputPreparation(**{
            **{field.name: getattr(prepared, field.name) for field in fields(prepared)},
            "_original_envelope_acquisition": prepared._original_envelope_acquisition,
        })
    assert _native_output_envelope_pin(copy.copy(prepared)) is None
    assert _native_output_envelope_pin(copy.deepcopy(prepared)) is None
    with pytest.raises(NativeTrustedOutputError, match="acquisition_detached"):
        copy.copy(prepared._original_envelope_acquisition)
    with pytest.raises(NativeTrustedOutputError, match="acquisition_detached"):
        copy.deepcopy(prepared._original_envelope_acquisition)


@pytest.mark.parametrize("fault", ["same_raw", "raw", "envelope", "semantic", "evidence", "digest"])
def test_original_acquisition_refuses_raw_identity_and_semantic_drift(tmp_path, monkeypatch, fault):
    _, _, arguments = _fixture(tmp_path, monkeypatch)
    prepared = prepare_native_trusted_output(tmp_path, **arguments)
    original = prepared._original_envelope_acquisition
    if fault == "same_raw":
        original.raw = bytes(bytearray(original.raw))
    elif fault == "raw":
        original.raw = original.raw + b" "
    elif fault == "envelope":
        object.__setattr__(prepared, "envelope", replace(prepared.envelope))
    elif fault == "semantic":
        prepared.envelope.budget["requests"] = 0
    elif fault == "evidence":
        original.evidence = replace(original.evidence)
    else:
        object.__setattr__(prepared, "envelope_bytes_sha256", "0" * 64)
    with pytest.raises(NativeTrustedOutputError, match="acquisition_changed"):
        _native_output_envelope_pin(prepared)


def _original_output(value, tmp_path, monkeypatch):
    """Read/parse a real local envelope; surrounding process facts stay inert."""
    previous, intent = value.run.output, value.intent
    batch = tmp_path / "evolution" / "producer-batches" / intent.journal_id
    path = batch / intent.envelope_path
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(previous.envelope.to_dict(), indent=2).encode()
    path.write_bytes(raw)
    evidence, _ = producer_process._read_envelope(
        path, relative_path=intent.envelope_path, limit=intent.output_max_bytes,
        deadline=time.monotonic() + 5, monotonic=time.monotonic,
    )
    receipt = replace(value.run.receipt, envelope_evidence=evidence, receipt_sha256=None)
    capture = {"broker_evidence": {"complete": True, "declared_count_matches": True},
               "capture_sha256": previous.output_capture_sha256,
               "envelope_evidence": {"sha256": evidence.sha256}}
    monkeypatch.setattr(output_module, "AlgorithmProblemContract", SimpleNamespace)
    monkeypatch.setattr(output_module, "recover_native_trusted_attempt", lambda *_a, **_k: {
        "protocol": "lunar-native-trusted-process-terminal-v1", "process_status": "exited_zero",
        "cleanup_status": "cleaned", "gate_released": True, "target_started": True,
        "terminal_sha256": previous.process_terminal_sha256,
    })
    monkeypatch.setattr(output_module, "recover_native_trusted_execution_receipt", lambda *_a, **_k: receipt)
    monkeypatch.setattr(output_module, "recover_native_trusted_output_capture", lambda *_a, **_k: capture)
    monkeypatch.setattr(output_module, "prepare_producer_bundle_manifest", lambda *_a, **_k: ())
    monkeypatch.setattr(output_module, "prepare_producer_bundle_drafts", lambda *_a, **_k: ())
    monkeypatch.setattr(output_module, "build_producer_bundle_admission_plan",
                        lambda *_a, **_k: previous.admission_plan)
    prepared = prepare_native_trusted_output(
        tmp_path, intent=intent, attestation=value.attestation, artifact=object(),
        contract=SimpleNamespace(digest=lambda: intent.contract_sha256), groups=(),
        **{name: getattr(intent, name) for name in (
            "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint",
            "dependency_sha256", "environment_sha256")},
        require_same_attempt_capture=True, require_execution_receipt=True,
    )
    value.run = replace(value.run, receipt=receipt, output=prepared)
    return prepared


def test_expanded_inspection_joins_original_raw_without_claiming_completed_runtime(tmp_path, monkeypatch):
    value = _evidence_fixture(tmp_path)
    prepared = _original_output(value, tmp_path, monkeypatch)
    inspected = _compose(value)
    report = inspected.to_dict()
    assert report["captured_envelope_semantic_join_verified"] is True
    assert "original_captured_envelope_semantic_join" not in report["missing_evidence"]
    assert set(report["missing_evidence"]) == {
        "original_computation_observation", "original_pycache_observation",
        "accepted_build_input_custody", "accepted_runtime_authority_root",
    }
    assert report["production_admission"] is report["online_publication"] is False
    # The receipt's original raw wire digest and canonical semantic digest are
    # distinct, both pinned to the same generic parsed object.
    assert report["envelope_bytes_sha256"] == prepared.envelope_bytes_sha256
    assert report["envelope_sha256"] == prepared.envelope.envelope_sha256
    assert report["envelope_bytes_sha256"] != report["envelope_sha256"]


def test_expanded_inspection_cannot_upgrade_constructed_or_detached_dto(tmp_path, monkeypatch):
    value = _evidence_fixture(tmp_path)
    _original_output(value, tmp_path, monkeypatch)
    value.run = replace(value.run, output=replace(value.run.output))
    report = _compose(value).to_dict()
    assert report["captured_envelope_semantic_join_verified"] is False
    assert "original_captured_envelope_semantic_join" in report["missing_evidence"]


def test_expanded_inspection_detects_same_hash_different_dto_after_composition(tmp_path, monkeypatch):
    value = _evidence_fixture(tmp_path)
    _original_output(value, tmp_path, monkeypatch)
    inspected = _compose(value)
    value.run.output.envelope.budget["attempts"] = 2
    with pytest.raises(ValueError, match="fixed_python_producer_evidence_refused"):
        inspected.to_json()


@pytest.mark.parametrize("fault", ["native_alias", "module_alias", "helper_code"])
def test_acquisition_helper_identity_and_code_are_retained(tmp_path, monkeypatch, fault):
    value = _evidence_fixture(tmp_path)
    inspected = _compose(value)
    if fault == "native_alias":
        from lunar_evolution import native_trusted_scheduler

        monkeypatch.setattr(native_trusted_scheduler, "_native_output_envelope_pin", lambda _output: None)
    elif fault == "module_alias":
        original = output_module._native_output_envelope_pin
        monkeypatch.setattr(output_module, "_native_output_envelope_pin", lambda output: original(output))
    else:
        monkeypatch.setattr(output_module._native_output_envelope_pin, "__code__", (lambda _output: None).__code__)
    with pytest.raises(ValueError, match="fixed_python_producer_evidence_refused"):
        inspected.to_json()
