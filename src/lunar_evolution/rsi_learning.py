"""Immutable protocol objects for Lunar's verifier-gated RSI learning mode.

This module is deliberately provider-free.  It describes the durable boundary between an RSI
controller and the existing solve/solver layers; it does not run a model, evaluator, or solver.
Ordinary ``MemoryStore`` notes remain separate from these approved, content-addressed snapshots.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from .candidate_evaluation_spec import canonical_json, strict_json

RSI_PROTOCOL = "lunar-rsi-learning-v1"
RSI_SCHEMA_VERSION = "1"
MAX_RSI_RECORD_BYTES = 128 * 1024
MAX_MEMORY_ENTRIES = 256
MAX_TEXT_BYTES = 8 * 1024
MAX_TRACE_DIGESTS = 64
MAX_TRACE_EVENTS = 64

VerifierOutcome = Literal["pass", "fail", "unresolved"]
EpisodeStatus = Literal[
    "planned", "running", "completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"
]
MemoryStatus = Literal["approved", "rejected", "unresolved"]
TransferStatus = Literal["passed", "failed", "unknown"]


class RSILearningError(ValueError):
    """A bounded, fixed-code RSI protocol or snapshot failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise RSILearningError(code)


def _text(value: object, *, name: str, maximum: int = MAX_TEXT_BYTES) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        _fail(f"rsi_{name}_invalid")
    try:
        if len(value.encode("utf-8")) > maximum:
            _fail(f"rsi_{name}_too_large")
    except UnicodeEncodeError:
        _fail(f"rsi_{name}_invalid")
    return value


def _id(value: object, *, name: str) -> str:
    value = _text(value, name=name, maximum=256)
    if any(char in value for char in "\r\n"):
        _fail(f"rsi_{name}_invalid")
    return value


