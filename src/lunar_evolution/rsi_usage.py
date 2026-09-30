"""Provider-free RSI usage and cost accounting.

This module is deliberately independent from :class:`model_profile.UsageLedger`: the latter
charges one model profile in memory, while this ledger records append-only, durable evidence for
an RSI run, episode and adapter lifecycle stage.  Missing provider token/time data is represented
as unknown and never as zero.  Consequently a summary with unknown usage cannot authorize a
budget check (fail closed), although its request count and known counters remain auditable.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import RSILearningError

_SCHEMA = "1"
_UNSET = object()
_MAX_BYTES = 8 * 1024 * 1024
_MAX_ID_BYTES = 512
_MAX_STAGE_BYTES = 128


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    """Read one bounded regular file without following the final symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise RSIUsageError("rsi_usage_ledger_corrupt") from exc
    try:
        identity = os.fstat(fd)
        if not stat.S_ISREG(identity.st_mode) or identity.st_size < 0 or identity.st_size > _MAX_BYTES:
            raise RSIUsageError("rsi_usage_ledger_corrupt")
        data = os.read(fd, identity.st_size + 1)
        if len(data) != identity.st_size or os.read(fd, 1):
            raise RSIUsageError("rsi_usage_ledger_corrupt")
        return json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, RSIUsageError):
            raise
        raise RSIUsageError("rsi_usage_ledger_corrupt") from exc
    finally:
        os.close(fd)


class RSIUsageError(RSILearningError):
    """Stable fail-closed error for malformed or conflicting usage evidence."""


def _error(code: str) -> None:
    raise RSIUsageError(f"rsi_usage_{code}")


