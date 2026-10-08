"""Bind an attested Linux executable to sealed bytes before process creation."""

from __future__ import annotations

import errno
import hashlib
import math
import os
import stat
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .producer_launcher import MAX_OUTPUT_BYTES

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl module.
    fcntl = None

_CHUNK_SIZE = 64 * 1024
_REQUIRED_SEALS = ("F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")
_CLEANUP_NOTE = "linux_execution_cleanup_unknown"


class LinuxExecutableBindingError(ValueError):
    """Fixed-code failure before an executable is handed to the kernel."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LinuxSealedExecutable:
    fd: int
    sha256: str
    size: int
    binding: str = "linux-sealed-memfd"

    @property
    def executable(self) -> str:
        return f"/proc/self/fd/{self.fd}"

    @property
    def pass_fd(self) -> int:
        return self.fd


@dataclass(slots=True)
class _Owner:
    deadline: float
    monotonic: Callable[[], float]
    seals: int
    source: int = -1
    source_identity: tuple[int, int, int] | None = None
    anchor: int = -1
    borrowed: int = -1
    identity: tuple[int, int, int] | None = None
    sha256: str = ""
    size: int = 0
    mode: int = 0

    def checkpoint(self) -> None:
        if self.monotonic() >= self.deadline:
            raise LinuxExecutableBindingError("linux_execution_wall_timeout")


# Only a creating context adds an entry, retaining the exact public object and
# the private original owner. A same-value DTO or number cannot recover it.
_OWNERS: dict[int, tuple[LinuxSealedExecutable, _Owner]] = {}


def _identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _release(owner: _Owner, roles: tuple[str, ...]) -> tuple[bool, BaseException | None]:
    """Attempt every role once without using expired budgets or public fields."""
    uncertain = False
    first_error = None
    for role in roles:
        fd = getattr(owner, role)
        setattr(owner, role, -1)  # Never retry an unknown close by numeric FD.
        if fd < 0:
            continue
        original = owner.source_identity if role == "source" else owner.identity
        try:
            if original is not None and _identity(os.fstat(fd)) != original:
                uncertain = True
                continue  # Known foreign reuse is never closed.
            # A private acquisition can fail before its first identity capture.
            # It has never been exposed and its first release is supported only
            # by the trusted controller's no-private-rebind assumption. A late
            # fstat is deliberately not promoted to original identity.
            os.close(fd)
        except BaseException as exc:  # noqa: BLE001 - release all roles even after interrupts
            uncertain = True
            if first_error is None:
                first_error = exc
    return uncertain, first_error


def _cleanup(owner: _Owner, primary: BaseException | None) -> None:
    uncertain, first_error = _release(owner, ("borrowed", "source", "anchor"))
    if uncertain:
        if primary is not None:
            primary.add_note(_CLEANUP_NOTE)
        else:
            raise LinuxExecutableBindingError(_CLEANUP_NOTE) from first_error


def _owned_info(owner: _Owner, fd: int) -> os.stat_result:
    owner.checkpoint()
    try:
        info = os.fstat(fd)
    except OSError as exc:
        if exc.errno == errno.EBADF:
            raise LinuxExecutableBindingError("linux_execution_binding_invalid") from exc
        raise
    owner.checkpoint()
    if _identity(info) != owner.identity:
        raise LinuxExecutableBindingError("linux_execution_binding_invalid")
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 0
            or info.st_size != owner.size or stat.S_IMODE(info.st_mode) != owner.mode):
        raise LinuxExecutableBindingError("linux_execution_binding_unknown")
    owner.checkpoint()
    flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    owner.checkpoint()
    seals = fcntl.fcntl(fd, fcntl.F_GET_SEALS)
    owner.checkpoint()
    if (type(flags) is not int or not flags & fcntl.FD_CLOEXEC
            or type(seals) is not int or seals & owner.seals != owner.seals):
        raise LinuxExecutableBindingError("linux_execution_binding_unknown")
    return info


def _verify_image(owner: _Owner, fd: int) -> None:
    _owned_info(owner, fd)
    digest, copied = hashlib.sha256(), 0
    while copied < owner.size:
        wanted = min(_CHUNK_SIZE, owner.size - copied)
        owner.checkpoint()
        chunk = os.pread(fd, wanted, copied)
        owner.checkpoint()
        if type(chunk) is not bytes or not 0 < len(chunk) <= wanted:
            raise LinuxExecutableBindingError("linux_execution_binding_unknown")
        digest.update(chunk)
        owner.checkpoint()
        copied += len(chunk)
    if digest.hexdigest() != owner.sha256:
        raise LinuxExecutableBindingError("linux_execution_binding_unknown")
    _owned_info(owner, fd)


def _validate_original_linux_executable(binding: LinuxSealedExecutable) -> None:
    """Reobserve this exact context's original object with its original budget.

    This does not reread the mutable source or accept a new deadline. It cannot
    establish FD generations or atomically resist concurrent controller rebinding.
    """
    if type(binding) is not LinuxSealedExecutable:
        raise LinuxExecutableBindingError("linux_execution_binding_invalid")
    record = _OWNERS.get(id(binding))
    if record is None or record[0] is not binding:
        raise LinuxExecutableBindingError("linux_execution_binding_invalid")
    owner = record[1]
    if (type(binding.fd) is not int or type(binding.sha256) is not str
            or type(binding.size) is not int or type(binding.binding) is not str
            or binding.fd != owner.borrowed or binding.sha256 != owner.sha256
            or binding.size != owner.size or binding.binding != "linux-sealed-memfd"):
        raise LinuxExecutableBindingError("linux_execution_binding_invalid")
    try:
        _owned_info(owner, owner.anchor)
        _verify_image(owner, owner.borrowed)
        owner.checkpoint()
    except LinuxExecutableBindingError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise LinuxExecutableBindingError("linux_execution_binding_unknown") from exc


def _source_identity(info: os.stat_result, sha256: str) -> dict[str, int | str]:
    return {
        "sha256": sha256,
        "size": info.st_size,
        "device": info.st_dev,
        "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def _same_source(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns,
    ) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns,
    )


@contextmanager
def sealed_linux_executable(
    source: str | Path,
    expected_identity: Mapping[str, object],
    *,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> Iterator[LinuxSealedExecutable]:
    """Yield a sealed memfd that remains open through ``Popen``.

    The caller must pass ``binding.executable`` as ``Popen(executable=...)`` and include
    ``binding.pass_fd`` in ``pass_fds``. Keeping that descriptor across exec also lets
    a shebang interpreter reopen the exact sealed script through ``/proc/self/fd``.
    """
    if (type(deadline) not in (int, float) or (type(deadline) is float and math.isnan(deadline))
            or deadline == float("-inf") or not callable(monotonic)):
        raise LinuxExecutableBindingError("linux_execution_binding_invalid")
    required = tuple(getattr(fcntl, name, None) for name in _REQUIRED_SEALS)
    if (
        not sys.platform.startswith("linux")
        or not callable(getattr(os, "memfd_create", None))
        or not hasattr(os, "MFD_ALLOW_SEALING")
        or not hasattr(os, "MFD_CLOEXEC")
        or not hasattr(fcntl, "F_ADD_SEALS")
        or not hasattr(fcntl, "F_GET_SEALS")
        or not hasattr(fcntl, "F_DUPFD_CLOEXEC")
        or not hasattr(fcntl, "F_GETFD")
        or not hasattr(fcntl, "FD_CLOEXEC")
        or not callable(getattr(fcntl, "fcntl", None))
        or not callable(getattr(os, "pread", None))
        or any(type(value) is not int for value in required)
        or not Path("/proc/self/fd").is_dir()
    ):
        raise LinuxExecutableBindingError("linux_execution_binding_unsupported")
    owner = _Owner(deadline=deadline, monotonic=monotonic, seals=0)
    for value in required:
        owner.seals |= value
    live = None
    primary = None
    try:
        owner.checkpoint()
        # Retain the original caller pins once, before source observation. Later
        # mutation of the caller's Mapping cannot replace the admitted digest.
        pins = dict(expected_identity)
        owner.checkpoint()
        owner.source = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        owner.checkpoint()
        before = os.fstat(owner.source)
        owner.source_identity = _identity(before)
        owner.checkpoint()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_OUTPUT_BYTES
            or not before.st_mode & 0o111
            or before.st_mode & (stat.S_ISUID | stat.S_ISGID)
        ):
            raise LinuxExecutableBindingError("linux_execution_source_invalid")
        metadata = _source_identity(before, str(pins.get("sha256", "")))
        if metadata != pins:
            raise LinuxExecutableBindingError("linux_execution_source_changed")

        owner.checkpoint()
        owner.anchor = os.memfd_create(
            "lunar-producer-executable", os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC,
        )
        owner.checkpoint()
        owner.identity = _identity(os.fstat(owner.anchor))
        owner.checkpoint()
        owner.size, owner.mode = before.st_size, stat.S_IMODE(before.st_mode)
        os.fchmod(owner.anchor, owner.mode)
        owner.checkpoint()
        digest = hashlib.sha256()
        copied = 0
        while copied <= MAX_OUTPUT_BYTES:
            owner.checkpoint()
            wanted = min(_CHUNK_SIZE, before.st_size + 1 - copied)
            chunk = os.read(owner.source, wanted)
            owner.checkpoint()
            if type(chunk) is not bytes or len(chunk) > wanted:
                raise LinuxExecutableBindingError("linux_execution_binding_unknown")
            if not chunk:
                break
            copied += len(chunk)
            if copied > before.st_size or copied > MAX_OUTPUT_BYTES:
                raise LinuxExecutableBindingError("linux_execution_source_changed")
            digest.update(chunk)
            owner.checkpoint()
            offset = 0
            while offset < len(chunk):
                owner.checkpoint()
                written = os.write(owner.anchor, chunk[offset:])
                owner.checkpoint()
                if type(written) is not int or not 0 < written <= len(chunk) - offset:
                    raise LinuxExecutableBindingError("linux_execution_binding_unknown")
                offset += written
        owner.checkpoint()
        after = os.fstat(owner.source)
        owner.checkpoint()
        expected_digest = pins.get("sha256")
        if (
            copied != before.st_size
            or not _same_source(before, after)
            or digest.hexdigest() != expected_digest
        ):
            raise LinuxExecutableBindingError("linux_execution_source_changed")
        owner.sha256 = digest.hexdigest()
        source_uncertain, source_error = _release(owner, ("source",))
        if source_uncertain:
            if source_error is not None and not isinstance(source_error, Exception):
                source_error.add_note(_CLEANUP_NOTE)
                raise source_error
            raise LinuxExecutableBindingError(_CLEANUP_NOTE) from source_error
        owner.checkpoint()
        os.fsync(owner.anchor)
        owner.checkpoint()
        fcntl.fcntl(owner.anchor, fcntl.F_ADD_SEALS, owner.seals)
        owner.checkpoint()
        _verify_image(owner, owner.anchor)
        owner.checkpoint()
        os.lseek(owner.anchor, 0, os.SEEK_SET)
        owner.checkpoint()
        borrowed = fcntl.fcntl(owner.anchor, fcntl.F_DUPFD_CLOEXEC, 3)
        if type(borrowed) is not int or borrowed < 3 or borrowed == owner.anchor:
            # Do not treat a fabricated duplication result as new cleanup authority.
            raise LinuxExecutableBindingError("linux_execution_binding_unknown")
        owner.borrowed = borrowed
        owner.checkpoint()
        live = LinuxSealedExecutable(owner.borrowed, owner.sha256, owner.size)
        _OWNERS[id(live)] = live, owner
        _validate_original_linux_executable(live)
    except LinuxExecutableBindingError as exc:
        primary = exc
        raise
    except (OSError, ValueError, TypeError) as exc:
        primary = LinuxExecutableBindingError("linux_execution_binding_unknown")
        raise primary from exc
    except BaseException as exc:
        primary = exc
        raise
    else:
        try:
            yield live
        except BaseException as exc:
            primary = exc
            raise
    finally:
        if live is not None:
            _OWNERS.pop(id(live), None)
        _cleanup(owner, primary)
