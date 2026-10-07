"""Provider-free trusted producer bootstrap handshake.

This module models the ordering boundary for a future Lunar-owned bootstrap runtime.  It does
not spawn a producer.  The state machine accepts only bounded, canonical handshake frames and
keeps a cooperative declaration separate from a trusted bootstrap observation.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .native_deadline_binding import (
    NATIVE_CONSUMPTION_PROTOCOL,
    NativeDeadlineBindingError,
    validate_native_deadline_binding,
)
from .producer_launcher import (
    MAX_OUTPUT_BYTES,
    ProducerLaunchAttestation,
    ProducerLaunchError,
    ProducerLaunchIntent,
    parse_producer_launch_attestation,
    parse_producer_launch_intent,
    verify_producer_launch_attestation,
)
from .producer_process import PRODUCER_PROCESS_PROTOCOL

TRUSTED_BOOTSTRAP_PROTOCOL = "lunar-trusted-producer-bootstrap-v1"
TRUSTED_BOOTSTRAP_SCHEMA_VERSION = "1"
MAX_BOOTSTRAP_PAYLOAD_BYTES = 64 * 1024
MAX_BOOTSTRAP_SEQUENCE = 4
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_KINDS = frozenset({"bootstrap_ready", "target_started", "target_start_failed", "terminal"})
_STATUSES = frozenset({"passed", "failed", "unknown"})


class ProducerBootstrapError(ValueError):
    """Fixed-code bootstrap protocol failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ProducerBootstrapError(code)


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProducerBootstrapError("producer_bootstrap_canonical_invalid") from exc
    if len(encoded) > MAX_BOOTSTRAP_PAYLOAD_BYTES:
        _fail("producer_bootstrap_payload_too_large")
    return encoded


def _digest_without(value: Mapping[str, object], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in items:
        if key in result:
            _fail("producer_bootstrap_duplicate_key")
        result[key] = item
    return result


def _strict_json(value: object) -> object:
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProducerBootstrapError("producer_bootstrap_json_invalid") from exc
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_BOOTSTRAP_PAYLOAD_BYTES:
        _fail("producer_bootstrap_json_invalid")
    try:
        return json.loads(value, object_pairs_hook=_pairs, parse_constant=lambda _: _fail("producer_bootstrap_json_invalid"))
    except ProducerBootstrapError:
        raise
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProducerBootstrapError("producer_bootstrap_json_invalid") from exc


def _object(value: object, fields: frozenset[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(code)
    return value


def _id(value: object, code: str = "producer_bootstrap_identity_invalid") -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _sha(value: object, code: str = "producer_bootstrap_digest_invalid") -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        _fail(code)
    return value


def _int(value: object, *, minimum: int, maximum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _fail(code)
    return value


_DESCRIPTOR_FIELDS = frozenset({
    "schema_version", "protocol", "implementation_version", "bootstrap_sha256", "size",
    "device", "inode", "mtime_ns", "ctime_ns", "allowlist_id", "platform_execution_mode",
    "descriptor_sha256",
})


@dataclass(frozen=True, slots=True)
class TrustedBootstrapDescriptor:
    implementation_version: str
    bootstrap_sha256: str
    size: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int
    allowlist_id: str
    platform_execution_mode: str
    descriptor_sha256: str | None = None
    schema_version: str = TRUSTED_BOOTSTRAP_SCHEMA_VERSION
    protocol: str = TRUSTED_BOOTSTRAP_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != TRUSTED_BOOTSTRAP_SCHEMA_VERSION or self.protocol != TRUSTED_BOOTSTRAP_PROTOCOL:
            _fail("producer_bootstrap_schema_invalid")
        _id(self.implementation_version)
        _sha(self.bootstrap_sha256)
        for value in (self.size, self.device, self.inode, self.mtime_ns, self.ctime_ns):
            _int(value, minimum=0, maximum=2**63 - 1, code="producer_bootstrap_identity_invalid")
        _id(self.allowlist_id)
        if self.platform_execution_mode not in {"darwin-immutable-snapshot", "linux-fd-bound", "fixture-only"}:
            _fail("producer_bootstrap_platform_mode_invalid")
        if self.descriptor_sha256 is not None and self.descriptor_sha256 != self.digest():
            _fail("producer_bootstrap_digest_mismatch")
        if self.descriptor_sha256 is None:
            object.__setattr__(self, "descriptor_sha256", self.digest())

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "implementation_version": self.implementation_version, "bootstrap_sha256": self.bootstrap_sha256,
            "size": self.size, "device": self.device, "inode": self.inode,
            "mtime_ns": self.mtime_ns, "ctime_ns": self.ctime_ns, "allowlist_id": self.allowlist_id,
            "platform_execution_mode": self.platform_execution_mode,
        }
        if include_digest:
            value["descriptor_sha256"] = self.descriptor_sha256
        return value

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "descriptor_sha256")


_LAUNCH_FIELDS = frozenset({
    "schema_version", "protocol", "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
    "intent_sha256", "attestation_sha256", "bootstrap_descriptor_sha256", "target_executable_identity",
    "gate_protocol", "gate_nonce", "launch_sha256",
})


@dataclass(frozen=True, slots=True)
class TrustedBootstrapLaunch:
    launch_id: str
    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    intent_sha256: str
    attestation_sha256: str
    bootstrap_descriptor_sha256: str
    target_executable_identity: str
    gate_protocol: str
    gate_nonce: str
    launch_sha256: str | None = None
    schema_version: str = TRUSTED_BOOTSTRAP_SCHEMA_VERSION
    protocol: str = TRUSTED_BOOTSTRAP_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != TRUSTED_BOOTSTRAP_SCHEMA_VERSION or self.protocol != TRUSTED_BOOTSTRAP_PROTOCOL:
            _fail("producer_bootstrap_schema_invalid")
        for value in (self.launch_id, self.journal_id, self.run_id, self.parent_task_id, self.task_id, self.gate_nonce):
            _id(value)
        for value in (self.intent_sha256, self.attestation_sha256, self.bootstrap_descriptor_sha256, self.target_executable_identity):
            _sha(value)
        if self.gate_protocol != "fd-read-one-byte-v1":
            _fail("producer_bootstrap_gate_protocol_invalid")
        if self.launch_sha256 is not None and self.launch_sha256 != self.digest():
            _fail("producer_bootstrap_digest_mismatch")
        if self.launch_sha256 is None:
            object.__setattr__(self, "launch_sha256", self.digest())

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "launch_id": self.launch_id, "journal_id": self.journal_id, "run_id": self.run_id,
            "parent_task_id": self.parent_task_id, "task_id": self.task_id,
            "intent_sha256": self.intent_sha256, "attestation_sha256": self.attestation_sha256,
            "bootstrap_descriptor_sha256": self.bootstrap_descriptor_sha256,
            "target_executable_identity": self.target_executable_identity,
            "gate_protocol": self.gate_protocol, "gate_nonce": self.gate_nonce,
        }
        if include_digest:
            value["launch_sha256"] = self.launch_sha256
        return value

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "launch_sha256")


