"""Trusted worker-local native lookup; never a public launch or cleanup endpoint.

Only an installed launcher retaining original objects may prepare this observer.
The in-memory resolver cannot be reconstructed from its durable diagnostic pin.
Neither this module nor a completed audit grants runtime or publication authority.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from ._candidate_workspace_io import DirectoryChain
from .external_worker_origin import WorkerOriginContext
from .external_worker_wrapper import (
    MAX_WORKER_REQUEST_BYTES,
    _publish,
    _read_at,
    parse_worker_json,
    validate_worker_request,
    worker_json,
)
from .native_bootstrap import NativeBootstrapArtifact, load_native_bootstrap_artifact
from .native_deadline_binding import verify_native_deadline_binding
from .native_trusted_attempt import (
    NativeTrustedRegisteredContext,
    audit_native_trusted_lifecycle,
    recover_native_trusted_attempt,
)
from .producer_bootstrap import build_trusted_bootstrap_launch
from .producer_launcher import (
    ProducerLaunchAttestation,
    ProducerLaunchIntent,
    verify_producer_launch_attestation,
)
from .producer_process import _current_recovery_lock_identity, _file_identity
from .rsi_gateway import SolverRequest

_PROTOCOL = "lunar-worker-native-local-inspection-v1"
_PIN_NAME = "native-context.json"
_MAX = 256 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_AUTHORITY = {
    "publication_eligible": False, "native_success": False,
    "remote_cleanup_verified": False, "publication_authority": False,
}


class WorkerNativeLifecycleError(ValueError):
    """Fixed local errors without private paths, original objects or child prose."""


def _fail(reason: str) -> None:
    raise WorkerNativeLifecycleError("worker_native_" + reason)


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("digest_invalid")
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(worker_json(value)).hexdigest()


def _private(chain: DirectoryChain) -> None:
    chain.check()
    info = os.fstat(chain.fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        _fail("context_drift")


def _entry(chain: DirectoryChain, path: Path, name: str, raw: bytes,
           pin: tuple[str | int, ...]) -> None:
    def check_directory() -> None:
        chain.check()
        # The original chain must name this exact path. Equal bytes in another
        # private directory cannot associate that directory's FD with this pin.
        if tuple(item[1] for item in chain.links) != path.parts[1:]:
            _fail("context_drift")
        named = os.stat(path, follow_symlinks=False)
        held = os.fstat(chain.fd)
        if (not stat.S_ISDIR(named.st_mode)
                or (named.st_dev, named.st_ino) != (held.st_dev, held.st_ino)):
            _fail("context_drift")

    def check_named_entry() -> None:
        info = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if (info.st_size, info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns) != pin[1:]:
            _fail("context_drift")

    check_directory()
    check_named_entry()
    if (tuple(_file_identity(path / name).values()) != pin
            or _read_at(chain.fd, name, _MAX) != raw
            or tuple(_file_identity(path / name).values()) != pin):
        _fail("context_drift")
    check_named_entry()
    check_directory()


@dataclass(frozen=True, slots=True)
class WorkerNativeTaskMapping:
    """Explicit installed launcher's assignment-to-native identity mapping."""

    worker_run_id: str
    worker_task_id: str
    episode_id: str
    native_run_id: str
    native_parent_task_id: str
    native_task_id: str

    def __post_init__(self) -> None:
        for value in self.to_dict().values():
            if type(value) is not str or _ID.fullmatch(value) is None:
                _fail("mapping_invalid")

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__slots__}


def native_lifecycle_lookup(*, context: WorkerOriginContext, request_sha256: str,
                            profile_sha256: str) -> bytes:
    """Build a bounded selector; paths, attestation, artifact and PID are absent."""
    if type(context) is not WorkerOriginContext:
        _fail("lookup_invalid")
    context.__post_init__()
    return worker_json({"schema_version": "1", "protocol": _PROTOCOL,
                        "context": context.to_dict(), "request_sha256": _sha(request_sha256),
                        "profile_sha256": _sha(profile_sha256)})


