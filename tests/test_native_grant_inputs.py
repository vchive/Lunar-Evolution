"""Pure original proposal extraction: inert bytes, no filesystem or native launch."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution import producer_launch_inputs as config_inputs
from lunar_evolution import rsi_native_inputs as rsi_inputs
from lunar_evolution.native_grant_inputs import NativeGrantInputError, original_native_grant_inputs
from lunar_evolution.producer_grant_anchors import ProducerGrantIdentity
from lunar_evolution.rsi_learning import MAX_RSI_RECORD_BYTES, canonical_json


def _fixture(kind):
    workspace = Path("/inert/workspace")
    batch = workspace / "evolution" / "producer-batches" / "inert"
    contents = (b'{"fixture":"config"}\n',) if kind == "config" else (
        b'{"fixture":"request"}\n', b'{"fixture":"memory"}\n',
    )
    names = ("config.json",) if kind == "config" else ("request.json", "memory.json")
    value = {
        "schema_version": "1", "protocol": config_inputs._INPUT_PROTOCOL if kind == "config" else rsi_inputs._INPUT_PROTOCOL,
        "journal_id": "inert", "workspace_identity": {"device": 1, "inode": 100},
        "batch_identity": {"device": 1, "inode": 200}, "inputs_identity": {"device": 1, "inode": 300},
        "manifest_file_identity": {"device": 1, "inode": 900},
        "files": [{"name": name, "device": 1, "inode": 400 + index, "size": len(content),
                   "mtime_ns": 1_700_000_000_000_000_000, "ctime_ns": 1_700_000_000_000_000_001,
                   "sha256": hashlib.sha256(content).hexdigest()}
                  for index, (name, content) in enumerate(zip(names, contents))],
    }
    if kind == "config":
        value.update({"config_sha256": hashlib.sha256(contents[0]).hexdigest(), "contract_sha256": "a" * 64})
    else:
        value.update({"request_sha256": hashlib.sha256(contents[0]).hexdigest(),
                      "memory_snapshot_sha256": hashlib.sha256(contents[1]).hexdigest(), "episode_id": "inert-episode"})
    digest = hashlib.sha256(canonical_json(value)).hexdigest()
    value["manifest_sha256"] = digest
    manifest = canonical_json(value)
    if kind == "config":
        return config_inputs.ProducerLaunchInputDescriptor(
            workspace, "inert", batch / ".producer-input", value["config_sha256"], value["contract_sha256"],
            digest, contents[0], manifest,
        )
    return rsi_inputs.NativeRSIInputDescriptor(
        workspace, "inert", batch / ".rsi-input", value["request_sha256"], value["memory_snapshot_sha256"],
        digest, contents[0], contents[1], manifest, None,
    )


def _rehash(inputs, value):
    value = dict(value)
    value.pop("manifest_sha256", None)
    digest = hashlib.sha256(canonical_json(value)).hexdigest()
    value["manifest_sha256"] = digest
    return replace(inputs, manifest_json=canonical_json(value), manifest_sha256=digest)


def _forbid_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("pure extraction refreshed a filesystem pin")

    for name in ("stat", "lstat", "fstat", "open", "mkdir"):
        monkeypatch.setattr(os, name, forbidden)


@pytest.mark.parametrize("kind", ["config", "rsi"])
def test_original_file_and_parent_pins_and_bytes_are_extracted_without_io(monkeypatch, kind):
    inputs = _fixture(kind)
    original = json.loads(inputs.manifest_json)
    _forbid_io(monkeypatch)
    proposals = original_native_grant_inputs(inputs)
    assert len(proposals.requests) == len(proposals.materials) == len(original["files"])
    assert len(proposals.expected_bindings) == 3
    for request, material, expected in zip(proposals.requests, proposals.materials, original["files"]):
        assert request.role == "protected-file"
        assert request.path == material.path == str(inputs.inputs_path / expected["name"])
        assert request.expected_identity == material.identity == ProducerGrantIdentity(1, expected["inode"], "file")
        assert hashlib.sha256(material.content).hexdigest() == expected["sha256"]
        assert (material.mtime_ns, material.ctime_ns) == (expected["mtime_ns"], expected["ctime_ns"])
        request.validate()
        material.validate()
    assert tuple(binding.path for binding in proposals.expected_bindings) == (
        str(inputs.workspace), str(inputs.inputs_path.parent), str(inputs.inputs_path),
    )
    assert [binding.identity.inode for binding in proposals.expected_bindings] == [100, 200, 300]
    for binding in proposals.expected_bindings:
        binding.validate()
    assert not {binding.path for binding in proposals.expected_bindings} & {request.path for request in proposals.requests}
    assert all(not hasattr(proposals, attribute) for attribute in ("pass_fds", "owner", "execution_receipt"))


def test_none_is_an_empty_proposal_without_filesystem_or_authority(monkeypatch):
    _forbid_io(monkeypatch)
    result = original_native_grant_inputs(None)
    assert result.requests == result.expected_bindings == result.materials == ()


@pytest.mark.parametrize("value", [{}, (), b"manifest", object()])
def test_unrecognized_input_dto_types_refuse_without_io(monkeypatch, value):
    _forbid_io(monkeypatch)
    with pytest.raises(NativeGrantInputError):
        original_native_grant_inputs(value)


@pytest.mark.parametrize("kind", ["config", "rsi"])
@pytest.mark.parametrize("mutation", ["noncanonical", "schema", "protocol", "missing", "extra", "selfdigest", "descriptor-digest", "files-list", "wrong-name", "extra-file", "metadata-shape", "file-sha", "size"])
def test_canonical_manifest_and_original_metadata_refusals(monkeypatch, kind, mutation):
    inputs = _fixture(kind)
    value = json.loads(inputs.manifest_json)
    if mutation == "noncanonical":
        inputs = replace(inputs, manifest_json=b" " + inputs.manifest_json)
    elif mutation == "descriptor-digest":
        inputs = replace(inputs, manifest_sha256="0" * 64)
    elif mutation == "selfdigest":
        value["manifest_sha256"] = "0" * 64
        inputs = replace(inputs, manifest_json=canonical_json(value), manifest_sha256="0" * 64)
    else:
        if mutation == "schema":
            value["schema_version"] = 1
        elif mutation == "protocol":
            value["protocol"] = "unrecognized"
        elif mutation == "missing":
            value.pop("workspace_identity")
        elif mutation == "extra":
            value["authorization"] = "forged"
        elif mutation == "files-list":
            value["files"] = {}
        elif mutation == "wrong-name":
            value["files"][0]["name"] = "manifest.json"
        elif mutation == "extra-file":
            value["files"].append(dict(value["files"][0]))
        elif mutation == "metadata-shape":
            value["files"][0]["mode"] = 0o400
        elif mutation == "file-sha":
            value["files"][0]["sha256"] = "0" * 64
        else:
            value["files"][0]["size"] += 1
        inputs = _rehash(inputs, value)
    _forbid_io(monkeypatch)
    with pytest.raises(NativeGrantInputError):
        original_native_grant_inputs(inputs)


@pytest.mark.parametrize("kind", ["config", "rsi"])
@pytest.mark.parametrize("key,value", [("device", True), ("device", -1), ("device", 1 << 64),
                                      ("inode", False), ("inode", 0), ("inode", 1 << 64),
                                      ("size", True), ("mtime_ns", True), ("ctime_ns", "123")])
def test_file_metadata_exact_types_and_identity_ranges_refuse(monkeypatch, kind, key, value):
    inputs = _fixture(kind)
    manifest = json.loads(inputs.manifest_json)
    manifest["files"][0][key] = value
    inputs = _rehash(inputs, manifest)
    _forbid_io(monkeypatch)
    with pytest.raises(NativeGrantInputError):
        original_native_grant_inputs(inputs)


@pytest.mark.parametrize("key", ["workspace_identity", "batch_identity", "inputs_identity"])
@pytest.mark.parametrize("mutation", ["shape", "device-type", "inode-zero"])
def test_non_grant_parent_expectations_have_strict_original_shape(monkeypatch, key, mutation):
    inputs = _fixture("config")
    value = json.loads(inputs.manifest_json)
    if mutation == "shape":
        value[key]["role"] = "readonly-directory"
    elif mutation == "device-type":
        value[key]["device"] = True
    else:
        value[key]["inode"] = 0
    inputs = _rehash(inputs, value)
    _forbid_io(monkeypatch)
    with pytest.raises(NativeGrantInputError):
        original_native_grant_inputs(inputs)


@pytest.mark.parametrize("kind", ["config", "rsi"])
def test_original_module_specific_content_limit_is_preserved(monkeypatch, kind):
    inputs = _fixture(kind)
    limit = config_inputs.MAX_PRODUCER_LAUNCH_INPUT_BYTES if kind == "config" else MAX_RSI_RECORD_BYTES
    content = b"x" * (limit + 1)
    field = "config_json" if kind == "config" else "request_json"
    inputs = replace(inputs, **{field: content})
    value = json.loads(inputs.manifest_json)
    value["files"][0].update({"size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    inputs = _rehash(inputs, value)
    _forbid_io(monkeypatch)
    with pytest.raises(NativeGrantInputError):
        original_native_grant_inputs(inputs)


@pytest.mark.parametrize("kind", ["config", "rsi"])
def test_material_timestamp_bounds_are_checked_by_pure_helper(monkeypatch, kind):
    inputs = _fixture(kind)
    value = json.loads(inputs.manifest_json)
    value["files"][0]["mtime_ns"] = 1 << 63
    inputs = _rehash(inputs, value)
    _forbid_io(monkeypatch)
    with pytest.raises(NativeGrantInputError):
        original_native_grant_inputs(inputs)


@pytest.mark.parametrize("kind", ["config", "rsi"])
def test_pure_proposals_reject_noncanonical_descriptor_paths(monkeypatch, kind):
    inputs = replace(_fixture(kind), inputs_path=Path("relative"))
    _forbid_io(monkeypatch)
    with pytest.raises(NativeGrantInputError):
        original_native_grant_inputs(inputs)
