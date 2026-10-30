"""Authenticated original-context persistence for explicit worker-local inspection.

This opt-in writer runs inside the original pre-gate observer. Restore requires
an independently retained original anchor, installed key and assignment; neither
a signed current file nor the old diagnostic pin can supply those originals.
No live Popen/FD, gate, deadline, launch, cleanup or publication authority returns.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

from ._candidate_workspace_io import DirectoryChain
from .external_worker_native_lifecycle import (
    WorkerNativeLifecycleResolver,
    WorkerNativeTaskMapping,
    _lookup,
    _Original,
)
from .external_worker_origin import WorkerOriginContext, WorkerOriginKey
from .external_worker_wrapper import (
    _publish,
    _read_at,
    parse_worker_json,
    validate_worker_request,
    worker_json,
)
from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_attempt import NativeTrustedRegisteredContext
from .producer_bootstrap import TrustedBootstrapDescriptor, build_trusted_bootstrap_launch
from .producer_bundle_deadline import _boot_id
from .producer_launcher import (
    parse_producer_launch_attestation,
    parse_producer_launch_intent,
    verify_producer_launch_attestation,
)
from .rsi_gateway import SolverRequest

_DOMAIN = b"lunar-worker-native-restart-v1\x00"
_PROTOCOL = "lunar-worker-native-restart-v1"
_PACKET = "native-restart-packet.json"
_COMPLETE = "native-restart-complete.json"
_MAX = 2 * 1024 * 1024
_IDENTITY = ("worker_id", "host_id", "host_boot_id", "key_id")
_NATIVE_BYTES = ("registration_json", "handoff_json", "deadline_json", "deadline_binding_json")
_NATIVE_PINS = ("recovery_lock_identity", "registration_file_identity", "handoff_file_identity")
_AUTHORITY = {"publication_eligible": False, "native_success": False,
              "remote_cleanup_verified": False, "publication_authority": False}


class WorkerNativeRestartError(ValueError):
    """Fixed-code failure; full context/attestation/key never enters diagnostics."""


def _fail(code: str) -> None:
    raise WorkerNativeRestartError("worker_native_restart_" + code)


def _object(value: object, names: set | frozenset) -> dict:
    if type(value) is not dict or set(value) != names:
        _fail("schema_invalid")
    return value


def _digest(value: object) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        _fail("digest_invalid")
    return value


def _path(value: object) -> Path:
    if (type(value) is not str or not value.startswith("/") or len(value) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or len(value.split("/")) > 64
            or any(part in {"", ".", ".."} for part in value.split("/")[1:])):
        _fail("path_invalid")
    return Path(value)


def _file_pin(value: object) -> tuple[str | int, ...]:
    if (type(value) not in {list, tuple} or len(value) != 6
            or any(type(item) is not int or not 0 <= item < 2**64 for item in value[1:])
            or value[3] < 1 or not 0 < value[1] <= _MAX):
        _fail("creator_pin_invalid")
    _digest(value[0])
    return tuple(value)


def _directory_pin(fd: int) -> list[int]:
    info = os.fstat(fd)
    return [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid]


def _chain_pins(chain: DirectoryChain) -> list[list[int]]:
    chain.check()
    return [_directory_pin(fd) for fd in chain.fds]


def _verify_chain(chain: DirectoryChain, pins: object) -> None:
    if (type(pins) is not list or not 1 <= len(pins) <= 64
            or any(type(row) is not list or len(row) != 5
                   or any(type(item) is not int or not 0 <= item < 2**64 for item in row)
                   for row in pins)
            or _chain_pins(chain) != pins):
        _fail("directory_drift")


def _bound(chain: DirectoryChain, name: str, pin: tuple[str | int, ...]) -> bytes:
    def check() -> None:
        chain.check()
        info = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if (info.st_size, info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns) != pin[1:]:
            _fail("creator_pin_drift")

    check()
    raw = _read_at(chain.fd, name, _MAX)
    if len(raw) != pin[1] or hashlib.sha256(raw).hexdigest() != pin[0]:
        _fail("creator_pin_drift")
    check()
    return raw


def _key(key: object) -> WorkerOriginKey:
    if type(key) is not WorkerOriginKey:
        _fail("key_invalid")
    key.__post_init__()
    if key.revoked:
        _fail("key_revoked")
    if key.host_boot_id != _boot_id():
        _fail("boot_drift")
    return key


def _sign(value: dict, key: WorkerOriginKey) -> bytes:
    unsigned = worker_json(value)
    mac = hmac.new(key.secret_key, _DOMAIN + unsigned, hashlib.sha256).hexdigest()
    raw = worker_json({**value, "mac_sha256": mac})
    if len(raw) > _MAX:
        _fail("packet_bounds")
    return raw


def _verified(raw: bytes, key: WorkerOriginKey, names: set) -> dict:
    parsed = _object(parse_worker_json(raw, _MAX), names | {"mac_sha256"})
    unsigned = {name: value for name, value in parsed.items() if name != "mac_sha256"}
    expected = hmac.new(key.secret_key, _DOMAIN + worker_json(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(_digest(parsed["mac_sha256"]), expected):
        _fail("authentication_refused")
    if (parsed["protocol"] != _PROTOCOL
            or any(parsed[name] != getattr(key, name) for name in _IDENTITY)):
        _fail("installed_identity_drift")
    return unsigned


def _native_wire(context: NativeTrustedRegisteredContext) -> dict:
    result = {item.name: getattr(context, item.name) for item in fields(NativeTrustedRegisteredContext)}
    for name in _NATIVE_BYTES:
        result[name] = parse_worker_json(result[name], _MAX)
    for name in _NATIVE_PINS:
        result[name] = list(result[name])
    return result


def _native(value: object) -> NativeTrustedRegisteredContext:
    row = dict(_object(value, {item.name for item in fields(NativeTrustedRegisteredContext)}))
    if row["publication_eligible"] is not False:
        _fail("authority_refused")
    for name in _NATIVE_BYTES:
        if type(row[name]) is not dict:
            _fail("schema_invalid")
        row[name] = worker_json(row[name])
    for name in _NATIVE_PINS:
        if name == "recovery_lock_identity":
            pin = row[name]
            if (type(pin) is not list or len(pin) != 2
                    or any(type(item) is not int or not 0 <= item < 2**64 for item in pin)
                    or pin[1] < 1):
                _fail("creator_pin_invalid")
            row[name] = tuple(pin)
        else:
            row[name] = _file_pin(row[name])
    for name in ("workspace", "producer_root", "artifact_path"):
        _path(row[name])
    for name in ("launch_sha256", "intent_sha256", "attestation_sha256",
                 "bootstrap_descriptor_sha256", "bootstrap_artifact_sha256"):
        _digest(row[name])
    return NativeTrustedRegisteredContext(**row)


@dataclass(frozen=True, slots=True)
class WorkerNativeRestartAnchor:
    """Original packet/completion creator pins retained outside the packet store.

    The trusted caller must preserve these bytes independently across restart.
    There is intentionally no public JSON/selector/from-disk anchor loader. A
    current stat or an HMAC-valid packet must never create this trust parameter.
    """

    canonical_bytes: bytes = field(repr=False)


class WorkerNativeRestartWriter:
    """One explicit original pre-gate writer; not a public worker capability."""

    def __init__(self, *, key: WorkerOriginKey, profile_sha256: str) -> None:
        self._key = _key(key)
        self._key_baseline = tuple(getattr(key, name) for name in _IDENTITY)
        self._secret_pin = hashlib.sha256(key.secret_key).digest()
        self._profile = _digest(profile_sha256)
        self._attempted = False
        self._anchor: WorkerNativeRestartAnchor | None = None

    @property
    def anchor(self) -> WorkerNativeRestartAnchor | None:
        return self._anchor

    def persist(self, original: _Original) -> None:
        """Called only by the original native observer before target gate release."""
        try:
            if self._attempted or type(original) is not _Original:
                _fail("writer_replayed")
            self._attempted = True
            key = _key(self._key)
            if (tuple(getattr(key, name) for name in _IDENTITY) != self._key_baseline
                    or not hmac.compare_digest(hashlib.sha256(key.secret_key).digest(), self._secret_pin)):
                _fail("key_drift")
            original.check_native()
            wire = parse_worker_json(original.worker_raw, _MAX)
            lookup = _lookup(original.lookup_raw)
            if (lookup["profile_sha256"] != self._profile
                    or any(wire[name] != getattr(key, name) for name in _IDENTITY)
                    or original.native is None or original.binding_raw is None
                    or original.binding_pin is None):
                _fail("original_identity_mismatch")
            directory_pins = [_chain_pins(original.worker_chain),
                              *(_chain_pins(chain) for chain in original.chains)]
            common = {"protocol": _PROTOCOL, **{name: getattr(key, name) for name in _IDENTITY},
                      "profile_sha256": self._profile, "lookup_sha256": hashlib.sha256(original.lookup_raw).hexdigest()}
            packet = {**common, "kind": "original-context", "original": parse_worker_json(original.baseline, _MAX),
                      "native": _native_wire(original.native), "worker_path": str(original.worker_path),
                      "worker_intent": wire, "worker_intent_identity": list(original.worker_pin),
                      "lookup": lookup, "binding": parse_worker_json(original.binding_raw, _MAX),
                      "binding_identity": list(original.binding_pin), "directory_pins": directory_pins,
                      **_AUTHORITY}
            packet_raw = _sign(packet, key)
            packet_pin = _publish(original.worker_chain.fd, _PACKET, packet_raw, capture_identity=True)
            packet_pin = _file_pin(packet_pin)
            original.check_native()
            for chain, pins in zip([original.worker_chain, *original.chains], directory_pins, strict=True):
                _verify_chain(chain, pins)
            if _bound(original.worker_chain, _PACKET, packet_pin) != packet_raw:
                _fail("creator_pin_drift")
            complete_raw = _sign({**common, "kind": "complete", "packet_identity": list(packet_pin), **_AUTHORITY}, key)
            complete_pin = _file_pin(_publish(original.worker_chain.fd, _COMPLETE, complete_raw, capture_identity=True))
            if _bound(original.worker_chain, _COMPLETE, complete_pin) != complete_raw:
                _fail("creator_pin_drift")
            original.check_native()
            if _native_wire(original.native) != packet["native"]:
                _fail("original_context_drift")
            for chain, pins in zip([original.worker_chain, *original.chains], directory_pins, strict=True):
                _verify_chain(chain, pins)
            _key(key)
            if (tuple(getattr(key, name) for name in _IDENTITY) != self._key_baseline
                    or not hmac.compare_digest(hashlib.sha256(key.secret_key).digest(), self._secret_pin)):
                _fail("key_drift")
            # An independent original anchor is delivered only after both create-only
            # files and their directory have fsynced. Neither file self-pins itself.
            self._anchor = WorkerNativeRestartAnchor(worker_json({
                **common, "kind": "trusted-original-anchor", "worker_path": str(original.worker_path),
                "worker_chain": directory_pins[0], "packet_identity": list(packet_pin),
                "complete_identity": list(complete_pin),
            }))
        except Exception:  # noqa: BLE001 - every persistence failure must refuse the original gate without private details.
            self._anchor = None
            raise WorkerNativeRestartError("worker_native_restart_persistence_refused") from None


def _report(lookup: bytes, reason: str) -> dict:
    return {"schema_version": "1", "protocol": _PROTOCOL,
            "lookup_sha256": hashlib.sha256(lookup).hexdigest() if type(lookup) is bytes and len(lookup) <= 8192 else None,
            "status": "context_unavailable", "reason": reason,
            "binding_sha256": None, "terminal_sha256": None, "native_process_status": None,
            **_AUTHORITY}


def inspect_native_restart(
    anchor: WorkerNativeRestartAnchor, raw: bytes, *, key: WorkerOriginKey,
    expected_context: WorkerOriginContext, expected_mapping: WorkerNativeTaskMapping,
    expected_profile_sha256: str,
) -> dict:
    """Restore only authenticated original data, then actually run read-only recovery.

    No path, key, context, mapping or original anchor is accepted from the public
    lookup. Its independently trusted parameters come from the installed caller.
    """
    chains: list[DirectoryChain] = []
    restored: _Original | None = None
    resolver: WorkerNativeLifecycleResolver | None = None
    try:
        lookup = _lookup(raw)
        key = _key(key)
        key_identity = tuple(getattr(key, name) for name in _IDENTITY)
        secret_pin = hashlib.sha256(key.secret_key).digest()
        if (type(anchor) is not WorkerNativeRestartAnchor
                or type(anchor.canonical_bytes) is not bytes
                or type(expected_context) is not WorkerOriginContext
                or type(expected_mapping) is not WorkerNativeTaskMapping):
            _fail("original_anchor_required")
        expected_context.__post_init__()
        expected_mapping.__post_init__()
        original_anchor_raw = anchor.canonical_bytes
        original_context_raw = worker_json(expected_context.to_dict())
        original_mapping_raw = worker_json(expected_mapping.to_dict())
        expected_profile = _digest(expected_profile_sha256)
        trusted = _object(parse_worker_json(anchor.canonical_bytes, 65536), {
            "protocol", *_IDENTITY, "profile_sha256", "lookup_sha256", "kind", "worker_path",
            "worker_chain", "packet_identity", "complete_identity",
        })
        if (trusted["protocol"] != _PROTOCOL or trusted["kind"] != "trusted-original-anchor"
                or any(trusted[name] != getattr(key, name) for name in _IDENTITY)
                or trusted["profile_sha256"] != expected_profile
                or trusted["lookup_sha256"] != hashlib.sha256(raw).hexdigest()
                or lookup["profile_sha256"] != expected_profile
                or lookup["context"] != expected_context.to_dict()):
            _fail("original_anchor_mismatch")
        worker_path = _path(trusted["worker_path"])
        worker_chain = DirectoryChain(worker_path, "worker_native_restart_directory_drift")
        chains.append(worker_chain)
        _verify_chain(worker_chain, trusted["worker_chain"])
        packet_pin, complete_pin = _file_pin(trusted["packet_identity"]), _file_pin(trusted["complete_identity"])
        packet_raw = _bound(worker_chain, _PACKET, packet_pin)
        complete_raw = _bound(worker_chain, _COMPLETE, complete_pin)
        common_names = {"protocol", *_IDENTITY, "profile_sha256", "lookup_sha256", "kind"}
        packet = _verified(packet_raw, key, common_names | {
            "original", "native", "worker_path", "worker_intent", "worker_intent_identity", "lookup",
            "binding", "binding_identity", "directory_pins", *_AUTHORITY,
        })
        complete = _verified(complete_raw, key, common_names | {"packet_identity", *_AUTHORITY})
        for row, kind in ((packet, "original-context"), (complete, "complete")):
            if (row["kind"] != kind or row["profile_sha256"] != expected_profile
                    or row["lookup_sha256"] != trusted["lookup_sha256"]
                    or any(row[name] is not False for name in _AUTHORITY)):
                _fail("binding_mismatch")
        if (complete["packet_identity"] != list(packet_pin) or packet["lookup"] != lookup
                or packet["worker_path"] != str(worker_path)
                or packet["directory_pins"][0] != trusted["worker_chain"]):
            _fail("binding_mismatch")
        worker_wire = packet["worker_intent"]
        if type(worker_wire) is not dict or "action" in worker_wire:
            _fail("schema_invalid")
        validate_worker_request(worker_json({**worker_wire, "action": "run"}))
        if any(worker_wire[name] != getattr(key, name) for name in _IDENTITY):
            _fail("installed_identity_drift")
        snapshot = _object(packet["original"], {"context", "request", "mapping", "workspace", "producer_root",
                                                "intent", "attestation", "artifact"})
        context = WorkerOriginContext.from_dict(snapshot["context"])
        request = SolverRequest.from_dict(snapshot["request"])
        mapping = WorkerNativeTaskMapping(**_object(snapshot["mapping"], set(WorkerNativeTaskMapping.__slots__)))
        if context != expected_context or mapping != expected_mapping or request.digest() != lookup["request_sha256"]:
            _fail("assignment_mismatch")
        intent = parse_producer_launch_intent(snapshot["intent"])
        attestation = parse_producer_launch_attestation(snapshot["attestation"])
        verify_producer_launch_attestation(intent, attestation)
        saved_artifact = _object(snapshot["artifact"], {
            "path", "source_sha256", "artifact_sha256", "compiler", "platform_execution_mode", "allowlist_id", "descriptor",
        })
        descriptor = TrustedBootstrapDescriptor(**_object(saved_artifact["descriptor"], {
            item.name for item in fields(TrustedBootstrapDescriptor)}))
        artifact_path = _path(saved_artifact["path"])
        if (saved_artifact["artifact_sha256"] != descriptor.bootstrap_sha256
                or saved_artifact["platform_execution_mode"] != descriptor.platform_execution_mode):
            _fail("artifact_drift")
        artifact = NativeBootstrapArtifact(path=artifact_path, **{
            name: value for name, value in saved_artifact.items() if name not in {"path", "descriptor"}
        }, descriptor=descriptor)
        native = _native(packet["native"])
        launch = build_trusted_bootstrap_launch(intent, attestation, descriptor)
        if native.launch_sha256 != launch.launch_sha256:
            _fail("native_binding_mismatch")
        workspace, producer_root = _path(snapshot["workspace"]), _path(snapshot["producer_root"])
        if (native.workspace != str(workspace) or native.producer_root != str(producer_root)
                or native.artifact_path != str(artifact_path)
                or (native.run_id, native.parent_task_id, native.task_id) != (
                    mapping.native_run_id, mapping.native_parent_task_id, mapping.native_task_id)
                or any(getattr(native, name) != value for name, value in {
                    "launch_id": intent.launch_id, "journal_id": intent.journal_id,
                    "intent_sha256": intent.digest(), "attestation_sha256": attestation.digest(),
                    "bootstrap_descriptor_sha256": descriptor.descriptor_sha256,
                    "bootstrap_artifact_sha256": artifact.artifact_sha256,
                    "bootstrap_allowlist_id": artifact.allowlist_id,
                }.items())):
            _fail("native_binding_mismatch")
        binding_raw = worker_json(packet["binding"])
        baseline = worker_json(snapshot)
        restored = _Original(context, request, mapping, intent, attestation, artifact, worker_chain,
                             worker_path, workspace, producer_root, worker_json(packet["worker_intent"]),
                             _file_pin(packet["worker_intent_identity"]), raw, baseline,
                             native=native, binding_raw=binding_raw, binding_pin=_file_pin(packet["binding_identity"]))
        roots = (workspace, workspace / "evolution" / "producer-batches" / intent.journal_id,
                 producer_root, artifact_path.parent)
        pins = packet["directory_pins"]
        if type(pins) is not list or len(pins) != 5:
            _fail("schema_invalid")
        for path, original_pins in zip(roots, pins[1:], strict=True):
            chain = DirectoryChain(path, "worker_native_restart_directory_drift")
            chains.append(chain)
            restored.chains.append(chain)
            _verify_chain(chain, original_pins)
        # Reuse original read-only inspection rather than preparing/registering or
        # fabricating a late original. Every file is compared to the signed creator pin.
        restored.check_native()
        resolver = WorkerNativeLifecycleResolver()
        resolver._originals[raw] = restored
        result = resolver.inspect(raw)
        if (anchor.canonical_bytes != original_anchor_raw
                or worker_json(expected_context.to_dict()) != original_context_raw
                or worker_json(expected_mapping.to_dict()) != original_mapping_raw
                or _native_wire(native) != packet["native"]):
            _fail("original_context_drift")
        for chain, original_pins in zip(chains, packet["directory_pins"], strict=True):
            _verify_chain(chain, original_pins)
        if (_bound(worker_chain, _PACKET, packet_pin) != packet_raw
                or _bound(worker_chain, _COMPLETE, complete_pin) != complete_raw):
            _fail("creator_pin_drift")
        _key(key)
        if (tuple(getattr(key, name) for name in _IDENTITY) != key_identity
                or not hmac.compare_digest(hashlib.sha256(key.secret_key).digest(), secret_pin)):
            _fail("key_drift")
        result["restart_context_authenticated"] = True
        return result
    except Exception:  # noqa: BLE001 - malformed or drifting private context must return only a bounded fail-closed report.
        return _report(raw, "original_restart_context_unavailable_or_drift")
    finally:
        # Own these newly reopened chains only; never close the caller's original
        # writer chains. Avoid closing them twice through the temporary resolver.
        if resolver is not None:
            resolver._originals.clear()
        if restored is not None:
            restored.chains.clear()
        for chain in reversed(chains):
            chain.close()
