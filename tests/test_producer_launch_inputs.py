"""Canonical producer configuration is bound before attestation consumption."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from test_openevolve_handoff import _contract
from test_rsi_native_inputs import _inventory, _new_intent, _replace_same_bytes_and_mode

from lunar_evolution import producer_launch_inputs as inputs
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native platform")
HEX = "a" * 64


def _config():
    return {
        "schema_version": "1", "contract": _contract().to_dict(),
        "result_path": "../output/result.json",
        "producer": {"id": "openevolve", "fingerprint": "declaration-only"},
        "budget": {"max_rounds": 2},
    }


@pytest.fixture(scope="module")
def native_artifact(tmp_path_factory):
    return build_native_bootstrap_artifact(tmp_path_factory.mktemp("native-producer-input-bootstrap"))


def _prepared(tmp_path, native_artifact, *, stage=True, argv=None, **intent_changes):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _config()
    descriptor = (inputs.prepare_producer_launch_inputs(
        workspace, journal_id="producer-journal", config=config,
    ) if stage else None)
    producer = tmp_path / "producer"
    producer.mkdir()
    (producer / "target").write_bytes(b"inert local native fixture\n")
    (producer / "target").chmod(0o700)
    kwargs = {
        "producer_root": producer, "launch_id": "producer-launch", "journal_id": "producer-journal",
        "run_id": "producer-run", "parent_task_id": "producer-parent", "task_id": "producer-task",
        "contract_sha256": _contract().digest(), "evaluator_kind": "local", "evaluator_fingerprint": HEX,
        "runner_fingerprint": HEX, "generator_fingerprint": HEX, "dependency_sha256": HEX,
        "environment_sha256": HEX, "producer_id": "local-fixture", "producer_fingerprint": HEX,
        "executable_relative": "target", "argv": argv or (
            ("target", *descriptor.argv_fragment) if descriptor else ("target",)
        ), "working_directory": "work", "output_directory": "output",
        "request_timeout_seconds": 1, "max_requests": 1, "output_max_bytes": 4096,
        "wall_timeout_seconds": 8,
    }
    intent = build_producer_launch_intent(**(kwargs | intent_changes))
    attestation = build_producer_launch_attestation(intent, "producer-input-once")
    batch = workspace / "evolution" / "producer-batches" / intent.journal_id
    return SimpleNamespace(workspace=workspace, producer=producer, config=config, descriptor=descriptor,
                           intent=intent, attestation=attestation, artifact=native_artifact, batch=batch)


def _bind(prepared, **changes):
    return inputs.bind_producer_launch_inputs(prepared.workspace, **({
        "intent": prepared.intent, "attestation": prepared.attestation,
        "artifact": prepared.artifact, "inputs": prepared.descriptor,
    } | changes))


def _validate(prepared, **changes):
    return inputs.validate_producer_launch_inputs(prepared.workspace, **({
        "intent": prepared.intent, "attestation": prepared.attestation,
        "artifact": prepared.artifact,
    } | changes))


def _forbid_mutations(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("input validation wrote, locked, staged or dispatched")

    for name in ("_write_file", "_recovery_lock", "prepare_producer_launch_inputs", "bind_producer_launch_inputs"):
        monkeypatch.setattr(inputs, name, forbidden)
    for name in ("write", "kill", "killpg"):
        monkeypatch.setattr(inputs.os, name, forbidden)


def test_preparation_freezes_full_config_and_exposes_only_exact_config_path(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    descriptor = prepared.descriptor
    content = canonical_json(prepared.config)
    assert descriptor.config_json == content
    assert descriptor.config_sha256 == hashlib.sha256(content).hexdigest()
    assert descriptor.contract_sha256 == _contract().digest()
    assert descriptor.config_path.read_bytes() == content
    assert descriptor.readonly_files == descriptor.read_paths == (descriptor.config_path,)
    assert descriptor.argv_fragment == (inputs.PRODUCER_LAUNCH_INPUT_MARKER, descriptor.manifest_sha256)
    assert descriptor.deadline_unix is None
    assert descriptor.launch_binding_sha256 is None
    assert stat.S_IMODE(descriptor.inputs_path.stat().st_mode) == 0o500
    for path in descriptor.inputs_path.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
    with pytest.raises((FrozenInstanceError, AttributeError)):
        descriptor.config_sha256 = HEX
    detached = descriptor.config
    detached["budget"]["max_rounds"] = 99
    prepared.config["budget"]["max_rounds"] = 100
    assert descriptor.config["budget"]["max_rounds"] == 2
    assert not hasattr(descriptor, "result")


def test_bound_config_replay_is_read_only_and_leaves_consumption_unclaimed(tmp_path, native_artifact, monkeypatch):
    prepared = _prepared(tmp_path, native_artifact)
    descriptor = _bind(prepared)
    before = _inventory(prepared.workspace)
    _forbid_mutations(monkeypatch)
    for _ in range(3):
        assert _validate(prepared) == descriptor
        assert _validate(prepared, require_unexpired=True) == descriptor
    assert _inventory(prepared.workspace) == before
    assert not (prepared.batch / "attestation-consumption.json").exists()
    assert not (prepared.batch / "process-registration.json").exists()
    assert not (prepared.batch / "execution-receipt.json").exists()


def test_legacy_marker_absence_returns_none_without_creating_batch(tmp_path, native_artifact, monkeypatch):
    prepared = _prepared(tmp_path, native_artifact, stage=False)
    before = _inventory(prepared.workspace)
    _forbid_mutations(monkeypatch)
    assert _validate(prepared) is None
    assert _inventory(prepared.workspace) == before
    assert not prepared.batch.exists()


@pytest.mark.parametrize("operation", ["prepare", "bind"])
def test_repeated_creation_does_not_replace_original_bytes_or_inodes(tmp_path, native_artifact, operation):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.ProducerLaunchInputError):
        if operation == "prepare":
            inputs.prepare_producer_launch_inputs(prepared.workspace, journal_id=prepared.intent.journal_id,
                                                 config=prepared.config)
        else:
            _bind(prepared)
    assert _inventory(prepared.workspace) == before


@pytest.mark.parametrize("config", [None, [], {}, {"contract": {}}, {"contract": "declared"}])
def test_invalid_contract_cannot_stage_any_files(tmp_path, config):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    before = _inventory(workspace)
    with pytest.raises(inputs.ProducerLaunchInputError):
        inputs.prepare_producer_launch_inputs(workspace, journal_id="journal", config=config)
    assert _inventory(workspace) == before


@pytest.mark.parametrize("change", ["nonfinite", "oversized", "unknown-contract"])
def test_noncanonical_or_oversized_config_is_refused_before_creation(tmp_path, change):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _config()
    if change == "nonfinite":
        config["quality"] = float("nan")
    elif change == "oversized":
        config["data"] = "x" * inputs.MAX_PRODUCER_LAUNCH_INPUT_BYTES
    else:
        config["contract"]["caller_authority"] = "trusted"
    before = _inventory(workspace)
    with pytest.raises(inputs.ProducerLaunchInputError):
        inputs.prepare_producer_launch_inputs(workspace, journal_id="journal", config=config)
    assert _inventory(workspace) == before


@pytest.mark.parametrize("entry", ["attestation-consumption.json", "process-registration.json", "work/nonempty"])
def test_started_attempt_cannot_be_bound_or_repaired(tmp_path, native_artifact, entry):
    prepared = _prepared(tmp_path, native_artifact)
    path = prepared.batch / entry
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"retained attempt evidence")
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.ProducerLaunchInputError):
        _bind(prepared)
    assert _inventory(prepared.workspace) == before
    assert not (prepared.batch / "native-producer-launch.json").exists()


@pytest.mark.parametrize("field", ["contract_sha256", "task_id", "parent_task_id", "run_id"])
def test_launch_identity_drift_never_rebinds_original_config(tmp_path, native_artifact, field):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    value = "b" * 64 if field == "contract_sha256" else "another-task"
    intent = _new_intent(prepared.intent, **{field: value})
    attestation = build_producer_launch_attestation(intent, "different-once")
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.ProducerLaunchInputError):
        _validate(prepared, intent=intent, attestation=attestation)
    assert _inventory(prepared.workspace) == before


def test_contract_pin_is_required_before_binding_creation(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact, contract_sha256="b" * 64)
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.ProducerLaunchInputError) as refused:
        _bind(prepared)
    assert refused.value.code == "producer_launch_inputs_contract_pin_mismatch"
    assert _inventory(prepared.workspace) == before


@pytest.mark.parametrize("kind", ["missing", "duplicate", "position", "invalid-sha", "rsi"])
def test_staged_config_cannot_downgrade_or_accept_ambiguous_markers(tmp_path, native_artifact, kind):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    marker, digest = prepared.descriptor.argv_fragment
    argv = {
        "missing": ("target",), "duplicate": ("target", marker, digest, marker, digest),
        "position": ("target", marker, digest, "after-marker"),
        "invalid-sha": ("target", marker, "invalid"),
        "rsi": ("target", "--lunar-rsi-input-v1", HEX, marker, digest),
    }[kind]
    intent = _new_intent(prepared.intent, argv=argv)
    attestation = build_producer_launch_attestation(intent, "changed-marker")
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.ProducerLaunchInputError):
        _validate(prepared, intent=intent, attestation=attestation)
    assert _inventory(prepared.workspace) == before


@pytest.mark.parametrize("material", ["config", "manifest", "binding"])
@pytest.mark.parametrize("drift", ["bytes", "mode", "inode", "symlink", "hardlink"])
def test_bound_material_drift_is_refused_without_writes(tmp_path, native_artifact, monkeypatch, material, drift):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    path = {
        "config": prepared.descriptor.config_path,
        "manifest": prepared.descriptor.inputs_path / "manifest.json",
        "binding": prepared.batch / "native-producer-launch.json",
    }[material]
    if drift == "bytes":
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b" ")
        path.chmod(0o400)
    elif drift == "mode":
        path.chmod(0o600)
    elif drift == "inode":
        path.parent.chmod(0o700)
        _replace_same_bytes_and_mode(path, tmp_path / "replacement.json")
        if material != "binding":
            path.parent.chmod(0o500)
    elif drift == "symlink":
        path.parent.chmod(0o700)
        target = tmp_path / "outside-config.json"
        target.write_bytes(path.read_bytes())
        target.chmod(0o400)
        path.unlink()
        path.symlink_to(target)
        if material != "binding":
            path.parent.chmod(0o500)
    else:
        os.link(path, tmp_path / "second-link.json")
    before = _inventory(prepared.workspace)
    _forbid_mutations(monkeypatch)
    with pytest.raises(inputs.ProducerLaunchInputError):
        _validate(prepared)
    assert _inventory(prepared.workspace) == before


def test_changed_bootstrap_artifact_and_detached_descriptor_are_refused(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.ProducerLaunchInputError):
        _bind(prepared, inputs=replace(prepared.descriptor, config_sha256="b" * 64))
    assert _inventory(prepared.workspace) == before
    _bind(prepared)
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.ProducerLaunchInputError):
        _validate(prepared, artifact=replace(prepared.artifact, artifact_sha256="b" * 64))
    assert _inventory(prepared.workspace) == before


def test_noncanonical_binding_is_refused_without_repair(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    path = prepared.batch / "native-producer-launch.json"
    value = json.loads(path.read_bytes())
    path.chmod(0o600)
    path.write_bytes(json.dumps(value, indent=2).encode())
    path.chmod(0o400)
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.ProducerLaunchInputError):
        _validate(prepared)
    assert _inventory(prepared.workspace) == before


def test_even_rehashed_config_and_manifest_cannot_replace_the_attested_marker(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    config_path = prepared.descriptor.config_path
    config = prepared.descriptor.config
    config["budget"]["max_rounds"] = 100
    config_path.chmod(0o600)
    config_path.write_bytes(canonical_json(config))
    config_path.chmod(0o400)
    content, file_identity = inputs._read_bound_file(config_path)
    manifest_path = prepared.descriptor.inputs_path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"] = [file_identity]
    manifest["config_sha256"] = hashlib.sha256(content).hexdigest()
    manifest["manifest_sha256"] = inputs._digest(manifest, "manifest_sha256")
    manifest_path.chmod(0o600)
    manifest_path.write_bytes(canonical_json(manifest))
    manifest_path.chmod(0o400)
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.ProducerLaunchInputError) as refused:
        _validate(prepared)
    assert refused.value.code == "producer_launch_inputs_manifest_pin_mismatch"
    assert _inventory(prepared.workspace) == before


@pytest.mark.parametrize("stage", ["during-held-read", "after-binding", "during-final-input"])
def test_binding_inode_races_are_refused_by_held_reads_and_final_revalidation(
    tmp_path, native_artifact, monkeypatch, stage,
):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    path = prepared.batch / "native-producer-launch.json"
    identity = path.stat().st_dev, path.stat().st_ino
    changes = []

    def replace_binding():
        _replace_same_bytes_and_mode(path, tmp_path / "raced-binding.json")
        changes.append(_inventory(prepared.workspace))

    if stage == "during-held-read":
        original = inputs.os.read

        def read(descriptor, size):
            info = inputs.os.fstat(descriptor)
            if not changes and (info.st_dev, info.st_ino) == identity:
                replace_binding()
            return original(descriptor, size)

        monkeypatch.setattr(inputs.os, "read", read)
    elif stage == "after-binding":
        original = inputs._read_bound_file

        def read(current):
            value = original(current)
            if current == path and not changes:
                replace_binding()
            return value

        monkeypatch.setattr(inputs, "_read_bound_file", read)
    else:
        original = inputs._read_inputs
        reads = []

        def read(*args, **kwargs):
            value = original(*args, **kwargs)
            reads.append(value)
            if len(reads) == 2:
                replace_binding()
            return value

        monkeypatch.setattr(inputs, "_read_inputs", read)
    with pytest.raises(inputs.ProducerLaunchInputError):
        _validate(prepared)
    assert len(changes) == 1
    assert _inventory(prepared.workspace) == changes[0]


def test_boolean_validation_option_and_config_declarations_never_grant_authority(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    descriptor = _bind(prepared)
    assert descriptor.config["producer"]["fingerprint"] == "declaration-only"
    assert prepared.intent.producer_fingerprint == HEX
    assert "publication_eligible" not in descriptor.to_dict()
    with pytest.raises(inputs.ProducerLaunchInputError):
        _validate(prepared, require_unexpired=1)
