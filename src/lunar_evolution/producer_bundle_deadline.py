"""Immutable boot-scoped monotonic deadlines for native producer transactions.

The controlled prepared-intent path uses one publication lock and writes the retained deadline
before the prepared journal. Interrupted writes remain evidence: neither corruption nor an older
prepared intent without a clock can start a new budget. No wall-clock value is used.
"""

from __future__ import annotations

import ctypes
import hashlib
import math
import os
import stat
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ._candidate_workspace_io import DirectoryChain
from .automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from .candidate_evaluation_spec import canonical_json, strict_json
from .producer_bundle_intent import (
    _INTENT_NAME,
    _intent_content,
    _started,
    _verify_existing,
)
from .producer_bundle_intent import (
    _write_exclusive as _write_intent,
)
from .producer_bundle_publication import ProducerBundlePublicationJournal
from .producer_bundle_staging import _batch, _locked, _present, _workspace

_PROTOCOL = "lunar-producer-bundle-deadline-v1"
_NAME = "execution.deadline.json"
_MAX_BYTES = 8192
_FIELDS = {
    "protocol", "journal_id", "journal_sha256", "timeout_seconds", "started_monotonic",
    "deadline_monotonic", "boot_id", "clock_kind", "clock_owner_pid", "file_identity", "self_sha256",
}


class ProducerBundleDeadlineError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ProducerBundleDeadlineError(f"producer_bundle_deadline_{code}")


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=_MAX_BYTES)
    except Exception as exc:
        raise ProducerBundleDeadlineError("producer_bundle_deadline_invalid") from exc