def build_trusted_bootstrap_launch(
    intent: object,
    attestation: object,
    descriptor: TrustedBootstrapDescriptor,
    *,
    gate_nonce: str | None = None,
) -> TrustedBootstrapLaunch:
    """Project one validated producer launch into the trusted-bootstrap contract.

    This is an identity-only adapter.  It does not consume the attestation, inspect the
    executable, or start a process.  Production callers must provide a descriptor backed by
    the platform's exact-byte execution mode; the fixture-only descriptor is intentionally
    rejected here.
    """
    if not isinstance(descriptor, TrustedBootstrapDescriptor):
        _fail("producer_bootstrap_descriptor_invalid")
    expected_mode = (
        "darwin-immutable-snapshot" if sys.platform == "darwin"
        else "linux-fd-bound" if sys.platform.startswith("linux") else None
    )
    if descriptor.platform_execution_mode == "fixture-only":
        _fail("producer_bootstrap_production_mode_required")
    if expected_mode is None or descriptor.platform_execution_mode != expected_mode:
        _fail("producer_bootstrap_platform_mode_mismatch")

    # Keep the producer-launch parser and verifier as the single source of truth for the
    # parent/child/task and executable-stat tuple. Translate failures to fixed bootstrap codes.
    if not isinstance(intent, ProducerLaunchIntent):
        try:
            intent = parse_producer_launch_intent(intent)
        except (ProducerLaunchError, TypeError, ValueError) as exc:
            raise ProducerBootstrapError("producer_bootstrap_launch_intent_invalid") from exc
    if not isinstance(attestation, ProducerLaunchAttestation):
        try:
            attestation = parse_producer_launch_attestation(attestation)
        except (ProducerLaunchError, TypeError, ValueError) as exc:
            raise ProducerBootstrapError("producer_bootstrap_launch_attestation_invalid") from exc
    try:
        verify_producer_launch_attestation(intent, attestation)
    except (ProducerLaunchError, TypeError, ValueError) as exc:
        raise ProducerBootstrapError("producer_bootstrap_launch_binding_mismatch") from exc

    if gate_nonce is None:
        gate_nonce = attestation.nonce
    else:
        _id(gate_nonce, "producer_bootstrap_gate_nonce_invalid")
        if gate_nonce != attestation.nonce:
            _fail("producer_bootstrap_gate_nonce_mismatch")
    return TrustedBootstrapLaunch(
        launch_id=intent.launch_id,
        journal_id=intent.journal_id,
        run_id=intent.run_id,
        parent_task_id=intent.parent_task_id,
        task_id=intent.task_id,
        intent_sha256=intent.intent_sha256 or intent.digest(),
        attestation_sha256=attestation.attestation_sha256 or attestation.digest(),
        bootstrap_descriptor_sha256=descriptor.descriptor_sha256 or descriptor.digest(),
        target_executable_identity=attestation.executable_sha256,
        gate_protocol="fd-read-one-byte-v1",
        gate_nonce=gate_nonce,
    )


_REGISTRATION_FIELDS = frozenset({
    "schema_version", "protocol", "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
    "intent_sha256", "attestation_sha256", "bootstrap_descriptor_sha256", "target_executable_identity",
    "pid", "pgid", "gate_protocol", "registration_sha256",
})


