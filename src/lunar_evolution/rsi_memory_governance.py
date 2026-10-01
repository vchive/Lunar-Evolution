"""Durable, verifier-gated governance for RSI memory admissions.

The RSI memory store intentionally remains a small immutable snapshot store.  This module is a
separate control plane for deciding whether one snapshot/item may be used by a future request.
It records an append-only admission history in SQLite and never mutates ``RSIMemoryStore``.

An admission progresses through explicit gates::

    observed -> verified -> candidate -> shadow -> approved -> active
    -> deprecated -> revoked

``revoke`` is a fail-closed safety operation and may be applied to any non-revoked admission.  A
successful practice episode can create a candidate, but cannot skip holdout/baseline gates or
become active directly.  Every write uses a compare-and-swap on the current record digest.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import RSILearningError

GovernanceState = Literal[
    "observed", "verified", "candidate", "shadow", "approved", "active", "deprecated", "revoked"
]
EpisodeOutcome = Literal["pass", "fail", "unknown"]

_STATES = frozenset({"observed", "verified", "candidate", "shadow", "approved", "active", "deprecated", "revoked"})
_PROMOTION_EDGES: dict[str, frozenset[str]] = {
    "observed": frozenset({"verified"}),
    "verified": frozenset({"candidate"}),
    "candidate": frozenset({"shadow"}),
    "shadow": frozenset({"approved"}),
    "approved": frozenset({"active"}),
    "active": frozenset({"deprecated"}),
    "deprecated": frozenset(),
    "revoked": frozenset(),
}


class MemoryGovernanceError(RSILearningError):
    """Fixed-code errors raised by the memory admission control plane."""


def _digest(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise MemoryGovernanceError(f"rsi_memory_governance_{name}_invalid")
    return value


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or any(char in value for char in "\x00\r\n"):
        raise MemoryGovernanceError(f"rsi_memory_governance_{name}_invalid")
    try:
        if len(value.encode("utf-8")) > 512:
            raise MemoryGovernanceError(f"rsi_memory_governance_{name}_too_large")
    except UnicodeEncodeError as exc:
        raise MemoryGovernanceError(f"rsi_memory_governance_{name}_invalid") from exc
    return value


def _mapping(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise MemoryGovernanceError("rsi_memory_governance_compatibility_invalid")
    try:
        encoded = canonical_json(dict(value), maximum=32 * 1024)
        parsed = json.loads(encoded)
    except Exception as exc:
        raise MemoryGovernanceError("rsi_memory_governance_compatibility_invalid") from exc
    if not isinstance(parsed, dict):
        raise MemoryGovernanceError("rsi_memory_governance_compatibility_invalid")
    return parsed


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=128 * 1024)
    except Exception as exc:
        raise MemoryGovernanceError("rsi_memory_governance_record_invalid") from exc


@dataclass(frozen=True)
class MemoryAdmissionRecord:
    """One immutable version in an admission's lifecycle."""

    admission_id: str
    memory_snapshot_sha256: str
    memory_item_sha256: str
    source_episode_id: str
    verifier_receipt_sha256: str | None
    parent_snapshot_sha256: str | None
    scope: str
    compatibility: Mapping[str, object]
    holdout_receipt_sha256: str | None = None
    baseline_receipt_sha256: str | None = None
    episode_outcome: EpisodeOutcome = "pass"
    regression_passed: bool = False
    state: GovernanceState = "observed"
    revision: int = 0
    parent_record_sha256: str | None = None
    reason: str | None = None
    created_at: str = ""
    record_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.admission_id, "admission_id")
        _digest(self.memory_snapshot_sha256, "memory_snapshot_sha256")
        _digest(self.memory_item_sha256, "memory_item_sha256")
        _identifier(self.source_episode_id, "source_episode_id")
        _digest(self.verifier_receipt_sha256, "verifier_receipt_sha256", optional=True)
        _digest(self.parent_snapshot_sha256, "parent_snapshot_sha256", optional=True)
        _identifier(self.scope, "scope")
        object.__setattr__(self, "compatibility", MappingProxyType(_mapping(self.compatibility)))
        _digest(self.holdout_receipt_sha256, "holdout_receipt_sha256", optional=True)
        _digest(self.baseline_receipt_sha256, "baseline_receipt_sha256", optional=True)
        if self.episode_outcome not in {"pass", "fail", "unknown"}:
            raise MemoryGovernanceError("rsi_memory_governance_episode_outcome_invalid")
        if type(self.regression_passed) is not bool:
            raise MemoryGovernanceError("rsi_memory_governance_regression_invalid")
        if self.state not in _STATES:
            raise MemoryGovernanceError("rsi_memory_governance_state_invalid")
        if type(self.revision) is not int or self.revision < 0:
            raise MemoryGovernanceError("rsi_memory_governance_revision_invalid")
        _digest(self.parent_record_sha256, "parent_record_sha256", optional=True)
        if self.reason is not None:
            _identifier(self.reason, "reason")
        if self.created_at:
            _identifier(self.created_at, "created_at")
        _digest(self.record_sha256, "record_sha256", optional=True)

    def content_dict(self) -> dict[str, Any]:
        """Return the canonical fields covered by this record's digest."""
        return {
            "admission_id": self.admission_id,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "memory_item_sha256": self.memory_item_sha256,
            "source_episode_id": self.source_episode_id,
            "verifier_receipt_sha256": self.verifier_receipt_sha256,
            "parent_snapshot_sha256": self.parent_snapshot_sha256,
            "scope": self.scope,
            "compatibility": dict(self.compatibility),
            "holdout_receipt_sha256": self.holdout_receipt_sha256,
            "baseline_receipt_sha256": self.baseline_receipt_sha256,
            "episode_outcome": self.episode_outcome,
            "regression_passed": self.regression_passed,
            "state": self.state,
            "revision": self.revision,
            "parent_record_sha256": self.parent_record_sha256,
            "reason": self.reason,
            "created_at": self.created_at,
        }

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.content_dict())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = self.content_dict()
        payload["record_sha256"] = self.record_sha256 or self.digest()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> MemoryAdmissionRecord:
        if not isinstance(value, Mapping):
            raise MemoryGovernanceError("rsi_memory_governance_record_invalid")
        allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) - allowed:
            raise MemoryGovernanceError("rsi_memory_governance_record_invalid")
        try:
            record = cls(**dict(value))
        except (TypeError, ValueError) as exc:
            if isinstance(exc, MemoryGovernanceError):
                raise
            raise MemoryGovernanceError("rsi_memory_governance_record_invalid") from exc
        if record.record_sha256 and record.record_sha256 != record.digest():
            raise MemoryGovernanceError("rsi_memory_governance_record_digest_mismatch")
        return record


