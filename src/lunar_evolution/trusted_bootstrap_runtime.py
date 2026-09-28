"""Provider-free trusted bootstrap runtime fixture and read-only observation.

This module is deliberately separate from the normal producer runner.  It exercises the
Feature 158 process boundary with a Lunar-owned Python bootstrap: the bootstrap emits a
ready frame, waits on a private one-byte gate, and only then starts the pinned target in its
existing process group.  It is a controlled fixture, not a scheduler entry point.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import selectors
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .process_ownership import RegisteredProcess, cleanup_registered_process
from .producer_bootstrap import (
    BootstrapHandshakeFrame,
    ProducerBootstrapError,
    TrustedBootstrapDescriptor,
    TrustedBootstrapEvidence,
    TrustedBootstrapLaunch,
    TrustedBootstrapSession,
    _strict_json,
    build_trusted_bootstrap_registration,
    parse_bootstrap_handshake_frame,
    parse_trusted_bootstrap_evidence,
    parse_trusted_bootstrap_registration,
    verify_trusted_bootstrap_attempt,
)
from .producer_launcher import (
    ProducerLaunchAttestation,
    ProducerLaunchError,
    parse_producer_launch_attestation,
)
from .producer_process import _current_process_owned, _process_owner_identity
from .trusted_bootstrap_handoff import (
    TrustedBootstrapHandoffError,
    verify_trusted_bootstrap_process_registration_handoff,
)

_MAX_CONTROL_BYTES = 64 * 1024
_MAX_FRAME_BYTES = 64 * 1024
_MAX_RUNTIME_SECONDS = 300.0
_SOURCE = Path(__file__).resolve()


class TrustedBootstrapRuntimeError(ValueError):
    """Fixed-code failure from the provider-free bootstrap fixture."""

    def __init__(self, code: str, *, evidence: TrustedBootstrapEvidence | None = None) -> None:
        self.code = code
        self.evidence = evidence
        super().__init__(code)


def trusted_bootstrap_source_path() -> Path:
    """Return the exact source file used by the fixture bootstrap process."""
    return _SOURCE


def _canonical(value: object) -> bytes:
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_control_invalid") from exc
    if len(data) > _MAX_CONTROL_BYTES:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_control_too_large")
    return data


def _digest_without(value: Mapping[str, object], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    return digest.hexdigest()
                digest.update(chunk)
    except OSError as exc:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_identity_unknown") from exc


def _identity(path: Path) -> dict[str, object]:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_identity_unknown") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_identity_invalid")
    return {
        "sha256": _sha256_file(path),
        "size": info.st_size,
        "device": info.st_dev,
        "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def build_trusted_bootstrap_descriptor(
    path: str | Path | None = None,
    *,
    implementation_version: str = "fixture-bootstrap-1",
    allowlist_id: str = "fixture-bootstrap",
    platform_execution_mode: str = "fixture-only",
) -> TrustedBootstrapDescriptor:
    """Build an exact descriptor for the controlled bootstrap source."""
    if platform_execution_mode != "fixture-only":
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_platform_mode_unsupported")
    source = _SOURCE if path is None else Path(path).resolve()
    observed = _identity(source)
    return TrustedBootstrapDescriptor(
        implementation_version=implementation_version,
        bootstrap_sha256=str(observed["sha256"]),
        size=int(observed["size"]),
        device=int(observed["device"]),
        inode=int(observed["inode"]),
        mtime_ns=int(observed["mtime_ns"]),
        ctime_ns=int(observed["ctime_ns"]),
        allowlist_id=allowlist_id,
        platform_execution_mode=platform_execution_mode,
    )


@dataclass(frozen=True, slots=True)
class TrustedBootstrapRuntimeResult:
    evidence: TrustedBootstrapEvidence
    registration_sha256: str
    registration_path: str
    bootstrap_pid: int
    bootstrap_pgid: int
    target_pid: int | None
    target_pgid: int | None
    target_exit_code: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence": self.evidence.to_dict(),
            "registration_sha256": self.registration_sha256,
            "registration_path": self.registration_path,
            "bootstrap_pid": self.bootstrap_pid,
            "bootstrap_pgid": self.bootstrap_pgid,
            "target_pid": self.target_pid,
            "target_pgid": self.target_pgid,
            "target_exit_code": self.target_exit_code,
        }


def _unknown_evidence(session: TrustedBootstrapSession) -> TrustedBootstrapEvidence:
    """Retain observations while refusing to report success after a deadline."""
    observed = session.evidence()
    if observed.status != "passed":
        return observed
    return TrustedBootstrapEvidence(
        launch_sha256=observed.launch_sha256,
        registration_sha256=observed.registration_sha256,
        bootstrap_ready_observed=observed.bootstrap_ready_observed,
        release_observed=observed.release_observed,
        target_started_observed=observed.target_started_observed,
        target_start_count=observed.target_start_count,
        target_group_identity=observed.target_group_identity,
        target_pid=observed.target_pid,
        target_pgid=observed.target_pgid,
        pre_gate_target_work_observed=observed.pre_gate_target_work_observed,
        status="unknown",
    )


def _registered_bootstrap_process(
    process: subprocess.Popen[bytes], pgid: int, launch_id: str,
) -> RegisteredProcess:
    owner_identity = _process_owner_identity(process.pid)
    if owner_identity is None:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_owner_identity_unknown")
    return RegisteredProcess(
        process.pid,
        pgid,
        owner_check=lambda: _current_process_owned(process.pid, owner_identity, process),
        label=launch_id,
    )


def _write_all(fd: int, data: bytes) -> None:
    written = 0
    while written < len(data):
        count = os.write(fd, data[written:])
        if count <= 0:
            raise OSError("short write")
        written += count


def _durable_json(path: Path, value: Mapping[str, object]) -> None:
    data = _canonical(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_registration_unknown") from exc


def _read_durable_bytes(name: str, *, parent: int, code: str) -> bytes:
    """Read one bounded regular artifact and reject a replacement during the read."""
    try:
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > _MAX_CONTROL_BYTES:
            raise TrustedBootstrapRuntimeError(code)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        try:
            opened = os.fstat(fd)
            data = bytearray()
            while len(data) <= _MAX_CONTROL_BYTES:
                chunk = os.read(fd, min(4096, _MAX_CONTROL_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except TrustedBootstrapRuntimeError:
        raise
    except OSError as exc:
        raise TrustedBootstrapRuntimeError(code) from exc
    def identity(info: os.stat_result) -> tuple[int, ...]:
        return (
            info.st_mode, info.st_nlink, info.st_dev, info.st_ino,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        )

    if (
        len(data) > _MAX_CONTROL_BYTES
        or identity(before) != identity(opened)
        or identity(before) != identity(after)
        or identity(before) != identity(current)
    ):
        raise TrustedBootstrapRuntimeError(code)
    return bytes(data)


def _recovery_workspace(workspace: str | Path) -> Path:
    if not isinstance(workspace, (str, Path)):
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_workspace_invalid")
    try:
        root = Path(workspace).expanduser().absolute()
        info = os.lstat(root)
    except (OSError, ValueError) as exc:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_workspace_invalid") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_workspace_invalid")
    return root


@contextmanager
def _held_recovery_directory(path: Path):
    """Hold the full no-follow directory chain through both artifact reads."""
    descriptors: list[int] = []
    links: list[tuple[int, str, int]] = []
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptors.append(os.open(path.anchor, flags))
        for part in path.parts[1:]:
            parent = descriptors[-1]
            try:
                info = os.stat(part, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                yield None
                return
            if not stat.S_ISDIR(info.st_mode):
                raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_registration_invalid")
            child = os.open(part, flags, dir_fd=parent)
            descriptors.append(child)
            links.append((parent, part, child))
            opened = os.fstat(child)
            if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_registration_invalid")
        yield descriptors[-1]
        for parent, part, child in reversed(links):
            current = os.stat(part, dir_fd=parent, follow_symlinks=False)
            held = os.fstat(child)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
                raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_registration_invalid")
    except TrustedBootstrapRuntimeError:
        raise
    except OSError as exc:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_registration_invalid") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _recovery_artifact(name: str, *, parent: int, code: str) -> bytes | None:
    """Return a stable artifact or ``None`` only when it was absent at read start."""
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise TrustedBootstrapRuntimeError(code) from exc
    return _read_durable_bytes(name, parent=parent, code=code)


def recover_trusted_bootstrap_fixture(
    workspace: str | Path, *, launch: TrustedBootstrapLaunch,
) -> dict[str, object]:
    """Read one fixture attempt's durable state without affecting its process lifecycle.

    This observation-only helper validates the canonical registration and terminal evidence from
    one journal. It does not inspect a PID, relaunch work, signal a process, or perform cleanup.
    Those operations remain owned by the Feature 156 runner.
    """
    if not isinstance(launch, TrustedBootstrapLaunch):
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_launch_invalid")
    root = _recovery_workspace(workspace)
    batch = root / "evolution" / "producer-batches" / launch.journal_id
    with _held_recovery_directory(batch) as parent:
        if parent is None:
            return {
                "status": "recovery_required",
                "reason": "trusted_bootstrap_registration_missing",
                "journal_id": launch.journal_id,
                "launch_id": launch.launch_id,
            }
        return _recover_from_held_directory(parent, launch=launch)


def _recover_from_held_directory(parent: int, *, launch: TrustedBootstrapLaunch) -> dict[str, object]:
    registration_bytes = _recovery_artifact(
        "trusted-bootstrap-registration.json", parent=parent,
        code="trusted_bootstrap_recovery_registration_invalid",
    )
    if registration_bytes is None:
        return {
            "status": "recovery_required",
            "reason": "trusted_bootstrap_registration_missing",
            "journal_id": launch.journal_id,
            "launch_id": launch.launch_id,
        }
    try:
        registration = parse_trusted_bootstrap_registration(registration_bytes, launch=launch)
    except ProducerBootstrapError as exc:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_registration_invalid") from exc

    evidence_bytes = _recovery_artifact(
        "trusted-bootstrap-evidence.json", parent=parent,
        code="trusted_bootstrap_recovery_evidence_invalid",
    )
    if evidence_bytes is None:
        return {
            "status": "recovery_required",
            "reason": "trusted_bootstrap_terminal_evidence_missing",
            "journal_id": launch.journal_id,
            "launch_id": launch.launch_id,
            "registration_sha256": registration.registration_sha256,
            "pid": registration.pid,
            "pgid": registration.pgid,
        }
    try:
        evidence = parse_trusted_bootstrap_evidence(evidence_bytes)
    except ProducerBootstrapError as exc:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_evidence_invalid") from exc
    if (
        evidence.launch_sha256 != launch.launch_sha256
        or evidence.registration_sha256 != registration.registration_sha256
    ):
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_evidence_binding_mismatch")
    if evidence.target_pgid is not None and evidence.target_pgid != registration.pgid:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_recovery_target_group_mismatch")
    if evidence.status == "unknown":
        return {
            "status": "recovery_required",
            "reason": "trusted_bootstrap_evidence_unknown",
            "journal_id": launch.journal_id,
            "launch_id": launch.launch_id,
            "registration_sha256": registration.registration_sha256,
            "evidence_sha256": evidence.evidence_sha256,
            "pid": registration.pid,
            "pgid": registration.pgid,
        }
    return {
        "status": "evidence_available",
        "bootstrap_status": evidence.status,
        "journal_id": launch.journal_id,
        "launch_id": launch.launch_id,
        "registration_sha256": registration.registration_sha256,
        "evidence_sha256": evidence.evidence_sha256,
        "pid": registration.pid,
        "pgid": registration.pgid,
    }


def observe_trusted_bootstrap_attempt(
    workspace: str | Path, *, launch: TrustedBootstrapLaunch,
    descriptor: TrustedBootstrapDescriptor, intent: object, attestation: object,
    require_handoff: bool = False,
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Validate the persisted formal attempt without inspecting or controlling processes."""
    def check_deadline() -> None:
        if deadline is not None and monotonic() >= deadline:
            raise ProducerBootstrapError("producer_bootstrap_attempt_wall_timeout")

    if not isinstance(launch, TrustedBootstrapLaunch):
        raise ProducerBootstrapError("producer_bootstrap_attempt_launch_invalid")
    check_deadline()
    try:
        parsed_attestation = parse_producer_launch_attestation(
            attestation.to_dict() if isinstance(attestation, ProducerLaunchAttestation) else attestation,
        )
    except (ProducerLaunchError, TypeError, ValueError) as exc:
        raise ProducerBootstrapError("producer_bootstrap_attempt_admission_invalid") from exc

    try:
        root = _recovery_workspace(workspace)
        batch = root / "evolution" / "producer-batches" / launch.journal_id
        nonce_key = hashlib.sha256(parsed_attestation.nonce.encode("utf-8")).hexdigest()
        nonce_directory = root / "evolution" / "producer-nonces"
        with _held_recovery_directory(batch) as journal_fd:
            if journal_fd is None:
                raise ProducerBootstrapError("producer_bootstrap_attempt_claim_missing")
            claim = _recovery_artifact(
                "attestation-consumption.json", parent=journal_fd,
                code="producer_bootstrap_attempt_claim_invalid",
            )
            if claim is None:
                raise ProducerBootstrapError("producer_bootstrap_attempt_claim_missing")
            with _held_recovery_directory(nonce_directory) as nonce_fd:
                if nonce_fd is None:
                    raise ProducerBootstrapError("producer_bootstrap_attempt_nonce_ledger_missing")
                ledger_claim = _recovery_artifact(
                    f"{nonce_key}.json", parent=nonce_fd,
                    code="producer_bootstrap_attempt_nonce_ledger_invalid",
                )
                if ledger_claim is None:
                    raise ProducerBootstrapError("producer_bootstrap_attempt_nonce_ledger_missing")
                if ledger_claim != claim:
                    raise ProducerBootstrapError("producer_bootstrap_attempt_nonce_ledger_mismatch")
                registration = _recovery_artifact(
                    "process-registration.json", parent=journal_fd,
                    code="producer_bootstrap_attempt_registration_invalid",
                )
                if registration is None:
                    raise ProducerBootstrapError("producer_bootstrap_attempt_registration_missing")
                handoff = None
                if require_handoff:
                    check_deadline()
                    handoff = _recovery_artifact(
                        "trusted-bootstrap-handoff.json", parent=journal_fd,
                        code="producer_bootstrap_attempt_handoff_invalid",
                    )
                    if handoff is None:
                        raise ProducerBootstrapError("producer_bootstrap_attempt_handoff_missing")
                evidence = _recovery_artifact(
                    "trusted-bootstrap-evidence.json", parent=journal_fd,
                    code="producer_bootstrap_attempt_evidence_invalid",
                )
                result = verify_trusted_bootstrap_attempt(
                    launch, descriptor, intent, parsed_attestation, claim, registration,
                    evidence=evidence,
                )
                if handoff is not None:
                    try:
                        verified_handoff = verify_trusted_bootstrap_process_registration_handoff(
                            handoff, launch=launch, descriptor=descriptor, intent=intent,
                            attestation=parsed_attestation, consumption=_strict_json(claim),
                            registration=_strict_json(registration),
                        )
                    except TrustedBootstrapHandoffError as exc:
                        raise ProducerBootstrapError(exc.code) from exc
                    result["handoff_sha256"] = verified_handoff["handoff_sha256"]
                check_deadline()
                return result
    except TrustedBootstrapRuntimeError as exc:
        raise ProducerBootstrapError(exc.code) from exc