def _digest(value: object, *, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        _fail(f"rsi_{name}_invalid")
    return value


def _optional_digest(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _digest(value, name=name)


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=MAX_RSI_RECORD_BYTES)
    except Exception as exc:
        if isinstance(exc, RSILearningError):
            raise
        _fail("rsi_record_invalid")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _object(value: object, *, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        _fail("rsi_record_invalid")
    if set(value) - allowed or required - set(value):
        _fail("rsi_record_invalid")
    return value


def _digest_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_TRACE_DIGESTS:
        _fail("rsi_trace_invalid")
    result = tuple(_digest(item, name="trace_digest") for item in value)
    if len(set(result)) != len(result):
        _fail("rsi_trace_invalid")
    return result


@dataclass(frozen=True)
class TraceEvent:
    """A bounded public action/tool/observation event.

    Private model reasoning is intentionally absent.  Each payload is represented by a digest so
    an actor can retain a detailed local trace without making it part of the RSI control plane.
    """

    sequence: int
    kind: Literal["action", "tool", "observation"]
    name: str
    payload_sha256: str
    observation_sha256: str | None = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0 or self.sequence >= MAX_TRACE_EVENTS:
            _fail("rsi_trace_event_sequence_invalid")
        if self.kind not in {"action", "tool", "observation"}:
            _fail("rsi_trace_event_kind_invalid")
        _id(self.name, name="trace_event_name")
        _digest(self.payload_sha256, name="trace_event_payload_sha256")
        _optional_digest(self.observation_sha256, name="trace_event_observation_sha256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "name": self.name,
            "payload_sha256": self.payload_sha256,
            "observation_sha256": self.observation_sha256,
        }


@dataclass(frozen=True)
class MemoryItem:
    """One verifier-gated, portable strategy observation."""

    memory_id: str
    problem_family: str
    trigger: str
    strategy: str
    expected_result: str
    failure_boundary: str
    compatible_contracts: tuple[str, ...]
    compatible_solvers: tuple[str, ...]
    verifier_outcome: VerifierOutcome
    receipt_sha256: str
    episode_id: str
    status: MemoryStatus = "approved"
    # Explicit causal form used by RSIAgent-style memory.  Legacy fields above remain as the
    # human-readable projection and are populated into this form when omitted.
    condition: str | None = None
    action: str | None = None
    observed_result: str | None = None
    applicability: str | None = None
    # ``None`` denotes the current wire form.  A loaded legacy record keeps the exact
    # set of causal extension keys it carried so its content digest remains stable.
    _wire_causal_fields: frozenset[str] | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _id(self.memory_id, name="memory_id")
        _text(self.problem_family, name="problem_family", maximum=256)
        _text(self.trigger, name="trigger")
        _text(self.strategy, name="strategy")
        _text(self.expected_result, name="expected_result")
        _text(self.failure_boundary, name="failure_boundary")
        for value, name in (
            (self.condition, "condition"), (self.action, "action"),
            (self.observed_result, "observed_result"), (self.applicability, "applicability"),
        ):
            if value is not None:
                _text(value, name=name)
        if self.condition is None:
            object.__setattr__(self, "condition", self.trigger)
        if self.action is None:
            object.__setattr__(self, "action", self.strategy)
        if self.observed_result is None:
            object.__setattr__(self, "observed_result", self.expected_result)
        if self.applicability is None:
            object.__setattr__(self, "applicability", self.failure_boundary)
        if type(self.compatible_contracts) is not tuple or len(self.compatible_contracts) > 32:
            _fail("rsi_compatible_contracts_invalid")
        for contract_digest in self.compatible_contracts:
            _digest(contract_digest, name="compatible_contract_sha256")
        if type(self.compatible_solvers) is not tuple or not self.compatible_solvers or len(self.compatible_solvers) > 32:
            _fail("rsi_compatible_solvers_invalid")
        for solver in self.compatible_solvers:
            _id(solver, name="solver_id")
        if type(self.verifier_outcome) is not str or self.verifier_outcome not in {"pass", "fail", "unresolved"}:
            _fail("rsi_verifier_outcome_invalid")
        _digest(self.receipt_sha256, name="receipt_sha256")
        _id(self.episode_id, name="episode_id")
        if type(self.status) is not str or self.status not in {"approved", "rejected", "unresolved"}:
            _fail("rsi_memory_status_invalid")
        if self.status == "approved" and self.verifier_outcome != "pass":
            _fail("rsi_approved_memory_unverified")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "memory_id": self.memory_id,
            "problem_family": self.problem_family,
            "trigger": self.trigger,
            "strategy": self.strategy,
            "expected_result": self.expected_result,
            "failure_boundary": self.failure_boundary,
            "compatible_contracts": list(self.compatible_contracts),
            "compatible_solvers": list(self.compatible_solvers),
            "verifier_outcome": self.verifier_outcome,
            "receipt_sha256": self.receipt_sha256,
            "episode_id": self.episode_id,
            "status": self.status,
        }
        causal_fields = self._wire_causal_fields
        if causal_fields is None:
            causal_fields = {"condition", "action", "observed_result", "applicability"}
        for name in causal_fields:
            payload[name] = getattr(self, name)
        return payload

    @classmethod
    def from_dict(cls, value: object) -> MemoryItem:
        item = _object(
            value,
            allowed={
                "memory_id", "problem_family", "trigger", "strategy", "expected_result",
                "failure_boundary", "compatible_contracts",
                "compatible_solvers", "verifier_outcome", "receipt_sha256", "episode_id", "status",
                "condition", "action", "observed_result", "applicability",
            },
            required={
                "memory_id", "problem_family", "trigger", "strategy", "expected_result",
                "failure_boundary", "compatible_contracts",
                "compatible_solvers", "verifier_outcome", "receipt_sha256", "episode_id", "status",
            },
        )
        contracts = item["compatible_contracts"]
        solvers = item["compatible_solvers"]
        if not isinstance(contracts, list) or any(type(digest) is not str for digest in contracts):
            _fail("rsi_compatible_contracts_invalid")
        if not isinstance(solvers, list) or any(type(solver) is not str for solver in solvers):
            _fail("rsi_compatible_solvers_invalid")
        result = cls(
            item["memory_id"], item["problem_family"], item["trigger"], item["strategy"],
            item["expected_result"], item["failure_boundary"], tuple(contracts), tuple(solvers), item["verifier_outcome"],
            item["receipt_sha256"], item["episode_id"], item["status"], item.get("condition"), item.get("action"),
            item.get("observed_result"), item.get("applicability"),
        )
        object.__setattr__(
            result,
            "_wire_causal_fields",
            frozenset(item) & {"condition", "action", "observed_result", "applicability"},
        )
        return result


@dataclass(frozen=True)
class MemorySnapshot:
    """A frozen set of approved items consumed by one solve/search phase."""

    snapshot_id: str
    parent_snapshot_sha256: str | None
    items: tuple[MemoryItem, ...]

    def __post_init__(self) -> None:
        _id(self.snapshot_id, name="snapshot_id")
        _optional_digest(self.parent_snapshot_sha256, name="parent_snapshot_sha256")
        if type(self.items) is not tuple or any(not isinstance(item, MemoryItem) for item in self.items):
            _fail("rsi_memory_snapshot_invalid")
        if len(self.items) > MAX_MEMORY_ENTRIES:
            _fail("rsi_memory_snapshot_too_large")
        if len({item.memory_id for item in self.items}) != len(self.items):
            _fail("rsi_memory_duplicate_item")
        if any(item.status != "approved" for item in self.items):
            _fail("rsi_memory_snapshot_unapproved")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": RSI_PROTOCOL,
            "schema_version": RSI_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "parent_snapshot_sha256": self.parent_snapshot_sha256,
            "items": [item.to_dict() for item in self.items],
        }

    def digest(self) -> str:
        return _sha256(self.to_dict())

    def to_bytes(self) -> bytes:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> MemorySnapshot:
        item = _object(
            value,
            allowed={"protocol", "schema_version", "snapshot_id", "parent_snapshot_sha256", "items"},
            required={"protocol", "schema_version", "snapshot_id", "parent_snapshot_sha256", "items"},
        )
        if item["protocol"] != RSI_PROTOCOL or item["schema_version"] != RSI_SCHEMA_VERSION:
            _fail("rsi_memory_snapshot_protocol_invalid")
        raw_items = item["items"]
        if not isinstance(raw_items, list):
            _fail("rsi_memory_snapshot_invalid")
        return cls(
            item["snapshot_id"], item["parent_snapshot_sha256"],
            tuple(MemoryItem.from_dict(entry) for entry in raw_items),
        )


