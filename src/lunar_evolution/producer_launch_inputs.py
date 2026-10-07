"""Create-only canonical configuration for one attested native producer launch.

The manifest marker is part of the original target argv. Input bytes, directories and the
launch binding retain their original inode identities. Validation only reads these records;
it cannot consume an attestation, launch a producer or grant publication authority. Producer
declarations inside configuration are ordinary input data, never authentication or score evidence.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn

from . import _benchmark_files as files
from .algorithm import AlgorithmProblemContract
from .candidate_evaluation_spec import canonical_json, strict_json
from .native_bootstrap import NativeBootstrapArtifact, load_native_bootstrap_artifact
from .producer_launcher import (
    ProducerLaunchAttestation,
    ProducerLaunchIntent,
    verify_producer_launch_attestation,
)
from .producer_process import _held_directory, _recovery_lock

PRODUCER_LAUNCH_INPUT_MARKER = "--lunar-producer-input-v1"
MAX_PRODUCER_LAUNCH_INPUT_BYTES = 512 * 1024
_RSI_MARKER = "--lunar-rsi-input-v1"
_INPUT_PROTOCOL = "lunar-producer-inputs-v1"
_BINDING_PROTOCOL = "lunar-producer-launch-inputs-v1"
_INPUT_DIRECTORY = ".producer-input"
_BINDING_NAME = "native-producer-launch.json"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MANIFEST_FIELDS = {
    "schema_version", "protocol", "journal_id", "config_sha256", "contract_sha256",
    "workspace_identity", "batch_identity", "inputs_identity", "files",
    "manifest_file_identity", "manifest_sha256",
}
_BINDING_FIELDS = {
    "schema_version", "protocol", "journal_id", "launch_id", "run_id", "parent_task_id",
    "task_id", "intent_sha256", "attestation_sha256", "bootstrap_descriptor_sha256",
    "bootstrap_artifact_sha256", "manifest_sha256", "config_sha256", "contract_sha256",
    "working_directory", "config_relative_path", "binding_file_identity", "binding_sha256",
}


class ProducerLaunchInputError(ValueError):
    """Fixed refusal code with no supplied paths, configuration or exception prose."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(reason: str) -> NoReturn:
    raise ProducerLaunchInputError("producer_launch_inputs_" + reason)


def _canonical(value: object) -> bytes:
    return canonical_json(value, maximum=MAX_PRODUCER_LAUNCH_INPUT_BYTES)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _digest(value: Mapping[str, Any], field: str) -> str:
    return _sha(_canonical({key: item for key, item in value.items() if key != field}))


def _node(path: Path) -> dict[str, int]:
    with _held_directory(path) as descriptor:
        info = os.fstat(descriptor)
        return {"device": info.st_dev, "inode": info.st_ino}


def _config(content: bytes) -> tuple[dict[str, Any], str]:
    value = strict_json(content, MAX_PRODUCER_LAUNCH_INPUT_BYTES)
    if not isinstance(value, dict) or _canonical(value) != content:
        _fail("config_invalid")
    contract = AlgorithmProblemContract.from_dict(value.get("contract"))
    if contract.to_dict() != value["contract"]:
        _fail("contract_invalid")
    return value, contract.digest()


def _read_bound_file(path: Path) -> tuple[bytes, dict[str, Any]]:
    """Read bounded bytes and identity from the same held no-follow descriptor."""
    with _held_directory(path.parent) as directory:
        before = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        try:
            opened = os.fstat(descriptor)
            names = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or stat.S_IMODE(opened.st_mode) != 0o400
                    or opened.st_size > MAX_PRODUCER_LAUNCH_INPUT_BYTES
                    or any(getattr(before, key) != getattr(opened, key) for key in names)):
                _fail("file_invalid")
            chunks = []
            remaining = MAX_PRODUCER_LAUNCH_INPUT_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(descriptor)
            named = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            if (len(content) > MAX_PRODUCER_LAUNCH_INPUT_BYTES or opened.st_size != len(content)
                    or any(getattr(opened, key) != getattr(after, key) for key in names)
                    or any(getattr(after, key) != getattr(named, key) for key in names)):
                _fail("input_changed")
            metadata = {
                "name": path.name, "size": len(content), "sha256": _sha(content),
                "device": opened.st_dev, "inode": opened.st_ino,
                "mtime_ns": opened.st_mtime_ns, "ctime_ns": opened.st_ctime_ns,
            }
        finally:
            os.close(descriptor)
    return content, metadata


