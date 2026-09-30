"""Provider-free native trusted-bootstrap attempt, without publication authority."""

from __future__ import annotations

import math
import os
import selectors
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from .native_bootstrap import (
    NativeBootstrapArtifact,
    NativeBootstrapError,
    encode_native_bootstrap_control,
    load_native_bootstrap_artifact,
    native_bootstrap_command,
)
from .native_trusted_capture import NativeTrustedCaptureError, capture_native_trusted_output
from .process_ownership import (
    ProcessCleanupStatus,
    RegisteredProcess,
    cleanup_registered_process,
)
from .producer_bootstrap import (
    BootstrapHandshakeFrame,
    ProducerBootstrapError,
    TrustedBootstrapSession,
    build_trusted_bootstrap_launch,
    observe_trusted_bootstrap_attempt,
    parse_bootstrap_handshake_frame,
)
from .producer_broker_ipc import (
    ProducerBrokerConfig,
    ProducerBrokerObservation,
    serve_producer_broker,
)
from .producer_isolation import ProducerIsolationError, build_producer_isolation_policy
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import (
    ProducerProcessError,
    _atomic_json,
    _cleanup,
    _current_process_owned,
    _current_recovery_lock_identity,
    _digest_without,
    _process_owner_identity,
    _read_durable_json,
    _recovery_lock,
    _relative_path,
    _safe_dir,
    _safe_root,
    _sha,
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


_TERMINAL_PROTOCOL = "lunar-native-trusted-process-terminal-v1"
_TERMINAL_NAME = "native-trusted-process-terminal.json"
_RECOVERY_PROTOCOL = "lunar-native-trusted-process-recovery-v1"
_RECOVERY_NAME = "native-trusted-process-recovery.json"
_CLEANUP_RESERVE_SECONDS = 0.25
_TERMINAL_FIELDS = frozenset({
    "schema_version", "protocol", "launch_id", "journal_id", "run_id",
    "parent_task_id", "task_id", "intent_sha256", "attestation_sha256",
    "consumption_sha256", "registration_sha256", "launch_sha256",
    "bootstrap_descriptor_sha256", "pid", "pgid", "owner_identity_sha256",
    "handoff_sha256", "bootstrap_evidence_sha256", "gate_released",
    "target_started", "exit_code", "cleanup_status", "process_status",
    "receipt_scope", "publication_eligible", "previous_receipt_sha256",
    "terminal_sha256",
})


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
    terminal_sha256: str | None = None
    output_capture_sha256: str | None = None
    broker_observation: ProducerBrokerObservation | None = None


def _terminal_receipt(
    registration: Mapping[str, object], *, handoff_sha256: str,
    evidence_sha256: str, gate_released: bool, target_started: bool,
    exit_code: int, cleanup_status: str,
) -> dict[str, object]:
    process_status = "exited_zero" if exit_code == 0 else "exited_nonzero"
    receipt: dict[str, object] = {
        "schema_version": "1", "protocol": _TERMINAL_PROTOCOL,
        **{key: registration[key] for key in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
            "intent_sha256", "attestation_sha256", "consumption_sha256",
            "registration_sha256", "launch_sha256", "bootstrap_descriptor_sha256",
            "pid", "pgid", "owner_identity_sha256",
        )},
        "handoff_sha256": handoff_sha256,
        "bootstrap_evidence_sha256": evidence_sha256,
        "gate_released": gate_released, "target_started": target_started,
        "exit_code": exit_code, "cleanup_status": cleanup_status,
        "process_status": process_status, "receipt_scope": "process_only",
        "publication_eligible": False,
        "previous_receipt_sha256": registration["registration_sha256"],
    }
    receipt["terminal_sha256"] = _digest_without(receipt, "terminal_sha256")
    return receipt


