"""Prepare separately bound bootstrap and target bytes for one trusted attempt.

This module prepares execution handles only. It does not consume an attestation,
spawn a process, publish registration, or authorize gate release.
"""

from __future__ import annotations

import os
import stat
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from .linux_executable_binding import (
    LinuxExecutableBindingError,
    LinuxSealedExecutable,
    _validate_original_linux_executable,
    sealed_linux_executable,
)
from .producer_bootstrap import (
    ProducerBootstrapError,
    TrustedBootstrapDescriptor,
    TrustedBootstrapLaunch,
    build_trusted_bootstrap_launch,
)
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import (
    ProducerExecutableSnapshot,
    ProducerProcessError,
    _relative_path,
    _remove_executable_snapshot,
    _safe_dir,
    _safe_root,
    _snapshot_executable,
)


class TrustedBootstrapBindingError(ValueError):
    """Fixed-code failure before a trusted executable pair is handed to a runner."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BoundExecutable:
    executable: str
    snapshot: ProducerExecutableSnapshot
    pass_fd: int | None = None


@dataclass(frozen=True, slots=True)
class TrustedExecutablePair:
    bootstrap: BoundExecutable
    target: BoundExecutable

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return tuple(fd for fd in (self.bootstrap.pass_fd, self.target.pass_fd) if fd is not None)


@dataclass(slots=True)
class _LinuxPairOwner:
    bootstrap: LinuxSealedExecutable
    target: LinuxSealedExecutable
    projections: tuple[tuple[object, ...], tuple[object, ...]]
    roles: tuple[BoundExecutable, BoundExecutable]
    snapshots: tuple[ProducerExecutableSnapshot, ProducerExecutableSnapshot]


_LINUX_PAIRS: dict[int, tuple[TrustedExecutablePair, _LinuxPairOwner]] = {}


def _projection(bound: BoundExecutable) -> tuple[object, ...]:
    if type(bound) is not BoundExecutable or type(bound.snapshot) is not ProducerExecutableSnapshot:
        raise TrustedBootstrapBindingError("trusted_binding_owner_invalid")
    snapshot = bound.snapshot
    values = (bound.executable, bound.pass_fd, snapshot.relative_path,
              snapshot.sha256, snapshot.size, snapshot.binding)
    if (type(values[0]) is not str or type(values[1]) is not int
            or values[2] is not None or type(values[3]) is not str
            or type(values[4]) is not int or type(values[5]) is not str):
        raise TrustedBootstrapBindingError("trusted_binding_owner_invalid")
    return values


def _binding_error(exc: LinuxExecutableBindingError) -> TrustedBootstrapBindingError:
    code = {
        "linux_execution_source_changed": "trusted_binding_source_changed",
        "linux_execution_cleanup_unknown": "trusted_binding_cleanup_unknown",
    }.get(exc.code, exc.code)
    mapped = TrustedBootstrapBindingError(code)
    if "linux_execution_cleanup_unknown" in getattr(exc, "__notes__", ()):
        mapped.add_note("linux_execution_cleanup_unknown")
    return mapped


def _validate_original_linux_executable_pair(pair: TrustedExecutablePair) -> None:
    """Validate a live Linux factory pair without reconstructing owner authority."""
    entry = _LINUX_PAIRS.get(id(pair))
    if type(pair) is not TrustedExecutablePair or entry is None or entry[0] is not pair:
        raise TrustedBootstrapBindingError("trusted_binding_owner_invalid")
    owner = entry[1]
    for index, bound in enumerate((pair.bootstrap, pair.target)):
        if (bound is not owner.roles[index] or bound.snapshot is not owner.snapshots[index]
                or _projection(bound) != owner.projections[index]):
            raise TrustedBootstrapBindingError("trusted_binding_owner_invalid")
    try:
        _validate_original_linux_executable(owner.bootstrap)
        _validate_original_linux_executable(owner.target)
    except LinuxExecutableBindingError as exc:
        raise _binding_error(exc) from exc


def _identity_from_descriptor(descriptor: TrustedBootstrapDescriptor) -> dict[str, int | str]:
    return {
        "sha256": descriptor.bootstrap_sha256, "size": descriptor.size,
        "device": descriptor.device, "inode": descriptor.inode,
        "mtime_ns": descriptor.mtime_ns, "ctime_ns": descriptor.ctime_ns,
    }


def _identity_from_intent(intent: ProducerLaunchIntent) -> dict[str, int | str]:
    return {
        "sha256": intent.executable_sha256, "size": intent.executable_size,
        "device": intent.executable_device, "inode": intent.executable_inode,
        "mtime_ns": intent.executable_mtime_ns, "ctime_ns": intent.executable_ctime_ns,
    }


def _snapshot_path(batch: Path, role: str) -> Path:
    return batch / ".producer-snapshots" / role


def _require_snapshot_absent(batch: Path, role: str) -> None:
    try:
        os.lstat(_snapshot_path(batch, role))
    except FileNotFoundError:
        return
    except OSError as exc:
        raise TrustedBootstrapBindingError("trusted_binding_snapshot_state_unknown") from exc
    raise TrustedBootstrapBindingError("trusted_binding_snapshot_exists")


def _remove_pre_spawn_snapshot(snapshot: ProducerExecutableSnapshot | None, batch: Path) -> None:
    if snapshot is None:
        return
    if snapshot.relative_path is None:
        raise TrustedBootstrapBindingError("trusted_binding_cleanup_unknown")
    _remove_executable_snapshot(snapshot, batch)
    try:
        os.lstat(batch / snapshot.relative_path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise TrustedBootstrapBindingError("trusted_binding_cleanup_unknown") from exc
    raise TrustedBootstrapBindingError("trusted_binding_cleanup_unknown")


def _require_unreturned_snapshot_absent(batch: Path, role: str) -> None:
    # A snapshot maker can fail after publication but before returning ownership.
    # Retain such a file for recovery; its inode was never handed to this helper.
    try:
        os.lstat(_snapshot_path(batch, role))
    except FileNotFoundError:
        return
    except OSError as exc:
        raise TrustedBootstrapBindingError("trusted_binding_cleanup_unknown") from exc
    raise TrustedBootstrapBindingError("trusted_binding_cleanup_unknown")


@contextmanager
def prepare_trusted_executable_pair(
    *,
    bootstrap_source: str | Path,
    producer_root: str | Path,
    batch: str | Path,
    descriptor: TrustedBootstrapDescriptor,
    launch: TrustedBootstrapLaunch,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> Iterator[TrustedExecutablePair]:
    """Hold both platform bindings through the caller's bootstrap ``Popen``.

    The descriptor must already have been selected from the installation's trusted
    allowlist. On Linux the caller must inherit both ``pass_fds`` into the bootstrap;
    the bootstrap must retain the target FD until its post-gate exec. On Darwin the
    caller owns immutable snapshot cleanup after terminal process quiescence.
    """
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(attestation, ProducerLaunchAttestation):
        raise TrustedBootstrapBindingError("trusted_binding_admission_invalid")
    try:
        expected_launch = build_trusted_bootstrap_launch(intent, attestation, descriptor)
    except (ProducerBootstrapError, TypeError, ValueError) as exc:
        raise TrustedBootstrapBindingError("trusted_binding_admission_invalid") from exc
    if not isinstance(launch, TrustedBootstrapLaunch) or launch != expected_launch:
        raise TrustedBootstrapBindingError("trusted_binding_launch_mismatch")
    if monotonic() >= deadline:
        raise TrustedBootstrapBindingError("trusted_binding_wall_timeout")
    try:
        root = _safe_root(producer_root, "producer_process_producer_root_invalid")
        batch_path = _safe_root(batch, "producer_process_batch_invalid")
        _safe_dir(batch_path)
        bootstrap_path = Path(bootstrap_source).expanduser().absolute()
        _safe_dir(bootstrap_path.parent)
        target_path = _relative_path(root, intent.executable_relative)
        _safe_dir(target_path.parent)
        bootstrap_identity = _identity_from_descriptor(descriptor)
        target_identity = _identity_from_intent(intent)
        if (bootstrap_identity["device"], bootstrap_identity["inode"]) == (
            target_identity["device"], target_identity["inode"]
        ):
            raise TrustedBootstrapBindingError("trusted_binding_sources_not_distinct")
    except ProducerProcessError as exc:
        raise TrustedBootstrapBindingError("trusted_binding_source_invalid") from exc

    if sys.platform == "darwin":
        _require_snapshot_absent(batch_path, "bootstrap")
        _require_snapshot_absent(batch_path, "target")
        bootstrap_snapshot: ProducerExecutableSnapshot | None = None
        target_snapshot: ProducerExecutableSnapshot | None = None
        try:
            bootstrap_snapshot = _snapshot_executable(
                bootstrap_path, batch_path, bootstrap_identity,
                deadline=deadline, monotonic=monotonic, role="bootstrap",
            )
            target_snapshot = _snapshot_executable(
                target_path, batch_path, target_identity,
                deadline=deadline, monotonic=monotonic, role="target",
            )
            for role, snapshot in (("bootstrap", bootstrap_snapshot), ("target", target_snapshot)):
                if snapshot.relative_path != f".producer-snapshots/{role}":
                    raise TrustedBootstrapBindingError("trusted_binding_snapshot_invalid")
                mode = os.stat(batch_path / snapshot.relative_path, follow_symlinks=False).st_mode
                if not mode & 0o111 or mode & (stat.S_ISUID | stat.S_ISGID):
                    raise TrustedBootstrapBindingError("trusted_binding_mode_invalid")
            if monotonic() >= deadline:
                raise TrustedBootstrapBindingError("trusted_binding_wall_timeout")
        except (ProducerProcessError, TrustedBootstrapBindingError, OSError) as exc:
            cleanup_failed = False
            for snapshot in (target_snapshot, bootstrap_snapshot):
                try:
                    _remove_pre_spawn_snapshot(snapshot, batch_path)
                except TrustedBootstrapBindingError:
                    cleanup_failed = True
            for role, snapshot in (
                ("target", target_snapshot),
                ("bootstrap", bootstrap_snapshot),
            ):
                if snapshot is None:
                    try:
                        _require_unreturned_snapshot_absent(batch_path, role)
                    except TrustedBootstrapBindingError:
                        cleanup_failed = True
            if cleanup_failed:
                raise TrustedBootstrapBindingError("trusted_binding_cleanup_unknown") from exc
            if isinstance(exc, TrustedBootstrapBindingError):
                raise
            if isinstance(exc, OSError):
                raise TrustedBootstrapBindingError("trusted_binding_mode_unknown") from exc
            if exc.code == "producer_process_executable_changed":
                raise TrustedBootstrapBindingError("trusted_binding_source_changed") from exc
            raise TrustedBootstrapBindingError(exc.code) from exc
        yield TrustedExecutablePair(
            BoundExecutable(str(batch_path / bootstrap_snapshot.relative_path), bootstrap_snapshot),
            BoundExecutable(str(batch_path / target_snapshot.relative_path), target_snapshot),
        )
        return

    if not sys.platform.startswith("linux"):
        raise TrustedBootstrapBindingError("trusted_binding_platform_unsupported")
    body_primary: BaseException | None = None
    try:
        with ExitStack() as stack:
            bootstrap_bound = stack.enter_context(sealed_linux_executable(
                bootstrap_path, bootstrap_identity, deadline=deadline, monotonic=monotonic,
            ))
            target_bound = stack.enter_context(sealed_linux_executable(
                target_path, target_identity, deadline=deadline, monotonic=monotonic,
            ))
            if monotonic() >= deadline:
                raise TrustedBootstrapBindingError("trusted_binding_wall_timeout")
            pair = TrustedExecutablePair(
                BoundExecutable(
                    bootstrap_bound.executable,
                    ProducerExecutableSnapshot(None, bootstrap_bound.sha256, bootstrap_bound.size, bootstrap_bound.binding),
                    bootstrap_bound.pass_fd,
                ),
                BoundExecutable(
                    target_bound.executable,
                    ProducerExecutableSnapshot(None, target_bound.sha256, target_bound.size, target_bound.binding),
                    target_bound.pass_fd,
                ),
            )
            owner = _LinuxPairOwner(
                bootstrap_bound, target_bound,
                (_projection(pair.bootstrap), _projection(pair.target)),
                (pair.bootstrap, pair.target),
                (pair.bootstrap.snapshot, pair.target.snapshot),
            )
            _LINUX_PAIRS[id(pair)] = pair, owner
            try:
                _validate_original_linux_executable_pair(pair)
                try:
                    yield pair
                except BaseException as exc:
                    body_primary = exc
                    raise
            finally:
                _LINUX_PAIRS.pop(id(pair), None)
    except LinuxExecutableBindingError as exc:
        if exc is body_primary:
            raise
        if body_primary is not None:
            # ExitStack cleanup must not replace the caller's primary error,
            # including KeyboardInterrupt/SystemExit. Keep the cleanup signal
            # fixed and non-sensitive on that exact exception object.
            body_primary.add_note("linux_execution_cleanup_unknown")
            raise body_primary
        raise _binding_error(exc) from exc
