"""Create-only RSI inputs bound before an isolated native producer is launched.

The reserved argv marker makes the input manifest part of the original native intent and
attestation. The native lifecycle must validate it before consumption and gate release and
allow only the two exact input files through its read-only isolation policy. This module does
not launch a worker, grant memory admission, or infer whether memory improved a solver result.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn

from . import _benchmark_files as files
from .candidate_evaluation_spec import canonical_json, strict_json
from .native_bootstrap import NativeBootstrapArtifact, load_native_bootstrap_artifact
from .producer_launcher import (
    ProducerLaunchAttestation,
    ProducerLaunchIntent,
    verify_producer_launch_attestation,
)
from .producer_process import _held_directory, _recovery_lock
from .rsi_gateway import SolverRequest
from .rsi_learning import MAX_RSI_RECORD_BYTES, MemorySnapshot, load_memory_snapshot

NATIVE_RSI_INPUT_MARKER = "--lunar-rsi-input-v1"
_INPUT_PROTOCOL = "lunar-native-rsi-inputs-v1"
_BINDING_PROTOCOL = "lunar-native-rsi-launch-inputs-v1"
_INPUT_DIRECTORY = ".rsi-input"
_BINDING_NAME = "native-rsi-launch.json"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MANIFEST_FIELDS = {
    "schema_version", "protocol", "journal_id", "episode_id", "request_sha256",
    "memory_snapshot_sha256", "workspace_identity", "batch_identity", "inputs_identity",
    "files", "manifest_file_identity", "manifest_sha256",
}
_BINDING_FIELDS = {
    "schema_version", "protocol", "journal_id", "launch_id", "run_id", "parent_task_id",
    "task_id", "intent_sha256", "attestation_sha256", "bootstrap_descriptor_sha256",
    "bootstrap_artifact_sha256", "manifest_sha256", "request_sha256", "memory_snapshot_sha256",
    "episode_id", "working_directory", "request_relative_path", "memory_relative_path",
    "binding_file_identity", "binding_sha256",
}


class NativeRSIInputError(ValueError):
    """Fixed public refusal codes without caller input, filesystem or producer prose."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(reason: str) -> NoReturn:
    raise NativeRSIInputError("rsi_native_inputs_" + reason)


def _canonical(value: object) -> bytes:
    return canonical_json(value, maximum=MAX_RSI_RECORD_BYTES)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _digest(value: dict[str, Any], field: str) -> str:
    return _sha(_canonical({key: item for key, item in value.items() if key != field}))


def _node(path: Path) -> dict[str, int]:
    with _held_directory(path) as descriptor:
        info = os.fstat(descriptor)
        return {"device": info.st_dev, "inode": info.st_ino}


def _file_descriptor(path: Path, content: bytes) -> dict[str, Any]:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o400 or info.st_size != len(content)):
        _fail("file_invalid")
    return {
        "name": path.name, "size": len(content), "sha256": _sha(content),
        "device": info.st_dev, "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
    }


