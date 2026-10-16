"""Read-only local process and workspace evidence for external-worker recovery.

The callback journal records what the controller *was told* about a worker.  This module
adds the small OS observation needed before a quarantined ``unknown`` can be settled:
the original process identity must no longer be present, its private process group must
be gone, and the workspace/transport/journal objects must still be the objects captured
at claim time.  It is deliberately local and fail-closed.  It never signals a process,
starts a worker, authenticates a remote source, or treats an unavailable probe as proof
of termination.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .candidate_evaluation_spec import canonical_json
from .external_worker_evidence import (
    ExternalWorkerReconcileEvidence,
    ExternalWorkerTrustProfile,
)
from .producer_process import _process_owner_identity

_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX = 128 * 1024

ProcessObservationStatus = Literal["running", "exited", "drifted", "unknown"]


class LocalWorkerProcessEvidenceError(ValueError):
    """Fixed-code errors from the local process/workspace observation boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _digest(value: object) -> str:
    try:
        payload = canonical_json(value, maximum=_MAX)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise LocalWorkerProcessEvidenceError("local_worker_evidence_canonical_invalid") from exc
    return hashlib.sha256(payload).hexdigest()


def process_start_identity_sha256(pid: int) -> str:
    """Return the boot/start-time identity digest for a live local process.

    The underlying platform observation is shared with the native producer lifecycle.  A
    missing or unsupported identity is an error rather than a fabricated PID-only token;
    callers must leave recovery in ``unknown`` in that case.
    """

    if type(pid) is not int or pid <= 1:
        raise LocalWorkerProcessEvidenceError("local_worker_pid_invalid")
    identity = _process_owner_identity(pid)
    if identity is None:
        raise LocalWorkerProcessEvidenceError("local_worker_process_identity_unavailable")
    return _digest(identity)


@dataclass(frozen=True, slots=True)
class LocalObjectObservation:
    """One path's immutable device/inode observation."""

    expected_device: int
    expected_inode: int
    observed_device: int | None
    observed_inode: int | None
    kind: str
    matches: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_device": self.expected_device,
            "expected_inode": self.expected_inode,
            "observed_device": self.observed_device,
            "observed_inode": self.observed_inode,
            "kind": self.kind,
            "matches": self.matches,
        }


@dataclass(frozen=True, slots=True)
class LocalWorkerProcessObservation:
    """A point-in-time local observation with no ownership or launch authority."""

    profile_sha256: str
    status: ProcessObservationStatus
    pid: int
    pgid: int
    expected_process_start_identity: str
    observed_process_start_identity: str | None
    process_state: str | None
    process_group: Literal["present", "absent", "unknown"]
    workspace: LocalObjectObservation
    transport: LocalObjectObservation
    journal: LocalObjectObservation
    terminal_observed: bool
    cleanup_confirmed: bool
    reason: str

    @property
    def eligible_for_reconcile(self) -> bool:
        """Whether this observation can bind a non-success unknown reconciliation."""

        return (
            self.status == "exited"
            and self.terminal_observed
            and self.cleanup_confirmed
            and self.workspace.matches
            and self.transport.matches
            and self.journal.matches
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_sha256": self.profile_sha256,
            "status": self.status,
            "pid": self.pid,
            "pgid": self.pgid,
            "expected_process_start_identity": self.expected_process_start_identity,
            "observed_process_start_identity": self.observed_process_start_identity,
            "process_state": self.process_state,
            "process_group": self.process_group,
            "workspace": self.workspace.to_dict(),
            "transport": self.transport.to_dict(),
            "journal": self.journal.to_dict(),
            "terminal_observed": self.terminal_observed,
            "cleanup_confirmed": self.cleanup_confirmed,
            "eligible_for_reconcile": self.eligible_for_reconcile,
            "reason": self.reason,
        }

    def reconcile_evidence(
        self,
        *,
        unknown_checkpoint_sha256: str,
        status: str,
        terminal_receipt_sha256: str,
        reason: str = "local process and workspace observation",
    ) -> ExternalWorkerReconcileEvidence:
        """Bind this exact observation to a failed/timeout/cancelled/abandoned receipt."""

        if not self.eligible_for_reconcile:
            raise LocalWorkerProcessEvidenceError("local_worker_reconcile_observation_ineligible")
        if _SHA.fullmatch(unknown_checkpoint_sha256) is None:
            raise LocalWorkerProcessEvidenceError("local_worker_unknown_checkpoint_invalid")
        if _SHA.fullmatch(terminal_receipt_sha256) is None:
            raise LocalWorkerProcessEvidenceError("local_worker_terminal_receipt_invalid")
        if type(status) is not str:
            raise LocalWorkerProcessEvidenceError("local_worker_terminal_state_invalid")
        return ExternalWorkerReconcileEvidence(
            profile_sha256=self.profile_sha256,
            unknown_checkpoint_sha256=unknown_checkpoint_sha256,
            status=status,
            terminal_receipt_sha256=terminal_receipt_sha256,
            controller_observed_terminal=True,
            cleanup_confirmed=True,
            reason=reason,
        )