def _number(value: object, *, positive: bool = False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        _fail("time_invalid")
    return float(value)


def _boot_id() -> str:
    """Read an OS boot UUID directly; no process identity or wall-clock fallback."""
    try:
        if sys.platform.startswith("linux"):
            value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        elif sys.platform == "darwin":
            library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
            query = library.sysctlbyname
            query.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
            query.restype = ctypes.c_int
            buffer = ctypes.create_string_buffer(128)
            size = ctypes.c_size_t(len(buffer))
            if query(b"kern.bootsessionuuid", buffer, ctypes.byref(size), None, 0) != 0:
                _fail("boot_unavailable")
            if not 1 < size.value <= len(buffer):
                _fail("boot_unavailable")
            value = buffer.raw[:size.value].rstrip(b"\x00").decode("ascii")
        else:
            _fail("boot_unavailable")
        return str(uuid.UUID(value))
    except ProducerBundleDeadlineError:
        raise
    except (OSError, ValueError, UnicodeError, AttributeError) as exc:
        raise ProducerBundleDeadlineError("producer_bundle_deadline_boot_unavailable") from exc


def _validate_record(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != _FIELDS or value["protocol"] != _PROTOCOL:
        _fail("invalid")
    for name in ("journal_sha256", "self_sha256"):
        digest = value[name]
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            _fail("invalid")
    file_identity = value["file_identity"]
    if (type(file_identity) is not dict or set(file_identity) != {"device", "inode"}
            or type(file_identity["device"]) is not int or file_identity["device"] < 0
            or type(file_identity["inode"]) is not int or file_identity["inode"] < 1):
        _fail("invalid")
    identifier = value["journal_id"]
    if type(identifier) is not str or not identifier or any(c in identifier for c in "\x00/\\\r\n"):
        _fail("invalid")
    if value["clock_kind"] not in {"native_monotonic", "injected_process_clock"}:
        _fail("invalid")
    if value["clock_kind"] == "native_monotonic":
        if value["clock_owner_pid"] is not None:
            _fail("invalid")
    elif type(value["clock_owner_pid"]) is not int or value["clock_owner_pid"] < 1:
        _fail("invalid")
    try:
        if str(uuid.UUID(value["boot_id"])) != value["boot_id"]:
            _fail("invalid")
    except (TypeError, ValueError, AttributeError) as exc:
        raise ProducerBundleDeadlineError("producer_bundle_deadline_invalid") from exc
    started = _number(value["started_monotonic"])
    timeout = _number(value["timeout_seconds"], positive=True)
    deadline = _number(value["deadline_monotonic"], positive=True)
    if started + timeout != deadline or deadline <= started:
        _fail("invalid")
    body = {key: item for key, item in value.items() if key != "self_sha256"}
    if hashlib.sha256(_canonical(body)).hexdigest() != value["self_sha256"]:
        _fail("digest_mismatch")
    return value


def _parse(raw: bytes) -> dict[str, object]:
    try:
        value = strict_json(raw, maximum=_MAX_BYTES)
    except Exception as exc:
        raise ProducerBundleDeadlineError("producer_bundle_deadline_invalid") from exc
    value = _validate_record(value)
    if _canonical(value) != raw:
        _fail("noncanonical")
    return value


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode


def _read(chain: DirectoryChain) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    descriptor = None
    try:
        chain.check()
        descriptor = os.open(_NAME, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=chain.fd)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o600 or not 0 < before.st_size <= _MAX_BYTES):
            _fail("path_invalid")
        raw = bytearray()
        while len(raw) <= _MAX_BYTES:
            chunk = os.read(descriptor, _MAX_BYTES + 1 - len(raw))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        named = os.stat(_NAME, dir_fd=chain.fd, follow_symlinks=False)
        if (_identity(before) != _identity(after) or _identity(before) != _identity(named)
                or named.st_nlink != 1 or len(raw) != before.st_size):
            _fail("changed")
        value = _parse(bytes(raw))
        if value["file_identity"] != {"device": before.st_dev, "inode": before.st_ino}:
            _fail("changed")
        chain.check()
        return bytes(raw), _identity(before)
    except FileNotFoundError as exc:
        raise ProducerBundleDeadlineError("producer_bundle_deadline_missing") from exc
    except ProducerBundleDeadlineError:
        raise
    except Exception as exc:
        raise ProducerBundleDeadlineError("producer_bundle_deadline_path_invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_exclusive(chain: DirectoryChain, body: dict[str, object]) -> None:
    descriptor = None
    try:
        chain.check()
        descriptor = os.open(_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=chain.fd)
        opened = os.fstat(descriptor)
        body = {**body, "file_identity": {"device": opened.st_dev, "inode": opened.st_ino}}
        body["self_sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
        raw = _canonical(_validate_record(body))
        remaining = memoryview(raw)
        while remaining:
            count = os.write(descriptor, remaining)
            if count <= 0:
                _fail("write_failed")
            remaining = remaining[count:]
        os.fsync(descriptor)
        retained, info = _read(chain)
        if retained != raw or info[:2] != (opened.st_dev, opened.st_ino):
            _fail("changed")
        os.fsync(chain.fd)
    except ProducerBundleDeadlineError:
        raise
    except Exception as exc:
        # Never remove a failed write: a partial clock is retained recovery evidence.
        raise ProducerBundleDeadlineError("producer_bundle_deadline_write_failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


@dataclass(frozen=True)
class ProducerBundleDeadline:
    workspace: Path
    journal_id: str
    journal_sha256: str
    raw: bytes
    identity: tuple[int, int, int, int, int, int]
    clock: Callable[[], float]

    def check(self, stage: str) -> float:
        """Reopen retained bytes at every boundary and require the original boot/deadline."""
        chain = None
        try:
            root = _workspace(self.workspace)
            chain = DirectoryChain(_batch(root, self.journal_id), "producer_bundle_deadline_path_invalid")
            raw, identity = _read(chain)
            if raw != self.raw or identity != self.identity:
                _fail("changed")
            value = _parse(raw)
            if value["journal_id"] != self.journal_id or value["journal_sha256"] != self.journal_sha256:
                _fail("journal_mismatch")
            if value["boot_id"] != _boot_id():
                _fail("boot_changed")
            if value["clock_kind"] == "injected_process_clock" and value["clock_owner_pid"] != os.getpid():
                _fail("clock_unrestorable")
            now = _number(self.clock())
            started, deadline = float(value["started_monotonic"]), float(value["deadline_monotonic"])
            if now < started:
                _fail("clock_rollback")
            if now >= deadline:
                raise SolveExecutionBudgetExceeded(stage, started_at=started, deadline=deadline, observed_at=now)
            return deadline - now
        except (ProducerBundleDeadlineError, SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            raise
        except Exception as exc:
            raise ProducerBundleDeadlineError("producer_bundle_deadline_path_invalid") from exc
        finally:
            if chain is not None:
                chain.close()


def persist_controlled_producer_bundle_intent(
    workspace: str | Path,
    journal: ProducerBundlePublicationJournal,
    control: SolveExecutionControl,
    *,
    checkpoint: Callable[[str], object],
) -> ProducerBundleDeadline:
    """Create both records under one publication lock, or reuse the retained exact intent.

    A deadline-only interrupted preparation is reusable. A prepared intent without a deadline,
    or any later evidence without both records, is rejected rather than allocated fresh budget.
    """
    if not isinstance(control, SolveExecutionControl) or not callable(checkpoint):
        _fail("control_invalid")
    intent, journal_digest = _intent_content(journal)
    chain = None
    try:
        root = _workspace(workspace)
        batch = _batch(root, journal.journal_id)
        chain = DirectoryChain(batch, "producer_bundle_deadline_path_invalid")

        def guarded_checkpoint(stage: str) -> None:
            checkpoint(stage)
            # A restarted caller's fresh allowance cannot prolong lock acquisition after the
            # retained clock has expired. A concurrent exclusive writer may expose incomplete
            # bytes here; failing closed is safer than treating those bytes as a new attempt.
            if _present(batch / _NAME):
                raw, identity = _read(chain)
                ProducerBundleDeadline(
                    root, journal.journal_id, journal_digest, raw, identity, control._clock,
                ).check(stage)

        with _locked(root, checkpoint=guarded_checkpoint):
            chain.check()
            checkpoint("producer_deadline_locked")
            control.check("producer_deadline_locked")
            path = batch / _NAME
            intent_present = _present(batch / _INTENT_NAME)
            if intent_present:
                _verify_existing(batch / _INTENT_NAME, intent)
            if not _present(path):
                if intent_present or _started(batch) or _present(root / "evolution" / "producer-publication.json"):
                    _fail("recovery_required")
                body = {
                    "protocol": _PROTOCOL, "journal_id": journal.journal_id,
                    "journal_sha256": journal_digest, "timeout_seconds": control.timeout_seconds,
                    "started_monotonic": control.started_at, "deadline_monotonic": control.deadline,
                    "boot_id": _boot_id(),
                    "clock_kind": "native_monotonic" if control._clock is time.monotonic else "injected_process_clock",
                    "clock_owner_pid": None if control._clock is time.monotonic else os.getpid(),
                }
                _write_exclusive(chain, body)
            raw, identity = _read(chain)
            value = _parse(raw)
            if value["timeout_seconds"] != control.timeout_seconds:
                _fail("allowance_mismatch")
            if (value["clock_kind"] == "native_monotonic") != (control._clock is time.monotonic):
                _fail("clock_mismatch")
            retained = ProducerBundleDeadline(root, journal.journal_id, journal_digest, raw, identity, control._clock)
            retained.check("producer_deadline_locked")
            if not intent_present:
                if _started(batch) or _present(root / "evolution" / "producer-publication.json"):
                    _fail("recovery_required")
                checkpoint("producer_prepared_intent_locked")
                retained.check("producer_prepared_intent_locked")
                _write_intent(chain, intent)
            _verify_existing(batch / _INTENT_NAME, intent)
            chain.check()
            return retained
    finally:
        if chain is not None:
            chain.close()


def restore_producer_bundle_execution_control(
    workspace: str | Path,
    journal: ProducerBundlePublicationJournal,
) -> SolveExecutionControl:
    """Restore a same-boot native clock with its original allowance and absolute deadline.

    Cancellation authority is process-local and must be supplied by the current caller/parent.
    This helper never reconciles unknown producer work or bypasses the transaction's intent check.
    """
    chain = None
    try:
        root = _workspace(workspace)
        batch = _batch(root, journal.journal_id)
        chain = DirectoryChain(batch, "producer_bundle_deadline_path_invalid")
        raw, identity = _read(chain)
        value = _parse(raw)
        if value["clock_kind"] != "native_monotonic":
            _fail("clock_unrestorable")
        retained = ProducerBundleDeadline(root, journal.journal_id, journal.digest(), raw, identity, time.monotonic)
        retained.check("producer_deadline_restore")
        return SolveExecutionControl(float(value["timeout_seconds"]), started_at=float(value["started_monotonic"]))
    finally:
        if chain is not None:
            chain.close()


__all__ = [
    "ProducerBundleDeadline", "ProducerBundleDeadlineError",
    "persist_controlled_producer_bundle_intent", "restore_producer_bundle_execution_control",
]