@dataclass(frozen=True, slots=True)
class TrustedBootstrapRegistration:
    """Canonical Feature 156-style process registration for one bootstrap launch.

    This DTO is intentionally provider-free.  It binds the process identity recorded before
    gate release to every identity carried by :class:`TrustedBootstrapLaunch`; it does not
    inspect a process, read a registration file, or authorize a scheduler launch.
    """

    launch_id: str
    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    intent_sha256: str
    attestation_sha256: str
    bootstrap_descriptor_sha256: str
    target_executable_identity: str
    pid: int
    pgid: int
    gate_protocol: str
    registration_sha256: str | None = None
    schema_version: str = TRUSTED_BOOTSTRAP_SCHEMA_VERSION
    protocol: str = TRUSTED_BOOTSTRAP_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != TRUSTED_BOOTSTRAP_SCHEMA_VERSION or self.protocol != TRUSTED_BOOTSTRAP_PROTOCOL:
            _fail("producer_bootstrap_registration_schema_invalid")
        for value in (self.launch_id, self.journal_id, self.run_id, self.parent_task_id, self.task_id):
            _id(value, "producer_bootstrap_registration_identity_invalid")
        for value in (
            self.intent_sha256,
            self.attestation_sha256,
            self.bootstrap_descriptor_sha256,
            self.target_executable_identity,
        ):
            _sha(value, "producer_bootstrap_registration_digest_invalid")
        _int(self.pid, minimum=2, maximum=2**63 - 1, code="producer_bootstrap_registration_process_identity_invalid")
        _int(self.pgid, minimum=2, maximum=2**63 - 1, code="producer_bootstrap_registration_process_identity_invalid")
        if self.gate_protocol != "fd-read-one-byte-v1":
            _fail("producer_bootstrap_registration_gate_protocol_invalid")
        if self.registration_sha256 is not None:
            _sha(self.registration_sha256, "producer_bootstrap_registration_digest_invalid")
            if self.registration_sha256 != self.digest():
                _fail("producer_bootstrap_registration_digest_mismatch")
        else:
            object.__setattr__(self, "registration_sha256", self.digest())

    @classmethod
    def from_launch(cls, launch: TrustedBootstrapLaunch, *, pid: int, pgid: int) -> TrustedBootstrapRegistration:
        """Build the exact registration payload for ``launch`` and one process identity."""
        if not isinstance(launch, TrustedBootstrapLaunch):
            _fail("producer_bootstrap_registration_launch_invalid")
        return cls(
            launch_id=launch.launch_id,
            journal_id=launch.journal_id,
            run_id=launch.run_id,
            parent_task_id=launch.parent_task_id,
            task_id=launch.task_id,
            intent_sha256=launch.intent_sha256,
            attestation_sha256=launch.attestation_sha256,
            bootstrap_descriptor_sha256=launch.bootstrap_descriptor_sha256,
            target_executable_identity=launch.target_executable_identity,
            pid=pid,
            pgid=pgid,
            gate_protocol=launch.gate_protocol,
        )

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "launch_id": self.launch_id,
            "journal_id": self.journal_id,
            "run_id": self.run_id,
            "parent_task_id": self.parent_task_id,
            "task_id": self.task_id,
            "intent_sha256": self.intent_sha256,
            "attestation_sha256": self.attestation_sha256,
            "bootstrap_descriptor_sha256": self.bootstrap_descriptor_sha256,
            "target_executable_identity": self.target_executable_identity,
            "pid": self.pid,
            "pgid": self.pgid,
            "gate_protocol": self.gate_protocol,
        }
        if include_digest:
            value["registration_sha256"] = self.registration_sha256
        return value

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "registration_sha256")

    def bind_to(self, launch: TrustedBootstrapLaunch) -> TrustedBootstrapRegistration:
        """Require every launch-owned field to match exactly."""
        if not isinstance(launch, TrustedBootstrapLaunch):
            _fail("producer_bootstrap_registration_launch_invalid")
        for field in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
            "attestation_sha256", "bootstrap_descriptor_sha256", "target_executable_identity", "gate_protocol",
        ):
            if getattr(self, field) != getattr(launch, field):
                _fail("producer_bootstrap_registration_binding_mismatch")
        return self


def build_trusted_bootstrap_registration(
    launch: TrustedBootstrapLaunch, *, pid: int, pgid: int,
) -> TrustedBootstrapRegistration:
    """Build one digest-bound registration DTO without process or filesystem I/O."""
    return TrustedBootstrapRegistration.from_launch(launch, pid=pid, pgid=pgid)


def parse_trusted_bootstrap_registration(
    value: object, *, launch: TrustedBootstrapLaunch | None = None,
) -> TrustedBootstrapRegistration:
    """Parse and optionally bind one canonical registration payload."""
    encoded: bytes | None = None
    if isinstance(value, (str, bytes, bytearray)):
        encoded = bytes(value, "utf-8") if isinstance(value, str) else bytes(value)
        value = _strict_json(encoded)
    raw = _object(value, _REGISTRATION_FIELDS, "producer_bootstrap_registration_schema_invalid")
    if encoded is not None and _canonical(raw) != encoded:
        _fail("producer_bootstrap_registration_noncanonical")
    try:
        registration = TrustedBootstrapRegistration(**raw)
    except ProducerBootstrapError:
        raise
    except (TypeError, ValueError) as exc:
        raise ProducerBootstrapError("producer_bootstrap_registration_schema_invalid") from exc
    if launch is not None:
        registration.bind_to(launch)
    _sha(raw["registration_sha256"], "producer_bootstrap_registration_digest_invalid")
    return registration


def verify_trusted_bootstrap_registration(
    launch: TrustedBootstrapLaunch, value: object,
) -> TrustedBootstrapRegistration:
    """Validate a registration payload against its exact trusted launch identity."""
    return parse_trusted_bootstrap_registration(value, launch=launch)


_FEATURE156_BOOTSTRAP_REGISTRATION_FIELDS = frozenset({
    "schema_version", "protocol", "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
    "intent_sha256", "attestation_sha256", "consumption_sha256", "executable_identity",
    "owner_identity", "owner_identity_sha256", "execution_binding",
    "execution_snapshot_relative_path", "execution_snapshot_sha256", "execution_snapshot_size",
    "pid", "pgid", "recovery_lock_protocol", "recovery_lock_device", "recovery_lock_inode",
    "gate_protocol", "registered_at_unix_ns", "registration_sha256",
    "launch_sha256", "bootstrap_descriptor_sha256", "target_executable_identity",
    "target_execution_binding", "target_execution_snapshot_relative_path",
    "target_execution_snapshot_sha256", "target_execution_snapshot_size",
})