def _read_bound_file(path: Path) -> tuple[bytes, dict[str, Any]]:
    """Tie bounded bytes and metadata to one held, no-follow file descriptor.

    The manifest and launch binding pin their own inode. Their identity must come
    from the descriptor that actually supplied the bytes, rather than a separate
    pathname lookup before or after a read.
    """
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
                    or opened.st_size > MAX_RSI_RECORD_BYTES
                    or any(getattr(before, key) != getattr(opened, key) for key in names)):
                _fail("file_invalid")
            chunks = []
            remaining = MAX_RSI_RECORD_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(descriptor)
            named = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            if (len(content) > MAX_RSI_RECORD_BYTES or opened.st_size != len(content)
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


def _deadline(request: SolverRequest, *, require_unexpired: bool) -> float | None:
    value = dict(request.budget).get("deadline_unix")
    if value is None:
        return None
    if type(value) not in {int, float} or not math.isfinite(float(value)) or value <= 0:
        _fail("deadline_invalid")
    if require_unexpired and time.time() >= value:
        _fail("deadline_expired")
    return float(value)


def _copy_inputs(request: SolverRequest, memory: MemorySnapshot) -> tuple[bytes, bytes, float | None]:
    if not isinstance(request, SolverRequest) or not isinstance(memory, MemorySnapshot):
        _fail("input_invalid")
    request_bytes = _canonical(request.to_dict())
    frozen_request = SolverRequest.from_dict(strict_json(request_bytes, MAX_RSI_RECORD_BYTES))
    memory_bytes = memory.to_bytes()
    frozen_memory = load_memory_snapshot(memory_bytes)
    if (frozen_request.digest() != request.digest() or frozen_memory.digest() != memory.digest()
            or frozen_request.memory_snapshot_sha256 != frozen_memory.digest()):
        _fail("memory_pin_mismatch")
    return request_bytes, memory_bytes, _deadline(frozen_request, require_unexpired=True)


@dataclass(frozen=True, slots=True)
class NativeRSIInputDescriptor:
    """Detached approved snapshot and complete request delivered to one native attempt.

    Only descriptors returned by validated APIs describe retained evidence. A caller-created
    DTO cannot bypass the file/launch checks. Neither approval structure nor input delivery is
    a substitute for the controller's independent governed-memory admission gate.
    """

    workspace: Path
    journal_id: str
    inputs_path: Path
    request_sha256: str
    memory_snapshot_sha256: str
    manifest_sha256: str
    request_json: bytes
    memory_json: bytes
    manifest_json: bytes
    deadline_unix: float | None
    launch_binding_sha256: str | None = None

    @property
    def request_path(self) -> Path:
        return self.inputs_path / "request.json"

    @property
    def memory_path(self) -> Path:
        return self.inputs_path / "memory.json"

    @property
    def read_paths(self) -> tuple[Path, Path]:
        return self.request_path, self.memory_path

    @property
    def argv_fragment(self) -> tuple[str, str]:
        return NATIVE_RSI_INPUT_MARKER, self.manifest_sha256

    @property
    def request(self) -> SolverRequest:
        return SolverRequest.from_dict(strict_json(self.request_json, MAX_RSI_RECORD_BYTES))

    @property
    def memory(self) -> MemorySnapshot:
        return load_memory_snapshot(self.memory_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1", "protocol": _INPUT_PROTOCOL,
            "workspace": str(self.workspace), "journal_id": self.journal_id,
            "inputs_path": str(self.inputs_path), "episode_id": self.request.episode_id,
            "request_sha256": self.request_sha256, "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "manifest_sha256": self.manifest_sha256, "deadline_unix": self.deadline_unix,
            "launch_binding_sha256": self.launch_binding_sha256,
            "read_paths": [str(path) for path in self.read_paths],
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
    """Permit only staging and empty ordinary work/output directories before binding."""
    with _held_directory(batch) as descriptor, os.scandir(descriptor) as entries:
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


def _write_open_file(descriptor: int, directory: int, name: str, content: bytes) -> dict[str, Any]:
    os.fchmod(descriptor, 0o400)
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("short input write")
        offset += written
    os.fsync(descriptor)
    opened = os.fstat(descriptor)
    named = os.stat(name, dir_fd=directory, follow_symlinks=False)
    names = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (any(getattr(opened, key) != getattr(named, key) for key in names)
            or opened.st_nlink != 1 or opened.st_size != len(content)):
        _fail("input_changed")
    return {
        "name": name, "size": len(content), "sha256": _sha(content),
        "device": opened.st_dev, "inode": opened.st_ino,
        "mtime_ns": opened.st_mtime_ns, "ctime_ns": opened.st_ctime_ns,
    }


def _open_new_file(directory: int, name: str) -> int:
    return os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o400, dir_fd=directory,
    )


def _write_file(directory: int, name: str, content: bytes) -> dict[str, Any]:
    descriptor = _open_new_file(directory, name)
    try:
        return _write_open_file(descriptor, directory, name, content)
    finally:
        os.close(descriptor)


def _write_self_bound_file(
    directory: int, name: str, payload: dict[str, Any], *, identity_field: str, digest_field: str,
) -> dict[str, Any]:
    descriptor = _open_new_file(directory, name)
    try:
        observed = os.fstat(descriptor)
        value = {**payload, identity_field: {"device": observed.st_dev, "inode": observed.st_ino}}
        value[digest_field] = _digest(value, digest_field)
        _write_open_file(descriptor, directory, name, _canonical(value))
        os.fsync(directory)
        return value
    finally:
        os.close(descriptor)


def _read_inputs(root: Path, batch: Path, *, require_unexpired: bool) -> NativeRSIInputDescriptor:
    path = batch / _INPUT_DIRECTORY
    with _held_directory(path) as descriptor:
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o500:
            _fail("input_directory_invalid")
        with os.scandir(descriptor) as entries:
            if {entry.name for entry in entries} != {"request.json", "memory.json", "manifest.json"}:
                _fail("input_directory_changed")
        manifest_bytes, manifest_file = _read_bound_file(path / "manifest.json")
        manifest = strict_json(manifest_bytes, MAX_RSI_RECORD_BYTES)
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
        if (not isinstance(manifest["files"], list) or len(manifest["files"]) != 2
                or [item.get("name") if isinstance(item, dict) else None for item in manifest["files"]]
                != ["request.json", "memory.json"]):
            _fail("manifest_invalid")
        materials = []
        for expected in manifest["files"]:
            current = path / expected["name"]
            content, metadata = _read_bound_file(current)
            if metadata != expected:
                _fail("input_changed")
            materials.append(content)
        request = SolverRequest.from_dict(strict_json(materials[0], MAX_RSI_RECORD_BYTES))
        memory = load_memory_snapshot(materials[1])
        if (request.digest() != manifest["request_sha256"]
                or memory.digest() != manifest["memory_snapshot_sha256"]
                or request.memory_snapshot_sha256 != memory.digest()
                or request.episode_id != manifest["episode_id"]
                or _canonical(request.to_dict()) != materials[0]):
            _fail("memory_pin_mismatch")
        deadline = _deadline(request, require_unexpired=require_unexpired)
    return NativeRSIInputDescriptor(
        root, batch.name, path, request.digest(), memory.digest(), manifest["manifest_sha256"],
        materials[0], materials[1], manifest_bytes, deadline,
    )


def prepare_native_rsi_inputs(
    workspace: str | Path, *, journal_id: str, request: SolverRequest, memory: MemorySnapshot,
) -> NativeRSIInputDescriptor:
    """Copy complete canonical inputs create-only, before constructing the native intent.

    Append ``descriptor.argv_fragment`` to the original target argv before building its intent
    and attestation, then call ``bind_native_rsi_launch``. Partial staging remains diagnostic
    evidence and cannot be silently overwritten or automatically reused.
    """
    try:
        request_bytes, memory_bytes, _ = _copy_inputs(request, memory)
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
                    identities = [_write_file(directory, name, content) for name, content in
                                  (("request.json", request_bytes), ("memory.json", memory_bytes))]
                    if identities != [_file_descriptor(batch / _INPUT_DIRECTORY / name, content)
                                      for name, content in (("request.json", request_bytes), ("memory.json", memory_bytes))]:
                        _fail("input_changed")
                    manifest = {
                        "schema_version": "1", "protocol": _INPUT_PROTOCOL, "journal_id": journal_id,
                        "episode_id": request.episode_id, "request_sha256": _sha(request_bytes),
                        "memory_snapshot_sha256": _sha(memory_bytes), "workspace_identity": _node(root),
                        "batch_identity": _node(batch), "inputs_identity": _node(batch / _INPUT_DIRECTORY),
                        "files": identities,
                    }
                    _write_self_bound_file(
                        directory, "manifest.json", manifest,
                        identity_field="manifest_file_identity", digest_field="manifest_sha256",
                    )
                    os.fchmod(directory, 0o500)
                    os.fsync(directory)
                os.fsync(parent)
            prepared = _read_inputs(root, batch, require_unexpired=True)
            if prepared.request_json != request_bytes or prepared.memory_json != memory_bytes:
                _fail("input_changed")
            return prepared
    except NativeRSIInputError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as exc:
        raise NativeRSIInputError("rsi_native_inputs_prepare_invalid") from exc


def _marker(intent: ProducerLaunchIntent) -> str | None:
    indexes = [index for index, value in enumerate(intent.argv) if value == NATIVE_RSI_INPUT_MARKER]
    if not indexes:
        return None
    if (len(indexes) != 1 or indexes[0] != len(intent.argv) - 2
            or _SHA256.fullmatch(intent.argv[-1]) is None):
        _fail("marker_invalid")
    return intent.argv[-1]


def _launch_payload(
    intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact, inputs: NativeRSIInputDescriptor,
    *, binding_identity: dict[str, int] | None = None,
) -> dict[str, Any]:
    marker = _marker(intent)
    if marker != inputs.manifest_sha256 or intent.journal_id != inputs.journal_id:
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
    request = inputs.request
    if (request.contract_sha256 != intent.contract_sha256
            or request.evaluator_sha256 != intent.evaluator_fingerprint
            or request.environment_sha256 != intent.environment_sha256
            or request.memory_snapshot_sha256 != inputs.memory_snapshot_sha256):
        _fail("launch_authority_mismatch")
    value = {
        "schema_version": "1", "protocol": _BINDING_PROTOCOL,
        **{key: getattr(intent, key) for key in
           ("journal_id", "launch_id", "run_id", "parent_task_id", "task_id")},
        "intent_sha256": intent.digest(), "attestation_sha256": attestation.digest(),
        "bootstrap_descriptor_sha256": installed.descriptor.digest(),
        "bootstrap_artifact_sha256": installed.artifact_sha256,
        "manifest_sha256": inputs.manifest_sha256, "request_sha256": inputs.request_sha256,
        "memory_snapshot_sha256": inputs.memory_snapshot_sha256, "episode_id": request.episode_id,
        "working_directory": "work", "request_relative_path": "../.rsi-input/request.json",
        "memory_relative_path": "../.rsi-input/memory.json",
    }
    if binding_identity is not None:
        value["binding_file_identity"] = binding_identity
        value["binding_sha256"] = _digest(value, "binding_sha256")
    return value


def bind_native_rsi_launch(
    workspace: str | Path, *, intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact, inputs: NativeRSIInputDescriptor,
) -> NativeRSIInputDescriptor:
    """Bind original intent/attestation/bootstrap create-only before any lifecycle claim."""
    if (not isinstance(intent, ProducerLaunchIntent) or not isinstance(attestation, ProducerLaunchAttestation)
            or not isinstance(artifact, NativeBootstrapArtifact) or not isinstance(inputs, NativeRSIInputDescriptor)):
        _fail("input_invalid")
    try:
        root, batch = _batch(workspace, intent.journal_id)
        with _recovery_lock(batch):
            _not_started(batch)
            retained = _read_inputs(root, batch, require_unexpired=True)
            if retained != inputs:
                _fail("descriptor_changed")
            value = _launch_payload(intent, attestation, artifact, retained)
            with _held_directory(batch) as directory:
                value = _write_self_bound_file(
                    directory, _BINDING_NAME, value,
                    identity_field="binding_file_identity", digest_field="binding_sha256",
                )
            validated = validate_native_rsi_launch_inputs(
                root, intent=intent, attestation=attestation, artifact=artifact, require_unexpired=True,
            )
            if validated is None or validated.launch_binding_sha256 != value["binding_sha256"]:
                _fail("binding_changed")
            _not_started(batch, allow_binding=True)
            return validated
    except NativeRSIInputError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as exc:
        raise NativeRSIInputError("rsi_native_inputs_bind_invalid") from exc


def validate_native_rsi_launch_inputs(
    workspace: str | Path, *, intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact, require_unexpired: bool = False,
) -> NativeRSIInputDescriptor | None:
    """Read exact original inputs/binding without writing, locking or refreshing a deadline.

    Legacy intents without a marker or binding return ``None``. A marker or retained binding
    forbids downgrade. New dispatch/gate admission must pass ``require_unexpired=True``; historical
    inspection defaults to accepting an expired original deadline without authorizing another run.
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
        retained = _read_inputs(root, batch, require_unexpired=require_unexpired)
        raw, binding_file = _read_bound_file(path)
        expected = _launch_payload(
            intent, attestation, artifact, retained,
            binding_identity={key: binding_file[key] for key in ("device", "inode")},
        )
        value = strict_json(raw, MAX_RSI_RECORD_BYTES)
        if (not isinstance(value, dict) or set(value) != _BINDING_FIELDS
                or value != expected or raw != _canonical(value)):
            _fail("binding_changed")
        # Reopen all inputs after the launch/installation validation; no stale detached read
        # may be accepted when an input or its original directory changed during inspection.
        if _read_inputs(root, batch, require_unexpired=require_unexpired) != retained:
            _fail("input_changed")
        if _read_bound_file(path) != (raw, binding_file):
            _fail("binding_changed")
        return replace(retained, launch_binding_sha256=value["binding_sha256"])
    except NativeRSIInputError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as exc:
        raise NativeRSIInputError("rsi_native_inputs_validation_invalid") from exc


__all__ = [
    "NATIVE_RSI_INPUT_MARKER",
    "NativeRSIInputDescriptor",
    "NativeRSIInputError",
    "bind_native_rsi_launch",
    "prepare_native_rsi_inputs",
    "validate_native_rsi_launch_inputs",
]