def _read_recovery_receipt(batch: Path, registration: Mapping[str, object]) -> dict[str, object] | None:
    path = batch / _RECOVERY_NAME
    try:
        os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise NativeTrustedAttemptError("native_trusted_recovery_receipt_invalid") from exc
    try:
        receipt = _read_durable_json(path, code="native_trusted_recovery_receipt_invalid")
    except ProducerProcessError as exc:
        raise NativeTrustedAttemptError("native_trusted_recovery_receipt_invalid") from exc
    bound = (
        "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
        "intent_sha256", "attestation_sha256", "consumption_sha256",
        "registration_sha256", "pid", "pgid", "owner_identity_sha256",
    )
    if (
        set(receipt) != {
            "schema_version", "protocol", "status", "execution_outcome", "reason",
            *bound, "previous_receipt_sha256", "cleanup_status", "term_sent",
            "kill_sent", "alive_after", "recovery_sha256",
        }
        or receipt.get("schema_version") != "1"
        or receipt.get("protocol") != _RECOVERY_PROTOCOL
        or receipt.get("status") != "recovery_required"
        or receipt.get("execution_outcome") != "unknown"
        or receipt.get("reason") != "native_trusted_attempt_terminal_receipt_missing"
        or receipt.get("previous_receipt_sha256") != registration["registration_sha256"]
        or any(receipt.get(key) != registration[key] for key in bound)
        or receipt.get("cleanup_status") not in {status.value for status in ProcessCleanupStatus}
        or any(not isinstance(receipt.get(key), bool) for key in (
            "term_sent", "kill_sent", "alive_after",
        ))
        or receipt.get("recovery_sha256") != _digest_without(receipt, "recovery_sha256")
    ):
        raise NativeTrustedAttemptError("native_trusted_recovery_receipt_invalid")
    return receipt


def _cleanup_recovered_attempt(
    batch: Path, registration: Mapping[str, object], lock_identity: tuple[int, int],
) -> dict[str, object]:
    if _read_recovery_receipt(batch, registration) is not None:
        raise NativeTrustedAttemptError("native_trusted_recovery_already_recorded")
    pid = registration["pid"]
    pgid = registration["pgid"]
    owner_identity = registration["owner_identity"]
    if (
        not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1
        or pgid != pid or not isinstance(owner_identity, dict)
        or registration.get("owner_identity_sha256") != _sha(owner_identity)
        or registration.get("recovery_lock_protocol") != "journal-flock-v1"
        or (registration.get("recovery_lock_device"), registration.get("recovery_lock_inode"))
        != lock_identity
    ):
        raise NativeTrustedAttemptError("native_trusted_recovery_registration_invalid")

    def owned() -> bool:
        try:
            current = _read_durable_json(
                batch / "process-registration.json",
                code="native_trusted_recovery_registration_invalid",
            )
            return (
                current == registration
                and _current_recovery_lock_identity(batch) == lock_identity
                and _process_owner_identity(pid) == owner_identity
            )
        except ProducerProcessError:
            return False

    result = cleanup_registered_process(
        RegisteredProcess(pid, pgid, owner_check=owned, label=str(registration["launch_id"])),
        grace_seconds=0.25,
    )
    receipt: dict[str, object] = {
        "schema_version": "1", "protocol": _RECOVERY_PROTOCOL,
        "status": "recovery_required", "execution_outcome": "unknown",
        "reason": "native_trusted_attempt_terminal_receipt_missing",
        **{key: registration[key] for key in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
            "intent_sha256", "attestation_sha256", "consumption_sha256",
            "registration_sha256", "pid", "pgid", "owner_identity_sha256",
        )},
        "previous_receipt_sha256": registration["registration_sha256"],
        "cleanup_status": result.status.value,
        "term_sent": result.term_sent, "kill_sent": result.kill_sent,
        "alive_after": result.alive_after,
    }
    receipt["recovery_sha256"] = _digest_without(receipt, "recovery_sha256")
    try:
        _atomic_json(batch / _RECOVERY_NAME, receipt, exclusive=True)
        if _read_recovery_receipt(batch, registration) != receipt:
            raise NativeTrustedAttemptError("native_trusted_recovery_receipt_write_unknown")
    except ProducerProcessError as exc:
        raise NativeTrustedAttemptError("native_trusted_recovery_receipt_write_unknown") from exc
    return receipt