EMPTY_MEMORY_SNAPSHOT = MemorySnapshot("rsi-empty-memory-v1", None, ())
EMPTY_MEMORY_SNAPSHOT_SHA256 = EMPTY_MEMORY_SNAPSHOT.digest()


@dataclass(frozen=True)
class VerifierCheck:
    name: str
    outcome: VerifierOutcome
    receipt_sha256: str

    def __post_init__(self) -> None:
        _id(self.name, name="verifier_check_name")
        if type(self.outcome) is not str or self.outcome not in {"pass", "fail", "unresolved"}:
            _fail("rsi_verifier_outcome_invalid")
        _digest(self.receipt_sha256, name="receipt_sha256")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "outcome": self.outcome, "receipt_sha256": self.receipt_sha256}


def load_memory_snapshot(source: bytes | str | Path | Mapping[str, Any]) -> MemorySnapshot:
    """Load one snapshot read-only and require canonical bytes when a serialized source is used."""
    if isinstance(source, Mapping):
        return MemorySnapshot.from_dict(dict(source))
    if isinstance(source, Path):
        try:
            content = source.read_bytes()
        except OSError as exc:
            raise RSILearningError("rsi_memory_snapshot_unreadable") from exc
    elif isinstance(source, str):
        try:
            content = source.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise RSILearningError("rsi_memory_snapshot_invalid") from exc
    elif isinstance(source, bytes):
        content = source
    else:
        _fail("rsi_memory_snapshot_source_invalid")
    if len(content) > MAX_RSI_RECORD_BYTES:
        _fail("rsi_memory_snapshot_too_large")
    try:
        value = strict_json(content, maximum=MAX_RSI_RECORD_BYTES)
    except Exception as exc:
        raise RSILearningError("rsi_memory_snapshot_invalid") from exc
    try:
        snapshot = MemorySnapshot.from_dict(value)
    except RSILearningError as exc:
        raise RSILearningError("rsi_memory_snapshot_invalid") from exc
    if _canonical(snapshot.to_dict()) != content:
        _fail("rsi_memory_snapshot_noncanonical")
    return snapshot


@dataclass(frozen=True)
class VerifierDecision:
    episode_id: str
    outcome: VerifierOutcome
    receipt_sha256: str
    diagnosis: str
    verifier_fingerprint: str
    checks: tuple[VerifierCheck, ...]
    independent_of_actor: bool = True
    contract_sha256: str | None = None
    evaluator_sha256: str | None = None
    environment_sha256: str | None = None
    official_evaluation_receipt_sha256: str | None = None
    evidence_sha256: str | None = None
    candidate_receipt_sha256: str | None = None
    execution_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        _id(self.episode_id, name="episode_id")
        if type(self.outcome) is not str or self.outcome not in {"pass", "fail", "unresolved"}:
            _fail("rsi_verifier_outcome_invalid")
        _digest(self.receipt_sha256, name="receipt_sha256")
        _text(self.diagnosis, name="diagnosis")
        _digest(self.verifier_fingerprint, name="verifier_fingerprint")
        if type(self.checks) is not tuple or not self.checks or any(
            not isinstance(check, VerifierCheck) for check in self.checks
        ):
            _fail("rsi_verifier_checks_invalid")
        if type(self.independent_of_actor) is not bool:
            _fail("rsi_verifier_independence_invalid")
        for value, name in (
            (self.contract_sha256, "contract_sha256"),
            (self.evaluator_sha256, "evaluator_sha256"),
            (self.environment_sha256, "environment_sha256"),
            (self.official_evaluation_receipt_sha256, "official_evaluation_receipt_sha256"),
            (self.evidence_sha256, "evidence_sha256"),
            (self.candidate_receipt_sha256, "candidate_receipt_sha256"),
            (self.execution_receipt_sha256, "execution_receipt_sha256"),
        ):
            _optional_digest(value, name=name)
        if self.outcome == "pass" and (
            not self.independent_of_actor
            or any(check.outcome != "pass" for check in self.checks)
        ):
            _fail("rsi_verifier_pass_not_independent")

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "outcome": self.outcome,
            "receipt_sha256": self.receipt_sha256,
            "diagnosis": self.diagnosis,
            "verifier_fingerprint": self.verifier_fingerprint,
            "checks": [check.to_dict() for check in self.checks],
            "independent_of_actor": self.independent_of_actor,
            "contract_sha256": self.contract_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
            "official_evaluation_receipt_sha256": self.official_evaluation_receipt_sha256,
            "evidence_sha256": self.evidence_sha256,
            "candidate_receipt_sha256": self.candidate_receipt_sha256,
            "execution_receipt_sha256": self.execution_receipt_sha256,
        }


