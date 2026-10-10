"""Provider-free refusal and DTO tests; no fixed-profile acquisition is fabricated."""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from tests.test_static_python_source_tree_observation import _bundle, _entries, _observe
from tests.test_static_python_verified_inputs import _receipt
from tools.static_python_fixture import source_provenance as provenance
from tools.static_python_fixture import verified_inputs
from tools.static_python_fixture.archive_observation import ArchiveSourceIdentity
from tools.static_python_fixture.source_tree_observation import (
    SOURCE_TREE_OBSERVATION_SCHEMA,
    SOURCE_TREE_SCHEMA,
    StaticPythonSourceTreeFile,
    StaticPythonSourceTreeObservation,
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def _inputs(signature="not-performed"):
    observation = _observe(_bundle(_entries()))
    raw = _canonical(_receipt(signature=signature))
    pins = {"expected_receipt_sha256": hashlib.sha256(raw).hexdigest(),
            "expected_manifest_sha256": observation.manifest_sha256,
            "expected_source_tree_sha256": observation.source_tree_sha256}
    return raw, observation, pins


def _coherent_detached_inputs(signature="not-performed"):
    """Handmade matching metadata only; no archive was acquired or authenticated."""
    receipt_payload = _receipt(signature=signature)
    raw = _canonical(receipt_payload)
    file = StaticPythonSourceTreeFile(receipt_payload["root"] + "/synthetic", 0o644, 2,
                                      hashlib.sha256(b"ab").hexdigest())
    file_wire = {"path": file.path, "mode": file.mode, "size": file.size,
                 "sha256": file.sha256}
    tree_raw = _canonical({"schema": SOURCE_TREE_SCHEMA, "archive": "cpython",
                           "root": receipt_payload["root"], "version": receipt_payload["version"],
                           "files": [file_wire]})
    tree_sha = hashlib.sha256(tree_raw).hexdigest()
    identity = ArchiveSourceIdentity(1, 2, receipt_payload["size"], 0o644, 0, 0)
    record = {
        "schema": SOURCE_TREE_OBSERVATION_SCHEMA, "archive": "cpython",
        "root": receipt_payload["root"], "version": receipt_payload["version"],
        "archive_sha256": receipt_payload["sha256"],
        "snapshot_sha256": receipt_payload["sha256"],
        "manifest_sha256": "b" * 64, "source_tree_sha256": tree_sha,
        "profile_pin_verified": True, "metadata_validation": "validated",
        "source_preimages_checked": False, "signature_verification": "not-performed",
        "source_identity": dataclasses.asdict(identity), "total_bytes": file.size,
        "files": [file_wire],
    }
    observation_raw = _canonical(record)
    observation = StaticPythonSourceTreeObservation(
        SOURCE_TREE_OBSERVATION_SCHEMA, "cpython", receipt_payload["root"],
        receipt_payload["version"], receipt_payload["sha256"],
        receipt_payload["sha256"], "b" * 64,
        tree_sha, (file,), file.size, tree_raw, True, "validated", False, "not-performed",
        identity, observation_raw, hashlib.sha256(observation_raw).hexdigest(),
    )
    pins = {"expected_receipt_sha256": hashlib.sha256(raw).hexdigest(),
            "expected_manifest_sha256": observation.manifest_sha256,
            "expected_source_tree_sha256": observation.source_tree_sha256}
    return raw, observation, pins


def _refused(call, reason):
    with pytest.raises(provenance.SourceProvenanceComparisonError) as caught:
        call()
    assert caught.value.reason == "source_provenance_" + reason
    assert str(caught.value) == caught.value.reason


def _repin_observation(observation, **changes):
    """Keep a malformed/inert fixture coherent only to exercise later refusal gates."""
    result = dataclasses.replace(observation, **changes)
    payload = json.loads(observation.canonical_json)
    for field, value in changes.items():
        if field in payload:
            payload[field] = value
    canonical = _canonical(payload)
    return dataclasses.replace(result, canonical_json=canonical,
                               observation_sha256=hashlib.sha256(canonical).hexdigest())


@pytest.mark.parametrize("signature", ["verified", "not-performed", "unavailable", "failed"])
def test_existing_receipt_declarations_never_upgrade_inert_observation(signature):
    raw, observation, pins = _inputs(signature)
    receipt = verified_inputs.validate_static_python_archive_receipt(
        raw, expected_sha256=pins["expected_receipt_sha256"],
    )
    assert receipt.signature_verification == signature
    _refused(lambda: provenance.compare_source_provenance(raw, observation, **pins),
             "observation_inert_or_unknown")


def test_stale_inert_upgrade_cannot_bypass_full_canonical_check():
    raw, observation, pins = _inputs()
    forged = dataclasses.replace(observation, profile_pin_verified=True,
                                 metadata_validation="validated")
    _refused(lambda: provenance.compare_source_provenance(raw, forged, **pins),
             "observation_canonical_mismatch")


@pytest.mark.parametrize("signature", ["verified", "not-performed", "unavailable", "failed"])
def test_coherent_detached_metadata_comparison_preserves_declarations_without_admission(signature):
    # This is structural agreement of handmade metadata, not an archive
    # observation, release acquisition or G1 acceptance result.
    raw, observation, pins = _coherent_detached_inputs(signature)
    result = provenance.compare_source_provenance(raw, observation, **pins)
    assert result.declared_signature_verification == signature
    assert result.observed_signature_verification == "not-performed"
    assert result.signature_verification_performed is False
    assert result.execution_performed is False
    assert result.runtime_load_protection is False
    assert result.production_admission is False
    assert result.general_code_origin_protection is False
    assert result.comparison_sha256 == hashlib.sha256(result.to_json()).hexdigest()
    assert result.files == observation.files
    assert result.files is not observation.files
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.files[0].size = 9
    detached = result.to_dict()
    detached["files"][0]["size"] = 9
    assert result.to_dict()["files"][0]["size"] == 2


@pytest.mark.parametrize("name,reason", [
    ("expected_manifest_sha256", "manifest_pin_mismatch"),
    ("expected_source_tree_sha256", "source_tree_pin_mismatch"),
])
def test_retained_tree_and_manifest_pins_are_independent(name, reason):
    raw, observation, pins = _coherent_detached_inputs()
    _refused(lambda: provenance.compare_source_provenance(
        raw, observation, **{**pins, name: "c" * 64}), reason)


def test_resigned_snapshot_digest_drift_remains_a_refusal():
    raw, observation, pins = _coherent_detached_inputs()
    changed = _repin_observation(observation, snapshot_sha256="c" * 64)
    _refused(lambda: provenance.compare_source_provenance(raw, changed, **pins),
             "snapshot_archive_mismatch")


@pytest.mark.parametrize("field,value,reason", [
    ("schema", "unknown", "observation_schema_invalid"),
    ("observation_sha256", "a" * 64, "observation_digest_mismatch"),
    ("canonical_json", b"{}", "observation_canonical_mismatch"),
    ("tree_json", b"{}", "tree_canonical_mismatch"),
    ("total_bytes", True, "total_bytes_invalid"),
    ("total_bytes", 1, "total_bytes_mismatch"),
    ("files", [], "observation_files_invalid"),
    ("profile_pin_verified", 1, "observation_status_invalid"),
    ("archive_sha256", "f" * 64, "observation_digest_invalid"),
])
def test_observation_fields_and_retained_wires_are_checked(field, value, reason):
    raw, observation, pins = _inputs()
    forged = dataclasses.replace(observation, **{field: value})
    _refused(lambda: provenance.compare_source_provenance(raw, forged, **pins), reason)


@pytest.mark.parametrize("status", ["unknown", "validated", "skipped-inert-profile"])
def test_coherent_inert_or_unknown_metadata_still_refuses(status):
    raw, observation, pins = _inputs()
    changed = _repin_observation(observation, metadata_validation=status)
    _refused(lambda: provenance.compare_source_provenance(raw, changed, **pins),
             "observation_inert_or_unknown")


@pytest.mark.parametrize("name,reason", [
    ("expected_receipt_sha256", "receipt_pin_invalid"),
    ("expected_manifest_sha256", "manifest_pin_invalid"),
    ("expected_source_tree_sha256", "source_tree_pin_invalid"),
])
def test_invalid_independent_pins_refuse_before_validation(monkeypatch, name, reason):
    raw, observation, pins = _inputs()
    monkeypatch.setattr(provenance, "validate_static_python_archive_receipt",
                        lambda *_args, **_kwargs: pytest.fail("receipt parser"))
    _refused(lambda: provenance.compare_source_provenance(
        raw, observation, **{**pins, name: "0" * 64}), reason)


@pytest.mark.parametrize("value", [None, bytearray(b"{}"), memoryview(b"{}"), "{}"])
def test_receipt_exact_bytes_and_cheap_bounds(value):
    _, observation, pins = _inputs()
    _refused(lambda: provenance.compare_source_provenance(value, observation, **pins),
             "receipt_wire_invalid")


def test_receipt_uses_original_schema_and_canonical_validator():
    raw, observation, pins = _inputs()
    unknown = json.loads(raw)
    unknown["source_tree_sha256"] = observation.source_tree_sha256
    changed = _canonical(unknown)
    _refused(lambda: provenance.compare_source_provenance(
        changed, observation, **{**pins, "expected_receipt_sha256": hashlib.sha256(changed).hexdigest()}),
        "receipt_receipt_shape_invalid")
    _refused(lambda: provenance.compare_source_provenance(raw + b" ", observation, **pins),
             "receipt_receipt_noncanonical_json")


def test_deeply_frozen_result_and_detached_views_do_not_alias():
    # Direct DTO construction tests the container contract only. It is not a
    # positive comparator result and does not represent acquired release bytes.
    file = StaticPythonSourceTreeFile("Python-3.13.12/file", 0o644, 2,
                                      hashlib.sha256(b"ab").hexdigest())
    raw = _canonical({"files": [{"path": file.path, "mode": file.mode,
                                "size": file.size, "sha256": file.sha256}]})
    result = provenance.SourceProvenanceComparison(
        provenance.SOURCE_PROVENANCE_SCHEMA, "a" * 64, "b" * 64, "c" * 64, "d" * 64,
        (file,), 2, "verified", "not-performed", False, False, False, False, False,
        raw, hashlib.sha256(raw).hexdigest(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.files[0].size = 8
    detached = result.to_dict()
    detached["files"][0]["size"] = 8
    assert result.files[0].size == 2
    assert result.to_dict()["files"][0]["size"] == 2
    assert result.signature_verification_performed is False
    assert result.execution_performed is False
    assert result.runtime_load_protection is False
    assert result.production_admission is False
    assert result.general_code_origin_protection is False


def test_comparator_has_no_external_effects_even_on_inert_refusal(monkeypatch):
    raw, observation, pins = _inputs()
    import builtins
    import os
    import socket
    import subprocess

    def forbidden(*_args, **_kwargs):
        pytest.fail("pure comparator must remain detached")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    _refused(lambda: provenance.compare_source_provenance(raw, observation, **pins),
             "observation_inert_or_unknown")