def _read_frame(fd: int, deadline: float) -> BootstrapHandshakeFrame | None:
    selector = selectors.DefaultSelector()
    selector.register(fd, selectors.EVENT_READ)
    data = bytearray()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TrustedBootstrapRuntimeError("trusted_bootstrap_deadline_exceeded")
            events = selector.select(min(0.1, remaining))
            if not events:
                continue
            # Read one byte at a time so a coalesced pipe write cannot discard the
            # beginning of the next canonical frame.  The fixture is control-plane
            # traffic only; the strict bound matters more than throughput here.
            chunk = os.read(fd, 1)
            if not chunk:
                if not data:
                    return None
                raise TrustedBootstrapRuntimeError("trusted_bootstrap_frame_truncated")
            data.extend(chunk)
            if len(data) > _MAX_FRAME_BYTES:
                raise TrustedBootstrapRuntimeError("trusted_bootstrap_frame_too_large")
            if b"\n" not in data:
                continue
            line, _, _ = bytes(data).partition(b"\n")
            return parse_bootstrap_handshake_frame(line)
    except ProducerBootstrapError as exc:
        raise TrustedBootstrapRuntimeError(exc.code) from exc
    except OSError as exc:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_handshake_unknown") from exc
    finally:
        selector.close()


def _runtime_deadline(timeout_seconds: float) -> float:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= _MAX_RUNTIME_SECONDS
    ):
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_timeout_invalid")
    return time.monotonic() + float(timeout_seconds)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_deadline_exceeded")
    return remaining