@dataclass(frozen=True)
class PracticeEpisode:
    """Frozen identity for one curriculum practice attempt."""

    episode_id: str
    run_id: str
    contract_sha256: str
    evaluator_sha256: str
    environment_sha256: str
    memory_snapshot_sha256: str
    solver_id: str
    status: EpisodeStatus
    verifier: VerifierDecision | None = None
    episode_kind: Literal["practice", "target"] = "practice"
    wave: int = 0
    ordinal: int = 0
    parent_target_episode_id: str | None = None
    request_sha256: str | None = None
    trace_digest: str | None = None
    candidate_receipt_sha256: str | None = None
    execution_receipt_sha256: str | None = None
    official_evaluation_receipt_sha256: str | None = None
    terminal_reason: str | None = None
    previous_record_sha256: str | None = None
    actor_fingerprint: str | None = None
    solver_fingerprint: str | None = None
    candidate_source_sha256: str | None = None
    dependency_sha256: str | None = None
    trace_events: tuple[TraceEvent, ...] = ()
    # ``None`` denotes the current wire form.  Legacy records omit these fields; retaining
    # their presence set allows exact canonical roundtrip without weakening hash checks.
    _wire_extension_fields: frozenset[str] | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for value, name in ((self.episode_id, "episode_id"), (self.run_id, "run_id"), (self.solver_id, "solver_id")):
            _id(value, name=name)
        for value, name in (
            (self.contract_sha256, "contract_sha256"), (self.evaluator_sha256, "evaluator_sha256"),
            (self.environment_sha256, "environment_sha256"),
            (self.memory_snapshot_sha256, "memory_snapshot_sha256"),
        ):
            _digest(value, name=name)
        if type(self.status) is not str or self.status not in {
            "planned", "running", "completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"
        }:
            _fail("rsi_episode_status_invalid")
        if self.verifier is not None and self.verifier.episode_id != self.episode_id:
            _fail("rsi_verifier_episode_mismatch")
        if self.verifier is not None and self.status == "completed":
            for name in ("candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256"):
                if getattr(self, name) is None and getattr(self.verifier, name) is not None:
                    object.__setattr__(self, name, getattr(self.verifier, name))
        if self.status != "completed" and self.verifier is not None and self.verifier.outcome == "pass":
            _fail("rsi_incomplete_episode_verified")
        if self.episode_kind not in {"practice", "target"}:
            _fail("rsi_episode_kind_invalid")
        if type(self.wave) is not int or self.wave < 0:
            _fail("rsi_episode_wave_invalid")
        if type(self.ordinal) is not int or self.ordinal < 0:
            _fail("rsi_episode_ordinal_invalid")
        if self.parent_target_episode_id is not None:
            _id(self.parent_target_episode_id, name="parent_target_episode_id")
        for value, name in (
            (self.request_sha256, "request_sha256"),
            (self.trace_digest, "trace_digest"),
            (self.candidate_receipt_sha256, "candidate_receipt_sha256"),
            (self.execution_receipt_sha256, "execution_receipt_sha256"),
            (self.official_evaluation_receipt_sha256, "official_evaluation_receipt_sha256"),
            (self.previous_record_sha256, "previous_record_sha256"),
            (self.actor_fingerprint, "actor_fingerprint"),
            (self.solver_fingerprint, "solver_fingerprint"),
            (self.candidate_source_sha256, "candidate_source_sha256"),
            (self.dependency_sha256, "dependency_sha256"),
        ):
            _optional_digest(value, name=name)
        if type(self.trace_events) is not tuple or len(self.trace_events) > MAX_TRACE_EVENTS or any(
            not isinstance(event, TraceEvent) for event in self.trace_events
        ):
            _fail("rsi_trace_events_invalid")
        if self.terminal_reason is not None:
            _text(self.terminal_reason, name="terminal_reason")
        if self.status == "completed" and self.verifier is not None:
            if (
                self.verifier.contract_sha256 is not None
                and self.verifier.contract_sha256 != self.contract_sha256
            ):
                _fail("rsi_verifier_contract_mismatch")
            if (
                self.verifier.evaluator_sha256 is not None
                and self.verifier.evaluator_sha256 != self.evaluator_sha256
            ):
                _fail("rsi_verifier_evaluator_mismatch")
            if (
                self.verifier.environment_sha256 is not None
                and self.verifier.environment_sha256 != self.environment_sha256
            ):
                _fail("rsi_verifier_environment_mismatch")
            if (
                self.official_evaluation_receipt_sha256 is not None
                and self.verifier.official_evaluation_receipt_sha256 is not None
                and self.official_evaluation_receipt_sha256
                != self.verifier.official_evaluation_receipt_sha256
            ):
                _fail("rsi_verifier_receipt_mismatch")

    def _record_payload(self) -> dict[str, Any]:
        """Return the hash-covered record without its self-referential digest."""
        payload = {
            "protocol": RSI_PROTOCOL,
            "schema_version": RSI_SCHEMA_VERSION,
            "kind": "rsi_episode",
            "episode_kind": self.episode_kind,
            "episode_id": self.episode_id,
            "run_id": self.run_id,
            "status": self.status,
            "contract_sha256": self.contract_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "solver_id": self.solver_id,
            "wave": self.wave,
            "ordinal": self.ordinal,
            "parent_target_episode_id": self.parent_target_episode_id,
            "request_sha256": self.request_sha256,
            "candidate_receipt_sha256": self.candidate_receipt_sha256,
            "execution_receipt_sha256": self.execution_receipt_sha256,
            "official_evaluation_receipt_sha256": self.official_evaluation_receipt_sha256,
            "trace_digest": self.trace_digest,
            "verifier": self.verifier.to_dict() if self.verifier is not None else None,
            "terminal_reason": self.terminal_reason,
            "previous_record_sha256": self.previous_record_sha256,
        }
        extension_fields = self._wire_extension_fields
        if extension_fields is None:
            extension_fields = {
                "actor_fingerprint", "solver_fingerprint", "candidate_source_sha256",
                "dependency_sha256", "trace_events",
            }
        for name in extension_fields:
            value = getattr(self, name)
            payload[name] = [event.to_dict() for event in value] if name == "trace_events" else value
        return payload

    def _validate_durable_state(self) -> None:
        """Reject records that cannot be safely resumed or admitted to memory."""
        terminal = {"failed", "timed_out", "abandoned", "cancelled", "unknown"}
        receipts = (
            self.candidate_receipt_sha256,
            self.execution_receipt_sha256,
            self.official_evaluation_receipt_sha256,
            self.trace_digest,
        )
        if self.status == "planned":
            if self.request_sha256 is not None or any(value is not None for value in receipts):
                _fail("rsi_planned_evidence_invalid")
            if self.verifier is not None or self.terminal_reason is not None:
                _fail("rsi_planned_evidence_invalid")
            return
        if self.status == "running":
            if self.request_sha256 is None:
                _fail("rsi_episode_request_missing")
            if any(value is not None for value in receipts) or self.verifier is not None:
                _fail("rsi_running_evidence_invalid")
            if self.terminal_reason is not None:
                _fail("rsi_running_terminal_reason_invalid")
            return
        if self.status == "completed":
            if self.request_sha256 is None:
                _fail("rsi_episode_request_missing")
            if any(value is None for value in receipts):
                _fail("rsi_completed_evidence_missing")
            if self.terminal_reason is not None:
                _fail("rsi_completed_terminal_reason_invalid")
            if self.verifier is not None and self.verifier.outcome == "pass":
                official = [
                    check for check in self.verifier.checks if check.name == "official_evaluator"
                ]
                if len(official) != 1 or official[0].outcome != "pass":
                    _fail("rsi_verifier_official_check_invalid")
                if official[0].receipt_sha256 != self.official_evaluation_receipt_sha256:
                    _fail("rsi_verifier_receipt_mismatch")
            return
        if self.status in terminal:
            if self.request_sha256 is None:
                _fail("rsi_episode_request_missing")
            if self.verifier is not None:
                _fail("rsi_terminal_verifier_invalid")
            if self.terminal_reason is None:
                _fail("rsi_terminal_reason_missing")
            return
        _fail("rsi_episode_status_invalid")

    def to_record_dict(self) -> dict[str, Any]:
        """Return the validated canonical durable representation."""
        self._validate_durable_state()
        payload = self._record_payload()
        payload["record_sha256"] = _sha256(payload)
        return payload

    def digest(self) -> str:
        """Return the content digest used as the parent of the next record."""
        return _sha256(self._record_payload())

    @property
    def record_sha256(self) -> str:
        return self.digest()

    def to_bytes(self) -> bytes:
        return _canonical(self.to_record_dict())

    @classmethod
    def from_dict(cls, value: object) -> PracticeEpisode:
        item = _object(
            value,
            allowed={
                "protocol", "schema_version", "kind", "episode_kind", "episode_id", "run_id", "status",
                "contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256",
                "solver_id", "wave", "ordinal", "parent_target_episode_id", "request_sha256",
                "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256",
                "trace_digest", "verifier", "terminal_reason", "previous_record_sha256", "record_sha256",
                "actor_fingerprint", "solver_fingerprint", "candidate_source_sha256", "dependency_sha256", "trace_events",
            },
            required={
                "protocol", "schema_version", "kind", "episode_kind", "episode_id", "run_id", "status",
                "contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256",
                "solver_id", "wave", "ordinal", "parent_target_episode_id", "request_sha256",
                "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256",
                "trace_digest", "verifier", "terminal_reason", "previous_record_sha256", "record_sha256",
            },
        )
        if item["protocol"] != RSI_PROTOCOL or item["schema_version"] != RSI_SCHEMA_VERSION or item["kind"] != "rsi_episode":
            _fail("rsi_episode_protocol_invalid")
        raw_verifier = item["verifier"]
        verifier = None
        if raw_verifier is not None:
            verifier_item = _object(
                raw_verifier,
                allowed={
                    "episode_id", "outcome", "receipt_sha256", "diagnosis", "verifier_fingerprint", "checks",
                    "independent_of_actor", "contract_sha256", "evaluator_sha256", "environment_sha256",
                    "official_evaluation_receipt_sha256", "evidence_sha256",
                    "candidate_receipt_sha256", "execution_receipt_sha256",
                },
                required={
                    "episode_id", "outcome", "receipt_sha256", "diagnosis", "verifier_fingerprint", "checks",
                    "independent_of_actor", "contract_sha256", "evaluator_sha256", "environment_sha256",
                    "official_evaluation_receipt_sha256", "evidence_sha256",
                    "candidate_receipt_sha256", "execution_receipt_sha256",
                },
            )
            raw_checks = verifier_item["checks"]
            if not isinstance(raw_checks, list):
                _fail("rsi_verifier_checks_invalid")
            checks = []
            for raw_check in raw_checks:
                check = _object(raw_check, allowed={"name", "outcome", "receipt_sha256"}, required={"name", "outcome", "receipt_sha256"})
                checks.append(VerifierCheck(check["name"], check["outcome"], check["receipt_sha256"]))
            verifier = VerifierDecision(
                verifier_item["episode_id"], verifier_item["outcome"], verifier_item["receipt_sha256"],
                verifier_item["diagnosis"], verifier_item["verifier_fingerprint"], tuple(checks),
                verifier_item["independent_of_actor"], verifier_item["contract_sha256"],
                verifier_item["evaluator_sha256"], verifier_item["environment_sha256"],
                verifier_item["official_evaluation_receipt_sha256"], verifier_item["evidence_sha256"],
                verifier_item["candidate_receipt_sha256"], verifier_item["execution_receipt_sha256"],
            )
        episode = cls(
            item["episode_id"], item["run_id"], item["contract_sha256"], item["evaluator_sha256"],
            item["environment_sha256"], item["memory_snapshot_sha256"], item["solver_id"], item["status"],
            verifier, item["episode_kind"], item["wave"], item["ordinal"], item["parent_target_episode_id"],
            item["request_sha256"], item["trace_digest"], item["candidate_receipt_sha256"],
            item["execution_receipt_sha256"], item["official_evaluation_receipt_sha256"], item["terminal_reason"],
            item["previous_record_sha256"], item.get("actor_fingerprint"), item.get("solver_fingerprint"),
            item.get("candidate_source_sha256"), item.get("dependency_sha256"),
            tuple(
                TraceEvent(event["sequence"], event["kind"], event["name"], event["payload_sha256"], event.get("observation_sha256"))
                for event in item.get("trace_events", [])
            ) if isinstance(item.get("trace_events", []), list) else _fail("rsi_trace_events_invalid"),
        )
        object.__setattr__(
            episode,
            "_wire_extension_fields",
            frozenset(item) & {
                "actor_fingerprint", "solver_fingerprint", "candidate_source_sha256",
                "dependency_sha256", "trace_events",
            },
        )
        episode._validate_durable_state()
        if item["record_sha256"] != episode.digest():
            _fail("rsi_episode_record_digest_mismatch")
        return episode

    def transition(self, status: EpisodeStatus, **evidence: object) -> PracticeEpisode:
        valid_keys = {
            "request_sha256", "candidate_receipt_sha256", "execution_receipt_sha256",
            "official_evaluation_receipt_sha256", "trace_digest", "terminal_reason",
            "actor_fingerprint", "solver_fingerprint", "candidate_source_sha256", "dependency_sha256", "trace_events",
        }
        if set(evidence) - valid_keys:
            _fail("rsi_episode_transition_evidence_invalid")
        request_sha256 = evidence.get("request_sha256", self.request_sha256)
        if self.request_sha256 is not None and request_sha256 != self.request_sha256:
            _fail("rsi_episode_request_changed")
        allowed = {
            "planned": {"running"},
            "running": {"completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"},
        }
        if status not in allowed.get(self.status, set()):
            _fail("rsi_episode_state_transition_invalid")
        if status == "completed" and any(
            evidence.get(name, getattr(self, name)) is None
            for name in (
                "candidate_receipt_sha256",
                "execution_receipt_sha256",
                "official_evaluation_receipt_sha256",
                "trace_digest",
            )
        ):
            _fail("rsi_completed_evidence_missing")
        next_episode = replace(
            self,
            status=status,
            request_sha256=request_sha256,
            candidate_receipt_sha256=evidence.get("candidate_receipt_sha256", self.candidate_receipt_sha256),
            execution_receipt_sha256=evidence.get("execution_receipt_sha256", self.execution_receipt_sha256),
            official_evaluation_receipt_sha256=evidence.get("official_evaluation_receipt_sha256", self.official_evaluation_receipt_sha256),
            trace_digest=evidence.get("trace_digest", self.trace_digest),
            terminal_reason=evidence.get("terminal_reason", self.terminal_reason),
            actor_fingerprint=evidence.get("actor_fingerprint", self.actor_fingerprint),
            solver_fingerprint=evidence.get("solver_fingerprint", self.solver_fingerprint),
            candidate_source_sha256=evidence.get("candidate_source_sha256", self.candidate_source_sha256),
            dependency_sha256=evidence.get("dependency_sha256", self.dependency_sha256),
            trace_events=evidence.get("trace_events", self.trace_events),
            previous_record_sha256=self.digest(),
        )
        # A transition writes the current complete representation, even when its parent was
        # loaded from a legacy record.
        object.__setattr__(next_episode, "_wire_extension_fields", None)
        next_episode._validate_durable_state()
        return next_episode

    def attach_verifier(self, verifier: VerifierDecision) -> PracticeEpisode:
        if self.status != "completed" or self.verifier is not None:
            _fail("rsi_verifier_attach_invalid")
        if verifier.episode_id != self.episode_id:
            _fail("rsi_verifier_episode_mismatch")
        next_episode = replace(self, verifier=verifier, previous_record_sha256=self.digest())
        object.__setattr__(next_episode, "_wire_extension_fields", None)
        next_episode._validate_durable_state()
        return next_episode

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "protocol": RSI_PROTOCOL,
            "schema_version": RSI_SCHEMA_VERSION,
            "episode_id": self.episode_id,
            "run_id": self.run_id,
            "contract_sha256": self.contract_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "solver_id": self.solver_id,
            "status": self.status,
            "verifier": self.verifier.to_dict() if self.verifier is not None else None,
            "episode_kind": self.episode_kind,
            "wave": self.wave,
            "ordinal": self.ordinal,
            "parent_target_episode_id": self.parent_target_episode_id,
            "request_sha256": self.request_sha256,
            "trace_digest": self.trace_digest,
            "candidate_receipt_sha256": self.candidate_receipt_sha256,
            "execution_receipt_sha256": self.execution_receipt_sha256,
            "official_evaluation_receipt_sha256": self.official_evaluation_receipt_sha256,
            "terminal_reason": self.terminal_reason,
            "previous_record_sha256": self.previous_record_sha256,
        }
        extension_fields = self._wire_extension_fields
        if extension_fields is None:
            extension_fields = {
                "actor_fingerprint", "solver_fingerprint", "candidate_source_sha256",
                "dependency_sha256", "trace_events",
            }
        for name in extension_fields:
            value = getattr(self, name)
            payload[name] = [event.to_dict() for event in value] if name == "trace_events" else value
        return payload


