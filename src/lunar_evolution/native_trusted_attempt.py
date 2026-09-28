"""Provider-free native trusted-bootstrap attempt, without publication authority.

This runner joins the pre-gate production records. It deliberately does not emit a
Feature 156 terminal receipt or claim that producer requests were host-observed.
"""

from __future__ import annotations

import os
import selectors
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from .native_bootstrap import (
    NativeBootstrapArtifact,
    NativeBootstrapError,
    encode_native_bootstrap_control,
    load_native_bootstrap_artifact,
    native_bootstrap_command,
)
from .process_ownership import ProcessCleanupStatus, RegisteredProcess
from .producer_bootstrap import (
    BootstrapHandshakeFrame,
    ProducerBootstrapError,
    TrustedBootstrapSession,
    build_trusted_bootstrap_launch,
    parse_bootstrap_handshake_frame,
)
from .producer_isolation import ProducerIsolationError, build_producer_isolation_policy
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import (
    ProducerProcessError,
    _atomic_json,
    _cleanup,
    _current_process_owned,
    _current_recovery_lock_identity,
    _read_durable_json,
    _recovery_lock,
    _relative_path,
    _safe_dir,
    _safe_root,
)
from .trusted_bootstrap_binding import TrustedBootstrapBindingError, prepare_trusted_executable_pair
from .trusted_bootstrap_registration import (
    TrustedBootstrapRegistrationError,
    consume_trusted_bootstrap_attestation,
    publish_trusted_bootstrap_registration,
)


