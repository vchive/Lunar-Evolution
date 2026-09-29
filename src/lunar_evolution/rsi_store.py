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
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .candidate_evaluation_spec import canonical_json
from .rsi_gateway import SolverRequest, SolverResult
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
WorkerState = Literal["running", "idle", "completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"]

RUN_STATES = frozenset({"created", "running", "paused", "completed", "failed", "cancelled", "unknown", "budget_exhausted"})
EPISODE_STATES = frozenset({
    "planned", "running", "completed", "failed", "timed_out", "abandoned", "cancelled", "unknown",
})
WORKER_STATES = frozenset({"running", "idle", "completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"})

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
    "unknown": frozenset({"unknown", "completed", "failed", "cancelled"}),
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
    if worker_state == "timed_out":
        return "timed_out"
    if worker_state == "abandoned":
        return "abandoned"
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
        self._controller_guards: dict[str, tuple[int, int, Path, str]] = {}
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
                "CREATE TABLE IF NOT EXISTS rsi_episode_results ("
                "episode_id TEXT NOT NULL PRIMARY KEY, request_sha256 TEXT NOT NULL, "
                "request_payload TEXT NOT NULL, result_payload TEXT NOT NULL, "
                "result_sha256 TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rsi_episode_reconciliations ("
                "episode_id TEXT NOT NULL, revision INTEGER NOT NULL, "
                "parent_record_sha256 TEXT NOT NULL, worker_state TEXT NOT NULL, "
                "evidence TEXT NOT NULL, result_sha256 TEXT, journal_sha256 TEXT NOT NULL UNIQUE, "
                "created_at TEXT NOT NULL, PRIMARY KEY(episode_id, revision))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS rsi_records_kind_idx ON rsi_records(kind, logical_id, revision)"
            )

    @contextmanager
    def controller_lock(self, run_id: str):
        """Acquire an exclusive, non-blocking controller lock for one run."""
        _id(run_id, name="run_id")
        lock_dir = self.database.parent / (self.database.name + ".controller-locks")
        lock_dir.mkdir(parents=True, exist_ok=True)
        try:
            if lock_dir.is_symlink() or not lock_dir.is_dir():
                raise RSILearningError("rsi_controller_lock_invalid")
            directory_fd = os.open(lock_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise RSILearningError("rsi_controller_lock_invalid") from exc
        name = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        descriptor: int | None = None
        try:
            descriptor = os.open(
                name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd
            )
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
            if (
                not stat.S_ISREG(named.st_mode)
                or held.st_nlink != 1
                or named.st_nlink != 1
                or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)
                or not stat.S_ISDIR(named_dir.st_mode)
                or (held_dir.st_dev, held_dir.st_ino) != (named_dir.st_dev, named_dir.st_ino)
            ):
                raise RSILearningError("rsi_controller_lock_identity_changed")
        except OSError as exc:
            raise RSILearningError("rsi_controller_lock_identity_changed") from exc

    @staticmethod
    def _checkpoint_digest(
        run_id: str, revision: int, parent_sha256: str | None, payload: Mapping[str, Any]
    ) -> str:
        return hashlib.sha256(canonical_json({
            "run_id": run_id,
            "revision": revision,
            "parent_sha256": parent_sha256,
            "payload": dict(payload),
        }, maximum=8 * 1024 * 1024)).hexdigest()

    def controller_checkpoint_history(self, run_id: str) -> list[tuple[str, dict[str, Any]]]:
        """Read and verify the append-only controller checkpoint hash chain."""
        _id(run_id, name="run_id")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT revision, parent_sha256, payload, checkpoint_sha256 "
                "FROM rsi_controller_journal WHERE run_id = ? ORDER BY revision", (run_id,)
            ).fetchall()
        parent: str | None = None
        history: list[tuple[str, dict[str, Any]]] = []
        for ordinal, row in enumerate(rows):
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RSILearningError("rsi_controller_checkpoint_corrupt") from exc
            if not isinstance(payload, dict):
                raise RSILearningError("rsi_controller_checkpoint_corrupt")
            digest = self._checkpoint_digest(run_id, ordinal, parent, payload)
            if row["revision"] != ordinal or row["parent_sha256"] != parent or row["checkpoint_sha256"] != digest:
                raise RSILearningError("rsi_controller_checkpoint_corrupt")
            parent = digest
            history.append((digest, payload))
        return history

    def controller_checkpoint(self, run_id: str) -> tuple[str, dict[str, Any]] | None:
        history = self.controller_checkpoint_history(run_id)
        return history[-1] if history else None

    def write_controller_checkpoint(
        self, run_id: str, state: Mapping[str, Any], *, expected_sha256: str | None
    ) -> str:
        """Append one controller checkpoint while holding the per-run process lock."""
        _id(run_id, name="run_id")
        self._assert_controller_lock(run_id)
        if not isinstance(state, Mapping):
            raise RSILearningError("rsi_controller_checkpoint_invalid")
        try:
            clean = json.loads(canonical_json(dict(state), maximum=8 * 1024 * 1024))
        except Exception as exc:
            raise RSILearningError("rsi_controller_checkpoint_invalid") from exc
        if not isinstance(clean, dict):
            raise RSILearningError("rsi_controller_checkpoint_invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision, checkpoint_sha256 FROM rsi_controller_journal "
                "WHERE run_id = ? ORDER BY revision DESC LIMIT 1", (run_id,)
            ).fetchone()
            parent = row["checkpoint_sha256"] if row else None
            if parent != expected_sha256:
                raise RSILearningError("rsi_controller_checkpoint_conflict")
            self._assert_controller_lock(run_id)
            revision = row["revision"] + 1 if row else 0
            digest = self._checkpoint_digest(run_id, revision, parent, clean)
            connection.execute(
                "INSERT INTO rsi_controller_journal VALUES (?, ?, ?, ?, ?)",
                (run_id, revision, parent, json.dumps(clean, sort_keys=True), digest),
            )
        return digest

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
            logical_id=record.logical_id,
            revision=record.revision,
            kind=record.kind,
            state=record.state,
            request_sha256=record.request_sha256,
            parent_record_sha256=record.parent_record_sha256,
            payload=record.payload,
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
        logical_id = f"memory:{snapshot.snapshot_id}"
        request_sha256 = snapshot.digest()
        payload = snapshot.to_dict()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._head(connection, logical_id)
            if existing is not None:
                if (
                    existing.kind != "memory"
                    or existing.request_sha256 != request_sha256
                    or existing.payload != payload
                ):
                    raise RSILearningError("rsi_memory_snapshot_conflict")
                return existing
            record_sha256 = self._record_digest(
                logical_id=logical_id, revision=0, kind="memory", state="approved",
                request_sha256=request_sha256, parent_record_sha256=None, payload=payload,
            )
            created_at = utc_now()
            connection.execute(
                "INSERT INTO rsi_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    logical_id, 0, "memory", "approved", request_sha256, None,
                    json.dumps(payload, sort_keys=True), record_sha256, created_at,
                ),
            )
            return RSIRecord(
                logical_id, 0, "memory", "approved", request_sha256, None,
                payload, record_sha256, created_at,
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

    def save_episode_result(self, request: SolverRequest, result: SolverResult) -> None:
        """Persist one immutable, request-bound solver result exactly once.

        Repeated writes with the same canonical bytes are idempotent. Any changed request or
        result for the same episode is rejected so reconcile cannot manufacture a terminal receipt.
        """
        if not isinstance(request, SolverRequest) or not isinstance(result, SolverResult):
            raise RSILearningError("rsi_episode_result_invalid")
        if result.episode_id != request.episode_id or result.request_sha256 != request.digest():
            raise RSILearningError("rsi_episode_result_request_mismatch")
        request_payload = request.to_dict()
        result_payload = result.to_dict()
        request_wire = canonical_json(request_payload, maximum=128 * 1024)
        result_wire = canonical_json(result_payload, maximum=128 * 1024)
        result_sha256 = hashlib.sha256(result_wire).hexdigest()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_sha256, request_payload, result_payload, result_sha256 "
                "FROM rsi_episode_results WHERE episode_id = ?", (request.episode_id,)
            ).fetchone()
            if row is not None:
                if (
                    row["request_sha256"] != request.digest()
                    or row["request_payload"] != request_wire.decode("utf-8")
                    or row["result_payload"] != result_wire.decode("utf-8")
                    or row["result_sha256"] != result_sha256
                ):
                    raise RSILearningError("rsi_episode_result_conflict")
                return
            connection.execute(
                "INSERT INTO rsi_episode_results VALUES (?, ?, ?, ?, ?, ?)",
                (
                    request.episode_id,
                    request.digest(),
                    request_wire.decode("utf-8"),
                    result_wire.decode("utf-8"),
                    result_sha256,
                    utc_now(),
                ),
            )

    def episode_result(self, episode_id: str) -> tuple[SolverRequest, SolverResult] | None:
        _id(episode_id, name="episode_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_payload, result_payload, result_sha256 FROM rsi_episode_results "
                "WHERE episode_id = ?", (episode_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            request = SolverRequest.from_dict(json.loads(row["request_payload"]))
            result = SolverResult.from_dict(json.loads(row["result_payload"]))
        except (TypeError, ValueError, RSILearningError) as exc:
            if isinstance(exc, RSILearningError):
                raise RSILearningError("rsi_episode_result_corrupt") from exc
            raise RSILearningError("rsi_episode_result_corrupt") from exc
        if result.episode_id != request.episode_id or result.request_sha256 != request.digest():
            raise RSILearningError("rsi_episode_result_corrupt")
        if hashlib.sha256(canonical_json(result.to_dict(), maximum=128 * 1024)).hexdigest() != row["result_sha256"]:
            raise RSILearningError("rsi_episode_result_corrupt")
        return request, result

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

    def _append_episode_record_tx(
        self,
        connection: sqlite3.Connection,
        episode: PracticeEpisode,
        *,
        expected_record_sha256: str | None = None,
        allow_unknown_completed: bool = False,
    ) -> RSIRecord:
        record = self._episode_payload(episode)
        head = self._head(connection, episode.episode_id)
        if head is None:
            raise RSILearningError("rsi_record_missing")
        self._check_episode_head(head, episode)
        if head.state == "unknown" and episode.status == "completed" and not allow_unknown_completed:
            raise RSILearningError("rsi_unknown_reconcile_required")
        expected = expected_record_sha256 or head.record_sha256
        _digest(expected, name="expected_record_sha256")
        if head.record_sha256 != expected:
            raise RSILearningError("rsi_record_parent_conflict")
        revision = head.revision + 1
        created_at = utc_now()
        record_sha256 = self._record_digest(
            logical_id=episode.episode_id, revision=revision, kind="episode",
            state=episode.status, request_sha256=episode.request_sha256,
            parent_record_sha256=head.record_sha256, payload=record,
        )
        connection.execute(
            "INSERT INTO rsi_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (episode.episode_id, revision, "episode", episode.status,
             episode.request_sha256, head.record_sha256, json.dumps(record, sort_keys=True),
             record_sha256, created_at),
        )
        return RSIRecord(
            episode.episode_id, revision, "episode", episode.status,
            episode.request_sha256, head.record_sha256, record, record_sha256, created_at,
        )

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
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._append_episode_record_tx(
                connection, episode, expected_record_sha256=expected_record_sha256,
            )

    def get(self, logical_id: str) -> RSIRecord | None:
        with self._connect() as connection:
            return self._head(connection, logical_id)

    def get_run(self, run_id: str) -> RSIRecord | None:
        record = self.get(run_id)
        if record is not None and record.kind != "run":
            raise RSILearningError("rsi_run_identity_conflict")
        return record

    def get_episode(self, episode_id: str) -> RSIRecord | None:
        record = self.get(episode_id)
        if record is not None and record.kind != "episode":
            raise RSILearningError("rsi_episode_identity_conflict")
        return record

    def get_transfer(self, run_id: str, target_id: str | None = None) -> RSIRecord | None:
        if target_id is None and run_id.startswith("transfer:"):
            logical_id = run_id
        else:
            _id(run_id, name="run_id")
            if target_id is None:
                raise RSILearningError("rsi_target_id_invalid")
            _id(target_id, name="target_id")
            logical_id = f"transfer:{run_id}:{target_id}"
        record = self.get(logical_id)
        if record is not None and record.kind != "transfer":
            raise RSILearningError("rsi_transfer_identity_conflict")
        return record

    def history(self, logical_id: str) -> tuple[RSIRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM rsi_records WHERE logical_id = ? ORDER BY revision", (logical_id,)
            ).fetchall()
        records = tuple(self._row_to_record(row) for row in rows)
        parent: str | None = None
        for ordinal, record in enumerate(records):
            if record.revision != ordinal or record.parent_record_sha256 != parent:
                raise RSILearningError("rsi_record_lineage_mismatch")
            parent = record.record_sha256
        return records

    def episode_ids_for_run(self, run_id: str) -> tuple[str, ...]:
        _id(run_id, name="run_id")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT logical_id FROM rsi_records "
                "WHERE kind = 'episode' ORDER BY logical_id"
            ).fetchall()
        result: list[str] = []
        for row in rows:
            record = self.get_episode(row["logical_id"])
            if record is not None and record.payload.get("run_id") == run_id:
                result.append(record.logical_id)
        return tuple(result)

    def episode_reconciliation(self, episode_id: str) -> tuple[dict[str, Any], ...]:
        """Read and verify the complete append-only reconciliation journal."""
        _id(episode_id, name="episode_id")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT revision, parent_record_sha256, worker_state, evidence, "
                "result_sha256, journal_sha256 FROM rsi_episode_reconciliations "
                "WHERE episode_id = ? ORDER BY revision", (episode_id,)
            ).fetchall()
        records = self.history(episode_id)
        record_digests = {record.record_sha256 for record in records}
        output: list[dict[str, Any]] = []
        for ordinal, row in enumerate(rows):
            try:
                evidence = json.loads(row["evidence"])
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RSILearningError("rsi_episode_reconciliation_corrupt") from exc
            if not isinstance(evidence, dict):
                raise RSILearningError("rsi_episode_reconciliation_corrupt")
            result_sha256 = row["result_sha256"]
            if result_sha256 is not None:
                result = self.episode_result(episode_id)
                if result is None:
                    raise RSILearningError("rsi_episode_reconciliation_result_missing")
                actual = hashlib.sha256(canonical_json(result[1].to_dict())).hexdigest()
                if actual != result_sha256:
                    raise RSILearningError("rsi_episode_reconciliation_result_mismatch")
            content = {
                "episode_id": episode_id,
                "revision": ordinal,
                "parent_record_sha256": row["parent_record_sha256"],
                "worker_state": row["worker_state"],
                "evidence": evidence,
                "result_sha256": result_sha256,
            }
            digest = hashlib.sha256(canonical_json(content)).hexdigest()
            if (
                row["revision"] != ordinal
                or row["parent_record_sha256"] not in record_digests
                or row["journal_sha256"] != digest
            ):
                raise RSILearningError("rsi_episode_reconciliation_corrupt")
            output.append(content | {"journal_sha256": digest})
        return tuple(output)

    @staticmethod
    def _is_canonical_episode(record: RSIRecord) -> bool:
        return record.kind == "episode" and record.payload.get("kind") == "rsi_episode"

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
            if self._is_canonical_episode(head):
                raise RSILearningError("rsi_episode_canonical_transition_required")
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
        current = self.get(episode_id)
        if current is None:
            raise RSILearningError("rsi_record_missing")
        if self._is_canonical_episode(current):
            raise RSILearningError("rsi_episode_canonical_reconcile_required")
        if current.state == "unknown" and state in {"completed", "failed", "cancelled"}:
            patch = payload_patch or {}
            if not isinstance(patch, Mapping) or not patch:
                raise RSILearningError("rsi_unknown_reconcile_evidence_required")
        return self.transition(
            episode_id,
            state=state,
            expected_record_sha256=expected_record_sha256,
            payload_patch=payload_patch,
        )

    def reconcile_episode(
        self,
        episode_id: str,
        *,
        worker_state: WorkerState,
        expected_record_sha256: str,
        launched: bool = True,
        result: SolverResult | None = None,
        evidence: Mapping[str, Any] | None = None,
        payload_patch: Mapping[str, Any] | None = None,
    ) -> RSIRecord:
        """Settle a canonical episode after an explicit evidence-bearing reconciliation.

        Generic payload patching is intentionally unavailable for canonical episodes.  This
        adapter loads the immutable episode, applies only the protocol transition, and appends
        the resulting canonical record with compare-and-swap lineage protection.
        """
        state = worker_to_episode_state(worker_state, launched=launched)
        current = self.get_episode(episode_id)
        if current is None:
            raise RSILearningError("rsi_record_missing")
        _digest(expected_record_sha256, name="expected_record_sha256")
        if current.record_sha256 != expected_record_sha256:
            raise RSILearningError("rsi_record_parent_conflict")
        try:
            episode = PracticeEpisode.from_dict(current.payload)
        except RSILearningError as exc:
            raise RSILearningError("rsi_episode_record_invalid") from exc
        if episode.status not in {"running", "unknown"}:
            raise RSILearningError("rsi_unknown_reconcile_required")
        supplied_evidence = evidence if evidence is not None else payload_patch
        supplied_evidence = supplied_evidence or {}
        if not isinstance(supplied_evidence, Mapping) or not supplied_evidence:
            raise RSILearningError("rsi_unknown_reconcile_evidence_required")
        reason = supplied_evidence.get("reconciliation")
        if not isinstance(reason, Mapping):
            raise RSILearningError("rsi_unknown_reconcile_evidence_required")
        if result is not None:
            if worker_state != "completed":
                raise RSILearningError("rsi_episode_result_state_mismatch")
            request_result = self.episode_result(episode_id)
            if request_result is None:
                raise RSILearningError("rsi_episode_result_missing")
            saved_request, saved_result = request_result
            if (
                saved_request.digest() != episode.request_sha256
                or saved_result.to_dict() != result.to_dict()
                or saved_result.status != "completed"
            ):
                raise RSILearningError("rsi_episode_result_conflict")
            if saved_request.episode_id != episode_id:
                raise RSILearningError("rsi_episode_result_request_mismatch")
            settled = replace(
                episode,
                status="completed",
                verifier=None,
                request_sha256=saved_request.digest(),
                candidate_receipt_sha256=saved_result.candidate_receipt_sha256,
                execution_receipt_sha256=saved_result.execution_receipt_sha256,
                official_evaluation_receipt_sha256=saved_result.official_evaluation_receipt_sha256,
                trace_digest=saved_result.trace_digest,
                candidate_source_sha256=saved_result.candidate_source_sha256,
                dependency_sha256=saved_result.dependency_sha256,
                trace_events=saved_result.trace_events,
                actor_fingerprint=saved_result.actor_fingerprint,
                terminal_reason=None,
                previous_record_sha256=episode.digest(),
            )
            settled._validate_durable_state()
        else:
            if worker_state == "completed":
                raise RSILearningError("rsi_episode_result_required")
            if worker_state == "unknown":
                if episode.status != "running":
                    raise RSILearningError("rsi_unknown_reconcile_state_invalid")
                settled = episode.transition(
                    "unknown",
                    terminal_reason="reconciled_worker_unknown",
                )
            else:
                if worker_state not in {"failed", "timed_out", "abandoned", "cancelled"}:
                    raise RSILearningError("rsi_unknown_reconcile_state_invalid")
                settled = episode.transition(
                    state,
                    terminal_reason=f"reconciled_worker_{worker_state}",
                )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            head = self._head(connection, episode_id)
            if head is None:
                raise RSILearningError("rsi_record_missing")
            if head.record_sha256 != expected_record_sha256:
                raise RSILearningError("rsi_record_parent_conflict")
            row = connection.execute(
                "SELECT COALESCE(MAX(revision), -1) AS revision FROM rsi_episode_reconciliations "
                "WHERE episode_id = ?", (episode_id,)
            ).fetchone()
            revision = int(row["revision"]) + 1
            result_sha256 = None
            if result is not None:
                result_sha256 = hashlib.sha256(canonical_json(result.to_dict())).hexdigest()
            journal_content = {
                "episode_id": episode_id,
                "revision": revision,
                "parent_record_sha256": expected_record_sha256,
                "worker_state": worker_state,
                "evidence": dict(supplied_evidence),
                "result_sha256": result_sha256,
            }
            journal_sha256 = hashlib.sha256(canonical_json(journal_content)).hexdigest()
            connection.execute(
                "INSERT INTO rsi_episode_reconciliations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    episode_id, revision, expected_record_sha256, worker_state,
                    json.dumps(dict(supplied_evidence), sort_keys=True), result_sha256,
                    journal_sha256, utc_now(),
                ),
            )
            return self._append_episode_record_tx(
                connection, settled, expected_record_sha256=expected_record_sha256,
                allow_unknown_completed=True,
            )


__all__ = [
    "EpisodeState",
    "RSILedger",
    "RSIRecord",
    "RunState",
    "WorkerState",
    "worker_to_episode_state",
]