def load_episode_record(source: bytes | str | Path | Mapping[str, Any]) -> PracticeEpisode:
    """Load one canonical, content-addressed episode record."""
    if isinstance(source, Mapping):
        return PracticeEpisode.from_dict(dict(source))
    if isinstance(source, Path):
        try:
            content = source.read_bytes()
        except OSError as exc:
            raise RSILearningError("rsi_episode_record_unreadable") from exc
    elif isinstance(source, str):
        try:
            content = source.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise RSILearningError("rsi_episode_record_invalid") from exc
    elif isinstance(source, bytes):
        content = source
    else:
        _fail("rsi_episode_record_source_invalid")
    if len(content) > MAX_RSI_RECORD_BYTES:
        _fail("rsi_episode_record_too_large")
    try:
        value = strict_json(content, maximum=MAX_RSI_RECORD_BYTES)
    except Exception as exc:
        raise RSILearningError("rsi_episode_record_invalid") from exc
    episode = PracticeEpisode.from_dict(value)
    if _canonical(episode.to_record_dict()) != content:
        _fail("rsi_episode_record_noncanonical")
    return episode


@dataclass(frozen=True)
class TransferReceipt:
    """Official result of a solve with curriculum and memory writes disabled."""

    run_id: str
    target_id: str
    memory_snapshot_sha256: str
    evaluator_sha256: str
    solver_fingerprint: str
    status: TransferStatus
    official_evaluation_receipt_sha256: str

    def __post_init__(self) -> None:
        _id(self.run_id, name="run_id")
        _id(self.target_id, name="target_id")
        for value, name in (
            (self.memory_snapshot_sha256, "memory_snapshot_sha256"),
            (self.evaluator_sha256, "evaluator_sha256"),
            (self.solver_fingerprint, "solver_fingerprint"),
            (self.official_evaluation_receipt_sha256, "official_evaluation_receipt_sha256"),
        ):
            _digest(value, name=name)
        if type(self.status) is not str or self.status not in {"passed", "failed", "unknown"}:
            _fail("rsi_transfer_status_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": RSI_PROTOCOL,
            "schema_version": RSI_SCHEMA_VERSION,
            "run_id": self.run_id,
            "target_id": self.target_id,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "solver_fingerprint": self.solver_fingerprint,
            "status": self.status,
            "official_evaluation_receipt_sha256": self.official_evaluation_receipt_sha256,
            "curriculum_enabled": False,
            "memory_write_enabled": False,
        }


