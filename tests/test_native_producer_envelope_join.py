"""Real local v2 bytes with an explicitly inert native execution seam.

Pipes, broker exchanges, input files and envelope reads are real; native launch,
registration and receipts stay inert. No static runtime or candidate is run.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, fields, replace

import pytest
from test_native_producer_original_completion import _original
from test_static_python_fixed_producer_evidence import _compose

from lunar_evolution import native_trusted_attempt as native
from lunar_evolution import static_python_fixed_producer_evidence as evidence
from lunar_evolution.static_python_producer_envelope_source import (
    FIXED_PRODUCER_ENVELOPE_PROFILE,
    FIXED_PRODUCER_ENVELOPE_PROTOCOL,
)


def _original_v2(tmp_path, monkeypatch, **options):
    return _original(tmp_path, monkeypatch, envelope_profile=True, **options)


def test_original_v2_joins_exact_envelope_stat_without_runtime_authority(tmp_path, monkeypatch):
    value, inputs, _reader, root = _original_v2(tmp_path, monkeypatch)
    pin = native._original_native_completion_pin(value.run.attempt)
    assert pin is not None and len(pin) == 12 and pin[2] is inputs
    assert pin[3] is value.intent and pin[4] is value.attestation and pin[5] is value.request
    name, raw, stat_info = pin[11]
    assert name == "producer-result.json" and raw == (root / name).read_bytes()
    captured = value.run.output._original_envelope_acquisition
    expected = captured.evidence.to_dict()
    assert expected.pop("relative_path") == value.intent.envelope_path
    assert dict(stat_info) == expected and captured.raw == raw
    assert captured.raw is not raw
    records = [json.loads(line) for line in value.run.attempt.producer_completion_bytes.splitlines()]
    assert {item["profile"] for item in records} == {FIXED_PRODUCER_ENVELOPE_PROFILE}
    assert {item["protocol"] for item in records} == {FIXED_PRODUCER_ENVELOPE_PROTOCOL}
    assert records[1]["envelope"]["sha256"] == expected["sha256"]
    report = _compose(value).to_dict()
    assert report["captured_envelope_semantic_join_verified"] is True
    assert report["original_computation_observation_verified"] is True
    assert set(report["missing_evidence"]) == {
        "original_pycache_observation", "accepted_build_input_custody", "accepted_runtime_authority_root",
    }
    assert all(report[name] is False for name in (
        "live_runtime_authenticated", "immutable_custody_verified", "production_admission", "online_publication",
    ))
    assert "_original_completion_acquisition" not in asdict(value.run.attempt)
    assert "_original_completion_acquisition" not in {field.name for field in fields(value.run.attempt)}


@pytest.mark.parametrize("fault", ("run-id", "fingerprint", "manifest", "marker"))
def test_v2_retention_refuses_argv_not_bound_to_original_intent(tmp_path, monkeypatch, fault):
    with pytest.raises(ValueError):
        _original_v2(tmp_path, monkeypatch, argv_fault=fault)


@pytest.mark.parametrize("kind", ("replace", "copy", "deepcopy", "constructor"))
def test_v2_attempt_copies_cannot_recreate_private_acquisition(tmp_path, monkeypatch, kind):
    value, _inputs, _reader, _root = _original_v2(tmp_path, monkeypatch)
    original = value.run.attempt
    if kind == "replace":
        detached = replace(original)
    elif kind == "constructor":
        detached = native.NativeTrustedAttemptObservation(**{
            field.name: getattr(original, field.name) for field in fields(original)
        })
    else:
        detached = getattr(copy, kind)(original)
    assert native._original_native_completion_pin(detached) is None
    value.run = replace(value.run, attempt=detached)
    report = _compose(value).to_dict()
    assert report["original_computation_observation_verified"] is False
    assert "original_computation_observation" in report["missing_evidence"]


@pytest.mark.parametrize("fault", ("tuple-copy", "raw-copy", "stat", "raw", "run-id", "fingerprint"))
def test_v2_getter_refuses_replaced_original_envelope_and_launch_fields(tmp_path, monkeypatch, fault):
    value, _inputs, _reader, _root = _original_v2(tmp_path, monkeypatch)
    acquired = value.run.attempt._original_completion_acquisition
    name, raw, info = acquired.envelope
    if fault in {"run-id", "fingerprint"}:
        field = "run_id" if fault == "run-id" else "producer_fingerprint"
        replacement = "other-run" if fault == "run-id" else "f" * 64
        object.__setattr__(value.intent, field, replacement)
    elif fault == "stat":
        changed = dict(info)
        changed["inode"] += 1
        acquired.envelope = (name, raw, tuple(sorted(changed.items())))
    elif fault == "tuple-copy":
        acquired.envelope = tuple(item for item in acquired.envelope)
        assert acquired.envelope is not acquired._originals[-1]
    else:
        replacement = bytes(bytearray(raw)) if fault == "raw-copy" else raw + b" "
        assert replacement is not raw
        acquired.envelope = (name, replacement, info)
    with pytest.raises(native.NativeTrustedAttemptError, match="acquisition_changed"):
        native._original_native_completion_pin(value.run.attempt)


@pytest.mark.parametrize("fault", ("same-bytes-inode", "changed-bytes", "semantically-equivalent"))
def test_v2_export_rechecks_original_envelope_bytes_and_inode(tmp_path, monkeypatch, fault):
    value, _inputs, _reader, root = _original_v2(tmp_path, monkeypatch)
    retained = _compose(value)
    path = root / "producer-result.json"
    original = path.read_bytes()
    replacement = root / "replacement-envelope.json"
    if fault == "changed-bytes":
        changed = json.loads(original)
        changed["budget"]["requests"] = 0
        raw = json.dumps(changed).encode()
    else:
        raw = original if fault == "same-bytes-inode" else json.dumps(json.loads(original), separators=(",", ":")).encode()
    replacement.write_bytes(raw)
    # Create the replacement while the original inode exists, preventing inode
    # reuse from weakening the same-bytes refusal assertion.
    assert replacement.stat().st_ino != path.stat().st_ino
    os.replace(replacement, path)
    with pytest.raises(evidence.FixedPythonProducerEvidenceError):
        retained.to_json()


def test_v2_requires_separately_original_captured_envelope(tmp_path, monkeypatch):
    value, _inputs, _reader, _root = _original_v2(tmp_path, monkeypatch)
    value.run = replace(value.run, output=replace(value.run.output))
    report = _compose(value).to_dict()
    assert report["original_computation_observation_verified"] is False
    assert report["captured_envelope_semantic_join_verified"] is False
    assert "original_computation_observation" in report["missing_evidence"]


@pytest.mark.parametrize("field,value", (("inode", 1), ("device", 1), ("relative_path", "output/other.json")))
def test_v2_export_requires_captured_stat_and_path_to_match_native_original(tmp_path, monkeypatch, field, value):
    original, _inputs, _reader, _root = _original_v2(tmp_path, monkeypatch)
    retained = _compose(original)
    captured = original.run.output._original_envelope_acquisition.evidence
    replacement = getattr(captured, field) + value if type(value) is int else value
    object.__setattr__(captured, field, replacement)
    with pytest.raises(evidence.FixedPythonProducerEvidenceError):
        retained.to_json()


@pytest.mark.parametrize("owner,name", (
    (native, "compare_fixed_producer_envelope_completion"),
    (native, "validate_fixed_producer_envelope_argv"),
    (evidence.native, "_original_native_completion_pin"),
    (evidence.envelope_completion, "compare_fixed_producer_envelope_completion"),
    (evidence.envelope_source, "validate_fixed_producer_envelope_argv"),
    (evidence.native_output.ProducerEnvelopeEvidence, "__init__"),
    (evidence.native_output.ProducerEnvelopeEvidence, "to_dict"),
))
def test_v2_export_refuses_replacement_of_actual_helper_aliases(tmp_path, monkeypatch, owner, name):
    value, _inputs, _reader, _root = _original_v2(tmp_path, monkeypatch)
    retained = _compose(value)
    original = getattr(owner, name)
    monkeypatch.setattr(owner, name, lambda *args, **kwargs: original(*args, **kwargs))
    with pytest.raises(evidence.FixedPythonProducerEvidenceError):
        retained.to_json()


def test_v2_export_refuses_equivalent_comparison_constructor_alias(tmp_path, monkeypatch):
    value, _inputs, _reader, _root = _original_v2(tmp_path, monkeypatch)
    retained = _compose(value)
    original = evidence.envelope_completion.FixedProducerCompletionComparison

    class ReplacementComparison:
        def __new__(cls, *args, **kwargs):
            return original(*args, **kwargs)

    monkeypatch.setattr(evidence.envelope_completion, "FixedProducerCompletionComparison", ReplacementComparison)
    with pytest.raises(evidence.FixedPythonProducerEvidenceError):
        retained.to_json()
