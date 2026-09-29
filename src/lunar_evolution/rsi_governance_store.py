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
_ANCHOR_ID = 1
_TRUSTED_PROOF_PROTOCOL = "lunar-rsi-trusted-promotion-proof-v1"


def _history_digest(
    parent: str | None, position: int, record_sha256: str | None, state: str | None,
) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "parent": parent,
                "position": position,
                "record_sha256": record_sha256,
                "state": state,
            },
            maximum=_MAX_RECORD,
        )
    ).hexdigest()


def _sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(value), maximum=_MAX_RECORD)).hexdigest()


class RSIMemoryGovernanceLedger:
    """Append-only lifecycle and content journal in the existing RSI database.

    This first durable boundary admits verified candidates, shadow, revocation and quarantine.
    It deliberately rejects approved/active records until trusted promotion evidence is wired in;
    caller-supplied score fields cannot authorize a usable memory.
    """

    def __init__(self, ledger: RSILedger, *, promotion_evidence: Any | None = None) -> None:
        if not isinstance(ledger, RSILedger):
            raise RSILearningError("rsi_memory_governance_ledger_invalid")
        self.ledger = ledger
        self.promotion_evidence = promotion_evidence
        with ledger._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rsi_memory_governance'"
            ).fetchone()
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rsi_memory_governance ("
                "position INTEGER PRIMARY KEY, memory_id TEXT NOT NULL, revision INTEGER NOT NULL, "
                "record_sha256 TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, "
                "UNIQUE(memory_id, revision))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rsi_memory_governance_anchor ("
                "anchor_id INTEGER PRIMARY KEY CHECK(anchor_id = 1), "
                "position INTEGER NOT NULL, record_sha256 TEXT, state TEXT, "
                "history_sha256 TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rsi_memory_trusted_proof ("
                "record_sha256 TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            anchor = connection.execute(
                "SELECT 1 FROM rsi_memory_governance_anchor WHERE anchor_id = ?", (_ANCHOR_ID,)
            ).fetchone()
            if anchor is None:
                if existing is not None:
                    # A pre-anchor journal cannot be safely upgraded: its missing high-water
                    # mark would make tail deletion indistinguishable from a valid history.
                    return
                connection.execute(
                    "INSERT INTO rsi_memory_governance_anchor "
                    "(anchor_id, position, record_sha256, state, history_sha256) VALUES (?, ?, ?, ?, ?)",
                    (_ANCHOR_ID, -1, None, None, _history_digest(None, -1, None, None)),
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
        reader.promotion_evidence = None
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
            return tuple(reader._read(connection, allow_trusted=True)[0])

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
    def _check_admission(record: MemoryPromotionRecord, *, allow_trusted: bool = False) -> None:
        if not allow_trusted and any(receipt.state in {"approved", "active"} for receipt in record.receipts):
            raise RSILearningError("rsi_memory_trusted_promotion_unavailable")

    @staticmethod
    def _anchor_row(connection: sqlite3.Connection) -> dict[str, Any]:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'rsi_memory_governance_anchor'"
        ).fetchone()
        if exists is None:
            raise RSILearningError("rsi_memory_governance_anchor_missing")
        rows = connection.execute(
            "SELECT anchor_id, position, record_sha256, state, history_sha256 "
            "FROM rsi_memory_governance_anchor ORDER BY anchor_id"
        ).fetchall()
        if len(rows) != 1 or rows[0]["anchor_id"] != _ANCHOR_ID:
            raise RSILearningError("rsi_memory_governance_anchor_missing")
        row = rows[0]
        position = row["position"]
        record_sha256 = row["record_sha256"]
        state = row["state"]
        history_sha256 = row["history_sha256"]
        if type(position) is not int or position < -1:
            raise RSILearningError("rsi_memory_governance_anchor_corrupt")
        if record_sha256 is not None and (
            type(record_sha256) is not str or len(record_sha256) != 64
            or any(char not in "0123456789abcdef" for char in record_sha256)
        ):
            raise RSILearningError("rsi_memory_governance_anchor_corrupt")
        if state is not None and type(state) is not str:
            raise RSILearningError("rsi_memory_governance_anchor_corrupt")
        if (type(history_sha256) is not str or len(history_sha256) != 64
                or any(char not in "0123456789abcdef" for char in history_sha256)):
            raise RSILearningError("rsi_memory_governance_anchor_corrupt")
        return {
            "position": position,
            "record_sha256": record_sha256,
            "state": state,
            "history_sha256": history_sha256,
        }

    @staticmethod
    def _history_anchor(records: list[MemoryPromotionRecord]) -> dict[str, Any]:
        parent: str | None = None
        state: str | None = None
        record_sha256: str | None = None
        for position, record in enumerate(records):
            record_sha256 = record.digest()
            state = record.state
            parent = _history_digest(parent, position, record_sha256, state)
        return {
            "position": len(records) - 1,
            "record_sha256": record_sha256,
            "state": state,
            "history_sha256": parent or _history_digest(None, -1, None, None),
        }

    @classmethod
    def _validate_anchor_rows(
        cls, connection: sqlite3.Connection, records: list[MemoryPromotionRecord],
    ) -> dict[str, Any]:
        anchor = cls._anchor_row(connection)
        if anchor != cls._history_anchor(records):
            raise RSILearningError("rsi_memory_governance_anchor_mismatch")
        return anchor

    def checkpoint_anchor(self) -> dict[str, Any]:
        """Return the verified governance high-water mark for a controller checkpoint."""
        with self.ledger._connect() as connection:
            connection.execute("BEGIN")
            self._read(connection, allow_trusted=True)
            return self._anchor_row(connection)

    def validate_anchor(self, expected: Mapping[str, Any]) -> None:
        """Require a retained history prefix; later transitions remain authoritative."""
        if (not isinstance(expected, Mapping)
                or set(expected) != {"position", "record_sha256", "state", "history_sha256"}
                or type(expected["position"]) is not int or expected["position"] < -1):
            raise RSILearningError("rsi_memory_governance_anchor_invalid")
        with self.ledger._connect() as connection:
            connection.execute("BEGIN")
            records, _contents, _authority = self._read(connection, allow_trusted=True)
            prefix_length = expected["position"] + 1
            if prefix_length > len(records):
                raise RSILearningError("rsi_memory_governance_anchor_conflict")
            actual = self._history_anchor(records[:prefix_length])
        if dict(expected) != actual:
            raise RSILearningError("rsi_memory_governance_anchor_conflict")

    def _read(self, connection: sqlite3.Connection, *, allow_trusted: bool = False):
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
            self._check_admission(record, allow_trusted=allow_trusted)
            if allow_trusted and any(receipt.state in {"approved", "active"} for receipt in record.receipts):
                proof = connection.execute(
                    "SELECT payload FROM rsi_memory_trusted_proof WHERE record_sha256 = ?",
                    (record.digest(),),
                ).fetchone()
                if proof is None:
                    raise RSILearningError("rsi_memory_trusted_proof_missing")
                try:
                    retained_proof = strict_json(proof[0].encode("utf-8"), maximum=_MAX_RECORD)
                except (TypeError, ValueError) as exc:
                    raise RSILearningError("rsi_memory_trusted_proof_invalid") from exc
                self._validate_proof(record, retained_proof)
            self._bind_content(record, memory)
            self._source(connection, record, memory)
            previous_content = contents.get(memory_id)
            if previous_content is not None and previous_content.to_dict() != memory.to_dict():
                raise RSILearningError("rsi_memory_content_authority_mismatch")
            contents[memory_id] = memory
            revisions[memory_id] = revision + 1
            records.append(record)
        self._validate_anchor_rows(connection, records)
        authority = MemoryGovernanceAuthority.from_history(records)
        return records, contents, authority

    def history(self, memory_id: str) -> tuple[MemoryPromotionRecord, ...]:
        with self.ledger._connect() as connection:
            connection.execute("BEGIN")
            records, _contents, authority = self._read(connection, allow_trusted=True)
            authority.get(memory_id)
            return tuple(record for record in records if record.authority.memory_id == memory_id)

    def restore(self) -> MemoryGovernanceAuthority:
        with self.ledger._connect() as connection:
            connection.execute("BEGIN")
            return self._read(connection, allow_trusted=True)[2]

    def active_memories(
        self, *, scope: MemoryScope, compatibility: MemoryCompatibility,
    ) -> tuple[MemoryItem, ...]:
        """Return only content whose durable lifecycle head is active."""
        with self.ledger._connect() as connection:
            connection.execute("BEGIN")
            _records, contents, authority = self._read(connection, allow_trusted=True)
            active = authority.retrieve(scope=scope, compatibility=compatibility)
            return tuple(contents[item.authority.memory_id] for item in active)

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
            records, contents, authority = self._read(connection, allow_trusted=True)
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
            position = len(records)
            connection.execute("INSERT INTO rsi_memory_governance VALUES (?, ?, ?, ?, ?)",
                               (position, memory_id, revision, record.digest(), payload))
            previous_anchor = self._anchor_row(connection)
            history_sha256 = _history_digest(
                None if position == 0 else previous_anchor["history_sha256"],
                position, record.digest(), record.state,
            )
            updated = connection.execute(
                "UPDATE rsi_memory_governance_anchor SET position = ?, record_sha256 = ?, "
                "state = ?, history_sha256 = ? WHERE anchor_id = ? AND position = ? "
                "AND history_sha256 = ?",
                (
                    position, record.digest(), record.state, history_sha256, _ANCHOR_ID,
                    position - 1, previous_anchor["history_sha256"],
                ),
            )
            if updated.rowcount != 1:
                raise RSILearningError("rsi_memory_governance_anchor_conflict")
        return record

    def append_trusted(
        self, record: MemoryPromotionRecord, *, memory: MemoryItem,
        expected_record_sha256: str | None, proof: Mapping[str, Any],
    ) -> MemoryPromotionRecord:
        """Append a holdout-gated trusted transition through an explicit API.

        The ordinary ``append`` method remains fail-closed for approved/active states.  This
        method is intentionally separate so callers must opt into the promotion path after
        constructing and validating a ``PromotionGate``.
        """
        if not isinstance(record, MemoryPromotionRecord) or not isinstance(memory, MemoryItem):
            raise RSILearningError("rsi_memory_governance_record_invalid")
        self._check_admission(record, allow_trusted=True)
        self._validate_proof(record, proof)
        self._bind_content(record, memory)
        with self.ledger._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            records, contents, authority = self._read(connection, allow_trusted=True)
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
            position = len(records)
            connection.execute(
                "INSERT INTO rsi_memory_governance VALUES (?, ?, ?, ?, ?)",
                (position, memory_id, revision, record.digest(), payload),
            )
            connection.execute(
                "INSERT INTO rsi_memory_trusted_proof(record_sha256, payload) VALUES (?, ?)",
                (record.digest(), canonical_json(dict(proof), maximum=_MAX_RECORD).decode("utf-8")),
            )
            previous_anchor = self._anchor_row(connection)
            history_sha256 = _history_digest(
                None if position == 0 else previous_anchor["history_sha256"],
                position, record.digest(), record.state,
            )
            updated = connection.execute(
                "UPDATE rsi_memory_governance_anchor SET position = ?, record_sha256 = ?, state = ?, history_sha256 = ? "
                "WHERE anchor_id = ? AND position = ? AND history_sha256 = ?",
                (position, record.digest(), record.state, history_sha256, _ANCHOR_ID,
                 position - 1, previous_anchor["history_sha256"]),
            )
            if updated.rowcount != 1:
                raise RSILearningError("rsi_memory_governance_anchor_conflict")
        return record

    def _retained_promotion(self, record: MemoryPromotionRecord) -> dict[str, Any]:
        # An arbitrary callback returning a success flag is not promotion authority.
        from .rsi_promotion import NativePromotionEvidence

        service = self.promotion_evidence
        if type(service) is not NativePromotionEvidence:
            raise RSILearningError("rsi_memory_trusted_promotion_unavailable")
        return service.validate_retained(record)

    def _proof(self, record: MemoryPromotionRecord, retained: Mapping[str, Any]) -> dict[str, Any]:
        gate = self.promotion_evidence.derive_gate(record, retained)
        if record.gate != gate:
            raise RSILearningError("rsi_memory_trusted_proof_gate_mismatch")
        return {
            "protocol": _TRUSTED_PROOF_PROTOCOL, "record_sha256": record.digest(),
            "service_fingerprint": retained["service_fingerprint"],
            "snapshot_sha256": retained["snapshot_sha256"],
            "comparison_receipt_sha256": retained["practice"]["receipt_sha256"],
            "holdout_comparison_receipt_sha256": retained["holdout"]["receipt_sha256"],
            "gate_sha256": _sha(gate.to_dict()),
        }

    def _validate_proof(self, record: MemoryPromotionRecord, proof: object) -> None:
        if not isinstance(proof, Mapping):
            raise RSILearningError("rsi_memory_trusted_proof_invalid")
        retained = self._retained_promotion(record)
        if dict(proof) != self._proof(record, retained):
            raise RSILearningError("rsi_memory_trusted_evidence_mismatch")

    def promote_shadow(
        self, *, memory_id: str, gate: Any, transition_receipt_sha256: str,
        actor_fingerprint: str, expected_record_sha256: str | None, memory: MemoryItem,
        proof: Mapping[str, Any] | None = None,
    ) -> MemoryPromotionRecord:
        """Advance a shadow candidate to approved after validating independent gate evidence."""
        authority = self.restore()
        head = authority.get(memory_id)
        if head is None:
            raise RSILearningError("rsi_memory_record_unknown")
        approved = authority.approve(
            head, gate, transition_receipt_sha256=transition_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
        )
        if proof is None:
            raise RSILearningError("rsi_memory_trusted_proof_required")
        return self.append_trusted(
            approved, memory=memory, expected_record_sha256=expected_record_sha256, proof=proof,
        )

    def promote_from_comparisons(
        self, *, memory_id: str, memory: MemoryItem, practice_comparison: Mapping[str, Any],
        holdout_comparison: Mapping[str, Any], transition_receipt_sha256: str,
        actor_fingerprint: str, expected_record_sha256: str | None,
    ) -> MemoryPromotionRecord:
        """Reopen retained panels, derive their gate, and durably approve a shadow candidate."""
        head = self.restore().get(memory_id)
        if head is None:
            raise RSILearningError("rsi_memory_record_unknown")
        retained = self._retained_promotion(head)
        if (retained["practice"] != practice_comparison
                or retained["holdout"] != holdout_comparison):
            raise RSILearningError("rsi_memory_trusted_evidence_mismatch")
        gate = self.promotion_evidence.derive_gate(head, retained)
        approved = self.restore().approve(
            head, gate, transition_receipt_sha256=transition_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
        )
        proof = self._proof(approved, retained)
        return self.append_trusted(approved, memory=memory, expected_record_sha256=expected_record_sha256, proof=proof)

    def activate(
        self, *, memory_id: str, transition_receipt_sha256: str,
        actor_fingerprint: str, expected_record_sha256: str | None, memory: MemoryItem,
        proof: Mapping[str, Any] | None = None,
    ) -> MemoryPromotionRecord:
        """Activate an approved record after its retained holdout gate passes."""
        authority = self.restore()
        head = authority.get(memory_id)
        if head is None:
            raise RSILearningError("rsi_memory_record_unknown")
        active = authority.activate(
            head, transition_receipt_sha256=transition_receipt_sha256,
            actor_fingerprint=actor_fingerprint,
        )
        if proof is None:
            proof = self._proof(active, self._retained_promotion(active))
        return self.append_trusted(
            active, memory=memory, expected_record_sha256=expected_record_sha256, proof=proof,
        )

    def terminalize(
        self, *, memory_id: str, state: str, transition_receipt_sha256: str,
        actor_fingerprint: str, expected_record_sha256: str | None, memory: MemoryItem,
        proof: Mapping[str, Any] | None = None,
    ) -> MemoryPromotionRecord:
        """Revoke or quarantine a record; both are excluded from active retrieval."""
        authority = self.restore()
        head = authority.get(memory_id)
        if head is None:
            raise RSILearningError("rsi_memory_record_unknown")
        if state == "revoked":
            next_record = authority.revoke(
                head, transition_receipt_sha256=transition_receipt_sha256,
                actor_fingerprint=actor_fingerprint,
            )
        elif state == "quarantined":
            next_record = authority.quarantine(
                head, transition_receipt_sha256=transition_receipt_sha256,
                actor_fingerprint=actor_fingerprint,
            )
        else:
            raise RSILearningError("rsi_memory_lifecycle_state_invalid")
        if head.gate is None:
            return self.append(next_record, memory=memory, expected_record_sha256=expected_record_sha256)
        if proof is None:
            proof = self._proof(next_record, self._retained_promotion(next_record))
        return self.append_trusted(
            next_record, memory=memory, expected_record_sha256=expected_record_sha256,
            proof=proof,
        )

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