class ReadOnlyMemorySnapshot:
    """Small capability object passed to an Actor during one frozen solve phase.

    It intentionally exposes iteration and lookup only.  The controller must create a new
    ``MemorySnapshot`` and commit it after independent verification; an Actor cannot mutate the
    snapshot it used for a practice episode.
    """

    __slots__ = ("_by_id", "_snapshot")

    def __init__(self, snapshot: MemorySnapshot) -> None:
        if not isinstance(snapshot, MemorySnapshot):
            raise TypeError("snapshot must be a MemorySnapshot")
        object.__setattr__(self, "_snapshot", snapshot)
        object.__setattr__(
            self,
            "_by_id",
            MappingProxyType({item.memory_id: item for item in snapshot.items}),
        )

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("ReadOnlyMemorySnapshot is immutable")

    @property
    def snapshot_id(self) -> str:
        return self._snapshot.snapshot_id

    @property
    def digest(self) -> str:
        return self._snapshot.digest()

    @property
    def items(self) -> tuple[MemoryItem, ...]:
        return self._snapshot.items

    def __iter__(self):
        return iter(self._snapshot.items)

    def get(self, memory_id: str) -> MemoryItem | None:
        return self._by_id.get(memory_id)

    def to_dict(self) -> dict[str, Any]:
        return self._snapshot.to_dict()


__all__ = [
    "EMPTY_MEMORY_SNAPSHOT",
    "EMPTY_MEMORY_SNAPSHOT_SHA256",
    "RSI_PROTOCOL",
    "RSI_SCHEMA_VERSION",
    "EpisodeStatus",
    "MemoryItem",
    "MemorySnapshot",
    "MemoryStatus",
    "PracticeEpisode",
    "RSILearningError",
    "ReadOnlyMemorySnapshot",
    "TraceEvent",
    "TransferReceipt",
    "TransferStatus",
    "VerifierCheck",
    "VerifierOutcome",
    "load_episode_record",
    "load_memory_snapshot",
]