def _write_file(directory: int, name: str, content: bytes | None = None, *,
                payload: dict[str, Any] | None = None, identity_field: str = "",
                digest_field: str = "") -> dict[str, Any]:
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o400, dir_fd=directory,
    )
    try:
        os.fchmod(descriptor, 0o400)
        value = None
        if payload is not None:
            identity = os.fstat(descriptor)
            value = {**payload, identity_field: {"device": identity.st_dev, "inode": identity.st_ino}}
            value[digest_field] = _digest(value, digest_field)
            content = _canonical(value)
        if content is None:
            _fail("file_invalid")
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                _fail("write_failed")
            offset += written
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        names = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (opened.st_nlink != 1 or opened.st_size != len(content)
                or any(getattr(opened, key) != getattr(named, key) for key in names)):
            _fail("input_changed")
        os.fsync(directory)
        return value if value is not None else {
            "name": name, "size": len(content), "sha256": _sha(content),
            "device": opened.st_dev, "inode": opened.st_ino,
            "mtime_ns": opened.st_mtime_ns, "ctime_ns": opened.st_ctime_ns,
        }
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class ProducerLaunchInputDescriptor:
    """Detached canonical input; callers must validate retained bytes at every native gate."""

    workspace: Path
    journal_id: str
    inputs_path: Path
    config_sha256: str
    contract_sha256: str
    manifest_sha256: str
    config_json: bytes
    manifest_json: bytes
    launch_binding_sha256: str | None = None

    @property
    def config_path(self) -> Path:
        return self.inputs_path / "config.json"

    @property
    def readonly_files(self) -> tuple[Path, ...]:
        return (self.config_path,)

    @property
    def read_paths(self) -> tuple[Path, ...]:
        return self.readonly_files

    @property
    def argv_fragment(self) -> tuple[str, str]:
        return PRODUCER_LAUNCH_INPUT_MARKER, self.manifest_sha256

    @property
    def deadline_unix(self) -> None:
        # Native intent/parent deadlines remain authoritative; configuration cannot renew them.
        return None

    @property
    def config(self) -> dict[str, Any]:
        return _config(self.config_json)[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1", "protocol": _INPUT_PROTOCOL,
            "workspace": str(self.workspace), "journal_id": self.journal_id,
            "inputs_path": str(self.inputs_path), "config_sha256": self.config_sha256,
            "contract_sha256": self.contract_sha256, "manifest_sha256": self.manifest_sha256,
            "launch_binding_sha256": self.launch_binding_sha256,
            "read_paths": [str(path) for path in self.read_paths], "deadline_unix": None,
        }


def _batch(workspace: str | Path, journal_id: str, *, create: bool = False) -> tuple[Path, Path]:
    if type(journal_id) is not str or _IDENTIFIER.fullmatch(journal_id) is None:
        _fail("journal_invalid")
    root = files.absolute_path(workspace)
    _node(root)
    batch = root / "evolution" / "producer-batches" / journal_id
    with _held_directory(batch, create=create):
        pass
    return root, batch


def _not_started(batch: Path, *, allow_binding: bool = False) -> None:
    with _held_directory(batch) as directory, os.scandir(directory) as entries:
        for entry in entries:
            if entry.name in {_INPUT_DIRECTORY, ".recovery.lock"}:
                continue
            if allow_binding and entry.name == _BINDING_NAME:
                continue
            if entry.name in {"work", "output"} and entry.is_dir(follow_symlinks=False):
                with _held_directory(batch / entry.name) as child, os.scandir(child) as contents:
                    if next(contents, None) is None:
                        continue
            _fail("attempt_already_started")


def _read_inputs(root: Path, batch: Path) -> ProducerLaunchInputDescriptor:
    path = batch / _INPUT_DIRECTORY
    with _held_directory(path) as directory:
        if stat.S_IMODE(os.fstat(directory).st_mode) != 0o500:
            _fail("input_directory_invalid")
        with os.scandir(directory) as entries:
            if {entry.name for entry in entries} != {"config.json", "manifest.json"}:
                _fail("input_directory_changed")
        manifest_bytes, manifest_file = _read_bound_file(path / "manifest.json")
        manifest = strict_json(manifest_bytes, MAX_PRODUCER_LAUNCH_INPUT_BYTES)
        if (not isinstance(manifest, dict) or set(manifest) != _MANIFEST_FIELDS
                or manifest["schema_version"] != "1" or manifest["protocol"] != _INPUT_PROTOCOL
                or _canonical(manifest) != manifest_bytes
                or manifest["manifest_sha256"] != _digest(manifest, "manifest_sha256")
                or manifest["manifest_file_identity"] != {
                    key: manifest_file[key] for key in ("device", "inode")
                }
                or manifest["journal_id"] != batch.name or manifest["workspace_identity"] != _node(root)
                or manifest["batch_identity"] != _node(batch) or manifest["inputs_identity"] != _node(path)):
            _fail("manifest_invalid")
        content, config_file = _read_bound_file(path / "config.json")
        if manifest["files"] != [config_file]:
            _fail("input_changed")
        _value, contract_sha = _config(content)
        if (manifest["config_sha256"] != _sha(content)
                or manifest["contract_sha256"] != contract_sha):
            _fail("config_changed")
    return ProducerLaunchInputDescriptor(
        root, batch.name, path, _sha(content), contract_sha, manifest["manifest_sha256"],
        content, manifest_bytes,
    )


