"""Provider-free native trusted-bootstrap attempt, without publication authority."""

from __future__ import annotations

import hashlib
import math
import os
import selectors
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path

from .native_bootstrap import (
    LINUX_CHILD_SUPERVISION,
    LINUX_FD_CONTROL_IMPLEMENTATION,
    LINUX_FD_HANDOFF_IMPLEMENTATION,
    LINUX_GRANT_OBJECT_BINDING,
    LINUX_GRANT_OBJECT_IMPLEMENTATION,
    LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION,
    LINUX_INPUT_MUTATION_IMPLEMENTATION,
    LINUX_IPC_CONTROL_IMPLEMENTATION,
    NativeBootstrapArtifact,
    NativeBootstrapError,
    encode_native_bootstrap_control,
    encode_native_bootstrap_control_v2,
    load_native_bootstrap_artifact,
    native_bootstrap_command,
)
from .native_deadline_binding import (
    NativeDeadlineBindingError,
    deadline_binding_digest,
    persist_native_deadline_binding,
    verify_native_deadline_binding,
)
from .native_grant_inputs import NativeGrantInputError, original_native_grant_inputs
from .native_guardian import NativeGuardianError, NativeGuardianOwner, start_native_guardian
from .native_trusted_capture import NativeTrustedCaptureError, capture_native_trusted_output
from .native_trusted_cleanup import (
    NativeTrustedCleanupError,
    persist_native_trusted_cleanup,
    recover_native_trusted_cleanup,
    verify_native_trusted_cleanup,
)
from .native_trusted_streams import (
    NativeTrustedStreamCapture,
    NativeTrustedStreamError,
    NativeTrustedStreamObservation,
    persist_native_trusted_stream_capture,
    recover_native_trusted_stream_capture,
    start_native_trusted_stream_capture,
)
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
from .producer_bundle_deadline import _boot_id as _producer_boot_id
from .producer_grant_anchors import ProducerGrantError, ProducerGrantRequest, hold_producer_grants
from .producer_isolation import ProducerIsolationError, build_producer_isolation_policy
from .producer_launch_inputs import (
    PRODUCER_LAUNCH_INPUT_MARKER,
    ProducerLaunchInputDescriptor,
    ProducerLaunchInputError,
    validate_producer_launch_inputs,
)
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import (
    ProducerProcessError,
    _atomic_json,
    _canonical,
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
from .rsi_native_inputs import (
    NATIVE_RSI_INPUT_MARKER,
    NativeRSIInputDescriptor,
    NativeRSIInputError,
    validate_native_rsi_launch_inputs,
)
from .trusted_bootstrap_binding import TrustedBootstrapBindingError, prepare_trusted_executable_pair
from .trusted_bootstrap_registration import (
    TrustedBootstrapRegistrationError,
    _claim_bytes,
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
_RECOVERY_PROTOCOL_V2 = "lunar-native-trusted-process-recovery-v2"
_RECOVERY_NAME = "native-trusted-process-recovery.json"
_DEADLINE_PROTOCOL = "lunar-native-trusted-attempt-deadline-v1"
_DEADLINE_NAME = "native-trusted-attempt-deadline.json"
_AUDIT_PROTOCOL = "lunar-native-trusted-execution-audit-v1"
_AUDIT_NAME = "native-trusted-execution-audit.json"
_CLEANUP_RESERVE_SECONDS = 0.25
_TERMINAL_FIELDS = frozenset({
    "schema_version", "protocol", "launch_id", "journal_id", "run_id",
    "parent_task_id", "task_id", "intent_sha256", "attestation_sha256",
    "consumption_sha256", "registration_sha256", "launch_sha256",
    "bootstrap_descriptor_sha256", "pid", "pgid", "owner_identity_sha256",
    "handoff_sha256", "bootstrap_evidence_sha256", "deadline_sha256", "gate_released",
    "target_started", "exit_code", "cleanup_status", "process_status",
    "receipt_scope", "publication_eligible", "previous_receipt_sha256",
    "terminal_sha256", "stream_capture_sha256", "cleanup_sha256",
})
_DEADLINE_FIELDS = frozenset({
    "schema_version", "protocol", "launch_id", "journal_id", "launch_sha256",
    "intent_sha256", "attestation_sha256",
    "started_monotonic", "deadline_monotonic", "boot_id", "deadline_sha256",
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
    stream_capture_sha256: str | None = None
    stream_observation: NativeTrustedStreamObservation | None = None
    broker_observation: ProducerBrokerObservation | None = None


def _terminal_receipt(
    registration: Mapping[str, object], *, handoff_sha256: str,
    evidence_sha256: str, gate_released: bool, target_started: bool,
    exit_code: int | None, cleanup_status: str, deadline_sha256: str,
    cancelled: bool = False, stream_capture_sha256: str | None = None,
    cleanup_sha256: str | None = None,
) -> dict[str, object]:
    if cancelled and exit_code is not None:
        raise NativeTrustedAttemptError("native_trusted_attempt_terminal_invalid")
    if not cancelled and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
        raise NativeTrustedAttemptError("native_trusted_attempt_terminal_invalid")
    process_status = "cancelled" if cancelled else (
        "exited_zero" if exit_code == 0 else "exited_nonzero"
    )
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
        "deadline_sha256": deadline_sha256,
        "gate_released": gate_released, "target_started": target_started,
        "exit_code": exit_code, "cleanup_status": cleanup_status,
        "process_status": process_status, "receipt_scope": "process_only",
        "publication_eligible": False,
        "previous_receipt_sha256": registration["registration_sha256"],
        "stream_capture_sha256": stream_capture_sha256,
        "cleanup_sha256": cleanup_sha256,
    }
    receipt["terminal_sha256"] = _digest_without(receipt, "terminal_sha256")
    return receipt


def _compose_attempt_budget(
    intent: ProducerLaunchIntent,
    monotonic: Callable[[], float],
    parent_deadline: float | None,
) -> tuple[float, float]:
    """Return the attempt start and its single effective monotonic deadline."""
    started = monotonic()
    if type(started) not in (int, float) or not math.isfinite(float(started)):
        raise NativeTrustedAttemptError("native_trusted_attempt_clock_invalid")
    own_deadline = float(started) + float(intent.wall_timeout_seconds)
    if parent_deadline is None:
        return float(started), own_deadline
    if type(parent_deadline) not in (int, float) or not math.isfinite(float(parent_deadline)):
        raise NativeTrustedAttemptError("native_trusted_attempt_parent_deadline_invalid")
    return float(started), min(own_deadline, float(parent_deadline))


def _native_launch_inputs(
    workspace: str | Path, *, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
    require_unexpired: bool,
) -> NativeRSIInputDescriptor | ProducerLaunchInputDescriptor | None:
    """Inspect optional input delivery without changing legacy launch bytes.

    Each protocol pins its marker in the original attested argv. This first producer-config
    slice keeps the protocols exclusive, rather than weakening RSI's exact terminal-marker
    contract. Missing markers cannot downgrade either protocol's retained input binding.
    """
    if (NATIVE_RSI_INPUT_MARKER in intent.argv
            and PRODUCER_LAUNCH_INPUT_MARKER in intent.argv):
        raise NativeTrustedAttemptError("native_trusted_attempt_launch_inputs_conflict")
    try:
        rsi = validate_native_rsi_launch_inputs(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
            require_unexpired=require_unexpired,
        )
        producer = validate_producer_launch_inputs(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
            require_unexpired=require_unexpired,
        )
    except (NativeRSIInputError, ProducerLaunchInputError) as exc:
        raise NativeTrustedAttemptError(exc.code) from exc
    if rsi is not None and producer is not None:
        raise NativeTrustedAttemptError("native_trusted_attempt_launch_inputs_conflict")
    return rsi if rsi is not None else producer


def _revalidate_native_launch_inputs(
    expected: NativeRSIInputDescriptor | ProducerLaunchInputDescriptor | None,
    workspace: str | Path, *, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
    require_unexpired: bool,
) -> None:
    if _native_launch_inputs(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
        require_unexpired=require_unexpired,
    ) != expected:
        code = ("rsi_native_inputs_binding_changed" if isinstance(expected, NativeRSIInputDescriptor)
                else "native_trusted_attempt_launch_inputs_binding_changed")
        raise NativeTrustedAttemptError(code)


def _deadline_record(
    launch: object,
    *,
    started: float,
    deadline: float,
) -> dict[str, object]:
    if type(started) not in (int, float) or not math.isfinite(float(started)):
        raise NativeTrustedAttemptError("native_trusted_attempt_clock_invalid")
    if type(deadline) not in (int, float) or not math.isfinite(float(deadline)):
        raise NativeTrustedAttemptError("native_trusted_attempt_clock_invalid")
    if float(deadline) <= float(started):
        raise NativeTrustedAttemptError("native_trusted_attempt_clock_invalid")
    try:
        boot_id = _producer_boot_id()
    except Exception as exc:
        raise NativeTrustedAttemptError("native_trusted_attempt_boot_identity_unknown") from exc
    record: dict[str, object] = {
        "schema_version": "1", "protocol": _DEADLINE_PROTOCOL,
        "launch_id": launch.launch_id, "journal_id": launch.journal_id,
        "launch_sha256": launch.launch_sha256,
        "intent_sha256": launch.intent_sha256,
        "attestation_sha256": launch.attestation_sha256,
        "started_monotonic": float(started), "deadline_monotonic": float(deadline),
        "boot_id": boot_id,
    }
    record["deadline_sha256"] = _digest_without(record, "deadline_sha256")
    return record


def _persist_deadline(
    batch: Path, launch: object, *, started: float, deadline: float,
) -> tuple[dict[str, object], dict[str, object]]:
    record = _deadline_record(launch, started=started, deadline=deadline)
    try:
        binding = persist_native_deadline_binding(batch, record=record)
    except NativeDeadlineBindingError as exc:
        if exc.code == "native_deadline_binding_conflict":
            # A retained deadline is evidence that this launch already entered the
            # admission path. Never replace it with a newly allocated budget.
            raise NativeTrustedAttemptError("native_trusted_attempt_claim_failed") from exc
        raise NativeTrustedAttemptError("native_trusted_attempt_deadline_write_unknown") from exc
    return record, binding


def _check_live_deadline(
    root: Path, batch: Path, *, attestation: ProducerLaunchAttestation,
    binding: Mapping[str, object], record: Mapping[str, object],
    claim: Mapping[str, object] | None,
) -> None:
    """Recheck admission's frozen file and both original claim bytes without recapturing."""
    try:
        verify_native_deadline_binding(batch, binding=binding, expected_record=record)
        if claim is not None:
            nonce_key = hashlib.sha256(attestation.nonce.encode("utf-8")).hexdigest()
            expected = _canonical(claim)
            for path in (
                batch / "attestation-consumption.json",
                root / "evolution" / "producer-nonces" / f"{nonce_key}.json",
            ):
                if _claim_bytes(path)[0] != expected:
                    raise NativeTrustedAttemptError("native_trusted_attempt_deadline_binding_changed")
        verify_native_deadline_binding(batch, binding=binding, expected_record=record)
    except (NativeDeadlineBindingError, TrustedBootstrapRegistrationError) as exc:
        raise NativeTrustedAttemptError("native_trusted_attempt_deadline_binding_changed") from exc


def _verify_deadline_record(
    record: object, registration: Mapping[str, object],
) -> dict[str, object]:
    """Pure binding check; the filesystem recovery separately verifies the current boot."""
    if not isinstance(record, Mapping):
        raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid")
    if set(record) != _DEADLINE_FIELDS:
        raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid")
    if (
        record.get("schema_version") != "1"
        or record.get("protocol") != _DEADLINE_PROTOCOL
        or record.get("launch_id") != registration.get("launch_id")
        or record.get("journal_id") != registration.get("journal_id")
        or record.get("launch_sha256") != registration.get("launch_sha256")
        or record.get("intent_sha256") != registration.get("intent_sha256")
        or record.get("attestation_sha256") != registration.get("attestation_sha256")
    ):
        raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid")
    started = record.get("started_monotonic")
    deadline = record.get("deadline_monotonic")
    if type(started) not in (int, float) or type(deadline) not in (int, float):
        raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid")
    try:
        started_value, deadline_value = float(started), float(deadline)
    except (OverflowError, ValueError) as exc:
        raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid") from exc
    if (
        not math.isfinite(started_value)
        or not math.isfinite(deadline_value)
        or deadline_value <= started_value
        or not isinstance(record.get("boot_id"), str)
        or record.get("deadline_sha256") != _digest_without(record, "deadline_sha256")
    ):
        raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid")
    if not record["boot_id"]:
        raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid")
    return dict(record)


def _read_deadline(
    batch: Path, registration: Mapping[str, object], *, binding: Mapping[str, object] | None = None,
) -> dict[str, object]:
    try:
        if binding is not None:
            record = verify_native_deadline_binding(batch, binding=binding)
        else:
            record = _read_durable_json(
                batch / _DEADLINE_NAME, code="native_trusted_recovery_deadline_invalid",
            )
    except (ProducerProcessError, NativeDeadlineBindingError) as exc:
        raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid") from exc
    record = _verify_deadline_record(record, registration)
    try:
        current_boot_id = _producer_boot_id()
    except Exception as exc:
        raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid") from exc
    if record["boot_id"] != current_boot_id:
        raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid")
    if binding is not None:
        try:
            verify_native_deadline_binding(batch, binding=binding, expected_record=record)
        except NativeDeadlineBindingError as exc:
            raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid") from exc
    return record


def _read_recovery_receipt(
    batch: Path, registration: Mapping[str, object], *, binding: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
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
    pin_fields = {"deadline_sha256", "deadline_binding_sha256"} if binding is not None else set()
    if (
        set(receipt) != {
            "schema_version", "protocol", "status", "execution_outcome", "reason",
            *bound, "previous_receipt_sha256", "cleanup_status", "term_sent",
            "kill_sent", "alive_after", "recovery_sha256", *pin_fields,
        }
        or receipt.get("schema_version") != ("2" if binding is not None else "1")
        or receipt.get("protocol") != (_RECOVERY_PROTOCOL_V2 if binding is not None else _RECOVERY_PROTOCOL)
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
    if binding is not None and (
        receipt["deadline_sha256"] != binding["deadline_sha256"]
        or receipt["deadline_binding_sha256"] != deadline_binding_digest(binding)
    ):
        raise NativeTrustedAttemptError("native_trusted_recovery_receipt_invalid")
    return receipt


def _cleanup_recovered_attempt(
    batch: Path, registration: Mapping[str, object], lock_identity: tuple[int, int],
    *, binding: Mapping[str, object], verify_context: Callable[[], dict[str, object]],
) -> dict[str, object]:
    deadline_record = verify_context()
    if _read_recovery_receipt(batch, registration, binding=binding) is not None:
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
            verify_context()
            current = _read_durable_json(
                batch / "process-registration.json",
                code="native_trusted_recovery_registration_invalid",
            )
            matches = (
                current == registration
                and _current_recovery_lock_identity(batch) == lock_identity
                and _process_owner_identity(pid) == owner_identity
            )
            verify_context()
            return matches
        except (ProducerProcessError, NativeTrustedAttemptError):
            return False

    result = cleanup_registered_process(
        RegisteredProcess(pid, pgid, owner_check=owned, label=str(registration["launch_id"])),
        # Recovery must consume the original attempt budget.  Passing the retained
        # absolute deadline prevents a post-crash cleanup from receiving a fresh grace
        # window after the original wall budget has expired.
        grace_seconds=_CLEANUP_RESERVE_SECONDS,
        deadline=float(deadline_record["deadline_monotonic"]),
    )
    # ALREADY_EXITED bypasses the owner predicate. A TERM already sent cannot be undone,
    # but later drift must still forbid another signal or a trusted recovery receipt.
    verify_context()
    receipt: dict[str, object] = {
        "schema_version": "2", "protocol": _RECOVERY_PROTOCOL_V2,
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
        "deadline_sha256": binding["deadline_sha256"],
        "deadline_binding_sha256": deadline_binding_digest(binding),
    }
    receipt["recovery_sha256"] = _digest_without(receipt, "recovery_sha256")
    try:
        verify_context()
        _atomic_json(batch / _RECOVERY_NAME, receipt, exclusive=True)
        verify_context()
        if _read_recovery_receipt(batch, registration, binding=binding) != receipt:
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


def _native_guard_deadline(
    deadline: float,
    monotonic: Callable[[], float],
    cancelled: Callable[[], bool] | None,
) -> int:
    """Map the frozen budget once, sampling native time before the caller clock.

    Sampling in this order is conservative even if a trusted harness clock has a
    different epoch or is slow to return. Setup consumes this absolute native budget;
    bootstrap reception and the broker must never reissue the remaining duration.
    """
    native_sample = time.monotonic_ns()
    remaining = _remaining(deadline, monotonic, cancelled)
    if type(native_sample) is not int or native_sample < 0 or not math.isfinite(remaining):
        raise NativeTrustedAttemptError("native_trusted_attempt_clock_invalid")
    remaining_ns = remaining * 1_000_000_000
    if not math.isfinite(remaining_ns):
        raise NativeTrustedAttemptError("native_trusted_attempt_clock_invalid")
    native_deadline = native_sample + int(remaining_ns)
    if not 0 < native_deadline <= 0xFFFFFFFFFFFFFFFF:
        raise NativeTrustedAttemptError("native_trusted_attempt_clock_invalid")
    return native_deadline


def _compose_parent_deadline(
    intent: ProducerLaunchIntent,
    monotonic: Callable[[], float],
    parent_deadline: float | None,
) -> float:
    """Compose the attempt budget with an optional caller-owned deadline."""
    return _compose_attempt_budget(intent, monotonic, parent_deadline)[1]


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


@contextmanager
def _original_attempt_grants(inputs, *, batch: Path, working: Path, output: Path, enabled: bool):
    if not enabled:
        with nullcontext(None) as owner:
            yield owner
        return
    try:
        original = original_native_grant_inputs(inputs)
        requests = tuple(ProducerGrantRequest(path, "writable-directory")
                         for path in sorted({str(working), str(output)}))
        requests += (ProducerGrantRequest(str(working), "cwd"), *original.requests)
        with hold_producer_grants(
            requests, expected_bindings=original.expected_bindings,
            create_writable_directories=True, creation_root=str(batch),
        ) as owner:
            owner.validate_protected_materials(original.materials)
            yield owner
    except (ProducerGrantError, NativeGrantInputError) as exc:
        raise NativeTrustedAttemptError("native_trusted_attempt_grant_objects_changed") from exc


def _check_original_attempt_grants(owner, inputs) -> None:
    if owner is not None:
        try:
            owner.validate_protected_materials(original_native_grant_inputs(inputs).materials)
        except (ProducerGrantError, NativeGrantInputError) as exc:
            raise NativeTrustedAttemptError("native_trusted_attempt_grant_objects_changed") from exc


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
    if (
        artifact.descriptor.platform_execution_mode == "linux-fd-bound"
        and artifact.descriptor.implementation_version not in {
            LINUX_INPUT_MUTATION_IMPLEMENTATION, LINUX_FD_HANDOFF_IMPLEMENTATION, LINUX_FD_CONTROL_IMPLEMENTATION,
            LINUX_GRANT_OBJECT_IMPLEMENTATION, LINUX_IPC_CONTROL_IMPLEMENTATION, LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION,
        }
    ):
        # Reject before budget persistence, nonce consumption or spawn. Read-only recovery
        # deliberately keeps its historical descriptor and process-only evidence contract.
        raise NativeTrustedAttemptError("native_trusted_attempt_input_mutation_required")
    if (
        artifact.descriptor.platform_execution_mode == "linux-fd-bound"
        and artifact.descriptor.implementation_version not in {
            LINUX_FD_HANDOFF_IMPLEMENTATION, LINUX_FD_CONTROL_IMPLEMENTATION, LINUX_GRANT_OBJECT_IMPLEMENTATION, LINUX_IPC_CONTROL_IMPLEMENTATION, LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION,
        }
    ):
        raise NativeTrustedAttemptError("native_trusted_attempt_fd_handoff_required")
    if (
        artifact.descriptor.platform_execution_mode == "linux-fd-bound"
        and artifact.descriptor.implementation_version not in {LINUX_FD_CONTROL_IMPLEMENTATION, LINUX_GRANT_OBJECT_IMPLEMENTATION, LINUX_IPC_CONTROL_IMPLEMENTATION, LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION}
    ):
        raise NativeTrustedAttemptError("native_trusted_attempt_fd_control_required")
    if (
        artifact.descriptor.platform_execution_mode == "linux-fd-bound"
        and artifact.descriptor.implementation_version not in {LINUX_GRANT_OBJECT_IMPLEMENTATION, LINUX_IPC_CONTROL_IMPLEMENTATION, LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION}
    ):
        raise NativeTrustedAttemptError("native_trusted_attempt_grant_objects_required")
    if (
        artifact.descriptor.platform_execution_mode == "linux-fd-bound"
        and artifact.descriptor.implementation_version not in {LINUX_IPC_CONTROL_IMPLEMENTATION, LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION}
    ):
        raise NativeTrustedAttemptError("native_trusted_attempt_ipc_control_required")
    if (
        artifact.descriptor.platform_execution_mode == "linux-fd-bound"
        and artifact.descriptor.implementation_version != LINUX_INDEPENDENT_GUARDIAN_IMPLEMENTATION
    ):
        raise NativeTrustedAttemptError("native_trusted_attempt_guardian_required")
    if broker_config is not None and type(broker_config) is not ProducerBrokerConfig:
        raise NativeTrustedAttemptError("native_trusted_attempt_broker_invalid")
    if cancelled is not None and not callable(cancelled):
        raise NativeTrustedAttemptError("native_trusted_attempt_cancellation_invalid")
    if _observe_cancellation(cancelled):
        raise NativeTrustedAttemptError("native_trusted_attempt_cancelled")
    started_monotonic, deadline = _compose_attempt_budget(intent, monotonic, parent_deadline)
    inputs = _native_launch_inputs(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
        require_unexpired=True,
    )
    if inputs is not None and inputs.deadline_unix is not None:
        # Sample monotonic before wall time, once, so setup cannot extend the original
        # absolute RSI deadline. Later admission checks may reject expiry but never remap it.
        sampled_monotonic = monotonic()
        sampled_unix = time.time()
        if any(type(value) not in (int, float) or not math.isfinite(float(value))
               for value in (sampled_monotonic, sampled_unix)):
            raise NativeTrustedAttemptError("native_trusted_attempt_clock_invalid")
        deadline = min(deadline, float(sampled_monotonic) + (inputs.deadline_unix - sampled_unix))
    _remaining(deadline, monotonic, cancelled)
    native_deadline_ns = _native_guard_deadline(deadline, monotonic, cancelled)
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
        if installed.descriptor.platform_execution_mode != "linux-fd-bound":
            _safe_dir(working, create=True)
            _safe_dir(output, create=True)
    except (NativeBootstrapError, ProducerBootstrapError, ProducerProcessError) as exc:
        raise NativeTrustedAttemptError("native_trusted_attempt_preflight_invalid") from exc

    with _recovery_lock(batch) as lock_identity, _original_attempt_grants(
        inputs, batch=batch, working=working, output=output,
        enabled=installed.descriptor.platform_execution_mode == "linux-fd-bound",
    ) as grant_owner:
        process: subprocess.Popen[bytes] | None = None
        guardian: NativeGuardianOwner | None = None
        guardian_finished = installed.descriptor.platform_execution_mode != "linux-fd-bound"
        owner: RegisteredProcess | None = None
        registration: dict[str, object] | None = None
        session: TrustedBootstrapSession | None = None
        gate_released = False
        target_started = False
        exit_code: int | None = None
        cleanup_status: str | None = None
        cleanup_sha256: str | None = None
        cleanup_record: dict[str, object] | None = None
        reason = "native_trusted_attempt_terminal_receipt_missing"
        terminal_sha256: str | None = None
        output_capture_sha256: str | None = None
        stream_capture_sha256: str | None = None
        stream_observation: NativeTrustedStreamObservation | None = None
        stream_capture: NativeTrustedStreamCapture | None = None
        stream_capture_failed = False
        handoff_sha256: str | None = None
        claimed = False
        cancellation_requested = False
        fds: set[int] = set()
        broker_thread: threading.Thread | None = None
        broker_ready: threading.Event | None = None
        broker_stop: threading.Event | None = None
        controller_lifeline_writer: int | None = None
        broker_state: dict[str, object] = {}
        deadline_binding: dict[str, object] | None = None
        consumption: dict[str, object] | None = None

        def check_deadline() -> None:
            if deadline_binding is None:
                raise NativeTrustedAttemptError("native_trusted_attempt_deadline_binding_changed")
            _check_live_deadline(
                root, batch, attestation=attestation, binding=deadline_binding,
                record=deadline_record, claim=consumption,
            )

        try:
            _revalidate_native_launch_inputs(
                inputs, root, intent=intent, attestation=attestation, artifact=installed,
                require_unexpired=True,
            )
            _check_original_attempt_grants(grant_owner, inputs)
            _remaining(deadline, monotonic, cancelled)
            deadline_record, deadline_binding = _persist_deadline(
                batch, launch, started=started_monotonic, deadline=deadline,
            )
            deadline_sha256 = str(deadline_record["deadline_sha256"])
            consumption = consume_trusted_bootstrap_attestation(
                root, producer_root=target_root, intent=intent, attestation=attestation,
                descriptor=installed.descriptor, launch=launch,
                recovery_lock_identity=lock_identity, deadline=deadline, monotonic=monotonic,
                deadline_binding=deadline_binding,
            )
            claimed = True
            check_deadline()
            with prepare_trusted_executable_pair(
                bootstrap_source=installed.path, producer_root=target_root, batch=batch,
                descriptor=installed.descriptor, launch=launch, intent=intent,
                attestation=attestation, deadline=deadline, monotonic=monotonic,
            ) as pair:
                # Linux executes the inherited sealed FD. Landlock must not
                # grant a second pathname route to the mutable source file.
                read_paths = [pair.target.executable] if sys.platform == "darwin" else []
                if inputs is not None:
                    read_paths.extend(inputs.read_paths)
                control_read, control_write = os.pipe()
                fds.update((control_read, control_write))
                gate_read, gate_write = os.pipe()
                fds.update((gate_read, gate_write))
                frame_read, frame_write = os.pipe()
                fds.update((frame_read, frame_write))
                lifeline_read, controller_lifeline_writer = os.pipe()
                fds.add(lifeline_read)
                guardian_fds: tuple[int, ...] = ()
                if grant_owner is not None:
                    guardian_finish_read, guardian_finish_write = os.pipe()
                    guardian_ack_read, guardian_ack_write = os.pipe()
                    guardian_fds = (guardian_finish_write, guardian_ack_read)
                    fds.update((guardian_finish_read, guardian_finish_write, guardian_ack_read, guardian_ack_write))
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
                    broker_stop = threading.Event()
                    broker_deadline_ns = native_deadline_ns

                    def serve() -> None:
                        try:
                            broker_state["observation"] = serve_producer_broker(
                                request_read, response_write, intent=intent,
                                journal_dir=batch / ".host-request-journal",
                                config=broker_config, deadline_ns=broker_deadline_ns,
                                ready=broker_ready,
                                stop=broker_stop,
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

                if grant_owner is not None:
                    _check_original_attempt_grants(grant_owner, inputs)
                    control = encode_native_bootstrap_control_v2(
                        launch, target_path=pair.target.executable,
                        target_argv=(pair.target.executable, *intent.argv[1:]),
                        target_cwd=working, target_fd=pair.target.pass_fd,
                        bootstrap_fd=pair.bootstrap.pass_fd, held_grants=grant_owner,
                        reserved_fds=tuple(sorted(fds)) + pair.pass_fds + (controller_lifeline_writer,),
                    )
                else:
                    policy = build_producer_isolation_policy(read_paths=read_paths, write_dirs=[working, output])
                    control = encode_native_bootstrap_control(
                        launch, target_path=pair.target.executable,
                        target_argv=(pair.target.executable, *intent.argv[1:]),
                        target_cwd=working, target_fd=pair.target.pass_fd, isolation_policy=policy,
                    )
                command = native_bootstrap_command(
                    pair.bootstrap.executable, control_fd=control_read,
                    gate_fd=gate_read, frame_fd=frame_write,
                    controller_lifeline_fd=lifeline_read,
                    deadline_monotonic_ns=native_deadline_ns,
                    child_supervision=(
                        LINUX_CHILD_SUPERVISION
                        if installed.descriptor.platform_execution_mode == "linux-fd-bound" else None
                    ),
                    grant_object_binding=LINUX_GRANT_OBJECT_BINDING if grant_owner is not None else None,
                    guardian_finish_fd=guardian_finish_write if grant_owner is not None else None,
                    guardian_ack_fd=guardian_ack_read if grant_owner is not None else None,
                )
                _remaining(deadline, monotonic, cancelled)
                check_deadline()
                _check_original_attempt_grants(grant_owner, inputs)
                if grant_owner is not None:
                    _revalidate_native_launch_inputs(
                        inputs, root, intent=intent, attestation=attestation, artifact=installed,
                        require_unexpired=True,
                    )
                process = subprocess.Popen(
                    command, executable=pair.bootstrap.executable,
                    shell=False, start_new_session=True, close_fds=True,
                    pass_fds=(control_read, gate_read, frame_write, *pair.pass_fds,
                              *broker_child_fds, *guardian_fds, lifeline_read,
                              *(grant_owner.pass_fds if grant_owner is not None else ())),
                    cwd="/" if grant_owner is not None else str(working), env=broker_env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                check_deadline()
                if grant_owner is not None:
                    try:
                        guardian = start_native_guardian(
                            process=process, executable=pair.bootstrap.executable,
                            bootstrap_fd=pair.bootstrap.pass_fd, lifeline_fd=lifeline_read,
                            finish_fd=guardian_finish_read, ack_fd=guardian_ack_write,
                            ack_read_fd=guardian_ack_read, deadline=deadline,
                            deadline_ns=native_deadline_ns, monotonic=monotonic,
                        )
                    except NativeGuardianError as exc:
                        # Preserve a live original owner if bounded startup cleanup could
                        # not complete before the caller closes the original writer.
                        guardian = exc.guardian_owner
                        raise
                    # The bootstrap owns the sole finish writer and acknowledgement
                    # reader after host readiness; the watcher owns the opposite ends.
                    for fd in (guardian_finish_read, guardian_finish_write, guardian_ack_read, guardian_ack_write):
                        os.close(fd)
                        fds.remove(fd)
                    check_deadline()
                stream_capture = start_native_trusted_stream_capture(
                    process, limit=intent.output_max_bytes,
                    deadline=deadline, monotonic=monotonic,
                )
                for fd in (control_read, gate_read, frame_write, lifeline_read):
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
                    expected_deadline_binding=deadline_binding,
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
                        check_deadline()
                        current = _read_durable_json(
                            batch / "process-registration.json",
                            code="native_trusted_attempt_registration_unknown",
                        )
                        matches = (
                            current == registration
                            and _current_recovery_lock_identity(batch) == lock_identity
                            and _current_process_owned(pid, owner_identity, process)
                        )
                        check_deadline()
                        return matches
                    except (ProducerProcessError, NativeTrustedAttemptError):
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
                _revalidate_native_launch_inputs(
                    inputs, root, intent=intent, attestation=attestation, artifact=installed,
                    require_unexpired=True,
                )
                _remaining(deadline, monotonic, cancelled)
                check_deadline()
                if _current_recovery_lock_identity(batch) != lock_identity:
                    raise NativeTrustedAttemptError("native_trusted_attempt_registration_unknown")
                _check_original_attempt_grants(grant_owner, inputs)
                _remaining(deadline, monotonic, cancelled)
                os.write(gate_write, b"1")
                os.close(gate_write)
                fds.remove(gate_write)
                gate_released = True
                session.release(launch.gate_nonce)
                check_deadline()
                started = _read_attempt_frame(frame_read, deadline, monotonic, cancelled)
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
                # Keep a small slice of the attempt budget available for the owner-checked
                # cleanup path. This remains inside the caller deadline; it only makes a
                # late terminal frame timeout conservative instead of entering cleanup with
                # no budget.
                execution_deadline = deadline - _CLEANUP_RESERVE_SECONDS
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
                if guardian is not None:
                    guardian.finish()
                    guardian_finished = True
                    check_deadline()
        except (NativeTrustedAttemptError, ProducerBootstrapError, TrustedBootstrapRegistrationError,
                TrustedBootstrapBindingError, NativeBootstrapError, NativeGuardianError, ProducerIsolationError,
                ProducerGrantError, ProducerProcessError, OSError, subprocess.SubprocessError) as exc:
            if not claimed:
                if isinstance(exc, NativeTrustedAttemptError) and exc.code in {
                    "native_trusted_attempt_deadline_write_unknown",
                    "native_trusted_attempt_boot_identity_unknown",
                }:
                    raise
                raise NativeTrustedAttemptError("native_trusted_attempt_claim_failed") from exc
            reason = (
                "native_trusted_attempt_grant_objects_changed" if isinstance(exc, ProducerGrantError)
                else getattr(exc, "code", "native_trusted_attempt_unknown")
            )
            cancellation_requested = reason == "native_trusted_attempt_cancelled"
        finally:
            if broker_stop is not None and (
                reason != "native_trusted_attempt_terminal_receipt_missing" or exit_code != 0
            ):
                # The main thread owns caller cancellation. The broker observes only
                # this stop event and keeps ownership of its descriptors and HTTP handle.
                broker_stop.set()
            for fd in tuple(fds):
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
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
                        if registration is not None:
                            try:
                                check_deadline()
                                cleanup_record = persist_native_trusted_cleanup(
                                    root,
                                    intent=intent,
                                    registration_sha256=str(registration["registration_sha256"]),
                                    deadline_sha256=deadline_sha256,
                                    cleanup=result,
                                )
                                check_deadline()
                                cleanup_sha256 = str(cleanup_record["cleanup_sha256"])
                            except NativeTrustedAttemptError as exc:
                                reason = exc.code
                            except NativeTrustedCleanupError:
                                reason = "native_trusted_attempt_cleanup_evidence_unknown"
                    try:
                        process.wait(timeout=max(0.0, deadline - monotonic()))
                    except subprocess.TimeoutExpired:
                        if reason == "native_trusted_attempt_terminal_receipt_missing":
                            reason = "native_trusted_attempt_reap_unknown"
            finally:
                if controller_lifeline_writer is not None:
                    # Retain the writer through live owner-checked cleanup. Abrupt controller
                    # death closes it in the OS; the bootstrap guardian then stops its group.
                    try:
                        os.close(controller_lifeline_writer)
                    except OSError:
                        reason = "native_trusted_attempt_lifeline_close_unknown"
                    controller_lifeline_writer = None
                if guardian is not None and not guardian.cleanup():
                    reason = "native_trusted_attempt_guardian_cleanup_unknown"
            if stream_capture is not None:
                try:
                    stream_observation = stream_capture.finish(deadline=deadline)
                    if not stream_observation.complete and reason == "native_trusted_attempt_terminal_receipt_missing":
                        stream_capture_failed = True
                except NativeTrustedStreamError:
                    stream_capture_failed = True
            if broker_thread is not None:
                if broker_stop is not None and reason != "native_trusted_attempt_terminal_receipt_missing":
                    broker_stop.set()
                broker_thread.join(timeout=max(0.0, deadline - monotonic()))
                if broker_thread.is_alive() or "error" in broker_state:
                    reason = "native_trusted_attempt_broker_unknown"
            if session is not None and registration is not None:
                evidence = session.evidence()
                if evidence.status == "passed" and (
                    cleanup_status not in {"cleaned", "already_exited"} or exit_code is None
                    or not guardian_finished
                ):
                    evidence = replace(evidence, status="unknown", evidence_sha256=None)
                try:
                    check_deadline()
                    current = _read_durable_json(
                        batch / "process-registration.json",
                        code="native_trusted_attempt_registration_unknown",
                    )
                    if current != registration or _current_recovery_lock_identity(batch) != lock_identity:
                        raise ProducerProcessError("native_trusted_attempt_registration_unknown")
                    _atomic_json(batch / "trusted-bootstrap-evidence.json", evidence.to_dict(), exclusive=True)
                    check_deadline()
                    persisted = _read_durable_json(
                        batch / "trusted-bootstrap-evidence.json",
                        code="native_trusted_attempt_evidence_write_unknown",
                    )
                    if persisted != evidence.to_dict():
                        raise ProducerProcessError("native_trusted_attempt_evidence_write_unknown")
                except NativeTrustedAttemptError as exc:
                    reason = exc.code
                except ProducerProcessError:
                    reason = "native_trusted_attempt_evidence_write_unknown"
        # A verified active cancellation is a durable process-only terminal.  It is
        # deliberately narrower than a normal terminal: the target has started and the
        # owner-checked group cleanup succeeded, but no exit code or producer output is
        # claimed.  The bootstrap evidence may therefore still be ``unknown``; the
        # evidence digest remains bound so recovery can inspect the exact record.
        try:
            _revalidate_native_launch_inputs(
                inputs, root, intent=intent, attestation=attestation, artifact=installed,
                require_unexpired=False,
            )
            _check_original_attempt_grants(grant_owner, inputs)
            if deadline_binding is not None:
                check_deadline()
        except NativeTrustedAttemptError as exc:
            reason = exc.code
        if (
            registration is not None and session is not None and handoff_sha256 is not None
            and cancellation_requested
            and reason == "native_trusted_attempt_cancelled"
            and gate_released and target_started
            and exit_code is None
            and cleanup_status in {"cleaned", "already_exited"}
        ):
            try:
                observed = observe_trusted_bootstrap_attempt(
                    root, launch=launch, descriptor=installed.descriptor,
                    intent=intent, attestation=attestation, require_handoff=True,
                    deadline=deadline, monotonic=monotonic,
                )
                evidence_sha = observed.get("evidence_sha256")
                valid_unknown = (
                    observed.get("status") == "recovery_required"
                    and observed.get("reason") == "trusted_bootstrap_evidence_unknown"
                )
                valid_passed = (
                    observed.get("status") == "evidence_available"
                    and observed.get("bootstrap_status") == "passed"
                )
                if (
                    not (valid_unknown or valid_passed)
                    or not isinstance(evidence_sha, str)
                    or observed.get("registration_sha256") != registration["registration_sha256"]
                    or observed.get("handoff_sha256") != handoff_sha256
                ):
                    raise NativeTrustedAttemptError("native_trusted_attempt_terminal_evidence_unknown")
                if stream_observation is not None and stream_observation.complete:
                    try:
                        stream_record = persist_native_trusted_stream_capture(
                            batch, intent=intent,
                            attestation_sha256=attestation.attestation_sha256,
                            registration_sha256=str(registration["registration_sha256"]),
                            deadline_sha256=deadline_sha256,
                            observation=stream_observation,
                        )
                        stream_capture_sha256 = str(stream_record["stream_capture_sha256"])
                    except NativeTrustedStreamError:
                        stream_capture_failed = True
                receipt = _terminal_receipt(
                    registration, handoff_sha256=handoff_sha256,
                    evidence_sha256=evidence_sha,
                    gate_released=gate_released, target_started=target_started,
                    exit_code=None, cleanup_status=cleanup_status,
                    deadline_sha256=deadline_sha256, cancelled=True,
                    stream_capture_sha256=stream_capture_sha256,
                    cleanup_sha256=cleanup_sha256,
                )
                # Receipt publication must consume the caller deadline, but must not
                # call the cancellation callback again after cleanup has been verified.
                _revalidate_native_launch_inputs(
                    inputs, root, intent=intent, attestation=attestation, artifact=installed,
                    require_unexpired=False,
                )
                _remaining(deadline, monotonic)
                check_deadline()
                _atomic_json(batch / _TERMINAL_NAME, receipt, exclusive=True)
                check_deadline()
                stored = _read_durable_json(
                    batch / _TERMINAL_NAME, code="native_trusted_attempt_terminal_write_unknown",
                )
                if stored != receipt:
                    raise NativeTrustedAttemptError("native_trusted_attempt_terminal_write_unknown")
                terminal_sha256 = str(receipt["terminal_sha256"])
            except (NativeTrustedAttemptError, ProducerBootstrapError) as exc:
                reason = exc.code
            except ProducerProcessError:
                reason = "native_trusted_attempt_terminal_write_unknown"
        if (
            registration is not None and session is not None and handoff_sha256 is not None
            and reason == "native_trusted_attempt_terminal_receipt_missing"
            and exit_code is not None and guardian_finished
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
                if stream_observation is not None and stream_observation.complete:
                    try:
                        stream_record = persist_native_trusted_stream_capture(
                            batch, intent=intent,
                            attestation_sha256=attestation.attestation_sha256,
                            registration_sha256=str(registration["registration_sha256"]),
                            deadline_sha256=deadline_sha256,
                            observation=stream_observation,
                        )
                        stream_capture_sha256 = str(stream_record["stream_capture_sha256"])
                    except NativeTrustedStreamError:
                        stream_capture_failed = True
                receipt = _terminal_receipt(
                    registration, handoff_sha256=handoff_sha256,
                    evidence_sha256=str(observed["evidence_sha256"]),
                    gate_released=gate_released, target_started=target_started,
                    exit_code=exit_code, cleanup_status=cleanup_status,
                    deadline_sha256=deadline_sha256,
                    stream_capture_sha256=stream_capture_sha256,
                    cleanup_sha256=cleanup_sha256,
                )
                _revalidate_native_launch_inputs(
                    inputs, root, intent=intent, attestation=attestation, artifact=installed,
                    require_unexpired=False,
                )
                _remaining(deadline, monotonic, cancelled)
                check_deadline()
                _atomic_json(batch / _TERMINAL_NAME, receipt, exclusive=True)
                check_deadline()
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
                if stream_capture_sha256 is None:
                    stream_capture_failed = True
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
                check_deadline()
                captured = capture_native_trusted_output(
                    batch, intent=intent, terminal_sha256=terminal_sha256,
                    broker=(broker_observation if isinstance(
                        broker_observation, ProducerBrokerObservation,
                    ) else None),
                    deadline=deadline, monotonic=monotonic,
                )
                check_deadline()
                output_capture_sha256 = str(captured["capture_sha256"])
            except NativeTrustedAttemptError as exc:
                reason = exc.code
            except NativeTrustedCaptureError:
                reason = "native_trusted_attempt_output_capture_unknown"
        if stream_capture_failed and reason == "native_trusted_attempt_request_and_output_unverified":
            reason = "native_trusted_attempt_stream_capture_unknown"
        if deadline_binding is not None:
            try:
                check_deadline()
            except NativeTrustedAttemptError as exc:
                reason = exc.code
        return NativeTrustedAttemptObservation(
            launch_id=launch.launch_id, journal_id=launch.journal_id,
            status="recovery_required", reason=reason,
            registration_sha256=(str(registration["registration_sha256"]) if registration else None),
            gate_released=gate_released, target_started=target_started,
            exit_code=exit_code, cleanup_status=cleanup_status,
            terminal_sha256=terminal_sha256,
            output_capture_sha256=output_capture_sha256,
            stream_capture_sha256=stream_capture_sha256,
            stream_observation=stream_observation,
            broker_observation=(broker_observation if isinstance(
                broker_observation, ProducerBrokerObservation,
            ) else None),
        )


def _verify_terminal_record(
    receipt: object, *, registration: Mapping[str, object],
    bound: Mapping[str, object], deadline_record: object,
    cleanup_record: object, intent: ProducerLaunchIntent,
) -> dict[str, object]:
    """Pure process-only check, after the caller has verified registration and handoff.

    Never reads a process, clock or file and never grants publication authority.
    """
    if not isinstance(receipt, Mapping):
        raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid")
    deadline_record = _verify_deadline_record(deadline_record, registration)
    if (
        set(receipt) != _TERMINAL_FIELDS
        or receipt.get("publication_eligible") is not False
        or receipt.get("terminal_sha256") != _digest_without(receipt, "terminal_sha256")
    ):
        raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid")
    cancelled_receipt = receipt.get("process_status") == "cancelled"
    if cancelled_receipt:
        valid_unknown = (
            bound.get("status") == "recovery_required"
            and bound.get("reason") == "trusted_bootstrap_evidence_unknown"
        )
        valid_passed = (
            bound.get("status") == "evidence_available"
            and bound.get("bootstrap_status") == "passed"
        )
        if (
            not (valid_unknown or valid_passed)
            or not isinstance(bound.get("handoff_sha256"), str)
            or not isinstance(bound.get("evidence_sha256"), str)
            or receipt.get("exit_code") is not None
            or receipt.get("cleanup_status") not in {"cleaned", "already_exited"}
            or receipt.get("gate_released") is not True
            or receipt.get("target_started") is not True
            or receipt.get("bootstrap_evidence_sha256") != bound["evidence_sha256"]
        ):
            raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid")
        expected = _terminal_receipt(
            registration, handoff_sha256=str(bound["handoff_sha256"]),
            evidence_sha256=str(bound["evidence_sha256"]),
            gate_released=True, target_started=True,
            exit_code=None, cleanup_status=str(receipt["cleanup_status"]),
            deadline_sha256=str(deadline_record["deadline_sha256"]), cancelled=True,
            stream_capture_sha256=receipt.get("stream_capture_sha256"),
            cleanup_sha256=receipt.get("cleanup_sha256"),
        )
    else:
        if (
            bound.get("status") != "evidence_available"
            or bound.get("bootstrap_status") != "passed"
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
            deadline_sha256=str(deadline_record["deadline_sha256"]),
            stream_capture_sha256=receipt.get("stream_capture_sha256"),
            cleanup_sha256=receipt.get("cleanup_sha256"),
        )
    if receipt != expected:
        raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid")
    cleanup_digest = receipt.get("cleanup_sha256")
    if not isinstance(cleanup_digest, str) or len(cleanup_digest) != 64:
        raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid")
    try:
        verify_native_trusted_cleanup(cleanup_record, intent=intent, terminal=receipt)
    except NativeTrustedCleanupError as exc:
        raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid") from exc
    stream_digest = receipt.get("stream_capture_sha256")
    if stream_digest is not None and (
        not isinstance(stream_digest, str) or len(stream_digest) != 64
        or any(c not in "0123456789abcdef" for c in stream_digest)
    ):
        raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid")
    return dict(receipt)


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
    inputs = _native_launch_inputs(
        root, intent=intent, attestation=attestation, artifact=artifact,
        require_unexpired=False,
    )
    final_deadline_check: Callable[[], dict[str, object]] | None = None

    def inspect(lock_identity: tuple[int, int] | None = None) -> dict[str, object]:
        nonlocal final_deadline_check
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
        # Every recovery observation, including an already-written terminal, must
        # validate the retained attempt budget. Otherwise a tampered sidecar could
        # silently detach the terminal from the original wall-clock authority.
        binding = observed.get("deadline_binding")
        if binding is not None and not isinstance(binding, Mapping):
            raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid")

        def verify_context() -> dict[str, object]:
            try:
                current = observe_trusted_bootstrap_attempt(
                    root, launch=launch, descriptor=artifact.descriptor,
                    intent=intent, attestation=attestation, require_handoff=binding is not None,
                )
                if any(current.get(key) != observed.get(key) for key in (
                    "consumption_sha256", "registration_sha256", "deadline_binding",
                )):
                    raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid")
                if lock_identity is not None and _current_recovery_lock_identity(batch) != lock_identity:
                    raise NativeTrustedAttemptError("native_trusted_recovery_registration_invalid")
                # The pure projection binds this descriptor to the original registration;
                # filesystem checks compare the original bytes/inode, never a newly captured pin.
                return _read_deadline(batch, registration, binding=binding)
            except ProducerBootstrapError as exc:
                raise NativeTrustedAttemptError("native_trusted_recovery_evidence_invalid") from exc

        deadline_record = verify_context()
        final_deadline_check = verify_context
        path = batch / _TERMINAL_NAME
        try:
            os.lstat(path)
        except FileNotFoundError:
            if binding is None:
                if cleanup:
                    raise NativeTrustedAttemptError("native_trusted_recovery_legacy_deadline_unanchored")
                return {
                    "status": "recovery_required",
                    "reason": "native_trusted_recovery_legacy_deadline_unanchored",
                    "launch_id": launch.launch_id, "journal_id": launch.journal_id,
                    "registration_sha256": registration["registration_sha256"],
                    "pid": registration["pid"], "pgid": registration["pgid"],
                }
            prior = _read_recovery_receipt(batch, registration, binding=binding)
            if prior is not None:
                if cleanup:
                    raise NativeTrustedAttemptError("native_trusted_recovery_already_recorded")
                return prior
            if cleanup:
                if lock_identity is None:
                    raise NativeTrustedAttemptError("native_trusted_recovery_lock_required")
                return _cleanup_recovered_attempt(
                    batch, registration, lock_identity, binding=binding, verify_context=verify_context,
                )
            return {
                "status": "recovery_required",
                "reason": "native_trusted_attempt_terminal_receipt_missing",
                "launch_id": launch.launch_id, "journal_id": launch.journal_id,
                "registration_sha256": registration["registration_sha256"],
                "pid": registration["pid"], "pgid": registration["pgid"],
            }
        except OSError as exc:
            raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid") from exc
        if _read_recovery_receipt(batch, registration, binding=binding) is not None:
            raise NativeTrustedAttemptError("native_trusted_recovery_conflicting_receipts")
        try:
            bound = observe_trusted_bootstrap_attempt(
                root, launch=launch, descriptor=artifact.descriptor,
                intent=intent, attestation=attestation, require_handoff=True,
            )
            receipt = _read_durable_json(path, code="native_trusted_recovery_terminal_invalid")
        except (ProducerBootstrapError, ProducerProcessError) as exc:
            raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid") from exc
        try:
            cleanup_record = recover_native_trusted_cleanup(root, intent=intent, terminal=receipt)
        except NativeTrustedCleanupError as exc:
            raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid") from exc
        receipt = _verify_terminal_record(
            receipt, registration=registration, bound=bound, deadline_record=deadline_record,
            cleanup_record=cleanup_record, intent=intent,
        )
        stream_digest = receipt.get("stream_capture_sha256")
        if stream_digest is not None:
            if not isinstance(stream_digest, str) or len(stream_digest) != 64:
                raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid")
            try:
                recover_native_trusted_stream_capture(
                    batch, intent=intent, terminal=receipt,
                )
            except NativeTrustedStreamError as exc:
                raise NativeTrustedAttemptError("native_trusted_recovery_terminal_invalid") from exc
        return receipt

    if cleanup:
        try:
            with _recovery_lock(batch) as lock_identity:
                _revalidate_native_launch_inputs(
                    inputs, root, intent=intent, attestation=attestation, artifact=artifact,
                    require_unexpired=False,
                )
                result = inspect(lock_identity)
                _revalidate_native_launch_inputs(
                    inputs, root, intent=intent, attestation=attestation, artifact=artifact,
                    require_unexpired=False,
                )
                if final_deadline_check is not None:
                    current_deadline = final_deadline_check()
                    if result.get("deadline_sha256", current_deadline["deadline_sha256"]) != current_deadline["deadline_sha256"]:
                        raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid")
                return result
        except ProducerProcessError as exc:
            raise NativeTrustedAttemptError("native_trusted_recovery_cleanup_unknown") from exc
    try:
        result = inspect()
        _revalidate_native_launch_inputs(
            inputs, root, intent=intent, attestation=attestation, artifact=artifact,
            require_unexpired=False,
        )
        if final_deadline_check is not None:
            current_deadline = final_deadline_check()
            if result.get("deadline_sha256", current_deadline["deadline_sha256"]) != current_deadline["deadline_sha256"]:
                raise NativeTrustedAttemptError("native_trusted_recovery_deadline_invalid")
        return result
    except ProducerProcessError as exc:
        raise NativeTrustedAttemptError("native_trusted_recovery_evidence_invalid") from exc


def audit_native_trusted_lifecycle(
    workspace: str | Path, *, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
) -> dict[str, object]:
    """Read-only audit of the native process/output evidence chain.

    This composes the durable process terminal with the optional same-attempt output
    capture and broker journal. It never launches, cleans up, or publishes. A valid
    process-only terminal remains ``process_only`` when output capture is absent;
    changed or malformed capture evidence is ``recovery_required``.
    """
    terminal = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    result: dict[str, object] = {
        "status": "process_only", "reason": "native_trusted_lifecycle_process_verified",
        "launch_id": intent.launch_id, "journal_id": intent.journal_id,
        "launch_sha256": terminal.get("launch_sha256"),
        "intent_sha256": terminal.get("intent_sha256"),
        "attestation_sha256": terminal.get("attestation_sha256"),
        "registration_sha256": terminal.get("registration_sha256"),
        "deadline_sha256": None,
        "terminal_sha256": terminal.get("terminal_sha256"),
        "stream_capture_sha256": None, "output_capture_sha256": None,
        "broker_coverage": "not_observed",
        "publication_eligible": False,
    }
    if (
        terminal.get("protocol") != _TERMINAL_PROTOCOL
        or not isinstance(terminal.get("terminal_sha256"), str)
        or terminal.get("process_status") not in {"exited_zero", "exited_nonzero", "cancelled"}
    ):
        result["status"] = "recovery_required"
        result["reason"] = "native_trusted_lifecycle_process_terminal_unverified"
        return result
    if terminal.get("process_status") != "exited_zero":
        result["reason"] = "native_trusted_lifecycle_process_terminal_unpublishable"
        return result
    batch = Path(workspace).expanduser().absolute() / "evolution" / "producer-batches" / intent.journal_id
    try:
        deadline = _read_deadline(batch, terminal)
    except NativeTrustedAttemptError:
        result["status"] = "recovery_required"
        result["reason"] = "native_trusted_recovery_deadline_invalid"
        return result
    result["deadline_sha256"] = deadline["deadline_sha256"]
    stream_digest = terminal.get("stream_capture_sha256")
    if stream_digest is not None:
        try:
            stream = recover_native_trusted_stream_capture(
                batch, intent=intent, terminal=terminal,
            )
        except NativeTrustedStreamError as exc:
            result["status"] = "recovery_required"
            result["reason"] = exc.code
            return result
        result["stream_capture_sha256"] = stream["stream_capture_sha256"]
    capture_path = batch / "native-trusted-output-capture.json"
    try:
        os.lstat(capture_path)
    except FileNotFoundError:
        result["reason"] = "native_trusted_lifecycle_capture_missing"
        return result
    except OSError as exc:
        raise NativeTrustedAttemptError("native_trusted_lifecycle_capture_invalid") from exc
    try:
        # Import lazily: native_trusted_output imports this module's recovery API.
        from .native_trusted_capture import (
            NativeTrustedCaptureError,
            recover_native_trusted_output_capture,
        )

        capture = recover_native_trusted_output_capture(
            batch, intent=intent, terminal=terminal,
        )
    except NativeTrustedCaptureError as exc:
        result["status"] = "recovery_required"
        result["reason"] = exc.code
        return result
    except Exception:  # noqa: BLE001 - fixed read-only audit boundary.
        result["status"] = "recovery_required"
        result["reason"] = "native_trusted_lifecycle_capture_invalid"
        return result
    result["output_capture_sha256"] = capture["capture_sha256"]
    broker = capture.get("broker_evidence")
    if isinstance(broker, dict):
        result["broker_coverage"] = broker.get("coverage", "unknown")
    else:
        result["broker_coverage"] = "producer_declaration_only"
    result["reason"] = "native_trusted_lifecycle_capture_verified"
    return result


def persist_native_trusted_lifecycle_audit(
    workspace: str | Path, *, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
) -> dict[str, object]:
    """Persist a create-only, publication-ineligible cross-record audit sidecar."""
    audit = audit_native_trusted_lifecycle(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    if audit.get("reason") != "native_trusted_lifecycle_capture_verified":
        raise NativeTrustedAttemptError("native_trusted_lifecycle_audit_not_verified")
    required = (
        "launch_sha256", "intent_sha256", "attestation_sha256", "registration_sha256",
        "deadline_sha256", "terminal_sha256", "stream_capture_sha256", "output_capture_sha256",
    )
    if any(not isinstance(audit.get(key), str) for key in required):
        raise NativeTrustedAttemptError("native_trusted_lifecycle_audit_context_invalid")
    record: dict[str, object] = {
        "schema_version": "1", "protocol": _AUDIT_PROTOCOL,
        "launch_id": audit["launch_id"], "journal_id": audit["journal_id"],
        "launch_sha256": audit["launch_sha256"], "intent_sha256": audit["intent_sha256"],
        "attestation_sha256": audit["attestation_sha256"],
        "registration_sha256": audit["registration_sha256"],
        "deadline_sha256": audit["deadline_sha256"],
        "terminal_sha256": audit["terminal_sha256"],
        "stream_capture_sha256": audit["stream_capture_sha256"],
        "capture_sha256": audit["output_capture_sha256"],
        "broker_coverage": audit["broker_coverage"],
        "publication_eligible": False,
    }
    record["audit_sha256"] = _digest_without(record, "audit_sha256")
    batch = Path(workspace).expanduser().absolute() / "evolution" / "producer-batches" / intent.journal_id
    try:
        _atomic_json(batch / _AUDIT_NAME, record, exclusive=True)
        stored = _read_durable_json(batch / _AUDIT_NAME, code="native_trusted_lifecycle_audit_write_unknown")
    except ProducerProcessError as exc:
        raise NativeTrustedAttemptError("native_trusted_lifecycle_audit_write_unknown") from exc
    if stored != record:
        raise NativeTrustedAttemptError("native_trusted_lifecycle_audit_write_unknown")
    return record


def recover_native_trusted_lifecycle_audit(
    workspace: str | Path, *, intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact,
) -> dict[str, object]:
    """Revalidate the audit sidecar and all of the evidence it summarizes."""
    audit = audit_native_trusted_lifecycle(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    if audit.get("reason") != "native_trusted_lifecycle_capture_verified":
        raise NativeTrustedAttemptError("native_trusted_lifecycle_audit_not_verified")
    batch = Path(workspace).expanduser().absolute() / "evolution" / "producer-batches" / intent.journal_id
    try:
        record = _read_durable_json(
            batch / _AUDIT_NAME, code="native_trusted_lifecycle_audit_invalid",
        )
    except ProducerProcessError as exc:
        raise NativeTrustedAttemptError("native_trusted_lifecycle_audit_invalid") from exc
    expected_fields = {
        "schema_version", "protocol", "launch_id", "journal_id", "launch_sha256",
        "intent_sha256", "attestation_sha256", "registration_sha256", "deadline_sha256",
        "terminal_sha256", "capture_sha256", "broker_coverage", "publication_eligible",
        "stream_capture_sha256", "audit_sha256",
    }
    if (
        set(record) != expected_fields
        or record.get("schema_version") != "1"
        or record.get("protocol") != _AUDIT_PROTOCOL
        or record.get("publication_eligible") is not False
        or record.get("audit_sha256") != _digest_without(record, "audit_sha256")
    ):
        raise NativeTrustedAttemptError("native_trusted_lifecycle_audit_invalid")
    expected = {
        "launch_id": audit["launch_id"], "journal_id": audit["journal_id"],
        "launch_sha256": audit["launch_sha256"], "intent_sha256": audit["intent_sha256"],
        "attestation_sha256": audit["attestation_sha256"],
        "registration_sha256": audit["registration_sha256"],
        "deadline_sha256": audit["deadline_sha256"],
        "terminal_sha256": audit["terminal_sha256"],
        "stream_capture_sha256": audit["stream_capture_sha256"],
        "capture_sha256": audit["output_capture_sha256"],
        "broker_coverage": audit["broker_coverage"],
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise NativeTrustedAttemptError("native_trusted_lifecycle_audit_invalid")
    return record


__all__ = [
    "NativeTrustedAttemptError",
    "NativeTrustedAttemptObservation",
    "audit_native_trusted_lifecycle",
    "persist_native_trusted_lifecycle_audit",
    "recover_native_trusted_attempt",
    "recover_native_trusted_lifecycle_audit",
    "run_native_trusted_attempt",
]