def _observe_cancellation(cancelled: Callable[[], bool] | None) -> bool:
    """Observe caller cancellation without allowing a faulty callback to escape."""
    if cancelled is None:
        return False
    try:
        value = cancelled()
    except Exception as exc:
        raise NativeTrustedAttemptError(
            "native_trusted_attempt_cancellation_unknown"
        ) from exc
    if not isinstance(value, bool):
        raise NativeTrustedAttemptError("native_trusted_attempt_cancellation_invalid")
    return value


def _remaining(
    deadline: float,
    monotonic: Callable[[], float],
    cancelled: Callable[[], bool] | None = None,
) -> float:
    if _observe_cancellation(cancelled):
        raise NativeTrustedAttemptError("native_trusted_attempt_cancelled")
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise NativeTrustedAttemptError("native_trusted_attempt_wall_timeout")
    return remaining


def _compose_parent_deadline(
    intent: ProducerLaunchIntent,
    monotonic: Callable[[], float],
    parent_deadline: float | None,
) -> float:
    """Compose the attempt budget with an optional caller-owned deadline."""
    started = monotonic()
    if type(started) not in (int, float) or not math.isfinite(float(started)):
        raise NativeTrustedAttemptError("native_trusted_attempt_clock_invalid")
    own_deadline = float(started) + float(intent.wall_timeout_seconds)
    if parent_deadline is None:
        return own_deadline
    if type(parent_deadline) not in (int, float) or not math.isfinite(float(parent_deadline)):
        raise NativeTrustedAttemptError("native_trusted_attempt_parent_deadline_invalid")
    return min(own_deadline, float(parent_deadline))


def _wait_event(
    event: threading.Event,
    deadline: float,
    monotonic: Callable[[], float],
    cancelled: Callable[[], bool] | None = None,
) -> bool:
    """Wait in bounded slices so cancellation is observed during broker startup."""
    while True:
        remaining = _remaining(deadline, monotonic, cancelled)
        if event.wait(timeout=min(0.05, remaining)):
            return True


def _write_control(
    fd: int,
    data: bytes,
    deadline: float,
    monotonic: Callable[[], float],
    cancelled: Callable[[], bool] | None = None,
) -> None:
    os.set_blocking(fd, False)
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_WRITE)
        offset = 0
        while offset < len(data):
            remaining = _remaining(deadline, monotonic, cancelled)
            if not selector.select(min(0.05, remaining) if cancelled is not None else remaining):
                if cancelled is not None:
                    continue
                raise NativeTrustedAttemptError("native_trusted_attempt_wall_timeout")
            try:
                offset += os.write(fd, data[offset:])
            except BlockingIOError:
                continue


def _read_frame(
    fd: int,
    deadline: float,
    monotonic: Callable[[], float],
    cancelled: Callable[[], bool] | None = None,
) -> BootstrapHandshakeFrame:
    data = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        while True:
            remaining = _remaining(deadline, monotonic, cancelled)
            if not selector.select(min(0.05, remaining) if cancelled is not None else remaining):
                if cancelled is not None:
                    continue
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


def _read_attempt_frame(
    fd: int,
    deadline: float,
    monotonic: Callable[[], float],
    cancelled: Callable[[], bool] | None,
) -> BootstrapHandshakeFrame:
    # Keep the historical three-argument call shape when no callback is supplied;
    # a few embedders instrument this private helper in their local harnesses.
    if cancelled is None:
        return _read_frame(fd, deadline, monotonic)
    return _read_frame(fd, deadline, monotonic, cancelled)


def _write_attempt_control(
    fd: int,
    data: bytes,
    deadline: float,
    monotonic: Callable[[], float],
    cancelled: Callable[[], bool] | None,
) -> None:
    if cancelled is None:
        _write_control(fd, data, deadline, monotonic)
    else:
        _write_control(fd, data, deadline, monotonic, cancelled)