class NativeTrustedAttemptError(ValueError):
    """Fixed-code failure before an attestation is consumed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NativeTrustedAttemptObservation:
    launch_id: str
    journal_id: str
    status: str
    reason: str
    registration_sha256: str | None
    gate_released: bool
    target_started: bool
    exit_code: int | None
    cleanup_status: str | None


def _remaining(deadline: float, monotonic: Callable[[], float]) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise NativeTrustedAttemptError("native_trusted_attempt_wall_timeout")
    return remaining


def _write_control(fd: int, data: bytes, deadline: float, monotonic: Callable[[], float]) -> None:
    os.set_blocking(fd, False)
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_WRITE)
        offset = 0
        while offset < len(data):
            if not selector.select(_remaining(deadline, monotonic)):
                raise NativeTrustedAttemptError("native_trusted_attempt_wall_timeout")
            try:
                offset += os.write(fd, data[offset:])
            except BlockingIOError:
                continue


def _read_frame(fd: int, deadline: float, monotonic: Callable[[], float]) -> BootstrapHandshakeFrame:
    data = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        while True:
            if not selector.select(_remaining(deadline, monotonic)):
                raise NativeTrustedAttemptError("native_trusted_attempt_wall_timeout")
            part = os.read(fd, 1)
            if not part:
                raise NativeTrustedAttemptError("native_trusted_attempt_frame_missing")
            if part == b"\n":
                try:
                    return parse_bootstrap_handshake_frame(bytes(data))
                except ProducerBootstrapError as exc:
                    raise NativeTrustedAttemptError("native_trusted_attempt_frame_invalid") from exc
            data.extend(part)
            if len(data) > 4096:
                raise NativeTrustedAttemptError("native_trusted_attempt_frame_invalid")


def run_native_trusted_attempt(
    workspace: str | Path,
    *,
    producer_root: str | Path,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact,
    monotonic: Callable[[], float] = time.monotonic,
) -> NativeTrustedAttemptObservation:
    """Run one locally isolated target under a durable pre-gate registration.

    A consumed attempt always remains recovery-required until the full execution
    receipt, request broker, and publication boundary are implemented.
    """
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(attestation, ProducerLaunchAttestation):
        raise NativeTrustedAttemptError("native_trusted_attempt_admission_invalid")
    if not isinstance(artifact, NativeBootstrapArtifact):
        raise NativeTrustedAttemptError("native_trusted_attempt_artifact_invalid")
    deadline = monotonic() + float(intent.wall_timeout_seconds)
    try:
        installed = load_native_bootstrap_artifact(
            artifact.path, descriptor=artifact.descriptor, allowlist_id=artifact.allowlist_id,
        )
        launch = build_trusted_bootstrap_launch(intent, attestation, installed.descriptor)
        root = _safe_root(workspace)
        target_root = _safe_root(producer_root)
        batch = root / "evolution" / "producer-batches" / intent.journal_id
        _safe_dir(batch, create=True)
        working = _relative_path(batch, intent.working_directory)
        output = _relative_path(batch, intent.output_directory)
        _safe_dir(working, create=True)
        _safe_dir(output, create=True)
    except (NativeBootstrapError, ProducerBootstrapError, ProducerProcessError) as exc:
        raise NativeTrustedAttemptError("native_trusted_attempt_preflight_invalid") from exc

    with _recovery_lock(batch) as lock_identity:
        process: subprocess.Popen[bytes] | None = None
        owner: RegisteredProcess | None = None
        registration: dict[str, object] | None = None
        session: TrustedBootstrapSession | None = None
        gate_released = False
        target_started = False
        exit_code: int | None = None
        cleanup_status: str | None = None
        reason = "native_trusted_attempt_terminal_receipt_missing"
        claimed = False
        fds: set[int] = set()
        try:
            consume_trusted_bootstrap_attestation(
                root, producer_root=target_root, intent=intent, attestation=attestation,
                descriptor=installed.descriptor, launch=launch,
                recovery_lock_identity=lock_identity, deadline=deadline, monotonic=monotonic,
            )
            claimed = True
            with prepare_trusted_executable_pair(
                bootstrap_source=installed.path, producer_root=target_root, batch=batch,
                descriptor=installed.descriptor, launch=launch, intent=intent,
                attestation=attestation, deadline=deadline, monotonic=monotonic,
            ) as pair:
                # Linux executes the inherited sealed FD. Landlock must not
                # grant a second pathname route to the mutable source file.
                read_paths = [pair.target.executable] if sys.platform == "darwin" else []
                policy = build_producer_isolation_policy(
                    read_paths=read_paths, write_dirs=[working, output],
                )
                control = encode_native_bootstrap_control(
                    launch, target_path=pair.target.executable,
                    target_argv=(pair.target.executable, *intent.argv[1:]),
                    target_cwd=working, target_fd=pair.target.pass_fd,
                    isolation_policy=policy,
                )
                control_read, control_write = os.pipe()
                fds.update((control_read, control_write))
                gate_read, gate_write = os.pipe()
                fds.update((gate_read, gate_write))
                frame_read, frame_write = os.pipe()
                fds.update((frame_read, frame_write))
                command = native_bootstrap_command(
                    pair.bootstrap.executable, control_fd=control_read,
                    gate_fd=gate_read, frame_fd=frame_write,
                )
                _remaining(deadline, monotonic)
                process = subprocess.Popen(
                    command, executable=pair.bootstrap.executable,
                    shell=False, start_new_session=True, close_fds=True,
                    pass_fds=(control_read, gate_read, frame_write, *pair.pass_fds),
                    cwd=str(working), env={"PATH": os.defpath, "LANG": "C"},
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                for fd in (control_read, gate_read, frame_write):
                    os.close(fd)
                    fds.remove(fd)
                _write_control(control_write, control, deadline, monotonic)
                os.close(control_write)
                fds.remove(control_write)
                ready = _read_frame(frame_read, deadline, monotonic)
                if ready.kind != "bootstrap_ready" or ready.sequence != 1:
                    raise NativeTrustedAttemptError("native_trusted_attempt_ready_invalid")
                published = publish_trusted_bootstrap_registration(
                    root, launch=launch, descriptor=installed.descriptor, intent=intent,
                    attestation=attestation, pair=pair, process=process, ready_frame=ready,
                    recovery_lock_identity=lock_identity, deadline=deadline, monotonic=monotonic,
                )
                registration = published.registration
                session = TrustedBootstrapSession(launch, str(registration["registration_sha256"]))
                session.accept_frame(ready)
                pid = process.pid
                owner_identity = registration["owner_identity"]

                def owned() -> bool:
                    try:
                        current = _read_durable_json(
                            batch / "process-registration.json",
                            code="native_trusted_attempt_registration_unknown",
                        )
                        return (
                            current == registration
                            and _current_recovery_lock_identity(batch) == lock_identity
                            and _current_process_owned(pid, owner_identity, process)
                        )
                    except ProducerProcessError:
                        return False

                owner = RegisteredProcess(pid, pid, owner_check=owned, label=launch.launch_id)
                _remaining(deadline, monotonic)
                os.write(gate_write, b"1")
                os.close(gate_write)
                fds.remove(gate_write)
                gate_released = True
                session.release(launch.gate_nonce)
                started = _read_frame(frame_read, deadline, monotonic)
                session.accept_frame(started)
                if (
                    started.kind != "target_started" or started.sequence != 2
                    or started.launch_sha256 != launch.launch_sha256
                    or started.intent_sha256 != launch.intent_sha256
                    or started.target_executable_identity != launch.target_executable_identity
                    or started.observed_pgid != pid
                ):
                    raise NativeTrustedAttemptError("native_trusted_attempt_target_start_unknown")
                target_started = True
                terminal = _read_frame(frame_read, deadline, monotonic)
                session.accept_frame(terminal)
                if (
                    terminal.kind != "terminal" or terminal.sequence != 3
                    or terminal.launch_sha256 != launch.launch_sha256
                    or terminal.intent_sha256 != launch.intent_sha256
                ):
                    raise NativeTrustedAttemptError("native_trusted_attempt_terminal_unknown")
                exit_code = process.wait(timeout=_remaining(deadline, monotonic))
        except (NativeTrustedAttemptError, ProducerBootstrapError, TrustedBootstrapRegistrationError,
                TrustedBootstrapBindingError, NativeBootstrapError, ProducerIsolationError,
                ProducerProcessError, OSError, subprocess.SubprocessError) as exc:
            if not claimed:
                raise NativeTrustedAttemptError("native_trusted_attempt_claim_failed") from exc
            reason = getattr(exc, "code", "native_trusted_attempt_unknown")
        finally:
            for fd in tuple(fds):
                try:
                    os.close(fd)
                except OSError:
                    pass
            if process is not None:
                if owner is None:
                    # The native child has not passed the registration gate, so
                    # no target has been started. Its unreaped Popen PID cannot be reused.
                    if process.poll() is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                else:
                    result = _cleanup(owner, process, deadline=deadline, monotonic=monotonic)
                    cleanup_status = result.status.value
                    if result.status not in {ProcessCleanupStatus.CLEANED, ProcessCleanupStatus.ALREADY_EXITED}:
                        reason = "native_trusted_attempt_cleanup_unknown"
                try:
                    process.wait(timeout=max(0.0, deadline - monotonic()))
                except subprocess.TimeoutExpired:
                    reason = "native_trusted_attempt_reap_unknown"
            if session is not None and registration is not None:
                evidence = session.evidence()
                if evidence.status == "passed" and (
                    cleanup_status not in {"cleaned", "already_exited"} or exit_code is None
                ):
                    evidence = replace(evidence, status="unknown", evidence_sha256=None)
                try:
                    current = _read_durable_json(
                        batch / "process-registration.json",
                        code="native_trusted_attempt_registration_unknown",
                    )
                    if current != registration or _current_recovery_lock_identity(batch) != lock_identity:
                        raise ProducerProcessError("native_trusted_attempt_registration_unknown")
                    _atomic_json(batch / "trusted-bootstrap-evidence.json", evidence.to_dict(), exclusive=True)
                    persisted = _read_durable_json(
                        batch / "trusted-bootstrap-evidence.json",
                        code="native_trusted_attempt_evidence_write_unknown",
                    )
                    if persisted != evidence.to_dict():
                        raise ProducerProcessError("native_trusted_attempt_evidence_write_unknown")
                except ProducerProcessError:
                    reason = "native_trusted_attempt_evidence_write_unknown"
        return NativeTrustedAttemptObservation(
            launch_id=launch.launch_id, journal_id=launch.journal_id,
            status="recovery_required", reason=reason,
            registration_sha256=(str(registration["registration_sha256"]) if registration else None),
            gate_released=gate_released, target_started=target_started,
            exit_code=exit_code, cleanup_status=cleanup_status,
        )


__all__ = [
    "NativeTrustedAttemptError", "NativeTrustedAttemptObservation", "run_native_trusted_attempt",
]
