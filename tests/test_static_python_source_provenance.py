"""Pure canonical source receipt/tree comparison tests."""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from lunar_evolution import source_provenance as provenance
from tests.test_static_python_source_tree_observation import _bundle, _entries, _observe


def _observation():
    inert = _observe(_bundle(_entries()))
    return dataclasses.replace(inert, profile_pin_verified=True, metadata_validation="validated")


def _receipt(observation):
    payload = {
        "schema": provenance.SOURCE_PROVENANCE_SCHEMA,
        "archive": observation.archive,
        "root": observation.root,
        "version": observation.version,
        "manifest_sha256": observation.manifest_sha256,
        "source_tree_sha256": observation.source_tree_sha256,
        "profile_pin_verified": True,
        "metadata_validation": "validated",
        "source_preimages_checked": observation.source_preimages_checked,
        "signature_verification": "not-performed",
        "total_bytes": observation.total_bytes,
        "files": observation.to_tree()["files"],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return raw, {
        "expected_receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "expected_manifest_sha256": observation.manifest_sha256,
        "expected_source_tree_sha256": observation.source_tree_sha256,
    }


def _refused(call, reason):
    with pytest.raises(provenance.SourceProvenanceComparisonError) as caught:
        call()
    assert caught.value.reason == "source_provenance_" + reason
    assert str(caught.value) == caught.value.reason


def test_matching_receipt_and_observation_return_detached_frozen_evidence():
    observation = _observation()
    raw, pins = _receipt(observation)
    result = provenance.compare_source_provenance(raw, observation, **pins)
    assert result.schema == provenance.SOURCE_PROVENANCE_SCHEMA
    assert result.profile_pin_verified is True
    assert result.signature_verification == "not-performed"
    assert result.comparison_sha256 == hashlib.sha256(result.to_json()).hexdigest()
    detached = result.to_dict()
    detached["files"].clear()
    assert len(result.files) == 3
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.total_bytes = 0


def test_pins_are_required_before_receipt_or_observation_work(monkeypatch):
    observation = _observation()
    raw, pins = _receipt(observation)
    monkeypatch.setattr(provenance, "_receipt", lambda *_args: pytest.fail("receipt"))
    expected_reasons = {
        "expected_receipt_sha256": "receipt_pin_invalid",
        "expected_manifest_sha256": "manifest_pin_invalid",
        "expected_source_tree_sha256": "source_tree_pin_invalid",
    }
    for name, reason in expected_reasons.items():
        changed = {**pins, name: "0" * 64}
        _refused(
            lambda changed=changed: provenance.compare_source_provenance(
                raw, observation, **changed,
            ),
                 reason)


def test_receipt_is_canonical_and_duplicate_free():
    observation = _observation()
    raw, pins = _receipt(observation)
    _refused(
        lambda: provenance.compare_source_provenance(
            raw + b" ", observation,
            **{**pins, "expected_receipt_sha256": hashlib.sha256(raw + b" ").hexdigest()},
        ),
             "receipt_canonical")
    duplicate = raw.replace(b'"archive":"cpython"', b'"archive":"cpython","archive":"cpython"')
    _refused(lambda: provenance.compare_source_provenance(
        duplicate, observation,
        **{**pins, "expected_receipt_sha256": hashlib.sha256(duplicate).hexdigest()}),
        "receipt_duplicate_key")


def test_unknown_receipt_fields_and_inert_observations_never_upgrade():
    observation = _observation()
    raw, pins = _receipt(observation)
    payload = json.loads(raw)
    payload["unknown"] = 1
    changed = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    _refused(
        lambda: provenance.compare_source_provenance(
            changed, observation,
            **{**pins, "expected_receipt_sha256": hashlib.sha256(changed).hexdigest()},
        ),
        "receipt_schema",
    )
    inert = dataclasses.replace(observation, profile_pin_verified=False,
                                metadata_validation="skipped-inert-profile")
    _refused(lambda: provenance.compare_source_provenance(raw, inert, **pins), "observation_inert")


def test_receipt_and_independent_pins_must_match_complete_tree():
    observation = _observation()
    raw, pins = _receipt(observation)
    payload = json.loads(raw)
    payload["files"][0]["size"] += 1
    changed = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    changed_pins = {**pins, "expected_receipt_sha256": hashlib.sha256(changed).hexdigest()}
    _refused(lambda: provenance.compare_source_provenance(changed, observation, **changed_pins),
             "observation_mismatch")
    _refused(lambda: provenance.compare_source_provenance(
        raw, observation, **{**pins, "expected_source_tree_sha256": "a" * 64}),
        "source_tree_pin_mismatch")


def test_status_and_signature_unknown_values_are_refused():
    observation = _observation()
    raw, pins = _receipt(observation)
    for field, value, reason in (("metadata_validation", "unknown", "receipt_metadata"),
                                 ("signature_verification", "verified", "receipt_signature"),
                                 ("profile_pin_verified", False, "receipt_inert")):
        payload = json.loads(raw)
        payload[field] = value
        changed = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        _refused(lambda changed=changed: provenance.compare_source_provenance(
            changed, observation,
            **{**pins, "expected_receipt_sha256": hashlib.sha256(changed).hexdigest()}), reason)


def test_comparator_has_no_external_effects(monkeypatch):
    observation = _observation()
    raw, pins = _receipt(observation)
    import builtins
    import os
    import socket
    import subprocess

    def forbidden(*_args, **_kwargs):
        pytest.fail("source provenance must stay detached")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    assert provenance.compare_source_provenance(raw, observation, **pins).profile_pin_verified