_FEATURE156_CONSUMPTION_FIELDS = frozenset({
    "schema_version", "protocol", "consumption_id", "launch_id", "journal_id", "run_id",
    "parent_task_id", "task_id", "intent_sha256", "attestation_sha256", "nonce",
    "executable_identity", "consumption_sha256",
})
_NATIVE_CONSUMPTION_V2_FIELDS = _FEATURE156_CONSUMPTION_FIELDS | {"deadline_binding"}


def _parse_trusted_bootstrap_consumption(value: object) -> dict[str, object]:
    """Parse the exact legacy claim or the native claim with its frozen deadline pin."""
    encoded: bytes | None = None
    if isinstance(value, (str, bytes, bytearray)):
        encoded = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        value = _strict_json(encoded)
    if not isinstance(value, dict):
        _fail("producer_bootstrap_attempt_consumption_schema_invalid")
    is_native = value.get("schema_version") == "2" and value.get("protocol") == NATIVE_CONSUMPTION_PROTOCOL
    fields = _NATIVE_CONSUMPTION_V2_FIELDS if is_native else _FEATURE156_CONSUMPTION_FIELDS
    claim = _object(value, fields, "producer_bootstrap_attempt_consumption_schema_invalid")
    if encoded is not None and _canonical(claim) != encoded:
        _fail("producer_bootstrap_attempt_consumption_noncanonical")
    if is_native:
        # Bound and detach object input too; a caller cannot retain a mutable nested pin.
        claim = _strict_json(_canonical(claim))
        try:
            claim["deadline_binding"] = validate_native_deadline_binding(claim["deadline_binding"])
        except NativeDeadlineBindingError as exc:
            raise ProducerBootstrapError("producer_bootstrap_attempt_deadline_binding_invalid") from exc
    elif claim["schema_version"] != "1" or claim["protocol"] != PRODUCER_PROCESS_PROTOCOL:
        _fail("producer_bootstrap_attempt_consumption_schema_invalid")
    return claim


def verify_trusted_bootstrap_process_registration(
    launch: TrustedBootstrapLaunch, descriptor: TrustedBootstrapDescriptor, value: object,
) -> dict[str, object]:
    """Check a proposed Feature 156 registration against a production bootstrap launch.

    This read-only check does not establish that the process exists, the snapshot was
    executed, or the registration was durably published. Those are runner obligations.
    """
    if not isinstance(launch, TrustedBootstrapLaunch) or not isinstance(descriptor, TrustedBootstrapDescriptor):
        _fail("producer_bootstrap_process_registration_context_invalid")
    expected_mode = (
        "darwin-immutable-snapshot" if sys.platform == "darwin"
        else "linux-fd-bound" if sys.platform.startswith("linux") else None
    )
    if descriptor.platform_execution_mode == "fixture-only":
        _fail("producer_bootstrap_production_mode_required")
    if expected_mode is None or descriptor.platform_execution_mode != expected_mode:
        _fail("producer_bootstrap_platform_mode_mismatch")
    if launch.bootstrap_descriptor_sha256 != descriptor.digest():
        _fail("producer_bootstrap_process_registration_binding_mismatch")

    encoded: bytes | None = None
    if isinstance(value, (str, bytes, bytearray)):
        encoded = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        value = _strict_json(encoded)
    raw = _object(value, _FEATURE156_BOOTSTRAP_REGISTRATION_FIELDS,
                  "producer_bootstrap_process_registration_schema_invalid")
    if encoded is not None and _canonical(raw) != encoded:
        _fail("producer_bootstrap_process_registration_noncanonical")
    if raw["schema_version"] != "1" or raw["protocol"] != PRODUCER_PROCESS_PROTOCOL:
        _fail("producer_bootstrap_process_registration_schema_invalid")

    for field in ("launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
                  "intent_sha256", "attestation_sha256", "gate_protocol"):
        if raw[field] != getattr(launch, field):
            _fail("producer_bootstrap_process_registration_binding_mismatch")
    if (
        raw["launch_sha256"] != launch.digest()
        or raw["bootstrap_descriptor_sha256"] != descriptor.digest()
        or raw["target_executable_identity"] != launch.target_executable_identity
    ):
        _fail("producer_bootstrap_process_registration_binding_mismatch")
    _sha(raw["consumption_sha256"], "producer_bootstrap_process_registration_digest_invalid")

    pid = _int(raw["pid"], minimum=2, maximum=2**63 - 1,
               code="producer_bootstrap_process_registration_process_identity_invalid")
    pgid = _int(raw["pgid"], minimum=2, maximum=2**63 - 1,
                code="producer_bootstrap_process_registration_process_identity_invalid")
    if pid != pgid:
        _fail("producer_bootstrap_process_registration_process_identity_invalid")
    owner = raw["owner_identity"]
    if not isinstance(owner, dict) or owner.get("pid") != pid:
        _fail("producer_bootstrap_process_registration_owner_identity_invalid")
    if expected_mode == "linux-fd-bound":
        if set(owner) != {"kind", "pid", "boot_id", "starttime_ticks"} or (
            owner["kind"] != "linux-proc-starttime-v1" or not isinstance(owner["boot_id"], str)
            or not owner["boot_id"] or len(owner["boot_id"]) > 128
        ):
            _fail("producer_bootstrap_process_registration_owner_identity_invalid")
        _int(owner["starttime_ticks"], minimum=1, maximum=2**63 - 1,
             code="producer_bootstrap_process_registration_owner_identity_invalid")
    elif set(owner) != {"kind", "pid", "start_sec", "start_usec"} or owner["kind"] != "darwin-libproc-starttime-v1":
        _fail("producer_bootstrap_process_registration_owner_identity_invalid")
    else:
        _int(owner["start_sec"], minimum=1, maximum=2**63 - 1,
             code="producer_bootstrap_process_registration_owner_identity_invalid")
        _int(owner["start_usec"], minimum=0, maximum=999_999,
             code="producer_bootstrap_process_registration_owner_identity_invalid")
    if raw["owner_identity_sha256"] != hashlib.sha256(_canonical(owner)).hexdigest():
        _fail("producer_bootstrap_process_registration_owner_identity_invalid")

    if raw["recovery_lock_protocol"] != "journal-flock-v1":
        _fail("producer_bootstrap_process_registration_lock_identity_invalid")
    for field in ("recovery_lock_device", "recovery_lock_inode"):
        _int(raw[field], minimum=1, maximum=2**63 - 1,
             code="producer_bootstrap_process_registration_lock_identity_invalid")
    _int(raw["registered_at_unix_ns"], minimum=1, maximum=2**63 - 1,
         code="producer_bootstrap_process_registration_schema_invalid")

    descriptor_identity = {
        "sha256": descriptor.bootstrap_sha256, "size": descriptor.size,
        "device": descriptor.device, "inode": descriptor.inode,
        "mtime_ns": descriptor.mtime_ns, "ctime_ns": descriptor.ctime_ns,
    }
    expected_executable_identity = hashlib.sha256(_canonical(descriptor_identity)).hexdigest()
    expected_binding = (
        "darwin-immutable-snapshot" if expected_mode == "darwin-immutable-snapshot"
        else "linux-sealed-memfd"
    )
    expected_snapshot_path = ".producer-snapshots/bootstrap" if expected_mode == "darwin-immutable-snapshot" else None
    if (
        raw["executable_identity"] != expected_executable_identity
        or raw["execution_binding"] != expected_binding
        or raw["execution_snapshot_relative_path"] != expected_snapshot_path
        or raw["execution_snapshot_sha256"] != descriptor.bootstrap_sha256
        or raw["execution_snapshot_size"] != descriptor.size
    ):
        _fail("producer_bootstrap_process_registration_execution_binding_mismatch")
    expected_target_path = ".producer-snapshots/target" if expected_mode == "darwin-immutable-snapshot" else None
    if (
        raw["target_execution_binding"] != expected_binding
        or raw["target_execution_snapshot_relative_path"] != expected_target_path
        or raw["target_execution_snapshot_sha256"] != launch.target_executable_identity
    ):
        _fail("producer_bootstrap_process_registration_target_binding_mismatch")
    _int(raw["target_execution_snapshot_size"], minimum=1, maximum=MAX_OUTPUT_BYTES,
         code="producer_bootstrap_process_registration_target_binding_mismatch")
    _sha(raw["registration_sha256"], "producer_bootstrap_process_registration_digest_invalid")
    if raw["registration_sha256"] != _digest_without(raw, "registration_sha256"):
        _fail("producer_bootstrap_process_registration_digest_mismatch")
    return dict(raw)