def prepare_producer_launch_inputs(
    workspace: str | Path, *, journal_id: str, config: Mapping[str, object],
) -> ProducerLaunchInputDescriptor:
    """Stage a canonical config create-only, then append its argv fragment before attestation.

    Config must carry a complete normalized AlgorithmProblemContract. Partial staging is retained
    as diagnostic evidence; retries cannot overwrite it or silently reuse an existing batch.
    """
    try:
        if not isinstance(config, Mapping):
            _fail("config_invalid")
        content = _canonical(dict(config))
        _value, contract_sha = _config(content)
        root, batch = _batch(workspace, journal_id, create=True)
        with _recovery_lock(batch):
            _not_started(batch)
            with _held_directory(batch) as parent:
                os.mkdir(_INPUT_DIRECTORY, 0o700, dir_fd=parent)
                created = os.stat(_INPUT_DIRECTORY, dir_fd=parent, follow_symlinks=False)
                with _held_directory(batch / _INPUT_DIRECTORY) as directory:
                    opened = os.fstat(directory)
                    if (created.st_dev, created.st_ino) != (opened.st_dev, opened.st_ino):
                        _fail("input_directory_changed")
                    config_file = _write_file(directory, "config.json", content)
                    if _read_bound_file(batch / _INPUT_DIRECTORY / "config.json") != (content, config_file):
                        _fail("input_changed")
                    _write_file(directory, "manifest.json", payload={
                        "schema_version": "1", "protocol": _INPUT_PROTOCOL, "journal_id": journal_id,
                        "config_sha256": _sha(content), "contract_sha256": contract_sha,
                        "workspace_identity": _node(root), "batch_identity": _node(batch),
                        "inputs_identity": _node(batch / _INPUT_DIRECTORY), "files": [config_file],
                    }, identity_field="manifest_file_identity", digest_field="manifest_sha256")
                    os.fchmod(directory, 0o500)
                    os.fsync(directory)
                os.fsync(parent)
            prepared = _read_inputs(root, batch)
            if prepared.config_json != content:
                _fail("input_changed")
            return prepared
    except ProducerLaunchInputError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as exc:
        raise ProducerLaunchInputError("producer_launch_inputs_prepare_invalid") from exc


def _marker(intent: ProducerLaunchIntent) -> str | None:
    indexes = [index for index, value in enumerate(intent.argv) if value == PRODUCER_LAUNCH_INPUT_MARKER]
    if not indexes:
        return None
    if (len(indexes) != 1 or indexes[0] != len(intent.argv) - 2
            or _SHA256.fullmatch(intent.argv[-1]) is None or _RSI_MARKER in intent.argv):
        _fail("marker_invalid")
    return intent.argv[-1]


def _launch_payload(
    intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact, inputs: ProducerLaunchInputDescriptor,
    *, binding_identity: dict[str, int] | None = None,
) -> dict[str, Any]:
    if _marker(intent) != inputs.manifest_sha256 or intent.journal_id != inputs.journal_id:
        _fail("manifest_pin_mismatch")
    if intent.working_directory != "work" or (
        Path(intent.output_directory) == Path(_INPUT_DIRECTORY)
        or Path(_INPUT_DIRECTORY) in Path(intent.output_directory).parents
    ):
        _fail("layout_invalid")
    verify_producer_launch_attestation(intent, attestation)
    installed = load_native_bootstrap_artifact(
        artifact.path, descriptor=artifact.descriptor, allowlist_id=artifact.allowlist_id,
    )
    if (artifact.artifact_sha256 != installed.artifact_sha256
            or artifact.platform_execution_mode != installed.platform_execution_mode):
        _fail("bootstrap_invalid")
    if inputs.contract_sha256 != intent.contract_sha256:
        _fail("contract_pin_mismatch")
    value = {
        "schema_version": "1", "protocol": _BINDING_PROTOCOL,
        **{key: getattr(intent, key) for key in
           ("journal_id", "launch_id", "run_id", "parent_task_id", "task_id")},
        "intent_sha256": intent.digest(), "attestation_sha256": attestation.digest(),
        "bootstrap_descriptor_sha256": installed.descriptor.digest(),
        "bootstrap_artifact_sha256": installed.artifact_sha256,
        "manifest_sha256": inputs.manifest_sha256, "config_sha256": inputs.config_sha256,
        "contract_sha256": inputs.contract_sha256,
        "working_directory": "work", "config_relative_path": "../.producer-input/config.json",
    }
    if binding_identity is not None:
        value["binding_file_identity"] = binding_identity
        value["binding_sha256"] = _digest(value, "binding_sha256")
    return value