def _lookup(raw: bytes) -> dict:
    try:
        value = parse_worker_json(raw, 8192)
        if set(value) != {"schema_version", "protocol", "context", "request_sha256", "profile_sha256"}:
            _fail("lookup_invalid")
        context = WorkerOriginContext.from_dict(value["context"])
        if native_lifecycle_lookup(context=context, request_sha256=value["request_sha256"],
                                   profile_sha256=value["profile_sha256"]) != raw:
            _fail("lookup_invalid")
        return value
    except Exception:  # noqa: BLE001 - normalize selector errors without retaining private context.
        raise WorkerNativeLifecycleError("worker_native_lookup_invalid") from None


@dataclass(slots=True)
class _Original:
    context: WorkerOriginContext = field(repr=False)
    request: SolverRequest = field(repr=False)
    mapping: WorkerNativeTaskMapping = field(repr=False)
    intent: ProducerLaunchIntent = field(repr=False)
    attestation: ProducerLaunchAttestation = field(repr=False)
    artifact: NativeBootstrapArtifact = field(repr=False)
    worker_chain: DirectoryChain = field(repr=False)
    worker_path: Path = field(repr=False)
    workspace: Path = field(repr=False)
    producer_root: Path = field(repr=False)
    worker_raw: bytes = field(repr=False)
    worker_pin: tuple[str | int, ...] = field(repr=False)
    lookup_raw: bytes = field(repr=False)
    baseline: bytes = field(repr=False)
    native: NativeTrustedRegisteredContext | None = field(default=None, repr=False)
    chains: list[DirectoryChain] = field(default_factory=list, repr=False)
    binding_raw: bytes | None = field(default=None, repr=False)
    binding_pin: tuple[str | int, ...] | None = field(default=None, repr=False)

    def snapshot(self) -> bytes:
        return worker_json({"context": self.context.to_dict(), "request": self.request.to_dict(),
                            "mapping": self.mapping.to_dict(), "workspace": str(self.workspace),
                            "producer_root": str(self.producer_root), "intent": self.intent.to_dict(),
                            "attestation": self.attestation.to_dict(),
                            "artifact": {"path": str(self.artifact.path),
                                         "source_sha256": self.artifact.source_sha256,
                                         "artifact_sha256": self.artifact.artifact_sha256,
                                         "compiler": self.artifact.compiler,
                                         "platform_execution_mode": self.artifact.platform_execution_mode,
                                         "allowlist_id": self.artifact.allowlist_id,
                                         "descriptor": self.artifact.descriptor.to_dict()}})

    def check_originals(self) -> None:
        if self.snapshot() != self.baseline:
            _fail("context_drift")
        self.context.__post_init__()
        self.mapping.__post_init__()
        self.intent.__post_init__()
        verify_producer_launch_attestation(self.intent, self.attestation)
        mapping = self.mapping
        if ((mapping.worker_run_id, mapping.worker_task_id, mapping.episode_id)
                != (self.context.run_id, self.context.task_id, self.context.episode_id)
                or (mapping.native_run_id, mapping.native_parent_task_id, mapping.native_task_id)
                != (self.intent.run_id, self.intent.parent_task_id, self.intent.task_id)
                or self.context.episode_id != self.request.episode_id
                or (self.request.contract_sha256, self.request.evaluator_sha256, self.request.environment_sha256)
                != (self.intent.contract_sha256, self.intent.evaluator_fingerprint, self.intent.environment_sha256)):
            _fail("mapping_mismatch")
        _private(self.worker_chain)
        _entry(self.worker_chain, self.worker_path, "intent.json", self.worker_raw, self.worker_pin)

    def check_native(self) -> None:
        self.check_originals()
        native = self.native
        if native is None or len(self.chains) != 4:
            _fail("context_unavailable")
        for chain in self.chains:
            chain.check()
        batch = Path(native.workspace) / "evolution" / "producer-batches" / native.journal_id
        _entry(self.chains[1], batch, "process-registration.json",
               native.registration_json, native.registration_file_identity)
        _entry(self.chains[1], batch, "trusted-bootstrap-handoff.json",
               native.handoff_json, native.handoff_file_identity)
        deadline = parse_worker_json(native.deadline_json, _MAX)
        binding = parse_worker_json(native.deadline_binding_json, _MAX)
        verify_native_deadline_binding(batch, binding=binding, expected_record=deadline)
        if _current_recovery_lock_identity(batch) != native.recovery_lock_identity:
            _fail("context_drift")
        load_native_bootstrap_artifact(self.artifact.path, descriptor=self.artifact.descriptor,
                                       allowlist_id=self.artifact.allowlist_id)
        if self.binding_raw is not None:
            _entry(self.worker_chain, self.worker_path, _PIN_NAME, self.binding_raw, self.binding_pin)
        for chain in self.chains:
            chain.check()
        self.check_originals()

    def close(self) -> None:
        while self.chains:
            self.chains.pop().close()