def _target_command(control: Mapping[str, object]) -> tuple[Path, list[str], Path]:
    executable = control.get("target_executable")
    argv = control.get("target_argv")
    cwd = control.get("target_cwd")
    if not isinstance(executable, str) or not isinstance(cwd, str) or not isinstance(argv, list) or not argv:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_target_binding_invalid")
    if any(not isinstance(item, str) or not item for item in argv):
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_target_binding_invalid")
    target = Path(executable).resolve()
    working = Path(cwd).resolve()
    if not target.is_file() or not working.is_dir():
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_target_binding_invalid")
    return target, list(argv), working


def _bootstrap_child(launch_fd: int, gate_fd: int, frame_fd: int) -> int:
    """Run inside the Lunar-owned fixture bootstrap subprocess."""
    try:
        raw = bytearray()
        while len(raw) <= _MAX_CONTROL_BYTES:
            chunk = os.read(launch_fd, min(4096, _MAX_CONTROL_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > _MAX_CONTROL_BYTES:
            return 20
        control = json.loads(bytes(raw), object_pairs_hook=lambda pairs: dict(pairs))
        if not isinstance(control, dict):
            return 21
        launch = TrustedBootstrapLaunch(**control["launch"])
        descriptor = TrustedBootstrapDescriptor(**control["descriptor"])
        if descriptor.descriptor_sha256 != launch.bootstrap_descriptor_sha256:
            return 22
        observed = _identity(_SOURCE)
        expected = {
            "sha256": descriptor.bootstrap_sha256,
            "size": descriptor.size,
            "device": descriptor.device,
            "inode": descriptor.inode,
            "mtime_ns": descriptor.mtime_ns,
            "ctime_ns": descriptor.ctime_ns,
        }
        if any(observed[key] != expected[key] for key in expected):
            return 23
        def emit(sequence: int, kind: str, **kwargs: object) -> None:
            frame = BootstrapHandshakeFrame(
                sequence=sequence,
                kind=kind,
                launch_sha256=launch.launch_sha256 or launch.digest(),
                intent_sha256=launch.intent_sha256,
                **kwargs,
            )
            _write_all(frame_fd, json.dumps(frame.to_dict(), sort_keys=True, separators=(",", ":")).encode() + b"\n")

        emit(1, "bootstrap_ready")
        token = os.read(gate_fd, 2)
        if token != b"1":
            return 24
        try:
            target, argv, cwd = _target_command(control)
            target_identity = _identity(target)
        except TrustedBootstrapRuntimeError:
            emit(2, "target_start_failed")
            return 25
        if target_identity["sha256"] != launch.target_executable_identity:
            emit(2, "target_start_failed")
            return 25
        if argv[0] != str(target) and Path(argv[0]).resolve() != target:
            emit(2, "target_start_failed")
            return 26
        try:
            target_process = subprocess.Popen(
                argv,
                executable=str(target),
                shell=False,
                start_new_session=False,
                close_fds=True,
                cwd=str(cwd),
                env={"PATH": os.defpath, "LANG": "C", "LUNAR_BOOTSTRAP_RELEASED": "1"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            target_pgid = os.getpgid(target_process.pid)
        except (OSError, subprocess.SubprocessError):
            emit(2, "target_start_failed")
            return 27
        if target_pgid != os.getpgrp():
            target_process.kill()
            target_process.wait()
            emit(2, "target_start_failed")
            return 28
        emit(
            2,
            "target_started",
            target_executable_identity=str(target_identity["sha256"]),
            observed_pid=target_process.pid,
            observed_pgid=target_pgid,
        )
        target_exit_code = target_process.wait()
        emit(3, "terminal")
        # The parent waits on this bootstrap process after consuming the terminal
        # frame. Returning the target's bounded exit status keeps the fixture result
        # honest without adding producer-controlled text to the handshake protocol.
        if target_exit_code < 0:
            return 128 + min(-target_exit_code, 127)
        return min(target_exit_code, 255)
    except (OSError, ValueError, TypeError, KeyError, ProducerBootstrapError, subprocess.SubprocessError):
        return 29
    finally:
        for fd in (launch_fd, gate_fd, frame_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def run_trusted_bootstrap_fixture(
    workspace: str | Path,
    *,
    launch: TrustedBootstrapLaunch,
    descriptor: TrustedBootstrapDescriptor,
    target_executable: str | Path,
    target_argv: Sequence[str] | None = None,
    target_cwd: str | Path | None = None,
    timeout_seconds: float = 5.0,
    on_before_release: Callable[[Path], None] | None = None,
) -> TrustedBootstrapRuntimeResult:
    """Run one provider-free trusted bootstrap attempt.

    The registration receipt is durably published before the one-byte release token is
    written.  The function never retries a failed handshake and never starts a target itself.
    """
    if descriptor.descriptor_sha256 != launch.bootstrap_descriptor_sha256:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_descriptor_binding_mismatch")
    deadline = _runtime_deadline(timeout_seconds)
    if descriptor.platform_execution_mode != "fixture-only":
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_platform_mode_unsupported")
    admitted_descriptor = build_trusted_bootstrap_descriptor(
        implementation_version=descriptor.implementation_version,
        allowlist_id=descriptor.allowlist_id,
    )
    if descriptor.to_dict() != admitted_descriptor.to_dict():
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_descriptor_not_allowlisted")
    target = Path(target_executable).resolve()
    target_identity = _identity(target)
    if target_identity["sha256"] != launch.target_executable_identity:
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_target_identity_mismatch")
    cwd = Path(target_cwd).resolve() if target_cwd is not None else target.parent
    argv = list(target_argv) if target_argv is not None else [str(target)]
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_target_binding_invalid")
    workspace_root = Path(workspace).resolve()
    batch = workspace_root / "evolution" / "producer-batches" / launch.journal_id
    registration_path = batch / "trusted-bootstrap-registration.json"
    evidence_path = batch / "trusted-bootstrap-evidence.json"
    launch_read, launch_write = os.pipe()
    gate_read, gate_write = os.pipe()
    frame_read, frame_write = os.pipe()
    process: subprocess.Popen[bytes] | None = None
    registration_digest = ""
    session = TrustedBootstrapSession(launch, "0" * 64)
    target_pid: int | None = None
    target_pgid: int | None = None
    target_exit_code: int | None = None
    registration_process: RegisteredProcess | None = None
    evidence: TrustedBootstrapEvidence | None = None
    cleanup_done = False
    try:
        control = {
            "launch": launch.to_dict(),
            "descriptor": descriptor.to_dict(),
            "target_executable": str(target),
            "target_argv": argv,
            "target_cwd": str(cwd),
        }
        source_root = str(_SOURCE.parents[1])
        env = {"PATH": os.defpath, "LANG": "C", "PYTHONPATH": source_root}
        process = subprocess.Popen(
            [sys.executable, "-m", "lunar_evolution.trusted_bootstrap_runtime", "--child", str(launch_read), str(gate_read), str(frame_write)],
            shell=False,
            start_new_session=True,
            close_fds=True,
            pass_fds=(launch_read, gate_read, frame_write),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.close(launch_read)
        os.close(gate_read)
        os.close(frame_write)
        launch_read = gate_read = frame_write = -1
        bootstrap_pgid = os.getpgid(process.pid)
        if bootstrap_pgid != process.pid:
            raise TrustedBootstrapRuntimeError("trusted_bootstrap_process_group_invalid")
        registration_process = _registered_bootstrap_process(process, bootstrap_pgid, launch.launch_id)
        _write_all(launch_write, _canonical(control))
        os.close(launch_write)
        launch_write = -1
        frame = _read_frame(frame_read, deadline)
        if frame is None:
            raise TrustedBootstrapRuntimeError("trusted_bootstrap_ready_missing")
        session.accept_frame(frame)
        registration = build_trusted_bootstrap_registration(
            launch, pid=process.pid, pgid=bootstrap_pgid,
        ).to_dict()
        parse_trusted_bootstrap_registration(registration, launch=launch)
        registration_digest = str(registration["registration_sha256"])
        session.registration_sha256 = registration_digest
        _durable_json(registration_path, registration)
        if on_before_release is not None:
            on_before_release(registration_path)
        _remaining(deadline)
        session.release(launch.gate_nonce)
        _write_all(gate_write, b"1")
        os.close(gate_write)
        gate_write = -1
        frame = _read_frame(frame_read, deadline)
        if frame is None:
            session.record_eof()
        else:
            session.accept_frame(frame)
            if frame.kind == "target_started":
                target_pid, target_pgid = frame.observed_pid, frame.observed_pgid
                frame = _read_frame(frame_read, deadline)
                if frame is None:
                    session.record_eof()
                else:
                    session.accept_frame(frame)
                    if frame.kind == "terminal":
                        trailing = _read_frame(frame_read, deadline)
                        if trailing is not None:
                            session.accept_frame(trailing)
        target_exit_code = process.wait(timeout=_remaining(deadline))
        cleanup_result = cleanup_registered_process(
            registration_process,
            grace_seconds=min(0.25, max(0.001, _remaining(deadline))),
            deadline=deadline,
            allow_exited_leader_initial=True,
        )
        if cleanup_result.status.value not in {"already_exited", "cleaned"}:
            evidence = _unknown_evidence(session)
            raise TrustedBootstrapRuntimeError(
                "trusted_bootstrap_cleanup_unknown", evidence=evidence,
            )
        cleanup_done = True
        evidence = session.evidence()
        _durable_json(evidence_path, evidence.to_dict())
        if evidence.status != "passed":
            raise TrustedBootstrapRuntimeError(evidence.failure_code or "trusted_bootstrap_unknown", evidence=evidence)
        return TrustedBootstrapRuntimeResult(
            evidence=evidence,
            registration_sha256=registration_digest,
            registration_path=str(registration_path),
            bootstrap_pid=process.pid,
            bootstrap_pgid=bootstrap_pgid,
            target_pid=target_pid,
            target_pgid=target_pgid,
            target_exit_code=target_exit_code,
        )
    except ProducerBootstrapError as exc:
        try:
            session.fail(exc.code)
        except ProducerBootstrapError:
            pass
        raise TrustedBootstrapRuntimeError(exc.code, evidence=session.evidence()) from exc
    except subprocess.TimeoutExpired as exc:
        evidence = _unknown_evidence(session)
        raise TrustedBootstrapRuntimeError(
            "trusted_bootstrap_deadline_exceeded", evidence=evidence,
        ) from exc
    except TrustedBootstrapRuntimeError as exc:
        if exc.evidence is None:
            try:
                exc.evidence = _unknown_evidence(session)
            except ProducerBootstrapError:
                exc.evidence = None
        raise
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        evidence = _unknown_evidence(session)
        raise TrustedBootstrapRuntimeError("trusted_bootstrap_runtime_unknown", evidence=evidence) from exc
    finally:
        for fd in (launch_read, launch_write, gate_read, gate_write, frame_read, frame_write):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if process is not None and registration_process is not None and not cleanup_done:
            cleanup_registered_process(
                registration_process,
                grace_seconds=0.25,
                deadline=deadline,
                allow_exited_leader_initial=process.poll() is not None,
            )
        if process is not None and process.stderr is not None:
            process.stderr.close()
        if registration_digest and not evidence_path.exists():
            try:
                _durable_json(evidence_path, (evidence or _unknown_evidence(session)).to_dict())
            except TrustedBootstrapRuntimeError:
                pass


def _main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("fds", nargs="*")
    args = parser.parse_args()
    if not args.child or len(args.fds) != 3:
        return 2
    try:
        return _bootstrap_child(*(int(value) for value in args.fds))
    except (TypeError, ValueError):
        return 3


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "TrustedBootstrapRuntimeError",
    "TrustedBootstrapRuntimeResult",
    "build_trusted_bootstrap_descriptor",
    "recover_trusted_bootstrap_fixture",
    "run_trusted_bootstrap_fixture",
    "trusted_bootstrap_source_path",
]
