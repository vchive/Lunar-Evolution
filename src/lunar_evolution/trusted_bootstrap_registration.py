"""Durable pre-gate registration for a native trusted bootstrap attempt.

The caller owns the already-spawned, blocked bootstrap and its private gate. This
module never releases that gate. A successful return means the exact formal
registration and its cross-record handoff are durable under the journal lock.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .producer_bootstrap import (
    BootstrapHandshakeFrame,
    ProducerBootstrapError,
    TrustedBootstrapDescriptor,
    TrustedBootstrapLaunch,
    build_trusted_bootstrap_launch,
    parse_bootstrap_handshake_frame,
    verify_trusted_bootstrap_process_registration,
)
from .producer_launcher import (
    ProducerLaunchAttestation,
    ProducerLaunchError,
    ProducerLaunchIntent,
    verify_producer_launch_attestation,
)
from .producer_process import (
    PRODUCER_PROCESS_PROTOCOL,
    ProducerProcessError,
    _atomic_json,
    _canonical,
    _current_recovery_lock_identity,
    _digest_without,
    _file_identity,
    _held_directory,
    _identity_digest,
    _process_owner_identity,
    _read_durable_json,
    _relative_path,
    _safe_dir,
    _safe_root,
    _sha,
)
from .trusted_bootstrap_binding import TrustedExecutablePair
from .trusted_bootstrap_handoff import build_trusted_bootstrap_process_registration_handoff


class TrustedBootstrapRegistrationError(ValueError):
    """Fixed-code pre-gate registration failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PublishedTrustedBootstrapRegistration:
    registration: dict[str, object]
    handoff: dict[str, object]


def _fail(code: str) -> None:
    raise TrustedBootstrapRegistrationError(code)