def _id(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or any(c in value for c in "\x00\r\n"):
        _error(f"{name}_invalid")
    if len(value.encode("utf-8")) > _MAX_ID_BYTES:
        _error(f"{name}_invalid")
    return value


def _stage(value: object) -> str:
    if type(value) is not str or not value.strip() or any(c in value for c in "\x00\r\n"):
        _error("adapter_stage_invalid")
    if len(value.encode("utf-8")) > _MAX_STAGE_BYTES:
        _error("adapter_stage_invalid")
    return value


def _nonnegative(value: object, name: str, *, optional: bool = True) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or value < 0:
        _error(f"{name}_invalid")
    return value


def _digest(value: object, name: str = "digest") -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _error(f"{name}_invalid")
    return value


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class UsagePricing:
    """Optional integer micro-USD estimates; no rates means cost remains unknown."""

    input_cost_per_1k_micros: int | None = None
    output_cost_per_1k_micros: int | None = None
    request_cost_micros: int | None = None

    def __post_init__(self) -> None:
        for name in ("input_cost_per_1k_micros", "output_cost_per_1k_micros", "request_cost_micros"):
            _nonnegative(getattr(self, name), name)
        if (self.input_cost_per_1k_micros is None) != (self.output_cost_per_1k_micros is None):
            _error("pricing_invalid")

    def to_dict(self) -> dict[str, int | None]:
        return {
            "input_cost_per_1k_micros": self.input_cost_per_1k_micros,
            "output_cost_per_1k_micros": self.output_cost_per_1k_micros,
            "request_cost_micros": self.request_cost_micros,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> UsagePricing:
        if not isinstance(value, Mapping) or set(value) != {
            "input_cost_per_1k_micros", "output_cost_per_1k_micros", "request_cost_micros"
        }:
            _error("pricing_invalid")
        try:
            return cls(**dict(value))
        except (TypeError, ValueError, RSIUsageError) as exc:
            if isinstance(exc, RSIUsageError):
                raise
            raise RSIUsageError("rsi_usage_pricing_invalid") from exc

    def estimate(self, receipt: UsageReceipt) -> int | None:
        """Estimate one receipt, returning unknown when any required input is unavailable."""
        input_rate, output_rate = self.input_cost_per_1k_micros, self.output_cost_per_1k_micros
        token_cost: int | None = None
        if input_rate is not None and output_rate is not None:
            if receipt.input_tokens is None or receipt.output_tokens is None:
                return None
            token_cost = ((receipt.input_tokens * input_rate + 999) // 1000
                          + (receipt.output_tokens * output_rate + 999) // 1000)
        request_cost = None if self.request_cost_micros is None else receipt.request_count * self.request_cost_micros
        if token_cost is None and request_cost is None:
            return None
        return (token_cost or 0) + (request_cost or 0)


@dataclass(frozen=True)
class UsageReceipt:
    """Immutable accounting observation for one adapter stage.

    Token and timing fields are nullable because a crashed or external worker may not return
    usage.  ``None`` means unknown and is preserved through aggregate summaries.
    """

    event_id: str
    run_id: str
    adapter_stage: str
    episode_id: str | None = None
    request_count: int = 1
    input_tokens: int | None = None
    output_tokens: int | None = None
    wall_time_ms: int | None = None
    cpu_time_ms: int | None = None
    estimated_cost_micros: int | None = None
    created_at: str = field(default_factory=_timestamp)

    def __post_init__(self) -> None:
        _id(self.event_id, "event_id")
        _id(self.run_id, "run_id")
        _stage(self.adapter_stage)
        if self.episode_id is not None:
            _id(self.episode_id, "episode_id")
        _nonnegative(self.request_count, "request_count", optional=False)
        if self.request_count < 1:
            _error("request_count_invalid")
        _nonnegative(self.input_tokens, "input_tokens")
        _nonnegative(self.output_tokens, "output_tokens")
        if (self.input_tokens is None) != (self.output_tokens is None):
            _error("token_unknown_partial")
        _nonnegative(self.wall_time_ms, "wall_time_ms")
        _nonnegative(self.cpu_time_ms, "cpu_time_ms")
        _nonnegative(self.estimated_cost_micros, "estimated_cost_micros")
        _id(self.created_at, "created_at")
        if self.input_tokens is not None and self.output_tokens is not None:
            # total_tokens is derived, avoiding a second inconsistent counter.
            object.__setattr__(self, "input_tokens", int(self.input_tokens))
            object.__setattr__(self, "output_tokens", int(self.output_tokens))

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "adapter_stage": self.adapter_stage,
            "request_count": self.request_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "wall_time_ms": self.wall_time_ms,
            "cpu_time_ms": self.cpu_time_ms,
            "estimated_cost_micros": self.estimated_cost_micros,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> UsageReceipt:
        if not isinstance(value, Mapping) or value.get("schema_version") != _SCHEMA:
            _error("receipt_invalid")
        allowed = set(cls.__dataclass_fields__) | {"schema_version", "total_tokens"}  # type: ignore[attr-defined]
        if set(value) != allowed:
            _error("receipt_invalid")
        total = value["total_tokens"]
        inputs, outputs = value["input_tokens"], value["output_tokens"]
        if type(total) is bool or (total is not None and type(total) is not int):
            _error("receipt_invalid")
        if (inputs is None) != (outputs is None):
            _error("receipt_invalid")
        if inputs is None:
            if total is not None:
                _error("receipt_invalid")
        elif total != inputs + outputs:
            _error("receipt_invalid")
        payload = dict(value)
        payload.pop("schema_version", None)
        payload.pop("total_tokens", None)
        try:
            return cls(**payload)
        except (TypeError, ValueError, RSIUsageError) as exc:
            if isinstance(exc, RSIUsageError):
                raise
            raise RSIUsageError("rsi_usage_receipt_invalid") from exc

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict(), maximum=64 * 1024)).hexdigest()


@dataclass(frozen=True)
class UsageSummary:
    run_id: str | None
    episode_id: str | None
    adapter_stage: str | None
    request_count: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    wall_time_ms: int | None
    cpu_time_ms: int | None
    estimated_cost_micros: int | None
    usage_complete: bool
    receipt_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "episode_id": self.episode_id, "adapter_stage": self.adapter_stage,
            "request_count": self.request_count, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens, "total_tokens": self.total_tokens,
            "wall_time_ms": self.wall_time_ms, "cpu_time_ms": self.cpu_time_ms,
            "estimated_cost_micros": self.estimated_cost_micros,
            "usage_complete": self.usage_complete, "receipt_count": self.receipt_count,
        }


