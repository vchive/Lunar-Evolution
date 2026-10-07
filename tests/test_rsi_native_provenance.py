"""Canonical same-attempt native provenance and immutable file recovery fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from copy import deepcopy

import pytest
from test_rsi_native_gateway import bundle, digest, make_request, plan_factory

import lunar_evolution.rsi_native_provenance as provenance
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_provenance import (
    NATIVE_RSI_PROVENANCE_NAME,
    NativeRSIProvenanceError,
    persist_native_rsi_provenance,
    read_native_rsi_provenance,
)


def payload():
    request = make_request()
    plan = plan_factory(request, EMPTY_MEMORY_SNAPSHOT)
    receipts = bundle(request, plan)
    return {"schema_version": "1", "protocol": "lunar-native-rsi-provenance-v1", "plan": plan.to_dict(),
            "input_binding_sha256": digest("input"), "retained_evidence_sha256": digest("retained"),
            "publication_journal_sha256": digest("journal"), "producer_execution_receipt_sha256": digest("producer"),
            "bundle": {name: getattr(receipts, name).to_dict() for name in ("candidate", "execution", "evaluation", "publication")}}


def write_record(batch, value, *, raw=None):
    path = batch / NATIVE_RSI_PROVENANCE_NAME
    path.chmod(0o600)
    if raw is None:
        content = {key: item for key, item in value.items() if key != "provenance_sha256"}
        value["provenance_sha256"] = hashlib.sha256(canonical_json(content, maximum=1024 * 1024)).hexdigest()
        raw = canonical_json(value, maximum=1024 * 1024)
    path.write_bytes(raw)
    path.chmod(0o400)


def test_create_read_and_identical_payload_replay_are_immutable(tmp_path):
    original = payload()
    before = deepcopy(original)
    receipt = persist_native_rsi_provenance(tmp_path, original)
    path = tmp_path / NATIVE_RSI_PROVENANCE_NAME
    info = path.stat()
    raw = path.read_bytes()
    value = read_native_rsi_provenance(tmp_path)
    assert original == before
    assert value["file_identity"] == {"device": info.st_dev, "inode": info.st_ino}
    assert value["provenance_sha256"] == receipt
    assert stat.S_IMODE(info.st_mode) == 0o400 and info.st_nlink == 1
    assert raw == canonical_json(value, maximum=1024 * 1024)
    assert persist_native_rsi_provenance(tmp_path, original) == receipt
    assert path.read_bytes() == raw and path.stat() == info
    value["bundle"]["candidate"]["candidate_id"] = "caller-mutation"
    assert read_native_rsi_provenance(tmp_path)["bundle"]["candidate"]["candidate_id"] == "candidate"


@pytest.mark.parametrize("mutation", ["unknown", "schema", "protocol", "input_digest", "plan", "bundle_key", "receipt_key", "request", "candidate"])
def test_invalid_payload_rejected_before_file_creation(tmp_path, mutation):
    value = payload()
    if mutation == "unknown":
        value["memory_authority"] = "active"
    elif mutation == "schema":
        value["schema_version"] = 1
    elif mutation == "protocol":
        value["protocol"] = "other"
    elif mutation == "input_digest":
        value["input_binding_sha256"] = "bad"
    elif mutation == "plan":
        value["plan"]["plan_sha256"] = digest("drift")
    elif mutation == "bundle_key":
        value["bundle"]["extra"] = {}
    elif mutation == "receipt_key":
        value["bundle"]["execution"]["extra"] = True
    elif mutation == "request":
        value["bundle"]["evaluation"]["request_sha256"] = digest("other")
    else:
        value["bundle"]["publication"]["candidate_id"] = "other"
    with pytest.raises(NativeRSIProvenanceError):
        persist_native_rsi_provenance(tmp_path, value)
    assert not (tmp_path / NATIVE_RSI_PROVENANCE_NAME).exists()


def test_conflicting_existing_valid_payload_is_never_overwritten(tmp_path):
    original = payload()
    persist_native_rsi_provenance(tmp_path, original)
    path = tmp_path / NATIVE_RSI_PROVENANCE_NAME
    before = provenance._metadata(path.stat()), path.read_bytes()
    changed = deepcopy(original)
    changed["retained_evidence_sha256"] = digest("different-retained")
    with pytest.raises(NativeRSIProvenanceError, match="conflict"):
        persist_native_rsi_provenance(tmp_path, changed)
    assert (provenance._metadata(path.stat()), path.read_bytes()) == before


@pytest.mark.parametrize("kind", ["missing-directory", "missing-file", "symlink-directory", "symlink-file", "hardlink", "mode"])
def test_read_is_no_follow_no_create_and_rejects_unsafe_paths(tmp_path, kind):
    path = tmp_path / NATIVE_RSI_PROVENANCE_NAME
    directory = tmp_path
    if kind == "missing-directory":
        directory = tmp_path / "absent" / "nested"
    elif kind == "symlink-directory":
        directory = tmp_path / "linked"
        directory.symlink_to(tmp_path, target_is_directory=True)
    elif kind != "missing-file":
        persist_native_rsi_provenance(tmp_path, payload())
        if kind == "symlink-file":
            retained = tmp_path / "retained"
            path.rename(retained)
            path.symlink_to(retained)
        elif kind == "hardlink":
            os.link(path, tmp_path / "alias")
        else:
            path.chmod(0o600)
    before = sorted(item.name for item in tmp_path.iterdir())
    with pytest.raises(NativeRSIProvenanceError):
        read_native_rsi_provenance(directory)
    assert sorted(item.name for item in tmp_path.iterdir()) == before
    assert not (tmp_path / "absent").exists()


def test_creation_never_initializes_missing_directory_or_follows_symlink(tmp_path):
    missing = tmp_path / "absent"
    with pytest.raises(NativeRSIProvenanceError, match="path_invalid"):
        persist_native_rsi_provenance(missing, payload())
    assert not missing.exists()
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(NativeRSIProvenanceError, match="path_invalid"):
        persist_native_rsi_provenance(linked, payload())
    assert not (tmp_path / NATIVE_RSI_PROVENANCE_NAME).exists()


@pytest.mark.parametrize("mutation", ["unknown", "digest", "file_identity", "dto", "duplicate", "noncanonical", "oversize"])
def test_existing_corrupt_records_are_read_only_and_cannot_be_repaired(tmp_path, mutation):
    original = payload()
    persist_native_rsi_provenance(tmp_path, original)
    value = read_native_rsi_provenance(tmp_path)
    path = tmp_path / NATIVE_RSI_PROVENANCE_NAME
    if mutation == "unknown":
        value["extra"] = True
        write_record(tmp_path, value)
    elif mutation == "digest":
        value["provenance_sha256"] = digest("wrong")
        write_record(tmp_path, value, raw=canonical_json(value, maximum=1024 * 1024))
    elif mutation == "file_identity":
        value["file_identity"]["inode"] += 1
        write_record(tmp_path, value)
    elif mutation == "dto":
        value["bundle"]["execution"]["memory_snapshot_sha256"] = digest("other")
        write_record(tmp_path, value)
    elif mutation == "duplicate":
        raw = path.read_bytes().replace(b'"schema_version":"1"', b'"schema_version":"1","schema_version":"1"', 1)
        write_record(tmp_path, value, raw=raw)
    elif mutation == "noncanonical":
        write_record(tmp_path, value, raw=json.dumps(value, indent=2).encode())
    else:
        write_record(tmp_path, value, raw=b"x" * (provenance.MAX_NATIVE_RSI_PROVENANCE_BYTES + 1))
    before = provenance._metadata(path.stat()), path.read_bytes()
    with pytest.raises(NativeRSIProvenanceError):
        read_native_rsi_provenance(tmp_path)
    with pytest.raises(NativeRSIProvenanceError):
        persist_native_rsi_provenance(tmp_path, original)
    assert (provenance._metadata(path.stat()), path.read_bytes()) == before


def test_identical_bytes_copied_to_new_inode_are_rejected(tmp_path):
    persist_native_rsi_provenance(tmp_path, payload())
    path = tmp_path / NATIVE_RSI_PROVENANCE_NAME
    replacement = tmp_path / "replacement"
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o400)
    replacement.replace(path)
    with pytest.raises(NativeRSIProvenanceError, match="changed"):
        read_native_rsi_provenance(tmp_path)


def test_read_twice_detects_replacement_after_first_verified_read(tmp_path, monkeypatch):
    persist_native_rsi_provenance(tmp_path, payload())
    read_once = provenance._read_once
    calls = 0

    def replace_after_read(chain):
        nonlocal calls
        result = read_once(chain)
        calls += 1
        if calls == 1:
            path = tmp_path / NATIVE_RSI_PROVENANCE_NAME
            changed = tmp_path / "replacement"
            changed.write_bytes(path.read_bytes())
            changed.chmod(0o400)
            changed.replace(path)
        return result

    monkeypatch.setattr(provenance, "_read_once", replace_after_read)
    with pytest.raises(NativeRSIProvenanceError, match="changed"):
        read_native_rsi_provenance(tmp_path)


def test_partial_write_is_retained_and_never_recreated(tmp_path, monkeypatch):
    write = os.write
    calls = 0

    def partial(descriptor, content):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("fixture interrupted write")
        return write(descriptor, content[:25])

    monkeypatch.setattr(provenance.os, "write", partial)
    with pytest.raises(NativeRSIProvenanceError, match="write_failed"):
        persist_native_rsi_provenance(tmp_path, payload())
    path = tmp_path / NATIVE_RSI_PROVENANCE_NAME
    assert path.exists() and path.stat().st_size == 25 and stat.S_IMODE(path.stat().st_mode) == 0o400
    before = provenance._metadata(path.stat()), path.read_bytes()
    monkeypatch.setattr(provenance.os, "write", write)
    with pytest.raises(NativeRSIProvenanceError, match="invalid"):
        persist_native_rsi_provenance(tmp_path, payload())
    assert (provenance._metadata(path.stat()), path.read_bytes()) == before


def test_provenance_retains_known_failure_without_granting_memory_authority(tmp_path):
    value = payload()
    value["bundle"]["evaluation"]["outcome"] = "fail"
    receipt = persist_native_rsi_provenance(tmp_path, value)
    retained = read_native_rsi_provenance(tmp_path)
    assert retained["provenance_sha256"] == receipt
    assert retained["bundle"]["evaluation"]["outcome"] == "fail"
    assert not set(retained) & {"approved", "active", "memory_admission", "verifier_decision"}


def test_in_place_content_mutation_during_read_is_detected(tmp_path, monkeypatch):
    persist_native_rsi_provenance(tmp_path, payload())
    read = os.read
    changed = False

    def mutate(descriptor, count):
        nonlocal changed
        content = read(descriptor, count)
        if content and not changed:
            changed = True
            path = tmp_path / NATIVE_RSI_PROVENANCE_NAME
            value = json.loads(path.read_bytes())
            value["retained_evidence_sha256"] = digest("mutation")
            write_record(tmp_path, value)
        return content

    monkeypatch.setattr(provenance.os, "read", mutate)
    with pytest.raises(NativeRSIProvenanceError, match="changed"):
        read_native_rsi_provenance(tmp_path)


def test_directory_replacement_after_first_read_is_detected(tmp_path, monkeypatch):
    batch = tmp_path / "batch"
    batch.mkdir()
    persist_native_rsi_provenance(batch, payload())
    read_once = provenance._read_once
    calls = 0

    def replace_batch(chain):
        nonlocal calls
        result = read_once(chain)
        calls += 1
        if calls == 1:
            batch.rename(tmp_path / "retained-batch")
            batch.mkdir()
        return result

    monkeypatch.setattr(provenance, "_read_once", replace_batch)
    with pytest.raises(NativeRSIProvenanceError):
        read_native_rsi_provenance(batch)
    assert not list(batch.iterdir())


def test_file_is_flushed_before_directory_and_replay_never_flushes(tmp_path, monkeypatch):
    sync = os.fsync
    flushed = []

    def observe(descriptor):
        flushed.append("directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file")
        return sync(descriptor)

    monkeypatch.setattr(provenance.os, "fsync", observe)
    receipt = persist_native_rsi_provenance(tmp_path, payload())
    assert flushed == ["file", "directory"]
    read_native_rsi_provenance(tmp_path)
    assert persist_native_rsi_provenance(tmp_path, payload()) == receipt
    assert flushed == ["file", "directory"]


def test_sidecar_fields_cannot_be_supplied_as_caller_payload(tmp_path):
    value = payload()
    value["file_identity"] = {"device": 0, "inode": 1}
    value["provenance_sha256"] = digest("caller")
    with pytest.raises(NativeRSIProvenanceError, match="invalid"):
        persist_native_rsi_provenance(tmp_path, value)
    assert not (tmp_path / NATIVE_RSI_PROVENANCE_NAME).exists()


def test_non_json_tuple_cannot_silently_normalize_to_canonical_payload(tmp_path):
    value = payload()
    value["plan"]["request"]["solver_settings"] = {"tuple": (1, 2)}
    with pytest.raises(NativeRSIProvenanceError, match="invalid"):
        persist_native_rsi_provenance(tmp_path, value)
    assert not (tmp_path / NATIVE_RSI_PROVENANCE_NAME).exists()
