"""Provider-free local producer process lifecycle.

This module is intentionally small and strict.  It consumes a Feature 154 attestation once,
starts the pinned executable without a shell, records process ownership before releasing a private
gate, and returns bounded execution evidence.  It never invokes a provider or interprets producer
scores.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import selectors
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from .linux_executable_binding import LinuxExecutableBindingError, sealed_linux_executable
from .process_ownership import (
    ProcessCleanupResult,
    ProcessCleanupStatus,
    RegisteredProcess,
    cleanup_registered_process,
)
from .producer_launcher import (
    MAX_OUTPUT_BYTES,
    ProducerLaunchAttestation,
    ProducerLaunchError,
    ProducerLaunchIntent,
    verify_producer_launch_attestation,
)

PRODUCER_PROCESS_PROTOCOL = "lunar-producer-process-execution-v1"
GATE_ENV = "LUNAR_PRODUCER_GATE_FD"
_PROTOCOL = PRODUCER_PROCESS_PROTOCOL
_MAX_RECEIPT_BYTES = 256 * 1024
_MAX_CAPTURE_CHUNK = 64 * 1024
_UF_IMMUTABLE = 0x00000002
_SNAPSHOT_RELATIVE_PATH = ".producer-snapshots/executable"
_SNAPSHOT_PATHS = {
    "producer": _SNAPSHOT_RELATIVE_PATH,
    "bootstrap": ".producer-snapshots/bootstrap",
    "target": ".producer-snapshots/target",
}
_RECOVERY_LOCK_PROTOCOL = "journal-flock-v1"

_RECEIPT_FIELDS = frozenset({
    "schema_version", "protocol", "launch_id", "journal_id", "run_id", "parent_task_id",
    "task_id", "intent_sha256", "attestation_sha256", "consumption_sha256",
    "registration_sha256", "executable_identity", "pid", "pgid", "owner_identity",
    "gate_released", "request_timeout_seconds", "max_requests", "output_max_bytes",
    "wall_timeout_seconds", "request_count", "exit_code", "stdout_evidence", "stderr_evidence",
    "envelope_evidence", "cleanup_status", "cleanup_sha256", "execution_binding",
    "execution_snapshot_relative_path", "execution_snapshot_sha256", "execution_snapshot_size",
    "status", "failure_code", "previous_receipt_sha256", "receipt_sha256",
})
_RECEIPT_OPTIONAL_FIELDS = frozenset({"trusted_execution"})


class ProducerProcessError(ValueError):
    """Fixed-code lifecycle error without producer-controlled prose or paths."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProducerAttestationConsumption:
    """Durable identity of the one-time attestation claim."""

    launch_id: str
    nonce: str
    intent_sha256: str
    attestation_sha256: str
    consumption_sha256: str


@dataclass(frozen=True, slots=True)
class ProducerProcessRegistration:
    """Durable process identity written before the work gate is released."""

    launch_id: str
    pid: int
    pgid: int
    owner_identity: Mapping[str, object]
    intent_sha256: str
    attestation_sha256: str
    registration_sha256: str


def _fail(code: str) -> None:
    raise ProducerProcessError(code)


def _canonical(value: object) -> bytes:
    try:
        result = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProducerProcessError("producer_process_canonical_invalid") from exc
    if len(result) > _MAX_RECEIPT_BYTES:
        _fail("producer_process_receipt_too_large")
    return result


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _process_owner_identity(pid: int) -> dict[str, object] | None:
    """Return an OS-observed identity that changes when a PID is reused.

    The identity is deliberately small and contains no command line or producer data.  Linux
    exposes a boot-scoped process start tick in ``/proc``.  Darwin exposes microsecond start
    time through libproc.  Unsupported platforms return ``None`` so recovery remains
    fail-closed instead of treating a PID/PGID pair as ownership evidence.
    """
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return None
    try:
        if sys.platform.startswith("linux"):
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
            fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").strip()
            marker = fields.rfind(")")
            if marker < 0:
                return None
            values = fields[marker + 2 :].split()
            # The suffix starts at field 3 (state); field 22 is index 19 here.
            starttime = values[19]
            if not boot_id or not starttime.isdigit():
                return None
            return {
                "kind": "linux-proc-starttime-v1",
                "pid": pid,
                "boot_id": boot_id,
                "starttime_ticks": int(starttime),
            }
        if sys.platform == "darwin":
            import ctypes

            class ProcBsdInfo(ctypes.Structure):
                _fields_ = [
                    ("flags", ctypes.c_uint32), ("status", ctypes.c_uint32),
                    ("xstatus", ctypes.c_uint32), ("pid", ctypes.c_uint32),
                    ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32),
                    ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32),
                    ("rgid", ctypes.c_uint32), ("svuid", ctypes.c_uint32),
                    ("svgid", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
                    ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
                    ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32),
                    ("pjobc", ctypes.c_uint32), ("tdev", ctypes.c_uint32),
                    ("tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
                    ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64),
                ]

            libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            libproc.proc_pidinfo.argtypes = [
                ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int,
            ]
            libproc.proc_pidinfo.restype = ctypes.c_int
            info = ProcBsdInfo()
            size = ctypes.sizeof(info)
            observed = libproc.proc_pidinfo(pid, 3, 0, ctypes.byref(info), size)
            if observed != size or info.pid != pid or info.start_sec == 0 or info.start_usec >= 1_000_000:
                return None
            return {
                "kind": "darwin-libproc-starttime-v1", "pid": pid,
                "start_sec": info.start_sec, "start_usec": info.start_usec,
            }
    except (OSError, UnicodeError, ValueError, IndexError, AttributeError):
        return None
    return None


