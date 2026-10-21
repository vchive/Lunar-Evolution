"""Provider-free refusal and DTO tests; no fixed-profile acquisition is fabricated."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import lzma
import os
import socket
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

from tests.test_static_python_source_tree_observation import _bundle, _entries, _observe
from tests.test_static_python_verified_inputs import _receipt
from tools.static_python_fixture import (
    archive_observation,
    source_patches,
    source_staging,
    verified_inputs,
)
from tools.static_python_fixture import source_provenance as provenance
from tools.static_python_fixture import source_tree_observation as tree_observation
from tools.static_python_fixture.archive_observation import ArchiveSourceIdentity
from tools.static_python_fixture.source_tree_observation import (
    SOURCE_TREE_OBSERVATION_SCHEMA,
    SOURCE_TREE_SCHEMA,
    StaticPythonSourceTreeFile,
    StaticPythonSourceTreeObservation,
)

FIXTURE = Path(__file__).parent / "fixtures/static_python_source"


def _staging_inputs(tmp_path):
    sources = {path: (FIXTURE / (path + ".source")).read_bytes()
               for path in source_patches.SOURCE_PATHS}
    root = "Python-3.13.12"
    entries = []
    root_entry = tarfile.TarInfo(root)
    root_entry.type = tarfile.DIRTYPE
    root_entry.mode = 0o755
    entries.append((root_entry, None))
    for path, raw in sources.items():
        member = tarfile.TarInfo(root + "/" + path)
        member.mode = 0o644
        member.size = len(raw)
        entries.append((member, raw))
    empty_dir = tarfile.TarInfo(root + "/explicit-empty")
    empty_dir.type = tarfile.DIRTYPE
    empty_dir.mode = 0o777
    entries.append((empty_dir, None))
    extra = tarfile.TarInfo(root + "/extra/unchanged.bin")
    extra.mode = 0o777
    extra.size = len(b"unchanged\x00data")
    entries.append((extra, b"unchanged\x00data"))
    empty_file = tarfile.TarInfo(root + "/extra/empty")
    empty_file.mode = 0o644
    empty_file.size = 0
    entries.append((empty_file, b""))
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for member, raw in entries:
            tar.addfile(member, None if raw is None else io.BytesIO(raw))
    compressed = lzma.compress(stream.getvalue(), format=lzma.FORMAT_XZ)
    members = sorted(({
        "path": member.name.rstrip("/") if member.isdir() else member.name,
        "kind": "directory" if member.isdir() else "file", "size": member.size,
        "mode": member.mode,
        "sha256": None if raw is None else hashlib.sha256(raw).hexdigest(),
    } for member, raw in entries), key=lambda item: item["path"])
    manifest = {"schema": "lunar-static-python-extraction-manifest-v1", "archive": "cpython",
                "root": root, "archive_sha256": hashlib.sha256(compressed).hexdigest(),
                "members": members}
    manifest_raw = _canonical(manifest)
    snapshot = archive_observation.snapshot_inert_archive_bytes(compressed, "cpython")
    bundle = snapshot, hashlib.sha256(manifest_raw).hexdigest()
    regular = sorted(({
        "path": member.name, "mode": member.mode, "size": member.size,
        "sha256": hashlib.sha256(raw).hexdigest(),
    } for member, raw in entries if raw is not None), key=lambda item: item["path"])
    tree = {"schema": tree_observation.SOURCE_TREE_SCHEMA, "archive": "cpython",
            "root": root, "version": "3.13.12", "files": regular}
    source_tree_sha256 = hashlib.sha256(_canonical(tree)).hexdigest()
    observation = tree_observation.observe_snapshot_source_tree(
        bundle[0], expected_manifest_sha256=bundle[1],
        expected_source_tree_sha256=source_tree_sha256, require_profile=False,
        deadline=time.monotonic() + 30.0,
    )
    destination = str(tmp_path.resolve() / "staged")
    staging = source_staging.stage_archive_sources(
        bundle[0], destination, expected_manifest_sha256=bundle[1],
        require_profile=False, deadline=time.monotonic() + 30.0,
    )
    pins = {"expected_staging_sha256": staging.staging_sha256,
            "expected_manifest_sha256": observation.manifest_sha256,
            "expected_source_tree_sha256": observation.source_tree_sha256}
    return observation, staging, pins, bundle[0].archive_size


def _repin_staging(staging, *, mutation=None, **dto_changes):
    payload = json.loads(staging.canonical_json)
    if mutation is not None:
        mutation(payload)
    raw = _canonical(payload)
    return dataclasses.replace(
        staging, canonical_json=raw, staging_sha256=hashlib.sha256(raw).hexdigest(),
        **dto_changes,
    )


def _profile_metadata(observation, staging, bundle_size):
    identity = ArchiveSourceIdentity(1, 2, bundle_size, 0o644, 0, 0)
    observation = dataclasses.replace(
        observation, profile_pin_verified=True, metadata_validation="validated",
        source_identity=identity,
    )
    record = json.loads(observation.canonical_json)
    record.update(profile_pin_verified=True, metadata_validation="validated",
                  source_identity=dataclasses.asdict(identity))
    raw = _canonical(record)
    observation = dataclasses.replace(observation, canonical_json=raw,
                                      observation_sha256=hashlib.sha256(raw).hexdigest())
    staging = _repin_staging(
        staging, mutation=lambda payload: payload.update(
            profile_pin_verified=True, metadata_validation="validated"),
    )
    return observation, staging


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
    if "archive_sha256" in changes and "snapshot_sha256" not in changes:
        payload["snapshot_sha256"] = changes["archive_sha256"]
        result = dataclasses.replace(result, snapshot_sha256=changes["archive_sha256"])
    if any(field in changes for field in ("archive", "root", "version", "files")):
        tree = json.loads(observation.tree_json)
        for field in ("archive", "root", "version", "files"):
            if field in changes:
                tree[field] = changes[field]
        tree_raw = _canonical(tree)
        tree_sha = hashlib.sha256(tree_raw).hexdigest()
        payload["source_tree_sha256"] = tree_sha
        result = dataclasses.replace(result, tree_json=tree_raw, source_tree_sha256=tree_sha)
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


def test_inert_source_tree_matches_complete_staging_and_fixed_postimages(tmp_path):
    observation, staging, pins, _archive_size = _staging_inputs(tmp_path)
    assert provenance.validate_source_staging_consistency(observation, staging, **pins) is None
    assert observation.profile_pin_verified is False
    manifest = staging.to_manifest()
    assert manifest["profile_pin_verified"] is False
    assert manifest["metadata_validation"] == "skipped-inert-profile"
    assert all(manifest[name] is False for name in (
        "release_verified", "source_execution_performed", "build_performed",
        "frozen_headers_generated", "runtime_execution_performed", "runtime_load_protection",
        "production_admission", "general_code_origin_protection",
    ))


def test_validated_profile_metadata_shape_matches_without_claiming_acquisition(tmp_path):
    observation, staging, pins, archive_size = _staging_inputs(tmp_path)
    observation, staging = _profile_metadata(observation, staging, archive_size)
    assert provenance.validate_source_staging_consistency(observation, staging, **{
        **pins, "expected_staging_sha256": staging.staging_sha256,
    }) is None
    assert observation.profile_pin_verified is True
    assert observation.metadata_validation == "validated"
    assert observation.signature_verification == "not-performed"


@pytest.mark.parametrize("pin,bad,reason", [
    ("expected_staging_sha256", "0" * 64, "staging_pin_invalid"),
    ("expected_staging_sha256", "a" * 64, "staging_pin_mismatch"),
    ("expected_manifest_sha256", "0" * 64, "manifest_pin_invalid"),
    ("expected_manifest_sha256", "a" * 64, "manifest_pin_mismatch"),
    ("expected_source_tree_sha256", "0" * 64, "source_tree_pin_invalid"),
    ("expected_source_tree_sha256", "a" * 64, "source_tree_pin_mismatch"),
])
def test_staging_consistency_requires_independent_pins(tmp_path, pin, bad, reason):
    observation, staging, pins, _archive_size = _staging_inputs(tmp_path)
    _refused(lambda: provenance.validate_source_staging_consistency(
        observation, staging, **{**pins, pin: bad}), reason)


def test_staging_wire_self_digest_and_canonical_encoding_are_required(tmp_path):
    observation, staging, pins, _archive_size = _staging_inputs(tmp_path)
    changed = dataclasses.replace(staging, canonical_json=staging.canonical_json + b" ")
    _refused(lambda: provenance.validate_source_staging_consistency(
        observation, changed, **{**pins, "expected_staging_sha256": staging.staging_sha256}),
        "staging_digest_mismatch")
    changed_raw = _canonical(staging.to_manifest()) + b" "
    changed = dataclasses.replace(staging, canonical_json=changed_raw,
                                  staging_sha256=hashlib.sha256(changed_raw).hexdigest())
    _refused(lambda: provenance.validate_source_staging_consistency(
        observation, changed, **{**pins, "expected_staging_sha256": changed.staging_sha256}),
        "staging_canonical_invalid")


def test_staging_json_bounds_support_realistic_entry_counts():
    entries = [{
        "path": (f"Python-3.13.12/{index:05d}" + "x" * (239 - len(f"Python-3.13.12/{index:05d}"))),
        "kind": "file",
        "implicit": False, "source_sha256": "a" * 64, "staged_sha256": "b" * 64,
        "archive_mode": 0o644, "device": 1, "inode": index + 1, "mode": 0o600,
        "nlink": 1, "size": 64, "mtime_ns": 1, "ctime_ns": 1,
    } for index in range(65_000)]
    raw = _canonical({"entries": entries})
    assert len(raw) > 32 * 1024 * 1024
    assert len(raw) < provenance.MAX_SOURCE_STAGING_MANIFEST_BYTES
    parsed = provenance._canonical_wire(raw, "staging")
    assert len(parsed["entries"]) == 65_000


def test_staging_wire_and_string_limits_are_independent(monkeypatch):
    raw = _canonical({"schema": "staging", "value": "abc"})
    monkeypatch.setattr(provenance, "MAX_SOURCE_STAGING_MANIFEST_BYTES", len(raw) - 1)
    _refused(lambda: provenance._canonical_wire(raw, "staging"), "staging_wire_invalid")

    monkeypatch.setattr(provenance, "MAX_SOURCE_STAGING_MANIFEST_BYTES", len(raw))
    monkeypatch.setattr(provenance, "MAX_SOURCE_STAGING_JSON_TEXT_BYTES", 2)
    _refused(lambda: provenance._canonical_wire(raw, "staging"), "staging_bounds_invalid")


def test_staging_path_budget_covers_implicit_ancestor_expansion(tmp_path):
    observation, staging, pins, _ = _staging_inputs(tmp_path)
    root = observation.root
    shared = root + "/" + "/".join(["s" + "x" * 15] * 50)
    fake_sha256 = "a" * 64
    added_files = []
    added_directories = set()
    for index in range(2_500):
        path = (shared + f"/b{index:04d}" + "/" + "/".join(
            ["d"] * 6 + ['"' * 16]))
        path += f"/f{index:04d}"
        added_files.append(StaticPythonSourceTreeFile(path, 0o644, 0, fake_sha256))
        parent = path.rpartition("/")[0]
        while parent:
            added_directories.add(parent)
            if parent == root:
                break
            parent = parent.rpartition("/")[0]

    all_files = tuple(sorted((*observation.files, *added_files), key=lambda item: item.path))
    tree_files = [{"path": item.path, "mode": item.mode, "size": item.size,
                   "sha256": item.sha256} for item in all_files]
    tree_raw = _canonical({
        "schema": SOURCE_TREE_SCHEMA, "archive": observation.archive,
        "root": root, "version": observation.version, "files": tree_files,
    })
    source_tree_sha256 = hashlib.sha256(tree_raw).hexdigest()
    observation_record = observation.to_manifest()
    observation_record.update(source_tree_sha256=source_tree_sha256, files=tree_files)
    observation_raw = _canonical(observation_record)
    observation = dataclasses.replace(
        observation, files=all_files, tree_json=tree_raw,
        source_tree_sha256=source_tree_sha256, canonical_json=observation_raw,
        observation_sha256=hashlib.sha256(observation_raw).hexdigest(),
    )

    manifest = staging.to_manifest()
    entries = manifest["entries"]
    known_paths = {item["path"] for item in entries}
    inode = 100_000
    for path in sorted(added_directories - known_paths):
        entries.append({
            "path": path, "kind": "directory", "implicit": True,
            "source_sha256": None, "staged_sha256": None, "archive_mode": None,
            "device": 1, "inode": inode, "mode": 0o700, "nlink": 1,
            "size": 0, "mtime_ns": 1, "ctime_ns": 1,
        })
        inode += 1
    for item in added_files:
        entries.append({
            "path": item.path, "kind": "file", "implicit": False,
            "source_sha256": fake_sha256, "staged_sha256": fake_sha256,
            "archive_mode": item.mode, "device": 1, "inode": inode,
            "mode": 0o600, "nlink": 1, "size": 0, "mtime_ns": 1,
            "ctime_ns": 1,
        })
        inode += 1
    entries.sort(key=lambda item: item["path"])
    staging_raw = _canonical(manifest)
    staging = dataclasses.replace(
        staging, canonical_json=staging_raw,
        staging_sha256=hashlib.sha256(staging_raw).hexdigest(),
    )
    pins["expected_staging_sha256"] = staging.staging_sha256
    pins["expected_source_tree_sha256"] = source_tree_sha256
    assert sum(len(item["path"].encode("utf-8")) for item in entries) > 16 * 1024 * 1024
    assert len(staging_raw) < provenance.MAX_SOURCE_STAGING_MANIFEST_BYTES
    assert provenance.validate_source_staging_consistency(
        observation, staging,
        expected_staging_sha256=pins["expected_staging_sha256"],
        expected_manifest_sha256=pins["expected_manifest_sha256"],
        expected_source_tree_sha256=pins["expected_source_tree_sha256"],
    ) is None


def test_source_observation_keeps_original_wire_limit(tmp_path, monkeypatch):
    observation, staging, pins, _ = _staging_inputs(tmp_path)
    monkeypatch.setattr(provenance, "MAX_EXTRACTION_MANIFEST_BYTES", len(observation.tree_json) - 1)
    _refused(lambda: provenance.validate_source_staging_consistency(
        observation, staging, **pins), "observation_wire_invalid")


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p.update(archive_sha256="c" * 64), "archive_observation_mismatch"),
    (lambda p: p.update(snapshot_sha256="c" * 64), "archive_observation_mismatch"),
    (lambda p: p.update(manifest_sha256="c" * 64), "manifest_pin_mismatch"),
    (lambda p: p.update(patch_set_sha256="c" * 64), "patch_set_mismatch"),
    (lambda p: p.update(extraction_performed=False), "staging_claim_invalid"),
    (lambda p: p.update(fixed_patches_staged=False), "staging_claim_invalid"),
    (lambda p: p.update(release_verified=True), "staging_claim_invalid"),
    (lambda p: p.update(source_execution_performed=True), "staging_claim_invalid"),
    (lambda p: p.update(build_performed=True), "staging_claim_invalid"),
    (lambda p: p.update(frozen_headers_generated=True), "staging_claim_invalid"),
    (lambda p: p.update(runtime_execution_performed=True), "staging_claim_invalid"),
    (lambda p: p.update(runtime_load_protection=True), "staging_claim_invalid"),
    (lambda p: p.update(production_admission=True), "staging_claim_invalid"),
    (lambda p: p.update(general_code_origin_protection=True), "staging_claim_invalid"),
])
def test_staging_archive_patch_and_claim_drift_refuse(tmp_path, mutation, reason):
    observation, staging, pins, _archive_size = _staging_inputs(tmp_path)
    changed = _repin_staging(staging, mutation=mutation)
    _refused(lambda: provenance.validate_source_staging_consistency(
        observation, changed, **{**pins, "expected_staging_sha256": changed.staging_sha256}), reason)


@pytest.mark.parametrize("field,value,reason", [
    ("version", "3.13.13", "version_root_mismatch"),
    ("archive_sha256", "c" * 64, "archive_observation_mismatch"),
    ("snapshot_sha256", "d" * 64, "observation_snapshot_archive_mismatch"),
    ("manifest_sha256", "c" * 64, "manifest_pin_mismatch"),
])
def test_observation_cross_record_drift_refuses(tmp_path, field, value, reason):
    observation, staging, pins, _archive_size = _staging_inputs(tmp_path)
    changed = _repin_observation(observation, **{field: value})
    if field in {"version", "archive_sha256"}:
        pins["expected_source_tree_sha256"] = changed.source_tree_sha256
    _refused(lambda: provenance.validate_source_staging_consistency(
        changed, staging, **pins), reason)


def _mutate_entry(payload, path, field, value):
    entry = next(item for item in payload["entries"] if item["path"] == path)
    entry[field] = value


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p["entries"].pop(next(i for i, e in enumerate(p["entries"])
                                     if e["kind"] == "file")), "staging_file_inventory_mismatch"),
    (lambda p: p["entries"].append(dict(p["entries"][0])), "staging_entry_order_invalid"),
    (lambda p: _mutate_entry(p, "Python-3.13.12/extra/unchanged.bin", "archive_mode", 0o600),
     "staging_source_file_mismatch"),
    (lambda p: _mutate_entry(p, "Python-3.13.12/extra/unchanged.bin", "source_sha256", "c" * 64),
     "staging_source_file_mismatch"),
    (lambda p: _mutate_entry(p, "Python-3.13.12/extra/unchanged.bin", "kind", []),
     "staging_entry_invalid"),
    (lambda p: _mutate_entry(p, "Python-3.13.12/extra/unchanged.bin", "kind", {}),
     "staging_entry_invalid"),
    (lambda p: _mutate_entry(p, "Python-3.13.12/extra/unchanged.bin", "staged_sha256", "c" * 64),
     "staging_postimage_mismatch"),
    (lambda p: _mutate_entry(p, "Python-3.13.12/extra/unchanged.bin", "size", 1),
     "staging_postimage_mismatch"),
    (lambda p: _mutate_entry(p, "Python-3.13.12/extra/unchanged.bin", "mode", True),
     "staging_stat_invalid"),
    (lambda p: _mutate_entry(p, "Python-3.13.12/extra/unchanged.bin", "nlink", 2),
     "staging_stat_invalid"),
    (lambda p: _mutate_entry(p, "Python-3.13.12/extra/unchanged.bin", "implicit", True),
     "staging_file_invalid"),
    (lambda p: _mutate_entry(p, "Python-3.13.12/extra/unchanged.bin", "archive_mode", True),
     "staging_archive_mode_invalid"),
    (lambda p: _mutate_entry(p, "Python-3.13.12/extra/unchanged.bin", "path", "../escape"),
     "staging_path_invalid"),
])
def test_staging_file_inventory_source_and_stat_mutations_refuse(tmp_path, mutation, reason):
    observation, staging, pins, _archive_size = _staging_inputs(tmp_path)
    changed = _repin_staging(staging, mutation=mutation)
    _refused(lambda: provenance.validate_source_staging_consistency(
        observation, changed, **{**pins, "expected_staging_sha256": changed.staging_sha256}), reason)


def test_missing_or_unexpected_regular_file_refuses(tmp_path):
    observation, staging, pins, _archive_size = _staging_inputs(tmp_path)
    changed = _repin_staging(
        staging, mutation=lambda payload: payload["entries"].remove(next(
            item for item in payload["entries"] if item["path"].endswith("/extra/empty"))),
    )
    _refused(lambda: provenance.validate_source_staging_consistency(
        observation, changed, **{**pins, "expected_staging_sha256": changed.staging_sha256}),
        "staging_file_inventory_mismatch")


def test_non_ancestor_implicit_directory_and_bad_directory_stat_refuse(tmp_path):
    observation, staging, pins, _archive_size = _staging_inputs(tmp_path)

    def add_non_ancestor(payload):
        item = dict(payload["entries"][0])
        item.update(path="Python-3.13.12/unrelated", implicit=True, archive_mode=None)
        payload["entries"].append(item)
        payload["entries"].sort(key=lambda entry: entry["path"])

    changed = _repin_staging(staging, mutation=add_non_ancestor)
    _refused(lambda: provenance.validate_source_staging_consistency(
        observation, changed, **{**pins, "expected_staging_sha256": changed.staging_sha256}),
        "staging_implicit_directory_invalid")

    def bad_directory(payload):
        entry = next(item for item in payload["entries"] if item["kind"] == "directory")
        entry["mode"] = 0o755

    changed = _repin_staging(staging, mutation=bad_directory)
    _refused(lambda: provenance.validate_source_staging_consistency(
        observation, changed, **{**pins, "expected_staging_sha256": changed.staging_sha256}),
        "staging_stat_invalid")


@pytest.mark.parametrize("mutation,reason", [
    (lambda payload: payload["tree_identity"].update(raw_mode=0o41700),
     "staging_tree_identity_invalid"),
    (lambda payload: payload["tree_identity"].update(raw_mode=0o40701),
     "staging_tree_identity_invalid"),
    (lambda payload: payload["ancestor_identities"].pop(),
     "staging_ancestor_identity_invalid"),
    (lambda payload: payload["ancestor_identities"].append(
        dict(payload["ancestor_identities"][-1])), "staging_ancestor_identity_invalid"),
])
def test_staging_tree_identity_and_ancestor_chain_are_exact(tmp_path, mutation, reason):
    observation, staging, pins, _archive_size = _staging_inputs(tmp_path)
    changed = _repin_staging(staging, mutation=mutation)
    _refused(lambda: provenance.validate_source_staging_consistency(
        observation, changed, **{**pins, "expected_staging_sha256": changed.staging_sha256}),
        reason)


def test_valid_explicit_empty_directory_remains_allowed(tmp_path):
    observation, staging, pins, _archive_size = _staging_inputs(tmp_path)
    assert any(item["path"].endswith("/explicit-empty") and item["kind"] == "directory"
               and item["implicit"] is False for item in staging.to_manifest()["entries"])
    assert provenance.validate_source_staging_consistency(observation, staging, **pins) is None


def test_source_tree_staging_consistency_has_no_external_effects(tmp_path, monkeypatch):
    observation, staging, pins, _archive_size = _staging_inputs(tmp_path)

    def forbidden(*_args, **_kwargs):
        pytest.fail("detached consistency check must not perform external effects")

    import builtins
    with monkeypatch.context() as patch:
        for owner, name in ((builtins, "open"), (os, "open"), (os, "stat"), (os, "listdir"),
                            (socket, "socket"), (subprocess, "run"),
                            (subprocess, "Popen")):
            patch.setattr(owner, name, forbidden)
        result = provenance.validate_source_staging_consistency(observation, staging, **pins)
    assert result is None