def _record_with_digest(record: MemoryAdmissionRecord) -> MemoryAdmissionRecord:
    digest = record.digest()
    return replace(record, record_sha256=digest)


class MemoryGovernanceStore:
    """SQLite-backed append-only admission history.

    The database path may be the same file used by :class:`RSILedger`; this module creates only
    its own table and never changes RSI snapshot rows or ledger transitions.
    """

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).expanduser().resolve()
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS rsi_memory_governance (
                    admission_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    parent_record_sha256 TEXT,
                    payload TEXT NOT NULL,
                    record_sha256 TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(admission_id, revision)
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS rsi_memory_governance_state_idx "
                "ON rsi_memory_governance(state, admission_id, revision)"
            )

    def _row(self, row: sqlite3.Row | None) -> MemoryAdmissionRecord | None:
        if row is None:
            return None
        try:
            payload = json.loads(row["payload"])
            record = MemoryAdmissionRecord.from_dict(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryGovernanceError("rsi_memory_governance_storage_corrupt") from exc
        if record.record_sha256 != row["record_sha256"] or record.state != row["state"]:
            raise MemoryGovernanceError("rsi_memory_governance_storage_corrupt")
        return record

    @staticmethod
    def _head(connection: sqlite3.Connection, admission_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM rsi_memory_governance WHERE admission_id = ? "
            "ORDER BY revision DESC LIMIT 1", (admission_id,)
        ).fetchone()

    def create(self, record: MemoryAdmissionRecord) -> MemoryAdmissionRecord:
        """Create an observed admission; all later lifecycle steps use ``transition``."""
        if record.state != "observed" or record.revision != 0 or record.parent_record_sha256 is not None:
            raise MemoryGovernanceError("rsi_memory_governance_initial_state_invalid")
        if not record.created_at:
            record = replace(record, created_at=_now())
        record = _record_with_digest(record)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._head(connection, record.admission_id) is not None:
                raise MemoryGovernanceError("rsi_memory_governance_exists")
            connection.execute(
                "INSERT INTO rsi_memory_governance "
                "(admission_id, revision, state, parent_record_sha256, payload, record_sha256, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.admission_id, record.revision, record.state, None,
                    json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")),
                    record.record_sha256, record.created_at,
                ),
            )
        return record

    def get(self, admission_id: str) -> MemoryAdmissionRecord | None:
        _identifier(admission_id, "admission_id")
        with self._connect() as connection:
            return self._row(self._head(connection, admission_id))

    def history(self, admission_id: str) -> tuple[MemoryAdmissionRecord, ...]:
        _identifier(admission_id, "admission_id")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM rsi_memory_governance WHERE admission_id = ? ORDER BY revision",
                (admission_id,),
            ).fetchall()
        return tuple(self._row(row) for row in rows if row is not None)

    def transition(
        self,
        admission_id: str,
        state: GovernanceState,
        *,
        expected_record_sha256: str,
        verifier_receipt_sha256: str | None = None,
        holdout_receipt_sha256: str | None = None,
        baseline_receipt_sha256: str | None = None,
        regression_passed: bool | None = None,
        episode_outcome: EpisodeOutcome | None = None,
        reason: str | None = None,
        compatibility: Mapping[str, object] | None = None,
    ) -> MemoryAdmissionRecord:
        """Append one lifecycle state after checking gates and the current digest."""
        _identifier(admission_id, "admission_id")
        _digest(expected_record_sha256, "expected_record_sha256")
        if state not in _STATES:
            raise MemoryGovernanceError("rsi_memory_governance_state_invalid")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._row(self._head(connection, admission_id))
            if current is None:
                raise MemoryGovernanceError("rsi_memory_governance_missing")
            if current.record_sha256 != expected_record_sha256:
                raise MemoryGovernanceError("rsi_memory_governance_cas_conflict")
            if current.state == "revoked":
                raise MemoryGovernanceError("rsi_memory_governance_revoked")
            if state != "revoked" and state not in _PROMOTION_EDGES[current.state]:
                raise MemoryGovernanceError("rsi_memory_governance_transition_invalid")
            if episode_outcome is not None and episode_outcome != current.episode_outcome:
                raise MemoryGovernanceError("rsi_memory_governance_episode_outcome_drift")
            for name, incoming, bound in (
                ("verifier_receipt_sha256", verifier_receipt_sha256, current.verifier_receipt_sha256),
                ("holdout_receipt_sha256", holdout_receipt_sha256, current.holdout_receipt_sha256),
                ("baseline_receipt_sha256", baseline_receipt_sha256, current.baseline_receipt_sha256),
            ):
                if incoming is not None and bound is not None and incoming != bound:
                    raise MemoryGovernanceError(f"rsi_memory_governance_{name}_drift")
            if state not in {"approved", "active"}:
                for name, incoming, bound in (
                    ("holdout_receipt_sha256", holdout_receipt_sha256, current.holdout_receipt_sha256),
                    ("baseline_receipt_sha256", baseline_receipt_sha256, current.baseline_receipt_sha256),
                ):
                    if incoming is not None and bound is None:
                        raise MemoryGovernanceError("rsi_memory_governance_regression_gate")
            if (
                regression_passed is not None
                and regression_passed != current.regression_passed
                and (state != "approved" or regression_passed is not True)
            ):
                raise MemoryGovernanceError("rsi_memory_governance_regression_drift")
            if state == "verified":
                if current.episode_outcome != "pass":
                    raise MemoryGovernanceError("rsi_memory_governance_episode_not_pass")
                verifier_receipt_sha256 = verifier_receipt_sha256 or current.verifier_receipt_sha256
                if verifier_receipt_sha256 is None:
                    raise MemoryGovernanceError("rsi_memory_governance_verifier_missing")
            if state == "candidate" and (
                current.episode_outcome != "pass" or current.verifier_receipt_sha256 is None
            ):
                raise MemoryGovernanceError("rsi_memory_governance_candidate_gate")
            if state in {"approved", "active"}:
                holdout_receipt_sha256 = holdout_receipt_sha256 or current.holdout_receipt_sha256
                baseline_receipt_sha256 = baseline_receipt_sha256 or current.baseline_receipt_sha256
                regression_passed = current.regression_passed if regression_passed is None else regression_passed
                if not holdout_receipt_sha256 or not baseline_receipt_sha256 or regression_passed is not True:
                    raise MemoryGovernanceError("rsi_memory_governance_regression_gate")
            if state == "active" and current.state != "approved":
                raise MemoryGovernanceError("rsi_memory_governance_activation_gate")
            if state == "revoked" and not reason:
                raise MemoryGovernanceError("rsi_memory_governance_revoke_reason_missing")
            if compatibility is not None:
                compatibility = _mapping(compatibility)
                if compatibility != dict(current.compatibility):
                    raise MemoryGovernanceError("rsi_memory_governance_compatibility_drift")
            updated = replace(
                current,
                state=state,
                revision=current.revision + 1,
                parent_record_sha256=current.record_sha256,
                verifier_receipt_sha256=verifier_receipt_sha256 or current.verifier_receipt_sha256,
                holdout_receipt_sha256=holdout_receipt_sha256 or current.holdout_receipt_sha256,
                baseline_receipt_sha256=baseline_receipt_sha256 or current.baseline_receipt_sha256,
                regression_passed=current.regression_passed if regression_passed is None else regression_passed,
                episode_outcome=current.episode_outcome if episode_outcome is None else episode_outcome,
                reason=reason or current.reason,
                created_at=_now(),
                record_sha256=None,
            )
            updated = _record_with_digest(updated)
            connection.execute(
                "INSERT INTO rsi_memory_governance "
                "(admission_id, revision, state, parent_record_sha256, payload, record_sha256, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    updated.admission_id, updated.revision, updated.state, updated.parent_record_sha256,
                    json.dumps(updated.to_dict(), sort_keys=True, separators=(",", ":")),
                    updated.record_sha256, updated.created_at,
                ),
            )
            return updated

    def promote(self, admission_id: str, state: GovernanceState, *, expected_record_sha256: str, **kwargs: Any) -> MemoryAdmissionRecord:
        """Named alias for lifecycle callers; all checks remain in ``transition``."""
        return self.transition(admission_id, state, expected_record_sha256=expected_record_sha256, **kwargs)

    def revoke(self, admission_id: str, *, expected_record_sha256: str, reason: str) -> MemoryAdmissionRecord:
        return self.transition(admission_id, "revoked", expected_record_sha256=expected_record_sha256, reason=reason)

    def list_retrievable(
        self, *, scope: str, compatibility: Mapping[str, object] | None = None
    ) -> tuple[MemoryAdmissionRecord, ...]:
        """Return active admissions only; drift and revoked/deprecated records fail closed."""
        _identifier(scope, "scope")
        requested = _mapping(compatibility or {})
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT g.* FROM rsi_memory_governance g "
                "JOIN (SELECT admission_id, MAX(revision) revision FROM rsi_memory_governance "
                "GROUP BY admission_id) h ON g.admission_id = h.admission_id AND g.revision = h.revision "
                "WHERE g.state = 'active' AND json_extract(g.payload, '$.scope') = ?",
                (scope,),
            ).fetchall()
        result: list[MemoryAdmissionRecord] = []
        for row in rows:
            record = self._row(row)
            if record is None:
                continue
            if any(record.compatibility.get(key) != value for key, value in requested.items()):
                continue
            result.append(record)
        return tuple(result)


__all__ = ["GovernanceState", "MemoryAdmissionRecord", "MemoryGovernanceError", "MemoryGovernanceStore"]