def run_native_trusted_attempt(
    workspace: str | Path,
    *,
    producer_root: str | Path,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact,
    broker_config: ProducerBrokerConfig | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] | None = None,
    parent_deadline: float | None = None,
) -> NativeTrustedAttemptObservation:
    """Run one locally isolated target under a durable pre-gate registration.

    A consumed attempt always remains recovery-required until the full execution
    receipt, request broker, and publication boundary are implemented.
    """
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(attestation, ProducerLaunchAttestation):
        raise NativeTrustedAttemptError("native_trusted_attempt_admission_invalid")
    if not isinstance(artifact, NativeBootstrapArtifact):
        raise NativeTrustedAttemptError("native_trusted_attempt_artifact_invalid")
    if broker_config is not None and type(broker_config) is not ProducerBrokerConfig:
        raise NativeTrustedAttemptError("native_trusted_attempt_broker_invalid")
    if cancelled is not None and not callable(cancelled):
        raise NativeTrustedAttemptError("native_trusted_attempt_cancellation_invalid")
    if _observe_cancellation(cancelled):
        raise NativeTrustedAttemptError("native_trusted_attempt_cancelled")
    deadline = _compose_parent_deadline(intent, monotonic, parent_deadline)
    _remaining(deadline, monotonic, cancelled)
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
        terminal_sha256: str | None = None
        output_capture_sha256: str | None = None
        handoff_sha256: str | None = None
        claimed = False
        fds: set[int] = set()
        broker_thread: threading.Thread | None = None
        broker_ready: threading.Event | None = None
        broker_state: dict[str, object] = {}
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
                broker_child_fds: tuple[int, int] = ()
                broker_env = {"PATH": os.defpath, "LANG": "C"}
                if broker_config is not None:
                    request_read, request_write = os.pipe()
                    response_read, response_write = os.pipe()
                    fds.update((request_read, request_write, response_read, response_write))
                    broker_child_fds = (request_write, response_read)
                    broker_env["LUNAR_PRODUCER_REQUEST_FD"] = str(request_write)
                    broker_env["LUNAR_PRODUCER_RESPONSE_FD"] = str(response_read)
                    broker_ready = threading.Event()
                    broker_deadline_ns = time.monotonic_ns() + int(
                        _remaining(deadline, monotonic, cancelled) * 1_000_000_000
                    )

                    def serve() -> None:
                        try:
                            broker_state["observation"] = serve_producer_broker(
                                request_read, response_write, intent=intent,
                                journal_dir=batch / ".host-request-journal",
                                config=broker_config, deadline_ns=broker_deadline_ns,
                                ready=broker_ready,
                            )
                        except Exception:  # noqa: BLE001 - fixed-code thread boundary
                            broker_state["error"] = "native_trusted_attempt_broker_unknown"
                        finally:
                            broker_ready.set()
                            for fd in (request_read, response_write):
                                try:
                                    os.close(fd)
                                except OSError:
                                    broker_state["error"] = "native_trusted_attempt_broker_unknown"

                command = native_bootstrap_command(
                    pair.bootstrap.executable, control_fd=control_read,
                    gate_fd=gate_read, frame_fd=frame_write,
                )
                _remaining(deadline, monotonic, cancelled)
                process = subprocess.Popen(
                    command, executable=pair.bootstrap.executable,
                    shell=False, start_new_session=True, close_fds=True,
                    pass_fds=(control_read, gate_read, frame_write, *pair.pass_fds,
                              *broker_child_fds),
                    cwd=str(working), env=broker_env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                for fd in (control_read, gate_read, frame_write):
                    os.close(fd)
                    fds.remove(fd)
                if broker_config is not None:
                    for fd in broker_child_fds:
                        os.close(fd)
                        fds.remove(fd)
                    broker_thread = threading.Thread(target=serve, daemon=True)
                    broker_thread.start()
                    # Only the broker thread closes its controller-side descriptors.
                    fds.remove(request_read)
                    fds.remove(response_write)
                _write_attempt_control(control_write, control, deadline, monotonic, cancelled)
                os.close(control_write)
                fds.remove(control_write)
                ready = _read_attempt_frame(frame_read, deadline, monotonic, cancelled)
                if ready.kind != "bootstrap_ready" or ready.sequence != 1:
                    raise NativeTrustedAttemptError("native_trusted_attempt_ready_invalid")
                published = publish_trusted_bootstrap_registration(
                    root, launch=launch, descriptor=installed.descriptor, intent=intent,
                    attestation=attestation, pair=pair, process=process, ready_frame=ready,
                    recovery_lock_identity=lock_identity, deadline=deadline, monotonic=monotonic,
                )
                registration = published.registration
                handoff_sha256 = str(published.handoff["handoff_sha256"])
                observed = observe_trusted_bootstrap_attempt(
                    root, launch=launch, descriptor=installed.descriptor,
                    intent=intent, attestation=attestation, require_handoff=True,
                    deadline=deadline, monotonic=monotonic,
                )
                if (
                    observed.get("status") != "recovery_required"
                    or observed.get("reason") != "trusted_bootstrap_terminal_evidence_missing"
                    or observed.get("registration_sha256") != registration["registration_sha256"]
                    or observed.get("handoff_sha256") != published.handoff["handoff_sha256"]
                ):
                    raise NativeTrustedAttemptError("native_trusted_attempt_handoff_unknown")
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
                if broker_ready is not None and (
                    not _wait_event(broker_ready, deadline, monotonic, cancelled)
                    or "error" in broker_state
                ):
                    raise NativeTrustedAttemptError("native_trusted_attempt_broker_unknown")
                _remaining(deadline, monotonic, cancelled)
                if _observe_cancellation(cancelled):
                    raise NativeTrustedAttemptError("native_trusted_attempt_cancelled")
                os.write(gate_write, b"1")
                os.close(gate_write)
                fds.remove(gate_write)
                gate_released = True
                session.release(launch.gate_nonce)
                # Keep a small slice of the attempt budget available for the owner-checked
                # cleanup path. This remains inside the caller deadline; it only makes a
                # late frame timeout conservative instead of entering cleanup with no budget.
                execution_deadline = deadline - _CLEANUP_RESERVE_SECONDS
                started = _read_attempt_frame(frame_read, execution_deadline, monotonic, cancelled)
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
                terminal = _read_attempt_frame(frame_read, execution_deadline, monotonic, cancelled)
                session.accept_frame(terminal)
                if (
                    terminal.kind != "terminal" or terminal.sequence != 3
                    or terminal.launch_sha256 != launch.launch_sha256
                    or terminal.intent_sha256 != launch.intent_sha256
                ):
                    raise NativeTrustedAttemptError("native_trusted_attempt_terminal_unknown")
                while True:
                    remaining = _remaining(deadline, monotonic, cancelled)
                    if remaining <= _CLEANUP_RESERVE_SECONDS:
                        raise NativeTrustedAttemptError("native_trusted_attempt_wall_timeout")
                    try:
                        exit_code = process.wait(
                            timeout=min(0.05, remaining)
                        )
                        break
                    except subprocess.TimeoutExpired:
                        continue
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
                    if reason == "native_trusted_attempt_terminal_receipt_missing":
                        reason = "native_trusted_attempt_reap_unknown"
            if broker_thread is not None:
                broker_thread.join(timeout=max(0.0, deadline - monotonic()))
                if broker_thread.is_alive() or "error" in broker_state:
                    reason = "native_trusted_attempt_broker_unknown"
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
        if (
            registration is not None and session is not None and handoff_sha256 is not None
            and reason == "native_trusted_attempt_terminal_receipt_missing"
            and exit_code is not None
            and cleanup_status in {"cleaned", "already_exited"}
        ):
            try:
                observed = observe_trusted_bootstrap_attempt(
                    root, launch=launch, descriptor=installed.descriptor,
                    intent=intent, attestation=attestation, require_handoff=True,
                    deadline=deadline, monotonic=monotonic,
                )
                if (
                    observed.get("status") != "evidence_available"
                    or observed.get("bootstrap_status") != "passed"
                    or observed.get("registration_sha256") != registration["registration_sha256"]
                    or observed.get("handoff_sha256") != handoff_sha256
                ):
                    raise NativeTrustedAttemptError("native_trusted_attempt_terminal_evidence_unknown")
                receipt = _terminal_receipt(
                    registration, handoff_sha256=handoff_sha256,
                    evidence_sha256=str(observed["evidence_sha256"]),
                    gate_released=gate_released, target_started=target_started,
                    exit_code=exit_code, cleanup_status=cleanup_status,
                )
                _remaining(deadline, monotonic, cancelled)
                _atomic_json(batch / _TERMINAL_NAME, receipt, exclusive=True)
                stored = _read_durable_json(
                    batch / _TERMINAL_NAME, code="native_trusted_attempt_terminal_write_unknown",
                )
                if stored != receipt:
                    raise NativeTrustedAttemptError("native_trusted_attempt_terminal_write_unknown")
                terminal_sha256 = str(receipt["terminal_sha256"])
                reason = (
                    "native_trusted_attempt_request_and_output_unverified"
                    if exit_code == 0 else "native_trusted_attempt_exit_failed"
                )
            except (NativeTrustedAttemptError, ProducerBootstrapError) as exc:
                reason = exc.code
            except ProducerProcessError:
                reason = "native_trusted_attempt_terminal_write_unknown"
        broker_observation = broker_state.get("observation")
        if (
            broker_config is not None and gate_released
            and reason == "native_trusted_attempt_request_and_output_unverified"
            and (not isinstance(broker_observation, ProducerBrokerObservation)
                 or not broker_observation.complete)
        ):
            reason = "native_trusted_attempt_broker_unknown"
        if (
            terminal_sha256 is not None and exit_code == 0
            and reason == "native_trusted_attempt_request_and_output_unverified"
        ):
            try:
                captured = capture_native_trusted_output(
                    batch, intent=intent, terminal_sha256=terminal_sha256,
                    broker=(broker_observation if isinstance(
                        broker_observation, ProducerBrokerObservation,
                    ) else None),
                    deadline=deadline, monotonic=monotonic,
                )
                output_capture_sha256 = str(captured["capture_sha256"])
            except NativeTrustedCaptureError:
                reason = "native_trusted_attempt_output_capture_unknown"
        return NativeTrustedAttemptObservation(
            launch_id=launch.launch_id, journal_id=launch.journal_id,
            status="recovery_required", reason=reason,
            registration_sha256=(str(registration["registration_sha256"]) if registration else None),
            gate_released=gate_released, target_started=target_started,
            exit_code=exit_code, cleanup_status=cleanup_status,
            terminal_sha256=terminal_sha256,
            output_capture_sha256=output_capture_sha256,
            broker_observation=(broker_observation if isinstance(
                broker_observation, ProducerBrokerObservation,
            ) else None),
        )


def recover_native_trusted_attempt(
    workspace: str | Path, *, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
    cleanup: bool = False,
) -> dict[str, object]:
    """Inspect one native attempt; explicit cleanup never relaunches its target.

    A process-only terminal receipt is diagnostic. It never authorizes bundle
    publication because request and output evidence are outside this slice.
    """
    if not isinstance(cleanup, bool) or not isinstance(artifact, NativeBootstrapArtifact):
        raise NativeTrustedAttemptError("native_trusted_recovery_context_invalid")
    try:
        launch = build_trusted_bootstrap_launch(intent, attestation, artifact.descriptor)
        root = _safe_root(workspace)
        batch = root / "evolution" / "producer-batches" / launch.journal_id
    except (ProducerBootstrapError, ProducerProcessError, TypeError, ValueError) as exc:
        raise NativeTrustedAttemptError("native_trusted_recovery_context_invalid") from exc

    def inspect(lock_identity: tuple[int, int] | None = None) -> dict[str, object]:
        try:
            observed = observe_trusted_bootstrap_attempt(
                root, launch=launch, descriptor=artifact.descriptor,
                intent=intent, attestation=attestation, require_handoff=False,
            )
        except ProducerBootstrapError as exc:
            if exc.code in {
                "producer_bootstrap_attempt_claim_missing",
                "producer_bootstrap_attempt_registration_missing",
            }:
                return {
                    "status": "recovery_required", "reason": exc.code,
                    "launch_id": launch.launch_id, "journal_id": launch.journal_id,
                }
            raise NativeTrustedAttemptError("native_trusted_recovery_evidence_invalid") from exc
        registration = _read_durable_json(
            batch / "process-registration.json", code="native_trusted_recovery_registration_invalid",
        )
        if registration.get("registration_sha256") != observed.get("registration_sha256"):
            raise NativeTrustedAttemptError("native_trusted_recovery_registration_invalid")
        if lock_identity is not None and (
            registration.get("recovery_lock_device"), registration.get("recovery_lock_inode")
        ) != lock_identity:
            raise NativeTrustedAttemptError("native_trusted_recovery_registration_invalid")
        path = batch / _TERMINAL_NAME
        try:
            os.lstat(path)
        except FileNotFoundError:
            prior = _read_recovery_receipt(batch, registration)
            if prior is not None:
                if cleanup:
                    raise NativeTrustedAttemptError("native_trusted_recovery_already_recorded")
                return prior
            if cleanup:
                if lock_identity is None:
                    raise NativeTrustedAttemptError("native_trusted_recovery_lock_required")
                return _cleanup_recovered_attempt(batch, registration, lock_identity)
            return {
                "status": "recovery_required",
                "reason": "native_trusted_attempt_terminal_receipt_missing",
                "launch_id": launch.launch_id, "journal_id": launch.journal_id,
                "registration_sha256": registration["registration_sha256"],
                "pid": registration["pid"], "pgid": registration["pgid"],
            }
        except OSError as exc:
            raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid") from exc
        if _read_recovery_receipt(batch, registration) is not None:
            raise NativeTrustedAttemptError("native_trusted_recovery_conflicting_receipts")
        try:
            bound = observe_trusted_bootstrap_attempt(
                root, launch=launch, descriptor=artifact.descriptor,
                intent=intent, attestation=attestation, require_handoff=True,
            )
            receipt = _read_durable_json(path, code="native_trusted_recovery_terminal_invalid")
        except (ProducerBootstrapError, ProducerProcessError) as exc:
            raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid") from exc
        if (
            bound.get("status") != "evidence_available"
            or bound.get("bootstrap_status") != "passed"
            or set(receipt) != _TERMINAL_FIELDS
            or isinstance(receipt.get("exit_code"), bool)
            or not isinstance(receipt.get("exit_code"), int)
            or not -255 <= receipt["exit_code"] <= 255
            or receipt.get("cleanup_status") not in {"cleaned", "already_exited"}
            or receipt.get("gate_released") is not True
            or receipt.get("target_started") is not True
        ):
            raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid")
        expected = _terminal_receipt(
            registration, handoff_sha256=str(bound["handoff_sha256"]),
            evidence_sha256=str(bound["evidence_sha256"]),
            gate_released=True, target_started=True,
            exit_code=receipt["exit_code"], cleanup_status=str(receipt["cleanup_status"]),
        )
        if receipt != expected:
            raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid")
        return receipt

    if cleanup:
        try:
            with _recovery_lock(batch) as lock_identity:
                return inspect(lock_identity)
        except ProducerProcessError as exc:
            raise NativeTrustedAttemptError("native_trusted_recovery_cleanup_unknown") from exc
    try:
        return inspect()
    except ProducerProcessError as exc:
        raise NativeTrustedAttemptError("native_trusted_recovery_evidence_invalid") from exc


__all__ = [
    "NativeTrustedAttemptError", "NativeTrustedAttemptObservation",
    "recover_native_trusted_attempt", "run_native_trusted_attempt",
]
