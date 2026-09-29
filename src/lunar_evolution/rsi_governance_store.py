"""Durable candidate governance; trusted holdout activation remains a separate boundary."""
from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping
from typing import Any

from .candidate_evaluation_spec import canonical_json, strict_json
from .rsi_learning import MemoryItem, PracticeEpisode, RSILearningError
from .rsi_memory_governance import (
    MemoryAuthority,
    MemoryCompatibility,
    MemoryGovernanceAuthority,
    MemoryPromotionRecord,
    MemoryScope,
)
from .rsi_store import RSILedger

_MAX_RECORD = 128 * 1024


def _sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(value), maximum=_MAX_RECORD)).hexdigest()


class RSIMemoryGovernanceLedger:
    """Append-only lifecycle and content journal in the existing RSI database.

    This first durable boundary admits verified candidates, shadow, revocation and quarantine.
    It deliberately rejects approved/active records until trusted promotion evidence is wired in;
    caller-supplied score fields cannot authorize a usable memory.
    """

    def __init__(self, ledger: RSILedger) -> None:
        if not isinstance(ledger, RSILedger):
            raise RSILearningError("rsi_memory_governance_ledger_invalid")
        self.ledger = ledger
        with ledger._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rsi_memory_governance ("
                "position INTEGER PRIMARY KEY, memory_id TEXT NOT NULL, revision INTEGER NOT NULL, "
                "record_sha256 TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, "
                "UNIQUE(memory_id, revision))"
            )

    @classmethod
    def inspect_records(
        cls, ledger: RSILedger, *, require_journal: bool = False,
    ) -> tuple[MemoryPromotionRecord, ...]:
        """Validate and read an existing journal without initializing or modifying it."""
        if not isinstance(ledger, RSILedger):
            raise RSILearningError("rsi_memory_governance_ledger_invalid")
        reader = object.__new__(cls)
        reader.ledger = ledger
        with sqlite3.connect(ledger.database.absolute().as_uri() + "?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rsi_memory_governance'"
            ).fetchone()
            if exists is None:
                if require_journal:
                    raise RSILearningError("rsi_memory_governance_journal_missing")
                return ()
            return tuple(reader._read(connection)[0])

    def _source(
        self, connection: sqlite3.Connection, record: MemoryPromotionRecord, memory: MemoryItem,
    ) -> None:
        rows = connection.execute(
            "SELECT * FROM rsi_records WHERE logical_id = ? ORDER BY revision",
            (record.authority.source_episode_id,),
        ).fetchall()
        source = None
        parent = None
        for revision, row in enumerate(rows):
            retained = self.ledger._row_to_record(row)
            if (retained.revision != revision or retained.parent_record_sha256 != parent
                    or retained.kind != "episode"):
                raise RSILearningError("rsi_memory_source_ledger_corrupt")
            parent = retained.record_sha256
            episode = PracticeEpisode.from_dict(retained.payload)
            if retained.state != episode.status or retained.request_sha256 != episode.request_sha256:
                raise RSILearningError("rsi_memory_source_ledger_corrupt")
            if episode.digest() == record.authority.source_episode_sha256:
                source = episode
        if source is None:
            raise RSILearningError("rsi_memory_source_evidence_missing")
        # Reuse the same authority check as a fresh verification, without executing a verifier.
        authority = MemoryGovernanceAuthority()
        observed = authority.observe(
            record.authority,
            observation_receipt_sha256=record.receipts[0].receipt_sha256,
            actor_fingerprint=record.receipts[0].actor_fingerprint,
            reason_code=record.receipts[0].reason_code,
        )
        verified = authority.verify(
            observed, source_episode=source,
            transition_receipt_sha256=_sha({"source_episode": source.digest()}),
            actor_fingerprint=record.receipts[0].actor_fingerprint,
        )
        if memory.receipt_sha256 != verified.verifier_receipt_sha256:
            raise RSILearningError("rsi_memory_source_verifier_mismatch")
        if record.verifier_receipt_sha256 is not None and (
            record.verifier_receipt_sha256 != verified.verifier_receipt_sha256
            or record.verifier_fingerprint != verified.verifier_fingerprint
        ):
            raise RSILearningError("rsi_memory_source_verifier_mismatch")

    @staticmethod
    def _bind_content(record: MemoryPromotionRecord, memory: MemoryItem) -> None:
        source = record.authority
        if (memory.memory_id != source.memory_id or _sha(memory.to_dict()) != source.content_sha256
                or memory.episode_id != source.source_episode_id
                or memory.problem_family != source.scope.problem_family
                or memory.status != "approved" or memory.verifier_outcome != "pass"
                or memory.compatible_contracts != (source.compatibility.contract_sha256,)
                or source.compatibility.solver_id not in memory.compatible_solvers
                or (record.verifier_receipt_sha256 is not None
                    and memory.receipt_sha256 != record.verifier_receipt_sha256)):
            raise RSILearningError("rsi_memory_content_authority_mismatch")

    @staticmethod
    def _check_admission(record: MemoryPromotionRecord) -> None:
        if any(receipt.state in {"approved", "active"} for receipt in record.receipts):
            raise RSILearningError("rsi_memory_trusted_promotion_unavailable")

    def _read(self, connection: sqlite3.Connection):
        records: list[MemoryPromotionRecord] = []
        contents: dict[str, MemoryItem] = {}
        revisions: dict[str, int] = {}
        rows = connection.execute("SELECT * FROM rsi_memory_governance ORDER BY position").fetchall()
        for position, row in enumerate(rows):
            try:
                value = strict_json(row["payload"].encode("utf-8"), maximum=_MAX_RECORD)
                if not isinstance(value, dict) or set(value) != {"record", "memory"}:
                    raise ValueError("invalid envelope")
                record = MemoryPromotionRecord.from_dict(value["record"])
                memory = MemoryItem.from_dict(value["memory"])
            except (TypeError, ValueError, KeyError) as exc:
                raise RSILearningError("rsi_memory_governance_record_corrupt") from exc
            memory_id = record.authority.memory_id
            revision = revisions.get(memory_id, 0)
            if (row["position"] != position or row["memory_id"] != memory_id
                    or row["revision"] != revision or row["record_sha256"] != record.digest()):
                raise RSILearningError("rsi_memory_governance_journal_corrupt")
            self._check_admission(record)
            self._bind_content(record, memory)
            self._source(connection, record, memory)
            previous_content = contents.get(memory_id)
            if previous_content is not None and previous_content.to_dict() != memory.to_dict():
                raise RSILearningError("rsi_memory_content_authority_mismatch")
            contents[memory_id] = memory
            revisions[memory_id] = revision + 1
            records.append(record)
        authority = MemoryGovernanceAuthority.from_history(records)
        return records, contents, authority

    def history(self, memory_id: str) -> tuple[MemoryPromotionRecord, ...]:
        with self.ledger._connect() as connection:
            connection.execute("BEGIN")
            records, _contents, authority = self._read(connection)
            authority.get(memory_id)
            return tuple(record for record in records if record.authority.memory_id == memory_id)

    def restore(self) -> MemoryGovernanceAuthority:
        with self.ledger._connect() as connection:
            connection.execute("BEGIN")
            return self._read(connection)[2]

    def append(
        self, record: MemoryPromotionRecord, *, memory: MemoryItem,
        expected_record_sha256: str | None,
    ) -> MemoryPromotionRecord:
        if not isinstance(record, MemoryPromotionRecord) or not isinstance(memory, MemoryItem):
            raise RSILearningError("rsi_memory_governance_record_invalid")
        self._check_admission(record)
        self._bind_content(record, memory)
        with self.ledger._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            records, contents, authority = self._read(connection)
            memory_id = record.authority.memory_id
            head = authority.get(memory_id)
            if head is not None and head.digest() == record.digest():
                if expected_record_sha256 != record.previous_record_sha256:
                    raise RSILearningError("rsi_memory_governance_parent_conflict")
                return head
            if (head.digest() if head is not None else None) != expected_record_sha256:
                raise RSILearningError("rsi_memory_governance_parent_conflict")
            MemoryGovernanceAuthority.from_history([*records, record])
            self._source(connection, record, memory)
            if memory_id in contents and contents[memory_id].to_dict() != memory.to_dict():
                raise RSILearningError("rsi_memory_content_authority_mismatch")
            revision = sum(item.authority.memory_id == memory_id for item in records)
            payload = canonical_json(
                {"record": record.to_dict(), "memory": memory.to_dict()}, maximum=_MAX_RECORD,
            ).decode("utf-8")
            connection.execute("INSERT INTO rsi_memory_governance VALUES (?, ?, ?, ?, ?)",
                               (len(records), memory_id, revision, record.digest(), payload))
        return record

    @staticmethod
    def preview_nomination(
        *, episode: PracticeEpisode, memory: MemoryItem, scope: MemoryScope,
        actor_fingerprint: str,
    ) -> tuple[MemoryPromotionRecord, MemoryPromotionRecord, MemoryPromotionRecord]:
        """Build a deterministic candidate proposal without reading or writing a ledger."""
        source = MemoryAuthority(
            memory.memory_id, _sha(memory.to_dict()), episode.episode_id, episode.digest(),
            episode.official_evaluation_receipt_sha256, episode.memory_snapshot_sha256, scope,
            MemoryCompatibility(episode.contract_sha256, episode.evaluator_sha256,
                                episode.environment_sha256, episode.solver_id,
                                episode.solver_fingerprint),
        )
        governance = MemoryGovernanceAuthority()
        observed = governance.observe(
            source, observation_receipt_sha256=source.source_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
        )
        verified = governance.verify(
            observed, source_episode=episode,
            transition_receipt_sha256=_sha({"state": "verified", "parent": observed.digest()}),
            actor_fingerprint=actor_fingerprint,
        )
        candidate = governance.nominate_candidate(
            verified, transition_receipt_sha256=_sha({"state": "candidate", "parent": verified.digest()}),
            actor_fingerprint=actor_fingerprint,
        )
        return observed, verified, candidate

    def nominate(
        self, *, episode: PracticeEpisode, memory: MemoryItem, scope: MemoryScope,
        actor_fingerprint: str,
    ) -> MemoryPromotionRecord:
        """Persist observed/verified/candidate idempotently, including partial-write recovery."""
        expected = self.preview_nomination(
            episode=episode, memory=memory, scope=scope, actor_fingerprint=actor_fingerprint,
        )
        retained = self.history(memory.memory_id)
        if tuple(record.digest() for record in retained[:3]) != tuple(
            record.digest() for record in expected[:len(retained)]
        ):
            raise RSILearningError("rsi_memory_candidate_identity_drift")
        if len(retained) >= 3:
            return retained[-1]
        for record in expected[len(retained):]:
            self.append(record, memory=memory, expected_record_sha256=record.previous_record_sha256)
        return expected[-1]


__all__ = ["RSIMemoryGovernanceLedger"]