def verify_trusted_bootstrap_attempt(
    launch: TrustedBootstrapLaunch,
    descriptor: TrustedBootstrapDescriptor,
    intent: ProducerLaunchIntent | object,
    attestation: ProducerLaunchAttestation | object,
    consumption: object,
    registration: object,
    evidence: object | None = None,
) -> dict[str, object]:
    """Observe one proposed formal attempt without granting process or cleanup authority.

    A Feature 156 consumption claim names the target's stat-tuple digest, while the formal
    process registration names the executed bootstrap's stat-tuple digest. Keep those identities
    separate and bind both to the verified launch before examining terminal evidence.
    """
    if not isinstance(launch, TrustedBootstrapLaunch):
        _fail("producer_bootstrap_attempt_launch_invalid")
    try:
        parsed_intent = parse_producer_launch_intent(intent.to_dict() if isinstance(intent, ProducerLaunchIntent) else intent)
        parsed_attestation = parse_producer_launch_attestation(
            attestation.to_dict() if isinstance(attestation, ProducerLaunchAttestation) else attestation,
        )
    except (ProducerLaunchError, TypeError, ValueError) as exc:
        raise ProducerBootstrapError("producer_bootstrap_attempt_admission_invalid") from exc
    expected_launch = build_trusted_bootstrap_launch(
        parsed_intent, parsed_attestation, descriptor, gate_nonce=launch.gate_nonce,
    )
    if launch != expected_launch:
        _fail("producer_bootstrap_attempt_launch_mismatch")

    claim = _parse_trusted_bootstrap_consumption(consumption)
    for field in ("launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
                  "intent_sha256", "attestation_sha256"):
        if claim[field] != getattr(launch, field):
            _fail("producer_bootstrap_attempt_consumption_binding_mismatch")
    target_identity = {
        "sha256": parsed_attestation.executable_sha256,
        "size": parsed_attestation.executable_size,
        "device": parsed_attestation.executable_device,
        "inode": parsed_attestation.executable_inode,
        "mtime_ns": parsed_attestation.executable_mtime_ns,
        "ctime_ns": parsed_attestation.executable_ctime_ns,
    }
    if (
        claim["consumption_id"] != launch.launch_id
        or claim["nonce"] != parsed_attestation.nonce
        or claim["executable_identity"] != hashlib.sha256(_canonical(target_identity)).hexdigest()
    ):
        _fail("producer_bootstrap_attempt_consumption_binding_mismatch")
    _sha(claim["consumption_sha256"], "producer_bootstrap_attempt_consumption_digest_invalid")
    if claim["consumption_sha256"] != _digest_without(claim, "consumption_sha256"):
        _fail("producer_bootstrap_attempt_consumption_digest_mismatch")

    registered = verify_trusted_bootstrap_process_registration(launch, descriptor, registration)
    if registered["consumption_sha256"] != claim["consumption_sha256"]:
        _fail("producer_bootstrap_attempt_registration_binding_mismatch")
    if registered["target_execution_snapshot_size"] != parsed_attestation.executable_size:
        _fail("producer_bootstrap_attempt_target_binding_mismatch")
    result: dict[str, object] = {
        "status": "recovery_required", "reason": "trusted_bootstrap_terminal_evidence_missing",
        "journal_id": launch.journal_id, "launch_id": launch.launch_id,
        "consumption_sha256": claim["consumption_sha256"],
        "registration_sha256": registered["registration_sha256"],
        "pid": registered["pid"], "pgid": registered["pgid"],
    }
    if claim["protocol"] == NATIVE_CONSUMPTION_PROTOCOL:
        result["deadline_binding"] = claim["deadline_binding"]
    if evidence is None:
        return result
    observed = parse_trusted_bootstrap_evidence(
        evidence.to_dict() if isinstance(evidence, TrustedBootstrapEvidence) else evidence,
    )
    if (
        observed.launch_sha256 != launch.digest()
        or observed.registration_sha256 != registered["registration_sha256"]
    ):
        _fail("producer_bootstrap_attempt_evidence_binding_mismatch")
    if observed.target_pgid is not None and observed.target_pgid != registered["pgid"]:
        _fail("producer_bootstrap_attempt_target_group_mismatch")
    result["evidence_sha256"] = observed.evidence_sha256
    if observed.status == "unknown":
        result["reason"] = "trusted_bootstrap_evidence_unknown"
        return result
    result.pop("reason")
    result["status"] = "evidence_available"
    result["bootstrap_status"] = observed.status
    return result