def _current_process_owned(
    pid: int, owner_identity: Mapping[str, object], process: subprocess.Popen[bytes],
) -> bool:
    current = _process_owner_identity(pid)
    if current is not None:
        return current == owner_identity
    # Only this live controller can extend its observation after reaping the exact child.
    # A visible PID with unreadable identity may already belong to a different group.
    # Recovery has no Popen handle and cannot use this fallback.
    if process.poll() is None:
        return False
    try:
        os.getpgid(pid)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def _digest_without(value: Mapping[str, object], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return _sha(payload)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _safe_root(path: str | Path, code: str = "producer_process_workspace_invalid") -> Path:
    root = Path(path).expanduser().absolute()
    try:
        info = os.lstat(root)
    except OSError as exc:
        raise ProducerProcessError(code) from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        _fail(code)
    return root


@contextmanager
def _held_directory(path: Path, *, create: bool = False):
    """Hold each ancestor by descriptor while reading or publishing a child."""
    path = path.absolute()
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
                if not create:
                    _fail("producer_process_directory_missing")
                os.mkdir(part, 0o700, dir_fd=parent)
                info = os.stat(part, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                _fail("producer_process_directory_invalid")
            child = os.open(part, flags, dir_fd=parent)
            descriptors.append(child)
            links.append((parent, part, child))
            if (info.st_dev, info.st_ino) != (os.fstat(child).st_dev, os.fstat(child).st_ino):
                _fail("producer_process_directory_invalid")
        yield descriptors[-1]
        for parent, part, child in reversed(links):
            info = os.stat(part, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != (os.fstat(child).st_dev, os.fstat(child).st_ino):
                _fail("producer_process_directory_invalid")
    except ProducerProcessError:
        raise
    except OSError as exc:
        raise ProducerProcessError("producer_process_directory_invalid") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _safe_dir(path: Path, *, create: bool = False) -> Path:
    with _held_directory(path, create=create):
        pass
    return path


def _relative_path(root: Path, relative: str) -> Path:
    # The launch-intent parser already rejects traversal.  Recheck the resulting path at the
    # process boundary so this module does not depend on caller-created object invariants.
    candidate = root.joinpath(*Path(relative).parts)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ProducerProcessError("producer_process_path_invalid") from exc
    return candidate


def _file_identity(path: Path) -> dict[str, int | str]:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ProducerProcessError("producer_process_executable_invalid") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail("producer_process_executable_invalid")
    if info.st_size > MAX_OUTPUT_BYTES:
        _fail("producer_process_executable_invalid")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or (
                opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns
            ) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns):
                _fail("producer_process_executable_invalid")
            digest_state = hashlib.sha256()
            remaining = MAX_OUTPUT_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(_MAX_CAPTURE_CHUNK, remaining))
                if not chunk:
                    break
                digest_state.update(chunk)
                remaining -= len(chunk)
            finished = os.fstat(fd)
            if remaining == 0 or (
                finished.st_dev, finished.st_ino, finished.st_size,
                finished.st_mtime_ns, finished.st_ctime_ns
            ) != (
                opened.st_dev, opened.st_ino, opened.st_size,
                opened.st_mtime_ns, opened.st_ctime_ns
            ):
                _fail("producer_process_executable_invalid")
            digest = digest_state.hexdigest()
        finally:
            os.close(fd)
    except OSError as exc:
        raise ProducerProcessError("producer_process_executable_invalid") from exc
    return {
        "sha256": digest,
        "size": info.st_size,
        "device": info.st_dev,
        "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def _identity_digest(identity: Mapping[str, object]) -> str:
    return _sha(dict(identity))


@dataclass(frozen=True, slots=True)
class ProducerExecutableSnapshot:
    """The exact byte binding used for one producer spawn.

    Darwin uses a private immutable copy because its kernel has no supported
    ``fexecve``/``execveat`` interface. Linux binds the same attested bytes to a
    sealed memfd held through process creation. Other platforms retain the
    pathname prototype explicitly.
    """

    relative_path: str | None
    sha256: str
    size: int
    binding: str

    @property
    def path(self) -> Path | None:
        return None


def _snapshot_executable(
    executable: Path,
    batch: Path,
    expected_identity: Mapping[str, object],
    *,
    deadline: float,
    monotonic: Callable[[], float],
    role: str = "producer",
) -> ProducerExecutableSnapshot:
    """Bind executable bytes before ``Popen`` on Darwin.

    A descriptor is opened without following the final symlink, copied while
    its identity is held, then published under a private batch directory.  The
    published file is made user-immutable before it is passed to ``Popen``.
    Linux's descriptor-bound copy is held in ``run_producer_process`` through
    process creation. This function publishes only its expected receipt metadata.
    """

    relative_path = _SNAPSHOT_PATHS.get(role)
    if relative_path is None:
        _fail("producer_process_snapshot_role_invalid")
    if sys.platform.startswith("linux"):
        return ProducerExecutableSnapshot(
            relative_path=None,
            sha256=str(expected_identity["sha256"]),
            size=int(expected_identity["size"]),
            binding="linux-sealed-memfd",
        )
    if sys.platform != "darwin":
        return ProducerExecutableSnapshot(
            relative_path=None,
            sha256=str(expected_identity["sha256"]),
            size=int(expected_identity["size"]),
            binding="pathname_unbound",
        )
    if not hasattr(os, "chflags"):
        _fail("producer_process_execution_binding_unsupported")
    if monotonic() >= deadline:
        _fail("producer_process_wall_timeout")
    snapshot_dir = batch / ".producer-snapshots"
    _safe_dir(snapshot_dir, create=True)
    snapshot = batch / relative_path
    temp_name = ".executable-" + secrets.token_hex(12)
    temp_path = snapshot_dir / temp_name
    source_fd = -1
    target_fd = -1
    published = False
    try:
        source_fd = os.open(executable, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        source_info = os.fstat(source_fd)
        source_tuple = {
            "size": source_info.st_size,
            "device": source_info.st_dev,
            "inode": source_info.st_ino,
            "mtime_ns": source_info.st_mtime_ns,
            "ctime_ns": source_info.st_ctime_ns,
        }
        expected_tuple = {key: expected_identity[key] for key in source_tuple}
        if not stat.S_ISREG(source_info.st_mode) or source_info.st_nlink != 1 or source_tuple != expected_tuple:
            _fail("producer_process_executable_changed")
        target_fd = os.open(
            temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            stat.S_IMODE(source_info.st_mode),
        )
        digest_state = hashlib.sha256()
        total = 0
        while True:
            if monotonic() >= deadline:
                _fail("producer_process_wall_timeout")
            chunk = os.read(source_fd, _MAX_CAPTURE_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_OUTPUT_BYTES:
                _fail("producer_process_executable_invalid")
            digest_state.update(chunk)
            written = 0
            while written < len(chunk):
                count = os.write(target_fd, chunk[written:])
                if count <= 0:
                    raise OSError("short write")
                written += count
        source_after = os.fstat(source_fd)
        if (
            source_after.st_dev, source_after.st_ino, source_after.st_size,
            source_after.st_mtime_ns, source_after.st_ctime_ns,
        ) != (
            source_info.st_dev, source_info.st_ino, source_info.st_size,
            source_info.st_mtime_ns, source_info.st_ctime_ns,
        ) or total != source_info.st_size or digest_state.hexdigest() != str(expected_identity["sha256"]):
            _fail("producer_process_executable_changed")
        os.fsync(target_fd)
        os.close(target_fd)
        target_fd = -1
        # Publish without replacing an existing attempt's role path. The temp link
        # must be removed before identity checks, which require one hard link.
        with _held_directory(snapshot_dir) as directory_fd:
            try:
                os.link(
                    temp_name, snapshot.name,
                    src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                _fail("producer_process_execution_binding_unknown")
            published = True
            os.unlink(temp_name, dir_fd=directory_fd)
            os.fsync(directory_fd)
        staged = _file_identity(snapshot)
        if staged["sha256"] != expected_identity["sha256"] or staged["size"] != expected_identity["size"]:
            _fail("producer_process_execution_binding_unknown")
        try:
            os.chflags(snapshot, _UF_IMMUTABLE)
        except OSError as exc:
            raise ProducerProcessError("producer_process_execution_binding_unknown") from exc
        try:
            flags = os.stat(snapshot, follow_symlinks=False).st_flags
        except OSError as exc:
            raise ProducerProcessError("producer_process_execution_binding_unknown") from exc
        if not flags & _UF_IMMUTABLE:
            _fail("producer_process_execution_binding_unknown")
        locked = _file_identity(snapshot)
        if locked["sha256"] != expected_identity["sha256"] or locked["size"] != expected_identity["size"]:
            _fail("producer_process_execution_binding_unknown")
        with _held_directory(snapshot_dir) as directory_fd:
            os.fsync(directory_fd)
        return ProducerExecutableSnapshot(
            relative_path=relative_path,
            sha256=str(locked["sha256"]),
            size=int(locked["size"]),
            binding="darwin-immutable-snapshot",
        )
    except ProducerProcessError:
        raise
    except OSError as exc:
        raise ProducerProcessError("producer_process_execution_binding_unknown") from exc
    finally:
        for fd in (source_fd, target_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if not published:
            try:
                temp_path.unlink()
            except OSError:
                pass


def _remove_executable_snapshot(snapshot: ProducerExecutableSnapshot | None, batch: Path | None) -> None:
    if snapshot is None or snapshot.binding != "darwin-immutable-snapshot" or batch is None:
        return
    path = batch / (snapshot.relative_path or "")
    try:
        os.chflags(path, 0)
        path.unlink()
    except OSError:
        # The immutable file is retained as recovery evidence if cleanup is
        # uncertain; execution bytes remain bound by the receipt digest.
        return


def _atomic_json(path: Path, value: Mapping[str, object], *, exclusive: bool = False) -> None:
    data = _canonical(value)

    def write_all(fd: int) -> None:
        written = 0
        while written < len(data):
            count = os.write(fd, data[written:])
            if count <= 0:
                raise OSError("short write")
            written += count
    with _held_directory(path.parent, create=True) as parent:
        temporary = ".producer-receipt-" + secrets.token_hex(12)
        created = False
        try:
            fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=parent,
            )
            created = True
            try:
                write_all(fd)
                os.fsync(fd)
            finally:
                os.close(fd)
            if exclusive:
                os.link(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                os.unlink(temporary, dir_fd=parent)
            else:
                os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            created = False
            os.fsync(parent)
        except FileExistsError as exc:
            raise ProducerProcessError("producer_process_attestation_replayed") from exc
        except OSError as exc:
            raise ProducerProcessError("producer_process_receipt_write_unknown") from exc
        finally:
            if created:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except OSError:
                    pass


@contextmanager
def _recovery_lock(batch: Path):
    """Serialize explicit recovery cleanup while allowing stale locks to recover."""
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - supported local targets are POSIX.
        raise ProducerProcessError("producer_process_recovery_lock_unsupported") from exc
    with _held_directory(batch) as directory_fd:
        try:
            fd = os.open(
                ".recovery.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory_fd,
            )
            try:
                opened = os.fstat(fd)
                current = os.stat(".recovery.lock", dir_fd=directory_fd, follow_symlinks=False)
                if (
                    not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
                ):
                    _fail("producer_process_recovery_lock_unknown")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (BlockingIOError, OSError) as exc:
                    if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in {11, 35}:
                        raise ProducerProcessError("producer_process_recovery_busy") from exc
                    raise ProducerProcessError("producer_process_recovery_lock_unknown") from exc
                current = os.stat(".recovery.lock", dir_fd=directory_fd, follow_symlinks=False)
                if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                    _fail("producer_process_recovery_lock_unknown")
                yield (opened.st_dev, opened.st_ino)
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(fd)
        except ProducerProcessError:
            raise
        except OSError as exc:
            raise ProducerProcessError("producer_process_recovery_lock_unknown") from exc


def _current_recovery_lock_identity(batch: Path) -> tuple[int, int] | None:
    try:
        with _held_directory(batch) as directory_fd:
            current = os.stat(".recovery.lock", dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                return None
            return current.st_dev, current.st_ino
    except (OSError, ProducerProcessError):
        return None


@dataclass(frozen=True, slots=True)
class ProducerStreamEvidence:
    stream: str
    bytes_observed: int
    sha256: str
    truncated: bool
    capture_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "stream": self.stream,
            "bytes_observed": self.bytes_observed,
            "sha256": self.sha256,
            "truncated": self.truncated,
            "capture_status": self.capture_status,
        }


@dataclass(frozen=True, slots=True)
class ProducerEnvelopeEvidence:
    relative_path: str
    sha256: str
    bytes: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int
    identity_before: str
    identity_after: str
    read_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "device": self.device,
            "inode": self.inode,
            "mtime_ns": self.mtime_ns,
            "ctime_ns": self.ctime_ns,
            "identity_before": self.identity_before,
            "identity_after": self.identity_after,
            "read_status": self.read_status,
        }


@dataclass(frozen=True, slots=True)
class ProducerExecutionReceipt:
    launch_id: str
    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    intent_sha256: str
    attestation_sha256: str
    consumption_sha256: str
    registration_sha256: str
    executable_identity: str
    pid: int
    pgid: int
    owner_identity: Mapping[str, object]
    gate_released: bool
    request_timeout_seconds: int
    max_requests: int
    output_max_bytes: int
    wall_timeout_seconds: int
    request_count: int | None
    exit_code: int | None
    stdout_evidence: ProducerStreamEvidence
    stderr_evidence: ProducerStreamEvidence
    envelope_evidence: ProducerEnvelopeEvidence | None
    cleanup_status: str
    cleanup_sha256: str | None
    execution_binding: str
    execution_snapshot_relative_path: str | None
    execution_snapshot_sha256: str
    execution_snapshot_size: int
    status: str
    failure_code: str | None = None
    previous_receipt_sha256: str | None = None
    receipt_sha256: str | None = None
    schema_version: str = "1"
    protocol: str = _PROTOCOL
    trusted_execution: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "1" or self.protocol != _PROTOCOL:
            _fail("producer_process_receipt_schema_invalid")
        if self.execution_binding not in {"pathname_unbound", "darwin-immutable-snapshot", "linux-sealed-memfd"}:
            _fail("producer_process_receipt_execution_binding_invalid")
        if (
            not isinstance(self.execution_snapshot_sha256, str)
            or len(self.execution_snapshot_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.execution_snapshot_sha256)
            or isinstance(self.execution_snapshot_size, bool)
            or not isinstance(self.execution_snapshot_size, int)
            or self.execution_snapshot_size < 0
        ):
            _fail("producer_process_receipt_execution_snapshot_invalid")
        if self.execution_binding == "darwin-immutable-snapshot" and not self.execution_snapshot_relative_path:
            _fail("producer_process_receipt_execution_snapshot_invalid")
        if self.execution_binding in {"pathname_unbound", "linux-sealed-memfd"} and self.execution_snapshot_relative_path is not None:
            _fail("producer_process_receipt_execution_snapshot_invalid")
        if self.status not in {"completed", "failed", "cancelled", "unknown", "recovery_required"}:
            _fail("producer_process_receipt_status_invalid")
        if not isinstance(self.owner_identity, Mapping) or self.owner_identity.get("pid") != self.pid:
            _fail("producer_process_receipt_owner_identity_invalid")
        expected = self.digest()
        if self.receipt_sha256 is None:
            object.__setattr__(self, "receipt_sha256", expected)
        elif self.receipt_sha256 != expected:
            _fail("producer_process_receipt_digest_mismatch")

    def to_dict(self, *, include_receipt_sha256: bool = True) -> dict[str, object]:
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
            "consumption_sha256": self.consumption_sha256,
            "registration_sha256": self.registration_sha256,
            "executable_identity": self.executable_identity,
            "pid": self.pid,
            "pgid": self.pgid,
            "gate_released": self.gate_released,
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_requests": self.max_requests,
            "output_max_bytes": self.output_max_bytes,
            "wall_timeout_seconds": self.wall_timeout_seconds,
            "request_count": self.request_count,
            "exit_code": self.exit_code,
            "stdout_evidence": self.stdout_evidence.to_dict(),
            "stderr_evidence": self.stderr_evidence.to_dict(),
            "envelope_evidence": None if self.envelope_evidence is None else self.envelope_evidence.to_dict(),
            "cleanup_status": self.cleanup_status,
            "cleanup_sha256": self.cleanup_sha256,
            "execution_binding": self.execution_binding,
            "execution_snapshot_relative_path": self.execution_snapshot_relative_path,
            "execution_snapshot_sha256": self.execution_snapshot_sha256,
            "execution_snapshot_size": self.execution_snapshot_size,
            "status": self.status,
            "failure_code": self.failure_code,
            "previous_receipt_sha256": self.previous_receipt_sha256,
            "owner_identity": self.owner_identity,
        }
        if include_receipt_sha256:
            value["receipt_sha256"] = self.receipt_sha256
        if self.trusted_execution is not None:
            value["trusted_execution"] = dict(self.trusted_execution)
        return value

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "receipt_sha256")


def parse_producer_execution_receipt(value: object) -> ProducerExecutionReceipt:
    """Parse one complete, self-authenticating process receipt.

    Publication code must consume the formal Feature 156 DTO rather than trusting a
    handful of copied status fields.  The parser therefore rejects unknown or missing
    fields and rebuilds the nested evidence objects before the DTO verifies its own
    canonical digest.
    """
    if not isinstance(value, dict):
        _fail("producer_process_receipt_schema_invalid")
    keys = set(value)
    if keys - (_RECEIPT_FIELDS | _RECEIPT_OPTIONAL_FIELDS) or not _RECEIPT_FIELDS <= keys:
        _fail("producer_process_receipt_schema_invalid")

    def _nested(raw: object, expected: frozenset[str], code: str) -> dict[str, object]:
        if not isinstance(raw, dict) or set(raw) != expected:
            _fail(code)
        return raw

    stream_fields = frozenset({"stream", "bytes_observed", "sha256", "truncated", "capture_status"})
    stdout = _nested(value.get("stdout_evidence"), stream_fields, "producer_process_receipt_stream_invalid")
    stderr = _nested(value.get("stderr_evidence"), stream_fields, "producer_process_receipt_stream_invalid")
    envelope_value = value.get("envelope_evidence")
    envelope = None
    if envelope_value is not None:
        envelope_fields = frozenset({
            "relative_path", "sha256", "bytes", "device", "inode", "mtime_ns", "ctime_ns",
            "identity_before", "identity_after", "read_status",
        })
        envelope = _nested(envelope_value, envelope_fields, "producer_process_receipt_envelope_invalid")
    owner = value.get("owner_identity")
    if not isinstance(owner, dict):
        _fail("producer_process_receipt_owner_identity_invalid")
    trusted = value.get("trusted_execution")
    if trusted is not None and not isinstance(trusted, dict):
        _fail("producer_process_receipt_trusted_execution_invalid")
    try:
        return ProducerExecutionReceipt(
            **{
                **value,
                "stdout_evidence": ProducerStreamEvidence(**stdout),
                "stderr_evidence": ProducerStreamEvidence(**stderr),
                "envelope_evidence": None if envelope is None else ProducerEnvelopeEvidence(**envelope),
                "owner_identity": owner,
                "trusted_execution": trusted,
            }
        )
    except ProducerProcessError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise ProducerProcessError("producer_process_receipt_schema_invalid") from exc


def _stream_evidence(name: str, state: dict[str, object]) -> ProducerStreamEvidence:
    return ProducerStreamEvidence(
        stream=name,
        bytes_observed=int(state["bytes"]),
        sha256=state["hash"].hexdigest(),  # type: ignore[union-attr]
        truncated=bool(state["truncated"]),
        capture_status="limit_exceeded" if state["truncated"] else "complete",
    )


def _empty_stream_evidence(name: str) -> ProducerStreamEvidence:
    return ProducerStreamEvidence(
        stream=name, bytes_observed=0, sha256=hashlib.sha256(b"").hexdigest(),
        truncated=False, capture_status="complete",
    )


def _capture(
    process: subprocess.Popen[bytes],
    *,
    limit: int,
    deadline: float,
    monotonic: Callable[[], float],
    on_exited_leader: Callable[[], bool] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[ProducerStreamEvidence, ProducerStreamEvidence, bool, bool]:
    selector = selectors.DefaultSelector()
    states: dict[str, dict[str, object]] = {
        "stdout": {"bytes": 0, "hash": hashlib.sha256(), "truncated": False},
        "stderr": {"bytes": 0, "hash": hashlib.sha256(), "truncated": False},
    }
    for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        if stream is not None:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
    overflow = False
    timed_out = False
    exited_leader_handled = False
    try:
        while True:
            if cancel_check is not None and cancel_check():
                break
            leader_exited = process.poll() is not None
            if not selector.get_map() and leader_exited:
                break
            if leader_exited and selector.get_map() and not exited_leader_handled and on_exited_leader is not None:
                exited_leader_handled = True
                if not on_exited_leader():
                    break
            remaining = deadline - monotonic()
            if remaining <= 0:
                timed_out = True
                break
            events = selector.select(min(0.05, remaining))
            for key, _ in events:
                stream = key.fileobj
                name = key.data
                try:
                    chunk = os.read(stream.fileno(), _MAX_CAPTURE_CHUNK)
                except OSError:
                    _fail("producer_process_capture_unknown")
                if not chunk:
                    selector.unregister(stream)
                    continue
                state = states[name]
                prior_bytes = int(state["bytes"])
                retained = max(0, min(len(chunk), limit - prior_bytes))
                if retained:
                    state["hash"].update(chunk[:retained])  # type: ignore[union-attr]
                observed = prior_bytes + len(chunk)
                state["bytes"] = min(limit + 1, observed)
                if observed > limit:
                    state["truncated"] = True
                    overflow = True
            # Keep draining both descriptors after one stream crosses its limit. The
            # evidence is saturated at limit+1, while the other pipe must still be
            # observed to avoid a producer blocked on a full stderr/stdout pipe.
    finally:
        selector.close()
    return _stream_evidence("stdout", states["stdout"]), _stream_evidence("stderr", states["stderr"]), overflow, timed_out


def _read_envelope(
    path: Path, *, relative_path: str, limit: int, deadline: float,
    monotonic: Callable[[], float],
) -> tuple[ProducerEnvelopeEvidence, int]:
    try:
        with _held_directory(path.parent) as parent:
            if monotonic() >= deadline:
                _fail("producer_process_wall_timeout")
            before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                _fail("producer_process_envelope_invalid")
            if before.st_size > limit:
                _fail("producer_process_output_limit_exceeded")
            fd = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=parent,
            )
            try:
                info = os.fstat(fd)
                if (info.st_dev, info.st_ino, info.st_size) != (before.st_dev, before.st_ino, before.st_size):
                    _fail("producer_process_envelope_changed")
                data = bytearray()
                while len(data) <= limit:
                    if monotonic() >= deadline:
                        _fail("producer_process_wall_timeout")
                    chunk = os.read(fd, min(_MAX_CAPTURE_CHUNK, limit + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                after = os.fstat(fd)
            finally:
                os.close(fd)
            final_path = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if len(data) > limit or (
                final_path.st_dev, final_path.st_ino, final_path.st_size,
                final_path.st_mtime_ns, final_path.st_ctime_ns,
            ) != (
                before.st_dev, before.st_ino, before.st_size,
                before.st_mtime_ns, before.st_ctime_ns,
            ) or (after.st_dev, after.st_ino, after.st_size) != (before.st_dev, before.st_ino, before.st_size):
                _fail("producer_process_envelope_changed")
            if monotonic() >= deadline:
                _fail("producer_process_wall_timeout")
    except ProducerProcessError:
        raise
    except FileNotFoundError as exc:
        raise ProducerProcessError("producer_process_envelope_missing") from exc
    except OSError as exc:
        raise ProducerProcessError("producer_process_envelope_unknown") from exc
    identity = {
        "device": before.st_dev, "inode": before.st_ino, "size": before.st_size,
        "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns,
    }
    identity_after = {
        "device": after.st_dev, "inode": after.st_ino, "size": after.st_size,
        "mtime_ns": after.st_mtime_ns, "ctime_ns": after.st_ctime_ns,
    }
    before_digest = _identity_digest(identity)
    after_digest = _identity_digest(identity_after)
    if before_digest != after_digest:
        _fail("producer_process_envelope_changed")
    try:
        raw = json.loads(data, object_pairs_hook=_unique_object)
        budget = raw["budget"]
        requests = budget["requests"]
        if isinstance(requests, bool) or not isinstance(requests, int) or requests < 0:
            _fail("producer_process_request_count_invalid")
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProducerProcessError("producer_process_envelope_invalid") from exc
    evidence = ProducerEnvelopeEvidence(
        relative_path=relative_path, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
        device=before.st_dev, inode=before.st_ino, mtime_ns=before.st_mtime_ns, ctime_ns=before.st_ctime_ns,
        identity_before=before_digest, identity_after=after_digest, read_status="stable",
    )
    return evidence, requests


def _cleanup(
    registration: RegisteredProcess, process: subprocess.Popen[bytes], *,
    deadline: float, monotonic: Callable[[], float],
) -> ProcessCleanupResult:
    remaining = max(0.01, min(0.25, deadline - monotonic()))
    return cleanup_registered_process(
        registration, grace_seconds=remaining, monotonic=monotonic,
        deadline=deadline,
        allow_exited_leader_initial=process.poll() is not None,
    )


def _remaining_timeout(deadline: float, monotonic: Callable[[], float]) -> float:
    """Return a wait timeout that cannot extend the lifecycle deadline."""
    return max(0.0, deadline - monotonic())


def _observe_cancellation(cancelled: Callable[[], bool] | None) -> bool:
    """Observe caller cancellation without allowing a faulty callback to escape ambiguity."""
    if cancelled is None:
        return False
    try:
        value = cancelled()
    except Exception as exc:
        raise ProducerProcessError("producer_process_cancellation_unknown") from exc
    if not isinstance(value, bool):
        raise ProducerProcessError("producer_process_cancellation_invalid")
    return value


def _compose_parent_deadline(
    intent: ProducerLaunchIntent,
    monotonic: Callable[[], float],
    parent_deadline: float | None,
) -> float:
    """Compose an optional caller deadline in the same monotonic clock domain."""
    started = monotonic()
    if type(started) not in (int, float) or not math.isfinite(float(started)):
        _fail("producer_process_clock_invalid")
    own_deadline = float(started) + float(intent.wall_timeout_seconds)
    if parent_deadline is None:
        return own_deadline
    if type(parent_deadline) not in (int, float) or not math.isfinite(float(parent_deadline)):
        _fail("producer_process_parent_deadline_invalid")
    return min(own_deadline, float(parent_deadline))


def _run_producer_process(
    workspace: str | Path,
    *,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation | object,
    producer_root: str | Path,
    expected_run_id: str | None = None,
    expected_parent_task_id: str | None = None,
    expected_task_id: str | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] | None = None,
    parent_deadline: float | None = None,
    popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    recovery_lock_identity: tuple[int, int],
) -> ProducerExecutionReceipt:
    """Run one exact producer attempt and return a durable terminal receipt."""
    if not isinstance(intent, ProducerLaunchIntent):
        _fail("producer_process_intent_invalid")
    if cancelled is not None and not callable(cancelled):
        _fail("producer_process_cancellation_invalid")
    if _observe_cancellation(cancelled):
        _fail("producer_process_cancelled")
    deadline = _compose_parent_deadline(intent, monotonic, parent_deadline)
    try:
        verify_producer_launch_attestation(intent, attestation)
    except ProducerLaunchError as exc:
        raise ProducerProcessError("producer_process_attestation_mismatch") from exc
    if expected_run_id is not None and expected_run_id != intent.run_id:
        _fail("producer_process_identity_mismatch")
    if expected_parent_task_id is not None and expected_parent_task_id != intent.parent_task_id:
        _fail("producer_process_identity_mismatch")
    if expected_task_id is not None and expected_task_id != intent.task_id:
        _fail("producer_process_identity_mismatch")
    if not isinstance(attestation, ProducerLaunchAttestation):
        # verify_producer_launch_attestation parsed object internally; parse again at this boundary
        # so the consumed digest is explicit and stable.
        from .producer_launcher import parse_producer_launch_attestation
        attestation = parse_producer_launch_attestation(attestation)

    root = _safe_root(producer_root, "producer_process_producer_root_invalid")
    workspace_root = _safe_root(workspace)
    executable = _relative_path(root, intent.executable_relative)
    _safe_dir(executable.parent)
    identity = _file_identity(executable)
    expected_identity = {
        "sha256": intent.executable_sha256, "size": intent.executable_size,
        "device": intent.executable_device, "inode": intent.executable_inode,
        "mtime_ns": intent.executable_mtime_ns, "ctime_ns": intent.executable_ctime_ns,
    }
    if identity != expected_identity:
        _fail("producer_process_executable_changed")
    batch = workspace_root / "evolution" / "producer-batches" / intent.journal_id
    working = _relative_path(batch, intent.working_directory)
    output = _relative_path(batch, intent.output_directory)
    _safe_dir(working, create=True)
    _safe_dir(output, create=True)
    snapshot: ProducerExecutableSnapshot | None = None
    snapshot_path = executable

    attestation_digest = attestation.attestation_sha256 or attestation.digest()
    intent_digest = intent.intent_sha256 or intent.digest()
    claim_payload = {
        "schema_version": "1", "protocol": _PROTOCOL, "consumption_id": intent.launch_id,
        "launch_id": intent.launch_id, "journal_id": intent.journal_id, "run_id": intent.run_id,
        "parent_task_id": intent.parent_task_id, "task_id": intent.task_id,
        "intent_sha256": intent_digest, "attestation_sha256": attestation_digest,
        "nonce": attestation.nonce, "executable_identity": _identity_digest(identity),
    }
    claim_payload["consumption_sha256"] = _digest_without(claim_payload, "consumption_sha256")
    nonce_key = hashlib.sha256(attestation.nonce.encode("utf-8")).hexdigest()
    _atomic_json(
        workspace_root / "evolution" / "producer-nonces" / f"{nonce_key}.json",
        claim_payload, exclusive=True,
    )
    claim_path = batch / "attestation-consumption.json"
    _atomic_json(claim_path, claim_payload, exclusive=True)
    consumption_digest = str(claim_payload["consumption_sha256"])

    # Consume the attestation before the final byte-bound preparation. If snapshot creation
    # fails after the one-time claim, recovery sees the claim and can close the attempt without
    # allowing a second launch.
    snapshot = _snapshot_executable(
        executable,
        batch,
        expected_identity,
        deadline=deadline,
        monotonic=monotonic,
    )
    snapshot_path = executable if snapshot.relative_path is None else batch / snapshot.relative_path

    gate_read, gate_write = os.pipe()
    gate_released = False
    process: subprocess.Popen[bytes] | None = None
    registration_digest = ""
    registration: RegisteredProcess | None = None
    try:
        if _observe_cancellation(cancelled):
            _fail("producer_process_cancelled")
        if monotonic() >= deadline:
            _fail("producer_process_wall_timeout")
        env = {"PATH": os.defpath, "LANG": "C", GATE_ENV: str(gate_read)}
        try:
            verify_producer_launch_attestation(intent, attestation)
        except ProducerLaunchError as exc:
            raise ProducerProcessError("producer_process_attestation_mismatch") from exc
        linux_context = (
            sealed_linux_executable(executable, expected_identity, deadline=deadline, monotonic=monotonic)
            if sys.platform.startswith("linux") else nullcontext(None)
        )
        try:
            with linux_context as linux_binding:
                if _file_identity(executable) != expected_identity:
                    _fail("producer_process_executable_changed")
                if linux_binding is not None and (
                    linux_binding.sha256 != snapshot.sha256 or linux_binding.size != snapshot.size
                ):
                    _fail("producer_process_execution_binding_unknown")
                process = popen_factory(
                    list(intent.argv),
                    executable=linux_binding.executable if linux_binding is not None else str(snapshot_path),
                    shell=False, start_new_session=True,
                    close_fds=True,
                    pass_fds=(gate_read, linux_binding.pass_fd) if linux_binding is not None else (gate_read,),
                    cwd=str(working), env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
        except LinuxExecutableBindingError as exc:
            code = {
                "linux_execution_binding_unsupported": "producer_process_execution_binding_unsupported",
                "linux_execution_wall_timeout": "producer_process_wall_timeout",
                "linux_execution_source_invalid": "producer_process_executable_invalid",
                "linux_execution_source_changed": "producer_process_executable_changed",
            }.get(exc.code, "producer_process_execution_binding_unknown")
            raise ProducerProcessError(code) from exc
        os.close(gate_read)
        gate_read = -1
        try:
            pgid = os.getpgid(process.pid)
        except OSError as exc:
            raise ProducerProcessError("producer_process_registration_unknown") from exc
        if pgid != process.pid:
            raise ProducerProcessError("producer_process_registration_mismatch")
        owner_identity = _process_owner_identity(process.pid)
        if owner_identity is None:
            raise ProducerProcessError("producer_process_owner_identity_unknown")

        registration = RegisteredProcess(
            process.pid, pgid,
            owner_check=lambda: _current_process_owned(process.pid, owner_identity, process),
            label=intent.launch_id,
        )
        registration_payload = {
            "schema_version": "1", "protocol": _PROTOCOL, "launch_id": intent.launch_id,
            "journal_id": intent.journal_id, "run_id": intent.run_id, "parent_task_id": intent.parent_task_id,
            "task_id": intent.task_id, "intent_sha256": intent_digest,
            "attestation_sha256": attestation_digest, "consumption_sha256": consumption_digest,
            "executable_identity": _identity_digest(identity),
            "owner_identity": owner_identity,
            "owner_identity_sha256": _sha(owner_identity),
            "execution_binding": snapshot.binding,
            "execution_snapshot_relative_path": snapshot.relative_path,
            "execution_snapshot_sha256": snapshot.sha256,
            "execution_snapshot_size": snapshot.size,
            "pid": process.pid, "pgid": pgid,
            "recovery_lock_protocol": _RECOVERY_LOCK_PROTOCOL,
            "recovery_lock_device": recovery_lock_identity[0],
            "recovery_lock_inode": recovery_lock_identity[1],
            "gate_protocol": "fd-read-one-byte", "registered_at_unix_ns": time.time_ns(),
        }
        registration_payload["registration_sha256"] = _digest_without(registration_payload, "registration_sha256")
        _atomic_json(batch / "process-registration.json", registration_payload, exclusive=True)
        registration_digest = str(registration_payload["registration_sha256"])
        if _observe_cancellation(cancelled):
            cleanup_result = _cleanup(registration, process, deadline=deadline, monotonic=monotonic)
            verified = cleanup_result.status in {ProcessCleanupStatus.ALREADY_EXITED, ProcessCleanupStatus.CLEANED}
            return _persist_receipt(
                batch, intent, attestation, consumption_digest, registration_digest, identity, snapshot,
                process.pid, pgid, gate_released, _empty_stream_evidence("stdout"),
                _empty_stream_evidence("stderr"), None, cleanup_result,
                "cancelled" if verified else "unknown",
                None if verified else "producer_process_cleanup_unknown",
            )
        if monotonic() >= deadline:
            _fail("producer_process_wall_timeout")
        os.write(gate_write, b"1")
        gate_released = True
        os.close(gate_write)
        gate_write = -1
        exited_leader_cleanup: ProcessCleanupResult | None = None

        def cleanup_exited_leader() -> bool:
            nonlocal exited_leader_cleanup
            exited_leader_cleanup = _cleanup(registration, process, deadline=deadline, monotonic=monotonic)
            return exited_leader_cleanup.status in {
                ProcessCleanupStatus.ALREADY_EXITED, ProcessCleanupStatus.CLEANED,
            }

        cancellation_observed = False

        def observe_capture_cancellation() -> bool:
            nonlocal cancellation_observed
            cancellation_observed = _observe_cancellation(cancelled)
            return cancellation_observed

        stdout, stderr, overflow, timed_out = _capture(
            process, limit=intent.output_max_bytes, deadline=deadline, monotonic=monotonic,
            on_exited_leader=cleanup_exited_leader, cancel_check=observe_capture_cancellation,
        )
        if cancellation_observed:
            cleanup_result = exited_leader_cleanup or _cleanup(
                registration, process, deadline=deadline, monotonic=monotonic,
            )
            verified = cleanup_result.status in {ProcessCleanupStatus.ALREADY_EXITED, ProcessCleanupStatus.CLEANED}
            return _persist_receipt(
                batch, intent, attestation, consumption_digest, registration_digest, identity, snapshot,
                process.pid, pgid, gate_released, stdout, stderr, None, cleanup_result,
                "cancelled" if verified else "unknown",
                None if verified else "producer_process_cleanup_unknown",
            )
        if exited_leader_cleanup is not None and exited_leader_cleanup.status not in {
            ProcessCleanupStatus.ALREADY_EXITED, ProcessCleanupStatus.CLEANED,
        }:
            return _persist_receipt(
                batch, intent, attestation, consumption_digest, registration_digest, identity, snapshot, process.pid, pgid,
                gate_released, stdout, stderr, None, exited_leader_cleanup, "unknown", "producer_process_cleanup_unknown",
                process.returncode,
            )
        if timed_out or overflow:
            cleanup_result = exited_leader_cleanup or _cleanup(
                registration, process, deadline=deadline, monotonic=monotonic,
            )
            try:
                process.wait(timeout=_remaining_timeout(deadline, monotonic))
            except subprocess.TimeoutExpired:
                pass
            if cleanup_result.status not in {ProcessCleanupStatus.ALREADY_EXITED, ProcessCleanupStatus.CLEANED} and process.poll() is not None:
                cleanup_result = _cleanup(registration, process, deadline=deadline, monotonic=monotonic)
            verified = cleanup_result.status in {ProcessCleanupStatus.ALREADY_EXITED, ProcessCleanupStatus.CLEANED}
            status = "unknown" if timed_out or not verified else "failed"
            failure = (
                "producer_process_cleanup_unknown" if not verified else
                "producer_process_wall_timeout" if timed_out else "producer_process_output_limit_exceeded"
            )
            return _persist_receipt(
                batch, intent, attestation, consumption_digest, registration_digest, identity, snapshot, process.pid, pgid,
                gate_released, stdout, stderr, None, cleanup_result, status, failure,
            )
        while True:
            if _observe_cancellation(cancelled):
                cleanup_result = _cleanup(registration, process, deadline=deadline, monotonic=monotonic)
                verified = cleanup_result.status in {ProcessCleanupStatus.ALREADY_EXITED, ProcessCleanupStatus.CLEANED}
                return _persist_receipt(
                    batch, intent, attestation, consumption_digest, registration_digest, identity, snapshot,
                    process.pid, pgid, gate_released, stdout, stderr, None, cleanup_result,
                    "cancelled" if verified else "unknown",
                    None if verified else "producer_process_cleanup_unknown",
                )
            remaining = _remaining_timeout(deadline, monotonic)
            if remaining <= 0:
                cleanup_result = _cleanup(registration, process, deadline=deadline, monotonic=monotonic)
                return _persist_receipt(
                    batch, intent, attestation, consumption_digest, registration_digest, identity, snapshot,
                    process.pid, pgid, gate_released, stdout, stderr, None, cleanup_result,
                    "unknown", "producer_process_wall_timeout",
                )
            try:
                exit_code = process.wait(timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        cleanup_result = exited_leader_cleanup or _cleanup(
            registration, process, deadline=deadline, monotonic=monotonic,
        )
        if cleanup_result.status not in {ProcessCleanupStatus.ALREADY_EXITED, ProcessCleanupStatus.CLEANED}:
            return _persist_receipt(
                batch, intent, attestation, consumption_digest, registration_digest, identity, snapshot, process.pid, pgid,
                gate_released, stdout, stderr, None, cleanup_result, "unknown", "producer_process_cleanup_unknown", exit_code,
            )
        if exit_code != 0:
            return _persist_receipt(
                batch, intent, attestation, consumption_digest, registration_digest, identity, snapshot, process.pid, pgid,
                gate_released, stdout, stderr, None, cleanup_result, "failed", "producer_process_exit_failed", exit_code,
            )
        try:
            envelope, request_count = _read_envelope(
                output / "producer-result.json", relative_path=intent.envelope_path,
                limit=intent.output_max_bytes, deadline=deadline, monotonic=monotonic,
            )
        except ProducerProcessError as exc:
            return _persist_receipt(
                batch, intent, attestation, consumption_digest, registration_digest, identity, snapshot, process.pid, pgid,
                gate_released, stdout, stderr, None, cleanup_result,
                "unknown" if exc.code.endswith("_unknown") or exc.code == "producer_process_wall_timeout" else "failed",
                exc.code, exit_code,
            )
        status = "completed" if request_count <= intent.max_requests else "failed"
        failure = None if status == "completed" else "producer_process_request_limit_exceeded"
        return _persist_receipt(
            batch, intent, attestation, consumption_digest, registration_digest, identity, snapshot, process.pid, pgid,
            gate_released, stdout, stderr, envelope, cleanup_result, status, failure, exit_code, request_count,
        )
    except ProducerProcessError:
        if process is not None and registration is not None:
            _cleanup(registration, process, deadline=deadline, monotonic=monotonic)
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        if process is not None and registration is not None:
            _cleanup(registration, process, deadline=deadline, monotonic=monotonic)
        raise ProducerProcessError("producer_process_launch_unknown") from exc
    finally:
        for fd in (gate_read, gate_write):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if process is not None:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        # Keep an immutable snapshot when no terminal receipt was durably published. A
        # post-spawn exception must leave recovery evidence and must not remove the bytes a
        # still-running child may be executing.
        if snapshot is not None and (batch / "execution-receipt.json").is_file():
            try:
                terminal = _read_durable_json(
                    batch / "execution-receipt.json", code="producer_process_receipt_cleanup_unknown",
                )
            except ProducerProcessError:
                terminal = {}
            if terminal.get("status") in {"completed", "failed", "cancelled"}:
                _remove_executable_snapshot(snapshot, batch)


def run_producer_process(
    workspace: str | Path,
    *,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation | object,
    producer_root: str | Path,
    expected_run_id: str | None = None,
    expected_parent_task_id: str | None = None,
    expected_task_id: str | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] | None = None,
    parent_deadline: float | None = None,
    popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> ProducerExecutionReceipt:
    """Hold the per-journal ownership lock through the entire process attempt."""
    if not isinstance(intent, ProducerLaunchIntent):
        _fail("producer_process_intent_invalid")
    root = _safe_root(workspace)
    if not isinstance(intent.journal_id, str) or not intent.journal_id or "/" in intent.journal_id or ".." in intent.journal_id:
        _fail("producer_process_identity_mismatch")
    batch = root / "evolution" / "producer-batches" / intent.journal_id
    _safe_dir(batch, create=True)
    with _recovery_lock(batch) as lock_identity:
        return _run_producer_process(
            workspace, intent=intent, attestation=attestation, producer_root=producer_root,
            expected_run_id=expected_run_id, expected_parent_task_id=expected_parent_task_id,
            expected_task_id=expected_task_id, monotonic=monotonic, cancelled=cancelled,
            parent_deadline=parent_deadline,
            popen_factory=popen_factory, recovery_lock_identity=lock_identity,
        )


def _persist_receipt(
    batch: Path, intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    consumption_digest: str, registration_digest: str, identity: Mapping[str, object],
    snapshot: ProducerExecutableSnapshot, pid: int, pgid: int,
    gate_released: bool, stdout: ProducerStreamEvidence, stderr: ProducerStreamEvidence,
    envelope: ProducerEnvelopeEvidence | None, cleanup: ProcessCleanupResult, status: str,
    failure: str | None, exit_code: int | None = None, request_count: int | None = None,
) -> ProducerExecutionReceipt:
    persisted_registration = _read_durable_json(
        batch / "process-registration.json", code="producer_process_receipt_registration_unknown",
    )
    owner_identity = persisted_registration.get("owner_identity")
    if (
        not isinstance(owner_identity, dict)
        or owner_identity.get("pid") != pid
        or persisted_registration.get("owner_identity_sha256") != _sha(owner_identity)
        or persisted_registration.get("registration_sha256") != registration_digest
    ):
        _fail("producer_process_receipt_registration_unknown")
    cleanup_status = cleanup.status.value
    cleanup_digest = _sha({"status": cleanup_status, "pid": pid, "pgid": pgid, "term_sent": cleanup.term_sent, "kill_sent": cleanup.kill_sent, "alive_after": cleanup.alive_after})
    receipt = ProducerExecutionReceipt(
        launch_id=intent.launch_id, journal_id=intent.journal_id, run_id=intent.run_id,
        parent_task_id=intent.parent_task_id, task_id=intent.task_id,
        intent_sha256=intent.intent_sha256 or intent.digest(), attestation_sha256=attestation.attestation_sha256 or attestation.digest(),
        consumption_sha256=consumption_digest, registration_sha256=registration_digest,
        executable_identity=_identity_digest(identity), pid=pid, pgid=pgid, gate_released=gate_released,
        owner_identity=owner_identity,
        request_timeout_seconds=intent.request_timeout_seconds, max_requests=intent.max_requests,
        output_max_bytes=intent.output_max_bytes, wall_timeout_seconds=intent.wall_timeout_seconds,
        request_count=request_count, exit_code=exit_code, stdout_evidence=stdout, stderr_evidence=stderr,
        envelope_evidence=envelope, cleanup_status=cleanup_status, cleanup_sha256=cleanup_digest,
        execution_binding=snapshot.binding,
        execution_snapshot_relative_path=snapshot.relative_path,
        execution_snapshot_sha256=snapshot.sha256,
        execution_snapshot_size=snapshot.size,
        status=status, failure_code=failure, previous_receipt_sha256=registration_digest,
    )
    _atomic_json(batch / "execution-receipt.json", receipt.to_dict(), exclusive=True)
    return receipt


class ProducerProcessRunner:
    """Small provider-free facade for one producer lifecycle attempt."""

    def __init__(self, *, producer_root: str | Path | None = None) -> None:
        self.producer_root = None if producer_root is None else Path(producer_root)

    def run(
        self,
        workspace: str | Path,
        intent: ProducerLaunchIntent,
        attestation: ProducerLaunchAttestation | object,
        *,
        producer_root: str | Path | None = None,
        expected_run_id: str | None = None,
        expected_parent_task_id: str | None = None,
        expected_task_id: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        cancelled: Callable[[], bool] | None = None,
        parent_deadline: float | None = None,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    ) -> ProducerExecutionReceipt:
        workspace_path = Path(workspace)
        root = producer_root or self.producer_root or workspace_path / "producer-root"
        return run_producer_process(
            workspace_path,
            intent=intent,
            attestation=attestation,
            producer_root=root,
            expected_run_id=expected_run_id,
            expected_parent_task_id=expected_parent_task_id,
            expected_task_id=expected_task_id,
            monotonic=monotonic,
            cancelled=cancelled,
            parent_deadline=parent_deadline,
            popen_factory=popen_factory,
        )


def _read_durable_json(path: Path, *, code: str) -> dict[str, object]:
    try:
        with _held_directory(path.parent) as parent:
            before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > _MAX_RECEIPT_BYTES:
                _fail(code)
            fd = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=parent,
            )
            try:
                opened = os.fstat(fd)
                data = bytearray()
                while len(data) <= _MAX_RECEIPT_BYTES:
                    chunk = os.read(fd, min(_MAX_CAPTURE_CHUNK, _MAX_RECEIPT_BYTES + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                after = os.fstat(fd)
            finally:
                os.close(fd)
            current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            if len(data) > _MAX_RECEIPT_BYTES or identity(before) != identity(opened) or identity(before) != identity(after) or identity(before) != identity(current):
                _fail(code)
            raw = json.loads(data, object_pairs_hook=_unique_object)
    except ProducerProcessError as exc:
        raise ProducerProcessError(code) from exc
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProducerProcessError(code) from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        _fail(code)
    return raw


def _inspect_producer_process(
    workspace: str | Path, *, journal_id: str,
) -> dict[str, object]:
    """Inspect durable launch state without consuming another claim or restarting a producer."""
    root = _safe_root(workspace)
    if not isinstance(journal_id, str) or not journal_id or "/" in journal_id or ".." in journal_id:
        _fail("producer_process_recovery_identity_invalid")
    batch = root / "evolution" / "producer-batches" / journal_id
    path = batch / "execution-receipt.json"
    try:
        os.lstat(path)
    except FileNotFoundError:
        claim = _read_durable_json(batch / "attestation-consumption.json", code="producer_process_recovery_claim_invalid")
        if (claim.get("schema_version") != "1" or claim.get("protocol") != _PROTOCOL
                or claim.get("journal_id") != journal_id
                or claim.get("consumption_sha256") != _digest_without(claim, "consumption_sha256")):
            _fail("producer_process_recovery_claim_invalid")
        registration_path = batch / "process-registration.json"
        try:
            os.lstat(registration_path)
        except FileNotFoundError:
            return {"status": "recovery_required", "reason": "producer_process_registration_missing", "journal_id": journal_id, "launch_id": claim["launch_id"]}
        registration = _read_durable_json(registration_path, code="producer_process_recovery_registration_invalid")
        owner_identity = registration.get("owner_identity")
        pid = registration.get("pid")
        pgid = registration.get("pgid")
        if (
            registration.get("schema_version") != "1"
            or registration.get("protocol") != _PROTOCOL
            or registration.get("journal_id") != journal_id
            or registration.get("consumption_sha256") != claim["consumption_sha256"]
            or registration.get("registration_sha256") != _digest_without(registration, "registration_sha256")
            or any(registration.get(key) != claim.get(key) for key in (
                "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
                "intent_sha256", "attestation_sha256", "consumption_sha256", "executable_identity",
            ))
            or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1
            or isinstance(pgid, bool) or not isinstance(pgid, int) or pgid != pid
            or not isinstance(owner_identity, dict)
            or owner_identity.get("pid") != pid
            or registration.get("owner_identity_sha256") != _sha(owner_identity)
        ):
            _fail("producer_process_recovery_registration_invalid")
        recovered = _read_recovery_receipt(batch, registration)
        if recovered is not None:
            return recovered
        return {"status": "recovery_required", "reason": "producer_process_terminal_receipt_missing", "journal_id": journal_id, "launch_id": claim["launch_id"], "registration_sha256": registration["registration_sha256"], "pid": registration["pid"], "pgid": registration["pgid"]}
    except OSError as exc:
        raise ProducerProcessError("producer_process_recovery_receipt_invalid") from exc
    raw = _read_durable_json(path, code="producer_process_recovery_receipt_invalid")
    if raw.get("protocol") != _PROTOCOL or raw.get("journal_id") != journal_id or raw.get("receipt_sha256") != _digest_without(raw, "receipt_sha256"):
        _fail("producer_process_recovery_receipt_invalid")
    claim = _read_durable_json(batch / "attestation-consumption.json", code="producer_process_recovery_receipt_invalid")
    registration = _read_durable_json(batch / "process-registration.json", code="producer_process_recovery_receipt_invalid")
    owner_identity = registration.get("owner_identity")
    if (
        claim.get("schema_version") != "1" or claim.get("protocol") != _PROTOCOL
        or claim.get("journal_id") != journal_id
        or claim.get("consumption_sha256") != _digest_without(claim, "consumption_sha256")
        or registration.get("schema_version") != "1" or registration.get("protocol") != _PROTOCOL
        or registration.get("journal_id") != journal_id
        or any(registration.get(key) != claim.get(key) for key in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
            "intent_sha256", "attestation_sha256", "consumption_sha256", "executable_identity",
        ))
        or registration.get("registration_sha256") != _digest_without(registration, "registration_sha256")
        or not isinstance(owner_identity, dict)
        or owner_identity.get("pid") != registration.get("pid")
        or registration.get("owner_identity_sha256") != _sha(owner_identity)
        or raw.get("status") not in {"completed", "failed", "cancelled", "unknown", "recovery_required"}
        or any(raw.get(key) != claim.get(key) for key in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
            "intent_sha256", "attestation_sha256", "consumption_sha256", "executable_identity",
        ))
        or any(raw.get(key) != registration.get(key) for key in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
            "intent_sha256", "attestation_sha256", "consumption_sha256", "registration_sha256",
            "executable_identity", "execution_binding", "execution_snapshot_relative_path",
            "execution_snapshot_sha256", "execution_snapshot_size", "pid", "pgid", "owner_identity",
        ))
        or raw.get("previous_receipt_sha256") != registration.get("registration_sha256")
    ):
        _fail("producer_process_recovery_receipt_invalid")
    if raw.get("status") in {"unknown", "recovery_required"}:
        _fail("producer_process_recovery_required")
    return raw


def _read_recovery_receipt(batch: Path, registration: Mapping[str, object]) -> dict[str, object] | None:
    path = batch / "recovery-receipt.json"
    try:
        os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProducerProcessError("producer_process_recovery_receipt_invalid") from exc
    receipt = _read_durable_json(path, code="producer_process_recovery_receipt_invalid")
    if (
        receipt.get("schema_version") != "1"
        or receipt.get("protocol") != "lunar-producer-process-recovery-v1"
        or receipt.get("status") != "recovery_required"
        or receipt.get("execution_outcome") != "unknown"
        or receipt.get("reason") != "producer_process_terminal_receipt_missing"
        or receipt.get("recovery_sha256") != _digest_without(receipt, "recovery_sha256")
        or any(receipt.get(key) != registration.get(key) for key in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
            "intent_sha256", "attestation_sha256", "consumption_sha256",
            "registration_sha256", "pid", "pgid", "owner_identity_sha256",
        ))
        or receipt.get("previous_receipt_sha256") != registration.get("registration_sha256")
        or receipt.get("cleanup_status") not in {status.value for status in ProcessCleanupStatus}
        or not isinstance(receipt.get("term_sent"), bool)
        or not isinstance(receipt.get("kill_sent"), bool)
        or not isinstance(receipt.get("alive_after"), bool)
    ):
        _fail("producer_process_recovery_receipt_invalid")
    return receipt


def _cleanup_recovered_process(
    batch: Path, registration: Mapping[str, object], lock_identity: tuple[int, int],
) -> dict[str, object]:
    pid = registration.get("pid")
    pgid = registration.get("pgid")
    owner_identity = registration.get("owner_identity")
    if (
        isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1
        or isinstance(pgid, bool) or not isinstance(pgid, int) or pgid != pid
        or not isinstance(owner_identity, dict)
        or owner_identity.get("pid") != pid
        or registration.get("owner_identity_sha256") != _sha(owner_identity)
        or registration.get("recovery_lock_protocol") != _RECOVERY_LOCK_PROTOCOL
        or registration.get("recovery_lock_device") != lock_identity[0]
        or registration.get("recovery_lock_inode") != lock_identity[1]
    ):
        _fail("producer_process_recovery_registration_invalid")
    prior = _read_recovery_receipt(batch, registration)
    if prior is not None:
        _fail("producer_process_recovery_already_recorded")

    registration_path = batch / "process-registration.json"

    def owner_check() -> bool:
        try:
            current = _read_durable_json(
                registration_path, code="producer_process_recovery_registration_invalid",
            )
            return (
                current == registration
                and _current_recovery_lock_identity(batch) == lock_identity
                and _process_owner_identity(pid) == owner_identity
            )
        except ProducerProcessError:
            return False

    # Recovery has no Popen handle. A vanished leader cannot authorize signals to a
    # surviving group; only an OS-visible, exact start identity can grant that authority.
    result = cleanup_registered_process(
        RegisteredProcess(pid, pgid, owner_check=owner_check, label=str(registration["launch_id"])),
        grace_seconds=0.25,
    )
    receipt: dict[str, object] = {
        "schema_version": "1", "protocol": "lunar-producer-process-recovery-v1",
        "status": "recovery_required", "execution_outcome": "unknown",
        "reason": "producer_process_terminal_receipt_missing",
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
        _atomic_json(batch / "recovery-receipt.json", receipt, exclusive=True)
    except ProducerProcessError as exc:
        raise ProducerProcessError("producer_process_recovery_receipt_write_unknown") from exc
    return receipt


def recover_producer_process(
    workspace: str | Path, *, journal_id: str, cleanup: bool = False,
) -> dict[str, object]:
    """Inspect one attempt; explicit cleanup only addresses a missing terminal receipt."""
    if not isinstance(cleanup, bool):
        _fail("producer_process_recovery_cleanup_invalid")
    if not cleanup:
        return _inspect_producer_process(workspace, journal_id=journal_id)
    root = _safe_root(workspace)
    if not isinstance(journal_id, str) or not journal_id or "/" in journal_id or ".." in journal_id:
        _fail("producer_process_recovery_identity_invalid")
    batch = root / "evolution" / "producer-batches" / journal_id
    with _recovery_lock(batch) as lock_identity:
        observation = _inspect_producer_process(workspace, journal_id=journal_id)
        if observation.get("protocol") == "lunar-producer-process-recovery-v1":
            _fail("producer_process_recovery_already_recorded")
        if observation.get("reason") != "producer_process_terminal_receipt_missing":
            return observation
        registration = _read_durable_json(
            batch / "process-registration.json", code="producer_process_recovery_registration_invalid",
        )
        if registration.get("registration_sha256") != observation.get("registration_sha256"):
            _fail("producer_process_recovery_registration_invalid")
        claim = _read_durable_json(
            batch / "attestation-consumption.json", code="producer_process_recovery_claim_invalid",
        )
        nonce = claim.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            _fail("producer_process_recovery_claim_invalid")
        nonce_key = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        nonce_claim = _read_durable_json(
            root / "evolution" / "producer-nonces" / f"{nonce_key}.json",
            code="producer_process_recovery_claim_invalid",
        )
        if nonce_claim != claim or claim.get("consumption_sha256") != registration.get("consumption_sha256"):
            _fail("producer_process_recovery_claim_invalid")
        return _cleanup_recovered_process(batch, registration, lock_identity)


launch_producer_process = run_producer_process
execute_producer_process = run_producer_process


__all__ = [
    "GATE_ENV",
    "PRODUCER_PROCESS_PROTOCOL",
    "ProducerAttestationConsumption",
    "ProducerEnvelopeEvidence",
    "ProducerExecutionReceipt",
    "ProducerProcessError",
    "ProducerProcessRegistration",
    "ProducerProcessRunner",
    "ProducerStreamEvidence",
    "execute_producer_process",
    "launch_producer_process",
    "parse_producer_execution_receipt",
    "recover_producer_process",
    "run_producer_process",
]