def bind_producer_launch_inputs(
    workspace: str | Path, *, intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact, inputs: ProducerLaunchInputDescriptor,
) -> ProducerLaunchInputDescriptor:
    """Bind intent/attestation/bootstrap create-only before a lifecycle claim or gate release."""
    if (not isinstance(intent, ProducerLaunchIntent) or not isinstance(attestation, ProducerLaunchAttestation)
            or not isinstance(artifact, NativeBootstrapArtifact) or not isinstance(inputs, ProducerLaunchInputDescriptor)):
        _fail("input_invalid")
    try:
        root, batch = _batch(workspace, intent.journal_id)
        with _recovery_lock(batch):
            _not_started(batch)
            retained = _read_inputs(root, batch)
            if retained != inputs:
                _fail("descriptor_changed")
            payload = _launch_payload(intent, attestation, artifact, retained)
            with _held_directory(batch) as directory:
                value = _write_file(directory, _BINDING_NAME, payload=payload,
                                    identity_field="binding_file_identity", digest_field="binding_sha256")
            validated = validate_producer_launch_inputs(
                root, intent=intent, attestation=attestation, artifact=artifact, require_unexpired=True,
            )
            if validated is None or validated.launch_binding_sha256 != value["binding_sha256"]:
                _fail("binding_changed")
            _not_started(batch, allow_binding=True)
            return validated
    except ProducerLaunchInputError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as exc:
        raise ProducerLaunchInputError("producer_launch_inputs_bind_invalid") from exc


def validate_producer_launch_inputs(
    workspace: str | Path, *, intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact, require_unexpired: bool = False,
) -> ProducerLaunchInputDescriptor | None:
    """Read exact inputs/binding without writes, locks, launch, replay or renewed budget.

    Legacy intents without a marker or retained material return None. A marker or staged material
    forbids downgrade. require_unexpired follows the RSI composition interface; this neutral
    configuration has no independent deadline and leaves the original native intent budget intact.
    """
    if (not isinstance(intent, ProducerLaunchIntent) or not isinstance(attestation, ProducerLaunchAttestation)
            or not isinstance(artifact, NativeBootstrapArtifact) or type(require_unexpired) is not bool):
        _fail("input_invalid")
    try:
        marker = _marker(intent)
        root = files.absolute_path(workspace)
        batch = root / "evolution" / "producer-batches" / intent.journal_id
        path = batch / _BINDING_NAME
        staged = batch / _INPUT_DIRECTORY
        if marker is None and not (path.exists() or path.is_symlink()
                                  or staged.exists() or staged.is_symlink()):
            return None
        if marker is None:
            _fail("marker_missing")
        root, batch = _batch(root, intent.journal_id)
        retained = _read_inputs(root, batch)
        raw, binding_file = _read_bound_file(path)
        expected = _launch_payload(
            intent, attestation, artifact, retained,
            binding_identity={key: binding_file[key] for key in ("device", "inode")},
        )
        value = strict_json(raw, MAX_PRODUCER_LAUNCH_INPUT_BYTES)
        if (not isinstance(value, dict) or set(value) != _BINDING_FIELDS
                or value != expected or raw != _canonical(value)):
            _fail("binding_changed")
        if _read_inputs(root, batch) != retained:
            _fail("input_changed")
        if _read_bound_file(path) != (raw, binding_file):
            _fail("binding_changed")
        return replace(retained, launch_binding_sha256=value["binding_sha256"])
    except ProducerLaunchInputError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as exc:
        raise ProducerLaunchInputError("producer_launch_inputs_validation_invalid") from exc


__all__ = [
    "MAX_PRODUCER_LAUNCH_INPUT_BYTES", "PRODUCER_LAUNCH_INPUT_MARKER",
    "ProducerLaunchInputDescriptor", "ProducerLaunchInputError", "bind_producer_launch_inputs",
    "prepare_producer_launch_inputs", "validate_producer_launch_inputs",
]