def _claim_bytes(path: Path) -> tuple[bytes, dict[str, object]]:
    try:
        with _held_directory(path.parent) as parent:
            before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= 64 * 1024:
                _fail("trusted_registration_claim_unknown")
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
            try:
                opened = os.fstat(fd)
                data = bytearray()
                while len(data) <= 64 * 1024:
                    chunk = os.read(fd, min(4096, 64 * 1024 + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                after = os.fstat(fd)
            finally:
                os.close(fd)
            named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            if (
                len(data) > 64 * 1024 or len(data) != before.st_size
                or any(identity(info) != identity(before) for info in (opened, after, named))
            ):
                _fail("trusted_registration_claim_unknown")

        def unique(items: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in items:
                if key in result:
                    _fail("trusted_registration_claim_unknown")
                result[key] = value
            return result

        claim = json.loads(data, object_pairs_hook=unique)
        if not isinstance(claim, dict) or _canonical(claim) != data:
            _fail("trusted_registration_claim_unknown")
        return bytes(data), claim
    except TrustedBootstrapRegistrationError:
        raise
    except (OSError, UnicodeError, ValueError, ProducerProcessError) as exc:
        raise TrustedBootstrapRegistrationError("trusted_registration_claim_unknown") from exc


def consume_trusted_bootstrap_attestation(
    workspace: str | Path,
    *,
    producer_root: str | Path,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    descriptor: TrustedBootstrapDescriptor,
    launch: TrustedBootstrapLaunch,
    recovery_lock_identity: tuple[int, int],
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Consume the target attestation once before preparing or spawning a bootstrap.

    The caller holds the journal recovery lock for the full attempt. A partial
    publication is deliberately left in place, so neither a failed write nor a
    crashed controller can reuse the nonce or journal identity.
    """
    if monotonic() >= deadline:
        _fail("trusted_registration_wall_timeout")
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(attestation, ProducerLaunchAttestation):
        _fail("trusted_registration_admission_invalid")
    try:
        verify_producer_launch_attestation(intent, attestation)
        expected_launch = build_trusted_bootstrap_launch(
            intent, attestation, descriptor, gate_nonce=attestation.nonce,
        )
    except (ProducerLaunchError, ProducerBootstrapError, TypeError, ValueError) as exc:
        raise TrustedBootstrapRegistrationError("trusted_registration_admission_invalid") from exc
    if launch != expected_launch:
        _fail("trusted_registration_launch_mismatch")
    try:
        root = _safe_root(workspace)
        batch = root / "evolution" / "producer-batches" / intent.journal_id
        _safe_dir(batch)
        if _current_recovery_lock_identity(batch) != recovery_lock_identity:
            _fail("trusted_registration_lock_mismatch")
        target_root = _safe_root(producer_root, "producer_process_producer_root_invalid")
        target = _relative_path(target_root, intent.executable_relative)
        _safe_dir(target.parent)
        identity = _file_identity(target)
    except ProducerProcessError as exc:
        raise TrustedBootstrapRegistrationError("trusted_registration_target_unknown") from exc
    expected_identity = {
        "sha256": intent.executable_sha256, "size": intent.executable_size,
        "device": intent.executable_device, "inode": intent.executable_inode,
        "mtime_ns": intent.executable_mtime_ns, "ctime_ns": intent.executable_ctime_ns,
    }
    if identity != expected_identity:
        _fail("trusted_registration_target_changed")
    if monotonic() >= deadline:
        _fail("trusted_registration_wall_timeout")
    claim: dict[str, object] = {
        "schema_version": "1", "protocol": PRODUCER_PROCESS_PROTOCOL,
        "consumption_id": intent.launch_id, "launch_id": intent.launch_id,
        "journal_id": intent.journal_id, "run_id": intent.run_id,
        "parent_task_id": intent.parent_task_id, "task_id": intent.task_id,
        "intent_sha256": intent.intent_sha256 or intent.digest(),
        "attestation_sha256": attestation.attestation_sha256 or attestation.digest(),
        "nonce": attestation.nonce, "executable_identity": _identity_digest(identity),
    }
    claim["consumption_sha256"] = _digest_without(claim, "consumption_sha256")
    nonce_key = hashlib.sha256(attestation.nonce.encode("utf-8")).hexdigest()
    try:
        _atomic_json(root / "evolution" / "producer-nonces" / f"{nonce_key}.json", claim, exclusive=True)
        _atomic_json(batch / "attestation-consumption.json", claim, exclusive=True)
    except ProducerProcessError as exc:
        raise TrustedBootstrapRegistrationError("trusted_registration_claim_conflict") from exc
    return claim


def publish_trusted_bootstrap_registration(
    workspace: str | Path,
    *,
    launch: TrustedBootstrapLaunch,
    descriptor: TrustedBootstrapDescriptor,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    pair: TrustedExecutablePair,
    process: subprocess.Popen[bytes],
    ready_frame: BootstrapHandshakeFrame | object,
    recovery_lock_identity: tuple[int, int],
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> PublishedTrustedBootstrapRegistration:
    """Publish registration and handoff while the native child remains gated.

    The caller must hold the journal recovery lock and both execution bindings
    through spawn, and must retain the gate until this function returns. A
    publication failure leaves any written records in place for recovery.
    """
    if monotonic() >= deadline:
        _fail("trusted_registration_wall_timeout")
    if not isinstance(pair, TrustedExecutablePair) or not isinstance(process, subprocess.Popen):
        _fail("trusted_registration_context_invalid")
    if not isinstance(recovery_lock_identity, tuple) or len(recovery_lock_identity) != 2 or any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in recovery_lock_identity
    ):
        _fail("trusted_registration_lock_invalid")
    frame = (
        ready_frame if isinstance(ready_frame, BootstrapHandshakeFrame)
        else parse_bootstrap_handshake_frame(ready_frame)
    )
    if (
        frame.kind != "bootstrap_ready" or frame.sequence != 1
        or frame.launch_sha256 != launch.launch_sha256
        or frame.intent_sha256 != launch.intent_sha256
    ):
        _fail("trusted_registration_ready_mismatch")
    if process.poll() is not None:
        _fail("trusted_registration_child_exited")

    root = _safe_root(workspace)
    batch = root / "evolution" / "producer-batches" / launch.journal_id
    _safe_dir(batch)
    if _current_recovery_lock_identity(batch) != recovery_lock_identity:
        _fail("trusted_registration_lock_mismatch")
    nonce_key = hashlib.sha256(attestation.nonce.encode("utf-8")).hexdigest()
    claim_bytes, claim = _claim_bytes(batch / "attestation-consumption.json")
    ledger_bytes, _ = _claim_bytes(root / "evolution" / "producer-nonces" / f"{nonce_key}.json")
    if claim_bytes != ledger_bytes:
        _fail("trusted_registration_claim_mismatch")

    try:
        pgid = os.getpgid(process.pid)
    except OSError as exc:
        raise TrustedBootstrapRegistrationError("trusted_registration_process_unknown") from exc
    if pgid != process.pid:
        _fail("trusted_registration_process_mismatch")
    owner = _process_owner_identity(process.pid)
    if owner is None:
        _fail("trusted_registration_owner_unknown")
    bootstrap = pair.bootstrap.snapshot
    target = pair.target.snapshot
    identity = {
        "sha256": descriptor.bootstrap_sha256, "size": descriptor.size,
        "device": descriptor.device, "inode": descriptor.inode,
        "mtime_ns": descriptor.mtime_ns, "ctime_ns": descriptor.ctime_ns,
    }
    registration: dict[str, object] = {
        "schema_version": "1", "protocol": PRODUCER_PROCESS_PROTOCOL,
        "launch_id": launch.launch_id, "journal_id": launch.journal_id,
        "run_id": launch.run_id, "parent_task_id": launch.parent_task_id,
        "task_id": launch.task_id, "intent_sha256": launch.intent_sha256,
        "attestation_sha256": launch.attestation_sha256,
        "consumption_sha256": claim.get("consumption_sha256"),
        "executable_identity": _sha(identity),
        "owner_identity": owner, "owner_identity_sha256": _sha(owner),
        "execution_binding": bootstrap.binding,
        "execution_snapshot_relative_path": bootstrap.relative_path,
        "execution_snapshot_sha256": bootstrap.sha256,
        "execution_snapshot_size": bootstrap.size,
        "target_execution_binding": target.binding,
        "target_execution_snapshot_relative_path": target.relative_path,
        "target_execution_snapshot_sha256": target.sha256,
        "target_execution_snapshot_size": target.size,
        "pid": process.pid, "pgid": pgid,
        "recovery_lock_protocol": "journal-flock-v1",
        "recovery_lock_device": recovery_lock_identity[0],
        "recovery_lock_inode": recovery_lock_identity[1],
        "gate_protocol": launch.gate_protocol,
        "registered_at_unix_ns": time.time_ns(),
        "launch_sha256": launch.launch_sha256,
        "bootstrap_descriptor_sha256": descriptor.descriptor_sha256,
        "target_executable_identity": launch.target_executable_identity,
    }
    registration["registration_sha256"] = _digest_without(registration, "registration_sha256")
    verify_trusted_bootstrap_process_registration(launch, descriptor, registration)
    handoff = build_trusted_bootstrap_process_registration_handoff(
        launch=launch, descriptor=descriptor, intent=intent, attestation=attestation,
        consumption=claim, registration=registration,
    )
    if monotonic() >= deadline or process.poll() is not None:
        _fail("trusted_registration_wall_timeout")
    try:
        _atomic_json(batch / "process-registration.json", registration, exclusive=True)
        _atomic_json(batch / "trusted-bootstrap-handoff.json", handoff, exclusive=True)
        stored_registration = _read_durable_json(
            batch / "process-registration.json", code="trusted_registration_publication_unknown",
        )
        stored_handoff = _read_durable_json(
            batch / "trusted-bootstrap-handoff.json", code="trusted_registration_publication_unknown",
        )
    except ProducerProcessError as exc:
        raise TrustedBootstrapRegistrationError("trusted_registration_publication_unknown") from exc
    if stored_registration != registration or stored_handoff != handoff:
        _fail("trusted_registration_publication_unknown")
    if monotonic() >= deadline or process.poll() is not None:
        _fail("trusted_registration_wall_timeout")
    return PublishedTrustedBootstrapRegistration(registration, handoff)


__all__ = [
    "PublishedTrustedBootstrapRegistration", "TrustedBootstrapRegistrationError",
    "consume_trusted_bootstrap_attestation", "publish_trusted_bootstrap_registration",
]