class WorkerNativeLifecycleResolver:
    """In-memory original object owner, with create-only private diagnostic pins.

    This trusted-only API is deliberately not wired to the worker byte channel.
    Prepare once using the creator's original worker-intent pin and held chain;
    give its returned callback only to the original native registered_observer.
    Closing a resolver loses lookup capability; durable files cannot restore it.
    """

    def __init__(self) -> None:
        self._originals: dict[bytes, _Original] = {}
        self._closed = False

    def prepare_observer(
        self, *, context: WorkerOriginContext, request: SolverRequest,
        profile_sha256: str, mapping: WorkerNativeTaskMapping,
        intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
        artifact: NativeBootstrapArtifact, workspace: Path, producer_root: Path,
        episode_directory: Path,
        original_episode_chain: DirectoryChain, original_worker_intent: bytes,
        original_worker_intent_identity: tuple[str | int, ...],
    ) -> Callable[[NativeTrustedRegisteredContext], None]:
        """Retain originals; only the actual pre-gate observer publishes a pin."""
        if self._closed or type(original_episode_chain) is not DirectoryChain:
            _fail("context_unavailable")
        if (type(context) is not WorkerOriginContext or type(request) is not SolverRequest
                or type(mapping) is not WorkerNativeTaskMapping
                or type(intent) is not ProducerLaunchIntent
                or type(attestation) is not ProducerLaunchAttestation
                or type(artifact) is not NativeBootstrapArtifact
                or not isinstance(episode_directory, Path) or not episode_directory.is_absolute()
                or ".." in episode_directory.parts
                or any(not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts
                       for path in (workspace, producer_root))):
            _fail("context_invalid")
        lookup = native_lifecycle_lookup(context=context, request_sha256=request.digest(),
                                         profile_sha256=profile_sha256)
        if lookup in self._originals:
            _fail("binding_replayed")
        wire = parse_worker_json(original_worker_intent, MAX_WORKER_REQUEST_BYTES)
        value = validate_worker_request(worker_json({**wire, "action": "run"}))
        if ("action" in wire or value["context"] != context.to_dict()
                or value["request"] != request.to_dict() or value["request_sha256"] != request.digest()
                or value["profile_sha256"] != profile_sha256):
            _fail("assignment_mismatch")
        # The caller supplies a creation-FD pin, not a current file observation.
        if (type(original_worker_intent_identity) is not tuple or len(original_worker_intent_identity) != 6
                or original_worker_intent_identity[0] != hashlib.sha256(original_worker_intent).hexdigest()
                or original_worker_intent_identity[1] != len(original_worker_intent)
                or any(type(item) is not int or item < 0 for item in original_worker_intent_identity[1:])
                or original_worker_intent_identity[3] < 1):
            _fail("creator_pin_invalid")
        original = _Original(context, request, mapping, intent, attestation, artifact,
                             original_episode_chain, episode_directory, workspace, producer_root, original_worker_intent,
                             original_worker_intent_identity, lookup, b"")
        original.baseline = original.snapshot()
        original.check_originals()
        self._originals[lookup] = original

        def registered(context_pin: NativeTrustedRegisteredContext) -> None:
            if self._closed or original.native is not None:
                _fail("binding_replayed")
            original.check_originals()
            if type(context_pin) is not NativeTrustedRegisteredContext or context_pin.publication_eligible is not False:
                _fail("registered_context_invalid")
            launch = build_trusted_bootstrap_launch(intent, attestation, artifact.descriptor)
            expected = {"run_id": intent.run_id, "parent_task_id": intent.parent_task_id,
                        "task_id": intent.task_id, "launch_id": intent.launch_id,
                        "journal_id": intent.journal_id, "intent_sha256": intent.digest(),
                        "attestation_sha256": attestation.digest(), "launch_sha256": launch.launch_sha256,
                        "bootstrap_descriptor_sha256": artifact.descriptor.descriptor_sha256,
                        "bootstrap_artifact_sha256": artifact.artifact_sha256,
                        "bootstrap_allowlist_id": artifact.allowlist_id, "artifact_path": str(artifact.path),
                        "workspace": str(workspace), "producer_root": str(producer_root)}
            if any(getattr(context_pin, key) != value for key, value in expected.items()):
                _fail("registered_context_mismatch")
            original.native = replace(context_pin)
            try:
                batch = workspace / "evolution" / "producer-batches" / intent.journal_id
                for path in (workspace, batch, Path(context_pin.producer_root), artifact.path.parent):
                    original.chains.append(DirectoryChain(path, "worker_native_context_drift"))
                original.check_native()
                record = {"schema_version": "1", "protocol": _PROTOCOL,
                          "lookup": _lookup(lookup), "mapping": mapping.to_dict(),
                          "worker_intent_identity": list(original.worker_pin),
                          **expected,
                          "registration_identity": list(context_pin.registration_file_identity),
                          "handoff_identity": list(context_pin.handoff_file_identity),
                          "deadline": parse_worker_json(context_pin.deadline_json, _MAX),
                          "deadline_binding": parse_worker_json(context_pin.deadline_binding_json, _MAX),
                          "recovery_lock_identity": list(context_pin.recovery_lock_identity), **_AUTHORITY}
                record["binding_sha256"] = _digest(record)
                raw = worker_json(record)
                if len(raw) > _MAX:
                    _fail("binding_invalid")
                original.binding_pin = _publish(original.worker_chain.fd, _PIN_NAME, raw, capture_identity=True)
                original.binding_raw = raw
                original.check_native()
            except BaseException:
                original.close()
                raise

        return registered

    def inspect(self, raw: bytes) -> dict[str, object]:
        """Explicit worker-local observation; no writes, signals, launch or renewal."""
        _lookup(raw)
        result: dict[str, object] = {"schema_version": "1", "protocol": _PROTOCOL,
                                    "lookup_sha256": hashlib.sha256(raw).hexdigest(),
                                    "status": "context_unavailable", "reason": "original_context_unavailable",
                                    "binding_sha256": None, "terminal_sha256": None,
                                    "native_process_status": None, **_AUTHORITY}
        original = None if self._closed else self._originals.get(raw)
        if original is None or original.binding_raw is None:
            return result
        try:
            original.check_native()
            native = original.native
            terminal = recover_native_trusted_attempt(
                native.workspace, intent=original.intent, attestation=original.attestation,
                artifact=original.artifact, cleanup=False,
            )
            audit = audit_native_trusted_lifecycle(
                native.workspace, intent=original.intent, attestation=original.attestation,
                artifact=original.artifact,
            )
            original.check_native()
            result["binding_sha256"] = parse_worker_json(original.binding_raw, _MAX)["binding_sha256"]
            terminal_sha = terminal.get("terminal_sha256")
            if type(terminal_sha) is str and _SHA.fullmatch(terminal_sha):
                result["terminal_sha256"] = terminal_sha
            status = terminal.get("process_status")
            if type(status) is str and status in {"exited_zero", "exited_nonzero", "cancelled", "timed_out", "unknown"}:
                result["native_process_status"] = status
            if terminal.get("reason") == "native_trusted_attempt_terminal_receipt_missing":
                result.update(status="recovery_required", reason="native_terminal_missing")
            elif audit.get("status") == "recovery_required":
                result.update(status="recovery_required", reason="native_lifecycle_unverified")
            elif audit.get("reason") == "native_trusted_lifecycle_capture_verified":
                result.update(status="lifecycle_observed", reason="native_lifecycle_observed")
            else:
                result.update(status="process_only", reason="native_process_only")
        except Exception:  # noqa: BLE001 - any failed original observation invalidates this diagnostic.
            # Drift/invalid originals supersede any observation made before failure.
            result.update(status="context_drift", reason="original_context_drift",
                          binding_sha256=None, terminal_sha256=None, native_process_status=None)
        return result

    def close(self) -> None:
        self._closed = True
        for original in self._originals.values():
            original.close()
        self._originals.clear()