def observe_trusted_bootstrap_attempt(
    workspace: str | Path, *, launch: TrustedBootstrapLaunch,
    descriptor: TrustedBootstrapDescriptor, intent: ProducerLaunchIntent | object,
    attestation: ProducerLaunchAttestation | object,
    require_handoff: bool = False,
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Read one formal attempt's durable records without process authority."""
    from .trusted_bootstrap_runtime import observe_trusted_bootstrap_attempt as observe

    return observe(
        workspace, launch=launch, descriptor=descriptor, intent=intent,
        attestation=attestation, require_handoff=require_handoff,
        deadline=deadline, monotonic=monotonic,
    )


_FRAME_FIELDS = frozenset({
    "schema_version", "protocol", "sequence", "kind", "launch_sha256", "intent_sha256",
    "target_executable_identity", "observed_pid", "observed_pgid", "frame_sha256",
})


@dataclass(frozen=True, slots=True)
class BootstrapHandshakeFrame:
    sequence: int
    kind: str
    launch_sha256: str
    intent_sha256: str
    target_executable_identity: str | None = None
    observed_pid: int | None = None
    observed_pgid: int | None = None
    frame_sha256: str | None = None
    schema_version: str = TRUSTED_BOOTSTRAP_SCHEMA_VERSION
    protocol: str = TRUSTED_BOOTSTRAP_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != TRUSTED_BOOTSTRAP_SCHEMA_VERSION or self.protocol != TRUSTED_BOOTSTRAP_PROTOCOL:
            _fail("producer_bootstrap_schema_invalid")
        _int(self.sequence, minimum=1, maximum=MAX_BOOTSTRAP_SEQUENCE, code="producer_bootstrap_sequence_invalid")
        if self.kind not in _KINDS:
            _fail("producer_bootstrap_frame_kind_invalid")
        _sha(self.launch_sha256)
        _sha(self.intent_sha256)
        if self.target_executable_identity is not None:
            _sha(self.target_executable_identity)
        for value in (self.observed_pid, self.observed_pgid):
            if value is not None:
                _int(value, minimum=2, maximum=2**63 - 1, code="producer_bootstrap_process_identity_invalid")
        if self.kind == "target_started" and (
            self.target_executable_identity is None or self.observed_pid is None or self.observed_pgid is None
        ):
            _fail("producer_bootstrap_target_frame_invalid")
        if self.kind != "target_started" and any(
            value is not None for value in (self.target_executable_identity, self.observed_pid, self.observed_pgid)
        ):
            _fail("producer_bootstrap_target_frame_invalid")
        if self.frame_sha256 is not None and self.frame_sha256 != self.digest():
            _fail("producer_bootstrap_digest_mismatch")
        if self.frame_sha256 is None:
            object.__setattr__(self, "frame_sha256", self.digest())

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "sequence": self.sequence, "kind": self.kind, "launch_sha256": self.launch_sha256,
            "intent_sha256": self.intent_sha256, "target_executable_identity": self.target_executable_identity,
            "observed_pid": self.observed_pid, "observed_pgid": self.observed_pgid,
        }
        if include_digest:
            value["frame_sha256"] = self.frame_sha256
        return value

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "frame_sha256")


def parse_bootstrap_handshake_frame(value: object) -> BootstrapHandshakeFrame:
    if isinstance(value, (str, bytes, bytearray)):
        value = _strict_json(value)
    raw = _object(value, _FRAME_FIELDS, "producer_bootstrap_frame_schema_invalid")
    try:
        return BootstrapHandshakeFrame(**raw)
    except ProducerBootstrapError:
        raise
    except (TypeError, ValueError) as exc:
        raise ProducerBootstrapError("producer_bootstrap_frame_schema_invalid") from exc


