"""Durable, read-only cleanup evidence for native trusted producer attempts.

The native bootstrap currently keeps its process-only terminal separate from Feature 156's
formal execution receipt.  This sidecar records the exact owner-checked cleanup observation so
that a later receipt projection can require the same process, deadline, and cleanup bytes.  It
never authorizes a signal and it deliberately excludes arbitrary process error text.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from .producer_launcher import ProducerLaunchIntent
from .producer_process import (
    ProducerProcessError,
    _atomic_json,
    _digest_without,
    _read_durable_json,
)


class NativeTrustedCleanupError(ValueError):
    """Fixed-code cleanup evidence failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_PROTOCOL = "lunar-native-trusted-cleanup-v1"
_NAME = "native-trusted-cleanup.json"
_STATUSES = frozenset(status.value for status in ProcessCleanupStatus)
_FIELDS = frozenset(
    {
        "schema_version",
        "protocol",
        "launch_id",
        "journal_id",
        "run_id",
        "parent_task_id",
        "task_id",
        "intent_sha256",
        "registration_sha256",
        "deadline_sha256",
        "pid",
        "pgid",
        "cleanup_status",
        "term_sent",
        "kill_sent",
        "alive_after",
        "publication_eligible",
        "cleanup_sha256",
    }
)


def _batch(workspace: str | Path, intent: ProducerLaunchIntent) -> Path:
    return (
        Path(workspace).expanduser().absolute()
        / "evolution"
        / "producer-batches"
        / intent.journal_id
    )


def _check_digest(value: object, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise NativeTrustedCleanupError(code)
    return value


def _check_record(record: Mapping[str, object], intent: ProducerLaunchIntent) -> dict[str, object]:
    if set(record) != _FIELDS:
        raise NativeTrustedCleanupError("native_trusted_cleanup_invalid")
    if (
        record.get("schema_version") != "1"
        or record.get("protocol") != _PROTOCOL
        or record.get("publication_eligible") is not False
        or any(record.get(field) != getattr(intent, field) for field in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
        ))
    ):
        raise NativeTrustedCleanupError("native_trusted_cleanup_invalid")
    _check_digest(record.get("registration_sha256"), "native_trusted_cleanup_invalid")
    _check_digest(record.get("deadline_sha256"), "native_trusted_cleanup_invalid")
    pid = record.get("pid")
    pgid = record.get("pgid")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 1
        or isinstance(pgid, bool)
        or not isinstance(pgid, int)
        or pgid <= 1
        or pid != pgid
        or record.get("cleanup_status") not in _STATUSES
        or any(type(record.get(key)) is not bool for key in ("term_sent", "kill_sent", "alive_after"))
        or record.get("cleanup_sha256") != _digest_without(record, "cleanup_sha256")
    ):
        raise NativeTrustedCleanupError("native_trusted_cleanup_invalid")
    return dict(record)


def _record(
    intent: ProducerLaunchIntent,
    registration_sha256: str,
    deadline_sha256: str,
    cleanup: ProcessCleanupResult,
) -> dict[str, object]:
    if not isinstance(cleanup, ProcessCleanupResult):
        raise NativeTrustedCleanupError("native_trusted_cleanup_context_invalid")
    _check_digest(registration_sha256, "native_trusted_cleanup_context_invalid")
    _check_digest(deadline_sha256, "native_trusted_cleanup_context_invalid")
    if (
        isinstance(cleanup.pid, bool)
        or not isinstance(cleanup.pid, int)
        or cleanup.pid <= 1
        or isinstance(cleanup.pgid, bool)
        or not isinstance(cleanup.pgid, int)
        or cleanup.pgid <= 1
        or cleanup.pid != cleanup.pgid
        or cleanup.status.value not in _STATUSES
    ):
        raise NativeTrustedCleanupError("native_trusted_cleanup_context_invalid")
    result: dict[str, object] = {
        "schema_version": "1",
        "protocol": _PROTOCOL,
        "launch_id": intent.launch_id,
        "journal_id": intent.journal_id,
        "run_id": intent.run_id,
        "parent_task_id": intent.parent_task_id,
        "task_id": intent.task_id,
        "intent_sha256": intent.intent_sha256 or intent.digest(),
        "registration_sha256": registration_sha256,
        "deadline_sha256": deadline_sha256,
        "pid": cleanup.pid,
        "pgid": cleanup.pgid,
        "cleanup_status": cleanup.status.value,
        "term_sent": cleanup.term_sent,
        "kill_sent": cleanup.kill_sent,
        "alive_after": cleanup.alive_after,
        "publication_eligible": False,
    }
    result["cleanup_sha256"] = _digest_without(result, "cleanup_sha256")
    return result


def persist_native_trusted_cleanup(
    workspace: str | Path,
    *,
    intent: ProducerLaunchIntent,
    registration_sha256: str,
    deadline_sha256: str,
    cleanup: ProcessCleanupResult,
) -> dict[str, object]:
    """Persist one owner-checked cleanup result without replacing an existing record."""
    if not isinstance(intent, ProducerLaunchIntent):
        raise NativeTrustedCleanupError("native_trusted_cleanup_context_invalid")
    record = _record(intent, registration_sha256, deadline_sha256, cleanup)
    path = _batch(workspace, intent) / _NAME
    try:
        _atomic_json(path, record, exclusive=True)
        stored = _read_durable_json(path, code="native_trusted_cleanup_write_unknown")
    except ProducerProcessError as exc:
        raise NativeTrustedCleanupError("native_trusted_cleanup_write_unknown") from exc
    if stored != record:
        raise NativeTrustedCleanupError("native_trusted_cleanup_write_unknown")
    return record


def recover_native_trusted_cleanup(
    workspace: str | Path,
    *,
    intent: ProducerLaunchIntent,
    terminal: Mapping[str, object],
) -> dict[str, object]:
    """Recover cleanup evidence and require it to match the process-only terminal."""
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(terminal, Mapping):
        raise NativeTrustedCleanupError("native_trusted_cleanup_context_invalid")
    try:
        record = _read_durable_json(
            _batch(workspace, intent) / _NAME,
            code="native_trusted_cleanup_invalid",
        )
    except ProducerProcessError as exc:
        raise NativeTrustedCleanupError("native_trusted_cleanup_invalid") from exc
    record = _check_record(record, intent)
    for key in ("registration_sha256", "deadline_sha256", "pid", "pgid"):
        if record.get(key) != terminal.get(key):
            raise NativeTrustedCleanupError("native_trusted_cleanup_terminal_mismatch")
    if record.get("cleanup_status") != terminal.get("cleanup_status"):
        raise NativeTrustedCleanupError("native_trusted_cleanup_terminal_mismatch")
    if terminal.get("process_status") == "cancelled" and record.get("alive_after") is not False:
        raise NativeTrustedCleanupError("native_trusted_cleanup_terminal_mismatch")
    return record


__all__ = [
    "NativeTrustedCleanupError",
    "persist_native_trusted_cleanup",
    "recover_native_trusted_cleanup",
]