@dataclass(frozen=True)
class _Record:
    revision: int
    parent_sha256: str | None
    receipt: UsageReceipt
    record_sha256: str


class UsageLedger:
    """Append-only JSON usage ledger with hash-chain and compare-and-swap append."""

    def __init__(self, path: str | Path, *, pricing: UsagePricing | None = None) -> None:
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()
        self._pricing = pricing
        self._records: list[_Record] = []
        self._load()

    @property
    def head_sha256(self) -> str | None:
        return self._records[-1].record_sha256 if self._records else None

    @property
    def pricing(self) -> UsagePricing:
        return self._pricing or UsagePricing()

    def _record_digest(self, revision: int, parent: str | None, receipt: UsageReceipt) -> str:
        return hashlib.sha256(canonical_json({
            "schema_version": _SCHEMA, "revision": revision, "parent_sha256": parent,
            "receipt": receipt.to_dict(),
        }, maximum=_MAX_BYTES)).hexdigest()

    def _state(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA,
            "pricing": self.pricing.to_dict(),
            "head_sha256": self.head_sha256,
            "records": [
                {"revision": record.revision, "parent_sha256": record.parent_sha256,
                 "receipt": record.receipt.to_dict(), "record_sha256": record.record_sha256}
                for record in self._records
            ],
        }

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = _read_json(self.path)
        allowed = {"schema_version", "pricing", "head_sha256", "records"}
        if (not isinstance(raw, dict) or set(raw) != allowed or raw.get("schema_version") != _SCHEMA
                or not isinstance(raw.get("records"), list)):
            _error("ledger_corrupt")
        persisted = UsagePricing.from_dict(raw.get("pricing", {}))
        if self._pricing is not None and self._pricing != persisted:
            _error("pricing_drift")
        self._pricing = persisted
        parent: str | None = None
        seen_events: set[str] = set()
        records: list[_Record] = []
        for revision, item in enumerate(raw["records"]):
            if (not isinstance(item, dict)
                    or set(item) != {"revision", "parent_sha256", "receipt", "record_sha256"}
                    or item.get("revision") != revision or item.get("parent_sha256") != parent):
                _error("ledger_corrupt")
            receipt = UsageReceipt.from_dict(item["receipt"])
            if receipt.event_id in seen_events:
                _error("ledger_corrupt")
            digest = self._record_digest(revision, parent, receipt)
            if item.get("record_sha256") != digest:
                _error("ledger_corrupt")
            records.append(_Record(revision, parent, receipt, digest))
            seen_events.add(receipt.event_id)
            parent = digest
        if raw.get("head_sha256") != parent:
            _error("ledger_corrupt")
        self._records = records

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            encoded = canonical_json(self._state(), maximum=_MAX_BYTES)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise RSIUsageError("rsi_usage_persist_failed") from exc
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise RSIUsageError("rsi_usage_persist_failed") from exc

    def append(self, receipt: UsageReceipt, *, expected_head_sha256: str | None | object = _UNSET) -> str:
        if not isinstance(receipt, UsageReceipt):
            _error("receipt_invalid")
        with self._lock:
            lock_path = self.path.with_suffix(self.path.suffix + ".lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                # Reload under the file lock so two processes cannot pass CAS against stale state.
                self._records = []
                self._pricing = self._pricing
                self._load()
                current = self.head_sha256
                expected = current if expected_head_sha256 is _UNSET else expected_head_sha256
                if expected != current:
                    # A missing expected head is an explicit CAS value, not an implicit append.
                    _error("cas_conflict")
                existing = next((record for record in self._records if record.receipt.event_id == receipt.event_id), None)
                if existing is not None:
                    if existing.receipt.digest() != receipt.digest():
                        _error("event_conflict")
                    return existing.record_sha256
                revision = len(self._records)
                digest = self._record_digest(revision, current, receipt)
                previous_records = self._records
                self._records = [*previous_records, _Record(revision, current, receipt, digest)]
                try:
                    self._write_locked()
                except Exception:
                    self._records = previous_records
                    raise
                return digest

    def record(self, *, event_id: str, run_id: str, adapter_stage: str, **kwargs: Any) -> str:
        return self.append(UsageReceipt(event_id=event_id, run_id=run_id, adapter_stage=adapter_stage, **kwargs), expected_head_sha256=self.head_sha256)

    def records(self) -> tuple[UsageReceipt, ...]:
        with self._lock:
            return tuple(record.receipt for record in self._records)

    @staticmethod
    def _sum(values: list[int | None]) -> tuple[int | None, bool]:
        if any(value is None for value in values):
            return None, False
        return sum(value for value in values if value is not None), True

    def summary(self, *, run_id: str | None = None, episode_id: str | None = None,
                adapter_stage: str | None = None) -> UsageSummary:
        if run_id is not None:
            _id(run_id, "run_id")
        if episode_id is not None:
            _id(episode_id, "episode_id")
        if adapter_stage is not None:
            _stage(adapter_stage)
        selected = [r.receipt for r in self._records if
                    (run_id is None or r.receipt.run_id == run_id) and
                    (episode_id is None or r.receipt.episode_id == episode_id) and
                    (adapter_stage is None or r.receipt.adapter_stage == adapter_stage)]
        requests = sum(item.request_count for item in selected)
        inputs, inputs_complete = self._sum([item.input_tokens for item in selected])
        outputs, outputs_complete = self._sum([item.output_tokens for item in selected])
        walls, wall_complete = self._sum([item.wall_time_ms for item in selected])
        cpus, cpu_complete = self._sum([item.cpu_time_ms for item in selected])
        costs: list[int | None] = []
        for item in selected:
            costs.append(item.estimated_cost_micros if item.estimated_cost_micros is not None
                         else self.pricing.estimate(item))
        estimated, cost_complete = self._sum(costs)
        complete = inputs_complete and outputs_complete and wall_complete and cpu_complete and cost_complete
        # Empty scopes are complete only for request/token accounting; timing/cost are unknown.
        if not selected:
            complete = True
        return UsageSummary(run_id, episode_id, adapter_stage, requests, inputs, outputs,
                            None if inputs is None or outputs is None else inputs + outputs,
                            walls, cpus, estimated, complete, len(selected))

    def budget_check(self, *, run_id: str | None = None, episode_id: str | None = None,
                     max_requests: int | None = None, max_total_tokens: int | None = None,
                     max_cost_micros: int | None = None, require_complete: bool = True) -> UsageSummary:
        summary = self.summary(run_id=run_id, episode_id=episode_id)
        if (require_complete and max_requests is None and max_total_tokens is None
                and max_cost_micros is None and not summary.usage_complete):
            _error("usage_unknown")
        for name, actual, limit in (("requests", summary.request_count, max_requests),
                                    ("total_tokens", summary.total_tokens, max_total_tokens),
                                    ("cost_micros", summary.estimated_cost_micros, max_cost_micros)):
            if limit is not None:
                _nonnegative(limit, f"max_{name}", optional=False)
                if actual is not None and actual > limit:
                    _error("budget_exhausted")
                if actual is None and require_complete:
                    _error("usage_unknown")
        return summary

    def state(self) -> dict[str, Any]:
        return json.loads(canonical_json(self._state(), maximum=_MAX_BYTES))


__all__ = ["RSIUsageError", "UsageLedger", "UsagePricing", "UsageReceipt", "UsageSummary"]
