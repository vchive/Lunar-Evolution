"""Explicit, provider-free memory translation into an unverified target candidate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import MemoryItem, MemorySnapshot, RSILearningError

MAX_TRANSLATION_BYTES = 256 * 1024


class MemoryTranslationError(RSILearningError):
    """Fixed-code failures for the explicit translation boundary."""


def _fail(code: str) -> None:
    raise MemoryTranslationError("rsi_memory_translation_" + code)


def _text(value: object, *, maximum: int = 8192, identifier: bool = False) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        _fail("text_invalid")
    try:
        if len(value.encode("utf-8")) > maximum:
            _fail("text_invalid")
    except UnicodeEncodeError as exc:
        raise MemoryTranslationError("rsi_memory_translation_text_invalid") from exc
    if identifier and any(char in value for char in "\r\n"):
        _fail("text_invalid")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        _fail("digest_invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=MAX_TRANSLATION_BYTES)
    except Exception as exc:
        raise MemoryTranslationError("rsi_memory_translation_record_invalid") from exc


@dataclass(frozen=True)
class SolverMemoryMapping:
    """Caller-declared semantics for one source/target solver and contract pair."""

    mapping_id: str
    source_solver_id: str
    target_solver_id: str
    source_solver_fingerprint: str
    target_solver_fingerprint: str
    source_contract_sha256: str
    target_contract_sha256: str
    condition: str
    action: str
    applicability: str
    rationale: str

    def __post_init__(self) -> None:
        for value in (self.mapping_id, self.source_solver_id, self.target_solver_id):
            _text(value, maximum=256, identifier=True)
        for value in (
            self.source_solver_fingerprint, self.target_solver_fingerprint,
            self.source_contract_sha256, self.target_contract_sha256,
        ):
            _digest(value)
        for value in (self.condition, self.action, self.applicability, self.rationale):
            _text(value)
        if self.source_solver_id == self.target_solver_id:
            _fail("same_solver")

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class TranslatedMemoryCandidate:
    """Immutable translation receipt; not a target verifier or promotion decision."""

    source_snapshot_sha256: str
    source_item: MemoryItem
    mapping: SolverMemoryMapping
    candidate_id: str

    def __post_init__(self) -> None:
        _digest(self.source_snapshot_sha256)
        _text(self.candidate_id, maximum=256, identifier=True)
        if not isinstance(self.source_item, MemoryItem) or not isinstance(self.mapping, SolverMemoryMapping):
            _fail("source_invalid")
        if self.source_item.status != "approved" or self.source_item.verifier_outcome != "pass":
            _fail("source_unverified")
        if self.mapping.source_solver_id not in self.source_item.compatible_solvers:
            _fail("source_solver_incompatible")
        if self.mapping.source_contract_sha256 not in self.source_item.compatible_contracts:
            _fail("source_contract_incompatible")
        if self.candidate_id == self.source_item.memory_id:
            _fail("candidate_identity_conflict")
        # Bound every projection at construction rather than deferring to serialization.
        _canonical(self._payload())

    def _payload(self) -> dict[str, Any]:
        source = self.source_item
        return {
            "protocol": "lunar-rsi-memory-translation-v1", "schema_version": "1",
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "source_memory": source.to_dict(), "source_receipt_sha256": source.receipt_sha256,
            "source_causal": {
                "condition": source.condition, "action": source.action,
                "observed_result": source.observed_result, "applicability": source.applicability,
            },
            "mapping": self.mapping.to_dict(),
            "candidate": {
                "memory_id": self.candidate_id, "problem_family": source.problem_family,
                "source_episode_id": source.episode_id,
                "condition": self.mapping.condition, "action": self.mapping.action,
                "observed_result": source.observed_result, "applicability": self.mapping.applicability,
                "compatible_solvers": [self.mapping.target_solver_id],
                "compatible_contracts": [self.mapping.target_contract_sha256],
                "verifier_outcome": "unresolved", "state": "candidate",
                "active_eligible": False, "required_gates": ["verified", "holdout"],
            },
        }

    @property
    def receipt_sha256(self) -> str:
        return hashlib.sha256(_canonical(self._payload())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "receipt_sha256": self.receipt_sha256}

    def to_bytes(self) -> bytes:
        return _canonical(self.to_dict())

    def draft_memory_item(self) -> MemoryItem:
        """Produce an unresolved draft that still requires fresh target verification."""
        return MemoryItem(
            memory_id=self.candidate_id, problem_family=self.source_item.problem_family,
            trigger=self.mapping.condition, strategy=self.mapping.action,
            expected_result=self.source_item.expected_result,
            failure_boundary=self.mapping.applicability,
            compatible_contracts=(self.mapping.target_contract_sha256,),
            compatible_solvers=(self.mapping.target_solver_id,),
            verifier_outcome="unresolved", receipt_sha256=self.receipt_sha256,
            episode_id=self.source_item.episode_id, status="unresolved",
            condition=self.mapping.condition, action=self.mapping.action,
            observed_result=self.source_item.observed_result, applicability=self.mapping.applicability,
        )


def translate_memory(
    source_snapshot: MemorySnapshot, source_memory_id: str, mapping: SolverMemoryMapping,
    *, expected_source_receipt_sha256: str, candidate_id: str,
) -> TranslatedMemoryCandidate:
    """Translate only a declared compatible source; never infer target compatibility."""
    if not isinstance(source_snapshot, MemorySnapshot):
        _fail("source_invalid")
    _text(source_memory_id, maximum=256, identifier=True)
    _digest(expected_source_receipt_sha256)
    source = next((item for item in source_snapshot.items if item.memory_id == source_memory_id), None)
    if source is None:
        _fail("source_missing")
    if source.receipt_sha256 != expected_source_receipt_sha256:
        _fail("source_receipt_drift")
    return TranslatedMemoryCandidate(source_snapshot.digest(), source, mapping, candidate_id)


def recover_translation(
    receipt_bytes: bytes, *, source_snapshot: MemorySnapshot, mapping: SolverMemoryMapping,
    expected_source_receipt_sha256: str, expected_receipt_sha256: str,
) -> TranslatedMemoryCandidate:
    """Read-only replay checked against current caller-supplied frozen provenance."""
    if type(receipt_bytes) is not bytes or len(receipt_bytes) > MAX_TRANSLATION_BYTES:
        _fail("record_invalid")
    _digest(expected_receipt_sha256)
    try:
        payload = json.loads(receipt_bytes)
        if type(payload) is not dict or _canonical(payload) != receipt_bytes:
            _fail("record_invalid")
        source_id = payload["source_memory"]["memory_id"]
        candidate_id = payload["candidate"]["memory_id"]
    except (ValueError, TypeError, KeyError) as exc:
        raise MemoryTranslationError("rsi_memory_translation_record_invalid") from exc
    expected = translate_memory(
        source_snapshot, source_id, mapping,
        expected_source_receipt_sha256=expected_source_receipt_sha256, candidate_id=candidate_id,
    )
    if receipt_bytes != expected.to_bytes() or expected.receipt_sha256 != expected_receipt_sha256:
        _fail("receipt_drift")
    return expected