@dataclass(frozen=True, slots=True)
class TrustedBootstrapEvidence:
    launch_sha256: str
    registration_sha256: str
    bootstrap_ready_observed: bool
    release_observed: bool
    target_started_observed: bool
    target_start_count: int
    target_group_identity: str | None
    target_pid: int | None
    target_pgid: int | None
    pre_gate_target_work_observed: bool
    status: str
    failure_code: str | None = None
    evidence_sha256: str | None = None
    schema_version: str = TRUSTED_BOOTSTRAP_SCHEMA_VERSION
    protocol: str = TRUSTED_BOOTSTRAP_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != TRUSTED_BOOTSTRAP_SCHEMA_VERSION or self.protocol != TRUSTED_BOOTSTRAP_PROTOCOL:
            _fail("producer_bootstrap_schema_invalid")
        _sha(self.launch_sha256)
        _sha(self.registration_sha256)
        if not all(isinstance(value, bool) for value in (
            self.bootstrap_ready_observed, self.release_observed,
            self.target_started_observed, self.pre_gate_target_work_observed,
        )):
            _fail("producer_bootstrap_evidence_boolean_invalid")
        _int(self.target_start_count, minimum=0, maximum=1, code="producer_bootstrap_target_count_invalid")
        if self.target_started_observed != (self.target_start_count == 1):
            _fail("producer_bootstrap_target_count_invalid")
        if self.target_group_identity is not None:
            _sha(self.target_group_identity)
        if self.target_start_count == 1:
            for value in (self.target_pid, self.target_pgid):
                _int(value, minimum=2, maximum=2**63 - 1, code="producer_bootstrap_process_identity_invalid")
            if self.target_group_identity != hashlib.sha256(
                _canonical({"pid": self.target_pid, "pgid": self.target_pgid})
            ).hexdigest():
                _fail("producer_bootstrap_target_group_identity_mismatch")
        elif any(value is not None for value in (
            self.target_group_identity, self.target_pid, self.target_pgid,
        )):
            _fail("producer_bootstrap_target_group_identity_unexpected")
        if self.status not in _STATUSES:
            _fail("producer_bootstrap_status_invalid")
        if self.status == "failed" and not self.failure_code:
            _fail("producer_bootstrap_failure_code_missing")
        if self.status != "failed" and self.failure_code is not None:
            _fail("producer_bootstrap_failure_code_unexpected")
        if self.status == "passed" and (
            not self.bootstrap_ready_observed or not self.release_observed
            or not self.target_started_observed or self.target_start_count != 1
            or self.pre_gate_target_work_observed or self.target_group_identity is None
        ):
            _fail("producer_bootstrap_evidence_incomplete")
        if self.evidence_sha256 is not None and self.evidence_sha256 != self.digest():
            _fail("producer_bootstrap_digest_mismatch")
        if self.evidence_sha256 is None:
            object.__setattr__(self, "evidence_sha256", self.digest())

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "launch_sha256": self.launch_sha256, "registration_sha256": self.registration_sha256,
            "bootstrap_ready_observed": self.bootstrap_ready_observed, "release_observed": self.release_observed,
            "target_started_observed": self.target_started_observed, "target_start_count": self.target_start_count,
            "target_group_identity": self.target_group_identity,
            "target_pid": self.target_pid, "target_pgid": self.target_pgid,
            "pre_gate_target_work_observed": self.pre_gate_target_work_observed,
            "status": self.status, "failure_code": self.failure_code,
        }
        if include_digest:
            value["evidence_sha256"] = self.evidence_sha256
        return value

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "evidence_sha256")


_EVIDENCE_FIELDS = frozenset({
    "schema_version", "protocol", "launch_sha256", "registration_sha256",
    "bootstrap_ready_observed", "release_observed", "target_started_observed",
    "target_start_count", "target_group_identity", "target_pid", "target_pgid",
    "pre_gate_target_work_observed",
    "status", "failure_code", "evidence_sha256",
})


def parse_trusted_bootstrap_evidence(value: object) -> TrustedBootstrapEvidence:
    """Parse one strict, self-authenticating bootstrap evidence payload."""
    encoded: bytes | None = None
    if isinstance(value, (str, bytes, bytearray)):
        encoded = bytes(value, "utf-8") if isinstance(value, str) else bytes(value)
        value = _strict_json(encoded)
    raw = _object(value, _EVIDENCE_FIELDS, "producer_bootstrap_evidence_schema_invalid")
    if encoded is not None and _canonical(raw) != encoded:
        _fail("producer_bootstrap_evidence_noncanonical")
    try:
        evidence = TrustedBootstrapEvidence(**raw)
    except ProducerBootstrapError:
        raise
    except (TypeError, ValueError) as exc:
        raise ProducerBootstrapError("producer_bootstrap_evidence_schema_invalid") from exc
    _sha(raw["evidence_sha256"], "producer_bootstrap_evidence_digest_invalid")
    return evidence


