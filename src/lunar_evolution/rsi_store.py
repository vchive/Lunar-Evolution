"""Append-only SQLite ledger for RSI runs and episode recovery.

The existing :mod:`lunar_evolution.store` owns ordinary agent runs.  RSI needs a separate
immutable ledger because an episode pins a solver request, evidence manifest and memory snapshot;
rewriting an ordinary task row would lose those recovery identities.  This module keeps the first
durable implementation small and provider-free while using the same SQLite/WAL conventions.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import stat
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import (
    MemorySnapshot,
    PracticeEpisode,
    RSILearningError,
    TransferReceipt,
)

RunState = Literal["created", "running", "paused", "completed", "failed", "cancelled", "unknown", "budget_exhausted"]
EpisodeState = Literal[
    "planned", "running", "completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"
]
WorkerState = Literal["running", "idle", "completed", "failed", "cancelled", "unknown"]

RUN_STATES = frozenset({"created", "running", "paused", "completed", "failed", "cancelled", "unknown", "budget_exhausted"})
EPISODE_STATES = frozenset({
    "planned", "running", "completed", "failed", "timed_out", "abandoned", "cancelled", "unknown",
})
WORKER_STATES = frozenset({"running", "idle", "completed", "failed", "cancelled", "unknown"})

_RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"created", "running", "cancelled", "failed", "unknown", "budget_exhausted"}),
    "running": frozenset({"running", "paused", "completed", "failed", "cancelled", "unknown", "budget_exhausted"}),
    "paused": frozenset({"paused", "running", "cancelled", "failed", "unknown", "budget_exhausted"}),
    "unknown": frozenset({"unknown", "completed", "failed", "cancelled", "budget_exhausted"}),
    "completed": frozenset({"completed"}),
    "failed": frozenset({"failed"}),
    "cancelled": frozenset({"cancelled"}),
    "budget_exhausted": frozenset({"budget_exhausted"}),
}
_EPISODE_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"planned", "running", "cancelled", "abandoned", "unknown"}),
    "running": frozenset({"running", "completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"}),
    "unknown": frozenset({"unknown", "completed", "failed", "timed_out", "abandoned", "cancelled"}),
    "completed": frozenset({"completed"}),
    "failed": frozenset({"failed"}),
    "timed_out": frozenset({"timed_out"}),
    "abandoned": frozenset({"abandoned"}),
    "cancelled": frozenset({"cancelled"}),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(value: object, *, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RSILearningError(f"rsi_{name}_invalid")
    return value


def _id(value: object, *, name: str) -> str:
    if type(value) is not str or not value.strip() or any(char in value for char in "\x00\r\n"):
        raise RSILearningError(f"rsi_{name}_invalid")
    return value


def _payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RSILearningError("rsi_record_payload_invalid")
    try:
        encoded = canonical_json(dict(value), maximum=128 * 1024)
        parsed = json.loads(encoded)
    except Exception as exc:
        raise RSILearningError("rsi_record_payload_invalid") from exc
    if not isinstance(parsed, dict):
        raise RSILearningError("rsi_record_payload_invalid")
    return parsed


def worker_to_episode_state(worker_state: WorkerState, *, launched: bool = True) -> EpisodeState:
    """Map worker lifecycle to an episode state without silently retrying unknown work."""
    if worker_state not in WORKER_STATES:
        raise RSILearningError("rsi_worker_state_invalid")
    if worker_state == "idle":
        return "running" if launched else "planned"
    if worker_state == "running":
        return "running"
    if worker_state == "completed":
        return "completed"
    if worker_state == "failed":
        return "failed"
    if worker_state == "cancelled":
        return "cancelled"
    return "unknown"


@dataclass(frozen=True)
class RSIRecord:
    logical_id: str
    revision: int
    kind: Literal["run", "episode", "memory", "transfer"]
    state: str
    request_sha256: str
    parent_record_sha256: str | None
    payload: dict[str, Any]
    record_sha256: str
    created_at: str


_MEMORY_STATES = frozenset({"approved"})
_TRANSFER_STATES = frozenset({"passed", "failed", "unknown"})


class RSILedger:
    """Durable append-only run/episode state with compare-and-swap transitions."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).expanduser().resolve()
        self._controller_guards = {}
        self._controller_guards_lock = threading.RLock()
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS rsi_records (
                    logical_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    parent_record_sha256 TEXT,
                    payload TEXT NOT NULL,
                    record_sha256 TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(logical_id, revision)
                )"""
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rsi_controller_journal ("
                "run_id TEXT NOT NULL, revision INTEGER NOT NULL, parent_sha256 TEXT, "
                "payload TEXT NOT NULL, checkpoint_sha256 TEXT NOT NULL UNIQUE, "
                "PRIMARY KEY(run_id, revision))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS rsi_records_kind_idx ON rsi_records(kind, logical_id, revision)"
            )


    @contextmanager
    def controller_lock(self, run_id: str):
        """Serialize controller mutations across threads/processes; never steal live work."""
        _id(run_id, name="run_id")
        name = hashlib.sha256(run_id.encode()).hexdigest()
        lock_dir = self.database.parent / (self.database.name + ".controller-locks")
        lock_dir.mkdir(parents=True, exist_ok=True)
        if lock_dir.is_symlink() or not lock_dir.is_dir():
            raise RSILearningError("rsi_controller_lock_invalid")
        directory_fd = os.open(lock_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptor = None
        try:
            descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600,
                                 dir_fd=directory_fd)
            identity = os.fstat(descriptor)
            if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1:
                raise RSILearningError("rsi_controller_lock_invalid")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RSILearningError("rsi_controller_busy") from exc
            with self._controller_guards_lock:
                self._controller_guards[run_id] = (directory_fd, descriptor, lock_dir, name)
            try:
                self._assert_controller_lock(run_id)
                yield
            finally:
                with self._controller_guards_lock:
                    self._controller_guards.pop(run_id, None)
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError as exc:
            raise RSILearningError("rsi_controller_lock_invalid") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory_fd)

    def _assert_controller_lock(self, run_id: str) -> None:
        with self._controller_guards_lock:
            guard = self._controller_guards.get(run_id)
        if guard is None:
            raise RSILearningError("rsi_controller_lock_required")
        directory_fd, descriptor, lock_dir, name = guard
        try:
            held = os.fstat(descriptor)
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            held_dir = os.fstat(directory_fd)
            named_dir = os.stat(lock_dir, follow_symlinks=False)
            if (not stat.S_ISREG(named.st_mode) or held.st_nlink != 1 or named.st_nlink != 1
                    or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)
                    or not stat.S_ISDIR(named_dir.st_mode)
                    or (held_dir.st_dev, held_dir.st_ino) != (named_dir.st_dev, named_dir.st_ino)):
                raise RSILearningError("rsi_controller_lock_identity_changed")
        except OSError as exc:
            raise RSILearningError("rsi_controller_lock_identity_changed") from exc

    def controller_checkpoint(self, run_id: str) -> tuple[str, dict[str, Any]] | None:
        history = self.controller_checkpoint_history(run_id)
        return history[-1] if history else None

    def controller_checkpoint_history(self, run_id: str) -> list[tuple[str, dict[str, Any]]]:
        """Return every verified controller checkpoint in append order.

        The returned payloads are decoded copies from the hash chain; callers must treat them as
        read-only evidence. A missing run has an empty history. Legacy rows remain readable only
        when their existing chain validates; migration of legacy budget payloads is enforced by
        ``RSIRunBudget.load`` at recovery time.
        """
        _id(run_id, name="run_id")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT revision, parent_sha256, payload, checkpoint_sha256 "
                "FROM rsi_controller_journal WHERE run_id = ? ORDER BY revision", (run_id,),
            ).fetchall()
        parent = None
        history = []
        for ordinal, row in enumerate(rows):
            payload = json.loads(row["payload"])
            digest = hashlib.sha256(canonical_json({
                "run_id": run_id, "revision": ordinal, "parent_sha256": parent,
                "payload": payload,
            }, maximum=8 * 1024 * 1024)).hexdigest()
            if (row["revision"] != ordinal or row["parent_sha256"] != parent
                    or row["checkpoint_sha256"] != digest):
                raise RSILearningError("rsi_controller_checkpoint_corrupt")
            parent = digest
            history.append((digest, payload))
        return history

    def write_controller_checkpoint(
        self, run_id: str, payload: Mapping[str, Any], *, expected_sha256: str | None,
    ) -> str:
        self._assert_controller_lock(run_id)
        clean = json.loads(canonical_json(dict(payload), maximum=8 * 1024 * 1024))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision, checkpoint_sha256 FROM rsi_controller_journal "
                "WHERE run_id = ? ORDER BY revision DESC LIMIT 1", (run_id,),
            ).fetchone()
            parent = row["checkpoint_sha256"] if row else None
            if parent != expected_sha256:
                raise RSILearningError("rsi_controller_checkpoint_conflict")
            self._assert_controller_lock(run_id)
            revision = row["revision"] + 1 if row else 0
            digest = hashlib.sha256(canonical_json({
                "run_id": run_id, "revision": revision, "parent_sha256": parent,
                "payload": clean,
            }, maximum=8 * 1024 * 1024)).hexdigest()
            connection.execute("INSERT INTO rsi_controller_journal VALUES (?, ?, ?, ?, ?)",
                               (run_id, revision, parent, json.dumps(clean, sort_keys=True), digest))
        return digest

    def resume_reconciled_run(self, run_id: str, *, expected_record_sha256: str) -> RSIRecord:
        """Only a controller checkpoint with settled children may reopen an unknown run."""
        self._assert_controller_lock(run_id)
        checkpoint = self.controller_checkpoint(run_id)
        if checkpoint is None or not checkpoint[1].get("reconciliation_ready"):
            raise RSILearningError("rsi_controller_reconciliation_required")
        if any(
            entry.get("stage") != "planned" and (
                entry.get("result") is None or entry["result"].get("status") == "unknown"
            ) for entry in checkpoint[1].get("episodes", {}).values()
        ):
            raise RSILearningError("rsi_controller_reconciliation_required")
        head = self.get(run_id)
        if head is None or head.kind != "run" or head.state != "unknown":
            raise RSILearningError("rsi_controller_reconciliation_required")
        # Keep the generic transition matrix fail-closed for unknown -> running.
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._head(connection, run_id)
            if current.record_sha256 != expected_record_sha256:
                raise RSILearningError("rsi_record_parent_conflict")
            revision = current.revision + 1
            payload = {**current.payload, "reconciled_checkpoint_sha256": checkpoint[0]}
            digest = self._record_digest(
                logical_id=run_id, revision=revision, kind="run", state="running",
                request_sha256=current.request_sha256, parent_record_sha256=current.record_sha256,
                payload=payload,
            )
            connection.execute("INSERT INTO rsi_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (run_id, revision, "run", "running", current.request_sha256,
                                current.record_sha256, json.dumps(payload, sort_keys=True), digest, utc_now()))
        return self.get(run_id)

    @staticmethod
    def _record_digest(
        *, logical_id: str, revision: int, kind: str, state: str, request_sha256: str,
        parent_record_sha256: str | None, payload: Mapping[str, Any],
    ) -> str:
        import hashlib

        content = {
            "logical_id": logical_id,
            "revision": revision,
            "kind": kind,
            "state": state,
            "request_sha256": request_sha256,
            "parent_record_sha256": parent_record_sha256,
            "payload": dict(payload),
        }
        return hashlib.sha256(canonical_json(content, maximum=128 * 1024)).hexdigest()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> RSIRecord:
        record = RSIRecord(
            logical_id=row["logical_id"],
            revision=row["revision"],
            kind=row["kind"],
            state=row["state"],
            request_sha256=row["request_sha256"],
            parent_record_sha256=row["parent_record_sha256"],
            payload=json.loads(row["payload"]),
            record_sha256=row["record_sha256"],
            created_at=row["created_at"],
        )
        expected = RSILedger._record_digest(
            logical_id=record.logical_id, revision=record.revision, kind=record.kind,
            state=record.state, request_sha256=record.request_sha256,
            parent_record_sha256=record.parent_record_sha256, payload=record.payload,
        )
        if expected != record.record_sha256:
            raise RSILearningError("rsi_record_digest_mismatch")
        return record

    def _head(self, connection: sqlite3.Connection, logical_id: str) -> RSIRecord | None:
        row = connection.execute(
            "SELECT * FROM rsi_records WHERE logical_id = ? ORDER BY revision DESC LIMIT 1", (logical_id,)
        ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def _create(
        self, *, logical_id: str, kind: Literal["run", "episode", "memory", "transfer"], state: str,
        request_sha256: str, payload: Mapping[str, Any],
    ) -> RSIRecord:
        _id(logical_id, name="logical_id")
        _digest(request_sha256, name="request_sha256")
        states = {
            "run": RUN_STATES,
            "episode": EPISODE_STATES,
            "memory": _MEMORY_STATES,
            "transfer": _TRANSFER_STATES,
        }[kind]
        if state not in states:
            raise RSILearningError("rsi_state_invalid")
        clean_payload = _payload(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._head(connection, logical_id) is not None:
                raise RSILearningError("rsi_record_exists")
            created_at = utc_now()
            record_sha256 = self._record_digest(
                logical_id=logical_id, revision=0, kind=kind, state=state,
                request_sha256=request_sha256, parent_record_sha256=None, payload=clean_payload,
            )
            connection.execute(
                "INSERT INTO rsi_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (logical_id, 0, kind, state, request_sha256, None, json.dumps(clean_payload, sort_keys=True), record_sha256, created_at),
            )
            return RSIRecord(logical_id, 0, kind, state, request_sha256, None, clean_payload, record_sha256, created_at)

    def create_run(self, run_id: str, request_sha256: str, payload: Mapping[str, Any]) -> RSIRecord:
        return self._create(logical_id=run_id, kind="run", state="created", request_sha256=request_sha256, payload=payload)

    def create_episode(self, episode_id: str, request_sha256: str, payload: Mapping[str, Any]) -> RSIRecord:
        return self._create(logical_id=episode_id, kind="episode", state="planned", request_sha256=request_sha256, payload=payload)

    def create_memory_snapshot(self, snapshot: MemorySnapshot) -> RSIRecord:
        """Persist one approved snapshot as an immutable ledger record."""
        if not isinstance(snapshot, MemorySnapshot):
            raise RSILearningError("rsi_memory_snapshot_invalid")
        return self._create(
            logical_id=f"memory:{snapshot.snapshot_id}",
            kind="memory",
            state="approved",
            request_sha256=snapshot.digest(),
            payload=snapshot.to_dict(),
        )

    def create_transfer_receipt(self, receipt: TransferReceipt) -> RSIRecord:
        """Persist a frozen-memory transfer result without allowing later mutation."""
        if not isinstance(receipt, TransferReceipt):
            raise RSILearningError("rsi_transfer_receipt_invalid")
        return self._create(
            logical_id=f"transfer:{receipt.run_id}:{receipt.target_id}",
            kind="transfer",
            state=receipt.status,
            request_sha256=receipt.solver_fingerprint,
            payload=receipt.to_dict(),
        )

    @staticmethod
    def _episode_payload(episode: PracticeEpisode) -> dict[str, Any]:
        """Validate and return the exact canonical episode record for ledger storage."""
        if not isinstance(episode, PracticeEpisode):
            raise RSILearningError("rsi_episode_record_invalid")
        # The SQLite ledger's request identity is non-null, so this binding starts once a
        # planned episode has been launched and acquired its immutable request digest.
        if episode.request_sha256 is None:
            raise RSILearningError("rsi_episode_request_missing")
        record = episode.to_record_dict()
        if record.get("record_sha256") != episode.record_sha256:
            raise RSILearningError("rsi_episode_record_digest_mismatch")
        return record

    @staticmethod
    def _episode_identity(episode: PracticeEpisode) -> tuple[object, ...]:
        return (
            episode.episode_id,
            episode.run_id,
            episode.episode_kind,
            episode.contract_sha256,
            episode.evaluator_sha256,
            episode.environment_sha256,
            episode.memory_snapshot_sha256,
            episode.solver_id,
            episode.wave,
            episode.ordinal,
            episode.parent_target_episode_id,
        )

    @classmethod
    def _check_episode_head(cls, head: RSIRecord, episode: PracticeEpisode) -> None:
        if head.kind != "episode" or head.logical_id != episode.episode_id:
            raise RSILearningError("rsi_episode_identity_conflict")
        payload = head.payload
        if payload.get("record_sha256") != episode.previous_record_sha256:
            raise RSILearningError("rsi_episode_lineage_conflict")
        try:
            previous = PracticeEpisode.from_dict(payload)
        except RSILearningError as exc:
            raise RSILearningError("rsi_episode_record_invalid") from exc
        if cls._episode_identity(previous) != cls._episode_identity(episode):
            raise RSILearningError("rsi_episode_identity_drift")
        if head.request_sha256 != episode.request_sha256:
            raise RSILearningError("rsi_episode_request_drift")
        if episode.status not in _EPISODE_TRANSITIONS.get(head.state, frozenset()):
            raise RSILearningError("rsi_state_transition_invalid")

    def create_episode_record(self, episode: PracticeEpisode) -> RSIRecord:
        """Create an episode ledger head from one canonical PracticeEpisode record."""
        record = self._episode_payload(episode)
        return self._create(
            logical_id=episode.episode_id,
            kind="episode",
            state=episode.status,
            request_sha256=episode.request_sha256,
            payload=record,
        )

    def append_episode_record(
        self,
        episode: PracticeEpisode,
        *,
        expected_record_sha256: str | None = None,
    ) -> RSIRecord:
        """Append a canonical episode revision with identity and lineage checks."""
        record = self._episode_payload(episode)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            head = self._head(connection, episode.episode_id)
            if head is None:
                raise RSILearningError("rsi_record_missing")
            self._check_episode_head(head, episode)
            expected = expected_record_sha256 or head.record_sha256
            _digest(expected, name="expected_record_sha256")
            if head.record_sha256 != expected:
                raise RSILearningError("rsi_record_parent_conflict")
            revision = head.revision + 1
            created_at = utc_now()
            record_sha256 = self._record_digest(
                logical_id=episode.episode_id,
                revision=revision,
                kind="episode",
                state=episode.status,
                request_sha256=episode.request_sha256,
                parent_record_sha256=head.record_sha256,
                payload=record,
            )
            connection.execute(
                "INSERT INTO rsi_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    episode.episode_id,
                    revision,
                    "episode",
                    episode.status,
                    episode.request_sha256,
                    head.record_sha256,
                    json.dumps(record, sort_keys=True),
                    record_sha256,
                    created_at,
                ),
            )
            return RSIRecord(
                episode.episode_id,
                revision,
                "episode",
                episode.status,
                episode.request_sha256,
                head.record_sha256,
                record,
                record_sha256,
                created_at,
            )

    def get(self, logical_id: str) -> RSIRecord | None:
        with self._connect() as connection:
            return self._head(connection, logical_id)

    def history(self, logical_id: str) -> tuple[RSIRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM rsi_records WHERE logical_id = ? ORDER BY revision", (logical_id,)
            ).fetchall()
        records = tuple(self._row_to_record(row) for row in rows)
        parent = None
        for ordinal, record in enumerate(records):
            if record.revision != ordinal or record.parent_record_sha256 != parent:
                raise RSILearningError("rsi_record_lineage_mismatch")
            parent = record.record_sha256
        return records

    def episode_ids_for_run(self, run_id: str) -> tuple[str, ...]:
        """Return durable episode identities bound to one controller run."""
        if not isinstance(run_id, str) or not run_id:
            raise RSILearningError("rsi_run_id_invalid")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT logical_id, payload FROM rsi_records WHERE kind = 'episode' "
                "ORDER BY logical_id, revision",
            ).fetchall()
        result: set[str] = set()
        for logical_id, raw in rows:
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RSILearningError("rsi_episode_record_invalid") from exc
            if isinstance(payload, dict) and payload.get("run_id") == run_id:
                result.add(str(logical_id))
        return tuple(sorted(result))

    def transition(
        self, logical_id: str, *, state: str, expected_record_sha256: str,
        payload_patch: Mapping[str, Any] | None = None,
    ) -> RSIRecord:
        _digest(expected_record_sha256, name="expected_record_sha256")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            head = self._head(connection, logical_id)
            if head is None:
                raise RSILearningError("rsi_record_missing")
            allowed = _RUN_TRANSITIONS if head.kind == "run" else _EPISODE_TRANSITIONS
            if state not in allowed.get(head.state, frozenset()):
                raise RSILearningError("rsi_state_transition_invalid")
            if head.record_sha256 != expected_record_sha256:
                raise RSILearningError("rsi_record_parent_conflict")
            patch = _payload(payload_patch or {})
            merged = {**head.payload, **patch}
            revision = head.revision + 1
            created_at = utc_now()
            record_sha256 = self._record_digest(
                logical_id=logical_id, revision=revision, kind=head.kind, state=state,
                request_sha256=head.request_sha256, parent_record_sha256=head.record_sha256, payload=merged,
            )
            connection.execute(
                "INSERT INTO rsi_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (logical_id, revision, head.kind, state, head.request_sha256, head.record_sha256,
                 json.dumps(merged, sort_keys=True), record_sha256, created_at),
            )
            return RSIRecord(logical_id, revision, head.kind, state, head.request_sha256, head.record_sha256, merged, record_sha256, created_at)

    def reconcile_worker(
        self, episode_id: str, *, worker_state: WorkerState, expected_record_sha256: str,
        launched: bool = True, payload_patch: Mapping[str, Any] | None = None,
    ) -> RSIRecord:
        state = worker_to_episode_state(worker_state, launched=launched)
        return self.transition(
            episode_id,
            state=state,
            expected_record_sha256=expected_record_sha256,
            payload_patch=payload_patch,
        )


__all__ = [
    "EpisodeState",
    "RSILedger",
    "RSIRecord",
    "RunState",
    "WorkerState",
    "worker_to_episode_state",
]