def _object_observation(path: Path, expected_device: int, expected_inode: int) -> LocalObjectObservation:
    if not isinstance(path, Path):
        raise LocalWorkerProcessEvidenceError("local_worker_path_invalid")
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return LocalObjectObservation(expected_device, expected_inode, None, None, "absent", False)
    except OSError:
        return LocalObjectObservation(expected_device, expected_inode, None, None, "unreadable", False)
    observed = (int(info.st_dev), int(info.st_ino))
    kind = (
        "symlink" if stat.S_ISLNK(info.st_mode)
        else "directory" if stat.S_ISDIR(info.st_mode)
        else "regular" if stat.S_ISREG(info.st_mode)
        else "other"
    )
    # The type is informational, while the device/inode pair is the binding.  Symlinks
    # are always rejected: a path resolving to the original object is still a path swap
    # at the controller boundary.
    matches = kind != "symlink" and observed == (expected_device, expected_inode)
    return LocalObjectObservation(expected_device, expected_inode, observed[0], observed[1], kind, matches)


def _probe_group(pgid: int) -> Literal["present", "absent", "unknown"]:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return "absent"
    except PermissionError:
        return "unknown"
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return "absent"
        if exc.errno == errno.EPERM:
            return "unknown"
        return "unknown"
    return "present"


def _linux_state(pid: int) -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except (FileNotFoundError, OSError, UnicodeError):
        return None
    marker = raw.rfind(")")
    if marker < 0:
        return None
    fields = raw[marker + 2 :].split()
    return fields[0] if fields else None


def observe_local_worker(
    profile: ExternalWorkerTrustProfile,
    *,
    workspace: Path,
    transport: Path,
    journal: Path,
) -> LocalWorkerProcessObservation:
    """Observe a claimed worker using only this host's OS and filesystem.

    ``running`` means the exact PID/start identity and process group are still present.
    ``exited`` requires the PID to be absent (or a reaped zombie) *and* the process group
    to be absent.  ``unknown`` covers permission, unsupported identity, or probe errors;
    it is never upgraded to a terminal state.  Any changed inode/start identity is
    ``drifted`` and cannot produce reconcile evidence.
    """

    if not isinstance(profile, ExternalWorkerTrustProfile):
        raise LocalWorkerProcessEvidenceError("local_worker_profile_invalid")
    objects = (
        _object_observation(workspace, profile.workspace_device, profile.workspace_inode),
        _object_observation(transport, profile.transport_device, profile.transport_inode),
        _object_observation(journal, profile.journal_device, profile.journal_inode),
    )
    workspace_observation, transport_observation, journal_observation = objects
    profile_sha = profile.digest()
    observed_identity: str | None = None
    process_state = _linux_state(profile.pid)
    process_group: Literal["present", "absent", "unknown"] = "unknown"
    reason = "process observation unavailable"
    status: ProcessObservationStatus = "unknown"
    identity = _process_owner_identity(profile.pid)
    if identity is not None:
        observed_identity = _digest(identity)
        if observed_identity != profile.process_start_identity:
            status, reason = "drifted", "process start identity changed"
        else:
            try:
                observed_pgid = os.getpgid(profile.pid)
            except ProcessLookupError:
                observed_pgid = None
            except OSError:
                observed_pgid = -1
            if observed_pgid not in {profile.pgid, None}:
                status, reason = "drifted", "process group changed"
            elif observed_pgid is None:
                process_group = _probe_group(profile.pgid)
                status = "exited" if process_group == "absent" else "unknown"
                reason = "process exited" if status == "exited" else "process group unresolved"
            else:
                process_group = _probe_group(profile.pgid)
                if process_group == "present":
                    status, reason = "running", "exact process and group are live"
                elif process_group == "absent":
                    # A live process with no group is contradictory; retain unknown.
                    status, reason = "unknown", "process group disappeared while process is live"
                else:
                    status, reason = "unknown", "process group probe denied"
    else:
        try:
            os.kill(profile.pid, 0)
        except ProcessLookupError:
            process_group = _probe_group(profile.pgid)
            status = "exited" if process_group == "absent" else "unknown"
            reason = "process exited" if status == "exited" else "process identity absent but group unresolved"
        except PermissionError:
            status, reason = "unknown", "process probe denied"
        except OSError:
            status, reason = "unknown", "process probe failed"

    paths_match = all(item.matches for item in objects)
    if status == "exited" and not paths_match:
        status, reason = "drifted", "workspace fingerprint changed"
    terminal_observed = status == "exited"
    cleanup_confirmed = terminal_observed and process_group == "absent"
    return LocalWorkerProcessObservation(
        profile_sha256=profile_sha,
        status=status,
        pid=profile.pid,
        pgid=profile.pgid,
        expected_process_start_identity=profile.process_start_identity,
        observed_process_start_identity=observed_identity,
        process_state=process_state,
        process_group=process_group,
        workspace=workspace_observation,
        transport=transport_observation,
        journal=journal_observation,
        terminal_observed=terminal_observed,
        cleanup_confirmed=cleanup_confirmed,
        reason=reason,
    )


__all__ = [
    "LocalObjectObservation",
    "LocalWorkerProcessEvidenceError",
    "LocalWorkerProcessObservation",
    "ProcessObservationStatus",
    "observe_local_worker",
    "process_start_identity_sha256",
]