class TrustedBootstrapSession:
    """Small deterministic state machine for the trusted bootstrap handshake."""

    def __init__(self, launch: TrustedBootstrapLaunch, registration_sha256: str) -> None:
        _sha(registration_sha256)
        self.launch = launch
        self.registration_sha256 = registration_sha256
        self.state = "created"
        # Keep observations separate from the current state.  A failed session is also
        # terminal, but reaching ``terminal`` does not imply that the ready frame was
        # ever observed.
        self.bootstrap_ready_observed = False
        self.release_count = 0
        self.target_start_count = 0
        self.pre_gate_target_work_observed = False
        self.target_group_identity: str | None = None
        self.target_pid: int | None = None
        self.target_pgid: int | None = None
        self.failure_code: str | None = None

    def _check_frame(self, frame: BootstrapHandshakeFrame) -> None:
        if frame.launch_sha256 != self.launch.launch_sha256 or frame.intent_sha256 != self.launch.intent_sha256:
            _fail("producer_bootstrap_frame_binding_mismatch")

    def accept_frame(self, frame: BootstrapHandshakeFrame | object) -> None:
        # A successful terminal frame closes the handshake just like a failure does.
        # Do not let a late frame turn a successful start into a second start or let a
        # malformed late frame mutate the evidence a second time.
        if self.state == "terminal" or self.failure_code is not None:
            _fail("producer_bootstrap_terminal")
        if not isinstance(frame, BootstrapHandshakeFrame):
            try:
                frame = parse_bootstrap_handshake_frame(frame)
            except ProducerBootstrapError as exc:
                # A malformed frame is a definitive protocol failure once a live
                # session has accepted responsibility for the handshake.
                self.fail(exc.code)
        try:
            self._check_frame(frame)
        except ProducerBootstrapError as exc:
            self.fail(exc.code)
        if frame.kind == "bootstrap_ready":
            if self.state != "created" or frame.sequence != 1:
                self.fail("producer_bootstrap_ready_order_invalid")
            self.bootstrap_ready_observed = True
            self.state = "ready"
            return
        if frame.kind == "target_started":
            if self.state == "target_started":
                self.fail("producer_bootstrap_duplicate_target_start")
            if self.state != "released" or frame.sequence != 2:
                self.fail("producer_bootstrap_target_started_before_release")
            if frame.target_executable_identity != self.launch.target_executable_identity:
                self.fail("producer_bootstrap_target_identity_mismatch")
            self.target_start_count += 1
            if self.target_start_count != 1:
                self.fail("producer_bootstrap_duplicate_target_start")
            self.target_group_identity = hashlib.sha256(
                _canonical({"pid": frame.observed_pid, "pgid": frame.observed_pgid})
            ).hexdigest()
            self.target_pid = frame.observed_pid
            self.target_pgid = frame.observed_pgid
            self.state = "target_started"
            return
        if frame.kind == "target_start_failed":
            if self.state != "released" or frame.sequence != 2:
                self.fail("producer_bootstrap_target_start_order_invalid")
            self.fail("producer_bootstrap_target_start_failed")
        if frame.kind == "terminal":
            # ``terminal`` is the optional final frame after the target-start frame.
            # A released bootstrap that never reported target start must use the
            # explicit target_start_failed frame; accepting terminal here would make
            # an incomplete launch look orderly.
            if self.state != "target_started" or frame.sequence != 3:
                self.fail("producer_bootstrap_terminal_order_invalid")
            self.state = "terminal"
            return
        self.fail("producer_bootstrap_frame_kind_invalid")

    def release(self, token: str) -> None:
        if self.state == "terminal":
            self.fail("producer_bootstrap_terminal")
        if self.state == "released":
            self.fail("producer_bootstrap_duplicate_release")
        if self.state != "ready":
            self.fail("producer_bootstrap_release_order_invalid")
        if token != self.launch.gate_nonce:
            self.fail("producer_bootstrap_release_token_invalid")
        self.release_count += 1
        if self.release_count != 1:
            self.fail("producer_bootstrap_duplicate_release")
        self.state = "released"

    def record_eof(self) -> None:
        """Close the handshake after start, or reject EOF before a target start."""
        if self.state in {"created", "ready", "released"}:
            self.fail("producer_bootstrap_early_eof")
        if self.state == "target_started":
            self.state = "terminal"
            return
        self.fail("producer_bootstrap_terminal")

    def record_pre_gate_target_work(self) -> None:
        if self.state in {"created", "ready"}:
            self.pre_gate_target_work_observed = True
            self.fail("producer_bootstrap_pre_gate_work")
        _fail("producer_bootstrap_terminal")

    def fail(self, code: str) -> None:
        # Once a terminal frame or terminal failure has been recorded, keep the
        # evidence immutable.  A late API call is rejected without downgrading a
        # previously successful handshake to ``failed``.
        if self.state == "terminal" or self.failure_code is not None:
            _fail("producer_bootstrap_terminal")
        self.failure_code = code
        self.state = "terminal"
        raise ProducerBootstrapError(code)

    def evidence(self) -> TrustedBootstrapEvidence:
        passed = (
            self.state == "terminal" and self.release_count == 1
            and self.target_start_count == 1 and not self.pre_gate_target_work_observed
            and self.target_group_identity is not None and self.failure_code is None
        )
        return TrustedBootstrapEvidence(
            launch_sha256=self.launch.launch_sha256 or self.launch.digest(),
            registration_sha256=self.registration_sha256,
            bootstrap_ready_observed=self.bootstrap_ready_observed,
            release_observed=self.release_count == 1,
            target_started_observed=self.target_start_count == 1,
            target_start_count=self.target_start_count,
            target_group_identity=self.target_group_identity,
            target_pid=self.target_pid,
            target_pgid=self.target_pgid,
            pre_gate_target_work_observed=self.pre_gate_target_work_observed,
            status="passed" if passed else ("failed" if self.failure_code else "unknown"),
            failure_code=self.failure_code,
        )


__all__ = [
    "MAX_BOOTSTRAP_PAYLOAD_BYTES",
    "TRUSTED_BOOTSTRAP_PROTOCOL",
    "TRUSTED_BOOTSTRAP_SCHEMA_VERSION",
    "BootstrapHandshakeFrame",
    "ProducerBootstrapError",
    "TrustedBootstrapDescriptor",
    "TrustedBootstrapEvidence",
    "TrustedBootstrapLaunch",
    "TrustedBootstrapRegistration",
    "TrustedBootstrapSession",
    "build_trusted_bootstrap_launch",
    "build_trusted_bootstrap_registration",
    "observe_trusted_bootstrap_attempt",
    "parse_bootstrap_handshake_frame",
    "parse_trusted_bootstrap_evidence",
    "parse_trusted_bootstrap_registration",
    "verify_trusted_bootstrap_registration",
]
