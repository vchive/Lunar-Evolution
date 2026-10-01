"""Fail-closed, read-only admission for one explicitly governed frozen RSI snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.parse import quote

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import MAX_MEMORY_ENTRIES, MemorySnapshot
from .rsi_memory_governance import (
    MemoryGovernanceError,
    MemoryGovernanceStore,
    _identifier,
    _mapping,
)


class MemorySnapshotAdmissionError(MemoryGovernanceError):
    """A fixed-code refusal to use any item in the configured frozen snapshot."""


def _fail(code: str) -> None:
    raise MemorySnapshotAdmissionError("rsi_memory_snapshot_gate_" + code)


def _database_identity(path: Path) -> tuple[int, int]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _fail("database_invalid")
        return info.st_dev, info.st_ino
    except OSError as exc:
        raise MemorySnapshotAdmissionError("rsi_memory_snapshot_gate_database_invalid") from exc


@dataclass(frozen=True, init=False)
class GovernedMemorySnapshotGate:
    """Require exact active admissions without altering the frozen snapshot.

    Inherited items must be explicitly re-admitted for this exact snapshot; lineage-based
    reuse is outside this first boundary. Configuration is stable across mutable head changes.
    """

    _governance: MemoryGovernanceStore
    _database: Path
    _identity: tuple[int, int]
    _snapshot_sha256: str
    _admissions: Mapping[str, str]
    _scope: str
    _compatibility_bytes: bytes

    def __init__(
        self,
        governance: MemoryGovernanceStore,
        *,
        snapshot_sha256: str,
        admissions: Mapping[str, str],
        scope: str,
        compatibility: Mapping[str, object],
    ) -> None:
        if not isinstance(governance, MemoryGovernanceStore):
            _fail("governance_invalid")
        if (type(snapshot_sha256) is not str or len(snapshot_sha256) != 64
                or any(char not in "0123456789abcdef" for char in snapshot_sha256)):
            _fail("snapshot_invalid")
        if not isinstance(admissions, Mapping) or len(admissions) > MAX_MEMORY_ENTRIES:
            _fail("mapping_invalid")
        try:
            parsed = {_identifier(key, "memory_id"): _identifier(value, "admission_id")
                      for key, value in admissions.items()}
            _identifier(scope, "scope")
            pins = canonical_json(_mapping(compatibility), maximum=32 * 1024)
        except (MemoryGovernanceError, TypeError, ValueError) as exc:
            raise MemorySnapshotAdmissionError("rsi_memory_snapshot_gate_configuration_invalid") from exc
        if len(set(parsed.values())) != len(parsed):
            _fail("mapping_invalid")
        path = governance.database
        object.__setattr__(self, "_governance", governance)
        object.__setattr__(self, "_database", path)
        object.__setattr__(self, "_identity", _database_identity(path))
        object.__setattr__(self, "_snapshot_sha256", snapshot_sha256)
        object.__setattr__(self, "_admissions", MappingProxyType(parsed))
        object.__setattr__(self, "_scope", scope)
        object.__setattr__(self, "_compatibility_bytes", pins)

    def rsi_fingerprint_config(self) -> dict[str, object]:
        """Pin configuration and database identity, never mutable admission state."""
        return {
            "protocol": "lunar-rsi-governed-memory-snapshot-v1",
            "database": str(self._database),
            "database_device": self._identity[0],
            "database_inode": self._identity[1],
            "snapshot_sha256": self._snapshot_sha256,
            "admissions": dict(self._admissions),
            "scope": self._scope,
            "compatibility": json.loads(self._compatibility_bytes),
        }

    def validate(self, snapshot: MemorySnapshot) -> None:
        """Read current governance heads and reject the whole snapshot on any mismatch."""
        if not isinstance(snapshot, MemorySnapshot) or snapshot.digest() != self._snapshot_sha256:
            _fail("snapshot_drift")
        if set(self._admissions) != {item.memory_id for item in snapshot.items}:
            _fail("mapping_incomplete")
        if self._governance.database != self._database or _database_identity(self._database) != self._identity:
            _fail("database_changed")
        if not snapshot.items:
            return
        try:
            uri = "file:" + quote(os.fspath(self._database), safe="/") + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
                connection.row_factory = sqlite3.Row
                identifiers = tuple(self._admissions.values())
                placeholders = ",".join("?" for _ in identifiers)
                rows = connection.execute(
                    "SELECT g.* FROM rsi_memory_governance g "
                    "JOIN (SELECT admission_id, MAX(revision) revision FROM rsi_memory_governance "
                    "GROUP BY admission_id) h ON g.admission_id = h.admission_id AND g.revision = h.revision "
                    f"WHERE g.admission_id IN ({placeholders})", identifiers,
                ).fetchall()
                records = {}
                for row in rows:
                    record = self._governance._row(row)
                    if record is None or any((
                        record.admission_id != row["admission_id"],
                        record.revision != row["revision"],
                        record.parent_record_sha256 != row["parent_record_sha256"],
                        record.created_at != row["created_at"],
                    )):
                        _fail("storage_invalid")
                    records[row["admission_id"]] = record
        except (sqlite3.Error, MemoryGovernanceError, OSError, ValueError) as exc:
            raise MemorySnapshotAdmissionError("rsi_memory_snapshot_gate_storage_invalid") from exc
        if _database_identity(self._database) != self._identity:
            _fail("database_changed")
        pins = json.loads(self._compatibility_bytes)
        for item in snapshot.items:
            record = records.get(self._admissions[item.memory_id])
            if record is None:
                _fail("admission_missing")
            if record.state == "revoked":
                _fail("revoked")
            if record.state != "active":
                _fail("inactive")
            if (
                record.episode_outcome != "pass" or record.regression_passed is not True
                or record.holdout_receipt_sha256 is None or record.baseline_receipt_sha256 is None
            ):
                _fail("evidence_missing")
            item_digest = hashlib.sha256(canonical_json(item.to_dict(), maximum=128 * 1024)).hexdigest()
            if (
                record.admission_id != self._admissions[item.memory_id]
                or record.memory_snapshot_sha256 != snapshot.digest()
                or record.parent_snapshot_sha256 != snapshot.parent_snapshot_sha256
                or record.memory_item_sha256 != item_digest
                or record.source_episode_id != item.episode_id
                or record.verifier_receipt_sha256 != item.receipt_sha256
                or record.scope != self._scope or dict(record.compatibility) != pins
            ):
                _fail("admission_drift")


__all__ = ["GovernedMemorySnapshotGate", "MemorySnapshotAdmissionError"]
